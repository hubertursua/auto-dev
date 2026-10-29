"""Tests for autodev.py brief / record / check-artifact.

Run: python3 -m unittest discover -s tests -v   (from the repo root)
"""

import json
import os
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

    def test_define_spec_is_checked_against_its_template(self):
        # Define has no shell to run check-artifact: record does it.
        (self.dir / "SPEC.md").write_text(SPEC.replace(
            "   - Edge: an invalid date is rejected → 400\n", "", 1))
        self.returned("define", 1, next="FITS", high_risk="yes", reading="none")
        r = self.cmd("record", "define", "1")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("SPEC.md: condition 1 has no `Edge:` line", r.stdout)
        (self.dir / "SPEC.md").write_text(SPEC)
        r = self.cmd("record", "define", "1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for nxt in ("REVISED", "OVERSIZED"):  # every ok return is checked
            (self.dir / "SPEC.md").write_text(SPEC.replace(
                "   - Verify by: unit\n", "", 1))
            self.returned("define", 2, next=nxt, high_risk="yes", reading="none")
            r = self.cmd("record", "define", "2")
            self.assertEqual(r.returncode, 1, nxt + r.stdout + r.stderr)
            self.assertIn("condition 2 has no `Verify by:` line", r.stdout)

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

    SHARED_BASE = ('import { one } from "./one";\n\ndescribe("todos", () => {\n'
                   '  it("adds", () => {\n    expect(one).toBe(1);\n  });\n});\n')
    SHARED_SEALED = ('import { one } from "./one";\nimport { due } from "./due";\n\n'
                     'describe("todos", () => {\n  it("adds", () => {\n'
                     '    expect(one).toBe(1);\n  });\n  it("shows the due date", () => {\n'
                     '    expect(due()).toBe("2026-01-01");\n  });\n});\n')

    def shared_check(self):
        """A sealed check that adds a test to src/todos.test.ts, which the coder
        has also edited: a changed import and a test of its own."""
        self.write("acceptance/files/src/todos.test.ts.sealed", self.SHARED_SEALED)
        self.write("acceptance/files/src/todos.test.ts.base", self.SHARED_BASE)
        target = self.worktree / "src" / "todos.test.ts"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.SHARED_BASE.replace("{ one }", "{ one, two }").replace(
            "  });\n});", '  });\n  it("adds two", () => {\n    expect(two).toBe(2);\n'
            "  });\n});"))
        return target

    def test_install_checks_adds_a_check_among_the_coders_lines(self):
        target = self.shared_check()
        r = self.cmd("install-checks")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("installed: src/todos.test.ts", r.stdout)
        self.assertEqual(target.read_text(), (
            'import { one, two } from "./one";\nimport { due } from "./due";\n\n'
            'describe("todos", () => {\n  it("adds", () => {\n    expect(one).toBe(1);\n'
            '  });\n  it("shows the due date", () => {\n'
            '    expect(due()).toBe("2026-01-01");\n  });\n  it("adds two", () => {\n'
            "    expect(two).toBe(2);\n  });\n});\n"))
        r = self.cmd("install-checks")  # in already: nothing to write
        self.assertNotIn("installed:", r.stdout)

    def test_install_checks_conflicts_when_the_lines_around_a_check_changed(self):
        target = self.shared_check()
        target.write_text(target.read_text().replace(
            'import { one, two } from "./one";\n\ndescribe', 'describe'))
        r = self.cmd("install-checks")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("conflict: src/todos.test.ts", r.stdout)
        self.assertNotIn("due()", target.read_text())

    def test_recheck_undoes_only_the_edits_that_touched_a_shared_check(self):
        target = self.shared_check()
        self.assertEqual(self.cmd("install-checks").returncode, 0)
        good = target.read_text()
        target.write_text("// the coder's comment\n" + good.replace(
            '"2026-01-01"', '"anything"'))
        r = self.cmd("install-checks", "--recheck")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(target.read_text(), "// the coder's comment\n" + good)

    def test_recheck_without_a_snapshot_is_a_conflict(self):
        target = self.shared_check()
        self.assertEqual(self.cmd("install-checks").returncode, 0)
        (self.dir / "acceptance/files/src/todos.test.ts.installed").unlink()
        target.write_text(target.read_text().replace('"2026-01-01"', '"anything"'))
        r = self.cmd("install-checks", "--recheck")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("conflict: src/todos.test.ts", r.stdout)

    def test_a_check_is_not_anchored_on_punctuation_alone(self):
        # The coder rewrote everything around the check but a closing line:
        # splicing it in there would land inside the coder's code.
        self.write("acceptance/files/src/x.test.ts.base", "a();\n});\nb();\n")
        self.write("acceptance/files/src/x.test.ts.sealed", "a();\n});\ncheck();\nb();\n")
        target = self.worktree / "src" / "x.test.ts"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("c();\n});\nd();\n")
        r = self.cmd("install-checks")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("conflict: src/x.test.ts", r.stdout)

    def test_after_the_build_a_check_cant_claim_a_file_that_holds_none(self):
        state = self.state()
        state["phases"]["4"]["status"] = "done"
        self.write_state(state)
        self.write("acceptance/files/app.ts.sealed", "export const one = 1;\ncheck\n")
        self.returned("acceptance-tester", 1, next="REPAIRED", checks="1", ambiguous="none")
        r = self.cmd("record", "acceptance-tester", 1)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("holds no check yet", r.stdout)

    def test_record_gives_a_sealed_copy_its_base_and_refuses_a_changed_line(self):
        self.write("acceptance/files/app.ts.sealed",
                   "export const one = 1;\nexport const two = 2;\n")
        self.write("acceptance/files/src/new.test.ts.sealed", "a new file\n")
        self.returned("acceptance-tester", 1, next="SEALED", checks="2", ambiguous="none")
        self.assertEqual(self.cmd("record", "acceptance-tester", 1).returncode, 0)
        base = self.dir / "acceptance" / "files" / "app.ts.base"
        self.assertEqual(base.read_text(), "export const one = 1;\n")  # app.ts at HEAD
        self.assertFalse((self.dir / "acceptance/files/src/new.test.ts.base").exists())
        self.write("acceptance/files/app.ts.sealed", "export const one = 2;\n")
        self.returned("acceptance-tester", 2, next="SEALED", checks="2", ambiguous="none")
        r = self.cmd("record", "acceptance-tester", 2)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("may only add lines", r.stdout)

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


PROPOSAL_ON_1 = """# Spec proposals

## P1
- Target: condition 1
- Why: the ticket asks for the date in the detail view as well as in the list
- Comment: none
- New text:
1. A todo can carry a due date that both the list and its detail view show
   - Example: Given todo 7, when its due date is set to 2026-01-02, then the list and
     the detail view show 2026-01-02.
   - Edge: an invalid date is rejected → 400
   - Verify by: integration
"""
NEW_CONDITION = """
## P{k}
- Target: new condition
- Why: undated todos have no place in the order
- Comment: {comment}
- New text:
{n}. A todo with no due date is listed after every dated todo
   - Example: Given one dated and one undated todo, when listed, then the undated one is last.
   - Edge: two undated todos keep the order they were created in
   - Verify by: unit
"""
NEW_CRITERION = """
## P{k}
- Target: new security criterion
- Why: the due date is visible to anyone who knows the id
- Comment: none
- New text:
{n}. Only the owner can read a todo's due date
   - Example: Given user B, when B reads A's todo, then it is refused with 404.
   - Verify by: integration
"""


