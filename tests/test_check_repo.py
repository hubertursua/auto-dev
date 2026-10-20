"""Tests for tools/check-repo.py, the check that the repo's files agree."""

import importlib.util
import json
import subprocess
import sys
import tempfile
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


if __name__ == "__main__":
    unittest.main()
