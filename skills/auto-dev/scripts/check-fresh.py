#!/usr/bin/env python3
"""Check that the pipeline's results were produced on the code as it is now.

Each report that judges the code (SPEC_EVAL.md, every lint/<CHECK>.md,
CODE_REVIEW.md, SECURITY_REVIEW.md) carries a `Tree: <hash>` line: the git tree
hash of the worktree when its writer checked it. This script prints that hash
for a worktree, and compares the reports' stamps with it, so a result checked
on older code is never presented as current (references/artifacts.md, _Stamps:
which code each result checked_). Read-only: it never touches the real index,
the working tree or any branch.

Usage:
    python3 <skill-dir>/scripts/check-fresh.py --print-tree <worktree> [--ref <rev>]
    python3 <skill-dir>/scripts/check-fresh.py <worktree> <artifact-dir> [--ref <rev>] [--phase 5|6]
    python3 <skill-dir>/scripts/check-fresh.py --help

<skill-dir> is the auto-dev skill's own directory, not the target repo.

The tree hash covers every file git would stage with `git add -A`, tracked or
untracked, minus ignored files and anything under .auto-dev/. It is computed
through a copy of the worktree's index, so the real index is left alone (git
does store the files' contents in .git/objects, as `git add` would). A submodule
counts by the commit it has checked out; edits inside it don't count, and nor do
edits inside a nested repository that is not a submodule, or to a file marked
assume-unchanged.
With --ref, the hash is `<rev>^{tree}` instead: the code a commit carries
(`--ref HEAD` after a commit, `--ref origin/<branch>` for what a PR holds).

--phase picks which reports must match:
    5   SPEC_EVAL.md and lint/*.md (the reports Phase 5 writes)
    6   those plus CODE_REVIEW.md and SECURITY_REVIEW.md (the default)
A report that is missing, or has no `Tree:` line holding a hash, counts as
stale: nothing says which code it checked.

Output:
    --print-tree  stdout  the tree hash alone
    compare       stdout  `Tree now: <hash>`, then `FRESH: …` with each report
                  stderr  `STALE: <report>: checked <hash>` and the files changed
                          since then, `NO STAMP: <report>`, `MISSING: <report>`,
                          or `ERROR: …`

Exit codes:
    0  fresh: every report checked exactly this tree (--print-tree: printed it)
    1  stale: at least one report is missing, unstamped or for other code;
       each is listed — re-run what wrote it
    2  could not run (git missing, not a git work tree, unknown --ref, bad
       arguments) — NOT a pass
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

EXIT_FRESH, EXIT_STALE, EXIT_CANNOT_RUN = 0, 1, 2

# The scratch directory: never part of the change, whatever .gitignore says.
ARTIFACTS_DIR = ".auto-dev"

# `Tree: <hash>`, also as a list item or in bold: `- **Tree:** `<hash>``.
# SHA-1 trees are 40 hex digits, SHA-256 trees 64.
STAMP_LINE = re.compile(r"^[\s>*-]*(?:\*\*)?Tree:(?:\*\*)?\s*(.*)$")
HASH = re.compile(r"`?([0-9a-f]{64}|[0-9a-f]{40})`?")

# Shown on stderr for each stale report: enough to scope a re-review.
MAX_PATHS_SHOWN = 50


def shown(path):
    """A path as printable text, whatever bytes its name holds."""
    return path.encode("utf-8", "surrogateescape").decode("utf-8", "replace")


class CannotRun(Exception):
    """An expected failure that stops the script before it can check."""


def git(cwd, *args, env=None):
    try:
        # surrogateescape: a file name that isn't valid UTF-8 must not crash
        # the check (a crash would exit 1, which reads as "stale", not 2).
        result = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True,
                                text=True, errors="surrogateescape", env=env,
                                check=False)
    except OSError as exc:
        raise CannotRun(f"could not run git: {exc}") from None
    if result.returncode != 0:
        detail = result.stderr.strip() or f"exit {result.returncode}"
        raise CannotRun(f"`git {' '.join(args)}` failed in {cwd}: {detail}")
    return result.stdout


def working_tree_hash(top):
    """The tree `git add -A` would record, written through a temporary index."""
    index = Path(git(top, "rev-parse", "--git-path", "index").strip())
    if not index.is_absolute():
        index = top / index
    tmpdir = tempfile.mkdtemp(prefix="check-fresh-")
    try:
        temp_index = Path(tmpdir) / "index"
        # Start from the real index, not an empty one: it keeps skip-worktree
        # entries (sparse checkouts) and uninitialized submodules, which have
        # nothing on disk for `git add` to find. Keep its mtime (copy2): git
        # re-reads a file changed in the same second as the index was written
        # only because the index's mtime says so. A fresh mtime makes it trust
        # the cached stat and miss a same-size edit.
        if index.exists():
            shutil.copy2(index, temp_index)
        env = {**os.environ, "GIT_INDEX_FILE": str(temp_index)}
        git(top, "add", "-A", "--", ".", f":(exclude){ARTIFACTS_DIR}/", env=env)
        # Drop anything under .auto-dev/ the real index somehow held.
        git(top, "rm", "-r", "-q", "--cached", "--ignore-unmatch", "--",
            f"{ARTIFACTS_DIR}/", env=env)
        return git(top, "write-tree", env=env).strip()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def ref_tree_hash(top, ref):
    return git(top, "rev-parse", "--verify", "--quiet", f"{ref}^{{tree}}").strip()


def read_stamp(path):
    """The hash on the report's first `Tree:` line, or None."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for line in text.splitlines():
        m = STAMP_LINE.match(line)
        if m:
            h = HASH.fullmatch(m.group(1).strip())
            return h.group(1) if h else None
    return None