class SpecProposalRecordTest(WorkCase):
    """`record` on a filer's spec proposals and on Define's rulings."""

    def brief(self, worker, as_mode=None, **sets):
        args = [a for k, v in sets.items() for a in ("--set", f"{k}={v}")]
        r = self.cmd("brief", worker, *(("--mode", as_mode) if as_mode else ()), *args)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return int(r.stdout.split("BRIEF:")[1].split()[0].rsplit("-", 1)[1][:-3])

    def entry(self, worker, n):
        return next(b for b in self.state()["briefs"]
                    if b["worker"] == worker and b["n"] == n)

    def verifier(self, proposal=None, count=None, **extra):
        """A verifier's CORRECT return, with `proposal` as its proposal file."""
        n = self.brief("verifier", mode="first pass", what_changed="none")
        self.spec_eval(v1="unmet")
        self.write("evidence/corrections.md", CORRECTION)
        if proposal is not None:
            self.write(f"proposals/verifier-{n}.md", proposal)
        if count is None:
            count = str(proposal.count("\n## P")) if proposal else "0"
        self.returned("verifier", n, next="CORRECT", tree="x", corrections="1",
                      proposals=count, **extra)
        return self.cmd("record", "verifier", n)

    def refused(self, r, *words):
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        for word in words:
            self.assertIn(word, r.stdout)

    def test_a_return_without_the_proposals_key_records(self):
        n = self.brief("verifier", mode="first pass", what_changed="none")
        self.spec_eval(v1="unmet")
        self.write("evidence/corrections.md", CORRECTION)
        self.returned("verifier", n, next="CORRECT", tree="x", corrections="1")
        r = self.cmd("record", "verifier", n)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        path = self.write("returns/define-9.json", json.dumps(
            {"worker": "define", "status": "ok", "next": "STANDS", "high_risk": "no",
             "reading": "none"}))
        self.assertEqual(self.cmd("check-artifact", path).returncode, 0)
        path.write_text(json.dumps({"worker": "define", "status": "ok", "next": "SHRUG",
                                    "high_risk": "no", "reading": "none"}))
        self.assertEqual(self.cmd("check-artifact", path).returncode, 1)

    def test_a_filer_brief_snapshots_the_spec_and_a_retry_keeps_it(self):
        n = self.brief("verifier", mode="first pass", what_changed="none")
        values = self.brief_values(self.dir / "briefs" / f"verifier-{n}.md")
        self.assertEqual(values["proposal_file"], str(self.dir / "proposals" / "verifier-1.md"))
        self.assertEqual(values["rulings"], "none")
        sha = self.entry("verifier", n)["spec"]
        self.assertEqual((self.dir / "proposals" / f"spec-{sha}.md").read_text(), SPEC)
        self.assertNotIn("spec", self.entry("coder", self.brief(
            "coder", as_mode="build")))
        (self.dir / "SPEC.md").write_text(SPEC.replace("earliest first", "latest first"))
        self.spec_eval(v1="unmet")
        self.write("evidence/corrections.md", CORRECTION)
        self.returned("verifier", n, next="CORRECT", tree="x", corrections="1",
                      proposals="0")
        self.refused(self.cmd("record", "verifier", n), "SPEC.md's condition 2 changed")
        r = self.cmd("brief", "verifier", "--retry", str(n), "--set", "mode=first pass",
                     "--set", "what_changed=none")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.entry("verifier", n + 1)["spec"], sha)

    def test_a_well_formed_verifier_filing_is_recorded(self):
        r = self.verifier(PROPOSAL_ON_1)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.state()["log"][-1]["data"]["proposals"], "1")

    def test_a_filing_on_a_condition_the_spec_lacks_is_refused(self):
        r = self.verifier(PROPOSAL_ON_1.replace("condition 1", "condition 9").replace(
            "\n1. A todo", "\n9. A todo"))
        self.refused(r, "condition 9, which SPEC.md does not have")

    def test_only_the_four_filers_may_file(self):
        self.returned("coder", self.brief("coder", as_mode="build"), next="BUILT",
                      blocked="0", test_changes="none", proposals="1")
        self.refused(self.cmd("record", "coder", "1"), "may not file a spec proposal")
        n = self.brief("cleanup", scope="phase5")
        self.write(f"proposals/cleanup-{n}.md", PROPOSAL_ON_1)
        self.write("lint/TEST.md", "# TEST — pass\n\n- **Tree:** abc\n")
        self.returned("cleanup", n, next="GREEN")
        self.refused(self.cmd("record", "cleanup", n), "cleanup (no mode) may not file")
        n = self.brief("triager", as_mode="ci", failing="unit")
        self.write(f"proposals/triager-{n}.md", PROPOSAL_ON_1)
        self.returned("triager", n, next="INFRA", blockers="0", acceptance_checks="0",
                      triage_file="none", checks_file="none", proposals="1")
        self.refused(self.cmd("record", "triager", n), "triager (ci) may not file")
        n = self.brief("review-judge", as_mode="security-verify")
        from test_next import SECURITY_REVIEW
        self.write("SECURITY_REVIEW.md", SECURITY_REVIEW.format(tree="0" * 40))
        self.write("review/security-corrections.md", "# Required changes\nNone.\n")
        self.returned("review-judge", n, next="VERIFIED", must_fix_open="0", revote="0",
                      proposals="0")
        self.write(f"proposals/review-judge-{n}.md", PROPOSAL_ON_1)
        self.refused(self.cmd("record", "review-judge", n),
                     "review-judge (security-verify) may not file")
        (self.dir / "proposals" / f"review-judge-{n}.md").unlink()
        r = self.cmd("record", "review-judge", n)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_a_filing_missing_a_part_is_refused(self):
        self.refused(self.verifier(PROPOSAL_ON_1.replace(
            "- Why: the ticket asks for the date in the detail view as well as in the "
            "list\n", "")), "P1 has no `Why:`")
        self.refused(self.verifier(PROPOSAL_ON_1.split("- New text:")[0]),
                     "P1 has no `New text:`")
        self.refused(self.verifier(PROPOSAL_ON_1.replace("- Target: condition 1",
                                                         "- Target: the sort rule")),
                     "names nothing")
        self.refused(self.verifier(PROPOSAL_ON_1.replace(
            "   - Edge: an invalid date is rejected → 400\n", "")), "no `Edge:` line")
        self.refused(self.verifier(PROPOSAL_ON_1, count="2"), "holds 1 proposal(s)")
        self.refused(self.verifier(None, count="1"), "there is no such file")

    def test_a_filing_that_takes_out_or_renumbers_is_refused(self):
        self.refused(self.verifier(PROPOSAL_ON_1.replace(
            "- Target: condition 1", "- Target: delete condition 2")),
            "never removes")
        self.refused(self.verifier(PROPOSAL_ON_1.replace("\n1. A todo", "\n2. A todo")),
                     "never renumbered")

    def test_a_filing_on_an_existing_s_row_is_refused(self):
        self.refused(self.verifier(PROPOSAL_ON_1.replace("condition 1", "S1")),
                     "security criterion S1")
        self.refused(self.verifier(PROPOSAL_ON_1.replace("- Target: condition 1",
                                                         "- Target: conditions 1, S1")),
                     "security criterion S1")

    def test_an_addition_is_one_item_with_the_next_number(self):
        head = "# Spec proposals\n"
        self.refused(self.verifier(head + NEW_CONDITION.format(k=1, n=3, comment="none")
                                   .replace("- Target: new condition",
                                            "- Target: new condition, condition 2")),
                     "adds and changes at once")
        self.refused(self.verifier(head + NEW_CONDITION.format(k=1, n=4, comment="none")),
                     "must be numbered 3")
        two = NEW_CONDITION.format(k=1, n=3, comment="none") + (
            "4. Another item\n   - Example: x\n   - Edge: y\n   - Verify by: unit\n")
        self.refused(self.verifier(head + two), "adds more than one item")
        r = self.verifier(head + NEW_CONDITION.format(k=1, n=3, comment="none")
                          + NEW_CRITERION.format(k=2, n="S2"))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.refused(self.verifier(head + NEW_CRITERION.format(k=1, n="S1")),
                     "must be numbered S2")

    def test_new_text_equal_to_the_current_item_is_refused(self):
        same = ("# Spec proposals\n\n## P1\n- Target: condition 2\n- Why: x\n"
                "- New text:\n2. The list sorts todos by due date\n   with the earliest "
                "first\n   - Example: Given two todos, when listed, then the earlier one "
                "is first.\n   - Edge: none — every todo has a place in the order\n"
                "   - Verify by:   unit\n")
        self.refused(self.verifier(same), "is what it says now (spacing aside)")

    def triager(self, proposal, comment, blockers="0"):
        n = self.brief("triager", as_mode="human")
        self.write(f"proposals/triager-{n}.md", proposal.replace(
            "- Comment: none", f"- Comment: {comment}"))
        self.returned("triager", n, next="TRIAGED", blockers=blockers,
                      acceptance_checks="0", triage_file="none", checks_file="none",
                      proposals="1")
        return n, self.cmd("record", "triager", n)

    def test_a_pr_comment_filing_needs_the_comment_id(self):
        _, r = self.triager(PROPOSAL_ON_1, "none")
        self.refused(r, "names no comment id")
        _, r = self.triager(PROPOSAL_ON_1, "12345")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_a_filer_that_edits_spec_md_is_refused(self):
        n = self.brief("triager", as_mode="human")
        cut = SPEC.split("2. The list sorts")[0] + "\n## Assumptions" + \
            SPEC.split("## Assumptions")[1]
        (self.dir / "SPEC.md").write_text(cut)
        self.returned("triager", n, next="TRIAGED", blockers="0", acceptance_checks="0",
                      triage_file="none", checks_file="none", proposals="0")
        self.refused(self.cmd("record", "triager", n), "SPEC.md's condition 2 changed",
                     "may only propose")
        # Even a blocked return: the edit is refused before its status counts.
        self.returned("triager", n, status="blocked", next="none")
        self.refused(self.cmd("record", "triager", n), "may only propose")
        (self.dir / "SPEC.md").write_text(SPEC.replace(
            "A todo can carry a due date that the list shows next to its title",
            "A todo can carry a due date\n   that the list shows next to its title"))
        self.returned("triager", n, next="TRIAGED", blockers="0", acceptance_checks="0",
                      triage_file="none", checks_file="none", proposals="0")
        r = self.cmd("record", "triager", n)  # re-wrapping is no edit
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_a_correction_quoting_a_proposed_statement_is_refused(self):
        no_pending = "\n".join(ln for ln in CODE_REVIEW.splitlines()
                               if not ln.startswith(("| C4", "| C6")))
        n = self.brief("review-judge", as_mode="consolidate", reviewers="R1, R2, R3",
                       scope="first", tree="a" * 40)
        self.write(f"proposals/review-judge-{n}.md", PROPOSAL_ON_1)
        self.write("review/pass-1/corrections.md", "# Required changes\n1. C1: make "
                   "both the list and its detail view show the date in src/view.ts\n")
        self.write("CODE_REVIEW.md", no_pending.format(tree="0" * 40))
        self.returned("review-judge", n, next="MUST_FIX", must_fix_open="1", revote="0",
                      proposals="1")
        self.refused(self.cmd("record", "review-judge", n), "copies P1's proposed text")
        self.write("review/pass-1/corrections.md", "# Required changes\n1. C1: guard "
                   "the null due date in `src/sort.ts:4` before comparing\n")
        r = self.cmd("record", "review-judge", n)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    # ------------------------------------------------------------ Define's answer

    def define(self, batch, rulings, spec, nxt):
        """Define ruling on `batch`: SPEC.md becomes `spec`; returns record's result."""
        self.write("proposals/batch-1.md", batch)
        n = self.brief("define", as_mode="revise",
                       proposals=f"{self.dir}/proposals/batch-1.md\nRule on 1 proposal.",
                       rulings_file=f"{self.dir}/proposals/batch-1-rulings.md")
        self.assertTrue(self.entry("define", n)["spec"])
        values = self.brief_values(self.dir / "briefs" / f"define-{n}.md")
        self.assertEqual(values["proposals"], f"{self.dir}/proposals/batch-1.md")
        self.assertEqual(values["rulings_file"], f"{self.dir}/proposals/batch-1-rulings.md")
        (self.dir / "SPEC.md").write_text(spec)
        self.write("proposals/batch-1-rulings.md", rulings)
        self.returned("define", n, next=nxt, high_risk="yes", reading="none")
        r = self.cmd("record", "define", n)
        (self.dir / "SPEC.md").write_text(SPEC)
        return r

    APPLIED = "# Rulings\n\n## P1\n- Answer: applied\n- Reason: none\n"
    STOOD = "# Rulings\n\n## P1\n- Answer: stands\n- Reason: the ticket names the list only\n"

    def test_define_rulings_must_match_the_spec_diff(self):
        new_1 = SPEC.replace("that the list shows next to its title",
                             "that both the list and its detail view show")
        new_2 = SPEC.replace("earliest first", "latest first")
        cases = {
            "only Context": (self.APPLIED, SPEC.replace("Todos have no due dates.",
                                                       "Todos have none."), "REVISED",
                             "condition 1 reads as before"),
            "stands but changed": (self.STOOD, new_1, "STANDS",
                                   "condition 1 changed, but no applied proposal"),
            "no reason": (self.STOOD.replace("the ticket names the list only", "none"),
                          SPEC, "STANDS", "P1 stands with no reason"),
            "applied plus 2": (self.APPLIED, new_1.replace("earliest first",
                                                           "latest first"),
                               "REVISED", "condition 2 changed, but no applied"),
            "condition 2 gone": (self.APPLIED, new_1.split("2. The list")[0]
                                 + "## Assumptions" + SPEC.split("## Assumptions")[1],
                                 "REVISED", "condition 2 is gone"),
            "renumbered": (self.APPLIED, new_1.replace("2. The list", "3. The list"),
                           "REVISED", "condition 2 is gone"),
            "an extra item": (self.APPLIED, new_1.replace(
                "\n## Assumptions", "3. Undated todos sort last\n   - Example: x\n"
                "   - Edge: y\n   - Verify by: unit\n\n## Assumptions"), "REVISED",
                "SPEC.md adds 3"),
            "wrong token": (self.APPLIED, new_1, "STANDS", "which is REVISED"),
        }
        for name, (rulings, spec, nxt, said) in cases.items():
            with self.subTest(name):
                self.refused(self.define(PROPOSAL_ON_1, rulings, spec, nxt), said)
        r = self.define(PROPOSAL_ON_1, self.APPLIED, new_1, "REVISED")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        r = self.define(PROPOSAL_ON_1, self.STOOD, SPEC.replace(
            "Todos have no due dates.", "Todos have none (the list-only reading stands)."),
            "STANDS")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIsNotNone(new_2)

    def test_define_may_not_touch_an_existing_s_row(self):
        new_1 = SPEC.replace("that the list shows next to its title",
                             "that both the list and its detail view show")
        reworded = new_1.replace("Only the owner can set", "Anyone can set")
        self.refused(self.define(PROPOSAL_ON_1, self.APPLIED, reworded, "REVISED"),
                     "security criterion S1 changed")
        deleted = new_1.split("S1. Only")[0]
        self.refused(self.define(PROPOSAL_ON_1, self.APPLIED, deleted, "REVISED"),
                     "security criterion S1 is gone")

    def test_check_artifact_reads_proposal_and_rulings_files(self):
        good = self.write("proposals/verifier-1.md", PROPOSAL_ON_1)
        self.assertEqual(self.cmd("check-artifact", good).returncode, 0)
        bad = self.write("proposals/verifier-2.md", PROPOSAL_ON_1.replace(
            "condition 1", "condition 9").replace("\n1. A todo", "\n9. A todo"))
        r = self.cmd("check-artifact", bad)
        self.refused(r, "condition 9")
        r = self.cmd("check-artifact", self.write("proposals/triager-3.md", PROPOSAL_ON_1))
        self.refused(r, "names no comment id")
        self.assertEqual(self.cmd("check-artifact", self.write(
            "proposals/batch-1.md", PROPOSAL_ON_1)).returncode, 0)
        self.assertEqual(self.cmd("check-artifact", self.write(
            "proposals/batch-1-rulings.md", self.STOOD)).returncode, 0)
        r = self.cmd("check-artifact", self.write(
            "proposals/batch-2-rulings.md", self.STOOD.replace(
                "the ticket names the list only", "none")))
        self.refused(r, "stands with no reason")


