"""Tests for the eval fixtures in skills/auto-dev/evals/files/.

Run: python3 -m unittest discover -s tests -v   (from the repo root)

A fixture is only useful if the version under test accepts it. These tests
check that every fixture evals.json names exists and is used, that each
state.json fixture's WORK_LOG.md is the one autodev.py generates from it, that
the resume-build fixtures are what a replayed Plan stage leaves, and that `resume` (and,
for resume-build, `next`) act on the fixtures the way their evals expect.

When the state's shape or the handoff changes, regenerate the resume-build
fixtures from the replay instead of editing them:

    AUTODEV_WRITE_FIXTURES=1 python3 -m unittest tests.test_eval_fixtures
"""

import json
import os
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_autodev import ROOT, SCRIPTS, RunCase
from test_next import IMPLEMENTATION, NextCase

sys.path.insert(0, str(SCRIPTS))
from lib import state as st

SKILL = ROOT / "skills" / "auto-dev"
FILES = SKILL / "evals" / "files"
EVALS = json.loads((SKILL / "evals" / "evals.json").read_text(encoding="utf-8"))


TASK = "Reject record creation when the requested value isn't in the context's allowed set"
ASK = ("Creating a record with a value outside its context's allowed set returns a "
       "typed, handled error instead of throwing.")
# The replay's clock and setup runner, as the fixture shows them.
CREATED, AT, SETUP_PID = "2026-10-20T02:04:32+00:00", "2026-10-20T02:04:34+00:00", 4242


def fill(text, worktree, main):
    return (text.replace("<abs-path-to-worktree>", str(worktree))
            .replace("<abs-path-to-main-checkout>", str(main)))


def unfill(text, worktree, main):
    """Put the placeholders back: the worktree first, since it starts with main,
    and the longer spelling of each path first (/private/var before /var)."""
    for path in sorted({str(worktree), str(Path(worktree).resolve())}, key=len, reverse=True):
        text = text.replace(path, "<abs-path-to-worktree>")
    for path in sorted({str(main), str(Path(main).resolve())}, key=len, reverse=True):
        text = text.replace(path, "<abs-path-to-main-checkout>")
    return text


