"""Tests for autodev.py's artifact parsers (check-manifest, eval-status,
apply-fix, spec-overlap, votes, review-scope, gate-summary).

Run: python3 -m unittest discover -s tests -v   (from the repo root)

Fixture artifacts are in tests/fixtures/parsers/ and follow the templates in
references/artifacts.md. Examples are in TypeScript, as CLAUDE.md asks.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_autodev import AUTODEV, SCRIPTS, RunCase

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "parsers"

SPEC = (FIXTURES / "SPEC.md").read_text()

MANIFEST = (FIXTURES / "MANIFEST.md").read_text()

BASE_RUNS = {
    "C1.txt": "Commit: abc\nCommand: npx vitest run\nResult: shows the due date: failed: no field\n"
              "rejects an invalid date: failed: got 200\nOutput:\n x\n",
    "C2.txt": "Commit: abc\nCommand: npx vitest run\nResult: sorts earliest first: failed: "
              "unsorted\nOutput:\n x\n",
    "CS1.txt": "Commit: abc\nCommand: npx vitest run\nResult: owner only: failed: 200\n"
               "Output:\n x\n",
}

SPEC_EVAL = (FIXTURES / "SPEC_EVAL.md").read_text()

CODE_REVIEW = (FIXTURES / "CODE_REVIEW.md").read_text()

SECURITY_REVIEW = (FIXTURES / "SECURITY_REVIEW.md").read_text()


def autodev(*args, cwd=None, env=None):
    return subprocess.run([sys.executable, str(AUTODEV), *map(str, args)],
                          capture_output=True, text=True, cwd=cwd, env=env, check=False)


class ArtifactCase(unittest.TestCase):
    """A worktree-like folder with .auto-dev/ holding the fixture artifacts."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", str(self.tmp)], check=False))
        self.dir = self.tmp / ".auto-dev"
        acc = self.dir / "acceptance"
        (acc / "base-run").mkdir(parents=True)
        (self.dir / "SPEC.md").write_text(SPEC)
        (acc / "MANIFEST.md").write_text(MANIFEST)
        for name, text in BASE_RUNS.items():
            (acc / "base-run" / name).write_text(text)
        for path in ("src/due.acceptance.test.ts", "src/sort.acceptance.test.ts"):
            sealed = acc / "files" / f"{path}.sealed"
            sealed.parent.mkdir(parents=True, exist_ok=True)
            sealed.write_text("test")

    def cmd(self, *args):
        return autodev(*args, "--dir", self.dir)

    def write(self, rel, text):
        path = self.dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def spec_eval(self, v1="met", v2="met", e2="ran the sort", judgment="Justified",
                  defective="None."):
        self.write("SPEC_EVAL.md", SPEC_EVAL.format(tree="0" * 40, v1=v1, v2=v2, e2=e2,
                                                    judgment=judgment, defective=defective))


class CheckManifestTest(ArtifactCase):
    def test_complete_manifest_passes(self):
        r = self.cmd("check-manifest")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("OK: 3 condition(s)", r.stdout)

    def test_each_gap_is_named(self):
        manifest = MANIFEST.replace(
            '| 1 | due date shown | `src/due.acceptance.test.ts` :: "rejects an invalid date" '
            '| Edge | integration | fail-to-pass | failed: 200 |\n', "")
        manifest = manifest.replace("| owner only | `src/due.acceptance.test.ts` :: \"owner "
                                    "only\" | Example | integration |",
                                    "| owner only | `src/due.acceptance.test.ts` :: \"owner "
                                    "only\" | Example | unit |")
        self.write("acceptance/MANIFEST.md", manifest)
        (self.dir / "acceptance" / "base-run" / "C2.txt").unlink()
        (self.tmp / "src").mkdir()
        (self.tmp / "src" / "sort.acceptance.test.ts").write_text("left behind")
        r = self.cmd("check-manifest")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("1: its Edge has no check", r.stdout)
        self.assertIn("S1: a check is unit, below Verify by integration", r.stdout)
        self.assertIn("2: no base-run/C2.txt", r.stdout)
        self.assertIn("still in the worktree", r.stdout)
        self.assertIn("respawn: 1, 2, S1", r.stdout)

    def test_a_pass_to_pass_check_must_have_passed(self):
        self.write("acceptance/MANIFEST.md", MANIFEST.replace(
            "| Example | unit | fail-to-pass | failed: unsorted |",
            "| Example | unit | pass-to-pass | failed: unsorted |"))
        r = self.cmd("check-manifest")
        self.assertEqual(r.returncode, 1)
        self.assertIn("pass-to-pass but did not pass", r.stdout)

    def test_missing_spec_cannot_run(self):
        (self.dir / "SPEC.md").unlink()
        self.assertEqual(self.cmd("check-manifest").returncode, 2)