# A five-step plan in its own words (example in TypeScript).
PLAN = """# Implementation plan — due dates (example in TypeScript)

Review effort: high — a small, local change

## Files
- `src/due.ts` — modify: the date field

## Design
The store keeps each date as an ISO string beside the title.

## Data flow
A request reaches the todo route, which reads the store.

## Build sequence
1. Add a `dueOn` field to the todo record in src/due.ts — test: `src/due.test.ts`
2. Parse the incoming value with the shared ISO parser — test: `src/due.test.ts`
3. Make the todo route pass the id to `setDue()` as a number — test: `src/route.test.ts`
4. Return the stored value in the route's JSON body — test: `src/route.test.ts`
5. Log each change with the acting user's id — test: `src/route.test.ts`

## Test plan
| Test | Location | Proves | Spec condition |
|------|----------|--------|----------------|
| stores the field | `src/due.test.ts` | the field is kept | 1 |

## Migrations / config
none
"""
NEW_3 = "3. Make the todo route pass the id to `setDue()` as a string — test: `src/route.test.ts`"
NEW_5 = "5. Log each change with the acting user's id and the old value — test: `src/route.test.ts`"
NEW_6 = "6. Reject an empty body before it reaches the store — test: `src/route.test.ts`"
STEP_WHY = "the route receives the id as a string, so a number never matches a record"
CHECK_WHY = "it expects the date in the title cell, but the plan puts it in its own column"
DUE_CHECK = '`src/due.acceptance.test.ts` :: "shows the due date"'
SORT_CHECK = '`src/sort.acceptance.test.ts` :: "sorts earliest first"'
PROPOSAL_ON_2 = """# Spec proposals

## P1
- Target: condition 2
- Why: the ticket asks for undated todos to come last
- Comment: none
- New text:
2. The list sorts todos by due date with the earliest first and undated ones last
   - Example: Given two todos, when listed, then the earlier one is first.
   - Edge: an undated todo is listed after every dated one
   - Verify by: unit
"""


def coder_file(*blocks):
    return "# Plan and check proposals\n\n" + "\n".join(blocks)


def step_block(k, target, new_text, why=STEP_WHY):
    return f"## P{k}\n- Target: {target}\n- Why: {why}\n- New text:\n{new_text}\n"


def check_block(k, check, why=CHECK_WHY):
    return f"## P{k}\n- Target: check {check}\n- Why: {why}\n- New text: none\n"


def rulings_text(*answers):
    return "# Rulings\n" + "".join(f"\n## P{i}\n- Answer: {a}\n- Reason: {r}\n"
                                   for i, (a, r) in enumerate(answers, 1))


