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
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp()))
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
        self.assertNotIn("staging", state["repo"])
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

    def push_docs(self, *paths):
        seed = self.tmp / "seed"
        for rel in paths:
            (seed / rel).parent.mkdir(parents=True, exist_ok=True)
            (seed / rel).write_text("# Rules\n")
        self.sh("git", "add", "-A", cwd=seed)
        self.sh("git", "commit", "-q", "-m", "docs", cwd=seed)
        self.sh("git", "push", "-q", "origin", "main", cwd=seed)

    def test_security_docs_in_the_override_win(self):
        self.push_docs("docs/rules.md", "SECURITY.md")
        (self.repo / ".auto-dev.yml").write_text("security_docs: [docs/rules.md]\n")
        self.assertEqual(self.init().returncode, 0)
        self.assertIn("**Security directives:** docs/rules.md\n",
                      (self.dir / "profile.md").read_text())

    def test_an_empty_security_docs_list_turns_them_off(self):
        self.push_docs("SECURITY.md")
        (self.repo / ".auto-dev.yml").write_text("security_docs: []\n")
        self.assertEqual(self.init().returncode, 0)
        self.assertEqual(self.state()["settings"]["security_docs"], [])
        self.assertIn("**Security directives:** none", (self.dir / "profile.md").read_text())

    def test_a_listed_security_doc_that_is_missing_is_dropped_with_a_note(self):
        self.push_docs("docs/rules.md")
        (self.repo / ".auto-dev.yml").write_text(
            "security_docs: [docs/rules.md, docs/gone.md]\n")
        self.assertEqual(self.init().returncode, 0)
        self.assertEqual(self.state()["settings"]["security_docs"], ["docs/rules.md"])
        self.assertIn("**Security directives:** docs/rules.md (not found: docs/gone.md)",
                      (self.dir / "profile.md").read_text())
        self.assertIn("security_docs not found in the worktree: docs/gone.md",
                      json.dumps(self.state()["notes"]))

    def test_checkpoint_events_come_from_the_override(self):
        (self.repo / ".auto-dev.yml").write_text("checkpoint_events: 40\n")
        self.assertEqual(self.init().returncode, 0)
        self.assertEqual(self.state()["settings"]["checkpoint_events"], 40)

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

    def test_a_staging_branch_on_origin_is_ignored(self):
        self.sh("git", "push", "-q", "origin", "main:staging", cwd=self.repo)
        r = self.init()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("staging", r.stdout.lower())
        state = self.state()
        self.assertNotIn("staging", state["repo"])
        self.assertNotIn("staging", json.dumps(state).lower())
        self.assertNotIn("staging", (self.dir / "profile.md").read_text().lower())

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

    def two_runs(self):
        self.assertEqual(self.init().returncode, 0)
        r = self.autodev("init", "--repo", self.repo, "--slug", "dark-mode",
                         "--task", "Add a dark mode", "--profile", self.profile,
                         "--max-wait", "30")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return self.tmp / "app-dark-mode"

    def test_several_open_runs_ask_from_the_main_checkout(self):
        self.two_runs()
        r = self.resume()
        self.assertTrue(r.stdout.startswith("ASK"), r.stdout)

    def test_inside_a_runs_worktree_that_run_resumes(self):
        other = self.two_runs()
        for tree in (other, other / "sub"):  # its root or a folder in it
            tree.mkdir(exist_ok=True)
            r = self.autodev("resume", "--repo", tree)
            self.assertTrue(r.stdout.startswith(f"RESUME: {other}"), r.stdout)
        # A finished run where the session started is reported, not skipped.
        self.autodev("gate", "jira", "stop", "--dir", other / ".auto-dev")
        r = self.autodev("resume", "--repo", other)
        self.assertTrue(r.stdout.startswith(f"FINISHED: {other}"), r.stdout)
        # A named task still wins over where the session started.
        r = self.autodev("resume", "--repo", other, "--task", "Add due dates to todos")
        self.assertTrue(r.stdout.startswith(f"RESUME: {self.worktree}"), r.stdout)

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


class AdoptWorktreeTest(RunCase):
    """`init` run from a worktree the user made uses it instead of a new one."""

    def make_worktree(self, *how):
        self.mine = self.tmp / "app-mine"
        self.sh("git", "fetch", "-q", "origin", cwd=self.repo)
        self.sh("git", "worktree", "add", "-q", str(self.mine), *how, "origin/main",
                cwd=self.repo)
        self.dir = self.mine / ".auto-dev"

    def init_here(self, task="Add due dates to todos"):
        return self.autodev("init", "--repo", self.mine, "--slug", "due-dates",
                            "--task", task, "--profile", self.profile,
                            "--max-wait", "30")

    def test_runs_in_the_worktree_and_keeps_its_branch(self):
        self.make_worktree("-b", "my-branch")
        r = self.init_here()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(f"INIT: {self.mine}", r.stdout)
        self.assertFalse(self.worktree.exists())  # no ../app-due-dates
        self.assertFalse((self.tmp / "app-mine-due-dates").exists())
        state = self.state()
        self.assertEqual(state["worktree"], str(self.mine))
        self.assertEqual(state["branch"], "my-branch")
        self.assertEqual(state["repo"]["main_checkout"], str(self.mine))
        self.assertEqual((self.mine / ".env").read_text(), "SECRET=1\n")  # seeded
        self.assertTrue((self.mine / "setup-ran.txt").exists())
        self.assertIn("worktree the user made", json.dumps(state["notes"]))
        self.assertEqual(self.sh("git", "status", "--porcelain", cwd=self.mine), "")
        r = self.autodev("resume", "--repo", self.repo)
        self.assertTrue(r.stdout.startswith(f"RESUME: {self.mine}"), r.stdout)

    def test_keeps_a_seeded_file_already_there(self):
        self.make_worktree("-b", "my-branch")
        (self.mine / ".env").write_text("MINE=1\n")
        self.assertEqual(self.init_here().returncode, 0)
        self.assertEqual((self.mine / ".env").read_text(), "MINE=1\n")

    def test_detached_head_gets_a_branch_at_the_same_commit(self):
        self.make_worktree("--detach")
        head = self.sh("git", "rev-parse", "HEAD", cwd=self.mine)
        r = self.init_here()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.state()["branch"], "feat/due-dates")
        self.assertEqual(self.sh("git", "symbolic-ref", "--short", "HEAD",
                                 cwd=self.mine), "feat/due-dates\n")
        self.assertEqual(self.sh("git", "rev-parse", "HEAD", cwd=self.mine), head)

    def test_commits_already_on_the_branch_are_noted(self):
        self.make_worktree("-b", "my-branch")
        (self.mine / "extra.ts").write_text("export const two = 2;\n")
        self.sh("git", "add", "-A", cwd=self.mine)
        self.sh("git", "commit", "-q", "-m", "start", cwd=self.mine)
        self.assertEqual(self.init_here().returncode, 0)
        self.assertIn("my-branch already holds 1 commit(s) not on origin/main",
                      json.dumps(self.state()["notes"]))

    def test_uncommitted_changes_stop(self):
        self.make_worktree("-b", "my-branch")
        (self.mine / "app.ts").write_text("export const one = 3;\n")
        r = self.init_here()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("uncommitted changes", r.stderr)
        self.assertFalse(self.dir.exists())
        self.assertEqual((self.mine / "app.ts").read_text(), "export const one = 3;\n")

    def test_failure_keeps_the_worktree_and_drops_a_created_branch(self):
        self.make_worktree("--detach")
        self.profile.write_text(PROFILE.replace('[".env"]', '["app.ts"]'))
        r = self.init_here()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("not gitignored", r.stderr)
        self.assertTrue((self.mine / "app.ts").exists())
        self.assertFalse(self.dir.exists())
        self.assertEqual(self.sh("git", "branch", "--list", "feat/due-dates",
                                 cwd=self.repo), "")
        self.profile.write_text(PROFILE)
        self.assertEqual(self.init_here().returncode, 0)

    def test_rerun_reattaches_and_another_task_stops(self):
        self.make_worktree("-b", "my-branch")
        self.assertEqual(self.init_here().returncode, 0)
        self.assertEqual(self.init_here().returncode, 0)  # the same task reattaches
        r = self.init_here(task="Rename the settings page")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("already holds another task's run", r.stderr)

    def test_a_worktree_on_the_base_branch_gets_a_new_one(self):
        self.sh("git", "switch", "-q", "--detach", cwd=self.repo)  # frees main
        self.mine = self.tmp / "home"
        self.sh("git", "worktree", "add", "-q", str(self.mine), "main", cwd=self.repo)
        r = self.init_here()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        new = self.tmp / "home-due-dates"
        self.assertIn(f"INIT: {new}", r.stdout)
        self.assertNotIn("adopted", r.stdout)
        self.assertFalse((self.mine / ".auto-dev").exists())

    def test_a_worktree_on_the_default_branch_is_not_adopted(self):
        # The base is `develop`; a worktree on `main` (the default) is not the
        # run's branch either: pushing to it would push to main.
        self.sh("git", "push", "-q", "origin", "main:develop", cwd=self.repo)
        self.sh("git", "switch", "-q", "--detach", cwd=self.repo)  # frees main
        self.mine = self.tmp / "home"
        self.sh("git", "worktree", "add", "-q", str(self.mine), "main", cwd=self.repo)
        self.sh("git", "config", "core.excludesFile", str(self.tmp / "ignore"),
                cwd=self.mine)
        (self.tmp / "ignore").write_text(".auto-dev.yml\n")
        (self.mine / ".auto-dev.yml").write_text("branches:\n  base: develop\n")
        r = self.init_here()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(f"INIT: {self.tmp / 'home-due-dates'}", r.stdout)
        self.assertFalse((self.mine / ".auto-dev").exists())

    def test_init_says_it_adopted_and_counts_commits_ahead(self):
        self.make_worktree("-b", "my-branch")
        (self.mine / "extra.ts").write_text("export const two = 2;\n")
        self.sh("git", "add", "-A", cwd=self.mine)
        self.sh("git", "commit", "-q", "-m", "start", cwd=self.mine)
        r = self.init_here()
        self.assertIn("adopted: yes", r.stdout)
        self.assertIn("ahead: 1", r.stdout)

    def test_a_stray_auto_dev_dir_stops(self):
        self.make_worktree("-b", "my-branch")
        (self.mine / ".auto-dev").mkdir()
        (self.mine / ".auto-dev" / ".gitignore").write_text("*\n")
        r = self.init_here()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("holds no 4.x run", r.stderr)

    def test_unrelated_history_stops(self):
        self.make_worktree("-b", "my-branch")
        self.sh("git", "switch", "-q", "--orphan", "lonely", cwd=self.mine)
        self.sh("git", "commit", "-q", "--allow-empty", "-m", "alone", cwd=self.mine)
        r = self.init_here()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("shares no history with origin/main", r.stderr)
        self.assertFalse(self.dir.exists())

    def test_a_missing_base_on_origin_stops(self):
        self.make_worktree("-b", "my-branch")
        self.sh("git", "config", "core.excludesFile", str(self.tmp / "ignore"),
                cwd=self.mine)
        (self.tmp / "ignore").write_text(".auto-dev.yml\n")
        (self.mine / ".auto-dev.yml").write_text("branches:\n  base: nowhere\n")
        r = self.init_here()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("origin/nowhere does not exist", r.stderr)

    def test_cleanup_never_removes_the_users_worktree(self):
        self.make_worktree("-b", "my-branch")
        self.assertEqual(self.init_here().returncode, 0)
        r = self.autodev("cleanup-worktree", "--dir", self.dir)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("user's own worktree", r.stdout + r.stderr)
        self.assertTrue(self.mine.exists())


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

    def test_the_staging_gate_and_mark_are_gone(self):
        r = self.cmd("gate", "staging", "proceed")
        self.assertNotEqual(r.returncode, 0)
        r = self.cmd("mark", "staging-ci", "--value", "green")
        self.assertNotEqual(r.returncode, 0)
        state = self.state()
        self.assertEqual(state["gates"], [])
        self.assertNotIn("staging-ci", state.get("marks") or {})

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
        # S2's orchestrator reads HANDOFF.md and nothing else in .auto-dev/ but the profile
        opened = text.split("## Files you may open\n", 1)[1].split("\n\n", 1)[0]
        self.assertEqual(opened, f"- {self.dir / 'profile.md'}")

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

    def test_merge_staging_is_gone(self):
        r = self.cmd("merge-staging")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("invalid choice", r.stderr)

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


