"""Tests for tools/eval-run.py, which runs each eval on its own fixture branches.

The fixture "GitHub" repo is a local bare repo: a throwaway git config rewrites
https://github.com/acme/fixture.git to a file://localhost URL for it with
`insteadOf`, which profile-path.py can still map to a profile path. `gh` is
tests/fake_gh/gh.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOL = HERE.parent / "tools" / "eval-run.py"
FAKE_GH = HERE / "fake_gh"
PROFILE_PATH = HERE.parent / "skills" / "auto-dev" / "scripts" / "profile-path.py"
REPO = "acme/fixture"
URL = f"https://github.com/{REPO}.git"


class EvalRunTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp()))
        self.addCleanup(subprocess.run, ["rm", "-rf", str(self.tmp)], check=False)
        self.bare = self.tmp / "fixture.git"
        gitconfig = self.tmp / "gitconfig"
        gitconfig.write_text(f'[url "file://localhost{self.bare}"]\n\tinsteadOf = {URL}\n'
                             "[user]\n\tname = T\n\temail = t@example.com\n"
                             "[init]\n\tdefaultBranch = main\n", encoding="utf-8")
        self.env = dict(os.environ, GIT_CONFIG_GLOBAL=str(gitconfig),
                        GIT_CONFIG_NOSYSTEM="1",
                        PATH=f"{FAKE_GH}{os.pathsep}{os.environ['PATH']}",
                        FAKE_GH_RESPONSES=str(self.tmp / "gh.json"),
                        FAKE_GH_LOG=str(self.tmp / "gh.log"))
        self.env.pop("AUTODEV_EVAL_REPO", None)
        self.work = self.tmp / "work"
        self.git("init", "-q", "--bare", str(self.bare))
        seed = self.tmp / "seed"
        self.git("clone", "-q", URL, str(seed))
        (seed / "README.md").write_text("fixture\n", encoding="utf-8")
        self.git("add", ".", cwd=seed)
        self.git("commit", "-q", "-m", "init", cwd=seed)
        self.git("push", "-q", "origin", "HEAD:main", cwd=seed)
        self.git("push", "-q", "origin", "HEAD:eval/other/e1/base", cwd=seed)
        self.git("push", "-q", "origin", "HEAD:eval/r10/e1/base", cwd=seed)
        self.seed = seed
        self.gh([])

    def git(self, *args, cwd=None):
        return subprocess.run(["git", *args], cwd=cwd, env=self.env, check=True,
                              capture_output=True, text=True).stdout

    def gh(self, responses):
        (self.tmp / "gh.json").write_text(json.dumps(responses), encoding="utf-8")

    def tool(self, *args):
        return subprocess.run([sys.executable, str(TOOL), *args], env=self.env,
                              capture_output=True, text=True, check=False)

    def setup_eval(self, eval_id, *extra, run="r1"):
        return self.tool("setup", "--repo", REPO, "--run", run, "--eval", str(eval_id),
                         "--workdir", str(self.work), *extra)

    def branches(self):
        out = self.git("ls-remote", "--heads", URL)
        return sorted(line.split("refs/heads/")[1] for line in out.splitlines())

    def gh_calls(self):
        log = self.tmp / "gh.log"
        if not log.exists():
            return []
        return [json.loads(line)["args"] for line in log.read_text().splitlines()]

    def test_setup_pushes_a_base_branch_with_its_config(self):
        res = self.setup_eval(7)
        self.assertEqual(res.returncode, 0, res.stderr)
        lines = dict(line.split(": ", 1) for line in res.stdout.splitlines())
        self.assertEqual(lines["BASE"], "eval/r1/e7/base")
        clone = Path(lines["CLONE"])
        self.assertEqual(clone, self.work / "r1" / "e7" / "fixture")
        self.assertIn(f"AUTO_DEV_PROFILES_DIR={lines['PROFILES']}", lines["RUN"])
        self.assertIn("eval/r1/e7/base", self.branches())
        config = self.git("show", "origin/eval/r1/e7/base:.auto-dev.yml", cwd=clone)
        self.assertIn("  base: eval/r1/e7/base\n", config)
        self.assertIn("  prefix: eval/r1/e7/work\n", config)
        self.assertEqual(self.git("rev-parse", "origin/main", cwd=clone),
                         self.git("rev-parse", "HEAD~1", cwd=clone))

    def test_setup_twice_is_refused(self):
        self.assertEqual(self.setup_eval(7).returncode, 0)
        res = self.setup_eval(7)
        self.assertEqual(res.returncode, 2)
        self.assertIn("already", res.stderr)

    def test_setup_refuses_a_base_branch_already_on_the_remote(self):
        self.git("push", "-q", "origin", "HEAD:eval/r1/e3/base", cwd=self.seed)
        res = self.setup_eval(3)
        self.assertEqual(res.returncode, 2)
        self.assertIn("already exists on the remote", res.stderr)
        self.assertFalse((self.work / "r1" / "e3").exists())

    def test_setup_refuses_a_ref_that_has_its_own_config(self):
        (self.seed / ".auto-dev.yml").write_text("ci: none\n", encoding="utf-8")
        self.git("add", ".", cwd=self.seed)
        self.git("commit", "-q", "-m", "config", cwd=self.seed)
        self.git("push", "-q", "origin", "HEAD:fixture/configured", cwd=self.seed)
        res = self.setup_eval(4, "--from", "fixture/configured")
        self.assertEqual(res.returncode, 2)
        self.assertIn("already has an .auto-dev.yml", res.stderr)
        self.assertNotIn("eval/r1/e4/base", self.branches())

    def test_a_missing_input_file_exits_2_and_leaves_nothing(self):
        for flag in ("--profile", "--yml"):
            with self.subTest(flag=flag):
                res = self.setup_eval(5, flag, str(self.tmp / "missing.yml"))
                self.assertEqual(res.returncode, 2, res.stderr)
                self.assertIn(f"could not read {flag}", res.stderr)
                self.assertNotIn("Traceback", res.stderr)
                self.assertFalse((self.work / "r1" / "e5").exists())
                self.assertNotIn("eval/r1/e5/base", self.branches())

    def test_setup_refuses_a_run_directory_of_another_repo(self):
        (self.work / "r1").mkdir(parents=True)
        (self.work / "r1" / ".eval-run").write_text("acme/other\n", encoding="utf-8")
        res = self.setup_eval(1)
        self.assertEqual(res.returncode, 2)
        self.assertIn("another fixture repo", res.stderr)

    def test_setup_starts_from_a_given_ref(self):
        (self.seed / "ci.txt").write_text("variant\n", encoding="utf-8")
        self.git("add", ".", cwd=self.seed)
        self.git("commit", "-q", "-m", "variant", cwd=self.seed)
        self.git("push", "-q", "origin", "HEAD:fixture/variant", cwd=self.seed)
        res = self.setup_eval(9, "--from", "fixture/variant")
        self.assertEqual(res.returncode, 0, res.stderr)
        clone = self.work / "r1" / "e9" / "fixture"
        self.assertEqual(self.git("show", "HEAD:ci.txt", cwd=clone), "variant\n")

    def test_setup_places_the_profile_and_extra_keys(self):
        profile = self.tmp / "profile.yml"
        profile.write_text("setup: []\n", encoding="utf-8")
        yml = self.tmp / "extra.yml"
        yml.write_text("ci: none\n", encoding="utf-8")
        res = self.setup_eval(1, "--profile", str(profile), "--yml", str(yml))
        self.assertEqual(res.returncode, 0, res.stderr)
        profiles = self.work / "r1" / "e1" / "profiles"
        found = subprocess.run(
            [sys.executable, str(PROFILE_PATH), str(profiles.parent / "fixture")],
            env=dict(self.env, AUTO_DEV_PROFILES_DIR=str(profiles)),
            capture_output=True, text=True, check=False)
        self.assertEqual(found.returncode, 0, found.stdout + found.stderr)
        saved = Path(found.stdout.splitlines()[0].split(": ", 1)[1])
        self.assertEqual(saved.read_text(encoding="utf-8"), "setup: []\n")
        config = (self.work / "r1" / "e1" / "fixture" / ".auto-dev.yml").read_text()
        self.assertTrue(config.endswith("ci: none\n"))

    def test_yml_with_branches_is_refused_and_leaves_nothing(self):
        yml = self.tmp / "extra.yml"
        yml.write_text("branches:\n  base: main\n", encoding="utf-8")
        res = self.setup_eval(1, "--yml", str(yml))
        self.assertEqual(res.returncode, 2)
        self.assertFalse((self.work / "r1" / "e1").exists())
        self.assertNotIn("eval/r1/e1/base", self.branches())

    def test_no_config_pushes_nothing(self):
        before = self.branches()
        res = self.setup_eval(13, "--no-config")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("BASE: none", res.stdout)
        self.assertEqual(self.branches(), before)
        self.assertFalse((self.work / "r1" / "e13" / "fixture" / ".auto-dev.yml").exists())

    def test_bad_arguments(self):
        self.assertEqual(self.setup_eval(1, run="Bad_Run").returncode, 2)
        res = self.tool("list")
        self.assertEqual(res.returncode, 2)
        self.assertIn("--repo", res.stderr)

    def prepare_cleanup(self):
        self.assertEqual(self.setup_eval(1).returncode, 0)
        self.assertEqual(self.setup_eval(10).returncode, 0)
        clone = self.work / "r1" / "e1" / "fixture"
        self.git("push", "-q", "origin", "HEAD:eval/r1/e1/work/guard", cwd=clone)
        self.gh([{"args": ["pr", "list"], "stdout": json.dumps([
            {"number": 5, "headRefName": "eval/r1/e1/work/guard",
             "baseRefName": "eval/r1/e1/base"},
            {"number": 6, "headRefName": "eval/other/e1/work/x",
             "baseRefName": "eval/other/e1/base"},
            {"number": 7, "headRefName": "feat/x", "baseRefName": "main"},
            {"number": 8, "headRefName": "feat/outside",
             "baseRefName": "eval/r1/e1/base"},
            {"number": 9, "headRefName": "eval/r10/e1/work/x",
             "baseRefName": "eval/r10/e1/base"}])},
                 {"args": ["pr", "close"], "stdout": ""},
                 {"args": ["secret", "list"], "stdout": json.dumps([
                     {"name": "EVAL_R1_E25"}, {"name": "EVAL_R1_X_E1"},
                     {"name": "EVAL_R10_E25"}, {"name": "EVAL_R1_E5_E2"},
                     {"name": "NPM_TOKEN"}])},
                 {"args": ["secret", "delete"], "stdout": ""}])

    def test_cleanup_removes_only_this_runs_prs_branches_and_files(self):
        self.prepare_cleanup()
        res = self.tool("cleanup", "--repo", REPO, "--run", "r1",
                        "--workdir", str(self.work))
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertEqual(self.branches(),
                         ["eval/other/e1/base", "eval/r10/e1/base", "main"])
        closed = [c for c in self.gh_calls() if c[:2] == ["pr", "close"]]
        self.assertEqual([c[2] for c in closed], ["5", "8"])
        deleted = [c for c in self.gh_calls() if c[:2] == ["secret", "delete"]]
        self.assertEqual([c[2] for c in deleted], ["EVAL_R1_E25"])
        self.assertFalse((self.work / "r1").exists())
        self.assertTrue(res.stdout.endswith("DONE\n"))

    def test_cleanup_works_from_outside_any_git_repo(self):
        self.prepare_cleanup()
        outside = self.tmp / "outside"
        outside.mkdir()
        # Stop git's repo search at the temp dir, in case it sits in a repo.
        env = dict(self.env, GIT_CEILING_DIRECTORIES=str(self.tmp))
        res = subprocess.run([sys.executable, str(TOOL), "cleanup", "--repo", REPO,
                              "--run", "r1", "--workdir", str(self.work)],
                             cwd=outside, env=env, capture_output=True, text=True,
                             check=False)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertEqual(self.branches(),
                         ["eval/other/e1/base", "eval/r10/e1/base", "main"])
        self.assertEqual(list(outside.iterdir()), [])

    def test_cleanup_dry_run_changes_nothing(self):
        self.prepare_cleanup()
        before = self.branches()
        res = self.tool("cleanup", "--repo", REPO, "--run", "r1",
                        "--workdir", str(self.work), "--dry-run")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("would close PR #5", res.stdout)
        self.assertIn("would delete branch eval/r1/e1/base", res.stdout)
        self.assertEqual(self.branches(), before)
        self.assertTrue((self.work / "r1").exists())
        self.assertFalse([c for c in self.gh_calls()
                          if c[:2] in (["pr", "close"], ["secret", "delete"])])

    def test_cleanup_reports_a_pr_it_could_not_close(self):
        self.prepare_cleanup()
        self.gh([{"args": ["pr", "list"], "stdout": json.dumps([
            {"number": 5, "headRefName": "eval/r1/e1/work/guard",
             "baseRefName": "eval/r1/e1/base"}])},
                 {"args": ["pr", "close"], "stderr": "denied", "exit": 1},
                 {"args": ["secret", "list"], "stdout": "[]"}])
        res = self.tool("cleanup", "--repo", REPO, "--run", "r1",
                        "--workdir", str(self.work))
        self.assertEqual(res.returncode, 1)
        self.assertIn("FAILED to close PR #5", res.stdout)

    def test_cleanup_reports_a_branch_it_could_not_delete(self):
        self.prepare_cleanup()
        hook = self.bare / "hooks" / "pre-receive"
        hook.write_text("#!/bin/sh\necho refused >&2\nexit 1\n", encoding="utf-8")
        hook.chmod(0o755)
        res = self.tool("cleanup", "--repo", REPO, "--run", "r1",
                        "--workdir", str(self.work))
        self.assertEqual(res.returncode, 1)
        self.assertIn("FAILED to delete eval/r1/e1/base", res.stdout)
        self.assertIn("eval/r1/e1/base", self.branches())

    def test_cleanup_stops_when_gh_fails(self):
        self.prepare_cleanup()
        before = self.branches()
        self.gh([{"args": ["pr", "list"], "stderr": "auth", "exit": 1}])
        res = self.tool("cleanup", "--repo", REPO, "--run", "r1",
                        "--workdir", str(self.work))
        self.assertEqual(res.returncode, 2)
        self.assertEqual(self.branches(), before)

    def test_cleanup_leaves_a_directory_it_did_not_make(self):
        (self.work / "r2").mkdir(parents=True)
        self.gh([{"args": ["pr", "list"], "stdout": "[]"},
                 {"args": ["secret", "list"], "stdout": "[]"}])
        res = self.tool("cleanup", "--repo", REPO, "--run", "r2",
                        "--workdir", str(self.work))
        self.assertEqual(res.returncode, 1)
        self.assertTrue((self.work / "r2").exists())

    def test_list_counts_branches_per_run(self):
        self.assertEqual(self.setup_eval(1).returncode, 0)
        self.assertEqual(self.setup_eval(2).returncode, 0)
        res = self.tool("list", "--repo", REPO)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(res.stdout,
                         "other: 1 branches\nr1: 2 branches\nr10: 1 branches\n")


if __name__ == "__main__":
    unittest.main()