class EvalStatusTest(ArtifactCase):
    def test_all_met(self):
        self.spec_eval()
        r = self.cmd("eval-status")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(r.stdout.startswith("ALL_MET"), r.stdout)
        self.assertIn("survivor: M2", r.stdout)

    def test_unmet_and_unjustified_are_corrections(self):
        self.spec_eval(v1="unmet", judgment="Unjustified")
        r = self.cmd("eval-status")
        self.assertTrue(r.stdout.startswith("CORRECT"), r.stdout)
        self.assertIn("condition 1 unmet", r.stdout)
        self.assertIn("integrity REMOVED_ASSERTION", r.stdout)

    def test_partial_only_from_a_defective_check_is_a_repair(self):
        self.spec_eval(v2="partial", e2="its only check is defective (too weak)",
                       defective="`src/sort.acceptance.test.ts` too weak for its Edge")
        r = self.cmd("eval-status")
        self.assertTrue(r.stdout.startswith("REPAIR"), r.stdout)
        self.assertIn("repair: 2", r.stdout)

    def test_mutation_left_changes_stops(self):
        r = self.cmd("eval-status", "--mutation-left-changes")
        self.assertTrue(r.stdout.startswith("STOP"), r.stdout)

    def test_a_missing_condition_row_is_malformed(self):
        self.spec_eval()
        path = self.dir / "SPEC_EVAL.md"
        path.write_text("\n".join(ln for ln in path.read_text().splitlines()
                                  if not ln.startswith("| S1 |")))
        r = self.cmd("eval-status")
        self.assertEqual(r.returncode, 1)
        self.assertIn("no row for condition(s) S1", r.stderr)


class ApplyFixTest(ArtifactCase):
    def fix(self, old, new, fix_id="1"):
        return self.write("fix.md", f"FIX {fix_id}\n<<<<<<< OLD\n{old}\n=======\n{new}\n"
                                    ">>>>>>> NEW\n")

    def test_applies_an_exact_match(self):
        self.fix("   - Edge: an invalid date is rejected → 400",
                 "   - Edge: a due date of 2026-02-30 is rejected → 400")
        r = self.cmd("apply-fix", self.dir / "SPEC.md", self.dir / "fix.md")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("2026-02-30 is rejected", (self.dir / "SPEC.md").read_text())

    def test_an_ambiguous_block_writes_nothing(self):
        self.fix("   - Verify by: integration", "   - Verify by: end-to-end")
        r = self.cmd("apply-fix", self.dir / "SPEC.md", self.dir / "fix.md")
        self.assertEqual(r.returncode, 1)
        self.assertIn("found 2 times", r.stdout)
        self.assertEqual((self.dir / "SPEC.md").read_text(), SPEC)


class SpecOverlapTest(ArtifactCase):
    def test_copied_wording_is_refused(self):
        brief = self.write("brief.md", "Fix it so the list sorts todos by due date with "
                                       "the earliest first.")
        r = self.cmd("spec-overlap", brief)
        self.assertEqual(r.returncode, 1)
        self.assertIn("condition 2", r.stdout)

    def test_concrete_behavior_passes(self):
        brief = self.write("brief.md", "In src/todos/list.ts, order the array returned by "
                                       "listTodos() ascending by dueAt; add a unit test.")
        self.assertEqual(self.cmd("spec-overlap", brief).returncode, 0)


class VotesTest(ArtifactCase):
    def setUp(self):
        super().setUp()
        self.write("CODE_REVIEW.md", CODE_REVIEW.format(tree="0" * 40))
        for k in (1, 2, 3):
            self.write(f"review/pass-1/R{k}.md", f"# Code review R{k}\n\n## Findings\nnone\n")

    def test_plan_names_each_slot_that_did_not_raise_the_finding(self):
        r = self.cmd("votes", "--plan")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("spawn: R1: C6", r.stdout)
        self.assertIn("spawn: R2: C4", r.stdout)
        self.assertIn("spawn: R3: C4, C6", r.stdout)

    def test_a_failed_slot_never_votes(self):
        (self.dir / "review" / "pass-1" / "R3.md").unlink()
        r = self.cmd("votes", "--plan")
        self.assertNotIn("R3", r.stdout)

    def test_apply_moves_findings_and_recounts(self):
        table = "| Finding | Vote | Reason |\n|---|---|---|\n"
        self.write("review/pass-1/VOTES-R1.md", table + "| C6 | disagree | schema rejects it |\n")
        self.write("review/pass-1/VOTES-R2.md", table + "| C4 | agree | unguarded |\n")
        self.write("review/pass-1/VOTES-R3.md", table + "| C4 | disagree | guarded |\n"
                                                        "| C6 | disagree | fine |\n")
        r = self.cmd("votes", "--apply")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        text = (self.dir / "CODE_REVIEW.md").read_text()
        self.assertIn("| C4 | empty list indexed | `src/list.ts:42` | correctness | 2/3 "
                      "(re-vote) | Medium | open |", text)
        self.assertIn("| C6 | blank title saved | `src/save.ts:18` | tests | 1/3 (re-vote) "
                      "| Low |", text)
        self.assertIn("**Overall confidence: Medium**", text)
        self.assertIn("must-fix decided 2–1: C4", text)
        self.assertIn("Must-fix: 2 open · 0 fixed   ·   Advisory: 1", text)
        pending = text.split("## Pending re-vote")[1].split("## Advisory")[0]
        self.assertNotIn("C4", pending)

    def test_apply_refuses_a_missing_vote(self):
        r = self.cmd("votes", "--apply")
        self.assertEqual(r.returncode, 1)
        self.assertIn("no re-vote recorded", r.stderr)


