#!/usr/bin/env python3
"""Check a worktree's staged set before a commit: nothing under .auto-dev/, and
optionally exactly the expected paths.

The last check before every Phase 6a commit (references/phase-6-ship.md, step 2)
and every correction-loop commit (references/correction-loop.md). Read-only: it
never stages or unstages anything; it prints the commands that would fix it.

Usage:
    python3 <skill-dir>/scripts/check-staged.py <worktree> [--expect <path> …]
    python3 <skill-dir>/scripts/check-staged.py --help

<skill-dir> is the auto-dev skill's own directory, not the target repo.
<worktree> is the worktree about to commit. Each --expect path is relative to
the worktree root (an absolute path inside it also works); repeat the flag or
list several paths after one. With --expect, the staged set must equal the
expected set exactly — the files the PR gate summary listed.

The staged set is `git -C <worktree> diff --cached --name-only --no-renames`.
`--no-renames` makes a staged rename list both its old (deleted) path and its
new one, as the PR gate's `git status --porcelain --untracked-files=all
--no-renames --ignore-submodules=dirty` list does; without it git lists only the new path, and an
--expect list that names the old path could never match.

An expected path that is neither on disk nor in HEAD is reported as IGNORED,
not MISSING: it was only marked intent-to-add (Phase 5's `git add -N`) and then
deleted, so the commit has nothing to record for it. That is safe only because
--expect also requires that nothing outside .auto-dev/ is left changed but
unstaged (UNSTAGED): a mistyped path is IGNORED, but the real one it should
have named is still unstaged, so the check fails.

Output:
    stdout  `CLEAN: …` and the staged paths; `IGNORED: …` paths, if any
    stderr  `STAGED ARTIFACTS: …`, `MISSING: …`, `EXTRA: …`, `UNSTAGED: …`
            with paths and the fix command, or `ERROR: …`

Exit codes:
    0  clean — nothing under .auto-dev/ staged (and, with --expect, the staged
       set is exactly the expected set and no other change is left unstaged)
    1  not clean — the offending paths are printed; fix and re-run
    2  could not run (git missing, not a git work tree, bad arguments) — NOT a
       pass
"""

import argparse
import posixpath
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

# The scratch directory at the worktree root. `.auto-dev.yml` (the committed
# override) shares the prefix but is a file, so match the directory only.
ARTIFACTS_PREFIX = ".auto-dev/"

EXIT_CLEAN, EXIT_NOT_CLEAN, EXIT_CANNOT_RUN = 0, 1, 2


class CannotRun(Exception):
    """An expected failure that stops the script before it can check."""


def git(worktree, *args):
    try:
        result = subprocess.run(["git", "-C", str(worktree), *args],
                                capture_output=True, text=True)
    except OSError as exc:
        raise CannotRun(f"could not run git: {exc}")
    if result.returncode != 0:
        detail = result.stderr.strip() or f"exit {result.returncode}"
        raise CannotRun(f"`git {' '.join(args)}` failed in {worktree}: {detail}")
    return result.stdout


def never_existed(top, path):
    """True if `path` is neither in the work tree nor in HEAD."""
    if (top / path).exists() or (top / path).is_symlink():
        return False
    result = subprocess.run(["git", "-C", str(top), "cat-file", "-e",
                             f"HEAD:{path}"], capture_output=True)
    return result.returncode != 0