# ------------------------------------------------------------------ mutants
# `autodev.py mutants select` names which mutants a verifier re-check runs
# again; `autodev.py mutants record` saves a finished pass as the next one's
# baseline. The throwaway repo's code is an example in TypeScript, with one
# Python and one Ruby test file for the cross-stack cases.

def numbered(count, special, name):
    """`count` lines, each ending in a newline; `special` maps a 1-based line
    number to its text."""
    return "".join(special.get(i, f"export const {name}{i} = {i};") + "\n"
                   for i in range(1, count + 1))


MUT_FILES = {
    "src/a.ts": numbered(20, {10: "  return total > 0;", 14: "  return count + 1;"}, "a"),
    "src/b.ts": numbered(45, {10: "  if (limit < 5) return;", 20: "  return limit * 2;",
                              40: '  const label = "b";'}, "b"),
    "src/c.ts": numbered(5, {3: "  while (busy) wait();"}, "c"),
    "src/notes.ts": numbered(4, {}, "note"),
    "src/due_check.ts": numbered(6, {3: '  expect(due("2024-01-02")).toBe(true);'}, "due"),
    "src/total.test.ts": numbered(6, {3: "  expect(total([1, 2])).toBe(3);"}, "t"),
    "tests/a.test.ts": ('import { total } from "../src/a";\n\n'
                        'it("totals", () => {\n  expect(total([1])).toBe(true);\n});\n'),
    "tests/b.test.ts": ('import { sum } from "../src/b";\n\ndescribe("sum", () => {\n'
                        'it("adds", () => {\n  const total = sum([4, 6]);\n  log(total);\n'
                        "  check(total);\n\n  // totals\n  note(total);\n  keep(total);\n"
                        "  expect(total).toBe(10);\n});\n});\n// end of the sum tests\n"),
    "tests/fixtures/totals.json": '{"total": 10}\n',
    "tests/test_b.py": ("from b import total_of\n\n\ndef test_total():\n"
                        "    total = total_of([4, 6])\n    a = 1\n    b = 2\n    c = 3\n"
                        "    d = 4\n    e = 5\n    f = 6\n    assert total == 10\n"),
    "spec/b_spec.rb": ('require "b"\n\nRSpec.describe "sum" do\n  it "adds" do\n'
                       "    total = sum([4, 6])\n    a = 1\n    b = 2\n    c = 3\n"
                       "    d = 4\n    e = 5\n    f = 6\n    expect(total).to eq(10)\n"
                       "  end\nend\n"),
    "package.json": '{"name": "app", "scripts": {"test": "jest"}}\n',
    "README.md": "# app\n\nSums things.\n",
}
MUT_SET = [
    {"id": "M1", "file": "src/a.ts", "line": 10, "find": "total > 0",
     "replace": "total >= 0", "condition": "1"},
    {"id": "M2", "file": "src/a.ts", "line": 14, "find": "count + 1",
     "replace": "count - 1", "condition": "1"},
    {"id": "M3", "file": "src/b.ts", "line": 10, "find": "limit < 5",
     "replace": "limit <= 5", "condition": "2"},
    {"id": "M4", "file": "src/c.ts", "line": 3, "find": "while (busy)",
     "replace": "while (true)", "condition": "3"},
]
M5_AT_20 = {"id": "M5", "file": "src/b.ts", "line": 20, "find": "limit * 2",
            "replace": "limit * 3", "condition": "2"}
MUT_STATUSES = {"M1": "killed", "M2": "survived", "M3": "killed", "M4": "timeout"}
NEW_TS_TEST = 'it("adds zero", () => {\n  expect(sum([0])).toBe(0);\n});\n'
NEW_PY_TEST = "\n\ndef test_zero():\n    assert total_of([0]) == 0\n"
EVERY_MUTANT = ["M1", "M2", "M3", "M4"]


class MutantsCase(unittest.TestCase):
    """A committed throwaway repo, its git-ignored .auto-dev/ with a mutation
    set M1-M4, and src/due_check.ts installed as a sealed acceptance check."""

    def setUp(self):
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp()))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.wt = self.tmp / "app"
        self.ad = self.wt / ".auto-dev"
        self.evidence = self.ad / "evidence"
        self.cwd = self.tmp / "cwd"
        self.cwd.mkdir()
        self.wt.mkdir()
        self.git("init", "-q", "-b", "main")
        for rel, text in MUT_FILES.items():
            self.write(rel, text)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "init")
        self.write(".auto-dev/.gitignore", "*\n")
        self.write(".auto-dev/acceptance/files/src/due_check.ts.sealed",
                   MUT_FILES["src/due_check.ts"])
        self.evidence.mkdir(parents=True)
        self.set_mutants(MUT_SET)

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.wt), *args], env=BASE_ENV,
                              capture_output=True, text=True, check=True).stdout

    def write(self, rel, text):
        path = self.wt / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def read(self, rel):
        return (self.wt / rel).read_text()

    def edit_line(self, rel, n, text):
        lines = self.read(rel).split("\n")
        lines[n - 1] = text
        self.write(rel, "\n".join(lines))

    def delete_line(self, rel, n):
        lines = self.read(rel).split("\n")
        del lines[n - 1]
        self.write(rel, "\n".join(lines))

    def append(self, rel, text):
        self.write(rel, self.read(rel) + text)

    def set_mutants(self, entries):
        (self.evidence / "mutation-set.json").write_text(json.dumps(entries, indent=2))

    def add_mutant(self, entry):
        entries = json.loads((self.evidence / "mutation-set.json").read_text())
        self.set_mutants([*entries, entry])

    @property
    def record_file(self):
        return self.evidence / "mutation-record.json"

    def tree(self):
        return subprocess.run([sys.executable, str(SCRIPTS / "check-fresh.py"), "--print-tree",
                               str(self.wt)], env=BASE_ENV, capture_output=True, text=True,
                              check=True).stdout.strip()

    def write_record(self, statuses=None, tree=None, results=None):
        """A record as `mutants record` leaves it, at `tree` (default: now)."""
        statuses = statuses or MUT_STATUSES
        if results is None:
            results = [{**m, "status": statuses[m["id"]]} for m in MUT_SET
                       if m["id"] in statuses]
        self.record_file.write_text(json.dumps(
            {"tree": self.tree() if tree is None else tree, "results": results}))

    def change_result(self, mid, **fields):
        record = json.loads(self.record_file.read_text())
        for result in record["results"]:
            if result["id"] == mid:
                result.update(fields)
        self.record_file.write_text(json.dumps(record))

    def mutants(self, *args, ad=None):
        return subprocess.run([sys.executable, str(AUTODEV), "mutants", *args, "--dir",
                               str(ad or self.ad)], env=BASE_ENV, capture_output=True,
                              text=True, cwd=self.cwd, check=False)

    def pick(self):
        r = self.mutants("select", "--json")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return json.loads(r.stdout)

    def rerun_ids(self, out):
        return [m["id"] for m in out["rerun"]]

    def carried(self, out):
        return {m["id"]: m["status"] for m in out["carried"]}

    def reset(self):
        """The committed files, the set M1-M4, and no record or run files."""
        self.git("checkout", "-q", "--", ".")
        self.git("clean", "-qfd", "-e", ".auto-dev")
        for name in ("mutation-record.json", "mutants.json.results.json", "mutate.exit"):
            (self.evidence / name).unlink(missing_ok=True)
        self.set_mutants(MUT_SET)

    def run_results(self, results, code):
        """What mutate.py leaves: its results file and, unless `code` is None,
        its exit file."""
        (self.evidence / "mutants.json.results.json").write_text(json.dumps(
            [{"output": "1 test ran", **r} for r in results], indent=2))
        if code is not None:
            (self.evidence / "mutate.exit").write_text(f"{code}\n")

    def ran(self, statuses, lines=None):
        """The set's entries for `statuses`, as mutate.py reports them."""
        lines = lines or {}
        entries = json.loads((self.evidence / "mutation-set.json").read_text())
        return [{**m, "line": lines.get(m["id"], m["line"]), "status": statuses[m["id"]]}
                for m in entries if m["id"] in statuses]

    def rec(self, *extra):
        r = self.mutants("record", "--json", *extra)
        return r.returncode, json.loads(r.stdout) if r.stdout.strip() else {"stderr": r.stderr}

    def first_pass(self, statuses=None, code=1):
        """Pass 1 ran every mutant and recorded its results at the tree now."""
        self.run_results(self.ran(statuses or MUT_STATUSES), code)
        code_, out = self.rec("--tree", self.tree())
        self.assertEqual(code_, 0, out)
        for name in ("mutants.json.results.json", "mutate.exit"):
            (self.evidence / name).unlink(missing_ok=True)
        return out


