"""Tests for tools/check-pr.py, the branch-name and PR-title check."""

import subprocess
import sys
import unittest
from pathlib import Path

TOOL = Path(__file__).resolve().parent.parent / "tools" / "check-pr.py"


def check(*args):
    return subprocess.run([sys.executable, str(TOOL), *args],
                          capture_output=True, text=True, check=False).returncode


class CheckPrTest(unittest.TestCase):
    def test_good_branches(self):
        for name in ("fix/mutate-mtime", "feat/acceptance-tester", "docs/readme",
                     "ci/python-matrix", "claude/code-review-xz3fzi"):
            with self.subTest(name=name):
                self.assertEqual(check("--branch", name), 0)

    def test_bad_branches(self):
        for name in ("main", "feature/x", "fix/Mutate_MTime", "fix/", "my-branch",
                     "fix/a--b", "fix/a/b"):
            with self.subTest(name=name):
                self.assertEqual(check("--branch", name), 1)

    def test_good_titles(self):
        for title in ("fix: give each mutant its own mtime",
                      "feat!: replace SPEC.md conditions with a new format",
                      "docs: bring README up to date"):
            with self.subTest(title=title):
                self.assertEqual(check("--title", title), 0)

    def test_bad_titles(self):
        for title in ("Fix the thing", "fix:no space", "Fix: capitalized type",
                      "fix: ends with a period.", "fix: " + "x" * 80):
            with self.subTest(title=title):
                self.assertEqual(check("--title", title), 1)

    def test_needs_an_argument(self):
        self.assertEqual(check(), 2)


if __name__ == "__main__":
    unittest.main()
