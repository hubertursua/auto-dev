#!/usr/bin/env python3
"""Audit a worktree's test changes against its base: catch tests that were
deleted, skipped, focused, weakened or tampered with, and new tests that assert
nothing.

Run by the Phase 5 verifier on every pass (agents/verifier.md). Read-only: it
never stages, edits or restores anything. Each
finding is a claim for the verifier to judge against SPEC.md — a deleted test
can be right when the spec removes that behavior — except ACCEPTANCE_*, which
is never justified.

Usage:
    python3 <skill-dir>/scripts/check-tests.py <worktree> --base <ref> [--acceptance <dir>]
    python3 <skill-dir>/scripts/check-tests.py --help

<skill-dir> is the auto-dev skill's own directory, not the target repo.
<worktree> is the tree to audit. --base is the ref Phase 1 cut it from
(`origin/<base>`). The change set is the working tree against that ref:
`git diff <ref>` (which includes files marked intent-to-add), plus untracked
files, read straight from disk. Paths under `.auto-dev/` are ignored.

--acceptance is `<artifact-dir>/acceptance`, the held-out checks Phase 3
wrote. Each file under its `files/` directory is the sealed copy of one check,
stored at `<repo-relative install path>.sealed` so no test runner collects it;
the installed file in <worktree> must be byte-identical to it.

Findings (one per line on stdout, tab-separated: KIND, location, detail):
    ACCEPTANCE_MISSING   a sealed acceptance test is not installed
    ACCEPTANCE_MODIFIED  an installed acceptance test differs from its sealed copy
    DELETED_TEST         a test file that exists at the base is gone (and was
                         not renamed: a rename is diffed as an edit instead)
    REMOVED_ASSERTION    a line holding an assertion was removed or changed in
                         an existing (or renamed) test
    ADDED_SKIP           a skip / xfail / ignore / focus (`.only`, `fit`,
                         `@tag :focus`) marker was added to a test
    NO_ASSERTIONS        a new test file defines tests but asserts nothing
    TEST_CONFIG_CHANGED  a file that can configure the test runner changed
                         (runner configs, test helpers, and manifests such as
                         pyproject.toml, package.json, mix.exs, Cargo.toml): it
                         can exclude or skip tests without touching a test file;
                         the verifier judges whether this change does

Test files are recognized by name (`*_test.*`, `test_*.py`, `*.test.*`,
`*.spec.*`, `*_spec.rb`, `*Test.java` …) or by a code file sitting under a
`test/`, `tests/`, `spec/` or `__tests__/` directory. The assertion and skip
patterns are heuristics across common stacks (ExUnit, pytest/unittest, Jest/
Vitest/Mocha, RSpec/Minitest, Go, Rust, JUnit, PHPUnit); comment-only lines are
ignored. A finding is a lead to read, and a clean run is not proof the tests
are meaningful.

Output:
    stdout  the findings, then `SUMMARY: <n> finding(s)` or `CLEAN: …`
    stderr  `ERROR: …`

Exit codes:
    0  clean — no findings
    1  findings — each needs a justification tied to SPEC.md, or a correction
    2  usage error, not a git worktree, the base ref does not resolve, or no
       `files/` directory under --acceptance (an empty one is fine: every
       condition was not automatable)
    3  an acceptance test is missing or modified — never justified (takes
       precedence over 1)
"""

import argparse
import difflib
import os
import re
import subprocess
import sys

SEALED_SUFFIX = ".sealed"
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
ASSERTION = re.compile(
    r"(\bassert(_\w+|[A-Z]\w*|!|\b)|\brefute(_\w+|\b)|\bexpect\s*[({]"
    r"|\.should\b|\bshould\s*\(|\bt\.(Error|Errorf|Fatal|Fatalf|Fail|FailNow)\b"
    r"|\brequire\.\w+\(|\bpytest\.raises\b|\.to(_not|Be|Equal|Throw|Have)\w*\b"
    r"|\bmust_\w+|\bverify\s*\()"
)
TEST_DEF = re.compile(
    r"(\btest\s+[\"']|\bdescribe\s*[\"'(]|\bit\s*[\"'(]|\bdef\s+test_?\w*"
    r"|\bfunc\s+Test\w+|@Test\b|#\[test\]|\btest\s*\(|\bproperty\s+[\"'])"
)
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
HUNK = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def git(worktree, *args):
    r = subprocess.run(["git", "-C", worktree, *args], capture_output=True, check=False)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode("utf-8", "replace").strip() or "git failed")
    return r.stdout.decode("utf-8", "replace")


def is_test_file(path):
    base = os.path.basename(path)
    if TEST_NAME.search(base):
        return True
    ext = os.path.splitext(base)[1]
    return ext in CODE_EXT and any(p in TEST_DIRS for p in path.split("/")[:-1])


def code(line):
    """The line, or '' when it is only a comment."""
    return "" if COMMENT_ONLY.match(line) else line


def read(path):
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        return None