class MutantSelectTest(MutantsCase):
    def test_reruns_uncaught_touched_and_added_and_carries_the_rest(self):
        self.write_record()
        self.edit_line("src/b.ts", 12, "export const b12 = 120;")
        self.append("tests/b.test.ts", NEW_TS_TEST)
        self.append("src/b.ts", "  return limit + 7;\n")
        self.add_mutant({"id": "M5", "file": "src/b.ts", "line": 46, "find": "limit + 7",
                         "replace": "limit - 7", "condition": "2"})
        out = self.pick()
        self.assertEqual(out["result"], "RERUN", out)
        self.assertEqual(self.rerun_ids(out), ["M2", "M3", "M5"], out)
        self.assertEqual(self.carried(out), {"M1": "killed", "M4": "timeout"}, out)
        self.assertIsNone(out["reason"], out)

    def test_text_output_names_each_mutant_and_why(self):
        self.write_record()
        base = self.tree()
        self.edit_line("src/b.ts", 40, '  const label = "bee";')
        self.add_mutant(M5_AT_20)
        r = self.mutants("select")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        lines = [line.strip() for line in r.stdout.splitlines()]
        self.assertEqual(lines[0], "RERUN: 3 to re-run, 2 carried forward")
        self.assertIn("rerun: M2 src/a.ts:14 — survived last pass", lines)
        self.assertIn("rerun: M3 src/b.ts:10 — src/b.ts changed since the last pass", lines)
        self.assertIn("rerun: M5 src/b.ts:20 — new since the last pass", lines)
        self.assertIn("carried: M1 src/a.ts:10 killed", lines)
        self.assertIn("carried: M4 src/c.ts:3 timeout", lines)
        self.assertIn(f"base: {base}", lines)
        self.assertIn(f"tree: {self.tree()}", lines)

    def test_any_edit_in_a_file_reruns_every_mutant_in_it(self):
        self.write_record()
        self.edit_line("src/b.ts", 40, '  const label = "bee";')  # M3 is on line 10
        out = self.pick()
        self.assertEqual(self.rerun_ids(out), ["M2", "M3"], out)
        self.assertEqual(self.carried(out), {"M1": "killed", "M4": "timeout"}, out)

    def test_file_put_back_byte_for_byte_keeps_its_kills(self):
        self.write_record()
        self.edit_line("src/a.ts", 10, "  return total > 1;")
        self.git("commit", "-q", "-am", "change a")
        self.write("src/a.ts", MUT_FILES["src/a.ts"])
        out = self.pick()
        self.assertEqual(self.rerun_ids(out), ["M2"], out)
        self.assertEqual(self.carried(out), {"M1": "killed", "M3": "killed", "M4": "timeout"})

    def test_mutant_missing_from_the_record_runs_alone(self):
        self.write_record()
        self.add_mutant(M5_AT_20)
        out = self.pick()
        self.assertEqual(self.rerun_ids(out), ["M2", "M5"], out)
        self.assertEqual(self.carried(out), {"M1": "killed", "M3": "killed", "M4": "timeout"})
        why = {m["id"]: m["why"] for m in out["rerun"]}
        self.assertEqual(why["M5"], "new since the last pass")

    def test_result_not_matching_its_set_entry_reruns_that_one(self):
        for field, value in (("find", "total >= 1"), ("replace", "total < 0"),
                             ("file", "src/other.ts")):
            with self.subTest(differs=field):
                self.reset()
                self.write_record()
                self.change_result("M1", **{field: value})
                out = self.pick()
                self.assertEqual(self.rerun_ids(out), ["M1", "M2"], out)
                self.assertEqual(self.carried(out), {"M3": "killed", "M4": "timeout"}, out)
                why = {m["id"]: m["why"] for m in out["rerun"]}
                self.assertEqual(why["M1"],
                                 "its recorded file, find or replace differs from the set")

    def test_recorded_line_is_not_compared(self):
        self.write_record()
        self.change_result("M1", line=12)
        out = self.pick()
        self.assertEqual(self.carried(out).get("M1"), "killed", out)
        self.assertEqual(self.rerun_ids(out), ["M2"], out)
        line = {m["id"]: m["line"] for m in out["carried"]}
        self.assertEqual(line["M1"], 12)  # its latest known line

    def test_result_for_a_mutant_gone_from_the_set_is_ignored(self):
        self.write_record(results=[{**m, "status": MUT_STATUSES[m["id"]]} for m in MUT_SET]
                          + [{"id": "M9", "file": "src/c.ts", "line": 1, "find": "c1",
                              "replace": "c2", "status": "killed"}])
        out = self.pick()
        self.assertNotIn("M9", json.dumps(out))
        self.assertEqual(self.rerun_ids(out), ["M2"], out)
        self.assertEqual(self.carried(out), {"M1": "killed", "M3": "killed", "M4": "timeout"})

    def test_docs_and_new_tests_rerun_only_the_uncaught(self):
        self.write_record()
        self.append("tests/a.test.ts", NEW_TS_TEST)
        self.append("README.md", "\nMore about sums.\n")
        out = self.pick()
        self.assertEqual(self.rerun_ids(out), ["M2"], out)
        self.assertEqual(self.carried(out), {"M1": "killed", "M3": "killed", "M4": "timeout"})

    def test_unchanged_tree_reruns_only_the_uncaught(self):
        for status in ("survived", "invalid"):
            with self.subTest(m2=status):
                self.reset()
                self.write_record({**MUT_STATUSES, "M2": status})
                out = self.pick()
                self.assertEqual(out["result"], "RERUN", out)
                self.assertEqual(self.rerun_ids(out), ["M2"], out)
                self.assertEqual(out["rerun"][0]["why"], f"{status} last pass")
                self.assertEqual(self.carried(out),
                                 {"M1": "killed", "M3": "killed", "M4": "timeout"}, out)

    def test_all_caught_and_tests_only_added_runs_nothing(self):
        self.write_record({**MUT_STATUSES, "M2": "killed"})
        self.append("tests/b.test.ts", NEW_TS_TEST)
        out = self.pick()
        self.assertEqual(out["result"], "CARRY_ALL", out)
        self.assertEqual(out["rerun"], [], out)
        self.assertEqual(len(out["carried"]), 4, out)
        r = self.mutants("select")
        self.assertTrue(r.stdout.startswith("CARRY_ALL: nothing to re-run, 4 carried forward"),
                        r.stdout)

    def test_test_changes_force_every_mutant(self):
        def rename(old, new):
            (self.wt / old).rename(self.wt / new)

        cases = [
            ("changed test line", lambda: self.edit_line(
                "tests/b.test.ts", 12, "  expect(total).toBeDefined();"),
             "tests/b.test.ts:12 — an existing test line was changed or removed"),
            ("deleted test line", lambda: self.delete_line("tests/b.test.ts", 5),
             "tests/b.test.ts:5 — "),
            ("changed blank line", lambda: self.edit_line("tests/b.test.ts", 8, "  // why"),
             "tests/b.test.ts:8 — "),
            ("changed comment line", lambda: self.edit_line("tests/b.test.ts", 9, "  // sums"),
             "tests/b.test.ts:9 — "),
            ("deleted test file", lambda: (self.wt / "tests/a.test.ts").unlink(),
             "tests/a.test.ts — a test file was deleted or renamed"),
            ("renamed test file", lambda: rename("tests/a.test.ts", "tests/a2.test.ts"),
             "tests/a.test.ts — a test file was deleted or renamed"),
            ("added skip marker", lambda: self.append(
                "tests/b.test.ts", 'it.skip("later", () => {});\n'),
             "tests/b.test.ts:16 — a skip or focus marker was added"),
            ("added focus marker", lambda: self.append(
                "tests/b.test.ts", NEW_TS_TEST + 'it.only("now", () => {});\n'),
             "tests/b.test.ts:19 — a skip or focus marker was added"),
            ("edited package.json", lambda: self.write(
                "package.json", '{"name": "app", "scripts": {"test": "jest --bail"}}\n'),
             "package.json — a test-runner config file changed"),
            ("new runner config", lambda: self.write(
                "jest.config.ts", "export default { testPathIgnorePatterns: [] };\n"),
             "jest.config.ts — a test-runner config file changed"),
            ("edited fixture data", lambda: self.write(
                "tests/fixtures/totals.json", '{"total": 11}\n'),
             "tests/fixtures/totals.json:1 — "),
            ("edited acceptance check", lambda: self.edit_line(
                "src/due_check.ts", 3, '  expect(due("2024-01-02")).toBeDefined();'),
             "src/due_check.ts:3 — "),
            ("python test line", lambda: self.edit_line(
                "tests/test_b.py", 12, "    assert total"), "tests/test_b.py:12 — "),
            ("ruby spec line", lambda: self.edit_line(
                "spec/b_spec.rb", 12, "    expect(total).to be_truthy"),
             "spec/b_spec.rb:12 — "),
            ("test named by its file name", lambda: self.edit_line(
                "src/total.test.ts", 3, "  expect(total([1, 2])).toBeDefined();"),
             "src/total.test.ts:3 — "),
        ]
        for name, change, reason in cases:
            with self.subTest(change=name):
                self.reset()
                self.write_record()
                change()
                out = self.pick()
                self.assertEqual(out["result"], "RERUN_ALL", out)
                self.assertEqual(self.rerun_ids(out), EVERY_MUTANT, out)
                self.assertEqual(out["carried"], [], out)
                self.assertTrue((out["reason"] or "").startswith(reason), out)
        with self.subTest(change="the same edit to a file that is no test"):
            self.reset()
            self.write_record()
            self.edit_line("src/notes.ts", 2, "export const note = 0;")
            out = self.pick()
            self.assertEqual(out["result"], "RERUN", out)
            self.assertEqual(self.carried(out).get("M1"), "killed", out)

    def test_tests_only_appended_keep_the_kills(self):
        for rel, text in (("tests/b.test.ts", NEW_TS_TEST), ("tests/test_b.py", NEW_PY_TEST)):
            with self.subTest(appended=rel):
                self.reset()
                self.write_record()
                self.append(rel, text)
                out = self.pick()
                self.assertEqual(out["result"], "RERUN", out)
                self.assertEqual(self.rerun_ids(out), ["M2"], out)
                self.assertEqual(self.carried(out),
                                 {"M1": "killed", "M3": "killed", "M4": "timeout"}, out)

    def test_a_new_test_file_with_a_skip_or_focus_marker_forces_every_mutant(self):
        cases = (
            ("focus marker", "tests/c.test.ts", 'it.only("now", () => {});\n',
             'it("now", () => {});\n'),
            ("skip marker", "tests/c.test.ts", 'it.skip("later", () => {});\n',
             'it("later", () => {});\n'),
            ("python skip marker", "tests/test_c.py",
             "@pytest.mark.skip\ndef test_later():\n    pass\n",
             "def test_later():\n    pass\n"),
        )
        for name, rel, marked, plain in cases:
            with self.subTest(new_file=name):
                self.reset()
                self.first_pass()
                self.write(rel, marked)
                out = self.pick()
                self.assertEqual(out["result"], "RERUN_ALL", out)
                self.assertEqual(self.rerun_ids(out), EVERY_MUTANT, out)
                self.assertEqual(out["carried"], [], out)
                self.assertEqual(out["reason"], f"{rel}:1 — a skip or focus marker was added")
            with self.subTest(new_file=f"{name}, the control without it"):
                self.reset()
                self.first_pass()
                self.write(rel, plain)
                out = self.pick()
                self.assertEqual(out["result"], "RERUN", out)
                self.assertEqual(self.carried(out),
                                 {"M1": "killed", "M3": "killed", "M4": "timeout"}, out)

    def test_a_test_file_replaced_by_a_symlink_forces_every_mutant(self):
        self.first_pass()
        self.assertEqual(self.carried(self.pick()).get("M1"), "killed")  # the control
        (self.wt / "tests/a.test.ts").unlink()
        os.symlink("b.test.ts", self.wt / "tests/a.test.ts")
        out = self.pick()
        self.assertEqual(out["result"], "RERUN_ALL", out)
        self.assertEqual(self.rerun_ids(out), EVERY_MUTANT, out)
        self.assertEqual(out["carried"], [], out)
        self.assertEqual(out["reason"],
                         "tests/a.test.ts — a test file was replaced by another kind of file")

    def test_appending_to_a_test_file_without_a_final_newline_keeps_the_kills(self):
        old = MUT_FILES["tests/a.test.ts"].rstrip("\n")  # its last line, 5, is "});"
        for name, new in (("new file ends in a newline", old + "\n" + NEW_TS_TEST),
                          ("new file ends without one", old + "\n" + NEW_TS_TEST.rstrip("\n"))):
            with self.subTest(append=name):
                self.reset()
                self.write("tests/a.test.ts", old)
                self.first_pass()
                self.write("tests/a.test.ts", new)
                out = self.pick()
                self.assertEqual(out["result"], "RERUN", out)
                self.assertEqual(self.rerun_ids(out), ["M2"], out)
                self.assertEqual(self.carried(out),
                                 {"M1": "killed", "M3": "killed", "M4": "timeout"}, out)
        with self.subTest(append="the control: the old last line's text changes too"):
            self.reset()
            self.write("tests/a.test.ts", old)
            self.first_pass()
            self.write("tests/a.test.ts", old[:-len("});")] + "}); // done\n" + NEW_TS_TEST)
            out = self.pick()
            self.assertEqual(out["result"], "RERUN_ALL", out)
            self.assertEqual(out["carried"], [], out)
            self.assertEqual(out["reason"],
                             "tests/a.test.ts:5 — an existing test line was changed or removed")

    def test_a_caught_mutant_at_a_path_git_does_not_list_reruns(self):
        os.symlink("src", self.wt / "lib")
        self.git("add", "lib")
        self.git("commit", "-q", "-m", "lib")
        via_link = {**MUT_SET[0], "id": "M6", "file": "lib/a.ts"}
        self.add_mutant(via_link)
        self.write_record(results=[{**m, "status": MUT_STATUSES[m["id"]]} for m in MUT_SET]
                          + [{**via_link, "status": "killed"}])
        out = self.pick()
        why = {m["id"]: m["why"] for m in out["rerun"]}
        self.assertEqual(why.get("M6"), "lib/a.ts is not in the tree now", out)
        self.assertNotIn("M6", self.carried(out), out)
        self.assertEqual(self.carried(out).get("M1"), "killed", out)  # same code, via src/

    def test_no_record_means_every_mutant_runs(self):
        out = self.pick()  # a run started on 4.7: a set but no record
        self.assertEqual(out["result"], "RERUN_ALL", out)
        self.assertEqual(self.rerun_ids(out), EVERY_MUTANT, out)
        self.assertIn("no previous results were recorded", out["reason"], out)
        self.assertEqual(out["carried"], [], out)
        self.write_record()  # the control: with a record, the same set carries M1
        self.assertEqual(self.carried(self.pick()).get("M1"), "killed")

    def test_recorded_tree_must_be_a_tree_object_here(self):
        head = self.git("rev-parse", "HEAD").strip()
        for name, tree in (("unknown hash", "0" * 40), ("a commit id", head),
                           ("HEAD", "HEAD"), ("an option", "--output=x"), ("no tree", None)):
            with self.subTest(tree=name):
                self.reset()
                self.write_record()
                record = json.loads(self.record_file.read_text())
                if tree is None:
                    del record["tree"]
                else:
                    record["tree"] = tree
                self.record_file.write_text(json.dumps(record))
                out = self.pick()
                self.assertEqual(out["result"], "RERUN_ALL", out)
                self.assertEqual(self.rerun_ids(out), EVERY_MUTANT, out)
                self.assertEqual(out["carried"], [], out)
                self.assertIn("is not a tree in this repository", out["reason"], out)
                for where in (self.wt, self.tmp, self.cwd, Path.cwd()):
                    self.assertFalse((where / "x").exists(), where)

    def test_recorded_tree_must_be_a_full_tree_hash(self):
        # Both name the recorded tree to git, so only the hash pattern refuses them.
        for name in ("HEAD^{tree}", "a 12-character prefix"):
            with self.subTest(tree=name):
                self.reset()
                self.write_record()
                record = json.loads(self.record_file.read_text())
                record["tree"] = (name if name == "HEAD^{tree}"
                                  else record["tree"][:12])
                self.record_file.write_text(json.dumps(record))
                out = self.pick()
                self.assertEqual(out["result"], "RERUN_ALL", out)
                self.assertEqual(self.rerun_ids(out), EVERY_MUTANT, out)
                self.assertEqual(out["carried"], [], out)
        with self.subTest(tree="the full hash, the control"):
            self.reset()
            self.write_record()
            self.assertEqual(self.carried(self.pick()).get("M1"), "killed")

    def test_an_edited_binary_test_file_forces_every_mutant(self):
        path = self.wt / "tests/__snapshots__/a.png"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x01")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "snapshot")
        self.first_pass()
        path.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x02")
        out = self.pick()
        self.assertEqual(out["result"], "RERUN_ALL", out)
        self.assertEqual(self.rerun_ids(out), EVERY_MUTANT, out)
        self.assertEqual(out["carried"], [], out)
        self.assertIn("tests/__snapshots__/a.png", out["reason"] or "", out)

    def test_unusable_record_means_every_mutant_runs(self):
        good = [{**m, "status": MUT_STATUSES[m["id"]]} for m in MUT_SET]
        cases = (
            ("not JSON", "{not json"),
            ("a list", json.dumps(good)),
            ("results not a list", json.dumps({"tree": "x", "results": {"M1": "killed"}})),
            ("no status", [{k: v for k, v in good[0].items() if k != "status"}] + good[1:]),
            ("status passed", [{**good[0], "status": "passed"}] + good[1:]),
            ("bad status, id not in the set",
             good + [{"id": "M9", "file": "src/c.ts", "find": "x", "replace": "y",
                      "status": "passed"}]),
            ("two results for M1", good + [good[0]]),
            ("an id that is a list", good + [{**good[1], "id": ["M2"]}]),
        )
        for name, body in cases:
            with self.subTest(record=name):
                self.reset()
                if isinstance(body, list):
                    self.write_record(results=body)
                else:
                    self.record_file.write_text(body)
                out = self.pick()
                self.assertEqual(out["result"], "RERUN_ALL", out)
                self.assertEqual(self.rerun_ids(out), EVERY_MUTANT, out)
                self.assertEqual(out["carried"], [], out)
                self.assertIn("mutation-record.json", out["reason"], out)
                self.assertNotIn("\n", out["reason"], out)

    def test_unreadable_set_or_plain_folder_cannot_run(self):
        self.write_record()
        no_find = [{k: v for k, v in MUT_SET[0].items() if k != "find"}, *MUT_SET[1:]]
        for name, body in (("not JSON", "[{"), ("missing", None),
                           ("an entry without find", json.dumps(no_find))):
            with self.subTest(set=name):
                path = self.evidence / "mutation-set.json"
                if body is None:
                    path.unlink()
                else:
                    path.write_text(body)
                r = self.mutants("select")
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                self.assertIn("ERROR:", r.stderr)
                self.assertIn("mutation-set.json", r.stderr)
                self.assertNotIn("rerun:", r.stdout)
                self.set_mutants(MUT_SET)
        with self.subTest(set="in a folder outside git"):
            plain = self.tmp / "plain" / ".auto-dev"
            (plain / "evidence").mkdir(parents=True)
            (plain / "evidence" / "mutation-set.json").write_text(json.dumps(MUT_SET))
            r = self.mutants("select", ad=plain)
            self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
            self.assertIn("ERROR:", r.stderr)
            self.assertIn("check-fresh.py", r.stderr)
            self.assertNotIn("rerun:", r.stdout)

    def test_each_malformed_set_cannot_run(self):
        self.write_record()
        m1 = MUT_SET[0]
        cases = (
            ("not a list", {}, "is not a JSON list"),
            ("an entry that is no object", [1], "entry 1 is not an object"),
            ("an empty id", [{**m1, "id": ""}], "entry 1 has no id"),
            ("no id", [{k: v for k, v in m1.items() if k != "id"}], "entry 1 has no id"),
            ("no file", [{k: v for k, v in m1.items() if k != "file"}],
             "entry 1 (M1) has no file"),
            ("a replace that is no string", [{**m1, "replace": None}],
             "entry 1 (M1) has no string replace"),
            ("two entries with one id", [m1, *MUT_SET[1:], {**MUT_SET[1], "id": "M1"}],
             "two entries for M1"),
        )
        for name, body, problem in cases:
            with self.subTest(set=name):
                (self.evidence / "mutation-set.json").write_text(json.dumps(body))
                r = self.mutants("select")
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                self.assertIn("ERROR: evidence/mutation-set.json", r.stderr)
                self.assertIn(problem, r.stderr)
                self.assertNotIn("rerun:", r.stdout)
                self.assertNotIn("carried:", r.stdout)

    def test_pick_leaves_status_index_branch_and_untracked_files_alone(self):
        self.write_record()
        self.edit_line("src/b.ts", 40, '  const label = "bee";')
        self.write("src/d.ts", "  return d > 1;\n")
        self.add_mutant({"id": "M6", "file": "src/d.ts", "line": 1, "find": "d > 1",
                         "replace": "d >= 1", "condition": "2"})

        def snapshot():
            return [self.git(*args) for args in (
                ("status", "--porcelain", "--untracked-files=all"), ("diff",),
                ("diff", "--cached"), ("ls-files", "--stage"),
                ("ls-files", "--others", "--exclude-standard"), ("rev-parse", "HEAD"),
                ("symbolic-ref", "HEAD"))]

        before = snapshot()
        out = self.pick()
        self.assertEqual(snapshot(), before)
        self.assertEqual(self.git("ls-files", "--", "src/d.ts"), "")
        self.assertIn("M6", self.rerun_ids(out), out)
        self.assertIn("M3", self.rerun_ids(out), out)
        self.assertEqual(self.carried(out).get("M1"), "killed", out)