def placeholders(state, worktree, main):
    """A replayed state as a fixture: paths, profile values and the clock as
    placeholders or fixed values, so the fixture fits any fixture repo."""
    state = json.loads(unfill(json.dumps(state), worktree, main))

    def clock(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in ("at", "updated"):
                    node[key] = AT
                elif key == "created":
                    node[key] = CREATED
                else:
                    clock(value)
        elif isinstance(node, list):
            for value in node:
                clock(value)

    clock(state)
    for brief in state.get("briefs", []):
        if "tree" in brief:  # read only when its own job is recorded, all done in the Plan stage
            brief["tree"]["head"] = "<head-at-brief>"
    state["init"]["setup_pid"] = SETUP_PID
    state["repo"]["name"] = "<repo-name>"
    settings = state["settings"]
    settings["stack"] = "<profile>"
    settings["setup"] = ["<the profile's setup command>"]
    for check in settings["gate"]:
        check["command"] = f"<the profile's {check['kind']} command>"
    return state


class FixtureFilesTest(unittest.TestCase):
    def test_every_named_fixture_exists_and_every_fixture_is_named(self):
        named = {f for e in EVALS["evals"] for f in e.get("files", [])}
        for rel in named:
            self.assertTrue((SKILL / rel).is_file(), f"evals.json names missing {rel}")
        on_disk = {str(p.relative_to(SKILL)) for p in FILES.rglob("*") if p.is_file()}
        self.assertEqual(on_disk - named, set(), "fixtures no eval names")

    def test_the_eval_suite_has_the_cases_where_the_user_decides(self):
        sessions = [e.get("session", "") for e in EVALS["evals"]]
        for label in ("Build (spec problem: the run stops)",
                      "Build (spec problem: fixed at the user's instruction)",
                      "Ship (spec problem: a PR comment)", "Build (a deviation from the plan)",
                      "Build (a check the tester rules right)"):
            self.assertTrue(any(s.startswith(label) for s in sessions), label)

    def test_each_state_fixture_has_its_generated_work_log(self):
        for path in FILES.rglob("state.json"):
            state = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(state["schema"], st.SCHEMA, path)
            self.assertEqual((path.parent / st.LEDGER).read_text(encoding="utf-8"),
                             st.render_ledger(state),
                             f"{path.parent}/WORK_LOG.md is not generated from its "
                             "state.json")


class ResumeBuildReplayTest(NextCase):
    """Eval 6's fixtures are what the Plan stage leaves: replay it with the fixture's task
    and compare what it writes, placeholders put back, with each fixture."""

    maxDiff = None

    def init(self, *extra, task=TASK):
        self.worktree = self.tmp / "app-allowed-set-guard"
        self.dir = self.worktree / ".auto-dev"
        return self.autodev("init", "--repo", self.repo, "--slug", "allowed-set-guard",
                            "--task", task, "--ask", ASK, "--profile", self.profile,
                            "--max-wait", "30", *extra)

    def test_the_resume_build_fixtures_are_what_the_plan_stage_writes(self):
        # The Plan stage straight through, each worker spawned once (NextCase.plan_session
        # also re-issues the planner, which a fixture shouldn't show).
        self.expect("define", "FITS", high_risk="yes", reading="none")
        self.expect("define-reviewer", "CLEAN", blockers="0", fix_file="none")
        (self.dir / "IMPLEMENTATION.md").write_text(IMPLEMENTATION)
        self.expect("planner", "WRITTEN", entry_points_changed="no")
        self.expect("plan-reviewer", "CLEAN", blockers="0", fix_file="none")
        self.expect("acceptance-tester", "SEALED", checks="4", ambiguous="none")
        self.after(self.next(5), "Approve & build")  # high risk: the post-plan gate
        self.assertIn("read references/build.md", self.next(0)["ACTION"])
        # The session ends here, as the Build stage starts (the user stops it, or
        # a checkpoint): the eval's fresh session resumes the run there.
        r = self.autodev("handoff", "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        state = placeholders(self.state(), self.worktree, self.repo)
        replayed = {
            "state.json": json.dumps(state, indent=2, sort_keys=True) + "\n",
            st.LEDGER: st.render_ledger(state),
            "HANDOFF.md": unfill((self.dir / "HANDOFF.md").read_text(encoding="utf-8"),
                                 self.worktree, self.repo),
        }
        fixture = FILES / "resume-build"
        if os.environ.get("AUTODEV_WRITE_FIXTURES"):
            for name, text in replayed.items():
                (fixture / name).write_text(text, encoding="utf-8")
        for name, text in replayed.items():
            self.assertEqual((fixture / name).read_text(encoding="utf-8"), text,
                             f"resume-build/{name} is not what the Plan stage writes now: "
                             "regenerate it "
                             "(see this file's docstring)")


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


class ResumeBuildFixtureTest(FixtureRunCase):
    """Eval 6: the state the Plan stage leaves, resumed in a fresh session."""

    def test_resumes_in_the_build_stage_and_spawns_the_coder(self):
        r = self.autodev("init", "--repo", self.repo, "--slug", "allowed-set-guard",
                         "--task", "x", "--profile", self.profile, "--max-wait", "30")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        fixture = FILES / "resume-build"
        state = json.loads(fill((fixture / "state.json").read_text(encoding="utf-8"),
                                self.worktree, self.repo))
        self.write_state(state)
        (self.dir / "HANDOFF.md").write_text(fill(
            (fixture / "HANDOFF.md").read_text(encoding="utf-8"), self.worktree, self.repo))
        out = self.resume()
        self.assertIn(f"RESUME: {self.worktree}", out)
        self.assertIn("stage: Build", out)
        self.assertIn("runbook: references/build.md", out)
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
        ledger = fill((FILES / "old-version" / "WORK_LOG.md").read_text(encoding="utf-8"),
                      self.worktree, self.repo)
        (self.dir / "WORK_LOG.md").write_text(ledger, encoding="utf-8")
        self.assertIn(f"OLD-VERSION: {self.worktree}", self.resume())
        # Eval 22: nothing is written, and the 3.x ledger is left as it was.
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["WORK_LOG.md"])
        self.assertEqual((self.dir / "WORK_LOG.md").read_text(encoding="utf-8"), ledger)
        status = self.sh("git", "status", "--porcelain", cwd=self.worktree)
        self.assertEqual(status.strip(), "?? .auto-dev/")


class NoProposalEvalsTest(unittest.TestCase):
    """5.0 has no proposals, rulings or deviation gate: no eval may expect one."""

    def test_no_eval_expects_a_proposal_a_ruling_or_a_consumer(self):
        for e in EVALS["evals"]:
            text = json.dumps(e, ensure_ascii=False)
            for word in (r"proposals?/", r"rulings?_file", r"\bconsumer\b", r"deviation gate",
                         r"gate deviation", r"--consumer"):
                self.assertIsNone(re.search(word, text), f"eval {e['id']}: {word}")


if __name__ == "__main__":
    unittest.main()