class UpstreamProposalRecordTest(WorkCase):
    """`record` on the coder's plan and check proposals, on the planner's and
    the acceptance tester's rulings, and on who may file against what."""

    brief = SpecProposalRecordTest.brief
    entry = SpecProposalRecordTest.entry
    refused = SpecProposalRecordTest.refused

    def setUp(self):
        super().setUp()
        self.write("IMPLEMENTATION.md", PLAN)
        for rel in ("src/due.acceptance.test.ts", "src/sort.acceptance.test.ts"):
            self.write(f"acceptance/files/{rel}.sealed",
                       f"test('{rel.split('/')[1].split('.')[0]} check')\n")

    def ok(self, r):
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("RECORDED", r.stdout)

    # ------------------------------------------------------------ the coder

    def coder(self, mode, *blocks, count=None, nxt="BUILT", blocked="0", **extra):
        sets = {}
        if mode == "correction":
            sets["corrections_file"] = str(self.write("evidence/corrections.md", CORRECTION))
        n = self.brief("coder", as_mode=mode, **sets)
        if blocks:
            self.write(f"proposals/coder-{n}.md", coder_file(*blocks))
        data = {"next": nxt, "blocked": blocked, "test_changes": "none", **extra}
        if count is not False:
            data["proposals"] = str(len(blocks) if count is None else count)
        self.returned("coder", n, **data)
        return n, self.cmd("record", "coder", n)

    def test_a_correcting_coder_may_question_a_step_and_a_listed_check(self):
        _, r = self.coder("correction", step_block(1, "step 3", NEW_3),
                          check_block(2, SORT_CHECK))
        self.ok(r)
        self.assertEqual(self.state()["log"][-1]["data"]["proposals"], "2")
        _, r = self.coder("correction", step_block(1, "new step", NEW_6))
        self.ok(r)
        _, r = self.coder("correction", step_block(
            1, "steps 3, 5", NEW_3 + "\n" + NEW_5))
        self.ok(r)

    def test_a_coder_naming_a_spec_item_is_refused(self):
        _, r = self.coder("correction", step_block(1, "condition 2", NEW_3))
        self.refused(r, "P1 names a SPEC.md condition",
                     "the coder may not propose against the spec")
        _, r = self.coder("correction", step_block(
            1, "new security criterion",
            "S2. Only the owner sees the log\n   - Example: x\n   - Verify by: unit"))
        self.refused(r, "P1 names a security criterion",
                     "the coder may not propose against the spec")
        _, r = self.coder("build", step_block(1, "the sort rule", NEW_3))
        self.refused(r, "P1 names no step and no check")

    def test_a_building_coder_has_no_check_to_question(self):
        _, r = self.coder("build", check_block(1, SORT_CHECK))
        self.refused(r, "P1 questions a check, but you were shown no check")
        _, r = self.coder("build", step_block(1, "step 3", NEW_3))
        self.ok(r)

    def test_a_coder_naming_a_missing_step_hears_the_real_ones(self):
        _, r = self.coder("build", step_block(1, "step 7", NEW_3.replace("3.", "7.", 1)))
        self.refused(r, "P1 names step 7, which IMPLEMENTATION.md's build sequence lacks",
                     "it has steps 1, 2, 3, 4, 5")
        old_3 = next(ln for ln in PLAN.splitlines() if ln.startswith("3. "))
        _, r = self.coder("build", step_block(1, "step 3", old_3.replace(" the id", "  the id")))
        self.refused(r, "new text for step 3 is what it says now")
        _, r = self.coder("build", step_block(1, "new step", NEW_6.replace("6.", "7.", 1)))
        self.refused(r, "the new step must be numbered 6")

    def test_a_coder_mixing_kinds_or_adding_while_changing_is_refused(self):
        _, r = self.coder("correction", step_block(1, f"step 3 and check {SORT_CHECK}", NEW_3))
        self.refused(r, "mixes a step with a check")
        _, r = self.coder("correction", step_block(1, "new step, step 3", NEW_3))
        self.refused(r, "adds a step and changes steps at once")
        _, r = self.coder("correction", step_block(1, "remove step 4", NEW_3))
        self.refused(r, "would take a step out or renumber one")
        _, r = self.coder("correction", check_block(1, f"{SORT_CHECK} and {DUE_CHECK}"))
        self.refused(r, "names more than one check")

    def test_a_coder_naming_its_own_test_or_an_unlisted_file_is_refused(self):
        _, r = self.coder("correction", check_block(
            1, '`src/sort.acceptance.test.ts` :: "my own helper test"'))
        self.refused(r, "MANIFEST.md lists as no check", "one of your own tests")
        _, r = self.coder("correction", check_block(1, '`src/list.test.ts` :: "lists"'))
        self.refused(r, "not one of the check files your brief listed",
                     "src/due.acceptance.test.ts, src/sort.acceptance.test.ts")
        _, r = self.coder("correction", check_block(1, DUE_CHECK))
        self.ok(r)

    def test_a_4_11_coder_return_reads_as_filing_nothing(self):
        n, r = self.coder("build", count=False)
        self.ok(r)
        self.assertNotIn("proposals", self.state()["log"][-1]["data"])
        self.assertFalse((self.dir / "proposals" / f"coder-{n}.md").exists())
        _, r = self.coder("build", count=1)
        self.refused(r, "holds 0 proposal(s)", "may not file a spec proposal")

    # ------------------------------------------------------------ the spec filers

    def test_spec_filers_are_sent_to_their_check_route(self):
        from test_next import CLEAN_REVIEW
        check = coder_file(check_block(1, DUE_CHECK))
        step = coder_file(step_block(1, "step 3", NEW_3))
        n = self.brief("verifier", mode="first pass", what_changed="none")
        self.spec_eval(v1="unmet")
        self.write("evidence/corrections.md", CORRECTION)
        self.returned("verifier", n, next="CORRECT", tree="x", corrections="1",
                      proposals="1")
        for text, said in ((check, "questions a check only through `next: REPAIR`"),
                           (step, "the verifier may not propose against the plan")):
            self.write(f"proposals/verifier-{n}.md", text)
            self.refused(self.cmd("record", "verifier", n), said)
        n = self.brief("review-judge", as_mode="consolidate", reviewers="R1, R2, R3",
                       scope="first", tree="a" * 40)
        self.write("CODE_REVIEW.md", CLEAN_REVIEW.format(tree="0" * 40))
        self.returned("review-judge", n, next="CLEAN", must_fix_open="0", revote="0",
                      proposals="1")
        for text, said in ((check, "category `acceptance-check`"),
                           (step, "the review judge may not propose against the plan")):
            self.write(f"proposals/review-judge-{n}.md", text)
            self.refused(self.cmd("record", "review-judge", n), said)
        n = self.brief("triager", as_mode="human")
        self.returned("triager", n, next="TRIAGED", blockers="0", acceptance_checks="0",
                      triage_file="none", checks_file="none", proposals="1")
        for text, said in ((check, "an ACCEPTANCE_CHECK entry in its checks file"),
                           (step, "the triager may not propose against the plan")):
            self.write(f"proposals/triager-{n}.md", text.replace(
                "- New text", "- Comment: 4242\n- New text"))
            self.refused(self.cmd("record", "triager", n), said)
        from test_next import SECURITY_REVIEW
        n = self.brief("security-reviewer", leads="none")
        self.write("SECURITY_REVIEW.md", SECURITY_REVIEW.format(tree="0" * 40))
        self.returned("security-reviewer", n, next="CLEAN", must_fix="0", pre_existing="0",
                      proposals="1")
        for text, said in ((check, ("may not question a check; it files against SPEC.md "
                                    "alone")),
                           (step, "the security reviewer may not propose against the plan")):
            self.write(f"proposals/security-reviewer-{n}.md", text)
            self.refused(self.cmd("record", "security-reviewer", n), said)
        self.write(f"proposals/security-reviewer-{n}.md", PROPOSAL_ON_1)
        self.ok(self.cmd("record", "security-reviewer", n))

    def test_non_filers_hear_who_files_what(self):
        who = ("SPEC.md's are filed by the verifier, the review judge in consolidate mode, "
               "the security reviewer and the triager in human mode; the plan's and the "
               "checks' by the coder")
        n = self.brief("triager", as_mode="ci", failing="unit")
        self.write(f"proposals/triager-{n}.md", coder_file(check_block(1, DUE_CHECK)))
        self.returned("triager", n, next="INFRA", blockers="0", acceptance_checks="0",
                      triage_file="none", checks_file="none", proposals="1")
        self.refused(self.cmd("record", "triager", n), "triager (ci) may not file a proposal",
                     who)
        n = self.brief("plan-reviewer")
        self.write(f"proposals/plan-reviewer-{n}.md", coder_file(step_block(1, "step 3",
                                                                          NEW_3)))
        self.returned("plan-reviewer", n, next="CLEAN", blockers="0", fix_file="none",
                      proposals="1")
        self.refused(self.cmd("record", "plan-reviewer", n),
                     "plan-reviewer (no mode) may not file a proposal", who)

    def test_a_verifier_spec_proposal_and_its_repair_record_together(self):
        n = self.brief("verifier", mode="first pass", what_changed="none")
        self.spec_eval(v1="partial", defective=DUE_CHECK)
        self.write(f"proposals/verifier-{n}.md", PROPOSAL_ON_2)
        self.returned("verifier", n, next="REPAIR", tree="x", corrections="0",
                      proposals="1")
        self.ok(self.cmd("record", "verifier", n))

    # ------------------------------------------------------------ snapshots

    def test_owner_briefs_keep_a_copy_and_a_retry_reuses_it(self):
        blocked = f"the steps listed in {self.dir}/blocked/coder-1.md"
        n = self.brief("planner", as_mode="blocked", blocked=blocked)
        sha = self.entry("planner", n)["plan"]
        self.assertEqual((self.dir / "proposals" / "snapshots" / f"plan-{sha}.md")
                         .read_text(), PLAN)
        m = self.brief("planner", as_mode="revise",
                       proposals=f"{self.dir}/proposals/plan-1.md\nRule on 1 proposal.",
                       rulings_file=f"{self.dir}/proposals/plan-1-rulings.md")
        self.assertEqual(self.entry("planner", m)["plan"], sha)
        self.assertIn("plan", self.entry("planner", self.brief(
            "planner", as_mode="revise", spec_change="condition 1 reads differently")))
        self.assertNotIn("plan", self.entry("planner", self.brief(
            "planner", as_mode="revise", direction="split step 2")))
        self.assertNotIn("plan", self.entry("planner", self.brief("planner",
                                                                   as_mode="write")))
        t = self.brief("acceptance-tester", as_mode="repair", scope="ONLY conditions 2: x",
                       report="y")
        name = self.entry("acceptance-tester", t)["sealed"]
        snap = self.dir / "proposals" / "snapshots" / name
        self.assertEqual((snap / "MANIFEST.md").read_text(), MANIFEST)
        self.assertEqual((snap / "files" / "src" / "sort.acceptance.test.ts.sealed")
                         .read_text(), "test('sort check')\n")
        self.assertNotIn("sealed", self.entry("acceptance-tester", self.brief(
            "acceptance-tester", as_mode="write", scope="ALL CONDITIONS")))
        # A refused planner answer: the retry is held to the first brief's copy.
        self.write("IMPLEMENTATION.md", PLAN.replace("Log each", "Record each"))
        self.write("acceptance/files/src/sort.acceptance.test.ts.sealed", "changed\n")
        self.refused(self.cmd("record", "planner", n))
        r = self.cmd("brief", "planner", "--mode", "blocked", "--retry", str(n),
                     "--set", f"blocked={blocked}")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.state()["briefs"][-1]["plan"], sha)
        self.refused(self.cmd("record", "acceptance-tester", t))
        r = self.cmd("brief", "acceptance-tester", "--mode", "repair", "--retry", str(t),
                     "--set", "scope=ONLY conditions 2: x", "--set", "report=y")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.state()["briefs"][-1]["sealed"], name)

    def blocked_coder(self, line):
        """A building coder that stopped step 3, filed P1 on it and wrote `line`
        as its blocked file. Returns record's result."""
        n = self.brief("coder", as_mode="build")
        self.write(f"proposals/coder-{n}.md", coder_file(step_block(1, "step 3", NEW_3)))
        self.write(f"blocked/coder-{n}.md", line + "\n")
        self.returned("coder", n, next="BLOCKED", blocked="1", test_changes="none",
                      proposals="1")
        return self.cmd("record", "coder", n)

    def test_a_blocked_file_in_bold_names_the_step_form_it_needs(self):
        self.refused(self.blocked_coder("- **Step 3:** the store has no lookup"),
                     "can't be read as a stopped step", "`- step <n>: <why>`")

    def test_a_blocked_file_with_words_after_the_number_is_refused(self):
        self.refused(self.blocked_coder("- step 3 (the todo route): the store has no lookup"),
                     "can't be read as a stopped step", "`- step <n>: <why>`")

    def test_a_blocked_file_in_the_step_form_is_recorded(self):
        self.ok(self.blocked_coder("- step 3: the store has no lookup"))

    def test_a_blocked_file_naming_no_step_is_refused(self):
        self.refused(self.blocked_coder("The store has no lookup."),
                     "names no stopped step", "`- step <n>: <why>`")

    def blocked_coder_with_no_proposal(self, text):
        """A building coder that stopped and filed no proposal, with `text` as
        its blocked file. Returns record's result."""
        n = self.brief("coder", as_mode="build")
        self.write(f"blocked/coder-{n}.md", text + "\n")
        self.returned("coder", n, next="BLOCKED", blocked="1", test_changes="none",
                      proposals="0")
        return self.cmd("record", "coder", n)

    def test_a_blocked_file_in_bold_with_no_proposal_is_recorded(self):
        # With no plan proposal the planner reads the file as prose, as before.
        self.ok(self.blocked_coder_with_no_proposal("- **Step 3:** the store has no lookup"))

    def test_a_blocked_file_in_plain_prose_with_no_proposal_is_recorded(self):
        self.ok(self.blocked_coder_with_no_proposal(
            "Step 3 can't be built: the store has no lookup."))

    def test_a_blocked_return_with_no_proposal_still_needs_its_blocked_file(self):
        n = self.brief("coder", as_mode="build")
        self.returned("coder", n, next="BLOCKED", blocked="1", test_changes="none",
                      proposals="0")
        self.refused(self.cmd("record", "coder", n), "does not exist")

    # ------------------------------------------------------------ the planner

    def planner(self, batch, rulings, plan, nxt="REVISED", mode="revise", stopped=None,
                base=PLAN):
        """The planner ruling on `batch` (plan-1.md's blocks): IMPLEMENTATION.md
        is `base` when it is briefed and becomes `plan`. Returns record's result."""
        self.write("IMPLEMENTATION.md", base)
        self.write("proposals/plan-1.md", "# Plan proposals\n\n" + "\n".join(batch))
        sets = {"proposals": f"{self.dir}/proposals/plan-1.md\nRule on {len(batch)}.",
                "rulings_file": f"{self.dir}/proposals/plan-1-rulings.md"}
        if mode == "blocked":
            self.write("blocked/coder-1.md", stopped or "- step 4: no such column\n")
            sets["blocked"] = f"the steps listed in {self.dir}/blocked/coder-1.md"
        n = self.brief("planner", as_mode=mode, **sets)
        self.write("IMPLEMENTATION.md", plan)
        self.write("proposals/plan-1-rulings.md", rulings)
        self.returned("planner", n, next=nxt, entry_points_changed="no")
        r = self.cmd("record", "planner", n)
        self.write("IMPLEMENTATION.md", PLAN)
        return r

    def plan_with(self, **steps):
        """PLAN with step <n> replaced by steps['s<n>'] (None removes it), and
        steps['extra'] appended to the build sequence."""
        text = PLAN
        for key, new in steps.items():
            if key == "extra":
                text = text.replace("\n\n## Test plan", f"\n{new}\n\n## Test plan")
                continue
            old = next(ln for ln in PLAN.splitlines() if ln.startswith(f"{key[1:]}. "))
            text = text.replace(old + "\n", "" if new is None else new + "\n")
        return text

    STEP_3 = step_block(1, "step 3", NEW_3)
    STEP_5 = step_block(2, "step 5", NEW_5)
    ADD_6 = step_block(3, "new step", NEW_6)
    REASON = "the log must keep the id alone, since the audit job parses that line"

    def test_planner_rulings_are_held_to_the_step_diff(self):
        both = [self.STEP_3, self.STEP_5]
        good = rulings_text(("applied", "none"), ("stands", self.REASON))
        cases = {
            "step 5 changed too": (both, good, self.plan_with(s3=NEW_3, s5=NEW_5), "REVISED",
                                   "step 5 changed, though P2, which names it, stands"),
            "applied but unchanged": (both, good, PLAN, "REVISED",
                                      "P1 is applied but step 3 reads as before"),
            "no reason": (both, rulings_text(("applied", "none"), ("stands", "none")),
                          self.plan_with(s3=NEW_3), "REVISED", "P2 stands with no reason"),
            "no ruling": (both, rulings_text(("applied", "none")), self.plan_with(s3=NEW_3),
                          "REVISED", "has no ruling for P2"),
            "an extra step": (both, good, self.plan_with(s3=NEW_3, extra=NEW_6), "REVISED",
                              "adds step(s) 6"),
            "a missing addition": (both + [self.ADD_6], rulings_text(
                ("applied", "none"), ("stands", self.REASON), ("applied", "none")),
                self.plan_with(s3=NEW_3), "REVISED", "asked for 1 new step(s) (6)"),
            "a gone step": (both, good, self.plan_with(s3=NEW_3, s4=None), "REVISED",
                            "step 4 is gone"),
            "an unnamed step": (both, good, self.plan_with(s3=NEW_3, s2="2. Parse it"),
                                "REVISED", "step 2 changed, but no applied proposal"),
            "wrong token": (both, good, self.plan_with(s3=NEW_3), "STANDS", "which is REVISED"),
            "stands token": (both, rulings_text(("stands", self.REASON), ("stands", "x y")),
                             PLAN, "REVISED", "which is STANDS"),
        }
        for name, (batch, rulings, plan, nxt, said) in cases.items():
            with self.subTest(name):
                self.refused(self.planner(batch, rulings, plan, nxt), said)
        self.ok(self.planner(both, good, self.plan_with(s3=NEW_3), "REVISED"))
        # Re-wrapping a standing step is no change.
        self.ok(self.planner(both, good, self.plan_with(s3=NEW_3).replace(
            "5. Log each change with the acting", "5. Log each change\n   with the  acting"),
            "REVISED"))
        self.ok(self.planner(both + [self.ADD_6], rulings_text(
            ("applied", "none"), ("stands", self.REASON), ("applied", "none")),
            self.plan_with(s3=NEW_3, extra=NEW_6), "REVISED"))
        self.ok(self.planner(both, rulings_text(("stands", "x y"), ("stands", self.REASON)),
                             PLAN, "STANDS"))

    def test_a_combined_blocked_answer_may_touch_stopped_steps(self):
        batch = [self.STEP_3, step_block(2, "step 4", "4. Return the value as a string"),
                 step_block(3, "step 5", NEW_5)]
        rulings = rulings_text(("applied", "none"), ("stands", self.REASON),
                               ("stands", self.REASON))
        plan = self.plan_with(s3=NEW_3, s4="4. Return the stored value under `due`",
                              extra=NEW_6)
        self.ok(self.planner(batch, rulings, plan, "PLAN_REVISED", mode="blocked"))
        self.refused(self.planner(batch, rulings, self.plan_with(s3=NEW_3, s5=NEW_5),
                                  "PLAN_REVISED", mode="blocked"),
                     "step 5 changed, though P3")
        self.refused(self.planner(batch, rulings, plan, "PLAN_REVISED", mode="blocked",
                                  stopped="- step 2: the parser is async\n"),
                     "step 4 changed, though P2")

    def test_a_plan_quoting_a_stands_reason_is_refused(self):
        batch = [self.STEP_3, self.STEP_5]
        rulings = rulings_text(("applied", "none"), ("stands", self.REASON))
        quoted = self.plan_with(s3=NEW_3).replace(
            "beside the title.", "beside the title. The log must keep the id alone, since "
            "the audit job parses that line.")
        self.refused(self.planner(batch, rulings, quoted), "repeats P2's stands reason")
        # A reason may quote the step it rules on: the coder could read that already.
        quoting = rulings_text(("applied", "none"), (
            "stands", ("step 5 says log each change with the acting user's id, and that "
                       "is right")))
        self.ok(self.planner(batch, quoting, self.plan_with(s3=NEW_3)))

    def test_a_four_word_stands_reason_in_the_plan_is_refused(self):
        batch = [self.STEP_3, self.STEP_5]
        rulings = rulings_text(("applied", "none"), ("stands", "auditors parse plain ids"))
        quoted = self.plan_with(s3=NEW_3).replace(
            "beside the title.", "beside the title, since auditors parse plain ids.")
        self.refused(self.planner(batch, rulings, quoted), "repeats P2's stands reason")

    def test_a_three_word_stands_reason_in_the_plan_is_accepted(self):
        batch = [self.STEP_3, self.STEP_5]
        rulings = rulings_text(("applied", "none"), ("stands", "auditors parse ids"))
        quoted = self.plan_with(s3=NEW_3).replace(
            "beside the title.", "beside the title, since auditors parse ids.")
        self.ok(self.planner(batch, rulings, quoted))

    def test_other_plan_sections_may_follow_an_applied_step(self):
        batch = [self.STEP_3, self.STEP_5]
        rulings = rulings_text(("applied", "none"), ("stands", self.REASON))
        followed = self.plan_with(s3=NEW_3).replace(
            "beside the title.", "beside the title; the route keeps ids as strings.").replace(
            "| stores the field |", "| passes the id as a string |")
        self.ok(self.planner(batch, rulings, followed))
        echoed = followed.replace("The store keeps", "A todo can carry a due date that the "
                                  "list shows next to its title. The store keeps")
        self.refused(self.planner(batch, rulings, echoed), "copies SPEC.md's wording")

    # ------------------------------------------------------------ the tester

    def checks_answer(self, targets, rulings, nxt, edits=(), rows=None, texts=None):
        """The tester ruling on a batch of conditions (`targets`, each a cid or
        None for an unnamed item): `edits` are sealed files it appends a line
        to, `texts` sealed files it rewrites whole ({file: text}), `rows` a new
        MANIFEST.md. Returns record's result."""
        files = self.dir / "acceptance" / "files" / "src"
        kept = {p: p.read_text() for p in files.iterdir()}
        batch = "# Check proposals\n" + "".join(
            f"\n## P{k}\n- Target: " + (f"condition {cid}" if cid else
                                        "no condition named — the checks the report names")
            + "\n- From: the coder (coder #1), its P1\n" for k, cid in enumerate(targets, 1))
        self.write("proposals/checks-1.md", batch)
        n = self.brief("acceptance-tester", as_mode="repair",
                       scope="ONLY conditions 2: the coder questions their checks",
                       report=f"{self.dir}/proposals/checks-1.md",
                       proposals=f"{self.dir}/proposals/checks-1.md\nRule on it.",
                       rulings_file=f"{self.dir}/proposals/checks-1-rulings.md")
        for rel, line in edits:
            path = files / f"{rel}.sealed"
            path.write_text(path.read_text() + line + "\n")
        for rel, text in (texts or {}).items():
            (files / f"{rel}.sealed").write_text(text)
        if rows is not None:
            self.write("acceptance/MANIFEST.md", rows)
        self.write("proposals/checks-1-rulings.md", rulings)
        self.returned("acceptance-tester", n, next=nxt, checks="1", ambiguous="none")
        r = self.cmd("record", "acceptance-tester", n)
        for path, text in kept.items():
            path.write_text(text)
        self.write("acceptance/MANIFEST.md", MANIFEST)
        return r

    SORT = ("sort.acceptance.test.ts", "test('sorts with ties kept in order')")
    DUE = ("due.acceptance.test.ts", "test('shows the date in its own column')")
    TESTER_REASON = "condition two orders by the date alone, and the check does just that"

    def test_tester_rulings_are_held_to_the_sealed_and_manifest_diff(self):
        stood = rulings_text(("stands", self.TESTER_REASON))
        repaired = rulings_text(("repaired", "none"))
        moved = MANIFEST.replace('"sorts earliest first" | Example', '"sorts earliest first" '
                                 '| Example and Edge')
        cases = {
            "stands but changed": (["2"], stood, "STANDS", [self.SORT], None,
                                   ("sort.acceptance.test.ts.sealed changed, but it is "
                                    "outside your scope")),
            "repaired, nothing changed": (["2"], repaired, "REPAIRED", [], None,
                                          "condition 2 is ruled repaired, but none"),
            "stood rows edited": (["2"], stood, "STANDS", [], moved,
                                  ("MANIFEST.md's rows for condition 2 changed, though "
                                   "it stands")),
            "no ruling": (["1", "S1"], repaired, "REPAIRED", [self.DUE], None,
                          "has no ruling for P2"),
            "no reason": (["2"], rulings_text(("stands", "none")), "STANDS", [], None,
                          "P1 stands with no reason"),
            "wrong token": (["2"], stood, "REPAIRED", [], None, "which is STANDS"),
        }
        for name, (targets, rulings, nxt, edits, rows, said) in cases.items():
            with self.subTest(name):
                self.refused(self.checks_answer(targets, rulings, nxt, edits, rows), said)
        self.ok(self.checks_answer(["2"], stood, "STANDS"))
        self.ok(self.checks_answer(["2"], repaired, "REPAIRED", [self.SORT]))
        self.ok(self.checks_answer(["2"], repaired, "REPAIRED", rows=moved))
        # A check under conditions 1 and S1: one ruling each; its file may change
        # once either is repaired.
        self.ok(self.checks_answer(["1", "S1"], rulings_text(("repaired", "none"),
                                                      ("stands", self.TESTER_REASON)),
                            "REPAIRED", [self.DUE]))

    def test_a_repair_editing_a_file_outside_the_batch_is_refused(self):
        r = self.checks_answer(["2"], rulings_text(("repaired", "none")), "REPAIRED",
                        [self.SORT, self.DUE])
        self.refused(r, "acceptance/files/src/due.acceptance.test.ts.sealed changed",
                     "outside your scope")

    def test_an_unnamed_item_holds_only_settled_files(self):
        rulings = rulings_text(("repaired", "none"), ("stands", self.TESTER_REASON))
        self.ok(self.checks_answer([None, "2"], rulings, "REPAIRED", [self.DUE]))
        self.refused(self.checks_answer([None, "2"], rulings, "REPAIRED", [self.SORT]),
                     "sort.acceptance.test.ts.sealed changed", "outside your scope")
        self.ok(self.checks_answer([None], rulings_text(("repaired", "none")), "REPAIRED",
                            [self.DUE, self.SORT]))

    def test_a_check_file_quoting_a_stands_reason_is_refused(self):
        reason = "the owner rule must stay strict for every caller of the route"
        rulings = rulings_text(("repaired", "none"), ("stands", reason))
        self.refused(self.checks_answer(["1", "S1"], rulings, "REPAIRED", [
            ("due.acceptance.test.ts", f"// {reason}")]), "repeats P2's stands reason")
        self.ok(self.checks_answer(["1", "S1"], rulings, "REPAIRED", [
            ("due.acceptance.test.ts", "// none")]))

    def test_a_plan_writing_a_stands_reason_around_a_kept_word_is_refused(self):
        batch = [self.STEP_3, self.STEP_5]
        rulings = rulings_text(("applied", "none"),
                               ("stands", "other callers depend on the number form"))
        around = ("3. Make the todo route pass the id to `setDue()` as a string; other "
                  "callers depend on the number form, so keep both — test: "
                  "`src/route.test.ts`")
        self.refused(self.planner(batch, rulings, self.plan_with(s3=around)),
                     "repeats P2's stands reason")

    # The Design line holds two phrases of the stands reason apart.
    APART = PLAN.replace("The store keeps each date as an ISO string beside the title.",
                         "Other callers depend on the stored date; the string form of the "
                         "id is kept for them.")
    JOINED_REASON = "callers depend on the string form of the id"

    def test_a_plan_joining_two_kept_phrases_into_a_stands_reason_is_refused(self):
        batch = [self.STEP_3, self.STEP_5]
        rulings = rulings_text(("applied", "none"), ("stands", self.JOINED_REASON))
        design = ("Other callers depend on the stored date; the string form of the id is "
                  "kept for them.")
        moved = self.APART.replace(design, "Other callers depend on the string form of "
                                   "the id; the stored date is kept for them.")
        self.refused(self.planner(batch, rulings, moved.replace(
            "as a number", "as a string"), base=self.APART), "repeats P2's stands reason")
        deleted = self.APART.replace(design, "Other callers depend on the string form of "
                                     "the id; it is kept for them.")
        self.refused(self.planner(batch, rulings, deleted.replace(
            "as a number", "as a string"), base=self.APART), "repeats P2's stands reason")
        # Quoting one unchanged phrase whole is text the coder could already read.
        whole = rulings_text(("applied", "none"),
                             ("stands", "other callers depend on the stored date"))
        self.ok(self.planner(batch, whole, self.APART.replace("as a number", "as a string"),
                             base=self.APART))

    def test_a_check_file_joining_two_kept_phrases_into_a_stands_reason_is_refused(self):
        reason = "the owner rule must hold for every caller of the route"
        rulings = rulings_text(("repaired", "none"), ("stands", reason))
        self.write("acceptance/files/src/due.acceptance.test.ts.sealed",
                   "test('the owner rule must hold when the id is known')\n"
                   "test('for every caller of the route')\n")
        self.refused(self.checks_answer(["1", "S1"], rulings, "REPAIRED", texts={
            "due.acceptance.test.ts": f"test('{reason}')\n"}), "repeats P2's stands reason")
        self.ok(self.checks_answer(["1", "S1"], rulings, "REPAIRED", edits=[
            ("due.acceptance.test.ts", "test('owner only')")]))

    def test_a_check_file_writing_a_stands_reason_around_a_kept_word_is_refused(self):
        reason = "the owner rule must check every caller of the route"
        rulings = rulings_text(("repaired", "none"), ("stands", reason))
        # The old line is test('due check'): "check" is kept, in the reason's middle.
        self.refused(self.checks_answer(["1", "S1"], rulings, "REPAIRED", texts={
            "due.acceptance.test.ts": f"test('{reason}')\n"}), "repeats P2's stands reason")
        self.ok(self.checks_answer(["1", "S1"], rulings, "REPAIRED", texts={
            "due.acceptance.test.ts": "test('due check')\ntest('owner only')\n"}))

    def test_a_step_a_blocked_line_only_mentions_was_not_stopped(self):
        batch = [step_block(1, "step 5", NEW_5)]
        rulings = rulings_text(("stands", self.REASON))
        stopped = "- step 3: needs the parser that step 5 adds first\n"
        revised_3 = ("3. Make the todo route parse the id with the new parser — test: "
                     "`src/route.test.ts`")
        self.refused(self.planner(batch, rulings, self.plan_with(s3=revised_3, s5=NEW_5),
                                  "PLAN_REVISED", mode="blocked", stopped=stopped),
                     "step 5 changed, though P1")
        self.ok(self.planner(batch, rulings, self.plan_with(s3=revised_3), "PLAN_REVISED",
                             mode="blocked", stopped=stopped))

    # A named batch on condition 3, whose check `due` it shares with condition 5.
    SHARED_MANIFEST = MANIFEST.split("| 1 |")[0] + (
        '| 2 | sorted | `src/sort.acceptance.test.ts` :: "sorts earliest first" | Example | '
        "unit | fail-to-pass | failed: unsorted |\n"
        '| 3 | due date shown | `src/due.acceptance.test.ts` :: "shows the due date" | '
        "Example | integration | fail-to-pass | failed: no field |\n"
        '| 5 | due label | `src/due.acceptance.test.ts` :: "shows the due date" | Edge | '
        "integration | fail-to-pass | failed: no field |\n"
    ) + "\n## Not automatable" + MANIFEST.split("\n## Not automatable")[1]

    def repair_on_3(self, rows=None, new_files=None, base=None):
        """The tester rules condition 3 repaired, appending to its file; `base`
        is MANIFEST.md when it is briefed (SHARED_MANIFEST by default), `rows`
        MANIFEST.md after, `new_files` sealed files it adds. Returns record's
        result."""
        self.write("acceptance/MANIFEST.md", base or self.SHARED_MANIFEST)
        self.write("proposals/checks-1.md", "# Check proposals\n\n## P1\n- Target: "
                   "condition 3\n- From: the coder (coder #1), its P1\n")
        n = self.brief("acceptance-tester", as_mode="repair",
                       scope="ONLY conditions 3: the coder questions their checks",
                       report=f"{self.dir}/proposals/checks-1.md",
                       proposals=f"{self.dir}/proposals/checks-1.md\nRule on it.",
                       rulings_file=f"{self.dir}/proposals/checks-1-rulings.md")
        due = self.dir / "acceptance" / "files" / "src" / "due.acceptance.test.ts.sealed"
        due.write_text(due.read_text() + "test('shows the due date beside the title')\n")
        for rel, text in (new_files or {}).items():
            self.write(f"acceptance/files/{rel}.sealed", text)
        if rows is not None:
            self.write("acceptance/MANIFEST.md", rows)
        self.write("proposals/checks-1-rulings.md", rulings_text(("repaired", "none")))
        self.returned("acceptance-tester", n, next="REPAIRED", checks="1", ambiguous="none")
        return self.cmd("record", "acceptance-tester", n)

    def test_a_named_batch_may_not_add_a_file_for_a_condition_outside_it(self):
        rows = self.SHARED_MANIFEST.replace("\n\n## Not automatable", (
            '\n| 7 | overdue | `src/overdue.acceptance.test.ts` :: "marks it overdue" | '
            "Example | integration | fail-to-pass | failed: no mark |\n\n## Not automatable"))
        r = self.repair_on_3(rows, {"src/overdue.acceptance.test.ts":
                                    "test('marks it overdue')\n"})
        self.refused(r, "acceptance/files/src/overdue.acceptance.test.ts.sealed changed",
                     "outside your scope")

    def test_a_named_batch_may_not_rewrite_the_rows_of_a_condition_outside_it(self):
        rows = self.SHARED_MANIFEST.replace('"sorts earliest first" | Example |',
                                            '"sorts earliest first" | Example and Edge |')
        self.refused(self.repair_on_3(rows), "MANIFEST.md's rows for condition 2 changed")

    def test_a_named_batch_may_rename_a_check_it_shares_with_a_condition_outside_it(self):
        rows = self.SHARED_MANIFEST.replace('"shows the due date"',
                                            '"shows the due date beside the title"')
        self.ok(self.repair_on_3(rows))

    # Condition 5 with a check of its own in condition 3's file.
    LABEL_ROW = ('| 5 | due label | `src/due.acceptance.test.ts` :: "shows the due label" | '
                 "Edge | integration | fail-to-pass | failed: no label |\n")
    LABEL_MANIFEST = SHARED_MANIFEST.split("| 5 |")[0] + LABEL_ROW + (
        "\n## Not automatable" + MANIFEST.split("\n## Not automatable")[1])

    def test_a_named_batch_may_not_delete_the_row_of_a_condition_outside_it(self):
        rows = self.LABEL_MANIFEST.replace(self.LABEL_ROW, "")
        self.refused(self.repair_on_3(rows, base=self.LABEL_MANIFEST),
                     "MANIFEST.md's rows for condition 5 changed")

    def test_a_named_batch_may_not_move_a_row_of_a_condition_outside_it(self):
        rows = self.LABEL_MANIFEST.replace("| 5 | due label |", "| 3 | due label |")
        self.refused(self.repair_on_3(rows, base=self.LABEL_MANIFEST),
                     "MANIFEST.md's rows for condition 5 changed")

    def test_a_named_batch_may_not_add_a_row_for_a_condition_outside_it(self):
        rows = self.LABEL_MANIFEST.replace(self.LABEL_ROW, self.LABEL_ROW + (
            '| 7 | overdue | `src/due.acceptance.test.ts` :: "marks it overdue" | Example | '
            "integration | fail-to-pass | failed: no mark |\n"))
        self.refused(self.repair_on_3(rows, base=self.LABEL_MANIFEST),
                     "MANIFEST.md's rows for condition 7 changed")

    def test_a_named_batch_may_move_its_own_check_into_a_new_file(self):
        rows = self.LABEL_MANIFEST.replace(
            '| 3 | due date shown | `src/due.acceptance.test.ts`',
            '| 3 | due date shown | `src/due_date.acceptance.test.ts`')
        self.ok(self.repair_on_3(rows, {"src/due_date.acceptance.test.ts":
                                        "test('shows the due date')\n"},
                                 base=self.LABEL_MANIFEST))

    def test_an_unnamed_item_may_change_the_row_of_a_condition_the_batch_does_not_name(self):
        rows = MANIFEST.replace('"shows the due date" | Example | integration | '
                                "fail-to-pass | failed: no field |",
                                '"shows the due date" | Example | integration | '
                                "fail-to-pass | not re-run (repair) |")
        self.assertNotEqual(rows, MANIFEST)
        self.ok(self.checks_answer([None], rulings_text(("repaired", "none")), "REPAIRED",
                                   [self.DUE], rows=rows))

    # ------------------------------------------------------------ the log

    def test_owner_records_note_what_they_changed(self):
        self.ok(self.planner([self.STEP_3, self.STEP_5], rulings_text(
            ("applied", "none"), ("stands", self.REASON)), self.plan_with(s3=NEW_3)))
        self.assertEqual(self.state()["log"][-1]["steps_changed"], ["3"])
        self.ok(self.checks_answer(["1", "S1"], rulings_text(("repaired", "none"),
                                                      ("stands", self.TESTER_REASON)),
                            "REPAIRED", [self.DUE]))
        self.assertEqual(self.state()["log"][-1]["checks_changed"], ["1", "S1"])
        self.ok(self.checks_answer(["2"], rulings_text(("stands", self.TESTER_REASON)), "STANDS"))
        self.assertEqual(self.state()["log"][-1]["checks_changed"], [])

    # ------------------------------------------------------------ check-artifact

    def test_check_artifact_reads_the_new_proposal_files(self):
        def check(rel, text):
            return self.cmd("check-artifact", self.write(rel, text))
        self.assertEqual(check("proposals/coder-1.md", coder_file(
            step_block(1, "step 3", NEW_3), check_block(2, SORT_CHECK))).returncode, 0)
        self.refused(check("proposals/coder-2.md", coder_file(step_block(1, "step 9", NEW_3))),
                     "names step 9")
        self.refused(check("proposals/coder-3.md", coder_file(step_block(1, "condition 1",
                                                                        NEW_3))),
                     "may not propose against the spec")
        self.refused(check("proposals/coder-4.md", coder_file(check_block(
            1, '`src/sort.acceptance.test.ts` :: "my own test"'))), "lists as no check")
        self.refused(check("proposals/verifier-5.md", coder_file(check_block(1, DUE_CHECK))),
                     "`next: REPAIR`")
        self.refused(check("proposals/review-judge-6.md", coder_file(step_block(
            1, "step 3", NEW_3))), "may not propose against the plan")
        for name in ("plan-1.md", "checks-1.md"):
            self.assertEqual(check(f"proposals/{name}", coder_file(
                step_block(1, "step 3", NEW_3))).returncode, 0)
            self.refused(check(f"proposals/{name}", "# Plan proposals\n"), "no `## P<k>`")
        self.assertEqual(check("proposals/plan-1-rulings.md", rulings_text(
            ("applied", "none"), ("stands", self.REASON))).returncode, 0)
        self.refused(check("proposals/plan-2-rulings.md", rulings_text(("repaired", "none"))),
                     "must be applied or stands")
        self.assertEqual(check("proposals/checks-1-rulings.md", rulings_text(
            ("repaired", "none"), ("stands", self.TESTER_REASON))).returncode, 0)
        self.refused(check("proposals/checks-2-rulings.md", rulings_text(("applied", "none"))),
                     "must be repaired or stands")
        self.refused(check("proposals/checks-3-rulings.md", rulings_text(("stands", "none"))),
                     "stands with no reason")
        self.assertEqual(check("proposals/snapshots/plan-abc.md", "anything").returncode, 0)


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

    def test_a_plan_review_effort_is_high_or_xhigh_or_absent(self):
        from test_next import IMPLEMENTATION
        title = "# Plan\n"
        for line in ("Review effort: high — one local function",
                     "Review effort: xhigh — a state machine spans three modules",
                     "**Review effort:** `xhigh` — parsing",
                     "- Review effort: high—one rename"):
            r = self.check("IMPLEMENTATION.md", IMPLEMENTATION.replace(
                title, f"{title}\n{line}\n", 1))
            self.assertEqual(r.returncode, 0, line + "\n" + r.stdout)
        for line, found in (("Review effort: max — be thorough", "max"),
                            ("- Review effort: max", "max"),
                            ("Review effort: <high | xhigh> — <reason>", "<high"),
                            ("Review effort:", "nothing")):
            r = self.check("IMPLEMENTATION.md", IMPLEMENTATION.replace(
                title, f"{title}\n{line}\n", 1))
            self.assertEqual(r.returncode, 1, line)
            self.assertIn(f"`Review effort:` must be high or xhigh (found: {found})",
                          r.stdout)

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


