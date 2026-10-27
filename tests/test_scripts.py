"""Tests for the helper scripts in skills/auto-dev/scripts/.

Run: python3 -m unittest discover -s tests -v   (from the repo root)

Each test runs a script as a subprocess, the way the pipeline does, and checks
its exit code and output. Git-based tests build a throwaway repo in a temp dir.
"""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "skills" / "auto-dev" / "scripts"

GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "test@example.com",
    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
}


def run(script, *args, cwd=None):
    return subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)],
                          capture_output=True, text=True, cwd=cwd, env=GIT_ENV, check=False)


class GitRepoCase(unittest.TestCase):
    """A fresh git repo with one commit, in self.repo."""

    def setUp(self):
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp()))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        self.write("src/app.py", "def add(a, b):\n    return a + b\n")
        self.write("tests/test_app.py",
                   "from src.app import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "init")

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], capture_output=True,
                              text=True, env=GIT_ENV, check=True).stdout

    def write(self, rel, text):
        path = self.repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path


class ExcludeArtifactsTest(GitRepoCase):
    def test_makes_auto_dev_self_ignoring_and_is_idempotent(self):
        for _ in range(2):
            r = run("exclude-artifacts.py", self.repo)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("VERIFIED", r.stdout)
        self.assertEqual((self.repo / ".auto-dev/.gitignore").read_text().strip(), "*")
        (self.repo / ".auto-dev/WORK_LOG.md").write_text("x")
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_not_a_git_tree(self):
        r = run("exclude-artifacts.py", self.tmp)
        self.assertEqual(r.returncode, 2)


class CheckStagedTest(GitRepoCase):
    def setUp(self):
        super().setUp()
        self.assertEqual(run("exclude-artifacts.py", self.repo).returncode, 0)
        self.write("src/app.py", "def add(a, b):\n    return b + a\n")

    def test_clean_with_expected_paths(self):
        self.git("add", "src/app.py")
        r = run("check-staged.py", self.repo, "--expect", "src/app.py")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("CLEAN", r.stdout)

    def test_staged_artifact_fails(self):
        (self.repo / ".auto-dev/SPEC.md").write_text("spec")
        self.git("add", "-f", ".auto-dev/SPEC.md")
        r = run("check-staged.py", self.repo)
        self.assertEqual(r.returncode, 1)
        self.assertIn("STAGED ARTIFACTS", r.stderr)

    def test_extra_and_unstaged_paths_fail(self):
        self.write("src/other.py", "x = 1\n")
        self.git("add", "src/other.py")
        r = run("check-staged.py", self.repo, "--expect", "src/other.py")
        self.assertEqual(r.returncode, 1)  # src/app.py changed but not staged
        self.git("add", "src/app.py")
        r = run("check-staged.py", self.repo, "--expect", "src/app.py")
        self.assertEqual(r.returncode, 1)  # src/other.py staged but not expected

    def test_a_file_name_that_is_not_utf8_is_checked(self):
        name = b"caf\xe9.txt"  # Latin-1
        try:
            with open(os.path.join(os.fsencode(self.repo), name), "wb") as f:
                f.write(b"x\n")
        except OSError as exc:  # macOS APFS refuses names that aren't UTF-8
            self.skipTest(f"this file system refuses the name: {exc}")
        self.git("add", "-A")
        r = run("check-staged.py", self.repo, "--expect", "src/app.py", os.fsdecode(name))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("caf\\xe9.txt", r.stdout)
        r = run("check-staged.py", self.repo, "--expect", "src/app.py")
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("EXTRA: 1", r.stderr)
        self.assertIn("caf\\xe9.txt", r.stderr)

    def fake_git(self, body):
        """Run check-staged.py with a `git` on PATH that runs `body` (Python)."""
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir(exist_ok=True)
        fake = bin_dir / "git"
        fake.write_text(f"#!{sys.executable}\nimport sys\nargs = sys.argv[1:]\n{body}\n")
        fake.chmod(0o755)
        env = {**GIT_ENV, "PATH": f"{bin_dir}{os.pathsep}{GIT_ENV['PATH']}"}
        return subprocess.run([sys.executable, str(SCRIPTS / "check-staged.py"), self.repo],
                              capture_output=True, text=True, env=env, check=False)

    def test_git_output_that_is_not_utf8_is_read(self):
        # Runs where the file system refuses such a name (the test above skips).
        r = self.fake_git(f"print({str(self.repo)!r}) if 'rev-parse' in args else "
                          "sys.stdout.buffer.write(b'caf\\xe9.txt\\0')")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("caf\\xe9.txt", r.stdout)

    def test_a_crash_is_exit_2(self):
        r = self.fake_git("sys.stdout.write('a\\0b')")  # a NUL in the top level crashes Path
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("not a pass", r.stderr)


