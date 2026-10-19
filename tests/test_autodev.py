"""Tests for autodev.py, run as a subprocess the way the pipeline runs it.

Run: python3 -m unittest discover -s tests -v   (from the repo root)

GitHub is replaced by tests/fake_gh/gh, which plays back the responses a test
scripts in $FAKE_GH_RESPONSES. Each test builds a bare `origin` and a clone of
it in a temp dir.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "skills" / "auto-dev" / "scripts"
AUTODEV = SCRIPTS / "autodev.py"
FAKE_GH = Path(__file__).resolve().parent / "fake_gh"

BASE_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "test@example.com",
    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
}

GH_OK = [
    {"args": ["auth", "status"], "stdout": "Logged in\n"},
    {"args": ["repo", "view", "--json", "nameWithOwner"],
     "stdout": '{"nameWithOwner": "acme/app"}'},
    {"args": ["repo", "view", "--json", "defaultBranchRef"],
     "stdout": '{"defaultBranchRef": {"name": "main"}}'},
]

PROFILE = """\
stack: typescript
setup: ["echo ready > setup-ran.txt"]
gate:
  - { kind: test, command: "true", report: "TEST.md" }
worktree_files: [".env"]
"""


class RunCase(unittest.TestCase):
    """A bare origin, a clone of it in self.repo, and a fake gh on PATH."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.env = {**BASE_ENV,
                    "PATH": f"{FAKE_GH}{os.pathsep}{os.environ.get('PATH', '')}",
                    "FAKE_GH_RESPONSES": str(self.tmp / "gh.json"),
                    "FAKE_GH_LOG": str(self.tmp / "gh.log")}
        self.script_gh(GH_OK)
        origin = self.tmp / "origin.git"
        self.sh("git", "init", "-q", "--bare", "-b", "main", str(origin))
        seed = self.tmp / "seed"
        self.sh("git", "clone", "-q", str(origin), str(seed))
        (seed / ".gitignore").write_text(".env\nsetup-ran.txt\n")
        (seed / "app.ts").write_text("export const one = 1;\n")
        self.sh("git", "add", "-A", cwd=seed)
        self.sh("git", "commit", "-q", "-m", "init", cwd=seed)
        self.sh("git", "push", "-q", "origin", "main", cwd=seed)
        self.repo = self.tmp / "app"
        self.sh("git", "clone", "-q", str(origin), str(self.repo))
        (self.repo / ".env").write_text("SECRET=1\n")
        self.profile = self.tmp / "profile.yml"
        self.profile.write_text(PROFILE)
        self.worktree = self.tmp / "app-due-dates"
        self.dir = self.worktree / ".auto-dev"

    def sh(self, *cmd, cwd=None):
        return subprocess.run(cmd, cwd=cwd, env=self.env, capture_output=True,
                              text=True, check=True).stdout

    def script_gh(self, responses):
        (self.tmp / "gh.json").write_text(json.dumps(responses))

    def autodev(self, *args, cwd=None):
        return subprocess.run([sys.executable, str(AUTODEV), *map(str, args)],
                              capture_output=True, text=True, env=self.env,
                              cwd=cwd or self.tmp, check=False)

    def init(self, *extra, task="Add due dates to todos"):
        return self.autodev("init", "--repo", self.repo, "--slug", "due-dates",
                            "--task", task, "--profile", self.profile,
                            "--max-wait", "30", *extra)

    def state(self):
        return json.loads((self.dir / "state.json").read_text())

    def write_state(self, state):
        (self.dir / "state.json").write_text(json.dumps(state))