CART_CHECK = '`tests/cart.test.ts` :: "rejects an empty cart"'
FILER_WHY = "the change showed this is wrong as written"


def filer_block(target, new_text="none", comment="none"):
    """One proposal in a spec filer's file (templates/PROPOSAL.md's shape)."""
    body = f"\n{new_text}" if new_text != "none" else " none"
    return (f"# Spec proposals\n\n## P1\n- Target: {target}\n- Why: {FILER_WHY}\n"
            f"- Comment: {comment}\n- New text:{body}\n")


class PlanAndCheckProposalRecordTest(WorkCase):
    """`record` on the coder's plan and check proposals, and on other workers'
    proposals aimed at the plan or at a held-out check."""

    def setUp(self):
        super().setUp()
        from test_next import PROPOSAL_MANIFEST, PROPOSAL_SPEC, step_plan
        (self.dir / "SPEC.md").write_text(PROPOSAL_SPEC)
        self.write("acceptance/MANIFEST.md", PROPOSAL_MANIFEST.replace(
            '`src/four.acceptance.test.ts` :: "refuses a past due date"', CART_CHECK))
        self.write("IMPLEMENTATION.md", step_plan())

    def job(self, worker, as_mode=None, **sets):
        args = [a for k, v in sets.items() for a in ("--set", f"{k}={v}")]
        r = self.cmd("brief", worker, *(("--mode", as_mode) if as_mode else ()), *args)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return int(Path(r.stdout.split("BRIEF:")[1].split()[0]).stem.rsplit("-", 1)[1])

    def proposal_file(self, worker, n):
        values = self.brief_values(self.dir / "briefs" / f"{worker}-{n}.md")
        path = values.get("proposal_file", "none")
        return Path(path) if path != "none" else self.dir / "proposals" / f"{worker}-{n}.md"

    def coder_files(self, mode, *blocks):
        """A coder in `mode` returns BUILT with `blocks` in its proposal file."""
        from test_next import coder_proposals
        sets = {}
        if mode == "correction":
            self.write("evidence/corrections.md", CORRECTION)
            sets["corrections_file"] = f"{self.dir}/evidence/corrections.md"
        n = self.job("coder", mode, **sets)
        path = self.proposal_file("coder", n)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(coder_proposals(*blocks))
        self.returned("coder", n, next="BUILT", blocked="0", test_changes="none",
                      proposals=str(len(blocks)))
        return n, self.cmd("record", "coder", n)

    def evaluate(self, partial=("4",), defective="None."):
        """SPEC_EVAL.md with a row per condition of the five-condition spec."""
        from test_next import PROPOSAL_CHECKS
        rule = "|---|-----------|---------|------|----------|\n"
        text = SPEC_EVAL.format(tree="0" * 40, v1="met", v2="met", e2="x",
                                judgment="Justified", defective=defective)
        head, rest = text.split(rule, 1)
        rows = "".join(f"| {cid} | condition {cid} | "
                       f"{'partial' if cid in partial else 'met'} | Strong | "
                       f"acceptance passed (`evidence/C{cid}.txt`) |\n"
                       for cid in PROPOSAL_CHECKS)
        self.write("SPEC_EVAL.md", head + rule + rows + "\n" + rest.split("\n\n", 1)[1])

    def verifier_files(self, text, nxt="CORRECT"):
        n = self.job("verifier", mode="first pass", what_changed="none")
        if nxt == "REPAIR":
            self.evaluate(defective=CART_CHECK)
        else:
            self.evaluate()
            self.write("evidence/corrections.md", CORRECTION)
        self.write(f"proposals/verifier-{n}.md", text)
        self.returned("verifier", n, next=nxt, tree="x",
                      corrections="1" if nxt == "CORRECT" else "0", proposals="1")
        return self.cmd("record", "verifier", n)

    def judge_files(self, text):
        n = self.job("review-judge", "consolidate", reviewers="R1, R2, R3", scope="first",
                     tree="a" * 40)
        no_pending = "\n".join(ln for ln in CODE_REVIEW.splitlines()
                               if not ln.startswith(("| C4", "| C6")))
        self.write("CODE_REVIEW.md", no_pending.format(tree="0" * 40))
        self.write("review/pass-1/corrections.md", "# Required changes\n1. C1: guard "
                   "the null due date in `src/sort.ts:4` before comparing\n")
        self.write(f"proposals/review-judge-{n}.md", text)
        self.returned("review-judge", n, next="MUST_FIX", must_fix_open="1", revote="0",
                      proposals="1")
        return self.cmd("record", "review-judge", n)

    def triager_files(self, mode, text):
        n = self.job("triager", mode, **({"failing": "unit"} if mode == "ci" else {}))
        self.write(f"proposals/triager-{n}.md", text)
        self.returned("triager", n, next="INFRA" if mode == "ci" else "TRIAGED",
                      blockers="0", acceptance_checks="0", triage_file="none",
                      checks_file="none", proposals="1")
        return self.cmd("record", "triager", n)

    def security_files(self, text):
        from test_next import SECURITY_REVIEW
        n = self.job("security-reviewer", leads="none")
        self.write("SECURITY_REVIEW.md", SECURITY_REVIEW.format(tree="0" * 40))
        self.write(f"proposals/security-reviewer-{n}.md", text)
        self.returned("security-reviewer", n, next="CLEAN", must_fix="0", pre_existing="0",
                      proposals="1")
        return self.cmd("record", "security-reviewer", n)

    def refused(self, r, *patterns):
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        for pattern in patterns:
            self.assertRegex(r.stdout, pattern)

    # -------------------------------------------------------------- condition 1

    def test_a_correcting_coder_may_question_a_step_and_a_check_its_brief_listed(self):
        from test_next import STEP_3_NEW, check_proposal, step_proposal
        n, r = self.coder_files("correction", step_proposal(1, {3: STEP_3_NEW}),
                                check_proposal(2, "tests/cart.test.ts", "rejects an empty cart"))
        self.assertIn("tests/cart.test.ts", self.brief_values(
            self.dir / "briefs" / f"coder-{n}.md")["acceptance_paths"])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_a_coder_proposal_naming_a_spec_item_is_refused(self):
        from test_next import NEW_S2, proposal_block
        new_2 = ("2. The list sorts todos by due date with the latest first\n"
                 "   - Example: Given two todos, when listed, then the later one is first.\n"
                 "   - Edge: none — every todo has a place in the order\n"
                 "   - Verify by: integration\n")
        for target, text in (("condition 2", new_2), ("new security criterion", NEW_S2)):
            with self.subTest(target):
                _, r = self.coder_files("correction", proposal_block(1, target, text)
                                        .replace("- Comment: none\n", ""))
                self.refused(r, r"(?i)coder[^\n]*may not[^\n]*spec")

    def test_a_building_coder_was_shown_no_check_to_question(self):
        from test_next import STEP_3_NEW, check_proposal, step_proposal
        _, r = self.coder_files("build", step_proposal(1, {3: STEP_3_NEW}))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        _, r = self.coder_files("build", check_proposal(1, "tests/cart.test.ts",
                                                        "rejects an empty cart"))
        self.refused(r, r"(?i)(shown|listed|given) no (acceptance |held-out )?check")

    def test_a_coder_naming_a_step_the_plan_lacks_hears_the_steps_it_has(self):
        from test_next import STEP_3_NEW, step_proposal
        _, r = self.coder_files("correction", step_proposal(1, {3: STEP_3_NEW}))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        _, r = self.coder_files("correction", step_proposal(
            1, {7: "cache the rendered due column per row"}))
        self.refused(r, r"\b7\b", r"\b1\b\D{0,8}\b2\b\D{0,8}\b3\b\D{0,8}\b4\b\D{0,10}\b5\b"
                              r"|\b1\s*(?:–|-|to)\s*5\b")

    def test_a_coder_proposal_on_two_kinds_or_a_test_that_is_no_check_is_refused(self):
        from test_next import STEP_3_NEW, STEP_6_NEW, check_proposal, step_proposal
        _, r = self.coder_files("correction", check_proposal(
            1, "tests/cart.test.ts", "rejects an empty cart"))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        both = step_proposal(1, {3: STEP_3_NEW}).replace(
            "- Target: step 3", f"- Target: step 3 and check {CART_CHECK}")
        adds_and_changes = step_proposal(1, {3: STEP_3_NEW}).replace(
            "- Target: step 3", "- Target: step 3, new step") + f"6. {STEP_6_NEW}\n"
        cases = {
            "a step and a check at once": (both, r"(?i)step"),
            "a change and an addition at once": (adds_and_changes, r"(?i)add"),
            "one of the coder's own tests": (check_proposal(
                1, "tests/cart.test.ts", "keeps the cart helper tidy"),
                r"(?i)keeps the cart helper tidy|manifest|not a (held-out )?check"),
            "a file the brief did not list": (check_proposal(
                1, "tests/other.test.ts", "rejects an empty cart"), r"tests/other\.test\.ts"),
        }
        for name, (block, pattern) in cases.items():
            with self.subTest(name):
                _, r = self.coder_files("correction", block)
                self.refused(r, pattern)

    # -------------------------------------------------------------- condition 2, S2

    def test_a_verifier_proposal_on_a_plan_step_is_refused(self):
        from test_next import PLAN_STEPS
        r = self.verifier_files(filer_block("step 2", f"2. {PLAN_STEPS[1]} in UTC"))
        self.refused(r, r"(?i)verifier[^\n]*may not[^\n]*plan")

    def test_a_verifier_spec_proposal_records_beside_its_check_repair(self):
        from test_next import NEW_3, proposal_block, proposals
        r = self.verifier_files(proposals(proposal_block(1, "condition 3", NEW_3)), "REPAIR")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_a_proposal_file_aimed_at_a_check_names_the_filer_s_own_route(self):
        on_check = filer_block('check `src/two.acceptance.test.ts` :: "sorts earliest first"')
        self.refused(self.verifier_files(on_check), r"REPAIR")
        self.refused(self.judge_files(on_check), r"acceptance-check")
        self.refused(self.triager_files("human", on_check.replace(
            "- Comment: none", "- Comment: 12345")), r"ACCEPTANCE_CHECK")

    def test_workers_that_may_not_file_hear_who_files_what(self):
        from test_next import PLAN_STEPS
        on_check = filer_block('check `src/two.acceptance.test.ts` :: "sorts earliest first"')
        on_step = filer_block("step 2", f"2. {PLAN_STEPS[1]} in UTC")
        self.refused(self.triager_files("ci", on_check), r"(?i)coder")
        self.refused(self.triager_files("ci", on_step), r"(?i)coder")
        n = self.job("plan-reviewer")
        self.write(f"proposals/plan-reviewer-{n}.md", on_step)
        self.returned("plan-reviewer", n, next="CLEAN", blockers="0", fix_file="none",
                      proposals="1")
        self.refused(self.cmd("record", "plan-reviewer", n), r"(?i)coder")

    def test_a_verifier_spec_proposal_accepted_before_is_still_accepted(self):
        from test_next import NEW_3, proposal_block, proposals
        r = self.verifier_files(proposals(proposal_block(1, "condition 3", NEW_3)))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_a_security_reviewer_may_not_propose_against_the_plan_or_a_check(self):
        from test_next import PLAN_STEPS
        r = self.security_files(filer_block("step 2", f"2. {PLAN_STEPS[1]} in UTC"))
        self.refused(r, r"(?i)\bplan\b")
        r = self.security_files(filer_block(
            'check `src/two.acceptance.test.ts` :: "sorts earliest first"'))
        self.refused(r, r"(?i)\bcheck\b")


