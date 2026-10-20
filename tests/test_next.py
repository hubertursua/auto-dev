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
from test_autodev import GH_OK, SCRIPTS, RunCase
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
        r = self.autodev("next", "--dir", self.dir, "--json", "--explain")
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

    def spec_eval(self, v1="met"):
        (self.dir / "SPEC_EVAL.md").write_text(SPEC_EVAL.format(
            tree=self.tree(), v1=v1, v2="met", e2="ran the sort", judgment="Justified",
            defective="None."))

    def lint(self, status="pass"):
        (self.dir / "lint").mkdir(exist_ok=True)
        (self.dir / "lint" / "TEST.md").write_text(
            f"# TEST — {status}\n\n- **Command:** `true`\n- **Tree:** {self.tree()}\n\n"
            "## Output tail (final run)\n```\nall good\n```\n")

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

    def review_clean(self):
        _, jobs = self.expect("code-reviewer")
        self.assertEqual(len(jobs), 3)
        for w, n in jobs:
            slot = self.sets(w, n)["reviewer"]
            pass_dir = self.dir / "review" / f"pass-{self.state()['phase6']['review_pass']}"
            (pass_dir / f"{slot}.md").write_text(r_report("none"))
            self.answer(w, n, "REVIEWED", findings="0", leads="0")
        (self.dir / "CODE_REVIEW.md").write_text(CLEAN_REVIEW.format(tree=self.tree()))
        self.expect("review-judge", "CLEAN", must_fix_open="0", revote="0")
        (self.dir / "SECURITY_REVIEW.md").write_text(SECURITY_REVIEW.format(
            tree=self.tree()))
        self.expect("security-reviewer-sensitive", "CLEAN", must_fix="0", pre_existing="0")


class PlanTest(NextCase):
    def test_plan_session_ends_at_the_boundary(self):
        self.plan_session()
        state = self.state()
        self.assertEqual(state["phases"]["3"]["status"], "done")
        self.assertEqual(state["budget"]["remaining"], state["budget"]["total"])

    def test_oversized_stops_and_reports(self):
        self.expect("define", "OVERSIZED", high_risk="yes", reading="none")
        out = self.next(4)
        self.assertIn("too big for one PR", " ".join(out["REPORT"]))
        self.assertIn("Jira was not moved", " ".join(out["REPORT"]))

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
            "# Required changes\n1. Sort todos with no due date last in src/sort.ts\n")
        self.expect("review-judge", "MUST_FIX", must_fix_open="1", revote="0")
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

    def open_pr(self, extra=()):
        """Run S3 from the review to a published PR; returns (sha, url)."""
        self.ship_ready()
        self.review_clean()
        self.lint()
        self.spec_eval()
        out = self.next(5)
        self.assertIn("pr gate", out["QUESTION"])
        self.after(out, "Open PR")
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
        self.script_gh(GH_OK + [
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
            "# Required changes\n1. Sort todos with no due date last in src/sort.ts\n")
        self.expect("review-judge", "MUST_FIX", must_fix_open="1", revote="0")
        (self.dir / "SECURITY_REVIEW.md").write_text(SECURITY_REVIEW.format(
            tree=self.tree()))
        self.expect("security-reviewer-sensitive", "CLEAN", must_fix="0", pre_existing="0")
        out = self.next(5)
        self.assertIn("pr gate", out["QUESTION"])
        self.assertIn("Budget exhausted", " ".join(out["SUMMARY"]))

    def test_ship_session_runs_to_the_merge(self):
        sha, _ = self.open_pr()
        self.expect("triager", "TRIAGED", blockers="0", acceptance_checks="0")
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
        self.assertIn("## Checklist\n- [ ] I added tests\n- [ ] Docs updated", text)
        self.assertNotIn("Please check", text)

    def test_a_folder_of_several_templates_has_no_default(self):
        self.write(".github/PULL_REQUEST_TEMPLATE/bug.md", "## Bug\n")
        self.write(".github/PULL_REQUEST_TEMPLATE/feature.md", "## Feature\n")
        self.assertIsNone(self.cmd_pr.find_template(self.tmp))
        (self.tmp / ".github/PULL_REQUEST_TEMPLATE/feature.md").unlink()
        self.assertEqual(self.cmd_pr.find_template(self.tmp).name, "bug.md")

    def test_no_template_adds_nothing(self):
        self.assertEqual(self.cmd_pr.template_sections(self.cmd_pr.find_template(self.tmp)),
                         [])


class TicketTest(NextCase):
    open_pr = ShipTest.open_pr

    def ship_ready(self):
        ShipTest.ship_ready(self)
        state = self.state()
        state["task"].update(ticket="TODO-7", ticket_url="https://acme.atlassian.net/browse/TODO-7")
        self.write_state(state)

    def test_the_ticket_is_linked_in_the_summary(self):
        self.open_pr()
        text = (self.dir / "pr-body.md").read_text()
        summary = text.split("## Acceptance conditions")[0]
        self.assertIn("Ticket: [TODO-7](https://acme.atlassian.net/browse/TODO-7)", summary)


class CiTest(NextCase):
    ship_ready = ShipTest.ship_ready
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
        self.answer(*jobs[0], "CODE", blockers="0", acceptance_checks="0")
        out, jobs = self.expect("coder", "BUILT", blocked="0", test_changes="none")
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
        self.write_state(state)
        (self.dir / "triage" / "ci-1.md").write_text("# Required changes\n1. x\n")
        self.answer(*jobs[0], "CODE", blockers="0", acceptance_checks="0")
        report = " ".join(self.next(4)["REPORT"])
        self.assertIn("stop and report each red check", report)
        self.assertNotIn("hold", report)


class HumanAndMainGateTest(NextCase):
    ship_ready = ShipTest.ship_ready
    open_pr = ShipTest.open_pr

    def test_a_reviewer_blocker_becomes_a_correction(self):
        self.open_pr()
        _, jobs = self.expect("triager")
        self.assertEqual(next(b for b in self.state()["briefs"]
                              if (b["worker"], b["n"]) == jobs[0])["mode"], "human")
        (self.dir / "triage" / "human-1.md").write_text(
            "# Required changes\n1. c-77: keep the field name when it is empty\n")
        self.answer(*jobs[0], "TRIAGED", blockers="1", acceptance_checks="0")
        out, jobs = self.expect("coder")
        self.assertEqual(self.sets(*jobs[0])["corrections_file"],
                         f"{self.dir}/triage/human-1.md")
        self.assertIn("human-1", out["BUDGET"])

    def test_an_outside_push_to_the_pr_branch_stops_before_the_main_gate(self):
        self.open_pr()
        self.expect("triager", "TRIAGED", blockers="0", acceptance_checks="0")
        out = self.next(0)
        self.assertIn("gh pr ready", out["ACTION"])
        self.after(out)
        branch = self.state()["branch"]
        other = self.tmp / "other"
        self.sh("git", "clone", "-q", "-b", branch, str(self.tmp / "origin.git"), str(other))
        (other / "app.ts").write_text("export const one = 1; // reworded\n")
        self.sh("git", "commit", "-q", "-am", "reword", cwd=other)
        self.sh("git", "push", "-q", "origin", branch, cwd=other)
        report = " ".join(self.next(4)["REPORT"])
        self.assertIn("someone pushed", report)
        self.assertIn("app.ts", report)
        log = (self.tmp / "gh.log").read_text()
        self.assertNotIn('"merge"', log)


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