class MutantRecordTest(MutantsCase):
    def test_first_pass_records_every_result(self):
        t1 = self.tree()
        self.run_results(self.ran(MUT_STATUSES), 1)
        code, out = self.rec("--tree", t1)
        self.assertEqual(code, 0, out)
        self.assertEqual(out["result"], "RECORDED", out)
        self.assertEqual(out["summary"], "4 mutants: 2 killed · 1 timeout · 1 survived "
                                         "· 0 invalid · 0 carried forward")
        self.assertEqual(out["survived"], ["M2 src/a.ts:14"])
        record = json.loads(self.record_file.read_text())
        self.assertEqual(record["tree"], t1)
        self.assertEqual({r["id"]: r["status"] for r in record["results"]}, MUT_STATUSES)
        self.assertNotIn("output", json.dumps(record))

    def test_recorded_pass_becomes_the_next_baseline(self):
        self.first_pass()
        lines = self.read("src/a.ts").split("\n")  # correction 1: M1 moves to line 12
        self.write("src/a.ts", "\n".join([*lines[:9], "  // guard", "  // more", *lines[9:]]))
        self.assertEqual(self.rerun_ids(self.pick()), ["M1", "M2"])
        t2 = self.tree()
        self.run_results(self.ran({"M1": "killed", "M2": "killed"}, {"M1": 12, "M2": 16}), 0)
        code, out = self.rec("--tree", t2)
        self.assertEqual(code, 0, out)
        self.assertEqual(json.loads(self.record_file.read_text())["tree"], t2)
        self.edit_line("src/b.ts", 40, '  const label = "bee";')  # correction 2
        out = self.pick()
        self.assertEqual(self.rerun_ids(out), ["M3"], out)
        self.assertEqual(self.carried(out), {"M1": "killed", "M2": "killed", "M4": "timeout"})
        self.assertEqual({m["id"]: m["line"] for m in out["carried"]}["M1"], 12)

    def test_unfinished_pass_keeps_the_old_record(self):
        def interrupted():
            self.run_results(self.ran({"M1": "killed", "M2": "killed"}), 6)

        def never_ended():
            self.run_results(self.ran({"M1": "killed", "M2": "killed"}), None)

        def no_results():
            (self.evidence / "mutate.exit").write_text("0\n")

        for name, run in (("exit 6", interrupted), ("no exit file", never_ended),
                          ("no results file", no_results)):
            with self.subTest(run=name):
                self.reset()
                self.first_pass()
                kept = self.record_file.read_bytes()
                self.edit_line("src/a.ts", 3, "export const a3 = 33;")  # correction 1
                run()
                code, out = self.rec("--tree", self.tree())
                self.assertEqual(code, 3, out)
                self.assertEqual(out["result"], "KEPT", out)
                self.assertEqual(self.record_file.read_bytes(), kept)
                self.edit_line("src/b.ts", 40, '  const label = "bee";')  # correction 2
                out = self.pick()  # still compared with pass 1
                self.assertEqual(self.rerun_ids(out), ["M1", "M2", "M3"], out)
                self.assertEqual(self.carried(out), {"M4": "timeout"}, out)

    def test_a_re_check_whose_named_mutants_were_all_invalid_records(self):
        # mutate.py writes every result, then exits 8 when none was applied.
        self.first_pass({**MUT_STATUSES, "M2": "invalid"}, code=0)
        self.append("tests/a.test.ts", NEW_TS_TEST)  # a correction only adds a test
        out = self.pick()
        self.assertEqual(self.rerun_ids(out), ["M2"], out)
        self.run_results(self.ran({"M2": "invalid"}), 8)
        t2 = self.tree()
        code, out = self.rec("--tree", t2)
        self.assertEqual(code, 0, out)
        self.assertEqual(out["result"], "RECORDED", out)
        self.assertEqual(out["summary"], "4 mutants: 2 killed · 1 timeout · 0 survived "
                                         "· 1 invalid · 3 carried forward")
        self.assertEqual(out["survived"], [], out)
        record = json.loads(self.record_file.read_text())
        self.assertEqual(record["tree"], t2)
        self.assertEqual({r["id"]: r["status"] for r in record["results"]},
                         {**MUT_STATUSES, "M2": "invalid"})
        for name in ("mutants.json.results.json", "mutate.exit"):
            (self.evidence / name).unlink()
        out = self.pick()
        self.assertEqual(out["base"], t2, out)
        self.assertEqual(self.rerun_ids(out), ["M2"], out)
        self.assertEqual(self.carried(out), {"M1": "killed", "M3": "killed", "M4": "timeout"})

    def test_a_pass_that_cannot_be_recorded_keeps_whatever_record_there_is(self):
        with self.subTest(record="none", run="the scoped tests failed unmutated"):
            self.reset()
            (self.evidence / "mutate.exit").write_text("3\n")
            code, out = self.rec("--tree", self.tree())
            self.assertEqual(code, 3, out)
            self.assertEqual(out["result"], "KEPT", out)
            self.assertIn("(there is none)", out["message"])
            self.assertFalse(self.record_file.exists())
        with self.subTest(record="none", run="the code changed during the pass"):
            self.reset()
            noted = self.tree()
            self.run_results(self.ran(MUT_STATUSES), 1)
            self.edit_line("src/notes.ts", 2, "export const note = 0;")
            code, out = self.rec("--tree", noted)
            self.assertEqual(code, 3, out)
            self.assertEqual(out["result"], "KEPT", out)
            self.assertIn("(there is none)", out["message"])
            self.assertIn("the code changed during the pass", out["message"])
            self.assertFalse(self.record_file.exists())
        with self.subTest(record="unusable", run="interrupted"):
            self.reset()
            self.record_file.write_text("{not json")
            self.run_results(self.ran(MUT_STATUSES), 6)
            code, out = self.rec("--tree", self.tree())
            self.assertEqual(code, 3, out)
            self.assertEqual(out["result"], "KEPT", out)
            self.assertIn("(it is unusable)", out["message"])
            self.assertEqual(self.record_file.read_bytes(), b"{not json")

    def test_any_id_the_set_accepts_records_and_prints(self):
        self.set_mutants([{**MUT_SET[0], "id": "M 1"}, *MUT_SET[1:]])
        self.run_results(self.ran({"M 1": "survived", "M2": "survived", "M3": "killed",
                                   "M4": "killed"}), 1)
        r = self.mutants("record", "--tree", self.tree())
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        lines = [line.strip() for line in r.stdout.splitlines()]
        self.assertTrue(lines[0].startswith("RECORDED: 4 result(s)"), r.stdout)
        self.assertEqual([ln for ln in lines if ln.startswith("survived:")],
                         ["survived: M 1 src/a.ts:10", "survived: M2 src/a.ts:14"])
        ids = [x["id"] for x in json.loads(self.record_file.read_text())["results"]]
        self.assertEqual(ids, ["M 1", "M2", "M3", "M4"])

    def test_the_only_named_mutant_leaving_the_set_records_the_carried_ones(self):
        self.first_pass({**MUT_STATUSES, "M2": "killed", "M4": "survived"})
        (self.wt / "src/c.ts").unlink()  # M4's file is gone
        self.assertEqual(self.rerun_ids(self.pick()), ["M4"])
        self.set_mutants([m for m in MUT_SET if m["id"] != "M4"])
        self.assertFalse((self.evidence / "mutate.exit").exists())  # mutate.py never ran
        t2 = self.tree()
        code, out = self.rec("--tree", t2)
        self.assertEqual(code, 0, out)
        self.assertEqual(out["result"], "RECORDED", out)
        self.assertEqual(out["summary"], "3 mutants: 3 killed · 0 timeout · 0 survived "
                                         "· 0 invalid · 3 carried forward")
        record = json.loads(self.record_file.read_text())
        self.assertEqual(record["tree"], t2)
        self.assertEqual([x["id"] for x in record["results"]], ["M1", "M2", "M3"])

    def test_a_carried_mutant_that_ran_this_pass_takes_this_run_s_result(self):
        self.first_pass()
        self.assertEqual(self.rerun_ids(self.pick()), ["M2"])
        # The whole set ran (after a repaired set, say): M1 survived this time;
        # M3's result is for other code, so it is no result of M3's.
        m3_elsewhere = {**MUT_SET[2], "find": "limit < 6", "status": "survived"}
        self.run_results(self.ran({"M1": "survived", "M2": "killed"}) + [m3_elsewhere], 1)
        code, out = self.rec("--tree", self.tree())
        self.assertEqual(code, 0, out)
        self.assertEqual(out["summary"], "4 mutants: 2 killed · 1 timeout · 1 survived "
                                         "· 0 invalid · 2 carried forward")
        self.assertEqual(out["survived"], ["M1 src/a.ts:10"])
        record = json.loads(self.record_file.read_text())
        self.assertEqual({x["id"]: x["status"] for x in record["results"]},
                         {"M1": "survived", "M2": "killed", "M3": "killed", "M4": "timeout"})
        for name in ("mutants.json.results.json", "mutate.exit"):
            (self.evidence / name).unlink()
        self.assertEqual(self.rerun_ids(self.pick()), ["M1"])

    def test_code_moving_under_the_pass_keeps_the_old_record(self):
        self.first_pass()
        kept = self.record_file.read_bytes()
        self.edit_line("src/a.ts", 3, "export const a3 = 33;")
        t2 = self.tree()
        self.run_results(self.ran({"M1": "killed", "M2": "killed"}), 0)
        self.edit_line("src/notes.ts", 2, "export const note = 0;")  # after T2 was noted
        for tree in (t2, "changed during the run"):
            with self.subTest(tree=tree):
                code, out = self.rec("--tree", tree)
                self.assertEqual(code, 3, out)
                self.assertEqual(out["result"], "KEPT", out)
                self.assertIn("the code changed during the pass", out["message"])
                self.assertEqual(self.record_file.read_bytes(), kept)

    def test_named_mutant_without_a_result_is_refused(self):
        self.first_pass()
        kept = self.record_file.read_bytes()
        self.edit_line("src/a.ts", 3, "export const a3 = 33;")
        self.assertEqual(self.rerun_ids(self.pick()), ["M1", "M2"])
        self.run_results(self.ran({"M1": "killed"}), 1)
        code, out = self.rec("--tree", self.tree())
        self.assertEqual(code, 1, out)
        self.assertEqual(out["result"], "INCOMPLETE", out)
        self.assertEqual(out["missing"], ["M2"], out)
        self.assertEqual(self.record_file.read_bytes(), kept)

    def test_nothing_to_run_still_records_the_carried_results(self):
        self.first_pass({**MUT_STATUSES, "M2": "killed"}, code=0)
        self.append("tests/b.test.ts", NEW_TS_TEST)
        self.assertEqual(self.rerun_ids(self.pick()), [])
        # A results file left from an earlier run must not count.
        self.run_results(self.ran({"M1": "survived"}), 1)
        t2 = self.tree()
        code, out = self.rec("--tree", t2)
        self.assertEqual(code, 0, out)
        self.assertEqual(out["summary"], "4 mutants: 3 killed · 1 timeout · 0 survived "
                                         "· 0 invalid · 4 carried forward")
        record = json.loads(self.record_file.read_text())
        self.assertEqual(record["tree"], t2)
        self.assertEqual({r["id"]: r["status"] for r in record["results"]},
                         {**MUT_STATUSES, "M2": "killed"})

    def test_summary_counts_each_mutant_once(self):
        self.write_record({"M1": "killed", "M2": "survived", "M3": "killed", "M4": "killed"})
        self.add_mutant(M5_AT_20)
        out = self.pick()
        self.assertEqual(self.rerun_ids(out), ["M2", "M5"], out)
        self.run_results(self.ran({"M2": "killed", "M5": "survived"}), 1)
        code, out = self.rec("--tree", self.tree())
        self.assertEqual(code, 0, out)
        self.assertEqual(out["summary"], "5 mutants: 4 killed · 0 timeout · 1 survived "
                                         "· 0 invalid · 3 carried forward")
        self.assertEqual(out["survived"], ["M5 src/b.ts:20"])
        self.assertEqual(len(json.loads(self.record_file.read_text())["results"]), 5)

    def test_mutant_removed_from_the_set_is_not_recorded(self):
        self.first_pass()
        self.delete_line("src/a.ts", 14)  # M2's code is gone
        self.set_mutants([m for m in MUT_SET if m["id"] != "M2"])
        self.run_results(self.ran({"M1": "killed"}), 0)
        code, out = self.rec("--tree", self.tree())
        self.assertEqual(code, 0, out)
        self.assertTrue(out["summary"].startswith("3 mutants: "), out)
        ids = [r["id"] for r in json.loads(self.record_file.read_text())["results"]]
        self.assertEqual(ids, ["M1", "M3", "M4"])

    def test_record_without_a_tree_cannot_run(self):
        self.run_results(self.ran(MUT_STATUSES), 1)
        r = self.mutants("record")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("mutants record needs --tree", r.stderr)
        self.assertFalse(self.record_file.exists())

    def select_and_record_with_saved_cold_run(self, saved):
        """The last pass killed M1 and M2 and saw M3 survive; select, re-run M3
        (killed), record. `saved` is the saved cold-run time's text beside the
        set, or None for a set as 4.8.0 left it, with no saved time."""
        self.reset()
        self.set_mutants(MUT_SET[:3])
        cold = self.evidence / "mutation-cold-run.txt"
        if saved is None:
            cold.unlink(missing_ok=True)
        else:
            cold.write_text(saved)
        last = {"M1": "killed", "M2": "killed", "M3": "survived"}
        self.write_record(results=[{**m, "status": last[m["id"]]} for m in MUT_SET[:3]])
        text = self.mutants("select")
        picked = self.mutants("select", "--json")
        self.run_results(self.ran({"M3": "killed"}), 0)
        recorded = self.mutants("record", "--json", "--tree", self.tree())
        return [(r.returncode, r.stdout, r.stderr) for r in (text, picked, recorded)]

    def test_a_saved_cold_run_time_changes_nothing_select_and_record_report(self):
        without = self.select_and_record_with_saved_cold_run(None)
        saved = self.select_and_record_with_saved_cold_run("42\n")
        (code, text, err), (_, picked, _), (rcode, recorded, rerr) = saved
        self.assertEqual(code, 0, text + err)
        self.assertEqual(text.splitlines()[0].strip(), "RERUN: 1 to re-run, 2 carried forward")
        self.assertEqual([m["id"] for m in json.loads(picked)["rerun"]], ["M3"], picked)
        self.assertEqual(rcode, 0, recorded + rerr)
        self.assertEqual(json.loads(recorded)["result"], "RECORDED", recorded)
        self.assertEqual(saved, without)

    def test_a_set_without_a_usable_saved_cold_run_time_selects_and_records_as_before(self):
        before = self.select_and_record_with_saved_cold_run(None)  # a set 4.8.0 wrote
        for code, out, err in before:
            self.assertEqual(code, 0, out + err)
        self.assertEqual(before[0][1].splitlines()[0].strip(),
                         "RERUN: 1 to re-run, 2 carried forward")
        for saved in ("abc\n", "0\n", "-5\n", "-0.5\n", ""):
            with self.subTest(saved=saved):
                self.assertEqual(self.select_and_record_with_saved_cold_run(saved), before)



