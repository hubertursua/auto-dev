"""Tests for tools/check-repo.py, the check that the repo's files agree."""

import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
TOOL = ROOT_DIR / "tools" / "check-repo.py"


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
        errors = self.check_agent_text("Spill output to `$TMPDIR`.\nThen `echo $? > x`.\n"
                                       "Or `cat ${W}/a`.\nOr `echo $1`.\n")
        self.assertEqual(len(errors), 4, errors)
        self.assertTrue(all("a shell variable" in e for e in errors), errors)

    def check_files(self, files):
        tool = load_tool()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            for name, text in files.items():
                (root / name).parent.mkdir(parents=True, exist_ok=True)
                (root / name).write_text(text, encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "tracked.md"], check=False)
            tool.check_personal_paths(root)
        return tool.errors

    def test_paths_a_tool_fixes_pass(self):
        text = ("ln -s /path/to/auto-dev/agents ~/.claude/agents\n"
                "Save to `~/.config/auto-dev/profiles` or `~/…`; see /usr/home/x.\n"
                "Or `$HOME/.config`, and https://example.com/home/page.\n")
        self.assertEqual(self.check_files({"tracked.md": text}), [])

    def test_a_personal_path_fails_in_tracked_and_untracked_files(self):
        # Built from parts so this file doesn't trip the check itself.
        home = "/Users" + "/alice/auto-dev"
        errors = self.check_files({
            "tracked.md": "ln -s ~" + "/Dev/auto-dev/agents ~/.claude/agents\n",
            "docs/new.md": "x\nclone into /home" + "/bob/src\n",
            "a.py": f"ROOT = '{home}'\nWIN = r'C:\\Users" + "\\carol'\n"
                    "FWD = 'C:/Users" + "/dan'\nENV = '$HOME" + "/src'\n",
        })
        self.assertEqual(len(errors), 6, errors)
        self.assertIn("names /Users" + "/alice,", errors[0])
        for where in ("tracked.md:1:", "docs/new.md:2:", "a.py:1:", "a.py:2:", "a.py:3:",
                      "a.py:4:"):
            self.assertTrue(any(e.startswith(where) for e in errors), (where, errors))

    def test_an_ignored_file_is_not_checked(self):
        errors = self.check_files({".gitignore": "*.local.md\n",
                                   "plan.local.md": "/Users" + "/alice\n"})
        self.assertEqual(errors, [])

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

    def copy_of_the_repo(self, tmp):
        """The repo's files (not its history) in `tmp`, as a git repo of its own."""
        copy = Path(tmp) / "repo"
        shutil.copytree(TOOL.parent.parent, copy, ignore=shutil.ignore_patterns(
            ".git", ".auto-dev", "__pycache__", ".ruff_cache"))
        subprocess.run(["git", "init", "-q", str(copy)], capture_output=True, check=True)
        return copy

    def test_a_result_token_or_template_the_repo_lacks_fails_the_check_naming_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = self.copy_of_the_repo(tmp)
            tool = copy / "tools" / "check-repo.py"
            define = copy / "agents" / "define.md"
            text = define.read_text(encoding="utf-8")

            def run():
                return subprocess.run([sys.executable, str(tool)], capture_output=True,
                                      text=True, check=False)

            result = run()
            self.assertEqual(result.returncode, 0, result.stdout)  # the copy passes as it is
            define.write_text(re.sub(r"(```auto-dev-result\n(?:.*\n)*?next: [^\n]*)",
                                     r"\1 | WITHDRAWN", text, count=1), encoding="utf-8")
            result = run()
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn("WITHDRAWN", result.stdout)
            define.write_text(text + "\nWrite your answer to `templates/NO-SUCH-RULINGS.md`.\n",
                              encoding="utf-8")
            result = run()
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn("NO-SUCH-RULINGS.md", result.stdout)

    def test_the_release_is_4_12_with_notes_on_upgrading_from_4_11(self):
        root = TOOL.parent.parent
        plugin = json.loads((root / ".claude-plugin" / "plugin.json").read_text("utf-8"))
        self.assertEqual(plugin["version"], "4.12.0")
        upgrading = (root / "UPGRADING.md").read_text(encoding="utf-8")
        first = re.search(r"^## (.*)$", upgrading, re.MULTILINE)
        self.assertEqual(first.group(1).strip(), "Upgrading from 4.11")
        section = re.search(r"^## Upgrading from 4\.11\b.*?(?=^## |\Z)", upgrading,
                            re.MULTILINE | re.DOTALL)
        self.assertRegex(section.group(0), r"(?i)resum")

    def check_agents_dir(self, files):
        tool = load_tool()
        with tempfile.TemporaryDirectory() as tmp:
            for name, text in files.items():
                (Path(tmp) / name).write_text(text, encoding="utf-8")
            tool.check_briefs(Path(tmp))
        return tool.errors

    def test_an_unknown_define_token_or_missing_template_fails_the_repo_check(self):
        agents = ROOT_DIR / "agents"
        define = (agents / "define.md").read_text(encoding="utf-8")
        self.assertIn("| REVISED | STANDS\n", define)
        errors = self.check_agents_dir({"define.md": define.replace(
            "| REVISED | STANDS\n", "| REVISED | STANDS | SHRUGGED\n", 1)})
        self.assertTrue(any("define.md" in e and "SHRUGGED" in e for e in errors), errors)
        errors = self.check_agents_dir({"define.md": define + "\nSee templates/NOPE.md.\n"})
        self.assertTrue(any("templates/NOPE.md" in e for e in errors), errors)
        errors = self.check_agents_dir({"define.md": define})
        self.assertFalse(any(e.startswith("agents/define.md") for e in errors), errors)


if __name__ == "__main__":
    unittest.main()
