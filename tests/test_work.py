"""Tests for autodev.py brief / record / check-artifact.

Run: python3 -m unittest discover -s tests -v   (from the repo root)
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_autodev import SCRIPTS, RunCase
from test_autodev import RunCase as InitCase
from test_parsers import CODE_REVIEW, FIXTURES, MANIFEST, PLAN, SPEC_EVAL

# The fixture plan at standard risk: no Security/Compliance criteria.
PLAN_NO_SECURITY = PLAN.replace("Risk: high", "Risk: standard").split(
    "## Security/Compliance criteria")[0] + "## Size check" + PLAN.split("## Size check")[1]
PLANNED = {"risk": "high", "reading": "none", "entry_points_changed": "no"}


def plan_review(verdict="APPROVE", risk="high", blockers=()):
    """A plan critic's review file; `blockers` are (evidence, change) pairs."""
    rows = "".join(f"### B{i}. the plan misses case {i}\n- Evidence: {ev}\n- Change: {ch}\n\n"
                   for i, (ev, ch) in enumerate(blockers, 1)) or "none\n\n"
    return (f"# Plan review — review\n\nVerdict: {verdict}\nRisk: {risk} — right\n\n"
            f"## Blockers\n{rows}## Notes\nnone\n")
# The result keys most tests leave at their default: nothing found.
DEFAULT_KEYS = {"coder": {"deviations": "0"}, "verifier": {"spec_problems": "0"},
                "review-judge": {"spec_problems": "0"},
                "security-reviewer": {"spec_problems": "0"},
                "security-reviewer-sensitive": {"spec_problems": "0"},
                "triager": {"spec_problems": "0"}}
CORRECTION = ("# Required changes\n1. Show the due date next to the title in src/list.ts\n"
              "   Where: `src/list.ts:12` — the row renderer\n")


class WorkCase(RunCase):
    def setUp(self):
        super().setUp()
        self.assertEqual(self.init().returncode, 0)
        (self.dir / "PLAN.md").write_text(PLAN)
        (self.dir / "acceptance").mkdir(exist_ok=True)
        (self.dir / "acceptance" / "MANIFEST.md").write_text(MANIFEST)

    def cmd(self, *args):
        return self.autodev(*args, "--dir", self.dir)

    def brief_values(self, path):
        values = {}
        for line in Path(path).read_text().splitlines()[1:]:
            if not line.startswith("  "):
                name, _, value = line.partition(": ")
                values[name] = value
        return values

    def job(self, worker, as_mode=None, **sets):
        args = [a for k, v in sets.items() for a in ("--set", f"{k}={v}")]
        r = self.cmd("brief", worker, *(("--mode", as_mode) if as_mode else ()), *args)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return int(Path(r.stdout.split("BRIEF:")[1].split()[0]).stem.rsplit("-", 1)[1])

    def returned(self, worker, n, status="ok", **data):
        path = self.dir / "returns" / f"{worker}-{n}.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps({"worker": worker, "status": status,
                                    **DEFAULT_KEYS.get(worker, {}), **data}))

    def write(self, rel, text):
        path = self.dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def state_size(self, size):
        state = self.state()
        state["size"] = size
        self.write_state(state)

    def spec_eval(self, v1="met", defective="None."):
        self.write("SPEC_EVAL.md", SPEC_EVAL.format(
            tree="0" * 40, v1=v1, v2="met", e2="x", judgment="Justified",
            defective=defective))


