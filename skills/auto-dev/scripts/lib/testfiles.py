"""Recognize test files, test-runner configs, skip/focus markers and comments.

Shared by `check-tests.py` (the audit of a build's test changes) and
`autodev.py mutants` (when a test change forces every mutant to run again), so
both recognize the same files. The patterns are heuristics across common
stacks: a test file by its name (`*_test.*`, `test_*.py`, `*.test.*`,
`*.spec.*`, `*_spec.rb`, `*Test.java` …) or by a code file under a `test/`,
`tests/`, `spec/`, `specs/` or `__tests__/` directory.
"""

import os
import re

CODE_EXT = {
    ".ex", ".exs", ".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".rb",
    ".go", ".rs", ".java", ".kt", ".kts", ".scala", ".cs", ".swift", ".php",
    ".erl", ".clj", ".cljs", ".dart", ".c", ".cc", ".cpp", ".h", ".hpp",
}
TEST_DIRS = {"test", "tests", "spec", "specs", "__tests__"}
TEST_NAME = re.compile(
    r"(_test\.\w+$|^test_.*\.py$|\.test\.\w+$|\.spec\.\w+$|_spec\.rb$"
    r"|Tests?\.(java|kt|scala|cs|swift|php)$)"
)
# Runner configs and shared helpers that can exclude, skip or focus tests.
TEST_CONFIG = re.compile(
    r"(^|/)(test_helper\.exs|conftest\.py|pytest\.ini|tox\.ini|setup\.cfg"
    r"|(jest|vitest|playwright|karma|cypress)\.config\.\w+|\.mocharc(\.\w+)?"
    r"|phpunit\.xml(\.dist)?|\.rspec|spec_helper\.rb|rails_helper\.rb"
    r"|pyproject\.toml|package\.json|mix\.exs|Cargo\.toml|vitest\.workspace\.\w+)$"
)
COMMENT_ONLY = re.compile(r"^\s*(#(?![\[!])|//|--|%|/\*|\*|;)")
SKIP = re.compile(
    r"(@(module)?tag\s+:?(skip|focus)\b|@tag\s+(skip|focus):"
    r"|@pytest\.mark\.(skip|skipif|xfail)\b|\bpytestmark\s*=.*\b(skip|xfail)"
    r"|@unittest\.(skip|expectedFailure)\b|\bpytest\.(skip|xfail)\("
    r"|\b(it|describe|test|context)\.(skip|todo|only)\b"
    r"|\b[xf](it|describe|test|context)\s*[(\"']|\bt\.Skip(Now|f)?\("
    r"|@(Disabled|Ignore)\b|#\[ignore\]|\bmarkTestSkipped\("
    r"|ExUnit\.(configure|start)\(.*\b(exclude|only)\b"
    r"|^\s*(skip|pending)(\s*\(|\s+[\"']))"
)


def under_test_dir(path):
    """True when a directory part of the POSIX `path` (every `/`-separated part
    but the last) is a test directory, whatever the file's extension."""
    return any(p in TEST_DIRS for p in path.split("/")[:-1])


def is_test_file(path):
    base = os.path.basename(path)
    if TEST_NAME.search(base):
        return True
    ext = os.path.splitext(base)[1]
    return ext in CODE_EXT and under_test_dir(path)


def code(line):
    """The line, or '' when it is only a comment."""
    return "" if COMMENT_ONLY.match(line) else line
