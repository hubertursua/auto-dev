"""Tests for autodev.py brief / record / check-artifact.

Run: python3 -m unittest discover -s tests -v   (from the repo root)
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_autodev import RunCase
from test_autodev import RunCase as InitCase
from test_parsers import CODE_REVIEW, FIXTURES, MANIFEST, SPEC, SPEC_EVAL

SPEC_NO_SECURITY = SPEC.split("## Security/Compliance criteria")[0]
CORRECTION = ("# Required changes\n1. Show the due date next to the title in src/list.ts\n"
              "   Where: `src/list.ts:12` — the row renderer\n")


class WorkCase(RunCase):
    def setUp(self):
        super().setUp()
        self.assertEqual(self.init().returncode, 0)
        (self.dir / "SPEC.md").write_text(SPEC)
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

    def returned(self, worker, n, status="ok", **data):
        path = self.dir / "returns" / f"{worker}-{n}.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps({"worker": worker, "status": status, **data}))

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
    def test_define_brief_fills_its_slots_from_state(self):
        r = self.cmd("brief", "define", "--mode", "write")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("agent: auto-dev:define", r.stdout)
        path = self.dir / "briefs" / "define-1.md"
        self.assertIn(f"prompt: Your brief is at {path}. Read it first.", r.stdout)
        values = self.brief_values(path)
        self.assertEqual(values["mode"], "write")
        self.assertEqual(values["worktree"], str(self.worktree))
        self.assertEqual(values["task"], "Add due dates to todos")
        self.assertEqual(values["result_file"], str(self.dir / "returns" / "define-1.json"))
        self.assertIn("CLAUDE.md", values["binding_rules"])
        self.cmd("brief", "define", "--mode", "write")
        self.assertTrue((self.dir / "briefs" / "define-2.md").exists())

    def test_coder_correction_brief_names_the_acceptance_paths(self):
        r = self.cmd("brief", "coder", "--mode", "correction", "--set",
                     f"corrections_file={self.dir}/evidence/corrections.md")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        values = self.brief_values(self.dir / "briefs" / "coder-1.md")
        self.assertEqual(values["acceptance_paths"],
                         "src/due.acceptance.test.ts, src/sort.acceptance.test.ts")

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
        self.assertEqual(values["fix_file"], "none")
        self.assertEqual(values["direction"], "use UTC")

    def test_verifier_brief_carries_the_last_survivors(self):
        (self.dir / "SPEC_EVAL.md").write_text(SPEC_EVAL.format(
            tree="0" * 40, v1="met", v2="met", e2="x", judgment="Justified",
            defective="None."))
        r = self.cmd("brief", "verifier", "--set", "mode=re-check",
                     "--set", "what_changed=the cleanup pass")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        text = (self.dir / "briefs" / "verifier-1.md").read_text()
        self.assertIn("| M2 | `src/sort.ts:4` |", text)
        self.assertIn("mutation_cap: 20", text)
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
        r = self.cmd("brief", "cleanup", "--set", "scope=phase5")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        values = self.brief_values(self.dir / "briefs" / "cleanup-1.md")
        self.assertEqual(values["cut"], cut)
        # origin/main moving on after a fetch leaves the cut where it was.
        seed = self.tmp / "seed"
        self.sh("git", "-C", str(seed), "pull", "-q", "origin", "main")
        (seed / "upstream.txt").write_text("y\n")
        self.sh("git", "-C", str(seed), "add", "upstream.txt")
        self.sh("git", "-C", str(seed), "commit", "-q", "-m", "upstream")
        self.sh("git", "-C", str(seed), "push", "-q", "origin", "main")
        self.sh("git", "-C", str(self.worktree), "fetch", "-q", "origin")
        r = self.cmd("brief", "cleanup", "--set", "scope=phase5")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        values = self.brief_values(self.dir / "briefs" / "cleanup-2.md")
        self.assertEqual(values["cut"], cut)

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
        self.returned("define", 1, next="FITS", high_risk="no", reading="none")
        self.assertEqual(self.cmd("record", "define", "1").returncode, 1)
        self.assertEqual(self.cmd("brief", "define", "--mode", "write", "--retry", "1")
                         .returncode, 0)
        text = (self.dir / "briefs" / "define-1.md").read_text()
        self.assertIn("previous_issues: - SPEC.md has Security/Compliance criteria", text)
        self.cmd("brief", "define", "--mode", "write")
        values = self.brief_values(self.dir / "briefs" / "define-2.md")
        self.assertEqual(values["previous_issues"], "none")
        self.returned("define", 1, next="FITS", high_risk="yes", reading="none")
        self.assertEqual(self.cmd("record", "define", "1").returncode, 0)
        r = self.cmd("brief", "define", "--mode", "write", "--retry", "1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("refused no return for define-1", r.stderr)

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
    def test_define_size_is_recorded_and_checked_against_the_spec(self):
        self.returned("define", 1, next="FITS", high_risk="no", reading="none")
        r = self.cmd("record", "define", "1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("Security/Compliance criteria", r.stdout)
        self.returned("define", 1, next="FITS", high_risk="yes", reading="none")
        r = self.cmd("record", "define", "1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        state = self.state()
        self.assertEqual(state["size"], "FITS")
        self.assertTrue(state["settings"]["post_plan_gate"])

    def test_oversized_stops_the_run(self):
        self.returned("define", 1, next="OVERSIZED", high_risk="yes", reading="none")
        self.assertEqual(self.cmd("record", "define", "1").returncode, 0)
        self.assertEqual(self.state()["phases"]["2"]["status"], "stopped")

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

    def test_a_plan_that_copies_the_spec_is_refused(self):
        from test_next import IMPLEMENTATION
        copied = IMPLEMENTATION.replace(
            "1. add the field",
            "1. a todo can carry a due date that the list shows next to its title")
        (self.dir / "IMPLEMENTATION.md").write_text(copied)
        self.returned("planner", 1, next="WRITTEN", entry_points_changed="no")
        r = self.cmd("record", "planner", "1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("copies SPEC.md's wording", r.stdout)
        self.assertIn("condition 1", r.stdout)
        (self.dir / "IMPLEMENTATION.md").write_text(IMPLEMENTATION)
        self.assertEqual(self.cmd("record", "planner", "1").returncode, 0)

    def test_a_plan_without_its_spec_is_not_passed(self):
        from test_next import IMPLEMENTATION
        (self.dir / "IMPLEMENTATION.md").write_text(IMPLEMENTATION)
        (self.dir / "SPEC.md").unlink()
        self.returned("planner", 1, next="WRITTEN", entry_points_changed="no")
        r = self.cmd("record", "planner", "1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("SPEC.md", r.stdout)

    def test_a_plan_fix_that_copies_the_spec_is_refused(self):
        fix = self.write("fixes/plan-reviewer-1.md", (
            "FIX B1\n<<<<<<< OLD\n1. add the field\n=======\n"
            "1. a todo can carry a due date that the list shows next to its title\n"
            ">>>>>>> NEW\n"))
        self.returned("plan-reviewer", 1, next="CLEAN", blockers="0", fix_file=str(fix))
        r = self.cmd("record", "plan-reviewer", "1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("plan-reviewer-1.md's new text copies SPEC.md's wording", r.stdout)
        self.assertIn("condition 1", r.stdout)
        fix.write_text("FIX B1\n<<<<<<< OLD\na todo can carry a due date that the list "
                       "shows next to its title\n=======\n1. add the field\n>>>>>>> NEW\n")
        self.assertEqual(self.cmd("record", "plan-reviewer", "1").returncode, 0)

    def test_corrections_that_copy_the_spec_are_refused(self):
        (self.dir / "SPEC_EVAL.md").write_text(SPEC_EVAL.format(
            tree="0" * 40, v1="unmet", v2="met", e2="x", judgment="Justified",
            defective="None."))
        (self.dir / "evidence").mkdir(exist_ok=True)
        corrections = self.dir / "evidence" / "corrections.md"
        corrections.write_text("# Required changes\n1. Make sure the list sorts todos "
                               "by due date with the earliest first\n")
        self.returned("verifier", 1, next="CORRECT", tree="x", corrections="1")
        r = self.cmd("record", "verifier", "1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("corrections.md copies SPEC.md's wording", r.stdout)

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
        self.returned("cleanup", 1, next="GREEN")
        r = self.cmd("record", "cleanup", "1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("TEST.md: no `Tree:` line", r.stdout)

    def test_a_reviewer_fix_file_needs_a_fix_block(self):
        fix = self.write("fixes/define-reviewer-1.md", "just prose\n")
        self.returned("define-reviewer", 1, next="BLOCKERS", blockers="1", fix_file=str(fix))
        r = self.cmd("record", "define-reviewer", "1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("define-reviewer-1.md: no FIX block", r.stdout)

    def test_a_revised_plan_that_copies_the_spec_is_refused(self):
        from test_next import IMPLEMENTATION
        (self.dir / "IMPLEMENTATION.md").write_text(IMPLEMENTATION.replace(
            "1. add the field",
            "1. a todo can carry a due date that the list shows next to its title"))
        self.returned("planner", 1, next="REVISED", entry_points_changed="no")
        r = self.cmd("record", "planner", "1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("copies SPEC.md's wording", r.stdout)

    def test_cleanup_green_needs_passing_reports(self):
        (self.dir / "lint").mkdir(exist_ok=True)
        (self.dir / "lint" / "TEST.md").write_text("# TEST — fail\n")
        self.returned("cleanup", 1, next="GREEN")
        self.assertEqual(self.cmd("record", "cleanup", "1").returncode, 1)
        (self.dir / "lint" / "TEST.md").write_text("# TEST — pass\n\n- **Tree:** abc\n")
        self.assertEqual(self.cmd("record", "cleanup", "1").returncode, 0)

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

    def test_a_failed_define_return_changes_nothing(self):
        self.returned("define", 1, status="failed", next="OVERSIZED")
        r = self.cmd("record", "define", "1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        state = self.state()
        self.assertIsNone(state["size"])
        self.assertNotEqual(state["phases"]["2"]["status"], "stopped")
        self.returned("define", 2, status="blocked", next="DONE")
        r = self.cmd("record", "define", "2")
        self.assertEqual(r.returncode, 1)
        self.assertIn("MALFORMED", r.stdout)

    def test_high_risk_accepts_true(self):
        self.returned("define", 1, next="FITS", high_risk=True, reading="none")
        self.assertEqual(self.cmd("record", "define", "1").returncode, 0)
        self.assertTrue(self.state()["high_risk"])

    def test_a_security_criterion_added_later_turns_the_gate_on(self):
        self.write("SPEC.md", SPEC_NO_SECURITY)
        self.returned("define", 1, next="FITS", high_risk="no", reading="none")
        self.assertEqual(self.cmd("record", "define", "1").returncode, 0)
        self.assertFalse(self.state()["settings"]["post_plan_gate"])
        self.write("SPEC.md", SPEC)
        self.returned("define", 2, next="REVISED", high_risk="yes", reading="none")
        self.assertEqual(self.cmd("record", "define", "2").returncode, 0)
        state = self.state()
        self.assertTrue(state["high_risk"])
        self.assertTrue(state["settings"]["post_plan_gate"])

    def test_a_fix_adding_a_security_criterion_turns_the_gate_on(self):
        self.write("SPEC.md", SPEC_NO_SECURITY)
        self.returned("define", 1, next="FITS", high_risk="no", reading="none")
        self.assertEqual(self.cmd("record", "define", "1").returncode, 0)
        fix = self.write("fixes/define-1.md", "FIX B1\n<<<<<<< OLD\n## Assumptions\n- none\n"
                         "=======\n## Assumptions\n- none\n\n## Security/Compliance "
                         "criteria\nS1. Only the owner can set a todo's due date\n"
                         "   - Example: Given user B, when B sets it, then 404.\n"
                         "   - Verify by: integration\n>>>>>>> NEW\n")
        r = self.cmd("apply-fix", self.dir / "SPEC.md", fix)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("high_risk: yes", r.stdout)
        self.assertTrue(self.state()["settings"]["post_plan_gate"])

    def test_verifier_unmet_with_a_defective_check_is_correct(self):
        self.spec_eval(v1="unmet", defective='- `src/due.acceptance.test.ts` :: '
                       '"shows the due date" — asserts a format SPEC.md does not give')
        self.write("evidence/corrections.md", CORRECTION)
        self.returned("verifier", 1, next="REPAIR", tree="x", corrections="1")
        r = self.cmd("record", "verifier", "1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("eval-status says CORRECT", r.stdout)
        self.returned("verifier", 1, next="CORRECT", tree="x", corrections="1")
        r = self.cmd("record", "verifier", "1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_install_conflict_needs_its_corrections(self):
        self.returned("verifier", 1, next="INSTALL_CONFLICT", tree="none", corrections="0")
        r = self.cmd("record", "verifier", "1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("INSTALL_CONFLICT", r.stdout)
        self.write("evidence/corrections.md", "# Required changes\n1. Move "
                   "`src/due.acceptance.test.ts`; an acceptance check installs there\n")
        self.returned("verifier", 1, next="INSTALL_CONFLICT", tree="none", corrections="1")
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

    def test_judge_corrections_must_not_copy_the_spec(self):
        no_pending = "\n".join(ln for ln in CODE_REVIEW.splitlines()
                               if not ln.startswith(("| C4", "| C6")))
        self.write("review/pass-1/corrections.md", "# Required changes\n1. C1: the list "
                   "sorts todos by due date with the earliest first\n")
        r = self.judge("MUST_FIX", "1", "0", no_pending)
        self.assertEqual(r.returncode, 1)
        self.assertIn("copies SPEC.md's wording", r.stdout)
        self.write("review/pass-1/corrections.md", "# Required changes\n1. C1: guard "
                   "the null due date in `src/sort.ts:4` before comparing\n")
        r = self.judge("MUST_FIX", "1", "0", no_pending)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

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

    def test_a_quoted_test_name_is_not_a_copy_of_the_spec(self):
        quoted = ("# Required changes\n1. C1: put todos with a due date before undated ones\n"
                  "   Where: `src/sort.ts:4` — the comparator\n"
                  "   Now: `src/sort.acceptance.test.ts` :: \"the list sorts todos by due "
                  "date with the earliest first\" fails\n")
        path = self.write("evidence/corrections.md", quoted)
        r = self.cmd("spec-overlap", path)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.cmd("check-artifact", path).returncode, 0)
        path.write_text(quoted.replace('"the list', "the list").replace('first" fails',
                                                                         "first fails"))
        self.assertEqual(self.cmd("spec-overlap", path).returncode, 1)
        r = self.cmd("check-artifact", path)
        self.assertEqual(r.returncode, 1)
        self.assertIn("copies SPEC.md's wording", r.stdout)
        # A plan is checked quoted text and all.
        plan = self.write("IMPLEMENTATION.md", "Test: \"the list sorts todos by due date "
                          "with the earliest first\"\n")
        self.assertEqual(self.cmd("spec-overlap", plan).returncode, 1)

    def test_install_checks_installs_refuses_a_conflict_and_rechecks(self):
        # The verifier installs the sealed checks with one command, not a
        # shell loop a permission check refuses.
        self.write("acceptance/files/src/due.acceptance.test.ts.sealed", "due\n")
        self.write("acceptance/files/src/sort.acceptance.test.ts.sealed", "sort\n")
        due = self.worktree / "src" / "due.acceptance.test.ts"
        due.parent.mkdir(parents=True, exist_ok=True)
        due.write_text("the coder's own file\n")
        r = self.cmd("install-checks")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("conflict: src/due.acceptance.test.ts", r.stdout)
        self.assertFalse((self.worktree / "src" / "sort.acceptance.test.ts").exists())
        due.unlink()
        r = self.cmd("install-checks")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("INSTALLED: 2 check(s)", r.stdout)
        self.assertEqual(due.read_text(), "due\n")
        r = self.cmd("install-checks")  # a resumed pass: nothing to write
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("installed:", r.stdout)
        due.write_text("edited\n")
        self.assertEqual(self.cmd("install-checks").returncode, 1)
        r = self.cmd("install-checks", "--recheck")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(due.read_text(), "due\n")

    def test_apply_fix_reports_applied_when_the_new_spec_is_malformed(self):
        self.state_size("FITS")
        fix = self.write("fixes/define-1.md", "FIX B1\n<<<<<<< OLD\n## Conditions\n"
                         "=======\n## Criteria\n>>>>>>> NEW\n")
        r = self.cmd("apply-fix", self.dir / "SPEC.md", fix)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("## Criteria", (self.dir / "SPEC.md").read_text())

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


class TicketTextTest(InitCase):
    def test_define_gets_the_ticket_text_verbatim(self):
        ticket = self.tmp / "ticket.txt"
        ticket.write_text("TODO-7 Due dates\nUsers can set a due date.\n"
                          "AC: overdue todos show in red.\n")
        r = self.init("--ticket", "TODO-7", "--ticket-text-file", ticket)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        r = self.autodev("brief", "define", "--mode", "write", "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        text = (self.dir / "briefs" / "define-1.md").read_text()
        self.assertIn("task: TODO-7 Due dates\n  Users can set a due date.\n"
                      "  AC: overdue todos show in red.\n", text)

    def test_without_ticket_text_define_gets_the_restated_ask(self):
        r = self.init("--ticket", "TODO-7", "--ask", "Let users set a due date on a todo",
                      task="TODO-7")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.autodev("brief", "define", "--mode", "write", "--dir", self.dir)
        text = (self.dir / "briefs" / "define-1.md").read_text()
        self.assertIn("task: Let users set a due date on a todo\n", text)

    def test_an_empty_or_missing_ticket_file_stops_before_the_worktree(self):
        empty = self.tmp / "empty.txt"
        empty.write_text("\n")
        for path, why in ((empty, "is empty"), (self.tmp / "missing.txt", "cannot read")):
            r = self.init("--ticket-text-file", path)
            self.assertEqual(r.returncode, 2)
            self.assertIn(why, r.stderr)
            self.assertFalse(self.worktree.exists())


class CheckArtifactTest(WorkCase):
    def check(self, rel, text):
        path = self.dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return self.cmd("check-artifact", path)

    def test_spec(self):
        self.assertEqual(self.cmd("check-artifact", self.dir / "SPEC.md").returncode, 0)
        no_edge = SPEC.replace("   - Edge: an invalid date is rejected → 400\n", "")
        r = self.check("SPEC.md", no_edge)
        self.assertEqual(r.returncode, 1)
        self.assertIn("condition 1 has no `Edge:` line", r.stdout)

    def test_implementation_headings(self):
        good = "# Implementation plan — x\n\n" + "\n\n".join(
            f"## {h}\nx" for h in ("Files", "Design", "Data flow", "Build sequence",
                                   "Test plan", "Migrations / config"))
        self.assertEqual(self.check("IMPLEMENTATION.md", good).returncode, 0)
        self.assertEqual(self.check("IMPLEMENTATION.md", good.replace("## Design", "## How"))
                         .returncode, 1)

    def test_a_plan_that_copies_the_spec(self):
        from test_next import IMPLEMENTATION
        self.assertEqual(self.check("IMPLEMENTATION.md", IMPLEMENTATION).returncode, 0)
        r = self.check("IMPLEMENTATION.md", IMPLEMENTATION.replace(
            "1. add the field",
            "1. a todo can carry a due date that the list shows next to its title"))
        self.assertEqual(r.returncode, 1)
        self.assertIn("copies SPEC.md's wording (condition 1", r.stdout)

    def test_corrections_and_fixes(self):
        self.assertEqual(self.check("evidence/corrections.md", "# Required changes\nNone.\n")
                         .returncode, 0)
        self.assertEqual(self.check("triage/ci-1.md", "Fix the build\n").returncode, 1)
        fix = "FIX B1\n<<<<<<< OLD\nold\n=======\nnew\n>>>>>>> NEW\n"
        self.assertEqual(self.check("fixes/define-1.md", fix).returncode, 0)
        self.assertEqual(self.check("fixes/define-2.md", fix + "FIX B2\nbroken\n")
                         .returncode, 1)

    def test_reports(self):
        review = (FIXTURES / "CODE_REVIEW.md").read_text().format(tree="0" * 40)
        self.assertEqual(self.check("CODE_REVIEW.md", review).returncode, 0)
        self.assertEqual(self.check("CODE_REVIEW.md", review.replace("## Noise", "## Junk"))
                         .returncode, 1)
        self.assertEqual(self.check("lint/TEST.md", "# TEST — pass\n\n- **Tree:** abc\n")
                         .returncode, 0)