def edit_findings(old_path, path, old_lines, new_lines, findings):
    """Removed/changed assertions and added skips between two versions.
    A removed line is reported at its old path and line; an added one at its new."""
    sm = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op in ("replace", "delete"):
            for n in range(i1, i2):
                if ASSERTION.search(code(old_lines[n])):
                    findings.append(("REMOVED_ASSERTION", f"{old_path}:-{n + 1}",
                                     old_lines[n].strip()[:120]))
        if op in ("replace", "insert"):
            for n in range(j1, j2):
                if SKIP.search(code(new_lines[n])):
                    findings.append(("ADDED_SKIP", f"{path}:{n + 1}", new_lines[n].strip()[:120]))


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
            raise RuntimeError(f"base ref does not resolve: {args.base}") from None
        status = git(wt, "diff", "--name-status", "--no-renames", "-z", args.base)
        untracked = git(wt, "ls-files", "--others", "--exclude-standard", "-z")
    except (RuntimeError, OSError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    findings = []
    tampered = False

    # Acceptance tests: each installed copy must equal its sealed copy.
    sealed = set()
    if args.acceptance:
        root = os.path.join(os.path.abspath(args.acceptance), "files")
        for dirpath, _, names in os.walk(root):
            for n in names:
                if not n.endswith(SEALED_SUFFIX):
                    continue
                src = os.path.join(dirpath, n)
                rel = os.path.relpath(src, root).replace(os.sep, "/")[: -len(SEALED_SUFFIX)]
                sealed.add(rel)
                installed = read(os.path.join(wt, rel))
                if installed is None:
                    findings.append(("ACCEPTANCE_MISSING", rel, "sealed check not installed"))
                    tampered = True
                elif installed != read(src):
                    findings.append(("ACCEPTANCE_MODIFIED", rel, "differs from the sealed copy"))
                    tampered = True
        if not os.path.isdir(root):
            print(f"ERROR: no sealed-checks directory at {root}", file=sys.stderr)
            return 2
        # An empty files/ is valid: every condition was not automatable.

    tokens = status.split("\0")
    changed = []
    for i in range(0, len(tokens) - 1, 2):
        c, p = tokens[i][:1], tokens[i + 1]
        if c == "T":  # type change (e.g. file -> symlink): judge as removed + new
            changed += [("D", p), ("A", p)]
        else:
            changed.append((c, p))
    changed += [("A", p) for p in untracked.split("\0") if p]
    changed = [(c, p) for c, p in changed if not p.startswith(".auto-dev/")]

    for _c, path in changed:
        if TEST_CONFIG.search(path):
            findings.append(("TEST_CONFIG_CHANGED", path, "runner config or test helper changed"))

    tests = [(c, p) for c, p in changed if is_test_file(p) and p not in sealed]
    added = {p: (read(os.path.join(wt, p)) or b"").decode("utf-8", "replace")
             for c, p in tests if c == "A"}
    paired = set()

    for c, path in tests:
        if c == "D":
            try:
                old = git(wt, "show", f"{args.base}:{path}")
            except RuntimeError:
                old = ""
            # A deleted test whose lines mostly reappear in a new file is a
            # rename: diff it as an edit so a weakened assertion cannot hide
            # behind it. Compare sets of non-blank lines (cheap, and two
            # unrelated files share few exact lines).
            old_set = {ln.strip() for ln in old.splitlines() if ln.strip()}
            best, ratio = None, 0.0
            for p, text in added.items():
                if p in paired or not old_set:
                    continue
                new_set = {ln.strip() for ln in text.splitlines() if ln.strip()}
                r = len(old_set & new_set) / max(len(old_set), len(new_set), 1)
                if r > ratio:
                    best, ratio = p, r
            if best and ratio >= 0.6:
                paired.add(best)
                edit_findings(path, best, old.splitlines(), added[best].splitlines(), findings)
            else:
                findings.append(("DELETED_TEST", path, "test file removed"))
        elif c == "M":
            try:
                diff = git(wt, "diff", "-U0", "--no-renames", args.base, "--", path)
            except RuntimeError:
                continue
            old_n = new_n = 0
            in_hunk = False
            for line in diff.splitlines():
                m = HUNK.match(line)
                if m:
                    old_n, new_n = int(m.group(1)), int(m.group(2))
                    in_hunk = True
                    continue
                if not in_hunk:  # the file header (---/+++ lines) precedes every hunk
                    continue
                if line.startswith("-"):
                    if ASSERTION.search(code(line[1:])):
                        findings.append(("REMOVED_ASSERTION", f"{path}:-{old_n}",
                                         line[1:].strip()[:120]))
                    old_n += 1
                elif line.startswith("+"):
                    if SKIP.search(code(line[1:])):
                        findings.append(("ADDED_SKIP", f"{path}:{new_n}", line[1:].strip()[:120]))
                    new_n += 1

    for path, text in added.items():
        if path in paired:
            continue
        lines = text.splitlines()
        for n, line in enumerate(lines, 1):
            if SKIP.search(code(line)):
                findings.append(("ADDED_SKIP", f"{path}:{n}", line.strip()[:120]))
        body = "\n".join(code(ln) for ln in lines)
        if TEST_DEF.search(body) and not ASSERTION.search(body):
            findings.append(("NO_ASSERTIONS", path, "defines tests, asserts nothing"))

    for kind, loc, detail in findings:
        print(f"{kind}\t{loc}\t{detail}")
    if not findings:
        print("CLEAN: no test deletions, skips, removed assertions or assertion-free new tests")
        return 0
    print(f"SUMMARY: {len(findings)} finding(s)")
    return 3 if tampered else 1


if __name__ == "__main__":
    sys.exit(main())
