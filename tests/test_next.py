"""Tests for autodev.py next and pr publish: a run driven by simulated workers.

Run: python3 -m unittest discover -s tests -v   (from the repo root)

Each test plays the orchestrator: it runs `next`, does what it says (writing
the worker's result file and artifacts instead of spawning an agent), runs the
AFTER command, and runs `next` again. GitHub is tests/fake_gh/gh. Examples are
in TypeScript, as CLAUDE.md asks.
"""

import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from importlib import import_module
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_autodev import AUTODEV, GH_OK, SCRIPTS, RunCase
from test_parsers import BASE_RUNS, CODE_REVIEW, MANIFEST, SECURITY_REVIEW, SPEC, SPEC_EVAL

IMPLEMENTATION = ("# Plan\n\n## Files\n- src/due.ts\n\n## Design\nx\n\n## Data flow\nx\n\n"
                  "## Build sequence\n1. add the field\n\n## Test plan\nx\n\n"
                  "## Migrations / config\nnone\n")
CLEAN_REVIEW = CODE_REVIEW.split("## Must-fix")[0].replace(
    "provisional (re-votes pending)", "High").replace("1 open", "0 open") + """\
## Must-fix
| ID | Finding | Location | Category | Votes | Confidence | Status |
|----|---------|----------|----------|-------|------------|--------|

## Pending re-vote
| ID | Finding | Location | Category | Raised by | Re-voters | Votes |
|----|---------|----------|----------|-----------|-----------|-------|

## Advisory
| ID | Finding | Location | Category | Votes | Confidence | Why advisory |
|----|---------|----------|----------|-------|------------|--------------|

## Noise
none

## Security leads
none

## Passes
| Pass | Scope | Reviewers finished | Must-fix found | Re-votes |
|------|-------|--------------------|----------------|----------|
| 1 | whole change | 3/3 | 0 | 0 |
"""
OPEN_REVIEW = CLEAN_REVIEW.replace("0 open", "1 open").replace(
    "|----|---------|----------|----------|-------|------------|--------|\n",
    "|----|---------|----------|----------|-------|------------|--------|\n"
    "| C1 | null due date crashes sort | `src/sort.ts:4` | correctness | 3/3 | High | open |\n",
    1)
CHECK_REVIEW = OPEN_REVIEW.replace(
    "| C1 | null due date crashes sort | `src/sort.ts:4` | correctness |",
    "| C1 | the due-date check passes on the old code | `src/due.acceptance.test.ts:3` | "
    "acceptance-check |")
SECURITY_MUST_FIX = SECURITY_REVIEW.replace(
    "| S2 | session token not rotated |",
    "| S3 | any user can set another user's due date | `src/due.ts:9` | introduced | High "
    "| confirmed | must-fix | open |\n| S2 | session token not rotated |")


def r_report(findings):
    """A code reviewer's report, with the sections its template requires."""
    return (f"## Findings\n{findings}\n\n## Security leads\nnone\n\n"
            "## Pre-existing\nnone\n")