class InitTest(RunCase):
    def test_creates_worktree_state_and_runs_setup(self):
        r = self.init()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(f"INIT: {self.worktree}", r.stdout)
        state = self.state()
        self.assertEqual(state["schema"], 4)
        self.assertEqual(state["branch"], "feat/due-dates")
        self.assertEqual(state["phases"]["1"]["status"], "done")
        self.assertEqual(state["repo"]["staging"], None)
        self.assertEqual((self.worktree / ".env").read_text(), "SECRET=1\n")
        self.assertTrue((self.worktree / "setup-ran.txt").exists())
        self.assertIn("**Base:** main", (self.dir / "profile.md").read_text())
        # Nothing init wrote is visible to git.
        self.assertEqual(self.sh("git", "status", "--porcelain", cwd=self.worktree), "")

    def test_generated_ledger_still_reads_with_resume_point(self):
        self.assertEqual(self.init().returncode, 0)
        r = subprocess.run([sys.executable, str(SCRIPTS / "resume-point.py"), self.dir],
                           capture_output=True, text=True, check=False)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Phase:     2 — Define (status: pending)", r.stdout)

    def test_signed_out_gh_stops(self):
        self.script_gh([{"args": ["auth", "status"], "stderr": "not logged in",
                         "exit": 1}])
        r = self.init()
        self.assertEqual(r.returncode, 1)
        self.assertIn("not signed in", r.stderr)
        self.assertFalse(self.worktree.exists())

    def test_gate_without_tests_stops(self):
        (self.repo / ".auto-dev.yml").write_text(
            'setup: ["true"]\ngate:\n  - { kind: lint, command: "true", report: "LINT.md" }\n')
        r = self.autodev("init", "--repo", self.repo, "--slug", "due-dates",
                         "--task", "Add due dates")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("kind: test", r.stderr)
        self.assertFalse(self.worktree.exists())

    def test_unignored_worktree_file_stops(self):
        self.profile.write_text(PROFILE.replace('[".env"]', '["app.local"]'))
        (self.repo / "app.local").write_text("x")
        r = self.init()
        self.assertEqual(r.returncode, 1)
        self.assertIn("not gitignored", r.stderr)
        self.assertFalse((self.worktree / "app.local").exists())

    def test_override_wins_over_profile(self):
        (self.repo / ".auto-dev.yml").write_text("branches:\n  prefix: feature\n"
                                                 "iteration_budget: 2\n")
        r = self.init()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.state()["branch"], "feature/due-dates")
        self.assertEqual(self.state()["budget"]["total"], 2)

    def test_failed_setup_stops_and_continue_retries(self):
        self.profile.write_text(PROFILE.replace("echo ready > setup-ran.txt",
                                                "test -f fixed.flag"))
        r = self.init()
        self.assertEqual(r.returncode, 1)
        self.assertIn("exited 1", r.stderr)
        self.assertEqual(self.state()["phases"]["1"]["status"], "stopped")
        (self.worktree / "fixed.flag").write_text("")
        r = self.autodev("init", "--continue", self.worktree, "--max-wait", "30")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.state()["phases"]["1"]["status"], "done")

    def test_missing_setup_tool_is_reported(self):
        self.profile.write_text(PROFILE.replace("echo ready > setup-ran.txt",
                                                "no-such-tool-xyz install"))
        r = self.init()
        self.assertEqual(r.returncode, 1)
        self.assertIn("not found (exit 127)", r.stderr)

    def test_slow_setup_returns_3_then_continue_waits(self):
        self.profile.write_text(PROFILE.replace("echo ready > setup-ran.txt",
                                                "sleep 2"))
        r = self.autodev("init", "--repo", self.repo, "--slug", "due-dates",
                         "--task", "Add due dates", "--profile", self.profile,
                         "--max-wait", "0")
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertIn("SETUP-RUNNING", r.stdout)
        r = self.autodev("init", "--continue", self.worktree, "--max-wait", "30")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_bad_slug_cannot_run(self):
        r = self.autodev("init", "--repo", self.repo, "--slug", "Due Dates",
                         "--task", "x", "--profile", self.profile)
        self.assertEqual(r.returncode, 2)