class MutantColdRunFileTest(MutantsCase):
    """The verifier keeps its cold test-run time in evidence/mutation-cold-run.txt,
    beside the set. `mutants select` and `mutants record` never read it."""

    def outcome(self, stored):
        """Each command's (code, stdout, stderr) with `stored` as the timing
        file's text (None: no file), and the file's text afterwards."""
        self.reset()
        self.set_mutants(MUT_SET[:3])
        cold = self.evidence / "mutation-cold-run.txt"
        if stored is None:
            cold.unlink(missing_ok=True)
        else:
            cold.write_text(stored)
        statuses = {"M1": "killed", "M2": "killed", "M3": "survived"}
        self.write_record(results=[{**m, "status": statuses[m["id"]]} for m in MUT_SET[:3]])
        calls = [self.mutants("select"), self.mutants("select", "--json")]
        self.run_results(self.ran({"M3": "killed"}), 0)
        calls.append(self.mutants("record", "--json", "--tree", self.tree()))
        return ([(r.returncode, r.stdout, r.stderr) for r in calls],
                cold.read_text() if cold.exists() else None)

    def test_a_stored_cold_time_leaves_select_and_record_output_unchanged(self):
        baseline, left = self.outcome(None)  # a set as 4.8 left it
        self.assertIsNone(left)
        (code, text, _), (jcode, js, _), (rcode, rec, _) = baseline
        self.assertEqual(code, 0, text)
        self.assertEqual(text.splitlines()[0], "RERUN: 1 to re-run, 2 carried forward", text)
        self.assertEqual(jcode, 0, js)
        picked = json.loads(js)
        self.assertEqual(self.rerun_ids(picked), ["M3"])
        self.assertEqual(self.carried(picked), {"M1": "killed", "M2": "killed"})
        self.assertEqual(rcode, 0, rec)
        recorded = json.loads(rec)
        self.assertEqual(recorded["result"], "RECORDED")
        self.assertEqual(recorded["summary"], "3 mutants: 3 killed · 0 timeout · 0 survived "
                                              "· 0 invalid · 2 carried forward")
        for stored in ("42\n", "abc\n", "0\n", "-5\n", ""):
            with self.subTest(stored=stored):
                calls, left = self.outcome(stored)
                self.assertEqual(calls, baseline)
                self.assertEqual(left, stored)

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


