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
        evals = {"evals": [{"setup": "Copy evals/files/resume-build/state.json over it.",
                            "files": ["evals/files/resume-build/WORK_LOG.md"]}]}
        self.assertEqual(self.check_evals(evals), [])

    def test_missing_eval_path_fails_wherever_it_is_named(self):
        evals = {"notes": "See skills/auto-dev/evals/files/gone/notes.md.",
                 "evals": [{"setup": "Copy evals/files/resume-build/missing.json.",
                            "expectations": ["Reads evals/files/no-such-dir/."]}]}
        errors = self.check_evals(evals)
        self.assertEqual(len(errors), 3, errors)
        for ref in ("evals/files/gone/notes.md", "evals/files/resume-build/missing.json",
                    "evals/files/no-such-dir"):
            self.assertTrue(any(f"names {ref}," in e for e in errors), (ref, errors))

    def test_runbook_setup_check_flags_setup_commands(self):
        tool = load_tool()
        tool.check_runbook_setup()  # the repo's own plan.md and SKILL.md
        self.assertEqual(tool.errors, [])
        for line in ("Run `autodev.py init --repo <repo> --slug <slug>`.",
                     "Then run `autodev.py init --continue <tree>`.",
                     "Run `python3 <skill-dir>/scripts/profile-path.py <repo>`.",
                     "Run `validate-config.py --profile <path>`.",
                     "`autodev.py brief profiler --out <tmp>`",
                     "`autodev.py brief lookup --out <tmp>`"):
            with self.subTest(line=line):
                tool = load_tool()
                with tempfile.TemporaryDirectory() as tmp:
                    path = Path(tmp) / "plan.md"
                    path.write_text(f"# Plan\n\n{line}\n", encoding="utf-8")
                    tool.check_runbook_setup([path])
                self.assertEqual(len(tool.errors), 1, tool.errors)
                self.assertIn("plan.md:3", tool.errors[0])

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

    def test_an_agent_asking_for_a_prose_summary_fails(self):
        errors = self.check_agent_text(
            "Write PLAN.md.\nReturn: assumptions, key risks.\n"
            "Do NOT modify code. Return: your votes, one line each.\n"
            "Return a structured summary:\nReturn the findings.\nSay what you changed.\n"
            "Report what changed, TEST CHANGES and BLOCKED.\n"
            "Return `deviations: <k>`, and return `next: STANDS`.\n")
        self.assertEqual([e.split(": asks")[0] for e in errors],
                         [f"coder.md:{n}" for n in range(2, 8)], errors)

    def test_a_worker_whose_reply_is_read_may_ask_for_one(self):
        tool = load_tool()
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("profiler.md", "lookup.md", "triager.md"):
                (Path(tmp) / name).write_text("Return: the draft profile.\n", encoding="utf-8")
            tool.check_agent_commands(Path(tmp))
        self.assertEqual(tool.errors, [])

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
            define = copy / "agents" / "planner.md"
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

    def test_the_release_is_5_x_with_notes_on_upgrading_from_5_0_then_4_27(self):
        # 5.0's notes, then the notes for the release after it (the version is
        # bumped on the release branch), newest first, each saying how a run resumes.
        root = TOOL.parent.parent
        plugin = json.loads((root / ".claude-plugin" / "plugin.json").read_text("utf-8"))
        self.assertRegex(plugin["version"], r"^5\.[01]\.\d+$")  # a patch keeps the notes
        upgrading = (root / "UPGRADING.md").read_text(encoding="utf-8")
        headings = re.findall(r"^## (.*)$", upgrading, re.MULTILINE)
        self.assertEqual([h.strip() for h in headings[:2]],
                         ["Upgrading from 5.0", "Upgrading from 4.27"])
        for since in (r"5\.0", r"4\.27"):
            section = re.search(rf"^## Upgrading from {since}\b.*?(?=^## |\Z)", upgrading,
                                re.MULTILINE | re.DOTALL)
            self.assertRegex(section.group(0), r"(?i)resum")

    def check_agents_dir(self, files):
        tool = load_tool()
        with tempfile.TemporaryDirectory() as tmp:
            for name, text in files.items():
                (Path(tmp) / name).write_text(text, encoding="utf-8")
            tool.check_briefs(Path(tmp))
        return tool.errors

    def test_an_unknown_planner_token_or_missing_template_fails_the_repo_check(self):
        agents = ROOT_DIR / "agents"
        planner = (agents / "planner.md").read_text(encoding="utf-8")
        self.assertIn("| OVERSIZED | REVISED", planner)
        errors = self.check_agents_dir({"planner.md": planner.replace(
            "| OVERSIZED | REVISED", "| OVERSIZED | SHRUGGED | REVISED", 1)})
        self.assertTrue(any("planner.md" in e and "SHRUGGED" in e for e in errors), errors)
        errors = self.check_agents_dir({"planner.md": planner + "\nSee templates/NOPE.md.\n"})
        self.assertTrue(any("templates/NOPE.md" in e for e in errors), errors)
        errors = self.check_agents_dir({"planner.md": planner})
        self.assertFalse(any(e.startswith("agents/planner.md") for e in errors), errors)

    LENS_HEAD = re.compile(r"^[ \t]*- \*\*(R\d+) — (.+?)\.?\*\*", re.MULTILINE)

    def code_reviewer_mode(self, mode, root=ROOT_DIR):
        """The `## Mode: <mode>` section of agents/code-reviewer.md, as written."""
        text = (root / "agents" / "code-reviewer.md").read_text(encoding="utf-8")
        found = re.search(rf"^## Mode: {mode}\b.*?(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
        self.assertIsNotNone(found, f"agents/code-reviewer.md has no `## Mode: {mode}`")
        return found.group(0)

    def test_each_panel_reviewer_slot_is_told_a_lens_of_its_own(self):
        review = self.code_reviewer_mode("review")
        heads = self.LENS_HEAD.findall(review)
        self.assertEqual(len(heads), 3, heads)
        self.assertEqual({slot: lens.strip().lower() for slot, lens in heads},
                         {"R1": "correctness and edge cases",
                          "R2": "tests and overfitting",
                          "R3": "callers and compatibility"})
        r3 = re.search(r"^[ \t]*- \*\*R3 — .*?(?=^[ \t]*- |\n\s*\n|\Z)", review,
                       re.MULTILINE | re.DOTALL)
        r3_text = " ".join(r3.group(0).split()).lower()
        for what in ("caller", "signature", "return value", "output line", "exit code",
                     "file format", "config key"):
            self.assertIn(what, r3_text)
        # Each reviewer, briefed with its own slot, is pointed at that slot's line:
        # the sentence leading into the lens list names its slot, and nothing outside
        # the lens lines names another slot as its own.
        lens_line = re.compile(r"^[ \t]*- \*\*R\d+ — .*?(?=^[ \t]*- |\n\s*\n|\Z)",
                               re.MULTILINE | re.DOTALL)
        for slot in ("R1", "R2", "R3"):
            told = review.replace("{{reviewer}}", slot)
            first = lens_line.search(told)
            lead_in = told[:first.start()].rstrip().rsplit("\n\n", 1)[-1]
            self.assertEqual(set(re.findall(r"\bR\d+\b", lead_in)), {slot},
                             f"reviewer {slot} is not pointed at its own lens: {lead_in!r}")
            elsewhere = set(re.findall(r"\bR\d+\b", lens_line.sub("", told)))
            self.assertEqual(elsewhere, {slot},
                             f"reviewer {slot}'s instructions name another slot: {elsewhere}")

    def test_the_review_report_header_states_the_lens_used(self):
        template = (ROOT_DIR / "skills" / "auto-dev" / "templates" / "R.md").read_text(
            encoding="utf-8")
        report = template.split("\n", 1)[1]  # below the template's comment line
        header = report.split("\n## ", 1)[0]
        self.assertRegex(header, r"(?m)^Lens: \S")

    def test_a_reviewer_s_lens_orders_its_effort_and_is_not_a_filter(self):
        review = " ".join(self.code_reviewer_mode("review").split()).lower()
        self.assertTrue("is not a filter" in review,
                        "the review mode does not say the lens is not a filter")

    def test_a_re_vote_judges_a_finding_from_the_code_whichever_lens_raised_it(self):
        re_vote = " ".join(self.code_reviewer_mode("re-vote").split()).lower()
        self.assertTrue("your review lens does not apply to a re-vote" in re_vote,
                        "the re-vote mode does not say the review lens does not apply")

    def test_every_panel_reviewer_still_runs_code_review_in_scopes_first_and_outside(self):
        review = " ".join(self.code_reviewer_mode("review").split())
        self.assertRegex(review, r"`first` or `outside`, run the /code-review skill")

    def lens_check_on_a_copy(self, edit):
        """check-repo.py's run on a repo copy whose agents/code-reviewer.md
        `edit` (text -> text) rewrites, after the copy passes as it is."""
        with tempfile.TemporaryDirectory() as tmp:
            copy = self.copy_of_the_repo(tmp)
            tool = copy / "tools" / "check-repo.py"
            agent = copy / "agents" / "code-reviewer.md"

            def run():
                return subprocess.run([sys.executable, str(tool)], capture_output=True,
                                      text=True, check=False)

            result = run()
            self.assertEqual(result.returncode, 0, result.stdout)  # the copy passes as it is
            text = agent.read_text(encoding="utf-8")
            edited = edit(text)
            self.assertNotEqual(edited, text, "the edit changed nothing")
            agent.write_text(edited, encoding="utf-8")
            return run()

    def lens_head_line(self, text, slot):
        found = re.search(rf"^[ \t]*- \*\*{slot} — .*$", text, re.MULTILINE)
        self.assertIsNotNone(found, f"agents/code-reviewer.md has no lens line for {slot}")
        return found

    def fail_lines(self, result):
        return [ln for ln in result.stdout.splitlines() if ln.startswith("FAIL")]

    def test_a_panel_slot_with_its_lens_deleted_fails_the_repo_check_naming_it(self):
        def drop_r3(text):
            line = self.lens_head_line(text, "R3")
            return text[:line.start()] + text[line.end() + 1:]

        result = self.lens_check_on_a_copy(drop_r3)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertTrue([ln for ln in self.fail_lines(result)
                         if "agents/code-reviewer.md" in ln and "R3" in ln], result.stdout)

    def test_two_slots_sharing_a_lens_in_another_case_fail_naming_the_lens(self):
        def r2_as_r1(text):
            line = self.lens_head_line(text, "R2")
            head = re.match(r"([ \t]*- \*\*R2 — ).+?\.?\*\*", line.group(0))
            self.assertIsNotNone(head, line.group(0))
            renamed = (head.group(1) + "Correctness and Edge Cases.**"
                       + line.group(0)[head.end():])
            return text[:line.start()] + renamed + text[line.end():]

        result = self.lens_check_on_a_copy(r2_as_r1)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertTrue([ln for ln in self.fail_lines(result)
                         if "correctness and edge cases" in ln.lower()], result.stdout)

    def test_a_lens_for_a_slot_the_panel_lacks_fails_naming_the_slot(self):
        def add_r4(text):
            line = self.lens_head_line(text, "R3")
            extra = "\n- **R4 — style and naming.** Read every new name for its meaning."
            return text[:line.end()] + extra + text[line.end():]

        result = self.lens_check_on_a_copy(add_r4)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertTrue([ln for ln in self.fail_lines(result) if "R4" in ln], result.stdout)

    def test_a_panel_slot_given_two_lenses_fails_naming_the_slot(self):
        def second_r2(text):
            line = self.lens_head_line(text, "R2")
            extra = "\n- **R2 — performance and load.** Time every changed loop."
            return text[:line.end()] + extra + text[line.end():]

        result = self.lens_check_on_a_copy(second_r2)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertTrue([ln for ln in self.fail_lines(result) if "R2" in ln], result.stdout)

    def test_the_readme_s_code_review_panel_item_names_each_lens(self):
        readme = (ROOT_DIR / "README.md").read_text(encoding="utf-8")
        section = re.search(r"^## Review on the draft PR\n.*?(?=^## |\Z)", readme,
                            re.MULTILINE | re.DOTALL)
        self.assertIsNotNone(section, "README.md has no *Review on the draft PR* section")
        item = re.search(r"\*\*Code review panel\.\*\*.*?(?=\*\*Security review\.\*\*|\Z)",
                         section.group(0), re.DOTALL)
        self.assertIsNotNone(item, "the section has no code review panel item")
        text = " ".join(item.group(0).split()).lower()
        for lens in ("correctness and edge cases", "tests and overfitting",
                     "callers and compatibility"):
            self.assertTrue(lens in text, f"the code review panel item does not name {lens!r}")

    def test_the_panel_has_one_lens_per_reviewer(self):
        tool = load_tool()
        text = (ROOT_DIR / "agents" / "code-reviewer.md").read_text(encoding="utf-8")
        self.assertEqual(tool.panel_lenses(text),
                         [("R1", "correctness and edge cases"),
                          ("R2", "tests and overfitting"),
                          ("R3", "callers and compatibility")])
        self.assertEqual(tuple(tool.load_panel_slots()), ("R1", "R2", "R3"))
        tool.check_panel_lenses()
        self.assertEqual(tool.errors, [])

    def check_lenses(self, lines, slots=("R1", "R2", "R3")):
        tool = load_tool()
        with tempfile.TemporaryDirectory() as tmp:
            text = "## Mode: review\n\n### Your lens\n\n" + "".join(
                f"- **{slot} — {lens}.** Look there first.\n" for slot, lens in lines)
            (Path(tmp) / "code-reviewer.md").write_text(text, encoding="utf-8")
            tool.check_panel_lenses(Path(tmp), slots=slots)
        return tool.errors

    def test_a_slot_without_its_own_lens_fails_the_check(self):
        three = [("R1", "correctness"), ("R2", "tests"), ("R3", "callers")]
        self.assertEqual(self.check_lenses(three), [])
        for lines, named in ((three[:2], ("R3",)),
                             (three + [("R2", "speed")], ("R2",)),
                             (three + [("R4", "style")], ("R4",)),
                             ([three[0], ("R2", " Correctness "), three[2]],
                              ("correctness", "R1", "R2"))):
            errors = self.check_lenses(lines)
            self.assertEqual(len(errors), 1, (lines, errors))
            self.assertTrue(errors[0].startswith("agents/code-reviewer.md:"), errors)
            for word in named:
                self.assertIn(word, errors[0])
        tool = load_tool()
        with tempfile.TemporaryDirectory() as tmp:
            tool.check_panel_lenses(Path(tmp), slots=("R1",))  # no code-reviewer.md
        self.assertEqual(len(tool.errors), 1, tool.errors)
        self.assertIn("agents/code-reviewer.md", tool.errors[0])


if __name__ == "__main__":
    unittest.main()
