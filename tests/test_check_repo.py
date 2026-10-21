"""Tests for tools/check-repo.py, the check that the repo's files agree."""

import importlib.util
import json
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

TOOL = Path(__file__).resolve().parent.parent / "tools" / "check-repo.py"


def load_tool():
    spec = importlib.util.spec_from_file_location("check_repo", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CheckRepoTest(unittest.TestCase):
    def test_repo_passes(self):
        result = subprocess.run([sys.executable, str(TOOL)],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stdout)

    def check_evals(self, evals):
        tool = load_tool()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "evals.json"
            path.write_text(json.dumps(evals), encoding="utf-8")
            tool.check_eval_paths(path)
        return tool.errors

    def test_eval_path_in_setup_that_exists_passes(self):
        evals = {"evals": [{"setup": "Copy evals/files/resume-s2/state.json over it.",
                            "files": ["evals/files/resume-s2/WORK_LOG.md"]}]}
        self.assertEqual(self.check_evals(evals), [])

    def test_missing_eval_path_fails_wherever_it_is_named(self):
        evals = {"notes": "See skills/auto-dev/evals/files/gone/notes.md.",
                 "evals": [{"setup": "Copy evals/files/resume-s2/missing.json.",
                            "expectations": ["Reads evals/files/no-such-dir/."]}]}
        errors = self.check_evals(evals)
        self.assertEqual(len(errors), 3, errors)
        for ref in ("evals/files/gone/notes.md", "evals/files/resume-s2/missing.json",
                    "evals/files/no-such-dir"):
            self.assertTrue(any(f"names {ref}," in e for e in errors), (ref, errors))

    def check_agent_text(self, text):
        tool = load_tool()
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "coder.md").write_text(text, encoding="utf-8")
            tool.check_agent_commands(Path(tmp))
        return tool.errors

    def test_plain_agent_commands_pass(self):
        text = ("Run `git -C {{worktree}} diff {{cut}}`, never `cd <path> && git …`\n"
                "and no `$(…)`. Then `cd {{worktree}} && npm test > {{artifact_dir}}/tmp/t`.\n")
        self.assertEqual(self.check_agent_text(text), [])

    def test_subshell_and_cd_prefix_in_an_agent_fail(self):
        errors = self.check_agent_text(
            "Run `git diff $(git merge-base origin/main HEAD)`.\n"
            "Or `cd {{worktree}} && git diff HEAD`.\n")
        self.assertEqual(len(errors), 2, errors)
        self.assertIn("coder.md:1: gives a `$(…)` substitution", errors[0])
        self.assertIn("coder.md:2: gives a `cd … && git` prefix", errors[1])

    def test_a_shell_variable_in_an_agent_fails(self):
        errors = self.check_agent_text("Spill output to `$TMPDIR`.\nThen `echo $? > x`.\n")
        self.assertEqual(len(errors), 2, errors)
        self.assertTrue(all("a shell variable" in e for e in errors), errors)

    def check_frontmatter(self, frontmatter):
        tool = load_tool()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "SKILL.md"
            path.write_text(f"---\nname: x\n{frontmatter}\n---\n\n# x\n",
                            encoding="utf-8")
            tool.check_skill_description(path)
        return tool.errors

    def check_description(self, length):
        description = ("word " * length)[:length - 1] + "."
        folded = textwrap.indent(textwrap.fill(description, 76), "  ")
        return self.check_frontmatter(f"description: >-\n{folded}")

    def test_description_at_the_limit_passes(self):
        self.assertEqual(self.check_description(1024), [])

    def test_description_over_the_limit_fails(self):
        errors = self.check_description(1025)
        self.assertEqual(len(errors), 1)
        self.assertIn("1025 characters", errors[0])

    def test_description_is_read_as_yaml_reads_it(self):
        tool = load_tool()
        cases = {
            "description: >-\n  one two\n  three\n\n  four": "one two three\nfour",
            "description: >\n  one\n  two": "one two\n",
            "description: 'it''s one line'": "it's one line",
            'description: "one line"': "one line",
            "description: plain line": "plain line",
        }
        for frontmatter, want in cases.items():
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "SKILL.md"
                path.write_text(f"---\n{frontmatter}\nname: x\n---\n", encoding="utf-8")
                self.assertEqual(tool.skill_description(path), want, frontmatter)

    def test_unreadable_or_missing_description_fails(self):
        for frontmatter in ("description: >+\n  kept", "description: |\n  literal",
                            "description: >2-\n  indented", "description: >-  # note\n  x",
                            "description: plain\n  continued", "description:\n  next line",
                            "summary: no description"):
            errors = self.check_frontmatter(frontmatter)
            self.assertEqual(len(errors), 1, frontmatter)
            self.assertIn("no description this check can read", errors[0])


if __name__ == "__main__":
    unittest.main()