# ------------------------------------------------------------------ mutants
# A verifier re-check runs again only the mutants whose earlier result may be
# stale (`autodev.py mutants select`), and each finished pass is recorded as the
# next pass's baseline (`autodev.py mutants record`). The throwaway repo's
# source and tests are an example in TypeScript, with one Python and one Ruby
# test file for the cross-stack cases.

def stale_lines(count, special, prefix):
    """`count` lines ending in a newline; `special` maps a 1-based line to its text."""
    return "".join(special.get(i, f"{prefix}{i};") + "\n" for i in range(1, count + 1))


STALE_FILES = {
    "src/a.ts": stale_lines(20, {10: "  return total > 0;", 14: "  return count + 1;"},
                            "export const a"),
    "src/b.ts": stale_lines(45, {10: "  if (limit < 5) return;", 20: "  return limit * 2;",
                                 40: '  const label = "b";'}, "export const b"),
    "src/c.ts": stale_lines(5, {3: "  while (busy) wait();"}, "export const c"),
    "src/notes.ts": stale_lines(4, {}, "export const note"),
    "src/due_check.ts": stale_lines(6, {3: '  expect(due("2024-01-02")).toBe(true);'},
                                    "export const dueCheck"),
    "src/total.test.ts": stale_lines(6, {3: "  expect(total([1, 2])).toBe(3);"},
                                     "export const totalTest"),
    "tests/a.test.ts": ('import { total } from "../src/a";\n\n'
                        'it("totals", () => {\n  expect(total([1])).toBe(true);\n});\n'),
    "tests/b.test.ts": ('import { sum } from "../src/b";\n\ndescribe("sum", () => {\n'
                        '  it("adds", () => {\n    const total = sum([4, 6]);\n'
                        "    log(total);\n    check(total);\n\n    // totals\n"
                        "    note(total);\n    keep(total);\n"
                        "    expect(total).toBe(10);\n  });\n});\n// end of the sum tests\n"),
    "tests/fixtures/totals.json": '{"total": 10}\n',
    "tests/test_b.py": ("from b import total_of\n\n\ndef test_total():\n"
                        "    total = total_of([4, 6])\n    a = 1\n    b = 2\n    c = 3\n"
                        "    d = 4\n    e = 5\n    f = 6\n    assert total == 10\n"),
    "spec/b_spec.rb": ('require "b"\n\nRSpec.describe "sum" do\n  it "adds" do\n'
                       "    total = sum([4, 6])\n    a = 1\n    b = 2\n    c = 3\n"
                       "    d = 4\n    e = 5\n    f = 6\n    expect(total).to eq(10)\n"
                       "  end\nend\n"),
    "package.json": '{"name": "app", "scripts": {"test": "jest"}}\n',
    "README.md": "# app\n\nSums things.\n",
}

STALE_SET = [
    {"id": "M1", "file": "src/a.ts", "line": 10, "find": "total > 0",
     "replace": "total >= 0", "condition": "1"},
    {"id": "M2", "file": "src/a.ts", "line": 14, "find": "count + 1",
     "replace": "count - 1", "condition": "1"},
    {"id": "M3", "file": "src/b.ts", "line": 10, "find": "limit < 5",
     "replace": "limit <= 5", "condition": "2"},
    {"id": "M4", "file": "src/c.ts", "line": 3, "find": "while (busy)",
     "replace": "while (true)", "condition": "3"},
]
STALE_M5_LINE20 = {"id": "M5", "file": "src/b.ts", "line": 20, "find": "limit * 2",
                   "replace": "limit * 3", "condition": "2"}
APPENDED_TS_TEST = ('describe("sum again", () => {\n  it("adds zero", () => {\n'
                    "    expect(sum([0])).toBe(0);\n  });\n});\n")
FIRST_PASS = {"M1": "killed", "M2": "survived", "M3": "killed", "M4": "timeout"}


class StaleMutantRepoCase(unittest.TestCase):
    """A committed throwaway repo with its .auto-dev/ (git-ignored), an installed
    acceptance check at src/due_check.ts, and a mutation set M1 to M4."""

    def setUp(self):
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp()))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.wt = self.tmp / "app"
        self.ad = self.wt / ".auto-dev"
        self.evidence = self.ad / "evidence"
        self.cwd = self.tmp / "cwd"
        self.cwd.mkdir()
        self.wt.mkdir()
        self.git("init", "-q", "-b", "main")
        for rel, text in STALE_FILES.items():
            self.write(rel, text)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "init")
        self.prepare_artifacts()

    def prepare_artifacts(self, mutants=STALE_SET):
        self.write(".auto-dev/.gitignore", "*\n")
        self.write(".auto-dev/acceptance/files/src/due_check.ts.sealed",
                   STALE_FILES["src/due_check.ts"])
        self.write(".auto-dev/acceptance/INSTALLED", "src/due_check.ts\n")
        self.evidence.mkdir(parents=True, exist_ok=True)
        self.set_mutants(mutants)

    def reset(self, mutants=STALE_SET):
        """Back to the committed tree, with no record and a fresh set."""
        self.git("reset", "-q", "--hard")
        self.git("clean", "-qfd")
        shutil.rmtree(self.evidence, ignore_errors=True)
        self.prepare_artifacts(mutants)

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.wt), *args], env=BASE_ENV,
                              capture_output=True, text=True, check=True).stdout

    def write(self, rel, text):
        path = self.wt / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def read(self, rel):
        return (self.wt / rel).read_text()

    def edit_line(self, rel, n, text):
        lines = self.read(rel).split("\n")
        lines[n - 1] = text
        self.write(rel, "\n".join(lines))

    def delete_line(self, rel, n):
        lines = self.read(rel).split("\n")
        del lines[n - 1]
        self.write(rel, "\n".join(lines))

    def append(self, rel, text):
        self.write(rel, self.read(rel) + text)

    def set_mutants(self, mutants):
        (self.evidence / "mutation-set.json").write_text(json.dumps(mutants, indent=2))

    def mutants(self):
        return json.loads((self.evidence / "mutation-set.json").read_text())

    def add_mutant(self, entry):
        self.set_mutants([*self.mutants(), entry])

    def record_path(self):
        return self.evidence / "mutation-record.json"

    def edit_record(self, change):
        record = json.loads(self.record_path().read_text())
        change(record)
        self.record_path().write_text(json.dumps(record))

    def tree(self):
        return subprocess.run([sys.executable, str(SCRIPTS / "check-fresh.py"),
                               "--print-tree", str(self.wt)], env=BASE_ENV,
                              capture_output=True, text=True, check=True).stdout.strip()

    def mutants_cmd(self, *args, ad=None):
        return subprocess.run([sys.executable, str(AUTODEV), "mutants", *args, "--dir",
                               str(ad or self.ad)], env=BASE_ENV, capture_output=True,
                              text=True, cwd=self.cwd, check=False)

    def pick(self):
        """Run the selection as the verifier does; returns its JSON."""
        r = self.mutants_cmd("select", "--json")
        self.assertEqual(r.returncode, 0, f"mutants select:\n{r.stdout}{r.stderr}")
        return json.loads(r.stdout)

    def rerun(self, out):
        return sorted(m["id"] for m in out["rerun"])

    def carried(self, out):
        return {m["id"]: m["status"] for m in out["carried"]}

    def run_results(self, statuses, code, lines=None):
        """What one mutate.py run leaves: the mutants it ran, their results and
        its exit file (`code` None: no exit file, as when it never ended)."""
        lines = lines or {}
        ran = [{**m, "line": lines.get(m["id"], m["line"])} for m in self.mutants()
               if m["id"] in statuses]
        (self.evidence / "mutants.json").write_text(json.dumps(ran, indent=2))
        (self.evidence / "mutants.json.results.json").write_text(json.dumps(
            [{**m, "status": statuses[m["id"]], "output": "tests ran"} for m in ran],
            indent=2))
        if code is not None:
            (self.evidence / "mutate.exit").write_text(f"{code}\n")

    def clear_run(self):
        """The verifier deletes the last run's files before the next one."""
        for name in ("mutants.json", "mutants.json.results.json", "mutate.exit"):
            (self.evidence / name).unlink(missing_ok=True)

    def record(self, tree):
        return self.mutants_cmd("record", "--tree", tree)

    def finish_pass(self, statuses, code, lines=None):
        """A pass that ran `statuses` and finished: record it at the tree now."""
        self.run_results(statuses, code, lines)
        r = self.record(self.tree())
        self.assertEqual(r.returncode, 0, f"mutants record:\n{r.stdout}{r.stderr}")
        self.clear_run()
        return r

    def first_pass(self, statuses=None):
        statuses = statuses or FIRST_PASS
        self.finish_pass(statuses, 1 if "survived" in statuses.values() else 0)

    def has_count(self, text, n, word):
        return f" {n} {word}" in " " + text.replace("\n", " ")


