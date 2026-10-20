"""Tests for autodev.py brief / record / check-artifact.

Run: python3 -m unittest discover -s tests -v   (from the repo root)
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_autodev import RunCase
from test_parsers import FIXTURES, MANIFEST, SPEC, SPEC_EVAL


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

    def returned(self, worker, n, **data):
        path = self.dir / "returns" / f"{worker}-{n}.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps({"worker": worker, "status": "ok", **data}))


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

    def test_profiler_brief_needs_no_run(self):
        out = self.tmp / "prof"
        r = self.autodev("brief", "profiler", "--out", out, "--set", f"repo={self.repo}",
                         "--set", "base=main", "--set", f"draft_path={out}/p.yml")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((out / "profiler-1.md").exists())


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
        self.returned("triager", 1, next="TRIAGED", blockers="1", acceptance_checks="0")
        r = self.cmd("record", "triager", "1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("human-1.md holds no required change", r.stdout)
        (self.dir / "triage" / "human-1.md").write_text(
            "# Required changes\n1. c-77: keep the field name when it is empty\n")
        self.assertEqual(self.cmd("record", "triager", "1").returncode, 0)

    def test_cleanup_green_needs_passing_reports(self):
        (self.dir / "lint").mkdir(exist_ok=True)
        (self.dir / "lint" / "TEST.md").write_text("# TEST — fail\n")
        self.returned("cleanup", 1, next="GREEN")
        self.assertEqual(self.cmd("record", "cleanup", "1").returncode, 1)
        (self.dir / "lint" / "TEST.md").write_text("# TEST — pass\n\n- **Tree:** abc\n")
        self.assertEqual(self.cmd("record", "cleanup", "1").returncode, 0)

    def test_a_malformed_return_is_refused(self):
        self.returned("coder", 1, next="DONE", blocked="0")
        r = self.cmd("record", "coder", "1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("MALFORMED", r.stderr)
        r = self.cmd("record", "coder", "2")
        self.assertIn("MISSING", r.stderr)


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