class CheckFreshTest(GitRepoCase):
    """check-fresh.py: reports stamped with the tree they checked."""

    REPORTS = ("SPEC_EVAL.md", "lint/TEST.md", "CODE_REVIEW.md", "SECURITY_REVIEW.md")

    def setUp(self):
        super().setUp()
        self.assertEqual(run("exclude-artifacts.py", self.repo).returncode, 0)
        self.artifacts = self.repo / ".auto-dev"
        self.write("src/app.py", "def add(a, b):\n    return b + a\n")

    def tree(self, *extra):
        r = run("check-fresh.py", "--print-tree", self.repo, *extra)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip()

    def stamp(self, tree=None, reports=REPORTS):
        tree = tree or self.tree()
        for name in reports:
            path = self.artifacts / name
            path.parent.mkdir(parents=True, exist_ok=True)
            # lint reports carry it as a list item, the others as a plain line.
            line = f"- **Tree:** `{tree}`" if name.startswith("lint/") else f"Tree: {tree}"
            path.write_text(f"# {name}\n\n{line}\n")
        return tree

    def check(self, *extra):
        return run("check-fresh.py", self.repo, self.artifacts, *extra)

    def test_fresh(self):
        self.stamp()
        r = self.check()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("FRESH: 4 report(s)", r.stdout)

    def test_print_tree_leaves_the_index_alone(self):
        self.write("src/new.py", "x = 1\n")
        before = self.git("status", "--porcelain")
        self.tree()
        self.assertEqual(self.git("status", "--porcelain"), before)
        self.assertIn("?? src/new.py", before)

    def test_print_tree_works_when_the_repo_ignores_auto_dev(self):
        # git 2.50 refuses an exclude pathspec that names an ignored path.
        self.write(".gitignore", ".auto-dev/\n")
        self.git("add", ".gitignore")
        self.git("commit", "-q", "-m", "ignore .auto-dev/")
        (self.artifacts / "SPEC.md").write_text("spec\n")
        tree = self.tree()
        listing = self.git("ls-tree", "-r", "--name-only", tree)
        self.assertNotIn(".auto-dev", listing)
        self.assertIn("src/app.py", listing)

    def test_edited_file_is_stale(self):
        self.stamp()
        self.write("src/app.py", "def add(a, b):\n    return a - b\n")
        r = self.check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("STALE: SPEC_EVAL.md", r.stderr)
        self.assertIn("src/app.py", r.stderr)  # what changed since the check

    def test_same_size_edit_right_after_commit_is_seen(self):
        # git trusts a file's cached stat unless the index's own mtime says it
        # may be stale ("racy git"); a copied index must keep that mtime.
        for i in range(30):
            self.write("src/app.py", f"x = {i % 10}a\n")
            self.git("add", "src/app.py")
            self.git("commit", "-q", "-m", f"c{i}")
            self.write("src/app.py", f"x = {i % 10}b\n")
            self.assertNotEqual(self.tree(), self.git("rev-parse", "HEAD^{tree}").strip(),
                                f"try {i}: a same-size edit was missed")

    def test_new_untracked_file_is_stale(self):
        self.stamp()
        self.write("src/extra.py", "y = 2\n")
        r = self.check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("src/extra.py", r.stderr)

    def test_missing_report_or_stamp_is_stale(self):
        self.stamp(reports=self.REPORTS[:3])
        r = self.check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("MISSING: SECURITY_REVIEW.md", r.stderr)
        (self.artifacts / "SECURITY_REVIEW.md").write_text("# Security review\n")
        r = self.check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("NO STAMP: SECURITY_REVIEW.md", r.stderr)

    def test_deleted_file_is_stale_and_ignored_file_is_not(self):
        self.write(".gitignore", "build/\n")
        self.git("add", ".gitignore")
        self.git("commit", "-q", "-m", "ignore build/")
        self.stamp()
        self.write("build/out.txt", "generated\n")
        self.assertEqual(self.check().returncode, 0)
        (self.repo / "tests/test_app.py").unlink()
        r = self.check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("tests/test_app.py", r.stderr)

    def test_stamp_that_is_not_a_hash_is_no_stamp(self):
        self.stamp()
        (self.artifacts / "SPEC_EVAL.md").write_text("# x\n\nTree: changed during the run\n")
        r = self.check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("NO STAMP: SPEC_EVAL.md", r.stderr)

    def test_unknown_old_tree_says_so(self):
        self.stamp(tree="0" * 40)
        r = self.check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("changed since: unknown", r.stderr)

    def test_artifacts_in_the_real_index_are_left_out(self):
        tree = self.stamp()
        self.git("add", "-f", ".auto-dev/SPEC_EVAL.md")
        self.assertEqual(self.tree(), tree)

    def test_non_utf8_file_name_does_not_crash(self):
        if sys.platform in ("darwin", "win32"):
            self.skipTest("the file system needs valid UTF-8 names")
        self.stamp()
        (self.repo / os.fsdecode(b"bad\xff.txt")).write_text("x\n")
        r = self.check()
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("bad", r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_phase_5_checks_only_its_own_reports(self):
        self.stamp(reports=self.REPORTS[:2])
        self.assertEqual(self.check().returncode, 1)
        r = self.check("--phase", "5")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_phase_5_needs_a_lint_report(self):
        self.stamp(reports=self.REPORTS[:1])
        r = self.check("--phase", "5")
        self.assertEqual(r.returncode, 1)
        self.assertIn("MISSING: lint/", r.stderr)

    def test_changes_under_auto_dev_are_ignored(self):
        self.stamp()
        (self.artifacts / "WORK_LOG.md").write_text("# Work Log\n")
        # Even if its self-exclusion were lost, .auto-dev/ is not part of the code.
        (self.artifacts / ".gitignore").unlink()
        r = self.check()
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_ref_head_matches_after_commit(self):
        tree = self.stamp()
        self.git("add", "src/app.py")
        self.git("commit", "-q", "-m", "change")
        self.assertEqual(self.tree("--ref", "HEAD"), tree)
        r = self.check("--ref", "HEAD")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_ref_sees_a_commit_the_check_never_saw(self):
        self.stamp()
        self.git("add", "src/app.py")
        self.git("commit", "-q", "-m", "change")
        self.write("src/app.py", "def add(a, b):\n    return 0\n")
        self.git("commit", "-q", "-am", "someone else's push")
        r = self.check("--ref", "HEAD")
        self.assertEqual(r.returncode, 1)
        self.assertIn("src/app.py", r.stderr)

    def test_unknown_ref_cannot_run(self):
        self.stamp()
        r = self.check("--ref", "no-such-branch")
        self.assertEqual(r.returncode, 2)
        self.assertIn("ERROR", r.stderr)

    def test_not_a_git_tree(self):
        plain = self.tmp / "plain"
        plain.mkdir()
        for args in (("--print-tree", plain), (plain, self.artifacts)):
            r = run("check-fresh.py", *args)
            self.assertEqual(r.returncode, 2)
            self.assertIn("ERROR", r.stderr)

    def test_needs_an_artifact_dir_or_print_tree(self):
        for args in ((self.repo,), ("--print-tree", self.repo, self.artifacts)):
            r = run("check-fresh.py", *args)
            self.assertEqual(r.returncode, 2)
            self.assertIn("ERROR", r.stderr)


class CheckTestsTest(GitRepoCase):
    def audit(self, *extra):
        return run("check-tests.py", self.repo, "--base", "HEAD", *extra)

    def test_clean_change(self):
        self.write("src/app.py", "def add(a, b):\n    return b + a\n")
        r = self.audit()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_deleted_test(self):
        (self.repo / "tests/test_app.py").unlink()
        r = self.audit()
        self.assertEqual(r.returncode, 1)
        self.assertIn("DELETED_TEST", r.stdout)

    def test_removed_assertion(self):
        self.write("tests/test_app.py",
                   "from src.app import add\n\n\ndef test_add():\n    add(1, 2)\n")
        r = self.audit()
        self.assertEqual(r.returncode, 1)
        self.assertIn("REMOVED_ASSERTION", r.stdout)

    def test_added_skip(self):
        self.write("tests/test_app.py",
                   "import pytest\nfrom src.app import add\n\n\n@pytest.mark.skip\n"
                   "def test_add():\n    assert add(1, 2) == 3\n")
        r = self.audit()
        self.assertEqual(r.returncode, 1)
        self.assertIn("ADDED_SKIP", r.stdout)

    def test_new_test_without_assertions(self):
        self.write("tests/test_new.py", "def test_nothing():\n    pass\n")
        r = self.audit()
        self.assertEqual(r.returncode, 1)
        self.assertIn("NO_ASSERTIONS", r.stdout)

    def test_tampered_acceptance_check(self):
        acceptance = self.tmp / "acceptance"
        sealed = acceptance / "files/tests/test_accept.py.sealed"
        sealed.parent.mkdir(parents=True)
        sealed.write_text("def test_accept():\n    assert True\n")
        self.write("tests/test_accept.py", "def test_accept():\n    assert 1\n")
        r = self.audit("--acceptance", acceptance)
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertIn("ACCEPTANCE_MODIFIED", r.stdout)


    def test_acceptance_tests_added_to_an_existing_file(self):
        # The check added a test to tests/test_app.py; the coder added another.
        acceptance = self.tmp / "acceptance"
        files = acceptance / "files/tests"
        files.mkdir(parents=True)
        base = (self.repo / "tests/test_app.py").read_text()
        added = "\n\ndef test_add_negative():\n    assert add(-1, -2) == -3\n"
        (files / "test_app.py.base").write_text(base)
        (files / "test_app.py.sealed").write_text(base + added)
        coder = "\n\ndef test_add_zero():\n    assert add(0, 0) == 0\n"
        self.write("tests/test_app.py", base + added + coder)
        r = self.audit("--acceptance", acceptance)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.write("tests/test_app.py", base + added.replace("-3", "-4") + coder)
        r = self.audit("--acceptance", acceptance)
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertIn("ACCEPTANCE_MODIFIED\ttests/test_app.py", r.stdout)


class MutateTest(GitRepoCase):
    CMD = f"{sys.executable} -c \"from src.app import add; assert add(1, 2) == 3\""

    def mutate(self, mutants, *extra):
        path = self.tmp / "mutants.json"
        path.write_text(json.dumps(mutants))
        return run("mutate.py", self.repo, "--mutants", path, *extra), path

    def test_caught_and_survived_mutants_restore_the_file(self):
        before = (self.repo / "src/app.py").read_bytes()
        r, path = self.mutate([
            {"id": "M1", "file": "src/app.py", "line": 2, "find": "a + b", "replace": "a - b",
             "condition": "1"},
            {"id": "M2", "file": "src/app.py", "line": 2, "find": "a + b", "replace": "b + a",
             "condition": "1"},
        ], "--cmd", self.CMD, "--timeout", "60")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)  # M2 survives
        self.assertEqual((self.repo / "src/app.py").read_bytes(), before)
        results = json.loads(Path(str(path) + ".results.json").read_text())
        self.assertEqual({m["id"]: m["status"] for m in results},
                         {"M1": "killed", "M2": "survived"})

    def test_restored_file_is_not_shadowed_by_cached_bytecode(self):
        # The restored file must get a newer mtime than the mutant, or Python
        # (like any mtime-based build cache) keeps running the mutant's bytecode.
        r, _ = self.mutate([{"id": "M1", "file": "src/app.py", "line": 2, "find": "a + b",
                             "replace": "a - b"}], "--cmd", self.CMD, "--timeout", "60")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        after = subprocess.run(self.CMD, shell=True, cwd=self.repo, capture_output=True,
                               text=True, check=False)
        self.assertEqual(after.returncode, 0, after.stderr)

    def test_red_baseline_mutates_nothing(self):
        before = (self.repo / "src/app.py").read_bytes()
        r, _ = self.mutate([{"id": "M1", "file": "src/app.py", "line": 2, "find": "a + b",
                             "replace": "a - b"}], "--cmd", "exit 1", "--timeout", "60")
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertEqual((self.repo / "src/app.py").read_bytes(), before)

    def test_malformed_mutants_file(self):
        r, _ = self.mutate({"not": "a list"}, "--cmd", self.CMD)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)

    def test_exit_file_holds_the_exit_code_whatever_ends_the_run(self):
        # A caller running it in the background needs no `echo $?`, which a
        # permission check refuses as a shell variable.
        exit_file = self.tmp / "mutate.exit"
        r, _ = self.mutate([{"id": "M1", "file": "src/app.py", "line": 2, "find": "a + b",
                             "replace": "b + a"}], "--cmd", self.CMD, "--timeout", "60",
                           "--exit-file", exit_file)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)  # it survives
        self.assertEqual(exit_file.read_text(), "1\n")
        r, _ = self.mutate([], "--timeout", "nope", "--exit-file", exit_file)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)  # a usage error
        self.assertEqual(exit_file.read_text(), "2\n")


