"""Tests for tools/run-tests.py, run as a subprocess on a small suite of its own."""

import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

TOOL = Path(__file__).resolve().parent.parent / "tools" / "run-tests.py"

PASSING = """
import unittest

class FirstTest(unittest.TestCase):
    def test_one(self):
        self.assertTrue(True)

    def test_two(self):
        self.assertTrue(True)

class SecondTest(unittest.TestCase):
    def test_three(self):
        self.assertTrue(True)

    @unittest.skip("not here")
    def test_skipped(self):
        pass
"""

FAILING = """
import unittest

class BrokenTest(unittest.TestCase):
    def test_wrong(self):
        self.assertEqual(1, 2, "the planted failure")
"""


class RunTestsTest(unittest.TestCase):
    def suite(self, **modules):
        """A repo of its own with tools/run-tests.py and tests/<name>.py for
        each module given."""
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        (tmp / "tools").mkdir()
        shutil.copy(TOOL, tmp / "tools" / "run-tests.py")
        (tmp / "tests").mkdir()
        for name, text in modules.items():
            (tmp / "tests" / f"{name}.py").write_text(textwrap.dedent(text), encoding="utf-8")
        return tmp

    def run_tool(self, root, *args):
        return subprocess.run([sys.executable, str(root / "tools" / "run-tests.py"), *args],
                              capture_output=True, text=True, check=False)

    def test_a_passing_suite_runs_every_class_and_exits_0(self):
        root = self.suite(test_a=PASSING)
        r = self.run_tool(root, "-j", "2")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("ok   test_a.FirstTest (2 tests", r.stdout)
        self.assertIn("ok   test_a.SecondTest (2 tests", r.stdout)
        self.assertIn("OK: 4 tests in 2 classes", r.stdout)
        self.assertNotIn("Ran 2 tests", r.stdout)  # a passing class's output is not shown

    def test_a_failing_class_is_named_with_its_output_and_exits_1(self):
        root = self.suite(test_a=PASSING, test_b=FAILING)
        r = self.run_tool(root)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("FAIL test_b.BrokenTest (1 tests", r.stdout)
        self.assertIn("the planted failure", r.stdout)
        self.assertIn("FAILED: 1 of 3 classes (5 tests", r.stdout)
        self.assertIn("test_b.BrokenTest", r.stdout.splitlines()[-1])

    def test_names_limit_the_run_to_those_modules_or_classes(self):
        root = self.suite(test_a=PASSING, test_b=FAILING)
        r = self.run_tool(root, "test_a.SecondTest")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("OK: 2 tests in 1 classes", r.stdout)
        self.assertNotIn("FirstTest", r.stdout)
        r = self.run_tool(root, "test_a")
        self.assertIn("OK: 4 tests in 2 classes", r.stdout)

    def test_v_shows_a_passing_class_s_output(self):
        root = self.suite(test_a=PASSING)
        r = self.run_tool(root, "-v", "test_a.FirstTest")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Ran 2 tests", r.stdout)

    def test_a_module_that_does_not_import_could_not_run(self):
        root = self.suite(test_a=PASSING, test_c="import no_such_module_here\n")
        r = self.run_tool(root)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("failed to import", r.stderr)

    def test_a_name_with_no_classes_could_not_run(self):
        root = self.suite(test_a=PASSING)
        r = self.run_tool(root, "test_nothing")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("no test classes found for test_nothing", r.stderr)

    def test_classes_with_more_tests_start_first(self):
        root = self.suite(test_a=PASSING, test_b=FAILING)
        r = self.run_tool(root, "-j", "1")
        names = [ln.split()[1] for ln in r.stdout.splitlines()
                 if ln.startswith(("ok ", "FAIL "))]
        self.assertEqual(names[-1], "test_b.BrokenTest", r.stdout)


if __name__ == "__main__":
    unittest.main()