class StaleMutantSelectionTest(StaleMutantRepoCase):
    def test_a_re_check_reruns_survivors_changed_files_and_new_mutants_and_carries_the_rest(self):
        self.first_pass()
        self.append("src/b.ts", "  return limit + 7;\n")
        self.append("tests/b.test.ts", APPENDED_TS_TEST)
        self.add_mutant({"id": "M5", "file": "src/b.ts", "line": 46, "find": "limit + 7",
                         "replace": "limit - 7", "condition": "2"})
        out = self.pick()
        self.assertEqual(self.rerun(out), ["M2", "M3", "M5"], out)
        self.assertEqual(self.carried(out), {"M1": "killed", "M4": "timeout"}, out)

    def test_any_edit_to_a_mutant_s_file_reruns_every_mutant_in_it(self):
        self.first_pass()
        self.edit_line("src/b.ts", 40, '  const label = "bee";')  # M3 is on line 10
        out = self.pick()
        self.assertEqual(self.rerun(out), ["M2", "M3"], out)
        self.assertEqual(self.carried(out), {"M1": "killed", "M4": "timeout"}, out)

    def test_a_file_put_back_to_its_verified_content_keeps_its_caught_mutants(self):
        self.first_pass()
        self.edit_line("src/a.ts", 10, "  return total > 1;")
        self.git("commit", "-q", "-am", "change a")
        self.write("src/a.ts", STALE_FILES["src/a.ts"])
        self.git("commit", "-q", "-am", "put a back")
        out = self.pick()
        self.assertEqual(self.rerun(out), ["M2"], out)
        self.assertEqual(self.carried(out),
                         {"M1": "killed", "M3": "killed", "M4": "timeout"}, out)

    def test_an_unchanged_tree_reruns_each_mutant_without_a_catch(self):
        for status in ("survived", "invalid"):
            with self.subTest(m2=status):
                self.reset()
                self.first_pass({**FIRST_PASS, "M2": status})
                out = self.pick()
                self.assertEqual(self.rerun(out), ["M2"], out)
                self.assertEqual(self.carried(out),
                                 {"M1": "killed", "M3": "killed", "M4": "timeout"}, out)

    def test_an_edited_test_line_reruns_every_mutant_and_names_the_line(self):
        self.first_pass()
        self.add_mutant(STALE_M5_LINE20)
        before = self.pick()  # the control: with no test edit, the kills carry
        self.assertIn("M1", self.carried(before), before)
        self.edit_line("tests/b.test.ts", 12, "    expect(total).toBeDefined();")
        out = self.pick()
        self.assertEqual(self.rerun(out), ["M1", "M2", "M3", "M4", "M5"], out)
        self.assertEqual(self.carried(out), {}, out)
        self.assertIn("tests/b.test.ts:12", out["reason"] or "", out)

    def test_each_kind_of_test_change_reruns_every_mutant(self):
        def rename(old, new):
            (self.wt / old).rename(self.wt / new)

        cases = [
            ("changed test line", lambda: self.edit_line(
                "tests/b.test.ts", 12, "    expect(total).toBeDefined();"),
             ["tests/b.test.ts:12"]),
            ("deleted test line", lambda: self.delete_line("tests/b.test.ts", 5),
             ["tests/b.test.ts:5"]),
            ("changed blank line", lambda: self.edit_line(
                "tests/b.test.ts", 8, "    // a note"), ["tests/b.test.ts:8"]),
            ("changed comment line", lambda: self.edit_line(
                "tests/b.test.ts", 9, "    // sums"), ["tests/b.test.ts:9"]),
            ("deleted test file", lambda: (self.wt / "tests/a.test.ts").unlink(),
             ["tests/a.test.ts"]),
            ("renamed test file", lambda: rename("tests/a.test.ts", "tests/a2.test.ts"),
             ["tests/a.test.ts", "tests/a2.test.ts"]),
            ("added skip marker", lambda: self.append(
                "tests/b.test.ts", 'it.skip("later", () => {});\n'),
             ["tests/b.test.ts:16"]),
            ("added focus marker", lambda: self.append(
                "tests/b.test.ts", 'it.only("now", () => {});\n'),
             ["tests/b.test.ts:16"]),
            ("added python skip marker", lambda: self.append(
                "tests/test_b.py", "\n\n@pytest.mark.skip\ndef test_later():\n    pass\n"),
             ["tests/test_b.py:15"]),
            ("edited package.json", lambda: self.write(
                "package.json", '{"name": "app", "scripts": {"test": "jest --bail"}}\n'),
             ["package.json"]),
            ("new runner config", lambda: self.write(
                "jest.config.ts", "export default { testPathIgnorePatterns: [] };\n"),
             ["jest.config.ts"]),
            ("new shared test helper", lambda: self.write(
                "conftest.py", "collect_ignore = []\n"), ["conftest.py"]),
            ("edited fixture data", lambda: self.write(
                "tests/fixtures/totals.json", '{"total": 11}\n'),
             ["tests/fixtures/totals.json"]),
            ("edited acceptance check", lambda: self.edit_line(
                "src/due_check.ts", 3, '  expect(due("2024-01-02")).toBeDefined();'),
             ["src/due_check.ts"]),
            ("python test line", lambda: self.edit_line(
                "tests/test_b.py", 12, "    assert total"), ["tests/test_b.py:12"]),
            ("ruby spec line", lambda: self.edit_line(
                "spec/b_spec.rb", 12, "    expect(total).to be_truthy"),
             ["spec/b_spec.rb:12"]),
            ("test named by its file name", lambda: self.edit_line(
                "src/total.test.ts", 3, "  expect(total([1, 2])).toBeDefined();"),
             ["src/total.test.ts:3"]),
        ]
        for name, change, causes in cases:
            with self.subTest(change=name):
                self.reset()
                self.first_pass()
                change()
                out = self.pick()
                self.assertEqual(self.rerun(out), ["M1", "M2", "M3", "M4"], out)
                self.assertEqual(self.carried(out), {}, out)
                reason = out["reason"] or ""
                self.assertTrue(any(c in reason for c in causes), out)
        with self.subTest(change="the same edit to a source file with no mutant"):
            self.reset()
            self.first_pass()
            self.edit_line("src/notes.ts", 2, "export const note = 0;")
            out = self.pick()
            self.assertEqual(self.rerun(out), ["M2"], out)
            self.assertEqual(self.carried(out),
                             {"M1": "killed", "M3": "killed", "M4": "timeout"}, out)

    def test_tests_only_added_rerun_only_the_survivors(self):
        cases = [
            ("a test appended in TypeScript", "tests/b.test.ts", APPENDED_TS_TEST),
            ("a test appended in Python", "tests/test_b.py",
             "\n\ndef test_zero():\n    assert total_of([0]) == 0\n"),
            ("a test appended in Ruby", "spec/b_spec.rb",
             ('\nRSpec.describe "zero" do\n  it "adds" do\n'
              "    expect(sum([0])).to eq(0)\n  end\nend\n")),
        ]
        for name, rel, text in cases:
            with self.subTest(change=name):
                self.reset()
                self.first_pass()
                self.append(rel, text)
                out = self.pick()
                self.assertEqual(self.rerun(out), ["M2"], out)
                self.assertEqual(self.carried(out),
                                 {"M1": "killed", "M3": "killed", "M4": "timeout"}, out)
        with self.subTest(change="a new test file"):
            self.reset()
            self.first_pass()
            self.write("tests/c.test.ts", 'it("waits", () => {\n  expect(1).toBe(1);\n});\n')
            out = self.pick()
            self.assertEqual(self.rerun(out), ["M2"], out)
            self.assertEqual(self.carried(out),
                             {"M1": "killed", "M3": "killed", "M4": "timeout"}, out)

    def test_a_new_test_and_a_docs_edit_rerun_only_the_survivor(self):
        self.first_pass()
        self.append("tests/a.test.ts", APPENDED_TS_TEST)
        self.append("README.md", "\nMore about sums.\n")
        out = self.pick()
        self.assertEqual(self.rerun(out), ["M2"], out)
        self.assertEqual(self.carried(out),
                         {"M1": "killed", "M3": "killed", "M4": "timeout"}, out)

    def test_no_survivors_and_only_a_new_test_runs_nothing_and_reports_every_mutant(self):
        self.first_pass({**FIRST_PASS, "M2": "killed"})
        self.append("tests/b.test.ts", APPENDED_TS_TEST)
        out = self.pick()
        self.assertEqual(self.rerun(out), [], out)
        self.assertEqual(self.carried(out), {"M1": "killed", "M2": "killed",
                                             "M3": "killed", "M4": "timeout"}, out)
        r = self.record(self.tree())  # nothing ran: no results and no exit file
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for n, word in ((4, "mutants"), (3, "killed"), (1, "timeout"), (0, "survived"),
                        (0, "invalid"), (4, "carried forward")):
            self.assertTrue(self.has_count(r.stdout, n, word), f"{n} {word}:\n{r.stdout}")

    def test_without_a_previous_record_every_mutant_reruns_and_says_why(self):
        out = self.pick()  # a run started on 4.7: a set, no recorded tree or results
        self.assertEqual(self.rerun(out), ["M1", "M2", "M3", "M4"], out)
        self.assertEqual(self.carried(out), {}, out)
        self.assertIn("no previous results were recorded", out["reason"] or "", out)
        self.first_pass()  # the control: once a pass is recorded, the kills carry
        self.assertIn("M1", self.carried(self.pick()))

    def test_a_recorded_tree_that_is_not_a_tree_here_reruns_every_mutant(self):
        self.first_pass()
        good = json.loads(self.record_path().read_text())["tree"]
        self.assertIn("M1", self.carried(self.pick()))  # the control
        head = self.git("rev-parse", "HEAD").strip()

        def set_tree(value):
            def change(record):
                record["tree"] = value
            return change

        def drop_tree(record):
            record.pop("tree", None)

        for name, change in (("a hash git can't find", set_tree("0" * 40)),
                             ("a commit id", set_tree(head)), ("HEAD", set_tree("HEAD")),
                             ("an option", set_tree("--output=x")),
                             ("no tree at all", drop_tree)):
            with self.subTest(tree=name):
                self.edit_record(change)
                out = self.pick()
                self.assertEqual(self.rerun(out), ["M1", "M2", "M3", "M4"], out)
                self.assertEqual(self.carried(out), {}, out)
                self.assertTrue(out["reason"], out)
                for where in (self.wt, self.cwd, self.ad, self.evidence, self.tmp):
                    self.assertFalse((where / "x").exists(), where)
                self.edit_record(set_tree(good))

    def test_an_unusable_record_reruns_every_mutant_and_says_why(self):
        def status(value):
            def change(record):
                for result in record["results"]:
                    if result["id"] == "M1":
                        if value is None:
                            result.pop("status", None)
                        else:
                            result["status"] = value
            return change

        for name, change in (("not JSON", None), ("a result with no status", status(None)),
                             ("a result with an unknown status", status("passed"))):
            with self.subTest(record=name):
                self.reset()
                self.first_pass()
                self.assertIn("M3", self.carried(self.pick()))  # the control
                if change is None:
                    self.record_path().write_text("{not json")
                else:
                    self.edit_record(change)
                out = self.pick()
                self.assertEqual(self.rerun(out), ["M1", "M2", "M3", "M4"], out)
                self.assertEqual(self.carried(out), {}, out)
                reason = out["reason"] or ""
                self.assertTrue(reason.strip(), out)
                self.assertNotIn("\n", reason.strip(), out)

    def test_a_mutant_with_no_recorded_result_reruns_alone(self):
        self.first_pass()
        self.add_mutant(STALE_M5_LINE20)
        out = self.pick()
        self.assertEqual(self.rerun(out), ["M2", "M5"], out)
        self.assertEqual(self.carried(out),
                         {"M1": "killed", "M3": "killed", "M4": "timeout"}, out)

    def test_a_recorded_result_unlike_its_set_entry_reruns_only_that_mutant(self):
        for field, value in (("file", "src/other.ts"), ("find", "total >= 1"),
                             ("replace", "total < 0")):
            with self.subTest(differs=field):
                self.reset()
                self.first_pass()

                def change(record, field=field, value=value):
                    for result in record["results"]:
                        if result["id"] == "M1":
                            result[field] = value
                self.edit_record(change)
                out = self.pick()
                self.assertEqual(self.rerun(out), ["M1", "M2"], out)
                self.assertEqual(self.carried(out), {"M3": "killed", "M4": "timeout"}, out)

    def test_a_recorded_line_unlike_the_set_s_line_still_carries(self):
        self.first_pass()

        def change(record):
            for result in record["results"]:
                if result["id"] == "M1":
                    result["line"] = 12  # where an earlier pass found it
        self.edit_record(change)
        out = self.pick()
        self.assertEqual(self.carried(out).get("M1"), "killed", out)
        self.assertEqual(self.rerun(out), ["M2"], out)

    def test_a_recorded_result_for_a_mutant_no_longer_in_the_set_is_ignored(self):
        self.first_pass()

        def change(record):
            record["results"].append({"id": "M9", "file": "src/c.ts", "line": 1,
                                      "find": "c1", "replace": "c2", "condition": "3",
                                      "status": "killed"})
        self.edit_record(change)
        out = self.pick()
        self.assertEqual(self.rerun(out), ["M2"], out)
        self.assertEqual(self.carried(out),
                         {"M1": "killed", "M3": "killed", "M4": "timeout"}, out)

    def test_an_unreadable_set_or_a_folder_outside_git_cannot_run(self):
        self.first_pass()
        self.assertIn("M1", self.carried(self.pick()))  # the control: a good set runs
        (self.evidence / "mutation-set.json").write_text("[{")
        r = self.mutants_cmd("select")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("ERROR:", r.stdout + r.stderr)
        self.assertNotIn("M1", r.stdout)
        plain = self.tmp / "plain" / ".auto-dev"
        (plain / "evidence").mkdir(parents=True)
        (plain / "evidence" / "mutation-set.json").write_text(json.dumps(STALE_SET))
        r = self.mutants_cmd("select", ad=plain)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("ERROR:", r.stdout + r.stderr)
        self.assertNotIn("M1", r.stdout)

    def test_the_selection_leaves_the_worktree_as_it_found_it(self):
        self.first_pass()
        self.edit_line("src/b.ts", 40, '  const label = "bee";')
        self.write("src/d.ts", "  return d > 1;\n")
        self.add_mutant({"id": "M6", "file": "src/d.ts", "line": 1, "find": "d > 1",
                         "replace": "d >= 1", "condition": "2"})

        def snapshot():
            return [self.git(*args) for args in (
                ("status", "--porcelain", "--untracked-files=all"), ("diff",),
                ("diff", "--cached"), ("ls-files", "--stage"),
                ("ls-files", "--others", "--exclude-standard"), ("rev-parse", "HEAD"),
                ("symbolic-ref", "HEAD"))] + [self.read("src/b.ts"), self.read("src/d.ts")]

        before = snapshot()
        out = self.pick()
        self.assertEqual(snapshot(), before)
        self.assertEqual(self.git("ls-files", "--", "src/d.ts"), "")  # still untracked
        self.assertIn("M6", self.rerun(out), out)
        self.assertIn("M3", self.rerun(out), out)
        self.assertEqual(self.carried(out).get("M1"), "killed", out)


