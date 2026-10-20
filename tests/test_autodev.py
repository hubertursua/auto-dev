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

    def test_security_docs_are_found_without_being_named(self):
        seed = self.tmp / "seed"
        (seed / "docs" / "security").mkdir(parents=True)
        (seed / "SECURITY.md").write_text("# Security\n")
        (seed / "docs" / "security" / "authz.md").write_text("# Authz\n")
        self.sh("git", "add", "-A", cwd=seed)
        self.sh("git", "commit", "-q", "-m", "docs", cwd=seed)
        self.sh("git", "push", "-q", "origin", "main", cwd=seed)
        self.assertEqual(self.init().returncode, 0)
        profile = (self.dir / "profile.md").read_text()
        self.assertIn("**Security directives:** SECURITY.md, docs/security/authz.md",
                      profile)

    def test_security_docs_in_the_override_win(self):
        (self.repo / ".auto-dev.yml").write_text("security_docs: [docs/rules.md]\n")
        self.assertEqual(self.init().returncode, 0)
        self.assertIn("**Security directives:** docs/rules.md",
                      (self.dir / "profile.md").read_text())

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

    def fail_setup(self):
        self.profile.write_text(PROFILE.replace("echo ready > setup-ran.txt", "false"))
        r = self.init()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("exited 1", r.stderr)

    def cont(self, *extra, wait="30"):
        return self.autodev("init", "--continue", self.worktree, "--max-wait", wait,
                            *extra)

    def test_failed_setup_keeps_the_run_open_and_continue_retries(self):
        self.fail_setup()
        state = self.state()
        self.assertEqual(state["init"]["setup"], "failed")
        self.assertEqual(state["phases"]["1"]["status"], "held")
        r = self.autodev("resume", "--repo", self.repo)
        self.assertTrue(r.stdout.startswith(f"RESUME: {self.worktree}"), r.stdout)
        self.assertIn("phase: 1 — Setup", r.stdout)
        self.assertIn(f"init --continue {self.worktree}", r.stdout)
        self.profile.write_text(PROFILE)
        r = self.cont("--profile", self.profile)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.state()["phases"]["1"]["status"], "done")
        self.assertTrue((self.worktree / "setup-ran.txt").exists())

    def test_continue_reads_a_fixed_override(self):
        self.fail_setup()
        (self.repo / ".auto-dev.yml").write_text(
            'setup: ["echo ready > setup-ran.txt"]\n')
        r = self.cont()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.state()["settings"]["setup"],
                         ["echo ready > setup-ran.txt"])
        self.assertTrue((self.worktree / "setup-ran.txt").exists())
        profile_md = (self.dir / "profile.md").read_text()
        self.assertIn("1. `echo ready > setup-ran.txt`", profile_md)
        self.assertNotIn("`false`", profile_md)

    def test_dead_setup_runner_is_restarted(self):
        self.assertEqual(self.init().returncode, 0)
        gone = subprocess.Popen([sys.executable, "-c", "pass"])
        gone.wait()
        state = self.state()
        state["init"].update(setup="pending", setup_pid=gone.pid)
        state["phases"]["1"]["status"] = "in-progress"
        self.write_state(state)
        (self.dir / "setup.json").unlink()
        (self.worktree / "setup-ran.txt").unlink()
        r = self.cont(wait="5")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("setup runner stopped without a result", r.stderr)
        self.assertEqual(self.state()["init"]["setup"], "failed")
        r = self.cont()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((self.worktree / "setup-ran.txt").exists())

    def test_setup_runner_error_still_writes_a_result(self):
        self.assertEqual(self.init().returncode, 0)
        state = self.state()
        state["init"]["setup"] = "pending"
        state["settings"]["setup"] = 5  # not a list: the runner raises
        self.write_state(state)
        (self.dir / "setup.json").unlink()
        self.autodev("_run-setup", self.dir)
        result = json.loads((self.dir / "setup.json").read_text())
        self.assertEqual(result["status"], "failed")
        self.assertIn("TypeError", result["error"])
        r = self.cont(wait="5")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("setup runner failed", r.stderr)

    def test_same_slug_for_another_task_stops(self):
        self.assertEqual(self.init().returncode, 0)
        before = (self.dir / "state.json").read_text()
        r = self.init(task="Rename the settings page")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("slug due-dates is already used by another run", r.stderr)
        self.assertEqual((self.dir / "state.json").read_text(), before)
        self.assertEqual(self.init().returncode, 0)  # the same task reattaches

    def test_failure_after_worktree_add_removes_it(self):
        self.profile.write_text(PROFILE.replace('[".env"]', '["app.ts"]'))
        (self.repo / "app.ts").write_text("export const one = 2;\n")
        r = self.init()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("not gitignored", r.stderr)
        self.assertFalse(self.worktree.exists())
        self.assertEqual(self.sh("git", "branch", "--list", "feat/due-dates",
                                 cwd=self.repo), "")
        self.assertEqual((self.repo / "app.ts").read_text(), "export const one = 2;\n")
        self.profile.write_text(PROFILE)
        r = self.init()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual((self.worktree / "app.ts").read_text(),
                         "export const one = 1;\n")

    def test_staging_must_match_the_whole_branch_name(self):
        self.sh("git", "push", "-q", "origin", "main:release/staging", cwd=self.repo)
        r = self.init()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIsNone(self.state()["repo"]["staging"])
        self.assertIn("staging gate: n/a", self.state()["phases"]["6"]["notes"])

    def test_staging_branch_on_origin_is_used(self):
        self.sh("git", "push", "-q", "origin", "main:staging", cwd=self.repo)
        r = self.init()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.state()["repo"]["staging"], "staging")

    def test_worktree_path_taken_stops(self):
        self.worktree.mkdir()
        r = self.init()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("already exists", r.stderr)

    def test_no_profile_cannot_run(self):
        r = self.autodev("init", "--repo", self.repo, "--slug", "due-dates",
                         "--task", "Add due dates")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("no profile", r.stderr)
        self.assertFalse(self.worktree.exists())

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

    def test_unreadable_state_is_an_error(self):
        self.assertEqual(self.init().returncode, 0)
        (self.dir / "state.json").write_text("{")
        for extra in ((), ("--task", "Add due dates to todos")):
            r = self.resume(*extra)
            self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
            self.assertIn(f"ERROR: the run in {self.worktree} is unreadable", r.stderr)

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
        self.assertIn("every open must-fix finding by name", r.stdout)  # consumer 4
        self.assertEqual(self.state()["budget"]["remaining"], 0)
        self.assertIn("(0 remaining)", (self.dir / "WORK_LOG.md").read_text())

    def test_mark_records_a_triage_answer(self):
        r = self.cmd("mark", "triage-S2", "--value", "separate")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.state()["marks"]["triage-S2"]["value"], "separate")
        self.assertIn("triage, S2: separate", (self.dir / "WORK_LOG.md").read_text())
        self.assertEqual(self.cmd("mark", "triage-S2", "--value", "fix").returncode, 1)
        self.assertEqual(self.cmd("mark", "no-such-step").returncode, 1)

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
        self.assertIn("Task: Add due dates to todos", text)
        self.assertIn("Pick up at: say `auto-dev continue`; `next` decides the step", text)
        self.assertNotIn("start of Phase", text)

    def test_handoff_refuses_a_finished_run(self):
        for n in range(2, 7):
            self.cmd("phase", str(n), "done")
        self.assertEqual(self.cmd("handoff").returncode, 1)

    def test_state_that_is_not_an_object_cannot_run(self):
        for text in ("null", "[]", '"x"'):
            (self.dir / "state.json").write_text(text)
            r = self.cmd("show")
            self.assertEqual(r.returncode, 2, text + r.stdout + r.stderr)
            self.assertIn("not a 4.x state object", r.stderr)

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

    def test_nothing_to_commit_is_not_an_attempt(self):
        self.stamp()
        r = self.cmd("commit", "--message", "feat: x")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("NOTHING", r.stderr)
        self.assertNotIn("commit_attempt", self.state()["phase6"])

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

    def fake_git(self, fail):
        """Put a git on PATH that runs the real one, then fails `git <fail>`
        (outside check-fresh's own temporary index)."""
        bindir = self.tmp / "fakegit"
        bindir.mkdir(exist_ok=True)
        real = shutil.which("git", path=self.env["PATH"])
        (bindir / "git").write_text(
            "#!/bin/sh\n"
            f'"{real}" "$@"; code=$?\n'
            f'if [ "$1" = "{fail}" ] && [ -z "$GIT_INDEX_FILE" ]; then\n'
            '  echo "fatal: injected failure" >&2; exit 128\nfi\nexit $code\n')
        (bindir / "git").chmod(0o755)
        self.env["PATH"] = f"{bindir}{os.pathsep}{self.env['PATH']}"

    def track(self, *names):
        for name in names:
            (self.worktree / name).write_text(f"export const {name[:-3]} = 0;\n")
        self.git("add", *names)
        self.git("commit", "-q", "-m", "track")

    def test_commit_unstages_when_staging_fails(self):
        for step in ("add", "rm"):
            with self.subTest(step=step):
                self.track(f"gone_{step}.ts")
                (self.worktree / f"gone_{step}.ts").unlink()
                self.change()
                self.stamp()
                path = self.env["PATH"]
                self.fake_git(step)
                r = self.cmd("commit", "--message", "feat: x")
                self.env["PATH"] = path
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                self.assertEqual(self.git("diff", "--cached", "--name-only"), "")
                self.git("checkout", "-q", "--", ".")
                self.git("clean", "-qfd", "-e", ".auto-dev")

    def test_commit_records_deleted_files(self):
        self.track("old1.ts", "old2.ts")
        (self.worktree / "old1.ts").unlink()       # deleted, not staged
        self.git("rm", "-q", "old2.ts")            # deletion already staged
        self.change()
        self.stamp()
        r = self.cmd("commit", "--message", "feat: x")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        status = self.git("show", "--name-status", "--format=", "HEAD").split("\n")
        self.assertIn("D\told1.ts", status)
        self.assertIn("D\told2.ts", status)
        self.assertEqual(self.git("status", "--porcelain", "--", ":!.auto-dev"), "")

    def test_commit_whose_check_could_not_run_is_checked_on_rerun(self):
        # state's artifact_dir is a link the post-commit hook removes, so the
        # check after the commit cannot run (the state itself is in --dir).
        link = self.tmp / "artifacts-link"
        link.symlink_to(self.dir)
        state = self.state()
        state["artifact_dir"] = str(link)
        self.write_state(state)
        hooks = self.repo / ".git" / "hooks"
        hooks.mkdir(exist_ok=True)
        (hooks / "post-commit").write_text(f"#!/bin/sh\nrm -f '{link}'\n")
        (hooks / "post-commit").chmod(0o755)
        self.change()
        self.stamp()
        r = self.cmd("commit", "--message", "feat: x")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        head = self.git("rev-parse", "HEAD").strip()
        self.assertIn(head, r.stderr)
        p6 = self.state()["phase6"]
        self.assertEqual(p6.get("unverified_commit"), head)
        self.assertNotIn("verified_sha", p6)
        self.assertNotIn("commit_attempt", p6)  # could not run: not an attempt
        (hooks / "post-commit").unlink()
        link.symlink_to(self.dir)
        r = self.cmd("commit", "--message", "feat: x")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(f"COMMITTED: {head}", r.stdout)
        p6 = self.state()["phase6"]
        self.assertEqual(p6["verified_sha"], head)
        self.assertNotIn("unverified_commit", p6)
        self.assertEqual(self.git("rev-parse", "HEAD").strip(), head)  # no new commit

    def test_unexpected_error_cannot_run(self):
        state = self.state()
        del state["settings"]
        self.write_state(state)
        r = self.watch()
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("ERROR: KeyError", r.stderr)

    # ci-watch
    def watch(self, *extra):
        return self.cmd("ci-watch", "--pr", "7", "--interval", "1", *extra)

    def checks(self, checks=None, head=None, **response):
        head = head or self.git("rev-parse", "HEAD").strip()
        self.script_gh([{"args": ["pr", "view"],
                         "stdout": json.dumps({"headRefOid": head})},
                        {"args": ["pr", "checks"],
                         "stdout": json.dumps(checks) if checks is not None else "",
                         **response}])

    PENDING = ({"name": "test", "bucket": "pending", "state": "PENDING", "link": ""},)

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
        self.checks(self.PENDING)
        r = self.watch("--max-wait", "0")
        self.assertEqual(r.returncode, 3)
        self.assertIn("PENDING", r.stdout)
        self.checks([{"name": "deploy", "bucket": "cancel", "state": "CANCELLED",
                      "link": "https://ci/2"}])
        r = self.watch()
        self.assertEqual(r.returncode, 1)
        self.assertIn("deploy — https://ci/2 (cancelled)", r.stdout)
        self.assertNotIn("infrastructure", r.stdout)

    def test_ci_rewatch_after_a_final_status_restarts_the_clock(self):
        self.set_settings(ci="github-actions", ci_timeout=30)
        state = self.state()
        head = self.git("rev-parse", "HEAD").strip()
        for status in ("green", "timeout", "unavailable"):
            with self.subTest(status=status):
                state["phase6"]["ci"] = {"sha": head, "started": 1.0, "status": status}
                self.write_state(state)
                self.checks(self.PENDING)
                r = self.watch("--max-wait", "0")
                self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
                self.assertIn("PENDING", r.stdout)
                self.assertGreater(self.state()["phase6"]["ci"]["started"], 1.0)
        # A watch still pending keeps its clock: it times out.
        state["phase6"]["ci"] = {"sha": head, "started": 1.0, "status": "pending"}
        self.write_state(state)
        r = self.watch("--max-wait", "0")
        self.assertIn("TIMEOUT", r.stdout)

    def test_ci_ignores_checks_for_another_head(self):
        self.set_settings(ci="github-actions")
        self.checks([{"name": "test", "bucket": "fail", "state": "FAILURE", "link": "l"}],
                    head="f" * 40)
        r = self.watch("--max-wait", "0")
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertIn("PENDING", r.stdout)
        self.assertIn("ffffffffffff", r.stdout)
        self.assertEqual(self.state()["phase6"]["ci"]["status"], "pending")
        r = self.watch("--max-wait", "0", "--grace", "0")
        self.assertEqual(r.returncode, 4, r.stdout + r.stderr)
        self.assertIn("UNAVAILABLE: the PR's head", r.stdout)
        self.checks([{"name": "test", "bucket": "pass", "state": "SUCCESS", "link": "l"}],
                    head="f" * 40)
        self.assertNotIn("GREEN", self.watch("--max-wait", "0").stdout)

    def test_ci_timeout_holds(self):
        self.set_settings(ci="github-actions", ci_timeout=0)
        self.checks(self.PENDING)
        r = self.watch("--max-wait", "5")
        self.assertEqual(r.returncode, 3)
        self.assertIn("TIMEOUT", r.stdout)
        self.assertIn("run `next`; the main gate shows CI as not monitored", r.stdout)
        self.assertNotIn("hold at the gate", r.stdout)

    def test_no_checks_after_grace_is_unavailable(self):
        self.set_settings(ci="github-actions")
        self.checks(stderr="no checks reported on the 'feat/due-dates' branch", exit=1)
        r = self.watch("--max-wait", "0", "--grace", "300")
        self.assertEqual(r.returncode, 3)  # still inside the grace period
        r = self.watch("--max-wait", "0", "--grace", "0")
        self.assertEqual(r.returncode, 4)
        self.assertIn("UNAVAILABLE", r.stdout)
        self.assertIn("run `next`; the main gate shows CI as not monitored", r.stdout)
        self.assertNotIn("hold at the gate", r.stdout)

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

    def test_merge_staging_that_could_not_run_is_not_an_attempt(self):
        state = self.state()
        state["repo"]["staging"] = "staging"  # no such branch on origin: fetch fails
        self.write_state(state)
        r = self.cmd("merge-staging")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertNotIn("staging_attempt", self.state()["phase6"])

    def test_merge_staging_git_failing_midway_is_not_an_attempt(self):
        self.staging(content="export const one = 9;\n")
        # A local edit the switch to staging would overwrite: git switch fails.
        (self.worktree / "app.ts").write_text("export const one = 5;\n")
        r = self.cmd("merge-staging")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertNotIn("staging_attempt", self.state()["phase6"])
        self.assertEqual(self.git("branch", "--show-current").strip(), "feat/due-dates")

    def test_merge_staging_conflict_aborts_and_returns(self):
        self.staging(content="export const one = 9;\n")
        r = self.cmd("merge-staging")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("CONFLICT", r.stderr)
        self.assertEqual(self.git("branch", "--show-current").strip(), "feat/due-dates")
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_merge_staging_push_rejected_returns_to_the_branch(self):
        self.staging()
        hook = self.tmp / "origin.git" / "hooks" / "pre-receive"
        hook.write_text("#!/bin/sh\necho 'protected branch' >&2\nexit 1\n")
        hook.chmod(0o755)
        r = self.cmd("merge-staging")
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertIn("REJECTED", r.stderr)
        self.assertEqual(self.git("branch", "--show-current").strip(), "feat/due-dates")
        self.assertEqual(self.git("status", "--porcelain"), "")

    # merge-pr
    def merge(self, merge_response, state="MERGED", view=None, repo=None):
        self.script_gh([
            {"args": ["repo", "view"], **(repo or {"stdout": json.dumps(
                {"squashMergeAllowed": True, "mergeCommitAllowed": True,
                 "rebaseMergeAllowed": False})})},
            {"args": ["pr", "merge"], **merge_response},
            {"args": ["pr", "view"], **(view or {"stdout": json.dumps({"state": state})})},
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
        refusals = (
            "Pull request is not mergeable: review required",
            ("X Pull request acme/app#7 is not mergeable: the base branch policy "
             "prohibits the merge."),
            'GraphQL: Required status check "test" is expected. (mergePullRequest)',
            ("GraphQL: At least 1 approving review is required by reviewers with write "
             "access. (mergePullRequest)"),
            ("X Pull request acme/app#7 is not mergeable: the merge commit cannot be "
             "cleanly created."))
        for refusal in refusals:
            with self.subTest(refusal=refusal[:30]):
                r = self.merge({"stderr": refusal, "exit": 1})
                self.assertEqual(r.returncode, 4, r.stdout + r.stderr)
                self.assertIn("REFUSED", r.stderr)
        r = self.merge({"stdout": "auto-merge enabled"}, state="OPEN")
        self.assertEqual(r.returncode, 3)
        self.assertIn("QUEUED", r.stdout)

    def test_merge_pr_that_could_not_run(self):
        usage = ("unknown flag: --match-head-commit\n\nUsage:  gh pr merge [<number>] "
                 "[flags]\n  --match-head-commit SHA  Commit SHA that the pull request "
                 "head must match to allow merge")
        for response in ({"stderr": usage, "exit": 1},
                         {"stderr": "To get started with GitHub CLI, please run:  gh auth "
                          "login", "exit": 4},
                         {"stderr": "error connecting to api.github.com\ncheck your "
                          "internet connection or https://githubstatus.com\n", "exit": 1},
                         {"stderr": "HTTP 502: Bad Gateway (https://api.github.com/graphql)",
                          "exit": 1},
                         {"stderr": "Post \"https://api.github.com/graphql\": context "
                          "deadline exceeded", "exit": 1}):
            with self.subTest(response=response["stderr"][:30]):
                r = self.merge(response)
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                self.assertNotIn("HEAD-MOVED", r.stderr)
                self.assertNotIn("merge_attempt", self.state()["phase6"])
        (self.tmp / "gh.log").unlink()
        r = self.merge({"stdout": "merged"}, repo={"stderr": "HTTP 502", "exit": 1})
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertFalse(any(c[:2] == ["pr", "merge"] for c in self.gh_calls()))
        r = self.merge({"stdout": "merged"}, view={"stderr": "HTTP 502", "exit": 1})
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertNotIn("QUEUED", r.stdout + r.stderr)
        self.assertIn("succeeded", r.stderr)
        # merged, maybe: recorded, so `next` never offers the merge again
        self.assertEqual(self.state()["phase6"]["merge_attempt"]["result"], "unknown")
        (self.tmp / "no-gh").mkdir()
        self.env["PATH"] = str(self.tmp / "no-gh")  # merge-pr runs only gh
        r = self.cmd("merge-pr", "--pr", "7", "--sha", "abc123")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("gh is not installed", r.stderr)

    # pr-body --check
    def test_pr_body_lint(self):
        state = self.state()
        state["phase6"]["verified_sha"] = "a" * 40
        self.write_state(state)
        body = self.tmp / "body.md"
        body.write_text(GOOD_BODY.format(sha="a" * 40))
        r = self.cmd("pr-body", "--check", body)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        (self.dir / "CODE_REVIEW.md").write_text(
            "# Code review\n\n| # | Finding |\n|---|---|\n| C2 | an empty list |\n")
        body.write_text(GOOD_BODY.format(sha="b" * 40).replace("### Test strength", "")
                        + f"See C2 in .auto-dev/SPEC.md, from {self.worktree}.\n"
                        + "token = ghp_" + "x" * 30 + "\n")
        r = self.cmd("pr-body", "--check", body)
        self.assertEqual(r.returncode, 1)
        for text in ("### Test strength", "not the verified commit", ".auto-dev/",
                     "C2", "worktree", "secret"):
            self.assertIn(text, r.stdout)

    def test_pr_body_lint_passes_ordinary_words(self):
        state = self.state()
        state["phase6"]["verified_sha"] = "a" * 40
        self.write_state(state)
        (self.dir / "SECURITY_REVIEW.md").write_text(
            "# Security review\n\n| # | Finding |\n|---|---|\n| S1 | weak hash |\n")
        body = self.tmp / "body.md"
        body.write_text(GOOD_BODY.format(sha="a" * 40) + (
            "Uploads go to S3 and M1 Macs build it. Strong passwords are required.\n"
            "The JWT verifier rejects a bad signature; a mutant record is skipped.\n"
            "`interface Login { token: string; password: string }`\n"
            "Served from /application/data.\n"))
        env = dict(self.env)
        self.env["HOME"] = "/app"
        r = self.cmd("pr-body", "--check", body)
        self.env = env
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        body.write_text(GOOD_BODY.format(sha="a" * 40)
                        + "Fixes S1; see /app/src/x.ts | met | Strong |\n"
                        + "GH=ghp_" + "y" * 36 + "\n")
        self.env["HOME"] = "/app"
        r = self.cmd("pr-body", "--check", body)
        self.env = env
        self.assertEqual(r.returncode, 1)
        for text in ("S1", "home directory", "evidence tier", "secret"):
            self.assertIn(text, r.stdout)

    def test_pr_body_lint_secrets(self):
        state = self.state()
        state["phase6"]["verified_sha"] = "a" * 40
        self.write_state(state)
        body = self.tmp / "body.md"
        for line in ("password=hunter2", "DB_PASSWORD=Tr0ub4dor&3",
                     "secret=Sup3rS3cret!", "password: correcthorsebatterystaple",
                     'API_KEY="abcd1234"', "GH=ghp_" + "z" * 36):
            with self.subTest(line=line):
                body.write_text(GOOD_BODY.format(sha="a" * 40) + line + "\n")
                r = self.cmd("pr-body", "--check", body)
                self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
                self.assertIn("secret", r.stdout)
        # Type annotations (example in TypeScript) are not secrets.
        body.write_text(GOOD_BODY.format(sha="a" * 40) + (
            "`token: string`\n`{ token: string }`\n`password: string;`\n"
            "`function login(password: Password) {}`\n`token: number | null`\n"))
        r = self.cmd("pr-body", "--check", body)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

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
