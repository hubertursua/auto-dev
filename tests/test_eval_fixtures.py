"""Tests for the eval fixtures in skills/auto-dev/evals/files/.

Run: python3 -m unittest discover -s tests -v   (from the repo root)

A fixture is only useful if the version under test accepts it. These tests
check that every fixture evals.json names exists and is used, that each
state.json fixture's WORK_LOG.md is the one autodev.py generates from it, and
that `resume` and `next` act on each fixture the way its eval expects.
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_autodev import ROOT, SCRIPTS, RunCase

sys.path.insert(0, str(SCRIPTS))
from lib import state as st

SKILL = ROOT / "skills" / "auto-dev"
FILES = SKILL / "evals" / "files"
EVALS = json.loads((SKILL / "evals" / "evals.json").read_text(encoding="utf-8"))


def fill(text, worktree, main):
    return (text.replace("<abs-path-to-worktree>", str(worktree))
            .replace("<abs-path-to-main-checkout>", str(main)))


class FixtureFilesTest(unittest.TestCase):
    def test_every_named_fixture_exists_and_every_fixture_is_named(self):
        named = {f for e in EVALS["evals"] for f in e.get("files", [])}
        for rel in named:
            self.assertTrue((SKILL / rel).is_file(), f"evals.json names missing {rel}")
        on_disk = {str(p.relative_to(SKILL)) for p in FILES.rglob("*") if p.is_file()}
        self.assertEqual(on_disk - named, set(), "fixtures no eval names")

    def test_each_state_fixture_has_its_generated_work_log(self):
        for path in FILES.rglob("state.json"):
            state = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(state["schema"], st.SCHEMA, path)
            self.assertEqual((path.parent / st.LEDGER).read_text(encoding="utf-8"),
                             st.render_ledger(state),
                             f"{path.parent}/WORK_LOG.md is not generated from its "
                             "state.json")


class FixtureRunCase(RunCase):
    """A clone of a bare origin, with a worktree where the fixture's run lives."""

    def setUp(self):
        super().setUp()
        self.worktree = self.tmp / "app-allowed-set-guard"
        self.dir = self.worktree / ".auto-dev"

    def resume(self):
        r = self.autodev("resume", "--repo", self.repo)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r.stdout


class ResumeS2FixtureTest(FixtureRunCase):
    """Eval 6: the state S1 leaves, resumed in a fresh session."""

    def test_resumes_in_s2_and_spawns_the_coder(self):
        r = self.autodev("init", "--repo", self.repo, "--slug", "allowed-set-guard",
                         "--task", "x", "--profile", self.profile, "--max-wait", "30")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        fixture = FILES / "resume-s2"
        state = json.loads(fill((fixture / "state.json").read_text(encoding="utf-8"),
                                self.worktree, self.repo))
        self.write_state(state)
        (self.dir / "HANDOFF.md").write_text(fill(
            (fixture / "HANDOFF.md").read_text(encoding="utf-8"), self.worktree, self.repo))
        out = self.resume()
        self.assertIn(f"RESUME: {self.worktree}", out)
        self.assertIn("session: S2", out)
        r = self.autodev("next", "--dir", self.dir, "--json")
        out = json.loads(r.stdout)
        self.assertEqual(out["exit"], 0, r.stdout + r.stderr)
        self.assertEqual(out["AGENT"], ["auto-dev:coder"])
        self.assertEqual(self.state()["phases"]["4"]["status"], "in-progress")


class OldVersionFixtureTest(FixtureRunCase):
    """Eval 22: a worktree a 3.x run left, with WORK_LOG.md and no state.json."""

    def test_a_3x_ledger_is_old_version(self):
        self.sh("git", "worktree", "add", "-q", "-b", "feat/allowed-set-guard",
                str(self.worktree), cwd=self.repo)
        self.dir.mkdir()
        (self.dir / "WORK_LOG.md").write_text(fill(
            (FILES / "old-version" / "WORK_LOG.md").read_text(encoding="utf-8"),
            self.worktree, self.repo))
        self.assertIn(f"OLD-VERSION: {self.worktree}", self.resume())
        self.assertFalse((self.dir / "state.json").exists())
        status = subprocess.run(["git", "status", "--porcelain"], cwd=self.worktree,
                                capture_output=True, text=True, check=True).stdout
        self.assertEqual(status.strip(), "?? .auto-dev/")


if __name__ == "__main__":
    unittest.main()