class SpecFilerTargetTest(WorkCase):
    """A spec filer's Target is the plan's only when it names steps in the
    plan's form; numbers that stand alone name conditions, as on 4.11."""

    job = PlanAndCheckProposalRecordTest.job
    evaluate = PlanAndCheckProposalRecordTest.evaluate
    verifier_files = PlanAndCheckProposalRecordTest.verifier_files
    refused = PlanAndCheckProposalRecordTest.refused

    def setUp(self):
        super().setUp()
        from test_next import PROPOSAL_MANIFEST, PROPOSAL_SPEC, step_plan
        (self.dir / "SPEC.md").write_text(PROPOSAL_SPEC)
        self.write("acceptance/MANIFEST.md", PROPOSAL_MANIFEST.replace(
            '`src/four.acceptance.test.ts` :: "refuses a past due date"', CART_CHECK))
        self.write("IMPLEMENTATION.md", step_plan())

    def test_a_verifier_target_whose_numbers_stand_alone_names_conditions(self):
        from test_next import NEW_2, NEW_3, PLAN_STEPS, proposal_block, proposals
        for target, text in (("3 (the wizard's address step)", NEW_3),
                             ("2, 3: the steps of the checkout", NEW_2 + NEW_3)):
            with self.subTest(target):
                r = self.verifier_files(proposals(proposal_block(1, target, text)))
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertEqual(self.state()["log"][-1]["data"]["proposals"], "1")
        r = self.verifier_files(filer_block("step 2", f"2. {PLAN_STEPS[1]} in UTC"))
        self.refused(r, r"P1 names a plan step: the verifier may not propose against the plan")