class BriefTest(WorkCase):
    def test_planner_brief_fills_its_slots_from_state(self):
        r = self.cmd("brief", "planner", "--mode", "write")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("agent: auto-dev:planner", r.stdout)
        path = self.dir / "briefs" / "planner-1.md"
        self.assertIn(f"prompt: Your brief is at {path}. Read it first.", r.stdout)
        values = self.brief_values(path)
        self.assertEqual(values["mode"], "write")
        self.assertEqual(values["worktree"], str(self.worktree))
        self.assertEqual(values["task"], "Add due dates to todos")
        self.assertEqual(values["result_file"], str(self.dir / "returns" / "planner-1.json"))
        self.assertIn("CLAUDE.md", values["binding_rules"])
        self.cmd("brief", "planner", "--mode", "write")
        self.assertTrue((self.dir / "briefs" / "planner-2.md").exists())

    def test_the_critic_s_review_file_is_filled_and_the_planner_s_is_optional(self):
        r = self.cmd("brief", "plan-critic", "--mode", "review")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        values = self.brief_values(self.dir / "briefs" / "plan-critic-1.md")
        self.assertEqual(values["review_file"], str(self.dir / "plan-review" / "1.md"))
        self.assertEqual(values["task"], "Add due dates to todos")
        r = self.cmd("brief", "plan-critic", "--mode", "recheck", "--set",
                     f"earlier={self.dir}/plan-review/1.md")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        values = self.brief_values(self.dir / "briefs" / "plan-critic-2.md")
        self.assertEqual(values["earlier"], f"{self.dir}/plan-review/1.md")
        self.assertEqual(values["review_file"], str(self.dir / "plan-review" / "2.md"))

    def test_coder_correction_brief_names_the_acceptance_paths(self):
        r = self.cmd("brief", "coder", "--mode", "correction", "--set",
                     f"corrections_file={self.dir}/evidence/corrections.md")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        values = self.brief_values(self.dir / "briefs" / "coder-1.md")
        # A file can hold the coder's tests too, so the brief names the checks.
        self.assertEqual(values["acceptance_paths"],
                         'src/due.acceptance.test.ts (tests: "shows the due date", '
                         '"rejects an invalid date", "owner only"); '
                         'src/sort.acceptance.test.ts (tests: "sorts earliest first")')

    def test_missing_caller_slots_are_refused(self):
        r = self.cmd("brief", "code-reviewer", "--mode", "review")
        self.assertEqual(r.returncode, 1)
        self.assertIn("--set reviewer=...", r.stderr)
        self.assertIn("--set scope=...", r.stderr)
        self.assertFalse((self.dir / "briefs").exists() and
                         list((self.dir / "briefs").glob("code-reviewer-*")))

    def test_mode_and_unknown_slots_are_checked(self):
        self.assertEqual(self.cmd("brief", "planner").returncode, 1)
        r = self.cmd("brief", "planner", "--mode", "write", "--set", "colour=blue")
        self.assertEqual(r.returncode, 1)
        self.assertIn("colour", r.stderr)

    def test_optional_slots_default_to_none(self):
        r = self.cmd("brief", "planner", "--mode", "revise", "--set", "direction=use UTC")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        values = self.brief_values(self.dir / "briefs" / "planner-1.md")
        self.assertEqual(values["review_file"], "none")
        self.assertEqual(values["direction"], "use UTC")

    def test_a_standard_risk_verifier_runs_no_mutation_and_no_probes(self):
        r = self.cmd("brief", "verifier", "--set", "mode=first pass")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        values = self.brief_values(self.dir / "briefs" / "verifier-1.md")
        self.assertEqual(values["mutation_cap"], "0 (off: a standard-risk run)")
        self.assertEqual(values["probes"], "off (a standard-risk run)")

    def test_verifier_brief_carries_the_last_survivors(self):
        state = json.loads((self.dir / "state.json").read_text())
        state["high_risk"] = True  # mutation and probes run on a high-risk run
        (self.dir / "state.json").write_text(json.dumps(state))
        (self.dir / "SPEC_EVAL.md").write_text(SPEC_EVAL.format(
            tree="0" * 40, v1="met", v2="met", e2="x", judgment="Justified",
            defective="None."))
        r = self.cmd("brief", "verifier", "--set", "mode=re-check",
                     "--set", "what_changed=a correction")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        text = (self.dir / "briefs" / "verifier-1.md").read_text()
        self.assertIn("| M2 | `src/sort.ts:4` |", text)
        self.assertIn("mutation_cap: 20", text)
        self.assertIn("probes: on", text)
        modes = [ln for ln in text.splitlines() if ln.startswith("mode:")]
        self.assertEqual(modes, ["mode: re-check"])

    def test_cut_is_the_literal_merge_base(self):
        # A worker's git commands use the sha itself: a headless run refuses
        # `$(git merge-base …)`, and the brief must stay put when origin moves.
        cut = self.sh("git", "-C", str(self.worktree), "merge-base", "origin/main",
                      "HEAD").strip()
        (self.worktree / "late.txt").write_text("x\n")
        self.sh("git", "-C", str(self.worktree), "add", "late.txt")
        self.sh("git", "-C", str(self.worktree), "commit", "-q", "-m", "late")
        r = self.cmd("brief", "verifier", "--set", "mode=first pass")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        values = self.brief_values(self.dir / "briefs" / "verifier-1.md")
        self.assertEqual(values["cut"], cut)
        # origin/main moving on after a fetch leaves the cut where it was.
        seed = self.tmp / "seed"
        self.sh("git", "-C", str(seed), "pull", "-q", "origin", "main")
        (seed / "upstream.txt").write_text("y\n")
        self.sh("git", "-C", str(seed), "add", "upstream.txt")
        self.sh("git", "-C", str(seed), "commit", "-q", "-m", "upstream")
        self.sh("git", "-C", str(seed), "push", "-q", "origin", "main")
        self.sh("git", "-C", str(self.worktree), "fetch", "-q", "origin")
        r = self.cmd("brief", "verifier", "--set", "mode=first pass")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        values = self.brief_values(self.dir / "briefs" / "verifier-2.md")
        self.assertEqual(values["cut"], cut)

    def test_coder_brief_gives_a_run_command_for_each_gate_check(self):
        # The coder runs each check through `autodev.py run`, never by typing
        # the profile's command (a permission check refuses `cd <wt> && …`).
        r = self.cmd("brief", "coder", "--mode", "build")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        text = (self.dir / "briefs" / "coder-1.md").read_text()
        runs = re.findall(r"run: `([^`]+)`", text)
        self.assertEqual(len(runs), 1, text)
        self.assertIn(" run gate 1 --dir ", runs[0])
        done = subprocess.run(runs[0], shell=True, cwd=self.tmp, env=self.env,
                              capture_output=True, text=True, check=False)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertTrue(done.stdout.startswith("PASSED: `true` exited 0"), done.stdout)

    def test_cut_without_the_base_cannot_run(self):
        self.sh("git", "-C", str(self.worktree), "update-ref", "-d",
                "refs/remotes/origin/main")
        r = self.cmd("brief", "verifier", "--set", "mode=first",
                     "--set", "what_changed=none")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("merge-base origin/main HEAD", r.stdout + r.stderr)

    def test_judge_tree_comes_from_the_caller(self):
        args = ("brief", "review-judge", "--mode", "consolidate",
                "--set", "reviewers=R1, R2, R3", "--set", "scope=whole change")
        r = self.cmd(*args)
        self.assertEqual(r.returncode, 1)
        self.assertIn("--set tree=...", r.stderr)
        r = self.cmd(*args, "--set", "tree=" + "a" * 40)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        values = self.brief_values(self.dir / "briefs" / "review-judge-1.md")
        self.assertEqual(values["tree"], "a" * 40)

    def test_refused_issues_reach_only_that_jobs_retry(self):
        self.returned("planner", 1, next="FITS", **{**PLANNED, "risk": "standard"})
        self.assertEqual(self.cmd("record", "planner", "1").returncode, 1)
        self.assertEqual(self.cmd("brief", "planner", "--mode", "write", "--retry", "1")
                         .returncode, 0)
        text = (self.dir / "briefs" / "planner-1.md").read_text()
        self.assertIn("\n  - risk is standard but PLAN.md's `Risk:` line says high", text)
        # A fix-up, not a redo: the refused return's files are kept.
        self.assertIn("previous_issues: `record` refused your last return for this job, "
                      "and the files you wrote for it are still in place.", text)
        self.assertIn("redo what your fix makes stale", text)
        self.assertIn("even where your instructions say to start clean", text)
        self.assertIn("If they are missing, partial or from an earlier pass", text)
        self.cmd("brief", "planner", "--mode", "write")
        values = self.brief_values(self.dir / "briefs" / "planner-2.md")
        self.assertEqual(values["previous_issues"], "none")
        self.returned("planner", 1, next="FITS", **PLANNED)
        self.assertEqual(self.cmd("record", "planner", "1").returncode, 0)
        r = self.cmd("brief", "planner", "--mode", "write", "--retry", "1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("refused no return for planner-1", r.stderr)

    def test_sibling_jobs_keep_their_own_issues(self):
        # Three reviewers in parallel: R1 wrote nothing, R2 is fine, R3 left a key out.
        self.returned("code-reviewer", 2, next="REVIEWED", findings="2", leads="0")
        self.returned("code-reviewer", 3, next="REVIEWED", findings="1")
        self.assertEqual(self.cmd("record", "code-reviewer", "1").returncode, 1)
        self.assertEqual(self.cmd("record", "code-reviewer", "2").returncode, 0)
        self.assertEqual(self.cmd("record", "code-reviewer", "3").returncode, 1)

        def retry(n, slot):
            r = self.cmd("brief", "code-reviewer", "--mode", "review", "--retry", str(n),
                         "--set", f"reviewer={slot}", "--set", "scope=whole change")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            return Path(r.stdout.split("BRIEF: ", 1)[1].splitlines()[0]).read_text()
        self.assertIn("you wrote no result file", retry(1, "R1"))
        self.assertNotIn("`leads`", retry(1, "R1"))
        self.assertIn("`leads`", retry(3, "R3"))
        # Only a return there is to fix up gets the fix-up line: R1 returned nothing.
        self.assertNotIn("still in place", retry(1, "R1"))
        self.assertIn("refused your last return for this job, and the files", retry(3, "R3"))
        self.assertEqual(self.cmd("brief", "code-reviewer", "--mode", "review", "--retry",
                                  "2", "--set", "reviewer=R2", "--set", "scope=x")
                         .returncode, 1)
        # A judge's refused consolidate return never reaches a security-verify brief.
        self.returned("review-judge", 1, next="CLEAN", must_fix_open="0", revote="0")
        self.write("CODE_REVIEW.md", CODE_REVIEW.format(tree="0" * 40))
        self.assertEqual(self.cmd("record", "review-judge", "1").returncode, 1)
        self.cmd("brief", "review-judge", "--mode", "security-verify")
        values = self.brief_values(self.dir / "briefs" / "review-judge-1.md")
        self.assertEqual(values["previous_issues"], "none")

    def test_profiler_brief_needs_no_run(self):
        out = self.tmp / "prof"
        r = self.autodev("brief", "profiler", "--out", out, "--set", f"repo={self.repo}",
                         "--set", "base=main", "--set", f"draft_path={out}/p.yml")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((out / "profiler-1.md").exists())

    def test_lookup_brief_before_the_run_needs_no_state(self):
        out = self.tmp / "look"
        r = self.autodev("brief", "lookup", "--out", out, "--set", f"worktree={self.repo}",
                         "--set", "question=is eslint adopted?")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        values = self.brief_values(out / "lookup-1.md")
        self.assertEqual(values["answer_file"], str(out.resolve() / "lookup-1-answer.md"))
        self.assertEqual(values["result_file"], str(out.resolve() / "lookup-1.json"))
        self.assertEqual(values["worktree"], str(self.repo))


class RecordTest(WorkCase):
    def test_the_planner_s_size_and_risk_are_recorded_and_checked_against_the_plan(self):
        self.returned("planner", 1, next="FITS", **{**PLANNED, "risk": "standard"})
        r = self.cmd("record", "planner", "1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("risk is standard but PLAN.md's `Risk:` line says high", r.stdout)
        self.returned("planner", 1, next="FITS", **PLANNED)
        r = self.cmd("record", "planner", "1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        state = self.state()
        self.assertEqual(state["size"], "FITS")
        self.assertTrue(state["high_risk"])
        self.assertTrue(state["settings"]["post_plan_gate"])

    def test_the_planner_s_size_must_match_the_plan_s_size_check(self):
        self.returned("planner", 1, next="OVERSIZED", **PLANNED)
        r = self.cmd("record", "planner", "1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("next is OVERSIZED but PLAN.md's size check says FITS", r.stdout)

    def test_security_criteria_need_a_high_risk_plan(self):
        self.write("PLAN.md", PLAN.replace("Risk: high", "Risk: standard"))
        self.returned("planner", 1, next="FITS", **{**PLANNED, "risk": "standard"})
        r = self.cmd("record", "planner", "1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("Security/Compliance criteria but its `Risk:` is not high", r.stdout)

    def test_a_standard_plan_is_recorded_standard(self):
        self.write("PLAN.md", PLAN_NO_SECURITY)
        self.returned("planner", 1, next="FITS", **{**PLANNED, "risk": "standard"})
        r = self.cmd("record", "planner", "1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        state = self.state()
        self.assertFalse(state["high_risk"])
        self.assertFalse(state["settings"].get("post_plan_gate"))

    def test_the_plan_is_checked_against_its_template(self):
        # The planner has no shell to run check-artifact: record does it.
        (self.dir / "PLAN.md").write_text(PLAN.replace(
            "   - Edge: an invalid date is rejected → 400\n", "", 1))
        self.returned("planner", 1, next="FITS", **PLANNED)
        r = self.cmd("record", "planner", "1")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("PLAN.md: condition 1 has no `Edge:` line", r.stdout)
        (self.dir / "PLAN.md").write_text(PLAN)
        r = self.cmd("record", "planner", "1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for nxt in ("REVISED", "PLAN_REVISED", "UPDATE_OLD_TEST"):  # every ok return
            (self.dir / "PLAN.md").write_text(PLAN.replace(
                "   - Verify by: unit\n", "", 1))
            self.returned("planner", 2, next=nxt, **PLANNED)
            r = self.cmd("record", "planner", "2")
            self.assertEqual(r.returncode, 1, nxt + r.stdout + r.stderr)
            self.assertIn("condition 2 has no `Verify by:` line", r.stdout)

    def test_oversized_stops_the_run(self):
        self.write("PLAN.md", PLAN.split("## Size check")[0] + "## Size check\n"
                   "OVERSIZED: three deliverables.\n")
        self.returned("planner", 1, next="OVERSIZED", **PLANNED)
        self.assertEqual(self.cmd("record", "planner", "1").returncode, 0)
        state = self.state()
        self.assertEqual(state["phases"]["2"]["status"], "stopped")
        self.assertFalse(state["high_risk"])  # an OVERSIZED plan raises nothing

    def test_a_revision_can_raise_the_risk_but_not_lower_it(self):
        self.write("PLAN.md", PLAN_NO_SECURITY)
        self.returned("planner", 1, next="FITS", **{**PLANNED, "risk": "standard"})
        self.assertEqual(self.cmd("record", "planner", "1").returncode, 0)
        self.assertFalse(self.state()["high_risk"])
        self.write("PLAN.md", PLAN)
        self.returned("planner", 2, next="REVISED", **PLANNED)
        self.assertEqual(self.cmd("record", "planner", "2").returncode, 0)
        state = self.state()
        self.assertTrue(state["high_risk"])
        self.assertTrue(state["settings"]["post_plan_gate"])
        self.write("PLAN.md", PLAN_NO_SECURITY)
        self.returned("planner", 3, next="REVISED", **{**PLANNED, "risk": "standard"})
        self.assertEqual(self.cmd("record", "planner", "3").returncode, 0)
        self.assertTrue(self.state()["high_risk"])

    def test_the_critic_can_t_lower_a_high_plan(self):
        self.state_size("FITS")  # PLAN.md is the fixture: Risk: high
        self.write("plan-review/1.md", plan_review("REVISE", "standard",
                                                   [("`src/due.ts:3`", "add a step")]))
        self.returned("plan-critic", 1, next="REVISE", blockers="1", risk="standard")
        r = self.cmd("record", "plan-critic", "1")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("the critic can't lower the tier", r.stdout)

    def test_the_critic_s_result_must_match_its_review(self):
        self.state_size("FITS")
        self.write("PLAN.md", PLAN_NO_SECURITY)
        self.write("plan-review/1.md", plan_review("REVISE", "standard",
                                                   [("`src/due.ts:3`", "add a step")]))
        for data, why in (
                ({"next": "APPROVE", "blockers": "1", "risk": "standard"},
                 "next is APPROVE but the review's verdict is REVISE"),
                ({"next": "REVISE", "blockers": "2", "risk": "standard"},
                 "blockers is 2 but the review lists 1"),
                ({"next": "REVISE", "blockers": "1", "risk": "high"},
                 "risk is high but the review's `Risk:` says standard")):
            self.returned("plan-critic", 1, **data)
            r = self.cmd("record", "plan-critic", "1")
            self.assertEqual(r.returncode, 1, r.stdout)
            self.assertIn(why, r.stdout)
        self.returned("plan-critic", 1, next="REVISE", blockers="1", risk="standard")
        r = self.cmd("record", "plan-critic", "1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_the_critic_must_write_its_review(self):
        self.returned("plan-critic", 1, next="APPROVE", blockers="0", risk="high")
        r = self.cmd("record", "plan-critic", "1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("plan-review/1.md does not exist", r.stdout)

    def test_a_high_risk_critic_raises_the_tier(self):
        self.write("PLAN.md", PLAN_NO_SECURITY)
        self.returned("planner", 1, next="FITS", **{**PLANNED, "risk": "standard"})
        self.assertEqual(self.cmd("record", "planner", "1").returncode, 0)
        self.write("plan-review/2.md", plan_review("APPROVE", "high"))
        self.returned("plan-critic", 2, next="APPROVE", blockers="0", risk="high")
        self.assertEqual(self.cmd("record", "plan-critic", "2").returncode, 0)
        state = self.state()
        self.assertTrue(state["high_risk"])
        self.assertTrue(state["settings"]["post_plan_gate"])
        self.assertIn("high risk, post-plan gate on: the plan critic says the risk is high",
                      [n["text"] for n in state["notes"]])

    def test_verifier_next_must_match_eval_status(self):
        (self.dir / "SPEC_EVAL.md").write_text(SPEC_EVAL.format(
            tree="0" * 40, v1="unmet", v2="met", e2="x", judgment="Justified",
            defective="None."))
        self.returned("verifier", 1, next="ALL_MET", tree="x", corrections="0")
        r = self.cmd("record", "verifier", "1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("eval-status says CORRECT", r.stdout)
        (self.dir / "evidence").mkdir(exist_ok=True)
        (self.dir / "evidence" / "corrections.md").write_text(
            "# Required changes\n1. Show the due date next to the title in src/list.ts\n")
        self.returned("verifier", 1, next="CORRECT", tree="x", corrections="1")
        r = self.cmd("record", "verifier", "1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("next: CORRECT", r.stdout)

    def test_a_plan_with_no_plan_file_is_refused(self):
        (self.dir / "PLAN.md").unlink()
        self.returned("planner", 1, next="FITS", **PLANNED)
        r = self.cmd("record", "planner", "1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("PLAN.md", r.stdout)

    def test_a_review_report_must_follow_its_template(self):
        state = self.state()
        state["phase6"] = {"review_pass": 1}
        self.write_state(state)
        self.assertEqual(self.cmd("brief", "code-reviewer", "--mode", "review", "--set",
                                  "reviewer=R2", "--set", "scope=first").returncode, 0)
        report = self.dir / "review" / "pass-1" / "R2.md"
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text("## Findings\nnone\n")
        self.returned("code-reviewer", 1, next="REVIEWED", findings="0", leads="0")
        r = self.cmd("record", "code-reviewer", "1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("R2.md: no `## Security leads` section", r.stdout)
        report.write_text("## Findings\nnone\n\n## Security leads\nnone\n\n"
                          "## Pre-existing\nnone\n")
        self.assertEqual(self.cmd("record", "code-reviewer", "1").returncode, 0)

    def test_a_must_fix_verdict_needs_its_corrections_file(self):
        from test_next import OPEN_REVIEW
        state = self.state()
        state["phase6"] = {"review_pass": 1}
        self.write_state(state)
        (self.dir / "CODE_REVIEW.md").write_text(OPEN_REVIEW.format(tree="0" * 40))
        self.returned("review-judge", 1, next="MUST_FIX", must_fix_open="1", revote="0")
        r = self.cmd("record", "review-judge", "1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("pass-1/corrections.md does not exist", r.stdout)

    def test_a_triaged_blocker_needs_a_required_change(self):
        self.assertEqual(self.cmd("brief", "triager", "--mode", "human").returncode, 0)
        self.returned("triager", 1, next="TRIAGED", blockers="1", acceptance_checks="0",
                      triage_file=str(self.dir / "triage" / "human-1.md"),
                      checks_file="none")
        r = self.cmd("record", "triager", "1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("human-1.md holds no required change", r.stdout)
        (self.dir / "triage" / "human-1.md").write_text(
            "# Required changes\n1. c-77: keep the field name when it is empty\n")
        self.assertEqual(self.cmd("record", "triager", "1").returncode, 0)

    def test_a_triage_file_named_through_a_symlink_is_this_triages_file(self):
        self.assertEqual(self.cmd("brief", "triager", "--mode", "human").returncode, 0)
        self.write("triage/human-1.md",
                   "# Required changes\n1. c-77: keep the field name when it is empty\n")
        self.write("triage/human-1-checks.md", "# Required changes\n1. 12345: the sort "
                   "check compares titles, not dates\n")
        link = self.tmp / "link"
        link.symlink_to(self.dir)
        self.returned("triager", 1, next="TRIAGED", blockers="1", acceptance_checks="1",
                      triage_file=str(link / "triage" / "human-1.md"),
                      checks_file=str(link / "triage" / "human-1-checks.md"))
        r = self.cmd("record", "triager", "1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.returned("triager", 1, next="TRIAGED", blockers="1", acceptance_checks="0",
                      triage_file=os.path.relpath(self.dir / "triage" / "human-1.md"),
                      checks_file="none")
        r = self.cmd("record", "triager", "1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("not this triage's file", r.stdout)

    def review_brief(self, mode="review", **sets):
        state = self.state()
        state["phase6"] = {"review_pass": 1}
        self.write_state(state)
        args = [a for k, v in sets.items() for a in ("--set", f"{k}={v}")]
        r = self.cmd("brief", "code-reviewer", "--mode", mode, *args)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        (self.dir / "review" / "pass-1").mkdir(parents=True, exist_ok=True)

    def test_a_missing_review_report_is_refused(self):
        self.review_brief(reviewer="R2", scope="first")
        self.returned("code-reviewer", 1, next="REVIEWED", findings="0", leads="0")
        r = self.cmd("record", "code-reviewer", "1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("R2.md does not exist", r.stdout)

    def test_a_re_vote_is_checked_in_its_votes_file(self):
        self.review_brief("re-vote", reviewer="R2", findings="C1")
        votes = self.dir / "review" / "pass-1" / "VOTES-R2.md"
        votes.write_text("| Finding | Vote | Reason |\n|---|---|---|\n| C1 | agree | x |\n")
        self.returned("code-reviewer", 1, next="VOTED", findings="1", leads="0")
        r = self.cmd("record", "code-reviewer", "1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        votes.write_text("no table\n")
        r = self.cmd("record", "code-reviewer", "1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("VOTES-R2.md", r.stdout)

    def test_a_security_review_must_follow_its_template(self):
        from test_next import SECURITY_REVIEW
        broken = SECURITY_REVIEW.format(tree="0" * 40).split("## Coverage")[0]
        (self.dir / "SECURITY_REVIEW.md").write_text(broken)
        self.returned("security-reviewer", 1, next="CLEAN", must_fix="0", pre_existing="1")
        r = self.cmd("record", "security-reviewer", "1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("SECURITY_REVIEW.md: no `## Coverage` section", r.stdout)

    def test_the_judge_s_security_verdict_checks_security_review(self):
        from test_next import SECURITY_REVIEW
        broken = SECURITY_REVIEW.format(tree="0" * 40).split("## Coverage")[0]
        (self.dir / "SECURITY_REVIEW.md").write_text(broken)
        self.returned("review-judge", 1, next="VERIFIED", must_fix_open="0", revote="0")
        r = self.cmd("record", "review-judge", "1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("SECURITY_REVIEW.md: no `## Coverage` section", r.stdout)

    def test_spec_eval_must_follow_its_template(self):
        text = SPEC_EVAL.format(tree="0" * 40, v1="met", v2="met", e2="x",
                                judgment="Justified", defective="None.")
        (self.dir / "SPEC_EVAL.md").write_text(
            "\n".join(ln for ln in text.splitlines() if "Tree:" not in ln) + "\n")
        self.returned("verifier", 1, next="ALL_MET", tree="x", corrections="0")
        r = self.cmd("record", "verifier", "1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("SPEC_EVAL.md: no `Tree:` line", r.stdout)

    def test_a_lint_report_needs_its_tree_line(self):
        (self.dir / "lint").mkdir(exist_ok=True)
        (self.dir / "lint" / "TEST.md").write_text("# TEST — pass\n")
        r = self.cmd("check-artifact", str(self.dir / "lint" / "TEST.md"))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("no `Tree:` line", r.stdout)

    def test_a_malformed_return_is_refused(self):
        self.returned("coder", 1, next="DONE", blocked="0", test_changes="none")
        r = self.cmd("record", "coder", "1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("MALFORMED", r.stdout)
        r = self.cmd("record", "coder", "2")
        self.assertIn("MISSING", r.stdout)

    def test_every_result_key_is_required(self):
        self.returned("coder", 1, next="BUILT", blocked="0")
        r = self.cmd("record", "coder", "1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("MALFORMED", r.stdout)
        self.assertIn("`test_changes`", r.stdout)

    def test_coder_blocked_none_is_zero(self):
        for blocked in ("none", "0", 0, ""):
            self.returned("coder", 1, next="BUILT", blocked=blocked, test_changes="none")
            r = self.cmd("record", "coder", "1")
            self.assertEqual(r.returncode, 0, f"{blocked!r}: {r.stdout}{r.stderr}")
        self.returned("coder", 1, next="BUILT", blocked="2", test_changes="none")
        self.assertEqual(self.cmd("record", "coder", "1").returncode, 1)

    def test_a_failed_planner_return_changes_nothing(self):
        self.returned("planner", 1, status="failed", next="OVERSIZED")
        r = self.cmd("record", "planner", "1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        state = self.state()
        self.assertIsNone(state["size"])
        self.assertNotEqual(state["phases"]["2"]["status"], "stopped")
        self.returned("planner", 2, status="blocked", next="DONE")
        r = self.cmd("record", "planner", "2")
        self.assertEqual(r.returncode, 1)
        self.assertIn("MALFORMED", r.stdout)

    def test_a_risk_word_is_read_in_any_case(self):
        self.write("PLAN.md", PLAN.replace("Risk: high", "**Risk:** High"))
        self.returned("planner", 1, next="FITS", **{**PLANNED, "risk": "High"})
        self.assertEqual(self.cmd("record", "planner", "1").returncode, 0)
        self.assertTrue(self.state()["high_risk"])

    def test_verifier_unmet_with_a_defective_check_is_correct(self):
        self.spec_eval(v1="unmet", defective='- `src/due.acceptance.test.ts` :: '
                       '"shows the due date" — asserts a format PLAN.md does not give')
        self.write("evidence/corrections.md", CORRECTION)
        self.returned("verifier", 1, next="REPAIR", tree="x", corrections="1")
        r = self.cmd("record", "verifier", "1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("eval-status says CORRECT", r.stdout)
        self.returned("verifier", 1, next="CORRECT", tree="x", corrections="1")
        r = self.cmd("record", "verifier", "1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def judge(self, nxt, must_fix_open, revote, review=CODE_REVIEW):
        self.write("CODE_REVIEW.md", review.format(tree="0" * 40))
        self.returned("review-judge", 1, next=nxt, must_fix_open=must_fix_open,
                      revote=revote)
        return self.cmd("record", "review-judge", "1")

    def test_judge_next_must_match_the_review(self):
        # The fixture has one open must-fix row and two pending re-votes.
        r = self.judge("CLEAN", "1", "2")
        self.assertEqual(r.returncode, 1)
        self.assertIn("which is REVOTE", r.stdout)
        self.assertEqual(self.judge("REVOTE", "1", "2").returncode, 0)
        no_pending = "\n".join(ln for ln in CODE_REVIEW.splitlines()
                               if not ln.startswith(("| C4", "| C6")))
        r = self.judge("REVOTE", "1", "0", no_pending)
        self.assertEqual(r.returncode, 1)
        self.assertIn("which is MUST_FIX", r.stdout)
        r = self.judge("CLEAN", "1", "0", no_pending)
        self.assertEqual(r.returncode, 1)
        r = self.judge("REVOTE", "1", "1")
        self.assertIn("revote is 1", r.stdout)

    def test_triager_check_comments_go_to_the_checks_file(self):
        triage = self.dir / "triage" / "human-1.md"
        checks = self.dir / "triage" / "human-1-checks.md"
        self.write("triage/human-1.md", "# Required changes\nNone.\n")
        self.returned("triager", 1, next="TRIAGED", blockers="0", acceptance_checks="1",
                      triage_file=str(triage), checks_file=str(checks))
        r = self.cmd("record", "triager", "1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("holds no entry", r.stdout)
        self.write("triage/human-1-checks.md", "# Required changes\n1. 12345: the sort "
                   "check compares titles, not dates\n")
        r = self.cmd("record", "triager", "1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.returned("triager", 1, next="TRIAGED", blockers="1", acceptance_checks="1",
                      triage_file=str(triage), checks_file=str(checks))
        self.assertEqual(self.cmd("record", "triager", "1").returncode, 1)

    def checks(self, *paths):
        for rel in paths:
            path = self.worktree / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"test in {rel}\n")

    def test_the_tester_leaves_its_checks_in_the_worktree(self):
        self.job("acceptance-tester", "write", scope="ALL CONDITIONS")
        self.checks("src/due.acceptance.test.ts")
        self.returned("acceptance-tester", 1, next="WRITTEN", checks="4", ambiguous="none")
        r = self.cmd("record", "acceptance-tester", "1")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("src/sort.acceptance.test.ts is in MANIFEST.md but not in the worktree",
                      r.stdout)
        self.assertFalse((self.dir / "acceptance" / "files").exists())
        self.checks("src/sort.acceptance.test.ts")
        r = self.cmd("record", "acceptance-tester", "1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_the_tester_only_adds_to_a_file_the_repo_had(self):
        shared = self.worktree / "src" / "due.acceptance.test.ts"
        shared.parent.mkdir(parents=True, exist_ok=True)
        shared.write_text("the repo's own test\n")
        self.sh("git", "add", "src/due.acceptance.test.ts", cwd=self.worktree)
        self.sh("git", "commit", "-q", "-m", "the repo's test", cwd=self.worktree)
        n = self.job("acceptance-tester", "write", scope="ALL CONDITIONS")
        self.checks("src/sort.acceptance.test.ts")
        shared.write_text("the repo's own test, rewritten\nthe new check\n")
        self.returned("acceptance-tester", n, next="WRITTEN", checks="4", ambiguous="none")
        r = self.cmd("record", "acceptance-tester", str(n))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("src/due.acceptance.test.ts: you changed or removed line(s) 1",
                      r.stdout)
        shared.write_text("the repo's own test\nthe new check\n")
        r = self.cmd("record", "acceptance-tester", str(n))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_the_tester_changes_only_its_check_files(self):
        for mode, nxt in (("write", "WRITTEN"), ("repair", "REPAIRED")):
            with self.subTest(mode=mode):
                extra = {"report": "x"} if mode == "repair" else {}
                n = self.job("acceptance-tester", mode, scope="ALL CONDITIONS", **extra)
                self.checks("src/due.acceptance.test.ts", "src/sort.acceptance.test.ts")
                (self.worktree / "src" / "fix.ts").write_text("the tester's fix to the code\n")
                self.returned("acceptance-tester", n, next=nxt, checks="1",
                              ambiguous="none")
                r = self.cmd("record", "acceptance-tester", str(n))
                self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
                self.assertIn("you changed src/fix.ts, which MANIFEST.md names as no "
                              "check file", r.stdout)
                (self.worktree / "src" / "fix.ts").unlink()
                r = self.cmd("record", "acceptance-tester", str(n))
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def tests_commit(self):
        self.checks("src/due.acceptance.test.ts", "src/sort.acceptance.test.ts")
        r = self.cmd("commit-tests")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r

    def test_commit_tests_commits_the_checks_alone_once(self):
        (self.worktree / "app.ts").write_text("the coder's work, not yet\n")
        r = self.tests_commit()
        self.assertTrue(r.stdout.startswith("COMMITTED: "), r.stdout)
        sha = r.stdout.split()[1]
        self.assertEqual(self.state()["tests_commits"][0]["sha"], sha)
        self.assertEqual(self.state()["tests_commits"][0]["paths"],
                         ["src/due.acceptance.test.ts", "src/sort.acceptance.test.ts"])
        shown = self.sh("git", "show", "--name-only", "--format=%s", "HEAD",
                        cwd=self.worktree).split()
        self.assertEqual(" ".join(shown[:5]), "test: acceptance checks for Add")
        self.assertEqual(sorted(shown[-2:]),
                         ["src/due.acceptance.test.ts", "src/sort.acceptance.test.ts"])
        self.assertIn("app.ts", self.sh("git", "status", "--porcelain",
                                        cwd=self.worktree))  # left uncommitted
        r = self.cmd("commit-tests")  # nothing changed since
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(r.stdout.startswith("UNCHANGED"), r.stdout)
        self.assertEqual(len(self.state()["tests_commits"]), 1)

    def test_commit_tests_after_a_repair_appends_a_commit(self):
        self.tests_commit()
        (self.worktree / "src" / "due.acceptance.test.ts").write_text("test, repaired\n")
        r = self.cmd("commit-tests")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        commits = self.state()["tests_commits"]
        self.assertEqual(len(commits), 2)
        self.assertEqual(commits[1]["paths"], ["src/due.acceptance.test.ts"])
        self.assertEqual(self.sh("git", "rev-parse", "HEAD", cwd=self.worktree).strip(),
                         commits[1]["sha"])

    def test_a_tests_commit_state_json_missed_is_adopted(self):
        self.tests_commit()
        sha = self.state()["tests_commits"][0]["sha"]
        state = self.state()  # as if the run stopped between the commit and the save
        del state["tests_commits"]
        self.write_state(state)
        r = self.cmd("commit-tests")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(r.stdout.startswith("UNCHANGED"), r.stdout)
        self.assertEqual([c["sha"] for c in self.state()["tests_commits"]], [sha])
        # A commit of the same subject that touches anything else is not adopted.
        state = self.state()
        del state["tests_commits"]
        self.write_state(state)
        (self.worktree / "app.ts").write_text("x\n")
        self.sh("git", "add", "app.ts", cwd=self.worktree)
        self.sh("git", "commit", "-q", "-m", "test: acceptance checks, and more",
                cwd=self.worktree)
        self.cmd("commit-tests")
        self.assertEqual([c["sha"] for c in self.state()["tests_commits"]], [sha])

    def test_a_hook_that_rejects_the_tests_commit_leaves_nothing_staged(self):
        hooks = self.tmp / "hooks"
        hooks.mkdir()
        (hooks / "pre-commit").write_text("#!/bin/sh\necho 'lint says no' >&2\nexit 1\n")
        (hooks / "pre-commit").chmod(0o755)
        self.sh("git", "config", "core.hooksPath", str(hooks), cwd=self.worktree)
        self.checks("src/due.acceptance.test.ts", "src/sort.acceptance.test.ts")
        r = self.cmd("commit-tests")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("lint says no", r.stdout + r.stderr)
        self.assertIn("COMMIT-FAILED", r.stdout + r.stderr)
        self.assertEqual(self.sh("git", "diff", "--cached", "--name-only",
                                 cwd=self.worktree), "")
        self.assertNotIn("tests_commits", self.state())

    def test_commit_tests_commits_a_dropped_check_file(self):
        self.tests_commit()
        (self.worktree / "src" / "sort.acceptance.test.ts").unlink()
        manifest = self.dir / "acceptance" / "MANIFEST.md"
        manifest.write_text("\n".join(ln for ln in manifest.read_text().splitlines()
                                      if "sort.acceptance" not in ln) + "\n")
        r = self.cmd("commit-tests")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.state()["tests_commits"][-1]["paths"],
                         ["src/sort.acceptance.test.ts"])
        self.assertNotIn("sort.acceptance", self.sh("git", "ls-files", cwd=self.worktree))

    def test_the_first_commit_tests_refuses_a_file_with_no_change(self):
        self.checks("src/due.acceptance.test.ts", "src/sort.acceptance.test.ts")
        self.sh("git", "add", "src/sort.acceptance.test.ts", cwd=self.worktree)
        self.sh("git", "commit", "-q", "-m", "someone committed it already",
                cwd=self.worktree)
        r = self.cmd("commit-tests")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("no change from HEAD in src/sort.acceptance.test.ts",
                      r.stdout + r.stderr)
        self.assertNotIn("tests_commits", self.state())
        (self.worktree / "src" / "sort.acceptance.test.ts").unlink()
        r = self.cmd("commit-tests")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("not in the worktree: src/sort.acceptance.test.ts", r.stdout + r.stderr)

    def test_commit_tests_path_must_be_a_check_file(self):
        self.tests_commit()
        r = self.cmd("commit-tests", "--path", "app.ts")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("MANIFEST.md names no check in app.ts", r.stdout + r.stderr)

    def test_a_coder_that_breaks_a_committed_check_is_refused_once_it_was_whole(self):
        self.tests_commit()
        n = self.job("coder", "build")
        check = self.worktree / "src" / "due.acceptance.test.ts"
        check.write_text("test in src/due.acceptance.test.ts\nthe coder's own test\n")
        self.returned("coder", n, next="BUILT", blocked="0", test_changes="none")
        self.assertEqual(self.cmd("record", "coder", str(n)).returncode, 0)
        n = self.job("coder", "correction", corrections_file="the gate's reports")
        check.write_text("weakened\n")
        self.returned("coder", n, next="BUILT", blocked="0", test_changes="none")
        r = self.cmd("record", "coder", str(n))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("committed acceptance checks in src/due.acceptance.test.ts at line(s) 1",
                      r.stdout)
        # Broken before the brief: not this worker's doing.
        n = self.job("coder", "build")
        self.returned("coder", n, next="BUILT", blocked="0", test_changes="none")
        self.assertEqual(self.cmd("record", "coder", str(n)).returncode, 0)

    def test_a_new_break_in_a_file_already_broken_at_the_brief_is_refused(self):
        self.checks("src/due.acceptance.test.ts", "src/sort.acceptance.test.ts")
        (self.worktree / "src" / "due.acceptance.test.ts").write_text("one\ntwo\nthree\n")
        self.assertEqual(self.cmd("commit-tests").returncode, 0)
        check = self.worktree / "src" / "due.acceptance.test.ts"
        check.write_text("ONE\ntwo\nthree\n")  # broken before the brief
        n = self.job("coder", "build")
        check.write_text("ONE\ntwo\nTHREE\n")  # and a new break, later in the file
        self.returned("coder", n, next="BUILT", blocked="0", test_changes="none")
        r = self.cmd("record", "coder", str(n))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("src/due.acceptance.test.ts at line(s) 3", r.stdout)
        self.assertNotIn("line(s) 1", r.stdout)

    def test_each_documented_result_block_is_accepted(self):
        agents = Path(__file__).resolve().parents[1] / "agents"
        for agent in sorted(agents.glob("*.md")):
            block = re.search(r"```auto-dev-result\n(.*?)```", agent.read_text(),
                              re.DOTALL).group(1)
            keys = dict(line.split(": ", 1) for line in block.strip().splitlines())
            for token in keys["next"].split(" | "):
                data = {k: "none" for k in keys}
                data.update(worker=keys["worker"], status="ok", next=token)
                path = self.write(f"returns/{keys['worker']}-1.json", json.dumps(data))
                r = self.cmd("check-artifact", path)
                self.assertEqual(r.returncode, 0, f"{agent.name} {token}: {r.stdout}")
            extra = [k for k in keys if k not in ("worker", "status", "next")]
            if extra:
                del data[extra[0]]
                path.write_text(json.dumps(data))
                self.assertEqual(self.cmd("check-artifact", path).returncode, 1, agent.name)

    def test_lookup_answer_must_be_written(self):
        self.returned("lookup", 1, next="ANSWERED", answer_file="")
        r = self.cmd("record", "lookup", "1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("holds no answer", r.stdout)
        self.write("lookups/1.md", "`dueDate` is set in src/todo.ts:12\n")
        self.assertEqual(self.cmd("record", "lookup", "1").returncode, 0)

    def test_a_lookup_that_declines_writes_only_the_out_of_scope_line(self):
        # The orchestrator acts on a lookup's answer unchecked, so a verdict
        # must not slip through under either token.
        cases = [
            ("ANSWERED", "OUT_OF_SCOPE: asks whether the code is correct\n",
             "starts with OUT_OF_SCOPE"),
            ("OUT_OF_SCOPE", None, "holds no `OUT_OF_SCOPE: <why>` line"),
            ("OUT_OF_SCOPE", "No: `refund()` misses a refund at src/refunds.ts:14\n",
             "holds no `OUT_OF_SCOPE: <why>` line"),
            ("OUT_OF_SCOPE", "OUT_OF_SCOPE: a verdict\nBut it is wrong at src/refunds.ts:14\n",
             "holds more than the `OUT_OF_SCOPE:` line"),
            ("OUT_OF_SCOPE", ("OUT_OF_SCOPE: a verdict, but `refund()` misses it at "
                             "src/refunds.ts:14\n"), "cites a `file:line`"),
        ]
        for n, (token, answer, issue) in enumerate(cases, start=1):
            self.returned("lookup", n, next=token, answer_file="")
            if answer is not None:
                self.write(f"lookups/{n}.md", answer)
            r = self.cmd("record", "lookup", str(n))
            self.assertEqual(r.returncode, 1, (token, answer, r.stdout))
            self.assertIn(issue, r.stdout, (token, answer))
        # A decline as models write it, and a real answer naming an
        # OUT_OF_SCOPE_… symbol, both record.
        recorded = [
            ("OUT_OF_SCOPE", ("OUT_OF_SCOPE: asks for a verdict; ask instead: "
                             "what does `refundedSoFar` return?\n")),
            ("OUT_OF_SCOPE", ("```\n**OUT_OF_SCOPE**: asks for a verdict\n\n"
                             "Ask instead: what does `refundedSoFar` return?\n```\n")),
            ("OUT_OF_SCOPE", "> OUT_OF_SCOPE: asks whether `src/refunds.ts` is safe\n"),
            ("ANSWERED", "`OUT_OF_SCOPE_ERROR` is defined at src/errors.ts:3\n"),
        ]
        for n, (token, answer) in enumerate(recorded, start=len(cases) + 1):
            self.returned("lookup", n, next=token, answer_file="")
            self.write(f"lookups/{n}.md", answer)
            r = self.cmd("record", "lookup", str(n))
            self.assertEqual(r.returncode, 0, (answer, r.stdout))


class TreeGuardTest(WorkCase):
    """A worker that never changes the repo (the planner, the plan critic, the
    review judge, the triager) is held to the tree it was
    briefed on: `record` refuses a change outside .auto-dev/ and puts it back,
    but only a change the worker could have made."""

    def git(self, *args):
        return self.sh("git", "-C", str(self.worktree), *args)

    def reviewer(self):
        return self.job("plan-critic", "review")

    def answered(self, n):
        self.returned("plan-critic", n, status="blocked")

    def record(self, n):
        return self.cmd("record", "plan-critic", str(n))

    def test_record_refuses_a_change_and_puts_the_files_back(self):
        wt = self.worktree
        (wt / "app.ts").write_text("export const one = 2;\n")  # dirty before the brief
        (wt / "notes.txt").write_text("the user's\n")           # untracked before it
        (wt / '"quoted').write_text("a name git would unquote\n")
        (wt / "tool.sh").write_text("#!/bin/sh\n")
        self.git("add", "tool.sh")
        self.git("update-index", "--chmod=+x", "tool.sh")
        self.git("commit", "-q", "-m", "tool")
        os.chmod(wt / "tool.sh", 0o755)
        env = (wt / ".env").read_text()
        n = self.reviewer()
        # The worker edits a dirty file, deletes an untracked one, changes a
        # clean one's mode and text, adds a file, un-ignores .env, and writes
        # its own file where it should.
        (wt / "app.ts").write_text("export const one = 3;\n")
        (wt / "notes.txt").unlink()
        (wt / "tool.sh").write_text("#!/bin/sh\necho hi\n")
        os.chmod(wt / "tool.sh", 0o644)
        (wt / "new.ts").write_text("export {};\n")
        (wt / ".gitignore").write_text("setup-ran.txt\n")
        self.write(f"plan-review/{n}.md", "none\n")
        self.answered(n)
        r = self.record(n)
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn(f"plan-critic-{n} changed 6 repo file(s)", r.stdout)  # with .env
        for path in (".gitignore", "app.ts", "new.ts", "notes.txt", "tool.sh"):
            self.assertIn(path, r.stdout)
        self.assertEqual((wt / "app.ts").read_text(), "export const one = 2;\n")
        self.assertEqual((wt / "notes.txt").read_text(), "the user's\n")
        self.assertEqual((wt / "tool.sh").read_text(), "#!/bin/sh\n")
        self.assertTrue(os.access(wt / "tool.sh", os.X_OK))
        self.assertFalse((wt / "new.ts").exists())
        self.assertEqual((wt / ".env").read_text(), env)  # ignored again, so kept
        backup = self.dir / "tree" / f"plan-critic-{n}"
        self.assertEqual((backup / "app.ts").read_text(), "export const one = 3;\n")
        self.assertEqual((backup / "new.ts").read_text(), "export {};\n")
        self.assertEqual(self.git("status", "--porcelain", "--", "app.ts", "tool.sh"),
                         " M app.ts\n")
        # Put back, the same return records when recorded again.
        self.assertEqual(self.record(n).returncode, 0)

    def test_each_worker_that_never_changes_the_repo_is_checked(self):
        guarded = [("planner", "write", {}), ("plan-critic", "review", {}),
                   ("review-judge", "security-verify", {}),
                   ("triager", "ci", {"failing": "test"})]
        for worker, as_mode, sets in guarded:
            n = self.job(worker, as_mode, **sets)
            (self.worktree / "app.ts").write_text(f"// {worker}\n")
            self.returned(worker, n, status="blocked")
            r = self.cmd("record", worker, str(n))
            self.assertEqual(r.returncode, 1, (worker, r.stdout))
            self.assertIn(f"{worker}-{n} changed 1 repo file(s)", r.stdout)
            self.assertEqual((self.worktree / "app.ts").read_text(),
                             "export const one = 1;\n", worker)
        # A worker that writes code, and a lookup (sent while the user may be
        # editing), are not.
        for worker, as_mode, sets in [("coder", "build", {}),
                                      ("lookup", None, {"question": "Where is `one`?"})]:
            n = self.job(worker, as_mode, **sets)
            (self.worktree / "app.ts").write_text(f"// {worker}\n")
            self.returned(worker, n, status="blocked")
            self.assertNotIn("repo file(s)", self.cmd("record", worker, str(n)).stdout)

    def test_only_a_change_the_worker_could_have_made_is_refused(self):
        wt = self.worktree
        # Recorded, then the coder works: recording it again undoes nothing.
        n = self.reviewer()
        self.answered(n)
        self.assertEqual(self.record(n).returncode, 0)
        (wt / "app.ts").write_text("// the coder's\n")
        (wt / "feature.ts").write_text("// the coder's\n")
        self.assertEqual(self.record(n).returncode, 0)
        self.assertEqual((wt / "feature.ts").read_text(), "// the coder's\n")
        # A coder briefed while the reviewer is out: the reviewer is not blamed.
        n = self.reviewer()
        self.job("coder", "build")
        (wt / "feature.ts").write_text("// the coder's, later\n")
        self.answered(n)
        self.assertEqual(self.record(n).returncode, 0)
        self.assertEqual((wt / "feature.ts").read_text(), "// the coder's, later\n")
        # No result file yet: it may still be running, so nothing is put back.
        n = self.reviewer()
        (wt / "feature.ts").write_text("// mid-run\n")
        self.assertNotIn("repo file(s)", self.record(n).stdout)
        self.assertEqual((wt / "feature.ts").read_text(), "// mid-run\n")

    def test_a_commit_since_the_brief_is_left_to_phase_6(self):
        n = self.reviewer()
        (self.worktree / "app.ts").write_text("// committed\n")
        self.git("commit", "-q", "-am", "an outside commit")
        self.answered(n)
        self.assertEqual(self.record(n).returncode, 0)
        self.assertEqual((self.worktree / "app.ts").read_text(), "// committed\n")

    def test_a_file_written_after_the_result_is_not_the_workers(self):
        wt = self.worktree
        n = self.reviewer()
        (wt / "mine.ts").write_text("// the reviewer's\n")
        self.answered(n)
        result = self.dir / "returns" / f"plan-critic-{n}.json"
        os.utime(wt / "mine.ts", (result.stat().st_mtime - 5,) * 2)
        (wt / "app.ts").write_text("// the user's, after the reviewer returned\n")
        os.utime(wt / "app.ts", (result.stat().st_mtime + 5,) * 2)
        r = self.record(n)
        self.assertEqual(r.returncode, 1)
        self.assertIn("changed 1 repo file(s)", r.stdout)
        self.assertIn("mine.ts", r.stdout)
        self.assertFalse((wt / "mine.ts").exists())
        self.assertEqual((wt / "app.ts").read_text(),
                         "// the user's, after the reviewer returned\n")

    def test_put_back_keeps_a_files_mode_and_undoes_a_folder_or_file_swap(self):
        wt = self.worktree
        (wt / "secret.txt").write_text("key\n")
        os.chmod(wt / "secret.txt", 0o600)
        (wt / "d").mkdir()
        (wt / "d" / "x.txt").write_text("the user's\n")
        n = self.reviewer()
        (wt / "secret.txt").write_text("changed\n")
        os.chmod(wt / "secret.txt", 0o644)
        (wt / "d" / "x.txt").unlink()
        (wt / "d").rmdir()
        (wt / "d").write_text("a file now\n")  # a folder turned into a file
        (wt / "app.ts").unlink()
        (wt / "app.ts").mkdir()
        (wt / "app.ts" / "y.ts").write_text("// a file turned into a folder\n")
        self.answered(n)
        r = self.record(n)
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertNotIn("could not put back", r.stdout)
        self.assertEqual((wt / "secret.txt").read_text(), "key\n")
        self.assertEqual((wt / "secret.txt").stat().st_mode & 0o777, 0o600)
        self.assertEqual((wt / "d" / "x.txt").read_text(), "the user's\n")
        self.assertEqual((wt / "app.ts").read_text(), "export const one = 1;\n")

    def test_a_retry_or_a_re_sent_brief_takes_a_fresh_snapshot(self):
        n = self.reviewer()
        (self.worktree / "app.ts").write_text("// the reviewer's\n")
        self.answered(n)
        self.assertEqual(self.record(n).returncode, 1)
        r = self.cmd("brief", "plan-critic", "--mode", "review", "--retry", str(n))
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(self.state()["briefs"][-1]["tree"]["files"], {})
        # The user edits while no worker is out; `next` sends the brief again.
        (self.worktree / "app.ts").write_text("// the user's\n")
        state = self.state()
        sys.path.insert(0, str(SCRIPTS))
        from lib import cmd_work
        cmd_work.fresh_tree(state, state["briefs"][-1])
        self.assertIn("app.ts", state["briefs"][-1]["tree"]["files"])

    def test_no_check_while_setup_still_runs(self):
        state = self.state()
        state["init"]["setup_pid"] = 4242
        self.write_state(state)
        (self.dir / "setup.json").unlink(missing_ok=True)
        n = self.reviewer()
        (self.worktree / "app.ts").write_text("// written by setup\n")
        self.answered(n)
        self.assertEqual(self.record(n).returncode, 0)


class TicketTextTest(InitCase):
    def test_the_planner_gets_the_ticket_text_verbatim(self):
        ticket = self.tmp / "ticket.txt"
        ticket.write_text("TODO-7 Due dates\nUsers can set a due date.\n"
                          "AC: overdue todos show in red.\n")
        r = self.init("--ticket", "TODO-7", "--ticket-text-file", ticket)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        r = self.autodev("brief", "planner", "--mode", "write", "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        text = (self.dir / "briefs" / "planner-1.md").read_text()
        self.assertIn("task: TODO-7 Due dates\n  Users can set a due date.\n"
                      "  AC: overdue todos show in red.\n", text)

    def test_without_ticket_text_the_planner_gets_the_restated_ask(self):
        r = self.init("--ticket", "TODO-7", "--ask", "Let users set a due date on a todo",
                      task="TODO-7")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.autodev("brief", "planner", "--mode", "write", "--dir", self.dir)
        text = (self.dir / "briefs" / "planner-1.md").read_text()
        self.assertIn("task: Let users set a due date on a todo\n", text)

    def test_an_empty_or_missing_ticket_file_stops_before_the_worktree(self):
        empty = self.tmp / "empty.txt"
        empty.write_text("\n")
        for path, why in ((empty, "is empty"), (self.tmp / "missing.txt", "cannot read")):
            r = self.init("--ticket-text-file", path)
            self.assertEqual(r.returncode, 2)
            self.assertIn(why, r.stderr)
            self.assertFalse(self.worktree.exists())


class SpecProblemAndDeviationRecordTest(WorkCase):
    """record holds a worker's spec_problems and the coder's deviations to the
    files they count, and a worker that judges against PLAN.md to the spec as
    it was at its brief."""

    def triage(self, problems=None, **data):
        self.assertEqual(self.cmd("brief", "triager", "--mode", "human").returncode, 0)
        if problems is not None:
            self.write("spec-problems/triager-1.md", problems)
        self.returned("triager", 1, next="TRIAGED", blockers="0", acceptance_checks="0",
                      triage_file="none", checks_file="none", **data)
        return self.cmd("record", "triager", "1")

    def test_a_spec_problem_is_recorded_with_its_file(self):
        r = self.triage("- condition 2: comment 77: it asks for newest first\n"
                        "- missing: comment 78: a todo with no date sorts last\n",
                        spec_problems="2")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_a_spec_problem_count_must_match_its_file(self):
        r = self.triage(None, spec_problems="1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("spec-problems/triager-1.md does not exist", r.stdout)
        r = self.triage("- condition 2: it asks for newest first\n", spec_problems="2")
        self.assertEqual(r.returncode, 1)
        self.assertIn("spec_problems is 2 but triager-1.md lists 1", r.stdout)

    def test_a_spec_problem_on_a_condition_the_spec_lacks_is_refused(self):
        r = self.triage("- condition 9: it asks for something else\n", spec_problems="1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("condition 9 is not in PLAN.md", r.stdout)
        r = self.triage("- condition 2:\n", spec_problems="1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("2: say what is wrong", r.stdout)

    def test_a_ci_triager_never_reports_a_spec_problem(self):
        self.assertEqual(self.cmd("brief", "triager", "--mode", "ci",
                                  "--set", "failing=test").returncode, 0)
        self.write("triage/ci-1.md", "# Required changes\n1. fix the sort in src/sort.ts\n")
        self.write("spec-problems/triager-1.md", "- condition 2: the log says so\n")
        self.returned("triager", 1, next="CODE", blockers="0", acceptance_checks="0",
                      triage_file=str(self.dir / "triage" / "ci-1.md"), checks_file="none",
                      spec_problems="1")
        r = self.cmd("record", "triager", "1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("never reports a spec problem", r.stdout)

    def test_a_worker_that_edits_spec_md_is_refused_whatever_it_returns(self):
        self.assertEqual(self.cmd("brief", "triager", "--mode", "human").returncode, 0)
        (self.dir / "PLAN.md").write_text(PLAN.replace("earliest first", "latest first"))
        self.returned("triager", 1, status="failed")
        r = self.cmd("record", "triager", "1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("PLAN.md changed since your brief", r.stdout)

    def coder(self, deviations, text=None):
        self.assertEqual(self.cmd("brief", "coder", "--mode", "build").returncode, 0)
        if text is not None:
            self.write("deviations/coder-1.md", text)
        self.returned("coder", 1, next="BUILT", blocked="0", test_changes="none",
                      deviations=deviations)
        return self.cmd("record", "coder", "1")

    def test_the_coder_s_deviations_must_match_its_file(self):
        r = self.coder("1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("deviations/coder-1.md does not exist", r.stdout)
        r = self.coder("0", "- step 1: the field goes on the Todo type instead\n")
        self.assertEqual(r.returncode, 1)
        self.assertIn("deviations is 0 but", r.stdout)
        r = self.coder("1", "- step 1: the field goes on the Todo type instead\n")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_record_refuses_a_plan_with_a_wrong_heading(self):
        self.assertEqual(self.cmd("brief", "planner", "--mode", "write").returncode, 0)
        self.write("PLAN.md", PLAN.replace("## Build sequence", "## Steps"))
        self.returned("planner", 1, next="FITS", **PLANNED)
        r = self.cmd("record", "planner", "1")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("PLAN.md: headings must be", r.stdout)

    def test_check_artifact_reads_both_files(self):
        good = self.write("spec-problems/verifier-1.md", "- condition 1: x is wrong\n")
        self.assertEqual(self.cmd("check-artifact", good).returncode, 0)
        bad = self.write("spec-problems/verifier-2.md", "the spec is wrong\n")
        r = self.cmd("check-artifact", bad)
        self.assertEqual(r.returncode, 1)
        self.assertIn("no `- condition <id>: <why>`", r.stdout + r.stderr)
        empty = self.write("deviations/coder-2.md", "nothing\n")
        self.assertEqual(self.cmd("check-artifact", empty).returncode, 1)


class CheckArtifactTest(WorkCase):
    def check(self, rel, text):
        path = self.dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return self.cmd("check-artifact", path)

    def test_plan_conditions(self):
        self.assertEqual(self.cmd("check-artifact", self.dir / "PLAN.md").returncode, 0)
        no_edge = PLAN.replace("   - Edge: an invalid date is rejected → 400\n", "")
        r = self.check("PLAN.md", no_edge)
        self.assertEqual(r.returncode, 1)
        self.assertIn("condition 1 has no `Edge:` line", r.stdout)

    def test_plan_headings(self):
        self.assertEqual(self.check("PLAN.md", PLAN).returncode, 0)
        r = self.check("PLAN.md", PLAN.replace("## Design", "## How"))
        self.assertEqual(r.returncode, 1)
        self.assertIn("headings must be, in order", r.stdout)

    def test_an_oversized_plan_may_stop_at_its_size_check(self):
        oversized = (PLAN.split("## Size check")[0] + "## Size check\n"
                     "OVERSIZED: three deliverables.\n")
        oversized = oversized.replace("Review effort: high — a small change\n", "")
        self.assertEqual(self.check("PLAN.md", oversized).returncode, 0)
        fits = oversized.replace("OVERSIZED: three", "FITS: three")
        r = self.check("PLAN.md", fits)
        self.assertEqual(r.returncode, 1)
        self.assertIn("## Files", r.stdout)
        self.assertIn("`Review effort:` must be", r.stdout)

    def test_a_plan_s_risk_is_standard_or_high(self):
        for line in ("Risk: standard — a local change", "**Risk:** `high` — auth"):
            r = self.check("PLAN.md", PLAN.replace("Risk: high — only the owner may set a "
                                                   "due date", line))
            self.assertEqual(r.returncode, 0, line + "\n" + r.stdout)
        for line, found in (("Risk: medium — some", "medium"),
                            ("Risk: <standard | high> — <why>", "<standard")):
            r = self.check("PLAN.md", PLAN.replace("Risk: high — only the owner may set a "
                                                   "due date", line))
            self.assertEqual(r.returncode, 1, line)
            self.assertIn(f"`Risk:` must be standard or high (found: {found})", r.stdout)
        r = self.check("PLAN.md", PLAN.replace("Risk: high — only the owner may set a "
                                               "due date\n", ""))
        self.assertIn("`Risk:` must be standard or high (found: nothing)", r.stdout)

    def test_a_plan_review_effort_is_high_or_xhigh(self):
        old = "Review effort: high — a small change"
        for line in ("Review effort: high — one local function",
                     "Review effort: xhigh — a state machine spans three modules",
                     "**Review effort:** `xhigh` — parsing",
                     "- Review effort: high—one rename"):
            r = self.check("PLAN.md", PLAN.replace(old, line))
            self.assertEqual(r.returncode, 0, line + "\n" + r.stdout)
        for line, found in (("Review effort: max — be thorough", "max"),
                            ("- Review effort: max", "max"),
                            ("Review effort: <high | xhigh> — <reason>", "<high"),
                            ("Review effort:", "nothing"),
                            ("", "nothing")):
            r = self.check("PLAN.md", PLAN.replace(old, line))
            self.assertEqual(r.returncode, 1, line)
            self.assertIn(f"`Review effort:` must be high or xhigh (found: {found})",
                          r.stdout)

    def test_a_plan_review(self):
        good = plan_review("REVISE", "high", [("`src/due.ts:3`", "add a step")])
        self.assertEqual(self.check("plan-review/1.md", good).returncode, 0)
        self.assertEqual(self.check("plan-review/2.md", plan_review()).returncode, 0)
        for text, why in (
                (good.replace("- Evidence: `src/due.ts:3`\n", ""),
                 "blocker B1 has no `Evidence:` line"),
                (good.replace("- Change: add a step\n", ""),
                 "blocker B1 has no `Change:` line"),
                (good.replace("Verdict: REVISE", "Verdict: APPROVE"),
                 "verdict APPROVE but 1 blocker(s) listed"),
                (plan_review().replace("Verdict: APPROVE", "Verdict: REVISE"),
                 "verdict REVISE but no `### B<n>.` blocker listed"),
                (plan_review("REVISE", "high", [("`a:1`", "x")] * 8),
                 "8 blockers: at most 7"),
                (good.replace("Verdict: REVISE", "Verdict: maybe"),
                 "`Verdict:` must be APPROVE or REVISE (found: MAYBE)"),
                (good.replace("Risk: high", "Risk: low"),
                 "`Risk:` must be standard or high (found: low)"),
                (good.replace("## Notes\nnone\n", ""), "no `## Notes` section")):
            r = self.check("plan-review/3.md", text)
            self.assertEqual(r.returncode, 1, why)
            self.assertIn(why, r.stdout)

    def test_corrections(self):
        self.assertEqual(self.check("evidence/corrections.md", "# Required changes\nNone.\n")
                         .returncode, 0)
        self.assertEqual(self.check("triage/ci-1.md", "Fix the build\n").returncode, 1)

    def test_reports(self):
        review = (FIXTURES / "CODE_REVIEW.md").read_text().format(tree="0" * 40)
        self.assertEqual(self.check("CODE_REVIEW.md", review).returncode, 0)
        self.assertEqual(self.check("CODE_REVIEW.md", review.replace("## Noise", "## Junk"))
                         .returncode, 1)
        self.assertEqual(self.check("lint/TEST.md", "# TEST — pass\n\n- **Tree:** abc\n")
                         .returncode, 0)


class AmendManifestTest(WorkCase):
    """cmd_amend.amend_manifest: rows split as the artifact parser splits them."""

    HEAD = ("| # | Condition | Check (path :: test name) | Covers | Level | Kind | Base run |\n"
            "|---|---|---|---|---|---|---|\n")

    def setUp(self):
        super().setUp()
        sys.path.insert(0, str(SCRIPTS))
        from lib import cmd_amend
        self.amend = cmd_amend.amend_manifest

    def test_pipes_in_code_spans_and_escaped_ones_do_not_shift_cells(self):
        text = ("# x\n\n" + self.HEAD +
                '| 1 | a `x | y` cond | `src/a.test.ts` :: "keeps" | E | unit | f | p |\n'
                '  | 1 | c | `src/a.test.ts` :: "a \\| b" | E | unit | f | p |\n'
                '| 1 | c | `src/a.test.ts` :: `quoted` | E | unit | f | p |\n'
                "\n## Not automatable\nNone.\n")
        out, missing = self.amend(text, [("src/a.test.ts", "a | b"),
                                         ("src/a.test.ts", "quoted")], [], [])
        self.assertEqual(missing, [])
        self.assertIn('"keeps"', out)
        self.assertNotIn("a \\| b", out)
        self.assertNotIn("quoted", out)
        out, missing = self.amend(text, [("src/a.test.ts", "x")], [], [])
        self.assertEqual(missing, [("src/a.test.ts", "x")])

    def test_a_row_with_extra_cells_is_refused_and_none_goes(self):
        sys.path.insert(0, str(SCRIPTS))
        from lib.output import Fail
        text = ("# x\n\n" + self.HEAD +
                '| 1 | c | `src/a.test.ts` :: "keeps" | E | unit | f | p |\n'
                "\n## Not automatable\n| # | Condition | Why | Proxy |\n|---|---|---|---|\n"
                "None.\n\n## Assumptions\n- none\n")
        with self.assertRaises(Fail):
            self.amend(text, [], ['| 1 | c | `p` :: "n" | E | unit | f | p | extra |'], [])
        out, _ = self.amend(text, [], [], ["| 2 | d | why | none |"])
        self.assertIn("| 2 | d | why | none |\n\n## Assumptions", out)
        self.assertNotIn("None.", out)


class AmendedNamesTest(WorkCase):
    """How `record` tells a dropped test is still in its file, and a row's id."""

    def setUp(self):
        super().setUp()
        sys.path.insert(0, str(SCRIPTS))
        from lib import cmd_work
        self.work = cmd_work

    def test_a_name_counts_quoted_or_as_a_whole_word(self):
        named = self.work.names_test
        self.assertTrue(named('it("adds two numbers", () => {})', "adds two numbers"))
        self.assertFalse(named('it("adds two numbers", () => {})', "adds"))
        self.assertTrue(named("export function testAdds() {}", "testAdds"))
        self.assertFalse(named("export function testAddsMore() {}", "testAdds"))

    def test_an_edge_row_counts_for_its_condition(self):
        self.assertEqual([self.work.row_id(c) for c in ("3 (Edge)", " S1 ", "2")],
                         ["3", "S1", "2"])