def changed_since(top, old, new):
    """Files that differ between two trees, or None if `old` isn't in the repo."""
    try:
        git(top, "cat-file", "-e", f"{old}^{{tree}}")
        out = git(top, "diff", "--name-only", "--no-renames", "-z", old, new)
    except CannotRun:
        return None
    return sorted(p for p in out.split("\0") if p)


def reports(artifact_dir, phase):
    """The reports that must match, in the order the pipeline writes them."""
    lint = sorted((artifact_dir / "lint").glob("*.md"))
    found = [artifact_dir / "SPEC_EVAL.md", *(lint or [artifact_dir / "lint" / "*.md"])]
    if phase == "6":
        found += [artifact_dir / "CODE_REVIEW.md", artifact_dir / "SECURITY_REVIEW.md"]
    return found


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
        usage="python3 %(prog)s (--print-tree <worktree> | <worktree> <artifact-dir>) "
              "[--ref REV] [--phase 5|6]")
    parser.add_argument("worktree", help="the worktree whose code is checked")
    parser.add_argument("artifact_dir", nargs="?",
                        help="the run's .auto-dev/ directory (or tasks/<id>)")
    parser.add_argument("--print-tree", action="store_true",
                        help="print the tree hash and exit")
    parser.add_argument("--ref", metavar="REV",
                        help="use the tree of this commit instead of the working tree")
    parser.add_argument("--phase", choices=("5", "6"), default="6",
                        help="which reports must match (default 6: all of them)")
    args = parser.parse_args()  # bad arguments exit 2 via argparse
    worktree = Path(args.worktree)

    try:
        if args.print_tree and args.artifact_dir:
            raise CannotRun("--print-tree takes only a worktree")
        if not args.print_tree and not args.artifact_dir:
            raise CannotRun("name the artifact directory, or pass --print-tree")
        if shutil.which("git") is None:
            raise CannotRun("git is not on PATH")
        if not worktree.is_dir():
            raise CannotRun(f"{worktree} is not a directory")
        top = Path(git(worktree, "rev-parse", "--show-toplevel").strip()).resolve()
        if args.ref:
            try:
                now = ref_tree_hash(top, args.ref)
            except CannotRun:
                raise CannotRun(f"--ref {args.ref} does not name a commit here") from None
        else:
            now = working_tree_hash(top)
        artifact_dir = None if args.print_tree else Path(args.artifact_dir)
        if artifact_dir is not None and not artifact_dir.is_dir():
            raise CannotRun(f"{artifact_dir} is not a directory")
    except CannotRun as exc:
        print(f"ERROR: {exc}. Nothing was checked — this is not a pass.",
              file=sys.stderr)
        return EXIT_CANNOT_RUN

    if args.print_tree:
        print(now)
        return EXIT_FRESH

    print(f"Tree now: {now}" + (f" ({args.ref})" if args.ref else " (working tree)"))
    fresh, stale = [], False
    for path in reports(artifact_dir, args.phase):
        name = path.relative_to(artifact_dir).as_posix()
        if not path.is_file():
            stale = True
            print(f"MISSING: {name} does not exist", file=sys.stderr)
            continue
        stamp = read_stamp(path)
        if stamp is None:
            stale = True
            print(f"NO STAMP: {name} has no `Tree: <hash>` line, so nothing says "
                  f"which code it checked", file=sys.stderr)
        elif stamp != now:
            stale = True
            print(f"STALE: {name}: checked {stamp}", file=sys.stderr)
            paths = changed_since(top, stamp, now)
            if paths is None:
                print("  changed since: unknown (that tree is not in this repo)",
                      file=sys.stderr)
            else:
                print(f"  changed since: {len(paths)} file(s)", file=sys.stderr)
                for p in paths[:MAX_PATHS_SHOWN]:
                    print(f"    {shown(p)}", file=sys.stderr)
                if len(paths) > MAX_PATHS_SHOWN:
                    print(f"    … and {len(paths) - MAX_PATHS_SHOWN} more",
                          file=sys.stderr)
        else:
            fresh.append(name)

    if stale:
        print("NOT FRESH: re-run what wrote each report above, then check again "
              "(references/correction-loop.md, _Stale results_).", file=sys.stderr)
        return EXIT_STALE
    print(f"FRESH: {len(fresh)} report(s) checked this tree:")
    for name in fresh:
        print(f"  {name}")
    return EXIT_FRESH


if __name__ == "__main__":
    sys.exit(main())