def normalize(path, top):
    """Turn an --expect path into the top-level-relative form git prints."""
    candidate = Path(path)
    if candidate.is_absolute():
        # Resolve the directory only, so a symlinked file keeps its name.
        parent = candidate.parent.resolve()
        for ancestor in (parent, *parent.parents):
            # samefile, not string comparison: a path that differs from git's
            # only in letter case (case-insensitive macOS/Windows file systems)
            # still names the worktree. A deleted directory can't be stat'ed;
            # keep walking up.
            try:
                if ancestor.samefile(top):
                    candidate = (parent / candidate.name).relative_to(ancestor)
                    break
            except OSError:
                continue
        else:
            raise CannotRun(f"--expect {path} is outside the worktree {top}")
    clean = posixpath.normpath(candidate.as_posix())
    if clean in (".", "") or clean.startswith("../"):
        raise CannotRun(f"--expect {path} does not name a file in the worktree")
    return clean


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
        usage="python3 %(prog)s <worktree> [--expect PATH ...]")
    parser.add_argument("worktree", help="the worktree about to commit")
    parser.add_argument("--expect", nargs="+", action="extend", default=None,
                        metavar="PATH",
                        help="the exact set of paths that should be staged")
    args = parser.parse_args()  # bad arguments exit 2 via argparse
    worktree = Path(args.worktree)

    try:
        if shutil.which("git") is None:
            raise CannotRun("git is not on PATH")
        if not worktree.is_dir():
            raise CannotRun(f"{worktree} is not a directory")
        top = Path(git(worktree, "rev-parse", "--show-toplevel").strip()).resolve()
        # -z keeps unusual file names unquoted; paths are top-level-relative.
        # --no-renames: a rename is its deleted old path plus its new path.
        out = git(worktree, "diff", "--cached", "--name-only", "--no-renames",
                  "-z")
        staged = sorted(p for p in out.split("\0") if p)
        expected = (None if args.expect is None
                    else sorted({normalize(p, top) for p in args.expect}))
        # Work-tree changes not staged: `XY path` entries whose Y (work-tree
        # column) is set, or untracked `??`. -z: no quoting, one path each.
        # --ignore-submodules=dirty: a submodule with only dirty content shows
        # as ` M sub` but nothing can stage it; a new submodule commit still
        # shows, and `git add sub` stages that.
        status = git(worktree, "status", "--porcelain", "-z",
                     "--untracked-files=all", "--no-renames",
                     "--ignore-submodules=dirty")
        unstaged = sorted(e[3:] for e in status.split("\0")
                          if len(e) > 3 and e[1] != " "
                          and not e[3:].startswith(ARTIFACTS_PREFIX))
    except CannotRun as exc:
        print(f"ERROR: {exc}. Nothing was checked — this is not a pass.",
              file=sys.stderr)
        return EXIT_CANNOT_RUN

    failed = False
    artifacts = [p for p in staged if p.startswith(ARTIFACTS_PREFIX)]
    if artifacts:
        failed = True
        print(f"STAGED ARTIFACTS: {len(artifacts)} path(s) under "
              f"{ARTIFACTS_PREFIX} are staged and must never be committed:",
              file=sys.stderr)
        for path in artifacts:
            print(f"  {path}", file=sys.stderr)
        print(f"  Unstage them:\n    git -C {shlex.quote(str(top))} restore "
              f"--staged -- {' '.join(shlex.quote(p) for p in artifacts)}",
              file=sys.stderr)

    if expected is not None:
        missing = [p for p in expected if p not in staged]
        # A file Phase 5 only marked intent-to-add and a later step deleted was
        # never committed and is gone: there is nothing to stage for it.
        vanished = [p for p in missing if never_existed(top, p)]
        missing = [p for p in missing if p not in vanished]
        if vanished:
            print(f"IGNORED: {len(vanished)} expected path(s) are neither on "
                  f"disk nor in HEAD — nothing to commit for them:")
            for path in vanished:
                print(f"  {path}")
        # .auto-dev/ paths are already reported above; don't list them twice.
        extra = [p for p in staged if p not in expected and p not in artifacts]
        if missing:
            failed = True
            print(f"MISSING: {len(missing)} expected path(s) not staged:",
                  file=sys.stderr)
            for path in missing:
                print(f"  {path}", file=sys.stderr)
        if extra:
            failed = True
            print(f"EXTRA: {len(extra)} staged path(s) not in the expected set:",
                  file=sys.stderr)
            for path in extra:
                print(f"  {path}", file=sys.stderr)
            print(f"  If they should not ride into the commit, unstage them:\n"
                  f"    git -C {shlex.quote(str(top))} restore --staged -- "
                  f"{' '.join(shlex.quote(p) for p in extra)}", file=sys.stderr)
        # The summary listed every changed path, so anything still changed
        # but unstaged means the --expect list was wrong (a typo, or a path
        # copied in git's quoted form). Without this, a mistyped deleted path
        # would read as IGNORED and the real deletion would never ship.
        if unstaged:
            failed = True
            print(f"UNSTAGED: {len(unstaged)} path(s) still have changes "
                  f"that are not staged:", file=sys.stderr)
            for path in unstaged:
                print(f"  {path}", file=sys.stderr)
            print("  Stage each one the PR gate summary listed (deleted paths "
                  "with `git rm --cached`), and fix the --expect list to "
                  "match.", file=sys.stderr)

    if failed:
        print("NOT CLEAN: fix the staged set and re-run before committing.",
              file=sys.stderr)
        return EXIT_NOT_CLEAN

    match = ("" if expected is None
             else f", exactly the {len(staged)} expected path(s)")
    print(f"CLEAN: {len(staged)} staged path(s), none under "
          f"{ARTIFACTS_PREFIX}{match}.")
    if not staged:
        print("  Note: nothing is staged, so a commit would be empty.")
    for path in staged:
        print(f"  {path}")
    return EXIT_CLEAN


if __name__ == "__main__":
    sys.exit(main())
