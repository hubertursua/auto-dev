#!/usr/bin/env python3
"""Audit a worktree's test changes against its base: catch tests that were
deleted, skipped, weakened or tampered with, and new tests that assert nothing.

Run by the Phase 5 verifier on every pass (references/subagent-prompts.md,
_Verifier_). Read-only: it never stages, edits or restores anything. Each
finding is a claim for the verifier to judge against SPEC.md — a deleted test
can be right when the spec removes that behavior — except ACCEPTANCE_*, which
is never justified.

Usage:
    python3 <skill-dir>/scripts/check-tests.py <worktree> --base <ref> [--acceptance <dir>]
    python3 <skill-dir>/scripts/check-tests.py --help

<skill-dir> is the auto-dev skill's own directory, not the target repo.
<worktree> is the tree to audit. --base is the ref Phase 1 cut it from
(`origin/<base>`). The change set is the working tree against that ref —
tracked changes from `git diff <ref>`, plus untracked files, which are read
straight from disk (nothing is marked intent-to-add). Paths under `.auto-dev/`
are ignored.

--acceptance is `<artifact-dir>/acceptance`, the held-out checks Phase 3
wrote. Every file under its `files/` directory is the sealed copy of an
acceptance test, at the repo-relative path it is installed at; the installed
file in <worktree> must be byte-identical to it.

Findings (one per line on stdout, tab-separated: KIND, location, detail):
    ACCEPTANCE_MISSING   a sealed acceptance test is not installed
    ACCEPTANCE_MODIFIED  an installed acceptance test differs from its sealed copy
    DELETED_TEST         a test file that exists at the base is gone
    REMOVED_ASSERTION    a line holding an assertion was removed or changed in an existing test
    ADDED_SKIP           a skip / xfail / ignore marker was added to a test
    NO_ASSERTIONS        a new test file defines tests but asserts nothing

Test files are recognized by name (`*_test.*`, `test_*.py`, `*.test.*`,
`*.spec.*`, `*_spec.rb`, `*Test.java` …) or by a code file sitting under a
`test/`, `tests/`, `spec/` or `__tests__/` directory. The assertion and skip
patterns are heuristics across common stacks (ExUnit, pytest/unittest, Jest/
Vitest/Mocha, RSpec/Minitest, Go, Rust, JUnit, PHPUnit): a finding is a lead
to read, and a clean run is not proof the tests are meaningful.

Output:
    stdout  the findings, then `SUMMARY: <n> finding(s)` or `CLEAN: …`
    stderr  `ERROR: …`

Exit codes:
    0  clean — no findings
    1  findings — each needs a justification tied to SPEC.md, or a correction
    2  usage error, not a git worktree, or the base ref does not resolve
    3  an acceptance test is missing or modified — never justified (takes
       precedence over 1)
"""

import argparse
import os
import re
import subprocess
import sys

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
ASSERTION = re.compile(
    r"(\bassert\w*!?|\brefute\w*|\bexpect\s*[({]|\.should\b|\bshould\s*\("
    r"|\bt\.(Error|Errorf|Fatal|Fatalf|Fail|FailNow)\b|\brequire\.\w+\("
    r"|\bassertThat\b|\bpytest\.raises\b|\.to(_not|Be|Equal|Throw|Have)\w*\b"
    r"|\bmust_\w+|\bverify\s*\()"
)
TEST_DEF = re.compile(
    r"(\btest\s+[\"']|\bdescribe\s*[\"'(]|\bit\s*[\"'(]|\bdef\s+test_?\w*"
    r"|\bfunc\s+Test\w+|@Test\b|#\[test\]|\btest\s*\(|\bproperty\s+[\"'])"
)
SKIP = re.compile(
    r"(@(module)?tag\s+:?skip\b|@tag\s+skip:|@pytest\.mark\.(skip|skipif|xfail)\b"
    r"|@unittest\.(skip|expectedFailure)\b|\bpytest\.(skip|xfail)\("
    r"|\b(it|describe|test|context)\.(skip|todo)\b|\bx(it|describe|test|context)\s*[(\"']"
    r"|\bt\.Skip(Now|f)?\(|@(Disabled|Ignore)\b|#\[ignore\]|\bmarkTestSkipped\("
    r"|^\s*(skip|pending)(\s*\(|\s+[\"']|\s*$))"
)
HUNK = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def git(worktree, *args):
    r = subprocess.run(["git", "-C", worktree, *args], capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode("utf-8", "replace").strip() or "git failed")
    return r.stdout.decode("utf-8", "replace")