class MovedCloneCase(WorkCase):
    """A run whose clone lies under the folders NEST inside the temp dir."""

    NEST = ()

    def init(self, *extra, **kw):
        if self.NEST and self.repo.parent == self.tmp:
            nest = self.tmp.joinpath(*self.NEST)
            nest.mkdir(parents=True)
            self.repo = nest / "app"
            self.sh("git", "clone", "-q", str(self.tmp / "origin.git"), str(self.repo))
            self.worktree = nest / "app-due-dates"
            self.dir = self.worktree / ".auto-dev"
        return super().init(*extra, **kw)


class ProposalsSnapshotsInTheClonePathTest(MovedCloneCase):
    """A clone under folders named proposals/snapshots is no snapshot."""

    NEST = ("proposals", "snapshots")
    brief = SpecProposalRecordTest.brief
    refused = SpecProposalRecordTest.refused

    def test_a_plan_missing_a_heading_is_still_refused(self):
        self.assertIn("proposals/snapshots/app-due-dates/.auto-dev", str(self.dir))
        path = self.write("IMPLEMENTATION.md", PLAN.replace("## Data flow", "## Flow"))
        self.refused(self.cmd("check-artifact", path), "headings must be")
        n = self.brief("planner", as_mode="write")
        self.returned("planner", n, next="WRITTEN", entry_points_changed="no")
        self.refused(self.cmd("record", "planner", n), "headings must be")
        # The run's own snapshot folder is still exempt.
        snap = self.write("proposals/snapshots/plan-abc.md", "anything")
        self.assertEqual(self.cmd("check-artifact", snap).returncode, 0)