class ReviewAndGateTest(RunCase):
    def setUp(self):
        super().setUp()
        self.assertEqual(self.init().returncode, 0)
        for name, text in (("SPEC.md", SPEC), ("acceptance/MANIFEST.md", MANIFEST)):
            path = self.dir / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)

    def cmd(self, *args):
        return self.autodev(*args, "--dir", self.dir)

    def tree(self):
        return subprocess.run([sys.executable, str(SCRIPTS / "check-fresh.py"),
                               "--print-tree", self.worktree], capture_output=True,
                              text=True, check=True).stdout.strip()

    def reports(self, judgment="Justified"):
        tree = self.tree()
        (self.dir / "lint").mkdir(exist_ok=True)
        (self.dir / "lint" / "TEST.md").write_text(f"# TEST — pass\n\n- **Tree:** {tree}\n")
        (self.dir / "SPEC_EVAL.md").write_text(SPEC_EVAL.format(
            tree=tree, v1="met", v2="met", e2="ran the sort", judgment=judgment,
            defective="None."))
        (self.dir / "CODE_REVIEW.md").write_text(CODE_REVIEW.format(tree=tree))
        (self.dir / "SECURITY_REVIEW.md").write_text(SECURITY_REVIEW.format(tree=tree))

    def test_review_scope_snapshot_and_files(self):
        (self.worktree / "due.ts").write_text("export const due = 1;\n")
        r = self.cmd("review-scope", "--snapshot")
        self.assertEqual(r.returncode, 0, r.stderr)
        snap = self.state()["phase6"]["snapshot"]
        (self.worktree / "app.ts").write_text("export const one = 2;\n")
        r = self.cmd("review-scope", "--snapshot")
        self.assertIn("KEPT", r.stdout)  # one snapshot per pending correction
        r = self.cmd("review-scope", "--files")
        self.assertIn("file: app.ts", r.stdout)
        self.assertNotIn("due.ts", r.stdout)
        self.assertEqual(self.state()["phase6"]["snapshot"], snap)
        self.cmd("review-scope", "--clear")
        self.assertEqual(self.cmd("review-scope", "--files").returncode, 1)

    def test_next_pass_counts_up(self):
        self.assertIn("PASS: 1", self.cmd("review-scope", "--next-pass").stdout)
        self.assertIn("PASS: 2", self.cmd("review-scope", "--next-pass").stdout)
        self.assertTrue((self.dir / "review" / "pass-2").is_dir())

    def test_pr_gate_summary_and_triage_question(self):
        (self.worktree / "app.ts").write_text("export const one = 2;\n")
        self.reports()
        r = self.cmd("gate-summary", "pr", "--json")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        out = json.loads(r.stdout)
        summary = "\n".join(out["summary"])
        self.assertIn("Acceptance — 3 met (2 Strong, 1 Adequate)", summary)
        self.assertIn("Test changes: 1 justified", summary)
        self.assertIn("S2 (Medium) `src/auth.ts:88`", summary)
        self.assertEqual([q["header"] for q in out["questions"]], ["Gate", "S2"])
        self.assertEqual(out["questions"][0]["options"][0]["label"], "Open PR")

    def test_pr_gate_refuses_stale_results_and_open_integrity_findings(self):
        self.reports()
        (self.worktree / "app.ts").write_text("export const one = 5;\n")
        r = self.cmd("gate-summary", "pr")
        self.assertEqual(r.returncode, 1)
        self.assertIn("stale", r.stderr)
        self.reports(judgment="Unjustified")
        r = self.cmd("gate-summary", "pr")
        self.assertEqual(r.returncode, 1)
        self.assertIn("Unjustified", r.stderr)

    def test_main_gate_refuses_a_draft(self):
        self.script_gh([{"args": ["pr", "view"], "stdout": json.dumps(
            {"state": "OPEN", "isDraft": True, "headRefOid": "a" * 40})}])
        r = self.cmd("gate-summary", "main", "--pr", "7")
        self.assertEqual(r.returncode, 1)
        self.assertIn("draft", r.stderr)


if __name__ == "__main__":
    unittest.main()