def is_test_file(path):
    base = os.path.basename(path)
    ext = os.path.splitext(base)[1]
    if TEST_NAME.search(base):
        return True
    parts = path.split("/")[:-1]
    return ext in CODE_EXT and any(p in TEST_DIRS for p in parts)


def read(path):
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("worktree")
    parser.add_argument("--base", required=True)
    parser.add_argument("--acceptance")
    args = parser.parse_args()  # bad arguments exit 2 via argparse
    wt = os.path.abspath(args.worktree)

    try:
        git(wt, "rev-parse", "--is-inside-work-tree")
        try:
            git(wt, "rev-parse", "--verify", "--quiet", args.base + "^{commit}")
        except RuntimeError:
            raise RuntimeError(f"base ref does not resolve: {args.base}")
        status = git(wt, "diff", "--name-status", "--no-renames", "-z", args.base)
        untracked = git(wt, "ls-files", "--others", "--exclude-standard", "-z")
    except (RuntimeError, OSError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    findings = []
    tampered = False

    # Acceptance tests: installed copy must equal the sealed copy.
    sealed = set()
    if args.acceptance:
        root = os.path.join(os.path.abspath(args.acceptance), "files")
        if not os.path.isdir(root):
            print(f"ERROR: no sealed acceptance tests at {root}", file=sys.stderr)
            return 2
        for dirpath, _, names in os.walk(root):
            for n in names:
                src = os.path.join(dirpath, n)
                rel = os.path.relpath(src, root).replace(os.sep, "/")
                sealed.add(rel)
                installed = read(os.path.join(wt, rel))
                if installed is None:
                    findings.append(("ACCEPTANCE_MISSING", rel, "sealed check not installed"))
                    tampered = True
                elif installed != read(src):
                    findings.append(("ACCEPTANCE_MODIFIED", rel, "differs from the sealed copy"))
                    tampered = True

    tokens = status.split("\0")
    changed = [(tokens[i], tokens[i + 1]) for i in range(0, len(tokens) - 1, 2)]
    changed += [("A", p) for p in untracked.split("\0") if p]

    for code, path in changed:
        if path.startswith(".auto-dev/") or not is_test_file(path):
            continue
        if code.startswith("D"):
            findings.append(("DELETED_TEST", path, "test file removed"))
            continue
        if code.startswith("A") and path not in sealed:
            data = read(os.path.join(wt, path))
            if data is None:
                continue
            text = data.decode("utf-8", "replace")
            for n, line in enumerate(text.splitlines(), 1):
                if SKIP.search(line):
                    findings.append(("ADDED_SKIP", f"{path}:{n}", line.strip()[:120]))
            if TEST_DEF.search(text) and not ASSERTION.search(text):
                findings.append(("NO_ASSERTIONS", path, "defines tests, asserts nothing"))
            continue
        if code.startswith("A"):
            continue  # a sealed acceptance test; checked above
        # Modified existing test: inspect the hunks.
        try:
            diff = git(wt, "diff", "-U0", "--no-renames", args.base, "--", path)
        except RuntimeError:
            continue
        old_n = new_n = 0
        for line in diff.splitlines():
            m = HUNK.match(line)
            if m:
                old_n, new_n = int(m.group(1)), int(m.group(2))
                continue
            if line.startswith(("---", "+++")):
                continue
            if line.startswith("-"):
                if ASSERTION.search(line[1:]):
                    findings.append(("REMOVED_ASSERTION", f"{path}:-{old_n}", line[1:].strip()[:120]))
                old_n += 1
            elif line.startswith("+"):
                if SKIP.search(line[1:]):
                    findings.append(("ADDED_SKIP", f"{path}:{new_n}", line[1:].strip()[:120]))
                new_n += 1

    for kind, loc, detail in findings:
        print(f"{kind}\t{loc}\t{detail}")
    if not findings:
        print("CLEAN: no test deletions, skips, removed assertions or assertion-free new tests")
        return 0
    print(f"SUMMARY: {len(findings)} finding(s)")
    return 3 if tampered else 1


if __name__ == "__main__":
    sys.exit(main())