class NextCase(RunCase):
    def setUp(self):
        super().setUp()
        self.assertEqual(self.init().returncode, 0)
        acc = self.dir / "acceptance"
        for rel, text in (("SPEC.md", SPEC), ("acceptance/MANIFEST.md", MANIFEST)):
            (self.dir / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.dir / rel).write_text(text)
        (acc / "base-run").mkdir(parents=True, exist_ok=True)
        for name, text in BASE_RUNS.items():
            (acc / "base-run" / name).write_text(text)
        for path in ("src/due.acceptance.test.ts", "src/sort.acceptance.test.ts"):
            sealed = acc / "files" / f"{path}.sealed"
            sealed.parent.mkdir(parents=True, exist_ok=True)
            sealed.write_text("test")

    # -------------------------------------------------------------- driving

    def next(self, expect=None):
        r = self.autodev("next", "--dir", self.dir, "--json")
        try:
            out = json.loads(r.stdout)
        except ValueError:
            self.fail(f"next printed no JSON (exit {r.returncode}):\n{r.stdout}{r.stderr}")
        if expect is not None:
            self.assertEqual(out["exit"], expect, json.dumps(out, indent=2))
        return out

    def spawned(self, out):
        """[(worker, n)] the action asks to spawn."""
        return [(Path(b).stem.rsplit("-", 1)[0], int(Path(b).stem.rsplit("-", 1)[1]))
                for b in out.get("BRIEF", [])]

    def sets(self, worker, n):
        return next(b for b in self.state()["briefs"]
                    if b["worker"] == worker and b["n"] == n)["sets"]

    def answer(self, worker, n, nxt, status="ok", **data):
        path = self.dir / "returns" / f"{worker}-{n}.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps({"worker": worker, "status": status, "next": nxt,
                                    **data}))
        r = self.autodev("record", worker, n, "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def expect(self, worker, nxt=None, **data):
        """Run next, check it spawns `worker`, answer with `nxt` (if given)."""
        out = self.next(0)
        jobs = self.spawned(out)
        self.assertEqual([w for w, _ in jobs], [worker] * len(jobs), json.dumps(out))
        self.assertTrue(jobs, json.dumps(out, indent=2))
        if nxt is not None:
            for w, n in jobs:
                self.answer(w, n, nxt, **data)
        return out, jobs

    def after(self, out, choice=None):
        """Run the AFTER command (for a question, the one for `choice`)."""
        lines = out["AFTER"]
        if choice is not None:
            lines = [ln.split(" → ", 1)[1] for ln in lines if ln.startswith(f'"{choice}"')]
        for line in lines:
            r = subprocess.run(line, shell=True, capture_output=True, text=True,
                               env=self.env, cwd=self.tmp, check=False)
            self.assertEqual(r.returncode, 0, line + "\n" + r.stdout + r.stderr)

    def tree(self):
        return subprocess.run([sys.executable, str(SCRIPTS / "check-fresh.py"),
                               "--print-tree", self.worktree], capture_output=True,
                              text=True, check=True).stdout.strip()

    def spec_eval(self, v1="met", defective="None."):
        (self.dir / "SPEC_EVAL.md").write_text(SPEC_EVAL.format(
            tree=self.tree(), v1=v1, v2="met", e2="ran the sort", judgment="Justified",
            defective=defective))

    lint_tail = "all good"

    def lint(self, status="pass"):
        (self.dir / "lint").mkdir(exist_ok=True)
        (self.dir / "lint" / "TEST.md").write_text(
            f"# TEST — {status}\n\n- **Command:** `true`\n- **Tree:** {self.tree()}\n\n"
            f"## Output tail (final run)\n```\n{self.lint_tail}\n```\n")

    def resume(self):
        r = self.autodev("resume", "--repo", self.repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("RESUME", r.stdout)

    # -------------------------------------------------------------- whole sessions

    def plan_session(self):
        self.expect("define", "FITS", high_risk="yes", reading="none")
        self.expect("define-reviewer", "CLEAN", blockers="0", fix_file="none")
        self.expect("planner")
        (self.dir / "IMPLEMENTATION.md").write_text(IMPLEMENTATION)
        for w, n in self.spawned(self.next(0)):  # re-issued: not recorded yet
            self.answer(w, n, "WRITTEN", entry_points_changed="no")
        self.expect("plan-reviewer", "CLEAN", blockers="0", fix_file="none")
        self.expect("acceptance-tester", "SEALED", checks="4", ambiguous="none")
        out = self.next(5)  # HIGH_RISK turns the post-plan gate on
        self.after(out, "Approve & build")
        out = self.next(6)
        self.after(out)
        self.assertTrue((self.dir / "HANDOFF.md").exists())

    def build_session(self):
        self.resume()
        self.expect("coder", "BUILT", blocked="0", test_changes="none")
        (self.worktree / "due.ts").write_text("export const due = 1;\n")
        out, jobs = self.expect("verifier")
        self.assertEqual(self.sets(*jobs[0])["mode"], "first pass")
        self.spec_eval()
        self.answer(*jobs[0], "ALL_MET", tree="x", corrections="0")
        self.lint()
        self.expect("cleanup", "GREEN")
        self.assertEqual(self.sets("cleanup", 1)["scope"], "phase5")
        self.expect("verifier", "ALL_MET", tree="x", corrections="0")
        self.spec_eval()
        out = self.next(6)
        self.after(out)

    def panel(self, review=None, judged="CLEAN", corrections=None):
        """The three reviewers and the judge, who writes `review`."""
        _, jobs = self.expect("code-reviewer")
        self.assertEqual(len(jobs), 3)
        pass_dir = self.dir / "review" / f"pass-{self.state()['phase6']['review_pass']}"
        for w, n in jobs:
            slot = self.sets(w, n)["reviewer"]
            (pass_dir / f"{slot}.md").write_text(r_report("none"))
            self.answer(w, n, "REVIEWED", findings="0", leads="0")
        review = review or getattr(self, "review_text", CLEAN_REVIEW)
        (self.dir / "CODE_REVIEW.md").write_text(review.format(tree=self.tree()))
        if corrections is not None:
            (pass_dir / "corrections.md").write_text(corrections)
        is_open = judged == "MUST_FIX"
        self.expect("review-judge", judged, must_fix_open=str(int(is_open)), revote="0")

    def review_clean(self):
        self.panel()
        (self.dir / "SECURITY_REVIEW.md").write_text(SECURITY_REVIEW.format(
            tree=self.tree()))
        self.expect("security-reviewer-sensitive", "CLEAN", must_fix="0", pre_existing="0")

    def write_return(self, worker, n, data):
        (self.dir / "returns" / f"{worker}-{n}.json").write_text(json.dumps(
            {"worker": worker, "status": "ok", **data}))


class PlanTest(NextCase):
    def test_plan_session_ends_at_the_boundary(self):
        self.plan_session()
        state = self.state()
        self.assertEqual(state["phases"]["3"]["status"], "done")
        self.assertEqual(state["budget"]["remaining"], state["budget"]["total"])

    def test_oversized_stops_and_reports(self):
        (self.dir / "SPEC.md").write_text(
            SPEC + "\n## Size check\nOVERSIZED: three deliverables.\n"
            "- Subsystems: lists (~6 files), invites (~8 files)\n"
            "- Split: ship shared lists first, then invites\n")
        self.expect("define", "OVERSIZED", high_risk="yes", reading="none")
        out = self.next(4)
        self.assertIn("too big for one PR", " ".join(out["REPORT"]))
        self.assertIn("Jira was not moved", " ".join(out["REPORT"]))
        # The reasons themselves, so the orchestrator never reads SPEC.md.
        self.assertIn("- Split: ship shared lists first, then invites", out["REPORT"])
        self.assertIn("- Subsystems: lists (~6 files), invites (~8 files)", out["REPORT"])

    def test_a_ticket_asks_before_moving_jira(self):
        state = self.state()
        state["task"]["ticket"] = "TODO-7"
        self.write_state(state)
        self.expect("define", "FITS", high_risk="yes", reading="none")
        out = self.next(5)
        self.assertIn("TODO-7", out["QUESTION"])
        self.after(out, "Move it")
        out = self.next(0)
        self.assertIn("move Jira ticket TODO-7 to `In Progress`", out["ACTION"])
        # The can't-move command is printed whole: no AFTER line to edit.
        self.assertIn("mark jira-in-progress --value skipped", out["ACTION"])
        self.after(out)
        self.expect("define-reviewer")

    def test_fix_blocks_are_applied_and_the_re_review_spends_a_round(self):
        self.expect("define", "FITS", high_risk="yes", reading="none")
        out, jobs = self.expect("define-reviewer")
        fix = self.dir / "fixes" / "define-1.md"
        fix.write_text("FIX 1\n<<<<<<< OLD\nan invalid date is rejected → 400\n=======\n"
                       "an invalid date is rejected with 400 and nothing is saved\n"
                       ">>>>>>> NEW\n")
        self.answer(*jobs[0], "BLOCKERS", blockers="1", fix_file=str(fix))
        out, _ = self.expect("define-reviewer", "CLEAN", blockers="0", fix_file="none")
        self.assertIn("nothing is saved", (self.dir / "SPEC.md").read_text())
        self.assertIn("define-reviewer-1", out["BUDGET"])
        self.assertEqual(self.state()["budget"]["remaining"], 3)

    def test_a_fix_that_does_not_apply_goes_to_the_author(self):
        self.expect("define", "FITS", high_risk="yes", reading="none")
        out, jobs = self.expect("define-reviewer")
        fix = self.dir / "fixes" / "define-1.md"
        fix.write_text("FIX 1\n<<<<<<< OLD\ntext that is not there\n=======\nnew\n"
                       ">>>>>>> NEW\n")
        self.answer(*jobs[0], "BLOCKERS", blockers="1", fix_file=str(fix))
        out, jobs = self.expect("define")
        self.assertEqual(self.sets(*jobs[0]), {"fix_file": str(fix)})
        self.assertNotIn("BUDGET", out)  # the re-review after it spends the round
        self.answer(*jobs[0], "REVISED", high_risk="yes", reading="none")
        out, _ = self.expect("define-reviewer")
        self.assertIn("BUDGET", out)

    def test_acceptance_gaps_respawn_the_tester_for_those_conditions(self):
        (self.dir / "acceptance" / "base-run" / "C2.txt").unlink()
        self.expect("define", "FITS", high_risk="yes", reading="none")
        self.expect("define-reviewer", "CLEAN", blockers="0", fix_file="none")
        (self.dir / "IMPLEMENTATION.md").write_text(IMPLEMENTATION)
        self.expect("planner", "WRITTEN", entry_points_changed="no")
        self.expect("plan-reviewer", "CLEAN", blockers="0", fix_file="none")
        self.expect("acceptance-tester", "SEALED", checks="4", ambiguous="none")
        out, jobs = self.expect("acceptance-tester")
        self.assertTrue(self.sets(*jobs[0])["scope"].startswith("ONLY conditions 2:"))
        self.assertIn("acceptance-tester-1", out["BUDGET"])

    def test_post_plan_revise_goes_to_the_planner_then_asks_again(self):
        self.expect("define", "FITS", high_risk="yes", reading="none")
        self.expect("define-reviewer", "CLEAN", blockers="0", fix_file="none")
        (self.dir / "IMPLEMENTATION.md").write_text(IMPLEMENTATION)
        self.expect("planner", "WRITTEN", entry_points_changed="no")
        self.expect("plan-reviewer", "CLEAN", blockers="0", fix_file="none")
        self.expect("acceptance-tester", "SEALED", checks="4", ambiguous="none")
        self.next(5)
        self.autodev("gate", "post-plan", "revise", "--reason", "store dates in UTC",
                     "--dir", self.dir)
        out, jobs = self.expect("planner", "REVISED", entry_points_changed="no")
        self.assertEqual(self.sets(*jobs[0])["direction"], "store dates in UTC")
        self.assertNotIn("BUDGET", out)
        self.after(self.next(5), "Approve & build")
        self.next(6)

    def test_an_unrecorded_brief_is_reissued_then_stops(self):
        out, jobs = self.expect("define")
        self.assertEqual(self.spawned(self.next(0)), jobs)
        self.next(0)
        out = self.next(4)
        self.assertIn("spawned 3 times", " ".join(out["REPORT"]))

    def test_a_long_session_checkpoints_and_resumes_where_it_stopped(self):
        state = self.state()
        state["settings"]["checkpoint_events"] = state["events"] + 4
        (self.dir / "state.json").write_text(json.dumps(state))
        self.expect("define", "FITS", high_risk="yes", reading="none")
        _, jobs = self.expect("define-reviewer")  # a brief in flight is finished first
        self.assertEqual(self.spawned(self.next(0)), jobs)
        self.answer(*jobs[0], "CLEAN", blockers="0", fix_file="none")
        out = self.next(6)
        self.assertIn("--checkpoint", out["AFTER"][0])
        self.after(out)
        self.assertIn("resume", (self.dir / "HANDOFF.md").read_text())
        self.resume()
        self.expect("planner")

    def test_a_checkpoint_resume_keeps_a_worker_s_first_failure(self):
        _, jobs = self.expect("define")
        self.answer(*jobs[0], "", status="failed")
        state = self.state()
        state["settings"]["checkpoint_events"] = state["events"]
        self.write_state(state)
        out = self.next(6)  # the re-spawn is an action: a clean point
        self.assertIn("--checkpoint", out["AFTER"][0])
        self.after(out)
        self.resume()
        state = self.state()
        state["settings"]["checkpoint_events"] = 1000
        self.write_state(state)
        _, jobs = self.expect("define")
        self.answer(*jobs[0], "", status="failed")
        self.assertIn("failed twice", " ".join(self.next(4)["REPORT"]))

    def test_a_checkpoint_count_that_is_not_a_number_falls_back_to_80(self):
        events = self.state()["events"]
        for value in ("lots", 0):
            with self.subTest(value=value):
                state = self.state()
                state["settings"]["checkpoint_events"] = value
                state["events"] = 80
                self.write_state(state)
                self.assertEqual(self.next()["exit"], 6)  # a checkpoint, not exit 2
        state = self.state()
        state["events"] = events  # far below 80
        self.write_state(state)
        self.assertEqual(self.next()["exit"], 0)

    def test_a_refused_return_is_respawned_with_its_issues(self):
        self.expect("define")
        (self.dir / "returns" / "define-1.json").write_text(json.dumps(
            {"worker": "define", "status": "ok", "next": "FITS"}))
        r = self.autodev("record", "define", "1", "--dir", self.dir)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("MALFORMED", r.stdout)
        out = self.next(0)
        self.assertEqual(self.spawned(out), [("define", 2)])
        self.assertIn("record define 2", " ".join(out["AFTER"]))
        brief = (self.dir / "briefs" / "define-2.md").read_text()
        self.assertIn("high_risk", brief)  # the refused issues ride along
        self.next(0)
        self.assertIn("spawned 3 times", " ".join(self.next(4)["REPORT"]))

    def test_explain_only_looks(self):
        for _ in range(4):
            r = self.autodev("next", "--dir", self.dir, "--explain")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("nothing was done", r.stdout)
            self.assertIn("RULE: Phase 2 starts with the Define agent", r.stdout)
        self.assertFalse((self.dir / "briefs" / "define-1.md").exists())
        _, jobs = self.expect("define")
        self.assertEqual(jobs, [("define", 1)])
        for _ in range(3):  # an explain is not a spawn
            self.assertEqual(self.autodev("next", "--dir", self.dir, "--explain").returncode, 0)
        self.assertEqual(self.spawned(self.next(0)), [("define", 1)])

    def test_a_clean_review_s_fix_blocks_apply_without_a_round(self):
        self.expect("define", "FITS", high_risk="yes", reading="none")
        _, jobs = self.expect("define-reviewer")
        fix = self.dir / "fixes" / "define-1.md"
        fix.write_text("FIX 1\n<<<<<<< OLD\nan invalid date is rejected → 400\n=======\n"
                       "an invalid date is rejected with 400 and nothing is saved\n"
                       ">>>>>>> NEW\n")
        self.answer(*jobs[0], "CLEAN", blockers="0", fix_file=str(fix))
        out, _ = self.expect("planner")  # no re-review
        self.assertIn("nothing is saved", (self.dir / "SPEC.md").read_text())
        self.assertNotIn("BUDGET", out)
        self.assertEqual(self.state()["budget"]["remaining"], self.state()["budget"]["total"])

    def test_a_malformed_manifest_check_is_not_a_round(self):
        self.expect("define", "FITS", high_risk="yes", reading="none")
        self.expect("define-reviewer", "CLEAN", blockers="0", fix_file="none")
        (self.dir / "IMPLEMENTATION.md").write_text(IMPLEMENTATION)
        self.expect("planner", "WRITTEN", entry_points_changed="no")
        self.expect("plan-reviewer", "CLEAN", blockers="0", fix_file="none")
        self.expect("acceptance-tester", "SEALED", checks="4", ambiguous="none")
        (self.dir / "SPEC.md").write_text("# Spec\n\nNo conditions here.\n")
        r = self.autodev("next", "--dir", self.dir)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)  # check-manifest MALFORMED
        self.assertIn("MALFORMED", r.stderr)
        state = self.state()
        self.assertEqual(state["budget"]["remaining"], state["budget"]["total"])

    def test_a_retry_brief_written_by_hand_is_spawned_once(self):
        self.expect("define")
        self.write_return("define", 1, {"next": "FITS"})
        r = self.autodev("record", "define", "1", "--dir", self.dir)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("autodev.py next", r.stdout)
        r = self.autodev("brief", "define", "--mode", "write", "--retry", "1", "--dir",
                         self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.spawned(self.next(0)), [("define", 2)])

    def test_recording_a_job_again_keeps_its_place(self):
        self.expect("define", "FITS", high_risk="yes", reading="none")
        self.expect("define-reviewer", "CLEAN", blockers="0", fix_file="none")
        r = self.autodev("record", "define", "1", "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.expect("planner")  # the review stands: define-1 is no newer than it

    def test_a_worker_blocked_once_is_spawned_again_and_twice_stops(self):
        _, jobs = self.expect("define")
        self.answer(*jobs[0], "", status="blocked")
        _, jobs = self.expect("define")  # once: spawned again, told why
        self.assertEqual(jobs, [("define", 2)])
        brief = (self.dir / "briefs" / "define-2.md").read_text()
        self.assertIn("returned `blocked`", brief)
        self.answer(*jobs[0], "", status="blocked")
        self.assertIn("stopped on purpose twice running",
                      " ".join(self.next(4)["REPORT"]))
        self.assertEqual(self.next(4)["exit"], 4)
        self.resume()
        _, jobs = self.expect("define")
        self.assertEqual(jobs, [("define", 3)])
        self.assertNotIn("returned `blocked`",  # after a resume, a fresh brief
                         (self.dir / "briefs" / "define-3.md").read_text())

    def test_failed_then_blocked_stops_too(self):
        # Mixed non-ok results must not re-spawn a worker forever.
        _, jobs = self.expect("define")
        self.answer(*jobs[0], "", status="failed")
        _, jobs = self.expect("define")
        self.answer(*jobs[0], "", status="blocked")
        self.assertIn("did not return ok twice running", " ".join(self.next(4)["REPORT"]))

    def test_resume_after_a_worker_never_returned_spawns_it_again(self):
        self.expect("define")
        self.next(0)
        self.next(0)
        self.assertIn("spawned 3 times", " ".join(self.next(4)["REPORT"]))
        self.resume()
        self.assertEqual(self.spawned(self.next(0)), [("define", 1)])

    def test_a_worker_that_failed_is_respawned_once(self):
        _, jobs = self.expect("define")
        self.answer(*jobs[0], "", status="failed")
        _, jobs = self.expect("define")
        self.answer(*jobs[0], "", status="failed")
        self.assertIn("failed twice", " ".join(self.next(4)["REPORT"]))


class BuildTest(NextCase):
    def test_build_session_ends_at_the_boundary(self):
        self.plan_session()
        self.build_session()
        self.assertEqual(self.state()["phases"]["5"]["status"], "done")

    def test_a_blocked_step_goes_to_the_planner_then_the_coder(self):
        self.plan_session()
        self.resume()
        out, jobs = self.expect("coder")
        (self.dir / "blocked" / "coder-1.md").write_text("- step 1: the store has no date type\n")
        self.answer(*jobs[0], "BLOCKED", blocked="1", test_changes="none")
        out, jobs = self.expect("planner", "PLAN_REVISED", entry_points_changed="no")
        self.assertIn("blocked/coder-1.md", self.sets(*jobs[0])["blocked"])
        out, jobs = self.expect("coder", "BUILT", blocked="0", test_changes="none")
        self.assertIn("planner-2", out["BUDGET"])
        self.expect("verifier")

    def test_an_unmet_condition_is_corrected_and_re_checked(self):
        self.plan_session()
        self.resume()
        self.expect("coder", "BUILT", blocked="0", test_changes="none")
        out, jobs = self.expect("verifier")
        self.spec_eval(v1="unmet")
        (self.dir / "evidence").mkdir(exist_ok=True)
        (self.dir / "evidence" / "corrections.md").write_text(
            "# Required changes\n1. Show the due date next to the title in src/list.ts\n")
        self.answer(*jobs[0], "CORRECT", tree="x", corrections="1")
        out, jobs = self.expect("coder", "BUILT", blocked="0", test_changes="none")
        self.assertEqual(self.sets(*jobs[0])["corrections_file"],
                         f"{self.dir}/evidence/corrections.md")
        self.assertIn("verifier-1", out["BUDGET"])
        out, jobs = self.expect("verifier")
        self.assertEqual(self.sets(*jobs[0])["mode"], "re-check")

    def test_a_freshness_check_that_could_not_run_exits_2(self):
        self.plan_session()
        self.resume()
        self.expect("coder", "BUILT", blocked="0", test_changes="none")
        (self.worktree / "due.ts").write_text("export const due = 1;\n")
        _, jobs = self.expect("verifier")
        self.spec_eval()
        self.answer(*jobs[0], "ALL_MET", tree="x", corrections="0")
        self.lint()
        self.expect("cleanup", "GREEN")
        self.expect("verifier", "ALL_MET", tree="x", corrections="0")
        (self.tmp / "no-git").mkdir()
        env = {**self.env, "PATH": str(self.tmp / "no-git")}  # check-fresh can't run git
        r = subprocess.run([sys.executable, str(AUTODEV), "next", "--dir", str(self.dir)],
                           capture_output=True, text=True, env=env, check=False)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("could not run", r.stderr)
        self.assertNotIn("stale", r.stdout)

    def test_a_check_the_tester_ruled_right_gets_no_second_round(self):
        self.plan_session()
        self.resume()
        self.expect("coder", "BUILT", blocked="0", test_changes="none")
        defective = '`src/due.acceptance.test.ts` :: "shows the due date"'
        _, jobs = self.expect("verifier")
        self.spec_eval(v1="partial", defective=defective)
        self.answer(*jobs[0], "REPAIR", tree="x", corrections="0")
        out, jobs = self.expect("acceptance-tester")
        self.assertTrue(self.sets(*jobs[0])["scope"].startswith("ONLY conditions 1:"))
        self.assertIn("verifier-1", out["BUDGET"])
        self.answer(*jobs[0], "STANDS", checks="0", ambiguous="none")
        _, jobs = self.expect("verifier")
        self.assertIn("conditions 1 stand as written", self.sets(*jobs[0])["what_changed"])
        self.answer(*jobs[0], "REPAIR", tree="x", corrections="0")
        out = self.next(4)
        self.assertIn("ruled they stand", " ".join(out["REPORT"]))
        state = self.state()
        self.assertEqual(state["budget"]["remaining"], state["budget"]["total"] - 1)

    def test_the_budget_running_out_stops_phase_5(self):
        self.plan_session()
        state = self.state()
        state["budget"]["remaining"] = 0
        self.write_state(state)
        self.resume()
        self.expect("coder", "BUILT", blocked="0", test_changes="none")
        out, jobs = self.expect("verifier")
        self.spec_eval(v1="unmet")
        (self.dir / "evidence").mkdir(exist_ok=True)
        (self.dir / "evidence" / "corrections.md").write_text("# Required changes\n1. x\n")
        self.answer(*jobs[0], "CORRECT", tree="x", corrections="1")
        out = self.next(4)
        self.assertIn("budget is used up", " ".join(out["REPORT"]))


class ShipTest(NextCase):
    def ship_ready(self):
        self.plan_session()
        self.build_session()
        self.resume()

    def test_review_must_fix_runs_a_correction_then_reviews_its_files(self):
        self.ship_ready()
        out, jobs = self.expect("code-reviewer")
        for w, n in jobs:
            (self.dir / "review" / "pass-1" / f"{self.sets(w, n)['reviewer']}.md").write_text(
                r_report("- null due date crashes sort"))
            self.answer(w, n, "REVIEWED", findings="1", leads="0")
        (self.dir / "CODE_REVIEW.md").write_text(OPEN_REVIEW.format(tree=self.tree()))
        (self.dir / "review" / "pass-1" / "corrections.md").write_text(
            "# Required changes\n1. C1: guard the sort in src/sort.ts against a "
            "missing due date\n")
        _, jobs = self.expect("review-judge", "MUST_FIX", must_fix_open="1", revote="0")
        self.assertEqual(self.sets(*jobs[0])["tree"],  # the tree the panel reviewed
                         self.state()["phase6"]["passes"][0]["tree"])
        out, jobs = self.expect("coder")
        self.assertEqual(self.sets(*jobs[0])["corrections_file"],
                         f"{self.dir}/review/pass-1/corrections.md")
        self.assertIn("pass-1-c4", out["BUDGET"])
        (self.worktree / "sort.ts").write_text("export const sort = 1;\n")
        self.answer(*jobs[0], "BUILT", blocked="0", test_changes="none")
        out, jobs = self.expect("cleanup", "GREEN")
        self.assertEqual(self.sets(*jobs[0]), {"scope": "review-fix", "files": "sort.ts"})
        self.expect("verifier", "ALL_MET", tree="x", corrections="0")
        out, jobs = self.expect("code-reviewer")
        self.assertEqual(self.sets(*jobs[0])["scope"], "review-fix")
        self.assertEqual(self.sets(*jobs[0])["files"], "sort.ts")
        self.assertEqual(self.state()["phase6"]["review_pass"], 2)

    def to_body(self, extra=(), first=(), answers=("Open PR",)):
        """Run S3 from the review to the PR body; returns (sha, url, out, body)."""
        self.ship_ready()
        self.review_clean()
        self.lint()
        self.spec_eval()
        out = self.next(5)
        self.assertIn("pr gate", out["QUESTION"])
        for choice in answers:
            self.after(out, choice)
        out = self.next(0)
        self.assertIn("commit: run", out["ACTION"])
        r = self.autodev("commit", "--message", "feat(todos): add due dates", "--dir",
                         self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        sha = self.state()["phase6"]["verified_sha"]
        out = self.next(0)
        self.assertIn("push -u origin HEAD", out["ACTION"])
        self.sh("git", "push", "-q", "-u", "origin", "HEAD", cwd=self.worktree)
        self.after(out)
        url = "https://github.com/acme/app"
        self.script_gh(list(first) + GH_OK + [
            {"args": ["repo", "view", "--json", "url"], "stdout": json.dumps({"url": url})},
            {"args": ["pr", "list"], "stdout": "[]"},
            {"args": ["pr", "create"], "stdout": f"{url}/pull/12\n"},
            {"args": ["pr", "view", "12", "--json", "number,url,body"],
             "stdout": json.dumps({"number": 12, "url": f"{url}/pull/12",
                                   "body": f"Checked at commit {sha}"})},
            {"args": ["pr", "view", "12", "--json", "state"], "stdout": '{"state": "MERGED"}'},
            {"args": ["pr", "view", "12", "--json"],  # the main gate's summary
             "stdout": json.dumps({"url": f"{url}/pull/12", "isDraft": False,
                                   "state": "OPEN", "headRefOid": sha})},
            {"args": ["repo", "view", "--json",
                      "squashMergeAllowed,mergeCommitAllowed,rebaseMergeAllowed"],
             "stdout": json.dumps({"squashMergeAllowed": True})},
            {"args": ["pr", "merge"], "stdout": ""},
            *extra,
        ])
        out = self.next(0)
        body = self.dir / "pr-body.md"
        self.assertIn(str(body), out["ACTION"])
        text = body.read_text()
        self.assertIn(f"Checked at commit {sha}", text)
        self.assertIn(f"{url}/blob/{sha}/src/due.acceptance.test.ts", text)
        self.assertNotIn(str(self.worktree), text)
        return sha, url, out, body

    def open_pr(self, extra=(), first=()):
        """Run S3 from the review to a published PR; returns (sha, url)."""
        sha, url, out, body = self.to_body(extra, first)
        text = body.read_text()
        r = self.autodev("pr", "publish", "--dir", self.dir)
        self.assertEqual(r.returncode, 1)  # the Summary is not written yet
        self.assertIn("WRITE", r.stderr)
        body.write_text(re.sub(r"<!-- WRITE: .*?-->", "Todos can carry a due date.", text))
        self.after(out)
        self.assertEqual(self.state()["phase6"]["pr"], 12)
        return sha, url

    def test_no_budget_for_a_review_fix_goes_to_the_pr_gate(self):
        self.ship_ready()
        state = self.state()
        state["budget"]["remaining"] = 0
        self.write_state(state)
        _, jobs = self.expect("code-reviewer")
        for w, n in jobs:
            (self.dir / "review" / "pass-1" / f"{self.sets(w, n)['reviewer']}.md").write_text(
                r_report("- null due date crashes sort"))
            self.answer(w, n, "REVIEWED", findings="1", leads="0")
        (self.dir / "CODE_REVIEW.md").write_text(OPEN_REVIEW.format(tree=self.tree()))
        (self.dir / "review" / "pass-1" / "corrections.md").write_text(
            "# Required changes\n1. C1: guard the sort in src/sort.ts against a "
            "missing due date\n")
        self.expect("review-judge", "MUST_FIX", must_fix_open="1", revote="0")
        (self.dir / "SECURITY_REVIEW.md").write_text(SECURITY_REVIEW.format(
            tree=self.tree()))
        self.expect("security-reviewer-sensitive", "CLEAN", must_fix="0", pre_existing="0")
        out = self.next(5)
        self.assertIn("pr gate", out["QUESTION"])
        self.assertIn("Budget exhausted", " ".join(out["SUMMARY"]))

    def test_ship_session_runs_to_the_merge(self):
        sha, _ = self.open_pr()
        self.expect("triager", "TRIAGED", blockers="0", acceptance_checks="0",
                    triage_file="none", checks_file="none")
        out = self.next(0)
        self.assertIn("gh pr ready 12", out["ACTION"])
        self.after(out)
        out = self.next(5)
        self.assertIn("main gate", out["QUESTION"])
        self.after(out, "Merge PR to main")
        out = self.next(0)
        self.assertIn(f"merge-pr --pr 12 --sha {sha}", out["ACTION"])
        r = self.autodev("merge-pr", "--pr", "12", "--sha", sha, "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        out = self.next(0)
        self.assertIn("mark main-ci", out["AFTER"][0])
        self.assertIn("gh pr view 12 --json mergeCommit", out["ACTION"])  # names the PR
        self.autodev("mark", "main-ci", "--value", "green", "--dir", self.dir)
        out = self.next(0)
        self.assertIn("final report", out["ACTION"])
        self.after(out)
        out = self.next(5)
        self.after(out, "Keep it")
        out = self.next(3)
        self.assertEqual(self.state()["phases"]["6"]["status"], "done")
        log = [json.loads(ln)["args"] for ln in
               (self.tmp / "gh.log").read_text().splitlines()]
        self.assertEqual(sum(1 for a in log if a[:2] == ["pr", "create"]), 1)

    def test_a_security_must_fix_is_verified_then_corrected(self):
        self.ship_ready()
        self.panel()
        (self.dir / "SECURITY_REVIEW.md").write_text(SECURITY_MUST_FIX.format(
            tree=self.tree()))
        self.expect("security-reviewer-sensitive", "MUST_FIX", must_fix="1",
                    pre_existing="1")
        _, jobs = self.expect("review-judge")
        self.assertEqual(self.sets(*jobs[0]), {})
        self.assertIn("mode: security-verify",
                      (self.dir / "briefs" / f"review-judge-{jobs[0][1]}.md").read_text())
        (self.dir / "review" / "security-corrections.md").write_text(
            "# Required changes\n1. S3: in src/due.ts, check that the caller owns the todo "
            "before its date is stored\n")
        self.answer(*jobs[0], "VERIFIED", must_fix_open="1", revote="0")
        out, jobs = self.expect("coder")
        self.assertEqual(self.sets(*jobs[0])["corrections_file"],
                         f"{self.dir}/review/security-corrections.md")
        self.assertIn("security-", out["BUDGET"])

    def test_an_acceptance_check_finding_goes_to_the_tester(self):
        self.ship_ready()
        self.panel(CHECK_REVIEW, "MUST_FIX", corrections="# Required changes\nNone.\n")
        out, jobs = self.expect("acceptance-tester")
        sets = self.sets(*jobs[0])
        self.assertTrue(sets["scope"].startswith("ONLY conditions 1, S1:"), sets)
        self.assertIn("CODE_REVIEW.md, must-fix finding(s) C1", sets["report"])
        self.assertIn("pass-1-c4", out["BUDGET"])
        self.answer(*jobs[0], "REPAIRED", checks="1", ambiguous="none")
        self.expect("verifier")  # never the coder: nothing else is open

    def triage_files(self):
        triage = self.dir / "triage"
        (triage / "human-1.md").write_text(
            "# Required changes\n1. In src/sort.ts, keep todos with no date at the end\n")
        (triage / "human-1-checks.md").write_text(
            "# Required changes\n1. The sort check should cover two todos on one day\n")
        return triage / "human-1.md", triage / "human-1-checks.md"

    def test_human_blockers_and_checks_share_one_round(self):
        self.open_pr()
        blockers, checks = self.triage_files()
        self.expect("triager", "TRIAGED", blockers="1", acceptance_checks="1",
                    triage_file=str(blockers), checks_file=str(checks))
        out, jobs = self.expect("acceptance-tester")
        self.assertEqual(self.sets(*jobs[0])["report"], str(checks))
        self.assertIn("human-1", out["BUDGET"])
        left = self.state()["budget"]["remaining"]
        self.answer(*jobs[0], "REPAIRED", checks="1", ambiguous="none")
        out, jobs = self.expect("coder")
        self.assertEqual(self.sets(*jobs[0])["corrections_file"], str(blockers))
        self.assertNotIn("BUDGET", out)
        self.assertEqual(self.state()["budget"]["remaining"], left)

    def test_a_correction_that_changes_nothing_reaches_the_gates(self):
        self.open_pr()
        _, checks = self.triage_files()
        self.expect("triager", "TRIAGED", blockers="0", acceptance_checks="1",
                    triage_file="none", checks_file=str(checks))
        self.expect("acceptance-tester", "STANDS", checks="0", ambiguous="none")
        _, jobs = self.expect("verifier")
        self.assertIn("stand as written", self.sets(*jobs[0])["what_changed"])
        self.answer(*jobs[0], "ALL_MET", tree="x", corrections="0")
        out = self.next(0)  # no commit, no empty review pass, no second triage
        self.assertIn("gh pr ready 12", out["ACTION"])
        self.after(out)
        self.assertIn("main gate", self.next(5)["QUESTION"])
        self.assertNotIn("commit_attempt", self.state()["phase6"])

    def test_a_commit_made_but_not_checked_is_checked_not_refused(self):
        self.ship_ready()
        self.review_clean()
        self.lint()
        self.spec_eval()
        self.after(self.next(5), "Open PR")
        self.assertIn("commit: run", self.next(0)["ACTION"])
        # `commit` committed, then could not check the commit (killed, say).
        self.sh("git", "add", "-A", "--", ".", ":!.auto-dev", cwd=self.worktree)
        self.sh("git", "commit", "-q", "-m", "feat: x", cwd=self.worktree)
        head = self.sh("git", "rev-parse", "HEAD", cwd=self.worktree).strip()
        state = self.state()
        state["phase6"]["unverified_commit"] = head
        self.write_state(state)
        self.assertIn("commit: run", self.next(0)["ACTION"])  # not "nothing to commit"
        r = self.autodev("commit", "--message", "feat: x", "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(f"COMMITTED: {head}", r.stdout)
        state = self.state()
        del state["phase6"]["verified_sha"]
        state["phase6"]["commit_attempt"] = {"result": "not-verified",
                                             "seq": state["events"] + 1}
        self.write_state(state)
        self.assertIn("The commit step failed (not-verified)",
                      " ".join(self.next(4)["REPORT"]))

    def test_gh_failing_at_publish_is_not_a_refusal(self):
        _sha, _url, _out, body = self.to_body(first=[
            {"args": ["pr", "create"], "stderr": "HTTP 502: Bad Gateway", "exit": 1}])
        body.write_text(re.sub(r"<!-- WRITE: .*?-->", "Todos can carry a due date.",
                               body.read_text()))
        r = self.autodev("pr", "publish", "--dir", self.dir)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertNotIn("publish_attempt", self.state()["phase6"])
        self.assertIn("pr publish", " ".join(self.next(0)["AFTER"]))

    def test_a_check_the_tester_ruled_right_on_a_pr_comment_gets_no_second_round(self):
        self.open_pr()
        _, checks = self.triage_files()
        self.expect("triager", "TRIAGED", blockers="0", acceptance_checks="1",
                    triage_file="none", checks_file=str(checks))
        self.expect("acceptance-tester", "STANDS", checks="0", ambiguous="none")
        left = self.state()["budget"]["remaining"]  # human-1 is spent
        _, jobs = self.expect("verifier")
        self.spec_eval(v1="partial",
                       defective='`src/due.acceptance.test.ts` :: "shows the due date"')
        self.answer(*jobs[0], "REPAIR", tree="x", corrections="0")
        self.assertIn("ruled they stand", " ".join(self.next(4)["REPORT"]))
        self.assertEqual(self.state()["budget"]["remaining"], left)

    def republished_triage(self, ruling):
        """A human round (one blocker, one check comment the tester answers
        `ruling`), then the refreshed PR: returns the second triager's sets and
        the first round's two files."""
        _, url = self.open_pr()
        blockers, checks = self.triage_files()
        self.expect("triager", "TRIAGED", blockers="1", acceptance_checks="1",
                    triage_file=str(blockers), checks_file=str(checks))
        self.expect("acceptance-tester", ruling, checks="0", ambiguous="none")
        (self.worktree / "sort.ts").write_text("export const sort = 1;\n")
        self.expect("coder", "BUILT", blocked="0", test_changes="none")
        self.lint()
        self.expect("cleanup", "GREEN")
        self.spec_eval()
        self.expect("verifier", "ALL_MET", tree="x", corrections="0")
        self.review_clean()
        self.assertIn("commit: run", self.next(0)["ACTION"])
        r = self.autodev("commit", "--message", "fix: x", "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        out = self.next(0)
        self.assertIn("push", out["ACTION"])
        self.sh("git", "push", "-q", "origin", "HEAD", cwd=self.worktree)
        self.after(out)
        out = self.next(0)
        self.assertIn("pr publish", out["ACTION"])
        body = self.dir / "pr-body.md"
        body.write_text(re.sub(r"<!-- WRITE: .*?-->", "Todos can carry a due date.",
                               body.read_text()))
        sha = self.state()["phase6"]["verified_sha"]
        gh = json.loads((self.tmp / "gh.json").read_text())
        self.script_gh([
            {"args": ["pr", "edit", "12"], "stdout": ""},
            {"args": ["pr", "view", "12", "--json", "number,url,body"],
             "stdout": json.dumps({"number": 12, "url": f"{url}/pull/12",
                                   "body": f"Checked at commit {sha}"})}] + gh)
        r = self.autodev("pr", "publish", "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        _, jobs = self.expect("triager")
        self.assertIn("earlier: human-1 (triaged ", (self.dir / "briefs" /
                                                    f"triager-{jobs[0][1]}.md").read_text())
        self.assertNotIn("earlier", self.sets("triager", 1))  # nothing earlier then
        return self.sets(*jobs[0]), blockers, checks

    def test_a_republished_pr_tells_the_triager_what_earlier_rounds_handled(self):
        sets, blockers, checks = self.republished_triage("STANDS")
        self.assertIn(f"the coder worked on the blockers in {blockers}", sets["earlier"])
        self.assertIn(f"the acceptance tester ruled they stand as written (right against "
                      f"SPEC.md) for the comments in {checks}", sets["earlier"])

    def test_a_repaired_check_is_named_as_repaired_to_the_next_triager(self):
        sets, _, checks = self.republished_triage("REPAIRED")
        self.assertIn(f"the acceptance tester repaired them for the comments in {checks}",
                      sets["earlier"])

    def test_a_refused_publish_stops(self):
        _sha, _url, out, body = self.to_body()
        r = self.autodev("pr", "publish", "--dir", self.dir)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn(str(body), self.next(0)["ACTION"])  # back to the write step once
        r = self.autodev("pr", "publish", "--dir", self.dir)
        state = self.state()
        state["settings"]["checkpoint_events"] = 1  # a checkpoint is due
        self.write_state(state)
        self.assertIn("unwritten", " ".join(self.next(4)["REPORT"]))  # the stop wins
        state = self.state()
        state["settings"]["checkpoint_events"] = 1000
        self.write_state(state)
        body.write_text(re.sub(r"<!-- WRITE: .*?-->", "Details in .auto-dev/SPEC.md.",
                               body.read_text()))
        r = self.autodev("pr", "publish", "--dir", self.dir)
        self.assertIn("PROBLEMS", r.stdout)
        out = self.next(4)  # never exit 1, never the same publish again
        self.assertIn(".auto-dev/", " ".join(out["REPORT"]))
        self.assertIn("auto-dev continue", " ".join(out["REPORT"]))
        self.resume()  # the user fixed it: a resume lifts the stop
        self.assertIn(str(body), self.next(0)["ACTION"])

    def test_a_body_written_before_quoted_regions_is_written_again(self):
        # A run stopped on 4.0.1, whose description had no quoted regions, gets
        # a fresh one on resume instead of the same refusal.
        _sha, _url, _out, body = self.to_body()
        state = self.state()
        del state["phase6"]["quoted"]
        self.write_state(state)
        body.write_text(re.sub(r"<!-- WRITE: .*?-->", "Todos can carry a due date.",
                               body.read_text()).replace(" <!-- auto-dev:quoted -->", "")
                        .replace("  <!-- /auto-dev:quoted -->\n", ""))
        self.resume()
        self.assertIn(str(body), self.next(0)["ACTION"])
        self.assertIn("auto-dev:quoted", body.read_text())
        self.assertIn("<!-- WRITE:", body.read_text())
        self.assertIn("quoted", self.state()["phase6"])

    def merge_ready(self, first=()):
        sha, _ = self.open_pr(first=first)
        self.expect("triager", "TRIAGED", blockers="0", acceptance_checks="0",
                    triage_file="none", checks_file="none")
        self.after(self.next(0))
        self.after(self.next(5), "Merge PR to main")
        return sha

    def test_a_merge_whose_outcome_is_unknown_is_never_offered_again(self):
        sha = self.merge_ready(first=[{"args": ["pr", "view", "12", "--json", "state"],
                                       "stderr": "HTTP 502", "exit": 1}])
        r = self.autodev("merge-pr", "--pr", "12", "--sha", sha, "--dir", self.dir)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        out = self.next(4)
        self.assertIn("gh pr view 12 --json state", " ".join(out["REPORT"]))
        self.assertEqual(self.next(4)["exit"], 4)

    def test_a_triage_answer_is_kept_and_listed_as_a_follow_up(self):
        separate = "S2: Separate PR (note it as a follow-up)"
        _sha, _url, _out, body = self.to_body(answers=(separate, "Open PR"))
        self.assertEqual(self.state()["marks"]["triage-S2"]["value"], "separate")
        text = body.read_text()
        self.assertIn("Follow-up for a separate PR: session token not rotated", text)
        body.write_text(re.sub(r"<!-- WRITE: .*?-->", "Todos can carry a due date.", text))
        r = self.autodev("pr-body", "--check", body, "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_an_edit_answered_at_the_pr_gate_is_re_checked_again(self):
        self.ship_ready()
        self.review_clean()
        (self.worktree / "extra.ts").write_text("export const extra = 1;\n")
        self.lint()  # stale for the gate: the code changed after the reviews
        _, jobs = self.expect("cleanup")
        self.assertEqual(self.sets(*jobs[0]), {"scope": "outside"})
        self.lint()
        self.answer(*jobs[0], "GREEN")
        self.spec_eval()
        self.expect("verifier", "ALL_MET", tree="x", corrections="0")
        self.review_clean()
        self.lint()
        self.spec_eval()
        self.after(self.next(5), "Hold (don't push yet)")
        (self.worktree / "extra.ts").write_text("export const extra = 2;\n")
        self.resume()
        _, jobs = self.expect("cleanup")  # a new check, not "stale twice"
        self.assertEqual(self.sets(*jobs[0]), {"scope": "outside"})

    def test_a_hold_at_the_pr_gate_stops_and_resume_asks_again(self):
        self.ship_ready()
        self.review_clean()
        self.lint()
        self.spec_eval()
        self.after(self.next(5), "Hold (don't push yet)")
        out = self.next(4)
        self.assertIn("held", " ".join(out["REPORT"]))
        self.resume()
        self.assertIn("pr gate", self.next(5)["QUESTION"])


class PublishTest(NextCase):
    def test_a_refresh_keeps_the_live_summary_and_ticked_boxes(self):
        from importlib import import_module
        sys.path.insert(0, str(SCRIPTS))
        cmd_pr = import_module("lib.cmd_pr")
        live = ("## Summary\nWritten on GitHub.\n\n## Acceptance conditions\nold\n\n"
                "### Checks for a person\n- [x] **Looks right on a phone**\n\n"
                "## Quality gate\nold\n\n## Review\nold\n\n## Assumptions\nUTC.\n\n"
                "Generated with [Claude Code](https://claude.com/claude-code)\n")
        new = ("## Summary\n<!-- WRITE: x -->\n\n## Acceptance conditions\nnew\n\n"
               "### Checks for a person\n- [ ] **Looks right on a phone**\n\n"
               "## Quality gate\nnew\n\n## Review\nnew\n\n## Assumptions\n<!-- WRITE: y -->\n")
        merged = cmd_pr.merge_live(live, new)
        self.assertIn("Written on GitHub.", merged)
        self.assertIn("UTC.", merged)
        self.assertNotIn("WRITE", merged)
        self.assertNotIn("old", merged)
        self.assertIn("- [x] **Looks right on a phone**", merged)

    def test_a_refresh_keeps_a_checklist_a_person_edited_on_github(self):
        cmd_pr = self.cmd_pr()
        from lib.cmd_ship import lint_body
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        (tmp / "pull_request_template.md").write_text("## Checklist\n- [ ] Docs updated\n")
        live = "## Summary\nx\n\n## Checklist\n- [x] Docs updated in the wiki\n"
        merged = cmd_pr.merge_live(live, "## Summary\nz\n\n## Checklist\n- [ ] Docs updated\n")
        self.assertIn("- [x] Docs updated in the wiki", merged)
        state = {"worktree": str(tmp), "phase6": {}}
        self.assertTrue(any("checklist" in p for p in lint_body(merged, state)))
        self.assertFalse(any("checklist" in p
                             for p in lint_body(merged, state, checklist=False)))

    def cmd_pr(self):
        from importlib import import_module
        sys.path.insert(0, str(SCRIPTS))
        return import_module("lib.cmd_pr")

    def test_everything_posted_ends_with_the_marker(self):
        cmd_pr = self.cmd_pr()
        live = "## Summary\nx\n\n## Assumptions\ny\n\n" + cmd_pr.ATTRIBUTION + "\n"
        new = "## Summary\nz\n\n## Quality gate\nnew\n\n## Assumptions\nw\n"
        merged = cmd_pr.merge_live(live, new).rstrip("\n").split("\n")
        self.assertEqual(merged[-2:], [cmd_pr.ATTRIBUTION, cmd_pr.MARKER])
        posted = []

        def gh(_wt, *args):
            name = args[args.index("-F") + 1].split("@", 1)[1]
            posted.append(Path(name).read_text())
            return 0, "", ""
        real = cmd_pr.gh
        cmd_pr.gh = gh
        self.addCleanup(setattr, cmd_pr, "gh", real)
        cmd_pr.output_comment(".", self.dir, 12, "55", "a" * 40)  # the output moved back
        self.assertTrue(posted[0].startswith(f"{cmd_pr.COMMENT_HEAD} aaaaaaaaaaaa"))
        self.assertEqual(posted[0].rstrip("\n").split("\n")[-1], cmd_pr.MARKER)

    def test_an_id_the_body_quotes_passes_but_one_written_in_is_refused(self):
        # The tester named a test after S1 and the verifier wrote S1 in its
        # Expected line: generate quotes both word for word, and nobody may
        # edit them, so the lint skips them. An ID in the Summary still fails.
        sha = self.sh("git", "rev-parse", "HEAD", cwd=self.worktree).strip()
        state = self.state()
        state["phase6"]["verified_sha"] = sha
        self.write_state(state)
        manifest = self.dir / "acceptance" / "MANIFEST.md"
        manifest.write_text(manifest.read_text().replace('"owner only"',
                                                         '"criterion S1: owner only"'))
        (self.dir / "acceptance" / "base-run").mkdir(parents=True, exist_ok=True)
        (self.dir / "acceptance" / "base-run" / "CS1.txt").write_text(
            f"Commit: {sha}\nCommand: npx vitest run -t \"criterion S1:\"\n"
            "Result: failed\nOutput (last lines):\n  FAIL criterion S1: owner only\n")
        (self.dir / "evidence").mkdir(exist_ok=True)
        (self.dir / "evidence" / "CS1.txt").write_text(
            "Expected: the S1 check passes\nCommand: npx vitest run -t \"criterion S1:\"\n"
            "Result: passed\nOutput (last lines):\n  PASS criterion S1: owner only\n")
        (self.dir / "CODE_REVIEW.md").write_text(OPEN_REVIEW.format(tree=self.tree()))
        (self.dir / "SECURITY_REVIEW.md").write_text(SECURITY_REVIEW.format(
            tree=self.tree()))
        self.spec_eval()
        self.lint()
        lint = self.dir / "lint" / "TEST.md"  # a verbose reporter names the tests
        lint.write_text(lint.read_text().replace("all good", "PASS criterion S1: owner only"))
        r = self.autodev("pr-body", "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        body = self.dir / "pr-body.md"
        text = body.read_text()
        self.assertIn("criterion S1: owner only", text)
        self.assertIn("- `true`: passed <!-- auto-dev:quoted -->", text)
        self.assertIn("- [x] **Only the owner can set a todo's due date** "
                      "<!-- auto-dev:quoted -->", text)
        self.assertIn("expecting the S1 check passes", text)
        written = re.sub(r"<!-- WRITE: .*?-->", "Todos can carry a due date.", text)
        body.write_text(written)
        r = self.autodev("pr-body", "--check", body, "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        body.write_text(written.replace("Todos can carry a due date.",
                                        "Todos can carry a due date (S1).", 1))
        r = self.autodev("pr-body", "--check", body, "--dir", self.dir)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("uses a condition or finding ID: S1", r.stdout)
        # A quoted region edited after generate is linted like any other text.
        body.write_text(written.replace("expecting the S1 check passes",
                                        "expecting the S1 check to pass"))
        r = self.autodev("pr-body", "--check", body, "--dir", self.dir)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("uses a condition or finding ID: S1", r.stdout)

    def test_a_finding_s_plain_words_stay_in_its_own_block(self):
        review = OPEN_REVIEW.replace("## Pending re-vote", (
            "### C1 — null due date crashes sort\nTrigger path: sorting a todo with no date\n"
            "Required change: in src/sort.ts, order a missing date last\n"
            "In plain words: sorting crashed on a todo with no due date.\n\n"
            "### C2 — blank title\nIn plain words: a blank title was saved.\n\n"
            "## Pending re-vote"), 1)
        sha = self.sh("git", "rev-parse", "HEAD", cwd=self.worktree).strip()
        state = self.state()
        state["phase6"]["verified_sha"] = sha
        self.write_state(state)
        (self.dir / "CODE_REVIEW.md").write_text(review.format(tree=self.tree()))
        (self.dir / "SECURITY_REVIEW.md").write_text(SECURITY_REVIEW.format(
            tree=self.tree()))
        self.spec_eval()
        self.lint()
        r = self.autodev("pr-body", "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        body = self.dir / "pr-body.md"
        text = body.read_text()
        still = [ln for ln in text.splitlines() if "Still open" in ln]
        self.assertEqual(still, [("  - Still open: sorting crashed on a todo with no due "
                                  "date. (`src/sort.ts:4`); shipped at the user's call at "
                                  "the PR gate")])
        body.write_text(re.sub(r"<!-- WRITE: .*?-->", "Todos can carry a due date.", text))
        r = self.autodev("pr-body", "--check", body, "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


class TemplateTest(unittest.TestCase):
    """The repo's own PR template and the ticket link in the generated body."""

    def setUp(self):
        sys.path.insert(0, str(SCRIPTS))
        self.cmd_pr = import_module("lib.cmd_pr")
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def write(self, rel, text):
        path = self.tmp / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def test_template_sections_are_added_answered_or_left_to_write(self):
        self.write(".GitHub/PULL_REQUEST_TEMPLATE.md",
                   "## Description\n<!-- what and why -->\n\n"
                   "## How has this been tested?\n<!-- describe -->\n\n"
                   "## Screenshots\n<!-- add screenshots for UI changes -->\n\n"
                   "## Checklist\nPlease check:\n- [x] I added tests\n- [ ] Docs updated\n")
        found = self.cmd_pr.find_template(self.tmp)
        self.assertIsNotNone(found)
        text = "\n".join(self.cmd_pr.template_sections(found))
        self.assertNotIn("Description", text)
        self.assertIn("## How has this been tested?\nSee _Acceptance conditions_", text)
        self.assertIn("## Screenshots\n<!-- WRITE: the repo's PR template asks for this "
                      "section (add screenshots for UI changes)", text)
        self.assertIn("## Checklist\n- [ ] I added tests\n- [ ] Docs updated\n"
                      "<!-- WRITE: tick each box", text)
        self.assertNotIn("Please check", text)

    def test_a_checklist_may_be_ticked_never_reworded(self):
        self.write("pull_request_template.md",
                   "## Testing\n- [ ] Ran it\n\n"  # a testing section is ours to fill
                   "## Checklist\n<!-- tick what applies -->\n- [ ] I added tests\n"
                   "- [ ] Docs updated\n")
        problems = self.cmd_pr.checklist_problems
        ok = "## Summary\nx\n\n## Checklist\n- [x] I added tests\n- [ ] Docs updated\n"
        self.assertEqual(problems(ok, self.tmp), [])
        self.assertEqual(problems(ok.replace("- [ ] Docs", "- [X] Docs"), self.tmp), [])
        for bad in (ok.replace("I added tests", "I added unit tests"),
                    ok.replace("- [ ] Docs updated\n", ""),
                    ok + "- [x] Reviewed by a person\n",
                    ok.replace("- [x] I added tests\n- [ ] Docs updated",
                               "- [ ] Docs updated\n- [x] I added tests")):
            self.assertEqual(len(problems(bad, self.tmp)), 1, bad)
            self.assertIn("keep the PR template's items", problems(bad, self.tmp)[0])
        self.assertIn("missing", problems("## Summary\nx\n", self.tmp)[0])

    def test_a_generated_checklist_passes_as_it_is(self):
        # Two sections under one heading, and an item the secret filter drops.
        self.write("pull_request_template.md",
                   "## Frontend\n### Checklist\n- [ ] a11y checked\n"
                   "## Backend\n### Checklist\n- [ ] migrations reversible\n"
                   "- [ ] No hardcoded password: verified by grep\n")
        lines = self.cmd_pr.template_sections(self.cmd_pr.find_template(self.tmp))
        body = self.cmd_pr.clean("\n".join(lines), str(self.tmp))
        self.assertEqual(body.count("## Checklist"), 2)
        self.assertEqual(self.cmd_pr.checklist_problems(body, self.tmp), [])
        swapped = body.replace("a11y checked", "X").replace("migrations reversible",
                                                            "a11y checked")
        self.assertEqual(len(self.cmd_pr.checklist_problems(swapped, self.tmp)), 2)

    def test_no_template_checklist_no_checklist_problem(self):
        self.assertEqual(self.cmd_pr.checklist_problems("## Summary\n", self.tmp), [])
        self.write("pull_request_template.md", "## Risk\nDescribe it.\n")
        self.assertEqual(self.cmd_pr.checklist_problems("## Summary\n", self.tmp), [])

    def test_a_txt_template_is_found_and_md_wins_beside_it(self):
        # GitHub accepts a .txt template in the same places as a .md one.
        txt = self.write(".github/Pull_Request_Template.TXT", "## Rollout\nThe plan.\n")
        self.assertEqual(self.cmd_pr.find_template(self.tmp), txt)
        self.assertIn("## Rollout", self.cmd_pr.template_sections(txt))
        md = self.write(".github/pull_request_template.md", "## Risk\n")
        self.assertEqual(self.cmd_pr.find_template(self.tmp), md)
        self.write("pull_request_template.md", "## Root\n")
        self.assertEqual(self.cmd_pr.find_template(self.tmp), md)  # .github/ first

    def test_a_template_folder_is_never_the_default(self):
        # GitHub applies a template from this folder only when a PR asks for it.
        self.write(".github/PULL_REQUEST_TEMPLATE/bug.md", "## Bug\n")
        self.write(".github/PULL_REQUEST_TEMPLATE/feature.md", "## Feature\n")
        self.assertIsNone(self.cmd_pr.find_template(self.tmp))
        (self.tmp / ".github/PULL_REQUEST_TEMPLATE/feature.md").unlink()
        self.assertIsNone(self.cmd_pr.find_template(self.tmp))

    def test_headings_in_comments_and_code_blocks_are_not_sections(self):
        found = self.write("pull_request_template.md",
                           "## Rollout\n<!--\n## Example heading in a comment\n-->\n"
                           "```md\n# not a heading\n```\n~~~\n## nor this\n~~~\n")
        lines = self.cmd_pr.template_sections(found)
        self.assertEqual([ln for ln in lines if ln.startswith("#")], ["## Rollout"])
        self.assertNotIn("not a heading", "\n".join(lines))

    def test_a_section_s_plain_instructions_reach_its_write_line(self):
        found = self.write("pull_request_template.md",
                           "## Risk\nDescribe the risk and the rollout plan.\n")
        self.assertIn("## Risk\n<!-- WRITE: the repo's PR template asks for this section "
                      "(Describe the risk and the rollout plan.)",
                      "\n".join(self.cmd_pr.template_sections(found)))

    def test_no_template_adds_nothing(self):
        self.assertEqual(self.cmd_pr.template_sections(self.cmd_pr.find_template(self.tmp)),
                         [])


class ReviewFindingsTest(unittest.TestCase):
    """Which review rows `pr publish` posts, without GitHub."""

    def test_open_and_advisory_rows_are_posted_fixed_ones_are_not(self):
        sys.path.insert(0, str(SCRIPTS))
        cmd_pr = import_module("lib.cmd_pr")
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        code = OPEN_REVIEW.replace(
            "| open |\n",
            "| open |\n| C2 | blank title | `src/save.ts:3` | correctness | 3/3 | High "
            "| fixed |\n", 1)
        (tmp / "CODE_REVIEW.md").write_text(code.format(tree="0" * 40))
        sec = SECURITY_MUST_FIX.replace(
            "| S2 | session token not rotated |",
            "| S4 | verbose error | `src/err.ts:2` | introduced | Low | confirmed "
            "| advisory | — |\n| S2 | session token not rotated |")
        (tmp / "SECURITY_REVIEW.md").write_text(sec.format(tree="0" * 40))
        found = cmd_pr.review_findings(tmp, {"marks": {}})
        self.assertEqual(sorted(f["where"] for f in found),
                         ["src/due.ts:9", "src/err.ts:2", "src/sort.ts:4"])

    def test_a_finding_is_posted_in_its_plain_words(self):
        sys.path.insert(0, str(SCRIPTS))
        cmd_pr = import_module("lib.cmd_pr")
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        review = OPEN_REVIEW.replace("## Pending re-vote", (
            "### C1 — null due date crashes sort\n"
            "In plain words: sorting crashed on a todo with no due date.\n\n"
            "## Pending re-vote"), 1)
        (tmp / "CODE_REVIEW.md").write_text(review.format(tree="0" * 40))
        found = cmd_pr.review_findings(tmp, {"marks": {}})
        self.assertIn("sorting crashed on a todo with no due date", found[0]["text"])

    def test_others_sent_to_a_separate_pr_are_posted(self):
        sys.path.insert(0, str(SCRIPTS))
        cmd_pr = import_module("lib.cmd_pr")
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        rows = "".join(f"| S{i} | old issue {i} | `src/old{i}.ts:{i}` | pre-existing | Medium "
                       "| confirmed | for the user | — |\n" for i in range(5, 9))
        sec = SECURITY_REVIEW.replace("| S2 | session token not rotated |",
                                      rows + "| S2 | session token not rotated |")
        (tmp / "SECURITY_REVIEW.md").write_text(sec.format(tree="0" * 40))
        found = cmd_pr.review_findings(tmp, {"marks": {"triage-others": {"value": "separate"}}})
        self.assertEqual(len(found), 3)  # the gate asked two one by one; three were "Others"

    def test_a_template_hint_cannot_end_the_write_comment(self):
        sys.path.insert(0, str(SCRIPTS))
        cmd_pr = import_module("lib.cmd_pr")
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        (tmp / "pull_request_template.md").write_text("## Rollout\n<!-- flag a--b -->\n")
        line = cmd_pr.template_sections(cmd_pr.find_template(tmp))[1]
        self.assertEqual(line.count("--"), 2)  # only the comment's own <!-- and -->

    def test_the_ticket_link(self):
        sys.path.insert(0, str(SCRIPTS))
        cmd_pr = import_module("lib.cmd_pr")
        self.assertEqual(cmd_pr.ticket_link({"ticket": "none"}), "")
        self.assertEqual(cmd_pr.ticket_link({}), "")
        self.assertEqual(cmd_pr.ticket_link({"ticket": "TODO-7"}), "Ticket: TODO-7")


class TicketTest(NextCase):
    to_body = ShipTest.to_body
    open_pr = ShipTest.open_pr

    def ship_ready(self):
        ShipTest.ship_ready(self)
        state = self.state()
        state["task"].update(ticket="TODO-7", ticket_url="https://acme.atlassian.net/browse/TODO-7")
        self.write_state(state)

    def test_the_repo_s_pr_template_reaches_the_body(self):
        self.ship_ready()
        (self.worktree / ".github").mkdir(exist_ok=True)
        (self.worktree / ".github" / "pull_request_template.md").write_text(
            "## Screenshots\n<!-- for UI changes -->\n")
        sha = self.sh("git", "rev-parse", "HEAD", cwd=self.worktree).strip()
        state = self.state()
        state["phase6"]["verified_sha"] = sha
        self.write_state(state)
        (self.dir / "CODE_REVIEW.md").write_text(CLEAN_REVIEW.format(tree=self.tree()))
        (self.dir / "SECURITY_REVIEW.md").write_text(SECURITY_REVIEW.format(tree=self.tree()))
        self.spec_eval()
        self.lint()
        r = self.autodev("pr-body", "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        text = (self.dir / "pr-body.md").read_text()
        self.assertIn("## Screenshots\n<!-- WRITE: the repo's PR template asks for this "
                      "section (for UI changes)", text)
        self.assertLess(text.index("## Screenshots"), text.index("## Assumptions"))

    def test_publish_refuses_a_reworded_checklist_and_takes_a_ticked_one(self):
        _, _, _, body = self.to_body()
        (self.worktree / "pull_request_template.md").write_text(
            "## Checklist\n- [ ] I added tests\n- [ ] Docs updated\n")
        r = self.autodev("pr-body", "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        text = body.read_text()
        self.assertIn("## Checklist\n- [ ] I added tests\n- [ ] Docs updated\n"
                      "<!-- WRITE: tick each box", text)
        text = re.sub(r"<!-- WRITE: .*?-->", "Todos can carry a due date.", text)
        body.write_text(text.replace("- [ ] Docs updated", "- [x] Docs updated if needed"))
        r = self.autodev("pr-body", "--check", body, "--dir", self.dir)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("keep the PR template's items", r.stdout)
        r = self.autodev("pr", "publish", "--dir", self.dir)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("keep the PR template's items", r.stdout)
        self.assertIsNone(self.state()["phase6"].get("pr"))
        body.write_text(text.replace("- [ ] I added tests", "- [x] I added tests"))
        r = self.autodev("pr", "publish", "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.state()["phase6"]["pr"], 12)

    def checklist_on_open_pr(self, live):
        """A reworded checklist published to an open PR whose description is `live`."""
        _, _, _, body = self.to_body(first=[
            {"args": ["pr", "list"], "stdout": '[{"number": 12}]'},
            {"args": ["pr", "view", "12", "--json", "body"],
             "stdout": json.dumps({"body": live})},
            {"args": ["pr", "edit"], "stdout": ""}])
        (self.worktree / "pull_request_template.md").write_text(
            "## Checklist\n- [ ] Docs updated\n")
        r = self.autodev("pr-body", "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        text = re.sub(r"<!-- WRITE: .*?-->", "Todos can carry a due date.",
                      body.read_text())
        body.write_text(text.replace("- [ ] Docs updated", "- [x] Docs in the wiki"))
        return self.autodev("pr", "publish", "--dir", self.dir)

    def test_a_person_s_edits_to_a_live_checklist_stand(self):
        r = self.checklist_on_open_pr("## Summary\nBy hand.\n\n## Checklist\n"
                                      "- [x] Docs updated in the wiki\n")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        log = [json.loads(ln) for ln in (self.tmp / "gh.log").read_text().splitlines()]
        sent = next(e["files"] for e in log if e["args"][:2] == ["pr", "edit"])
        self.assertIn("- [x] Docs updated in the wiki", "".join(sent.values()))

    def test_an_empty_live_description_still_checks_the_checklist(self):
        r = self.checklist_on_open_pr("")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("keep the PR template's items", r.stdout)

    def test_the_ticket_is_linked_in_the_summary(self):
        self.open_pr()
        text = (self.dir / "pr-body.md").read_text()
        summary = text.split("## Acceptance conditions")[0]
        self.assertIn("Ticket: [TODO-7](https://acme.atlassian.net/browse/TODO-7)", summary)

    def test_gate_output_about_scratch_files_stays_out_of_the_body(self):
        # A formatter over `.` lists the git-ignored .auto-dev/ files; cleanup
        # passes the check, and publish must not refuse the body for them.
        self.lint_tail = ("[warn] .auto-dev/SPEC.md\n[warn] .auto-dev/state.json\n"
                          "[warn] Code style issues found in 2 files.")
        self.open_pr()
        gate = (self.dir / "pr-body.md").read_text().split("## Quality gate")[1]
        self.assertNotIn(".auto-dev/", gate)
        self.assertIn("Code style issues found in 2 files.", gate)
        self.assertIn("(2 line(s) about git-ignored pipeline files left out)", gate)


class InlineCommentsTest(NextCase):
    to_body = ShipTest.to_body
    open_pr = ShipTest.open_pr
    review_text = CLEAN_REVIEW.replace(
        "|----|---------|----------|----------|-------|------------|--------------|\n",
        "|----|---------|----------|----------|-------|------------|--------------|\n"
        "| C5 | magic number | `due.ts:1` | style | 1/3 | Low | style only |\n"
        "| C6 | slow loop | `app.ts:40` | performance | 1/3 | Medium | not on a hot path |\n")

    inline = True

    def ship_ready(self):
        ShipTest.ship_ready(self)
        state = self.state()
        state["settings"]["inline_comments"] = self.inline
        self.write_state(state)

    def calls(self):
        return [json.loads(ln) for ln in (self.tmp / "gh.log").read_text().splitlines()]

    def test_findings_go_inline_in_the_diff_and_the_rest_in_one_comment(self):
        sha, _ = self.open_pr(extra=[
            {"args": ["api", "--method", "POST"], "stdout": "{}"},
            {"args": ["pr", "comment"], "stdout": "https://x/pull/12#issuecomment-5\n"}])
        calls = self.calls()
        review = [c for c in calls if c["args"][:3] == ["api", "--method", "POST"]]
        self.assertEqual(len(review), 1)
        self.assertIn("repos/{owner}/{repo}/pulls/12/reviews", review[0]["args"])
        payload = json.loads(next(iter(review[0]["files"].values())))
        self.assertEqual(payload["commit_id"], sha)
        self.assertEqual(payload["event"], "COMMENT")
        self.assertEqual([(c["path"], c["line"]) for c in payload["comments"]],
                         [("due.ts", 1)])
        self.assertIn("**Advisory** (confidence Low): magic number",
                      payload["comments"][0]["body"])
        general = [c for c in calls if c["args"][:2] == ["pr", "comment"]]
        self.assertEqual(len(general), 1)
        comment = next(iter(general[0]["files"].values()))
        self.assertIn("`app.ts:40`: **Advisory** (confidence Medium): slow loop", comment)
        # everything the pipeline posts ends with the marker the triager skips
        sys.path.insert(0, str(SCRIPTS))
        from importlib import import_module as load
        marker = load("lib.cmd_pr").MARKER
        self.assertEqual(comment.rstrip("\n").split("\n")[-1], marker)
        self.assertTrue(payload["body"].endswith(marker))
        self.assertTrue(payload["comments"][0]["body"].endswith(marker))
        self.assertEqual(self.state()["phase6"]["inline"]["inline"], 1)

    def test_a_pre_existing_finding_is_posted_only_when_sent_to_a_separate_pr(self):
        sys.path.insert(0, str(SCRIPTS))
        cmd_pr = import_module("lib.cmd_pr")
        (self.dir / "SECURITY_REVIEW.md").write_text(SECURITY_REVIEW.format(tree="0" * 40))
        state = {"marks": {"triage-S2": {"value": "ignore"}}}
        self.assertEqual(cmd_pr.review_findings(self.dir, state), [])
        state["marks"]["triage-S2"]["value"] = "separate"
        found = cmd_pr.review_findings(self.dir, state)
        self.assertEqual([(f["path"], f["line"]) for f in found], [("src/auth.ts", 88)])
        self.assertIn("left for a separate PR", found[0]["text"])

    def test_a_failed_post_is_reported_not_fatal(self):
        self.open_pr(extra=[
            {"args": ["api", "--method", "POST"], "stderr": "Unprocessable", "exit": 1},
            {"args": ["pr", "comment"], "stderr": "Forbidden", "exit": 1}])
        inline = self.state()["phase6"]["inline"]
        self.assertEqual((inline["inline"], inline["general"]), (0, 0))
        self.assertIn("Unprocessable", inline["error"])
        self.assertIn("Forbidden", inline["error"])

    def test_a_republish_posts_the_findings_only_once(self):
        self.open_pr(
            first=[{"args": ["pr", "view", "12", "--json", "body"], "stdout": '{"body": ""}'}],
            extra=[{"args": ["api", "--method", "POST"], "stdout": "{}"},
                   {"args": ["pr", "comment"], "stdout": "https://x/pull/12#issuecomment-5\n"},
                   {"args": ["pr", "edit"], "stdout": ""}])
        r = self.autodev("pr", "publish", "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        calls = self.calls()
        self.assertEqual(len([c for c in calls if c["args"][:1] == ["api"]]), 1)
        self.assertEqual(len([c for c in calls if c["args"][:2] == ["pr", "comment"]]), 1)

    def test_a_refused_review_moves_every_finding_to_the_general_comment(self):
        self.open_pr(extra=[
            {"args": ["api", "--method", "POST"], "stderr": "Unprocessable", "exit": 1},
            {"args": ["pr", "comment"], "stdout": "https://x/pull/12#issuecomment-5\n"}])
        inline = self.state()["phase6"]["inline"]
        self.assertEqual((inline["inline"], inline["general"]), (0, 2))
        self.assertIn("Unprocessable", inline["error"])
        general = [c for c in self.calls() if c["args"][:2] == ["pr", "comment"]]
        comment = next(iter(general[0]["files"].values()))
        self.assertIn("`due.ts:1`", comment)
        self.assertIn("`app.ts:40`", comment)

    def test_the_publish_output_says_how_findings_were_posted(self):
        _sha, _url, _out, body = self.to_body(extra=[
            {"args": ["api", "--method", "POST"], "stdout": "{}"},
            {"args": ["pr", "comment"], "stdout": "https://x/pull/12#issuecomment-5\n"}])
        body.write_text(re.sub(r"<!-- WRITE: .*?-->", "Todos can carry a due date.",
                               body.read_text()))
        r = self.autodev("pr", "publish", "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("1 posted inline, 1 in a general comment", r.stdout)

    def test_a_secret_looking_finding_does_not_blank_the_others(self):
        self.review_text = self.review_text.replace(
            "| C6 |", "| C7 | token = abcdef1234567890XYZ | `due.ts:1` | security | 1/3 "
            "| Low | test data |\n| C6 |")
        self.open_pr(extra=[
            {"args": ["api", "--method", "POST"], "stdout": "{}"},
            {"args": ["pr", "comment"], "stdout": "https://x/pull/12#issuecomment-5\n"}])
        review = [c for c in self.calls() if c["args"][:3] == ["api", "--method", "POST"]]
        payload = json.loads(next(iter(review[0]["files"].values())))
        self.assertEqual([c["body"].split("\n")[0] for c in payload["comments"]],
                         ["**Advisory** (confidence Low): magic number"])
        inline = self.state()["phase6"]["inline"]
        self.assertEqual((inline["inline"], inline["general"], inline["error"]), (1, 1, ""))

    def test_the_user_s_diff_settings_do_not_hide_the_diff(self):
        for key, value in (("diff.noprefix", "true"), ("color.diff", "always"),
                           ("color.ui", "always")):
            self.sh("git", "config", key, value, cwd=self.worktree)
        self.open_pr(extra=[
            {"args": ["api", "--method", "POST"], "stdout": "{}"},
            {"args": ["pr", "comment"], "stdout": "https://x/pull/12#issuecomment-5\n"}])
        inline = self.state()["phase6"]["inline"]
        self.assertEqual((inline["inline"], inline["general"]), (1, 1))

    def test_nothing_is_posted_when_the_key_is_off(self):
        self.inline = False
        self.open_pr()
        self.assertFalse([c for c in self.calls() if c["args"][:1] == ["api"]
                          or c["args"][:2] == ["pr", "comment"]])
        self.assertNotIn("inline", self.state()["phase6"])


class CiTest(NextCase):
    ship_ready = ShipTest.ship_ready
    to_body = ShipTest.to_body
    open_pr = ShipTest.open_pr

    def test_red_ci_is_triaged_and_corrected_after_the_commit(self):
        state = self.state()
        state["settings"]["ci"] = "github"
        self.write_state(state)
        checks = [{"name": "test", "state": "FAILURE", "bucket": "fail",
                   "link": "https://ci/1"}]
        _sha, _ = self.open_pr(extra=[{"args": ["pr", "checks"],
                                      "stdout": json.dumps(checks)}])
        out = self.next(0)
        self.assertIn("ci-watch", out["ACTION"])
        r = self.autodev("ci-watch", "--dir", self.dir, "--max-wait", "0")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        out, jobs = self.expect("triager")
        self.assertEqual(self.sets(*jobs[0])["failing"], "test — https://ci/1")
        (self.dir / "triage" / "ci-1.md").write_text(
            "# Required changes\n1. Handle a missing due date in src/sort.ts\n")
        self.answer(*jobs[0], "CODE", blockers="0", acceptance_checks="0",
                    triage_file=str(self.dir / "triage" / "ci-1.md"), checks_file="none")
        out, jobs = self.expect("coder")
        (self.worktree / "sort.ts").write_text("export const sort = 1;\n")
        self.answer(*jobs[0], "BUILT", blocked="0", test_changes="none")
        self.assertEqual(self.sets(*jobs[0])["corrections_file"],
                         f"{self.dir}/triage/ci-1.md")
        self.assertIn("ci-1", out["BUDGET"])
        out, jobs = self.expect("cleanup", "GREEN")
        self.assertEqual(self.sets(*jobs[0]), {"scope": "after-commit"})
        self.expect("verifier", "ALL_MET", tree="x", corrections="0")
        out, jobs = self.expect("code-reviewer")
        self.assertEqual(self.sets(*jobs[0])["scope"], "after-commit")

    def test_red_ci_with_no_round_left_stops_and_names_the_check(self):
        state = self.state()
        state["settings"]["ci"] = "github"
        self.write_state(state)
        checks = [{"name": "test", "state": "FAILURE", "bucket": "fail",
                   "link": "https://ci/1"}]
        self.open_pr(extra=[{"args": ["pr", "checks"], "stdout": json.dumps(checks)}])
        self.next(0)
        self.autodev("ci-watch", "--dir", self.dir, "--max-wait", "0")
        _, jobs = self.expect("triager")
        state = self.state()
        state["budget"]["remaining"] = 0
        state["settings"]["checkpoint_events"] = 1  # the stop still wins
        self.write_state(state)
        (self.dir / "triage" / "ci-1.md").write_text("# Required changes\n1. x\n")
        self.answer(*jobs[0], "CODE", blockers="0", acceptance_checks="0",
                    triage_file=str(self.dir / "triage" / "ci-1.md"), checks_file="none")
        report = " ".join(self.next(4)["REPORT"])
        self.assertIn("stop and report each red check", report)
        self.assertIn("Red checks: test — https://ci/1", report)
        self.assertNotIn("hold", report)


    @staticmethod
    def checks(started, **extra):
        return {"args": ["pr", "checks"], **extra, "stdout": json.dumps(
            [{"name": "test", "state": "SUCCESS", "bucket": "pass", "link": "https://ci/1",
              "startedAt": started}])}

    GREEN = (checks.__func__("2999-01-01T00:00:00Z"),)  # started after any mark

    def github_ci(self):
        state = self.state()
        state["settings"]["ci"] = "github"
        self.write_state(state)

    def watch(self, code=0):
        self.assertIn("ci-watch", self.next(0)["ACTION"])
        r = self.autodev("ci-watch", "--dir", self.dir, "--max-wait", "0")
        self.assertEqual(r.returncode, code, r.stdout + r.stderr)

    def ready(self, extra=None):
        self.github_ci()
        sha, _ = self.open_pr(extra=extra or self.GREEN)
        self.watch()
        self.expect("triager", "TRIAGED", blockers="0", acceptance_checks="0",
                    triage_file="none", checks_file="none")
        out = self.next(0)
        self.assertIn("gh pr ready 12", out["ACTION"])
        self.after(out)
        return sha

    def test_ci_is_watched_again_once_the_pr_is_ready(self):
        self.ready()
        self.watch()  # workflows that skip drafts run now
        self.assertIn("main gate", self.next(5)["QUESTION"])

    def test_the_draft_s_green_checks_do_not_count_once_the_pr_is_ready(self):
        old = self.checks("2000-01-01T00:00:00Z", times=2)
        self.ready(extra=[old, *self.GREEN])
        self.watch(3)  # only the draft's checks so far: still pending
        self.watch()  # a check started after the mark: green
        self.assertIn("main gate", self.next(5)["QUESTION"])

    def test_a_resume_after_the_merge_goes_on_from_the_merge(self):
        sha = self.ready()
        self.watch()
        self.after(self.next(5), "Merge PR to main")
        r = self.autodev("merge-pr", "--pr", "12", "--sha", sha, "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        state = self.state()
        state["phase6"]["ci"]["status"] = "timeout"  # nothing before the merge re-runs
        self.write_state(state)
        self.resume()
        out = self.next(0)
        self.assertIn("mark main-ci", out["AFTER"][0])

    def test_a_failed_findings_post_reaches_the_final_report(self):
        sha = self.ready()
        self.watch()
        self.after(self.next(5), "Merge PR to main")
        r = self.autodev("merge-pr", "--pr", "12", "--sha", sha, "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        state = self.state()
        state["phase6"]["inline"] = {"sha": sha, "inline": 0, "general": 0,
                                     "error": "general comment: Forbidden"}
        self.write_state(state)
        self.assertIn("mark main-ci", self.next(0)["AFTER"][0])
        r = self.autodev("mark", "main-ci", "--value", "green", "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        out = self.next(0)
        self.assertIn("final report", out["ACTION"])
        self.assertIn("could not all be posted on the PR (general comment: Forbidden)",
                      out["ACTION"])

    def test_the_main_gate_comes_next_and_shows_only_people_s_comments(self):
        self.ready()
        self.watch()
        # A staging branch on origin is ignored: the next gate is the main gate.
        self.sh("git", "push", "-q", "origin", "origin/main:refs/heads/staging",
                cwd=self.worktree)
        sys.path.insert(0, str(SCRIPTS))
        marker = import_module("lib.cmd_pr").MARKER
        responses = json.loads((self.tmp / "gh.json").read_text())
        sha = self.state()["phase6"]["verified_sha"]
        responses.insert(0, {"args": ["pr", "view", "12", "--json"], "stdout": json.dumps({
            "url": "https://github.com/acme/app/pull/12", "isDraft": False,
            "state": "OPEN", "headRefOid": sha,
            "comments": [{"body": f"Command output\n\n{marker}"}, {"body": "LGTM"}],
            "reviews": [{"body": f"Findings\n\n{marker}"}]})})
        self.script_gh(responses)
        out = self.next(5)
        summary = " ".join(out["SUMMARY"])
        self.assertIn("main", out["QUESTION"])
        self.assertNotIn("staging", (out["QUESTION"] + summary).lower())
        self.assertIn("1 human review(s)/comment(s)", summary)

    def test_red_ci_the_code_cannot_fix_holds_before_jira(self):
        self.github_ci()
        checks = [{"name": "test", "state": "FAILURE", "bucket": "fail",
                   "link": "https://ci/1"}]
        self.open_pr(extra=[{"args": ["pr", "checks"], "stdout": json.dumps(checks)}])
        self.watch(1)
        self.expect("triager", "INFRA", blockers="0", acceptance_checks="0",
                    triage_file="none", checks_file="none")
        report = " ".join(self.next(4)["REPORT"])
        self.assertIn("INFRA", report)
        self.assertIn("triage/ci-1.md", report)
        self.assertIn("The run stops here", report)

    def test_a_secret_ci_failure_stops_and_continue_watches_again(self):
        self.github_ci()
        checks = [{"name": "test", "state": "FAILURE", "bucket": "fail",
                   "link": "https://ci/1"}]
        self.open_pr(extra=[{"args": ["pr", "checks"], "stdout": json.dumps(checks)}])
        self.watch(1)
        self.expect("triager", "SECRET", blockers="0", acceptance_checks="0",
                    triage_file="none", checks_file="none")
        report = " ".join(self.next(4)["REPORT"])
        self.assertIn("Once the secret is fixed and CI re-run", report)
        self.assertNotIn("do not re-run", report)
        self.resume()
        self.assertIn("ci-watch", self.next(0)["ACTION"])

    def test_the_main_gate_shows_ci_that_timed_out_as_not_monitored(self):
        self.ready()
        state = self.state()
        state["phase6"]["ci"]["status"] = "timeout"
        state["phase6"]["ci"]["seq"] = state["events"] + 1
        self.write_state(state)
        out = self.next(5)
        self.assertIn("CI: not monitored (timeout) — never assume green",
                      " ".join(out["SUMMARY"]))


class HumanAndMainGateTest(NextCase):
    ship_ready = ShipTest.ship_ready
    to_body = ShipTest.to_body
    open_pr = ShipTest.open_pr

    def test_a_reviewer_blocker_becomes_a_correction(self):
        self.open_pr()
        _, jobs = self.expect("triager")
        self.assertEqual(next(b for b in self.state()["briefs"]
                              if (b["worker"], b["n"]) == jobs[0])["mode"], "human")
        (self.dir / "triage" / "human-1.md").write_text(
            "# Required changes\n1. c-77: keep the field name when it is empty\n")
        self.answer(*jobs[0], "TRIAGED", blockers="1", acceptance_checks="0",
                    triage_file=str(self.dir / "triage" / "human-1.md"), checks_file="none")
        out, jobs = self.expect("coder")
        self.assertEqual(self.sets(*jobs[0])["corrections_file"],
                         f"{self.dir}/triage/human-1.md")
        self.assertIn("human-1", out["BUDGET"])

    def push_outside(self, text):
        """Someone pushes a commit changing app.ts to the PR branch."""
        branch = self.state()["branch"]
        other = self.tmp / "other"
        if not other.exists():
            self.sh("git", "clone", "-q", "-b", branch, str(self.tmp / "origin.git"),
                    str(other))
        (other / "app.ts").write_text(text)
        self.sh("git", "commit", "-q", "-am", "reword", cwd=other)
        self.sh("git", "push", "-q", "origin", branch, cwd=other)
        return branch

    def held_then_pushed(self):
        """Eval 16 up to its stop; returns (old verified sha, PR url, branch)."""
        old, url = self.open_pr()
        self.expect("triager", "TRIAGED", blockers="0", acceptance_checks="0",
                    triage_file="none", checks_file="none")
        out = self.next(0)
        self.assertIn("gh pr ready", out["ACTION"])
        self.after(out)
        out = self.next(5)
        self.assertIn("main", out["QUESTION"])
        self.after(out, "Hold")
        self.next(4)
        branch = self.push_outside("export const one = 1; // reworded\n")
        self.resume()  # un-holds the main gate
        out = self.next(4)
        report = " ".join(out["REPORT"])
        self.assertIn("someone pushed", report)
        self.assertIn("app.ts", report)
        self.assertNotIn("QUESTION", out)  # the main gate is not asked
        self.assertNotIn("merge-pr", json.dumps(out))
        self.assertIn(f"merge --ff-only origin/{branch}", report)
        return old, url, branch

    def recheck(self, old, branch, edit=None):
        """The user brings the commits in; the re-check runs up to the commit
        action. `edit` is a file cleanup writes during it. Returns the new HEAD
        and the review pass."""
        self.sh("git", "merge", "-q", "--ff-only", f"origin/{branch}", cwd=self.worktree)
        head = self.sh("git", "rev-parse", "HEAD", cwd=self.worktree).strip()
        _, jobs = self.expect("cleanup")
        self.assertEqual(self.sets(*jobs[0])["scope"], "outside")
        self.assertEqual(self.state()["phase6"]["unverified_commit"], head)
        if edit:
            (self.worktree / edit).write_text("export const tidy = 1;\n")
        self.lint()
        self.answer(*jobs[0], "GREEN")
        self.spec_eval()
        self.expect("verifier", "ALL_MET", tree="x", corrections="0")
        self.panel()  # asserts three reviewers
        p = self.state()["phase6"]["passes"][-1]
        self.assertEqual((p["scope"], p["since"]), ("outside", old))
        sets = self.sets("code-reviewer", max(n for w, n in (
            (b["worker"], b["n"]) for b in self.state()["briefs"]) if w == "code-reviewer"))
        self.assertEqual((sets["scope"], sets["files"], sets["since"]),
                         ("outside", ", ".join(p["files"]), old))
        (self.dir / "SECURITY_REVIEW.md").write_text(SECURITY_REVIEW.format(
            tree=self.tree()))
        self.expect("security-reviewer-sensitive", "CLEAN", must_fix="0", pre_existing="0")
        self.assertIn("commit: run", self.next(0)["ACTION"])
        return head, p

    def to_main_gate(self, url, head):
        """From a verified `head` to the main gate asked again."""
        out = self.next(0)
        self.assertIn("push -u origin HEAD", out["ACTION"])
        self.sh("git", "push", "-q", "-u", "origin", "HEAD", cwd=self.worktree)
        self.after(out)
        self.script_gh(GH_OK + [
            {"args": ["repo", "view", "--json", "url"], "stdout": json.dumps({"url": url})},
            {"args": ["pr", "view", "12", "--json", "body"], "stdout": '{"body": ""}'},
            {"args": ["pr", "edit"], "stdout": ""},
            {"args": ["pr", "view", "12", "--json", "number,url,body"],
             "stdout": json.dumps({"number": 12, "url": f"{url}/pull/12",
                                   "body": f"Checked at commit {head}"})},
            {"args": ["pr", "view", "12", "--json"],
             "stdout": json.dumps({"url": f"{url}/pull/12", "isDraft": False,
                                   "state": "OPEN", "headRefOid": head})}])
        out = self.next(0)
        body = self.dir / "pr-body.md"
        self.assertIn(f"Checked at commit {head}", body.read_text())
        body.write_text(re.sub(r"<!-- WRITE: .*?-->", "Todos can carry a due date.",
                               body.read_text()))
        self.after(out)
        out = self.next(0)
        self.assertIn("pr publish", out["ACTION"])
        r = self.autodev("pr", "publish", "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.expect("triager", "TRIAGED", blockers="0", acceptance_checks="0",
                    triage_file="none", checks_file="none")
        out = self.next(5)
        self.assertIn("main", out["QUESTION"])
        self.assertIn(f"Head {head}", " ".join(out["SUMMARY"]))

    def verify_only(self, head):
        r = self.autodev("commit", "--message", "unused", "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(f"COMMITTED: {head}", r.stdout)  # verified, no new commit
        self.assertEqual(self.sh("git", "rev-parse", "HEAD", cwd=self.worktree).strip(), head)
        self.assertEqual(self.state()["phase6"]["verified_sha"], head)

    def test_an_outside_push_after_a_held_main_gate_is_re_checked_before_it_is_asked(self):
        # Eval 16: the main gate is held, someone pushes to the PR branch, and a
        # fresh session resumes the run.
        old, url, branch = self.held_then_pushed()
        self.sh("git", "fetch", "-q", "origin", cwd=self.worktree)
        before = self.state()
        self.sh("git", "merge", "-q", "--ff-only", f"origin/{branch}", cwd=self.worktree)
        r = self.autodev("next", "--explain", "--dir", self.dir)
        self.assertIn("re-check the PR branch's commits", r.stdout)
        self.assertEqual(self.state(), before)  # --explain writes nothing
        self.resume()
        head, p = self.recheck(old, branch)
        self.assertEqual(p["files"], ["app.ts"])
        self.verify_only(head)
        self.to_main_gate(url, head)

    def test_an_edit_made_while_re_checking_an_outside_push_is_reviewed(self):
        old, url, branch = self.held_then_pushed()
        head, p = self.recheck(old, branch, edit="other.ts")
        self.assertEqual(p["files"], ["app.ts", "other.ts"])  # the pass saw cleanup's edit
        r = self.autodev("commit", "--message", "chore: tidy", "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        new = self.state()["phase6"]["verified_sha"]
        self.assertNotEqual(new, head)  # cleanup's edit is committed on top
        self.to_main_gate(url, new)

    def test_a_second_outside_push_in_the_same_session_is_re_checked_too(self):
        old, url, branch = self.held_then_pushed()
        head, _ = self.recheck(old, branch)
        self.verify_only(head)
        self.to_main_gate(url, head)
        self.push_outside("export const one = 1; // reworded again\n")
        self.sh("git", "fetch", "-q", "origin", cwd=self.worktree)
        report = " ".join(self.next(4)["REPORT"])  # no resume: the same session
        self.assertIn("someone pushed", report)
        second, p = self.recheck(head, branch)  # not "stale twice running"
        self.assertEqual(p["files"], ["app.ts"])
        self.verify_only(second)


class ReVoteTest(NextCase):
    def test_lone_findings_are_re_voted_then_applied(self):
        self.plan_session()
        self.build_session()
        self.resume()
        _out, jobs = self.expect("code-reviewer")
        for w, n in jobs:
            slot = self.sets(w, n)["reviewer"]
            (self.dir / "review" / "pass-1" / f"{slot}.md").write_text(r_report("x"))
            self.answer(w, n, "REVIEWED", findings="1", leads="0")
        (self.dir / "CODE_REVIEW.md").write_text(CODE_REVIEW.format(tree=self.tree()))
        self.expect("review-judge", "REVOTE", must_fix_open="1", revote="2")
        _, jobs = self.expect("code-reviewer")
        voters = sorted(self.sets(w, n)["reviewer"] for w, n in jobs)
        self.assertEqual(voters, ["R1", "R2", "R3"])
        for w, n in jobs:
            slot = self.sets(w, n)["reviewer"]
            self.assertIn("C", self.sets(w, n)["findings"])
            rows = "".join(f"| {fid} | disagree | not reachable |\n" for fid in ("C4", "C6")
                           if fid in self.sets(w, n)["findings"])
            (self.dir / "review" / "pass-1" / f"VOTES-{slot}.md").write_text(
                "| Finding | Vote | Reason |\n|---|---|---|\n" + rows)
            self.answer(w, n, "VOTED", findings="1", leads="0")
        _, jobs = self.expect("coder")  # C1 is still open: a correction
        text = (self.dir / "CODE_REVIEW.md").read_text()
        self.assertNotIn("| C4 | empty list indexed | `src/list.ts:42` | correctness | R1", text)
        self.assertIn("lone finding; re-vote 1/3", text)

    def test_a_re_voter_that_fails_twice_stops(self):
        self.plan_session()
        self.build_session()
        self.resume()
        _out, jobs = self.expect("code-reviewer")
        for w, n in jobs:
            slot = self.sets(w, n)["reviewer"]
            (self.dir / "review" / "pass-1" / f"{slot}.md").write_text(r_report("x"))
            self.answer(w, n, "REVIEWED", findings="1", leads="0")
        (self.dir / "CODE_REVIEW.md").write_text(CODE_REVIEW.format(tree=self.tree()))
        self.expect("review-judge", "REVOTE", must_fix_open="1", revote="2")
        _, jobs = self.expect("code-reviewer")
        for w, n in jobs:
            slot = self.sets(w, n)["reviewer"]
            if slot == "R3":
                self.answer(w, n, "", status="failed")
                continue
            rows = "".join(f"| {fid} | disagree | not reachable |\n" for fid in ("C4", "C6")
                           if fid in self.sets(w, n)["findings"])
            (self.dir / "review" / "pass-1" / f"VOTES-{slot}.md").write_text(
                "| Finding | Vote | Reason |\n|---|---|---|\n" + rows)
            self.answer(w, n, "VOTED", findings="1", leads="0")
        _, jobs = self.expect("code-reviewer", "", status="failed")  # one more try
        self.assertEqual([self.sets(*j)["reviewer"] for j in jobs], ["R3"])
        out = self.next(4)
        self.assertIn("R3 (failed twice)", " ".join(out["REPORT"]))


class QuoteTest(RunCase):
    def test_printed_commands_survive_a_path_with_spaces(self):
        self.repo = self.tmp / "my app"
        self.sh("git", "clone", "-q", str(self.tmp / "origin.git"), str(self.repo))
        (self.repo / ".env").write_text("SECRET=1\n")
        self.worktree = self.tmp / "my app-due-dates"
        self.dir = self.worktree / ".auto-dev"
        r = self.init()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        out = json.loads(self.autodev("next", "--dir", self.dir, "--json").stdout)
        r = subprocess.run(out["AFTER"][0], shell=True, capture_output=True, text=True,
                           env=self.env, cwd=self.tmp, check=False)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)  # it ran: no result yet
        self.assertIn("MISSING", r.stdout)


class TextOutputTest(NextCase):
    def test_lines_are_printed_in_order(self):
        r = self.autodev("next", "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.splitlines()
        self.assertTrue(lines[0].startswith("ACTION: spawn auto-dev:define"))
        self.assertEqual(lines[1], "AGENT: auto-dev:define")
        self.assertTrue(lines[2].startswith(f"BRIEF: {self.dir}/briefs/define-1.md"))
        self.assertTrue(lines[3].startswith("PROMPT: Your brief is at"))
        self.assertTrue(lines[4].startswith("AFTER: python3 "))
        self.assertIn("record define 1", lines[4])
        self.assertFalse(any(ln.startswith("RULE:") for ln in lines))
        r = self.autodev("next", "--dir", self.dir, "--explain")
        self.assertIn("RULE: a brief was issued", r.stdout)