class ResumeTest(RunCase):
    def resume(self, *extra):
        return self.autodev("resume", "--repo", self.repo, *extra)

    def test_no_runs_and_no_task_asks(self):
        r = self.resume()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(r.stdout.startswith("ASK"), r.stdout)

    def test_a_task_with_no_run_starts_fresh(self):
        self.assertEqual(self.init().returncode, 0)
        r = self.resume("--task", "Rename the settings page")
        self.assertTrue(r.stdout.startswith("FRESH"), r.stdout)

    def test_the_one_open_run_resumes(self):
        self.assertEqual(self.init().returncode, 0)
        for extra in ((), ("--task", "Add due dates to todos")):
            r = self.resume(*extra)
            self.assertTrue(r.stdout.startswith(f"RESUME: {self.worktree}"), r.stdout)
            self.assertIn("phase: 2 — Define", r.stdout)
            self.assertIn("session: S1 — Plan", r.stdout)

    def test_near_miss_asks(self):
        self.assertEqual(self.init().returncode, 0)
        r = self.resume("--task", "due dates")
        self.assertTrue(r.stdout.startswith("ASK"), r.stdout)

    def test_stopped_run_is_finished(self):
        self.assertEqual(self.init().returncode, 0)
        self.autodev("gate", "jira", "stop", "--dir", self.dir)
        r = self.resume("--task", "Add due dates to todos")
        self.assertTrue(r.stdout.startswith("FINISHED"), r.stdout)

    def test_3x_ledger_is_old_version(self):
        old = self.tmp / "app-old"
        self.sh("git", "worktree", "add", "-q", str(old), "-b", "feat/old", cwd=self.repo)
        (old / ".auto-dev").mkdir()
        (old / ".auto-dev" / "WORK_LOG.md").write_text(
            "# Work Log\n\n- **Task:** Fix the expiry message\n"
            "- **Ticket:** none — fix the expiry message\n\n## Phase status\n")
        r = self.resume()
        self.assertTrue(r.stdout.startswith(f"OLD-VERSION: {old}"), r.stdout)
        r = self.resume("--task", "Fix the expiry message")
        self.assertTrue(r.stdout.startswith("OLD-VERSION"), r.stdout)


class StateCommandsTest(RunCase):
    def setUp(self):
        super().setUp()
        self.assertEqual(self.init().returncode, 0)

    def cmd(self, *args):
        return self.autodev(*args, "--dir", self.dir)

    def test_budget_spends_once_per_id_and_refuses_at_zero(self):
        state = self.state()
        state["budget"].update(total=2, remaining=2)
        self.write_state(state)
        r = self.cmd("budget", "spend", "--consumer", "3", "--id", "p5-r1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("1 of 2 left", r.stdout)
        r = self.cmd("budget", "spend", "--consumer", "3", "--id", "p5-r1")
        self.assertIn("ALREADY-SPENT", r.stdout)
        self.assertEqual(self.state()["budget"]["remaining"], 1)
        self.assertEqual(self.cmd("budget", "spend", "--consumer", "3", "--id",
                                  "p5-r2").returncode, 0)
        r = self.cmd("budget", "spend", "--consumer", "4", "--id", "6a-r1")
        self.assertEqual(r.returncode, 3)
        self.assertIn("EXHAUSTED", r.stdout)
        self.assertIn("PR gate", r.stdout)  # consumer 4's own instruction
        self.assertEqual(self.state()["budget"]["remaining"], 0)
        self.assertIn("(0 remaining)", (self.dir / "WORK_LOG.md").read_text())

    def test_hold_and_stop_are_different_states(self):
        r = self.cmd("gate", "pr", "hold", "--reason", "waiting on design")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.state()["phases"]["6"]["status"], "held")
        self.assertIn("| 6 | Ship | blocked | held", (self.dir / "WORK_LOG.md").read_text())
        self.cmd("gate", "pr", "proceed")
        self.assertEqual(self.state()["phases"]["6"]["status"], "in-progress")
        self.cmd("gate", "main", "stop")
        self.assertEqual(self.state()["phases"]["6"]["status"], "stopped")

    def test_gate_refuses_a_choice_it_does_not_offer(self):
        r = self.cmd("gate", "pr", "skip")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.state()["gates"], [])

    def test_oversized_stops_the_run(self):
        r = self.cmd("size", "OVERSIZED", "--high-risk", "no")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("STOP: OVERSIZED", r.stdout)
        phases = self.state()["phases"]
        self.assertEqual(phases["2"], {"status": "stopped", "notes": "OVERSIZED"})
        self.assertEqual({phases[n]["status"] for n in "3456"}, {"n/a"})

    def test_high_risk_turns_on_the_post_plan_gate(self):
        self.cmd("size", "FITS", "--high-risk", "yes")
        self.assertTrue(self.state()["settings"]["post_plan_gate"])

    def test_handoff_names_the_next_session(self):
        for n in (2, 3):
            self.cmd("phase", str(n), "done")
        r = self.cmd("handoff", "--assumption", "dates are UTC")
        self.assertEqual(r.returncode, 0, r.stderr)
        text = (self.dir / "HANDOFF.md").read_text()
        self.assertIn(f"Re-enter with: `cd {self.worktree}`", text)
        self.assertIn("Phase 4 — Build", text)
        self.assertIn("- dates are UTC", text)
        self.assertIn("auto-dev continue", r.stdout)
        self.assertNotIn("opus", r.stdout + text)  # no model-switch advice

    def test_handoff_refuses_a_finished_run(self):
        for n in range(2, 7):
            self.cmd("phase", str(n), "done")
        self.assertEqual(self.cmd("handoff").returncode, 1)

    def test_json_output(self):
        r = self.cmd("show", "--json")
        self.assertEqual(json.loads(r.stdout)["result"], "STATE")