class StaleMutantRecordTest(StaleMutantRepoCase):
    def test_a_recorded_re_check_counts_carried_and_rerun_mutants_once(self):
        self.first_pass({"M1": "killed", "M2": "survived", "M3": "killed", "M4": "killed"})
        self.add_mutant(STALE_M5_LINE20)
        out = self.pick()
        self.assertEqual(self.rerun(out), ["M2", "M5"], out)
        self.assertEqual(self.carried(out), {"M1": "killed", "M3": "killed",
                                             "M4": "killed"}, out)
        r = self.finish_pass({"M2": "killed", "M5": "survived"}, 1)
        for n, word in ((5, "mutants"), (4, "killed"), (0, "timeout"), (1, "survived"),
                        (0, "invalid"), (3, "carried forward")):
            self.assertTrue(self.has_count(r.stdout, n, word), f"{n} {word}:\n{r.stdout}")
        named = [line.split() for line in r.stdout.splitlines() if "surviv" in line]
        self.assertIn("M5", [w for words in named for w in words], r.stdout)
        self.assertNotIn("M2", [w for words in named for w in words], r.stdout)
        out = self.pick()  # M2 was caught this time: it carries, never a survivor
        self.assertEqual(self.rerun(out), ["M5"], out)
        self.assertEqual(self.carried(out), {"M1": "killed", "M2": "killed",
                                             "M3": "killed", "M4": "killed"}, out)

    def test_a_mutant_whose_code_is_gone_leaves_the_count_and_the_record(self):
        self.first_pass()
        self.delete_line("src/a.ts", 14)  # M2's code is gone
        self.set_mutants([m for m in STALE_SET if m["id"] != "M2"])
        out = self.pick()
        self.assertEqual(self.rerun(out), ["M1"], out)
        r = self.finish_pass({"M1": "killed"}, 0)
        self.assertTrue(self.has_count(r.stdout, 3, "mutants"), r.stdout)
        self.assertFalse(self.has_count(r.stdout, 4, "mutants"), r.stdout)
        out = self.pick()
        self.assertEqual(self.rerun(out), [], out)
        self.assertEqual(self.carried(out),
                         {"M1": "killed", "M3": "killed", "M4": "timeout"}, out)

    def test_each_finished_pass_becomes_the_baseline_for_the_next(self):
        self.add_mutant(STALE_M5_LINE20)
        self.first_pass({**FIRST_PASS, "M5": "killed"})
        lines = self.read("src/a.ts").split("\n")  # correction 1: M1 moves to line 12
        self.write("src/a.ts", "\n".join([*lines[:9], "  // guard", "  // more", *lines[9:]]))
        out = self.pick()
        self.assertEqual(self.rerun(out), ["M1", "M2"], out)
        self.finish_pass({"M1": "killed", "M2": "killed"}, 0, lines={"M1": 12, "M2": 16})
        self.edit_line("src/b.ts", 40, '  const label = "bee";')  # correction 2
        out = self.pick()
        self.assertEqual(self.rerun(out), ["M3", "M5"], out)
        self.assertEqual(self.carried(out),
                         {"M1": "killed", "M2": "killed", "M4": "timeout"}, out)

    def test_an_unfinished_or_moved_pass_leaves_the_earlier_baseline(self):
        def correction_1():
            self.edit_line("src/a.ts", 3, "export const a3 = 33;")

        def interrupted():
            self.run_results({"M1": "killed", "M2": "killed"}, 6)
            self.record(self.tree())

        def never_ended():
            self.run_results({"M1": "killed", "M2": "killed"}, None)
            self.record(self.tree())

        def no_results():
            (self.evidence / "mutate.exit").write_text("0\n")
            self.record(self.tree())

        def code_moved():
            noted = self.tree()
            self.run_results({"M1": "killed", "M2": "killed"}, 0)
            self.edit_line("src/notes.ts", 2, "export const note = 0;")
            self.record(noted)

        def changed_during_the_run():
            self.run_results({"M1": "killed", "M2": "killed"}, 0)
            self.record("changed during the run")

        for name, pass_2 in (("interrupted", interrupted), ("no exit file", never_ended),
                             ("no results", no_results), ("code moved", code_moved),
                             ("changed during the run", changed_during_the_run)):
            with self.subTest(pass_2=name):
                self.reset()
                self.first_pass()
                correction_1()
                self.assertEqual(self.rerun(self.pick()), ["M1", "M2"])
                pass_2()
                self.clear_run()
                self.edit_line("src/b.ts", 40, '  const label = "bee";')  # correction 2
                out = self.pick()  # still compared with pass 1: src/a.ts changed
                self.assertEqual(self.rerun(out), ["M1", "M2", "M3"], out)
                self.assertEqual(self.carried(out), {"M4": "timeout"}, out)

    def test_a_pass_with_nothing_to_rerun_still_becomes_the_baseline(self):
        self.first_pass({**FIRST_PASS, "M2": "killed"})
        self.append("tests/a.test.ts", APPENDED_TS_TEST)
        self.assertEqual(self.rerun(self.pick()), [])
        r = self.record(self.tree())
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        # Taking the new test out again edits a test line of the recorded tree,
        # though the tree is now what pass 1 tested.
        self.write("tests/a.test.ts", STALE_FILES["tests/a.test.ts"])
        out = self.pick()
        self.assertEqual(self.rerun(out), ["M1", "M2", "M3", "M4"], out)
        self.assertEqual(self.carried(out), {}, out)
        self.assertIn("tests/a.test.ts", out["reason"] or "", out)


if __name__ == "__main__":
    unittest.main()