class SpacedArtifactDirTest(MovedCloneCase):
    """A run whose artifact dir's path holds a space."""

    NEST = ("my repos",)
    refused = SpecProposalRecordTest.refused
    ok = UpstreamProposalRecordTest.ok
    planner = UpstreamProposalRecordTest.planner
    plan_with = UpstreamProposalRecordTest.plan_with

    def brief(self, worker, as_mode=None, **sets):
        args = [a for k, v in sets.items() for a in ("--set", f"{k}={v}")]
        r = self.cmd("brief", worker, *(("--mode", as_mode) if as_mode else ()), *args)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        path = re.search(r"^BRIEF: (.*\.md)", r.stdout, re.M).group(1)
        return int(Path(path).stem.rsplit("-", 1)[1])

    def test_a_blocked_answer_may_revise_a_stopped_step_a_stood_proposal_names(self):
        self.assertIn(" ", str(self.dir))
        self.write("IMPLEMENTATION.md", PLAN)
        batch = [step_block(1, "step 3", NEW_3)]
        rulings = rulings_text(("stands", UpstreamProposalRecordTest.REASON))
        revised = ("3. Make the todo route look the todo up by its key first — test: "
                   "`src/route.test.ts`")
        self.ok(self.planner(batch, rulings, self.plan_with(s3=revised), "PLAN_REVISED",
                             mode="blocked", stopped="- step 3: the store has no lookup\n"))