GOOD_BODY = """## Summary
Adds due dates.

## Acceptance conditions
Checked at commit {sha}: every result below was produced on this code.
- [x] **A todo can have a due date**

### Checks for a person
None: every requirement was checked automatically.

### Changes to tests
No existing test was deleted, skipped or weakened, and every new test checks something.

### Test strength
We put 3 small deliberate bugs into the changed code. They caught 3.

## Quality gate
- `npm test`: passed

## Review
- Code review (3 independent reviewers) — confidence High: all covered.

## Assumptions
none

Generated with [Claude Code](https://claude.com/claude-code)
"""


class ShipTest(RunCase):
    REPORTS = ("SPEC_EVAL.md", "lint/TEST.md", "CODE_REVIEW.md", "SECURITY_REVIEW.md")

    def setUp(self):
        super().setUp()
        self.assertEqual(self.init().returncode, 0)

    def cmd(self, *args):
        return self.autodev(*args, "--dir", self.dir)

    def git(self, *args):
        return self.sh("git", *args, cwd=self.worktree)

    def stamp(self):
        r = subprocess.run([sys.executable, str(SCRIPTS / "check-fresh.py"),
                            "--print-tree", self.worktree], capture_output=True,
                           text=True, check=True)
        for name in self.REPORTS:
            (self.dir / name).parent.mkdir(parents=True, exist_ok=True)
            (self.dir / name).write_text(f"# {name}\n\nTree: {r.stdout.strip()}\n")

    def change(self):
        (self.worktree / "app.ts").write_text("export const one = 2;\n")
        (self.worktree / "due.ts").write_text("export const due = 1;\n")

    def set_settings(self, **settings):
        state = self.state()
        state["settings"].update(settings)
        self.write_state(state)

    def hook(self, body):
        hooks = self.repo / ".git" / "hooks"
        hooks.mkdir(exist_ok=True)
        (hooks / "pre-commit").write_text(f"#!/bin/sh\n{body}\n")
        (hooks / "pre-commit").chmod(0o755)

    # commit
    def test_commit_stages_by_name_and_records_the_verified_commit(self):
        self.change()
        self.stamp()
        r = self.cmd("commit", "--message", "feat(todos): add due dates")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        head = self.git("rev-parse", "HEAD").strip()
        self.assertIn(f"COMMITTED: {head}", r.stdout)
        self.assertEqual(self.state()["phase6"]["verified_sha"], head)
        files = self.git("show", "--name-only", "--format=", "HEAD").split()
        self.assertEqual(sorted(files), ["app.ts", "due.ts"])
        self.assertIn("Co-Authored-By: Claude Code", self.git("log", "-1", "--format=%B"))

    def test_commit_refuses_stale_results_and_stages_nothing(self):
        self.change()
        self.stamp()
        (self.worktree / "app.ts").write_text("export const one = 3;\n")
        r = self.cmd("commit", "--message", "feat: x")
        self.assertEqual(r.returncode, 1)
        self.assertIn("STALE", r.stderr)
        self.assertEqual(self.git("diff", "--cached", "--name-only"), "")

    def test_failed_commit_unstages(self):
        self.change()
        self.stamp()
        self.hook("exit 1")
        r = self.cmd("commit", "--message", "feat: x")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("COMMIT-FAILED", r.stderr)
        self.assertEqual(self.git("diff", "--cached", "--name-only"), "")

    def test_commit_that_adds_unchecked_code_is_not_verified(self):
        self.change()
        self.stamp()
        self.hook("echo extra > extra.ts && git add extra.ts")
        r = self.cmd("commit", "--message", "feat: x")
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertIn("NOT-VERIFIED", r.stdout)
        self.assertNotIn("verified_sha", self.state()["phase6"])

    # ci-watch
    def watch(self, *extra):
        return self.cmd("ci-watch", "--pr", "7", "--interval", "1", *extra)

    def checks(self, checks=None, **response):
        self.script_gh([{"args": ["pr", "checks"],
                         "stdout": json.dumps(checks) if checks is not None else "",
                         **response}])

    def test_ci_none_skips_the_watch(self):
        r = self.watch()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("SKIPPED", r.stdout)

    def test_ci_green_red_and_pending(self):
        self.set_settings(ci="github-actions")
        self.checks([{"name": "test", "bucket": "pass", "state": "SUCCESS", "link": "l"}])
        self.assertEqual(self.watch().returncode, 0)
        self.checks([{"name": "test", "bucket": "fail", "state": "FAILURE",
                      "link": "https://ci/1"}])
        r = self.watch()
        self.assertEqual(r.returncode, 1)
        self.assertIn("test — https://ci/1", r.stdout)
        self.checks([{"name": "test", "bucket": "pending", "state": "PENDING", "link": ""}])
        r = self.watch("--max-wait", "0")
        self.assertEqual(r.returncode, 3)
        self.assertIn("PENDING", r.stdout)

    def test_ci_timeout_holds(self):
        self.set_settings(ci="github-actions", ci_timeout=0)
        self.checks([{"name": "test", "bucket": "pending", "state": "PENDING", "link": ""}])
        r = self.watch("--max-wait", "5")
        self.assertEqual(r.returncode, 3)
        self.assertIn("TIMEOUT", r.stdout)

    def test_no_checks_after_grace_is_unavailable(self):
        self.set_settings(ci="github-actions")
        self.checks(stderr="no checks reported on the 'feat/due-dates' branch", exit=1)
        r = self.watch("--max-wait", "0", "--grace", "300")
        self.assertEqual(r.returncode, 3)  # still inside the grace period
        r = self.watch("--max-wait", "0", "--grace", "0")
        self.assertEqual(r.returncode, 4)
        self.assertIn("UNAVAILABLE", r.stdout)

    # merge-staging
    def staging(self, content=None):
        self.git("push", "-q", "origin", "origin/main:refs/heads/staging")
        if content is not None:
            self.git("switch", "-q", "-c", "tmp", "origin/staging")
            (self.worktree / "app.ts").write_text(content)
            self.git("commit", "-q", "-am", "staging change")
            self.git("push", "-q", "origin", "HEAD:staging")
            self.git("switch", "-q", "feat/due-dates")
        state = self.state()
        state["repo"]["staging"] = "staging"
        self.write_state(state)
        (self.worktree / "app.ts").write_text("export const one = 2;\n")
        self.git("commit", "-q", "-am", "feat: change")

    def test_merge_staging_pushes_and_returns_to_the_branch(self):
        self.staging()
        r = self.cmd("merge-staging")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.git("branch", "--show-current").strip(), "feat/due-dates")
        self.git("fetch", "-q", "origin", "staging")
        self.assertIn("feat: change", self.git("log", "--format=%s", "origin/staging"))

    def test_merge_staging_conflict_aborts_and_returns(self):
        self.staging(content="export const one = 9;\n")
        r = self.cmd("merge-staging")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("CONFLICT", r.stderr)
        self.assertEqual(self.git("branch", "--show-current").strip(), "feat/due-dates")
        self.assertEqual(self.git("status", "--porcelain"), "")

    # merge-pr
    def merge(self, merge_response, state="MERGED"):
        self.script_gh([
            {"args": ["repo", "view"], "stdout": json.dumps(
                {"squashMergeAllowed": True, "mergeCommitAllowed": True,
                 "rebaseMergeAllowed": False})},
            {"args": ["pr", "merge"], **merge_response},
            {"args": ["pr", "view"], "stdout": json.dumps({"state": state})},
        ])
        return self.cmd("merge-pr", "--pr", "7", "--sha", "abc123")

    def gh_calls(self):
        return [json.loads(line)["args"] for line in
                (self.tmp / "gh.log").read_text().splitlines()]

    def test_merge_pr_locks_to_the_checked_commit(self):
        r = self.merge({"stdout": "merged"})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        call = next(c for c in self.gh_calls() if c[:2] == ["pr", "merge"])
        self.assertEqual(call, ["pr", "merge", "7", "--squash", "--match-head-commit",
                                "abc123"])
        self.assertFalse(any("--admin" in call for call in self.gh_calls()))

    def test_merge_pr_outcomes(self):
        r = self.merge({"stderr": "Head branch was modified. Review and try again.",
                        "exit": 1})
        self.assertEqual(r.returncode, 1)
        self.assertIn("HEAD-MOVED", r.stderr)
        r = self.merge({"stderr": "Pull request is not mergeable: review required",
                        "exit": 1})
        self.assertEqual(r.returncode, 4)
        r = self.merge({"stdout": "auto-merge enabled"}, state="OPEN")
        self.assertEqual(r.returncode, 3)
        self.assertIn("QUEUED", r.stdout)

    # pr-body --check
    def test_pr_body_lint(self):
        state = self.state()
        state["phase6"]["verified_sha"] = "a" * 40
        self.write_state(state)
        body = self.tmp / "body.md"
        body.write_text(GOOD_BODY.format(sha="a" * 40))
        r = self.cmd("pr-body", "--check", body)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        body.write_text(GOOD_BODY.format(sha="b" * 40).replace("### Test strength", "")
                        + f"See C2 in .auto-dev/SPEC.md, from {self.worktree}.\n"
                        + "token = ghp_" + "x" * 30 + "\n")
        r = self.cmd("pr-body", "--check", body)
        self.assertEqual(r.returncode, 1)
        for text in ("### Test strength", "not the verified commit", ".auto-dev/",
                     "C2", "worktree", "secret"):
            self.assertIn(text, r.stdout)

    # cleanup-worktree
    def test_cleanup_worktree(self):
        (self.worktree / "stray.txt").write_text("x")
        r = self.cmd("cleanup-worktree")
        self.assertEqual(r.returncode, 1)
        self.assertTrue(self.worktree.exists())
        (self.worktree / "stray.txt").unlink()
        r = self.cmd("cleanup-worktree")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(self.worktree.exists())


class CliTest(unittest.TestCase):
    def test_missing_state_cannot_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = subprocess.run([sys.executable, str(AUTODEV), "show", "--dir", tmp],
                               capture_output=True, text=True, check=False)
        self.assertEqual(r.returncode, 2)

    def test_bad_arguments_cannot_run(self):
        r = subprocess.run([sys.executable, str(AUTODEV), "phase", "9", "done"],
                           capture_output=True, text=True, check=False)
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
