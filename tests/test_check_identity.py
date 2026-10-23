"""Tests for tools/check-identity.py, the check that no file names the committer.

gh is tests/fake_gh/gh, which answers `gh config get` with the test's login.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOL = HERE.parent / "tools" / "check-identity.py"
FAKE_GH = HERE / "fake_gh"


class CheckIdentityTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "repo"
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        self.identify()

    def tearDown(self):
        self.tmp.cleanup()

    def identify(self, name="Jane Q Doe", email="jane.doe@example.com", login="jdoe7",
                 gh_login="octo-jane", remote="git@github.com:widget-co/widget.git"):
        for key, value in (("user.name", name), ("user.email", email)):
            subprocess.run(["git", "-C", str(self.root), "config", key, value], check=True)
        subprocess.run(["git", "-C", str(self.root), "remote", "remove", "origin"],
                       capture_output=True, check=False)
        if remote:
            subprocess.run(["git", "-C", str(self.root), "remote", "add", "origin", remote],
                           check=True)
        self.login = login
        responses = Path(self.tmp.name) / "gh.json"
        responses.write_text(json.dumps([{"args": ["config", "get", "-h", "github.com",
                                                   "user"], "stdout": gh_login + "\n"}]))
        self.responses = responses

    def write(self, files):
        for name, text in files.items():
            (self.root / name).parent.mkdir(parents=True, exist_ok=True)
            (self.root / name).write_text(text, encoding="utf-8")

    def git(self, *args):
        subprocess.run(["git", "-C", str(self.root), *args], check=True)

    def run_check(self, files=None, staged=False):
        self.write(files or {})
        env = {**os.environ, "LOGNAME": self.login, "USER": self.login,
               "USERNAME": self.login, "PATH": f"{FAKE_GH}{os.pathsep}{os.environ['PATH']}",
               "FAKE_GH_RESPONSES": str(self.responses)}
        cmd = [sys.executable, str(TOOL), *(["--staged"] if staged else []), str(self.root)]
        result = subprocess.run(cmd, env=env, capture_output=True, text=True, check=False)
        return result.returncode, result.stdout

    def test_files_that_do_not_name_you_pass(self):
        code, out = self.run_check({
            "README.md": "/plugin marketplace add widget-co/widget\nA plain doc.\n",
            ".claude-plugin/plugin.json": '{"author": {\n  "name": "octo-jane"\n}}\n',
            "notes.md": "Jane and Doe alone are fine; so is jdoe70.\n",
        })
        self.assertEqual(code, 0, out)

    def test_each_part_of_your_identity_fails(self):
        code, out = self.run_check({
            "a.md": "By Jane  Q\nDoe.\n",
            "b.md": "Ask JANE.DOE.\n",
            "c.md": "Mail jane.doe@example.com.\n",
            "d.py": "ROOT = '/home" + "/jdoe7/src'\n",  # split so check-repo passes
            "e.md": "Thanks octo-jane, see widget-co/widget.\n",
            "f.json": '{\n  "name": "octo-jane"\n}\n',
            "docs/jdoe7-notes.md": "x\n",
        })
        self.assertEqual(code, 1, out)
        for where in ("a.md:1: names 'Jane Q Doe'", "b.md:1:", "c.md:1:", "d.py:1:",
                      "e.md:1: names 'octo-jane'", "f.json:2:", "docs/jdoe7-notes.md (path):"):
            self.assertIn(f"FAIL {where}", out)
        self.assertEqual(out.count("FAIL "), 7, out)

    def test_a_common_account_name_is_not_a_term(self):
        self.identify(name="Claude", email="noreply@example.com", login="root",
                      gh_login="")
        code, out = self.run_check({"a.md": "Claude runs as root; see auto-dev.\n"})
        self.assertEqual(code, 0, out)
        code, out = self.run_check({"b.md": "Mail noreply@example.com.\n"})
        self.assertEqual(code, 1, out)

    def test_without_an_origin_the_owner_slug_is_not_allowed(self):
        self.identify(remote=None)
        code, out = self.run_check({"a.md": "See octo-jane/widget.\n"})
        self.assertEqual(code, 1, out)
        self.assertIn("FAIL a.md:1: names 'octo-jane'", out)

    def test_an_ignored_file_is_not_checked(self):
        code, out = self.run_check({".gitignore": "*.local.md\n",
                                    "plan.local.md": "Jane Q Doe\n"})
        self.assertEqual(code, 0, out)

    def test_staged_reads_what_the_commit_will_hold(self):
        self.write({"a.md": "By Jane Q Doe.\n"})
        self.git("add", "a.md")
        code, out = self.run_check({"a.md": "By the maintainer.\n", "new.md": "jdoe7\n"},
                                   staged=True)
        self.assertEqual(code, 1, out)
        self.assertIn("FAIL a.md:1:", out)
        self.assertNotIn("new.md", out)
        self.git("add", "a.md")
        code, out = self.run_check({"a.md": "By Jane Q Doe.\n"}, staged=True)
        self.assertEqual(code, 0, out)

    def test_outside_a_git_repo_is_exit_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run([sys.executable, str(TOOL), tmp],
                                    capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 2, result.stdout)


if __name__ == "__main__":
    unittest.main()