@unittest.skipUnless(importlib.util.find_spec("yaml"), "PyYAML is not installed")
class ValidateConfigTest(unittest.TestCase):
    def validate(self, text):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".auto-dev.yml"
            path.write_text(text)
            return run("validate-config.py", path)

    def test_valid(self):
        r = self.validate("iteration_budget: 3\nmutation:\n  max: 10\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("VALID", r.stdout)

    def test_typo_is_named(self):
        r = self.validate("iteration_budgt: 3\n")
        self.assertEqual(r.returncode, 1)
        self.assertIn("iteration_budget", r.stderr)

    def test_the_removed_staging_key_is_refused(self):
        r = self.validate("branches:\n  base: main\n  staging: staging\n")
        self.assertEqual(r.returncode, 1)
        self.assertIn("branches.staging: removed in 4.0", r.stderr)
        self.assertNotIn("unknown key", r.stderr)
        self.assertEqual(self.validate("branches:\n  base: main\n").returncode, 0)

    def test_checkpoint_events(self):
        self.assertEqual(self.validate("checkpoint_events: 40\n").returncode, 0)
        for bad in ("0", "x"):
            r = self.validate(f"checkpoint_events: {bad}\n")
            self.assertEqual(r.returncode, 1, bad)
            self.assertIn("checkpoint_events", r.stderr)

    def test_mutation_max_out_of_range(self):
        r = self.validate("mutation:\n  max: 500\n")
        self.assertEqual(r.returncode, 1)

    def test_symbol_lookup_valid(self):
        r = self.validate('symbol_lookup:\n  definition: "dexter lookup <symbol>"\n'
                          '  references: "dexter references <symbol>"\n')
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_symbol_lookup_needs_placeholder(self):
        r = self.validate('symbol_lookup:\n  definition: "dexter lookup"\n')
        self.assertEqual(r.returncode, 1)
        self.assertIn("<symbol>", r.stderr)

    def test_symbol_lookup_unknown_field(self):
        r = self.validate('symbol_lookup:\n  lookup: "dexter lookup <symbol>"\n')
        self.assertEqual(r.returncode, 1)
        self.assertIn("symbol_lookup", r.stderr)

    def validate_profile(self, text):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "web-app.yml"
            path.write_text(text)
            return run("validate-config.py", "--profile", path)

    PROFILE = ('stack: typescript\nsetup: ["npm ci"]\ngate:\n'
               '  - { kind: test, command: "npm test", report: "TEST.md" }\n')

    def test_profile_valid(self):
        r = self.validate_profile(self.PROFILE + "ci: github-actions\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("is a profile with", r.stdout)

    def test_profile_needs_setup_and_gate(self):
        r = self.validate_profile("stack: typescript\n")
        self.assertEqual(r.returncode, 1)
        self.assertIn("must set `setup`", r.stderr)
        self.assertIn("must set `gate`", r.stderr)

    def test_profile_rejects_repo_policy_keys(self):
        r = self.validate_profile(self.PROFILE + "iteration_budget: 3\n")
        self.assertEqual(r.returncode, 1)
        self.assertIn(".auto-dev.yml", r.stderr)

    def test_profile_gate_needs_a_test(self):
        r = self.validate_profile(
            'setup: []\ngate:\n'
            '  - { kind: lint, command: "npx eslint .", report: "LINT.md" }\n')
        self.assertEqual(r.returncode, 1)
        self.assertIn("kind: test", r.stderr)

    def test_missing_profile_is_invalid(self):
        r = run("validate-config.py", "--profile", "/nonexistent/web-app.yml")
        self.assertEqual(r.returncode, 1)

    def test_override_may_still_set_policy_keys(self):
        r = self.validate("stack: typescript\niteration_budget: 3\n")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_stack_alone_warns_it_selects_nothing(self):
        r = self.validate("stack: typescript\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("no longer selects", r.stdout)
        r = self.validate(self.PROFILE)
        self.assertNotIn("no longer selects", r.stdout)


class ProfilePathTest(GitRepoCase):
    def setUp(self):
        super().setUp()
        self.profiles = self.tmp / "profiles"

    def lookup(self, url=None, repo=None, env=None):
        if url is not None:
            self.git("remote", "add", "origin", url)
        environ = {**GIT_ENV, "AUTO_DEV_PROFILES_DIR": str(self.profiles), **(env or {})}
        return subprocess.run([sys.executable, str(SCRIPTS / "profile-path.py"),
                               str(repo or self.repo)],
                              capture_output=True, text=True, env=environ, check=False)

    def test_url_forms_share_one_path(self):
        expected = self.profiles / "github.com" / "acme" / "web-app.yml"
        for url in ("git@github.com:Acme/Web-App.git",
                    "https://github.com/acme/web-app",
                    "https://user:token@github.com/acme/web-app.git/",
                    "ssh://git@github.com:22/acme/web-app.git"):
            with self.subTest(url=url):
                if "origin" in self.git("remote"):
                    self.git("remote", "remove", "origin")
                r = self.lookup(url)
                self.assertEqual(r.returncode, 1, r.stderr)
                self.assertIn(f"NOT FOUND: {expected}", r.stdout)
                self.assertIn(f"DIR: {self.profiles}", r.stdout)

    def test_found(self):
        saved = self.profiles / "gitlab.com" / "acme" / "team" / "api.yml"
        saved.parent.mkdir(parents=True)
        saved.write_text("setup: []\n")
        r = self.lookup("git@gitlab.com:acme/team/api.git")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"FOUND: {saved}", r.stdout)

    def test_worktree_finds_the_same_profile(self):
        self.git("remote", "add", "origin", "git@github.com:acme/web-app.git")
        tree = self.tmp / "web-app-feature"
        self.git("worktree", "add", "-q", "-b", "feature", str(tree))
        self.assertIn(str(self.profiles / "github.com" / "acme" / "web-app.yml"),
                      self.lookup(repo=tree).stdout)

    def test_xdg_config_home(self):
        self.git("remote", "add", "origin", "git@github.com:acme/web-app.git")
        environ = {k: v for k, v in GIT_ENV.items() if k != "AUTO_DEV_PROFILES_DIR"}
        environ["XDG_CONFIG_HOME"] = str(self.tmp / "xdg")
        r = subprocess.run([sys.executable, str(SCRIPTS / "profile-path.py"), str(self.repo)],
                           capture_output=True, text=True, env=environ, check=False)
        self.assertIn(str(self.tmp / "xdg" / "auto-dev" / "profiles" / "github.com"), r.stdout)

    def test_no_origin(self):
        r = self.lookup()
        self.assertEqual(r.returncode, 2)
        self.assertIn("ERROR", r.stderr)

    def test_not_a_repo(self):
        r = self.lookup(repo=self.tmp / "nowhere")
        self.assertEqual(r.returncode, 2)

    def test_unsafe_segment_is_refused(self):
        r = self.lookup("https://github.com/acme/../../etc/passwd")
        self.assertEqual(r.returncode, 2)
        self.assertNotIn("FOUND", r.stdout)


if __name__ == "__main__":
    unittest.main()
