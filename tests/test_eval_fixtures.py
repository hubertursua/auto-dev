"""Tests for the eval fixtures in skills/auto-dev/evals/files/.

Run: python3 -m unittest discover -s tests -v   (from the repo root)

A fixture is only useful if the version under test accepts it. These tests
check that every fixture evals.json names exists and is used, that each
state.json fixture's WORK_LOG.md is the one autodev.py generates from it, that
the resume-s2 fixtures are what a replayed S1 leaves, and that `resume` (and,
for resume-s2, `next`) act on the fixtures the way their evals expect.

When the state's shape or the handoff changes, regenerate the resume-s2
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

    def test_the_eval_suite_has_the_four_spec_proposal_cases(self):
        sessions = [e.get("session", "") for e in EVALS["evals"]]
        for label in ("S2 (spec proposal: filed)", "S2 (spec proposal: applied)",
                      "S3 (spec proposal: stands)", "S3 (spec proposal: PR comment)"):
            self.assertTrue(any(s.startswith(label) for s in sessions), label)

    def test_each_state_fixture_has_its_generated_work_log(self):
        for path in FILES.rglob("state.json"):
            state = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(state["schema"], st.SCHEMA, path)
            self.assertEqual((path.parent / st.LEDGER).read_text(encoding="utf-8"),
                             st.render_ledger(state),
                             f"{path.parent}/WORK_LOG.md is not generated from its "
                             "state.json")


class ResumeS2ReplayTest(NextCase):
    """Eval 6's fixtures are what S1 leaves: replay S1 with the fixture's task
    and compare what it writes, placeholders put back, with each fixture."""

    maxDiff = None

    def init(self, *extra, task=TASK):
        self.worktree = self.tmp / "app-allowed-set-guard"
        self.dir = self.worktree / ".auto-dev"
        return self.autodev("init", "--repo", self.repo, "--slug", "allowed-set-guard",
                            "--task", task, "--ask", ASK, "--profile", self.profile,
                            "--max-wait", "30", *extra)

    def test_the_resume_s2_fixtures_are_what_s1_writes(self):
        # S1 straight through, each worker spawned once (NextCase.plan_session
        # also re-issues the planner, which a fixture shouldn't show).
        self.expect("define", "FITS", high_risk="yes", reading="none")
        self.expect("define-reviewer", "CLEAN", blockers="0", fix_file="none")
        (self.dir / "IMPLEMENTATION.md").write_text(IMPLEMENTATION)
        self.expect("planner", "WRITTEN", entry_points_changed="no")
        self.expect("plan-reviewer", "CLEAN", blockers="0", fix_file="none")
        self.expect("acceptance-tester", "SEALED", checks="4", ambiguous="none")
        self.after(self.next(5), "Approve & build")  # high risk: the post-plan gate
        self.after(self.next(6))
        state = placeholders(self.state(), self.worktree, self.repo)
        replayed = {
            "state.json": json.dumps(state, indent=2, sort_keys=True) + "\n",
            st.LEDGER: st.render_ledger(state),
            "HANDOFF.md": unfill((self.dir / "HANDOFF.md").read_text(encoding="utf-8"),
                                 self.worktree, self.repo),
        }
        fixture = FILES / "resume-s2"
        if os.environ.get("AUTODEV_WRITE_FIXTURES"):
            for name, text in replayed.items():
                (fixture / name).write_text(text, encoding="utf-8")
        for name, text in replayed.items():
            self.assertEqual((fixture / name).read_text(encoding="utf-8"), text,
                             f"resume-s2/{name} is not what S1 writes now: regenerate it "
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
        ledger = fill((FILES / "old-version" / "WORK_LOG.md").read_text(encoding="utf-8"),
                      self.worktree, self.repo)
        (self.dir / "WORK_LOG.md").write_text(ledger, encoding="utf-8")
        self.assertIn(f"OLD-VERSION: {self.worktree}", self.resume())
        # Eval 22: nothing is written, and the 3.x ledger is left as it was.
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["WORK_LOG.md"])
        self.assertEqual((self.dir / "WORK_LOG.md").read_text(encoding="utf-8"), ledger)
        status = self.sh("git", "status", "--porcelain", cwd=self.worktree)
        self.assertEqual(status.strip(), "?? .auto-dev/")


class SpecProposalEvalsTest(unittest.TestCase):
    """The eval suite covers the spec-proposal path."""

    def test_the_evals_cover_a_filing_a_stands_a_redo_and_a_steering_pr_comment(self):
        texts = [json.dumps(e, ensure_ascii=False) for e in EVALS["evals"]]
        cases = [t for t in texts if re.search(r"(?i)\bproposals?\b", t)]
        self.assertGreaterEqual(len(cases), 4, "fewer than four evals about spec proposals")
        self.assertTrue(any("STANDS" in t for t in cases), "no eval of a proposal that stands")
        self.assertTrue(any(re.search(r"(?i)\bappl(?:y|ies|ied)\b", t) and
                            re.search(r"(?i)\bplanner\b|\bredo\b", t) for t in cases),
                        "no eval of an applied proposal's redo")
        self.assertTrue(any(re.search(r"(?i)PR comment", t) and
                            re.search(r"(?i)instruction|ignore your brief|steer", t)
                            for t in cases),
                        "no eval of a PR comment that tries to steer the spec")

    def test_the_evals_cover_a_coder_plan_proposal_and_the_order(self):
        texts = [json.dumps(e, ensure_ascii=False) for e in EVALS["evals"]]
        self.assertTrue(any(re.search(r"(?i)\bcoder\b", t) and
                            re.search(r"(?i)\bplan proposal\b", t) and
                            re.search(r"auto-dev:planner", t) and
                            "proposals/plan-<k>" in t for t in texts),
                        "no eval of a coder's plan proposal ruled on by the planner")
        self.assertTrue(any(re.search(r"(?i)spec then checks|spec, then plan", t) and
                            "auto-dev:define" in t and "auto-dev:acceptance-tester" in t
                            for t in texts),
                        "no eval of the order spec proposals and check proposals settle in")


if __name__ == "__main__":
    unittest.main()
