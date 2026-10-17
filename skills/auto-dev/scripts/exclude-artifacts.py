#!/usr/bin/env python3
"""Make a worktree's .auto-dev/ exclude itself from git, then prove it.

Does exactly the Phase 1 step (references/phase-1-setup.md, step 6, and
references/artifacts.md, _Never commit `.auto-dev/`_): creates
<worktree>/.auto-dev/lint/ if missing and writes .auto-dev/.gitignore containing
`*` if it is absent or holds anything else. Never touches .git/info/exclude.
Then verifies with git that nothing under .auto-dev/ is visible. Running it
twice gives the same result.

Usage:
    python3 <skill-dir>/scripts/exclude-artifacts.py <worktree>
    python3 <skill-dir>/scripts/exclude-artifacts.py --help

<skill-dir> is the auto-dev skill's own directory, not the target repo.
<worktree> is the root of the control worktree (the one Phase 1 created).

Verification (all must hold):
    git -C <worktree> status --porcelain --untracked-files=all -- .auto-dev/
        prints nothing
    git -C <worktree> check-ignore -q .auto-dev/WORK_LOG.md
        succeeds
    git -C <worktree> ls-files -- .auto-dev/
        prints nothing (a tracked file is never ignored, whatever .gitignore says)

Output:
    stdout  what was created or left alone, then `VERIFIED: …`
    stderr  `NOT EXCLUDED: …` with the paths git still sees, or `ERROR: …`

Exit codes:
    0  .auto-dev/ is self-excluding and verified
    1  verification failed — git still sees the printed paths
    2  could not run (git missing, not a git work tree, not the worktree root,
       .auto-dev or its .gitignore not writable) — NOT a pass
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ARTIFACTS = ".auto-dev"
# The same tree the manual step creates (`mkdir -p .auto-dev/lint`): Phase 5
# writes one report per quality-gate check into lint/.
SUBDIRS = ("lint",)
# `*` ignores every file in the directory, .gitignore included, so even a stray
# `git add -A` cannot stage an artifact.
GITIGNORE_BODY = "*\n"
# A file that need not exist yet: check-ignore asks whether it WOULD be ignored.
PROBE = f"{ARTIFACTS}/WORK_LOG.md"

EXIT_OK, EXIT_NOT_EXCLUDED, EXIT_CANNOT_RUN = 0, 1, 2


class CannotRun(Exception):
    """An expected failure that stops the script before verification."""


def git(worktree, *args):
    try:
        return subprocess.run(["git", "-C", str(worktree), *args],
                              capture_output=True, text=True)
    except OSError as exc:
        raise CannotRun(f"could not run git: {exc}")


def check_worktree(worktree):
    if not worktree.is_dir():
        raise CannotRun(f"{worktree} is not a directory")
    result = git(worktree, "rev-parse", "--is-inside-work-tree",
                 "--show-toplevel")
    out = result.stdout.split("\n")
    if result.returncode != 0 or out[0].strip() != "true":
        detail = result.stderr.strip() or "not inside a work tree"
        raise CannotRun(f"{worktree} is not a git work tree ({detail})")
    top = Path(out[1].strip()).resolve()
    # samefile compares device and inode, so a path that differs from git's
    # only in letter case (case-insensitive macOS/Windows file systems) or by a
    # symlink still counts as the root.
    if not top.samefile(worktree):
        # .auto-dev/ belongs at the worktree root, where every later phase
        # looks for it; a subdirectory would put it somewhere nothing reads.
        raise CannotRun(f"{worktree} is inside the work tree {top} but is not "
                        f"its root — pass {top}")


def ensure_exclusion(worktree):
    """Create .auto-dev/ and its .gitignore; return lines saying what changed."""
    notes = []
    root = worktree / ARTIFACTS
    try:
        for sub in ("",) + SUBDIRS:
            path = root / sub if sub else root
            if path.is_dir():
                continue
            path.mkdir(parents=True)
            notes.append(f"created  {path}/")
        ignore = root / ".gitignore"
        current = None
        if ignore.exists():
            try:
                current = ignore.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                current = "<not UTF-8 text>"
        if current is not None and current.strip() == GITIGNORE_BODY.strip():
            notes.append(f"kept     {ignore} (already `*`)")
        else:
            ignore.write_text(GITIGNORE_BODY, encoding="utf-8")
            if current is None:
                notes.append(f"wrote    {ignore} (`*`)")
            else:
                was = current.strip().replace("\n", "\\n") or "<empty>"
                notes.append(f"replaced {ignore} (was: {was[:80]})")
    except OSError as exc:
        raise CannotRun(f"could not prepare {root}: {exc}")
    return notes


def verify(worktree):
    """Return the paths git still sees under .auto-dev/ (empty means verified)."""
    seen = []
    status = git(worktree, "status", "--porcelain", "--untracked-files=all",
                 "--", f"{ARTIFACTS}/")
    if status.returncode != 0:
        raise CannotRun(f"git status failed: {status.stderr.strip()}")
    seen += [f"status:   {line}" for line in status.stdout.splitlines() if line]

    tracked = git(worktree, "ls-files", "--", f"{ARTIFACTS}/")
    if tracked.returncode != 0:
        raise CannotRun(f"git ls-files failed: {tracked.stderr.strip()}")
    seen += [f"tracked:  {line}" for line in tracked.stdout.splitlines() if line]

    ignored = git(worktree, "check-ignore", "-q", PROBE)
    if ignored.returncode == 1:
        seen.append(f"not ignored: {PROBE} (check-ignore exit 1)")
    elif ignored.returncode != 0:
        raise CannotRun(f"git check-ignore failed: {ignored.stderr.strip()}")
    return seen


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
        usage="python3 %(prog)s <worktree>")
    parser.add_argument("worktree", help="root of the control worktree")
    args = parser.parse_args()  # bad arguments exit 2 via argparse
    worktree = Path(args.worktree)

    try:
        if shutil.which("git") is None:
            raise CannotRun("git is not on PATH")
        check_worktree(worktree)
        for note in ensure_exclusion(worktree):
            print(note)
        seen = verify(worktree)
        sys.stdout.flush()  # keep the notes above any stderr verdict
    except CannotRun as exc:
        print(f"ERROR: {exc}. Nothing was verified — this is not a pass.",
              file=sys.stderr)
        return EXIT_CANNOT_RUN

    if seen:
        print(f"NOT EXCLUDED: git still sees {len(seen)} path(s) under "
              f"{worktree / ARTIFACTS}:", file=sys.stderr)
        for line in seen:
            print(f"  {line}", file=sys.stderr)
        if any(line.startswith("tracked:") for line in seen):
            print("  A tracked path stays visible whatever .gitignore says: it "
                  "is committed\n  on the branch this worktree was cut from.",
                  file=sys.stderr)
        print("  Don't write artifacts here until this exits 0.", file=sys.stderr)
        return EXIT_NOT_EXCLUDED

    print(f"VERIFIED: git sees nothing under {worktree / ARTIFACTS}/ and "
          f"ignores {PROBE}.")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
