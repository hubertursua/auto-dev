"""autodev.py commit-tests — commit the acceptance checks as their own commit.

Usage:
    autodev.py commit-tests [--dir <artifact-dir>] [--path <path>]... [--json]

The acceptance tester writes its checks as ordinary test files in the
worktree. Once check-manifest finds no gaps, `next` commits exactly the files
acceptance/MANIFEST.md names, with the subject `test: acceptance checks for
<task>`, and appends the commit to state.json's `tests_commits`. A repair, or a
fix the user asked for that edited a check file, is committed the same way as
a later tests commit. When the repair's or fix's brief kept the check files as
they were (`next` passes them as `before`), only what changed since the brief
goes into the commit, applied to the files at HEAD: lines the coder added to a
shared check file in the meantime stay out of it, and unguarded. When that
change can't be applied on its own, the whole file is committed instead, with
a note saying so. Every line a tests commit added is then guarded
(lib/protected.py, `check-tests.py --tests-commit`). `next` does this itself;
run by hand, it commits and writes state.json the same way, and a `next` after
it finds nothing left to commit. Nothing is pushed: the build's first push
carries the commits.

A tests commit made but not recorded (a run stopped between the two) is
adopted first: each commit since the last recorded one whose subject starts
`test: acceptance checks` and that touches only check files is recorded as a
tests commit, so it is never refused as "no change" nor read as an edit.

A file an earlier tests commit holds that MANIFEST.md no longer names (a check
the user had dropped) is committed too when it changed, its deletion included,
so the guard follows it.

--path limits the commit to those of the files (each must be one MANIFEST.md
names, or one an earlier tests commit holds).

The first tests commit needs a change in every file it commits: a check file
that matches HEAD holds no new check. A later one commits the files that
changed and prints `UNCHANGED` when none did.

Prints `COMMITTED: <sha>` and a `path:` line per file, or `UNCHANGED`.

Exit codes:
    0  COMMITTED or UNCHANGED
    1  refused: MANIFEST.md names no check file, a file is missing from the
       worktree, a --path MANIFEST.md doesn't name, (the first time) a file
       with no change, or a commit hook rejected the commit (its output is
       printed; nothing is left staged)
    2  could not run (no state.json, git failing)
"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import state as st
from .cmd_ship import TRAILER
from .cmd_work import check_files
from .output import CANNOT_RUN, FAILED, Fail, emit
from .proc import git

SUBJECT_TASK = 60  # characters of the task in the subject


def add_arguments(parser):
    parser.add_argument("--dir", default=".auto-dev", help="the run's .auto-dev/")
    parser.add_argument("--path", action="append", default=[])


def subject(state):
    task = " ".join(str(state["task"].get("text") or "the task").split())
    if len(task) > SUBJECT_TASK:
        task = task[:SUBJECT_TASK - 1].rstrip() + "…"
    return f"test: acceptance checks for {task}"


SUBJECT_PREFIX = "test: acceptance checks"


def adopt(state, paths):
    """Record each tests commit made since the last recorded one (or the cut)
    that state.json missed: its subject is a tests commit's and it touches
    only `paths`. Returns the shas adopted."""
    wt = state["worktree"]
    known = [c["sha"] for c in state.get("tests_commits") or []]
    if known:
        since = known[-1]
    else:
        since = ""
        # origin/<base> first, as `cut_commit` reads it: a stale local base
        # branch would reach back past the cut.
        for ref in (f"origin/{state['repo']['base']}", state["repo"]["base"]):
            code, out, _ = git(wt, "merge-base", ref, "HEAD", check=False)
            if code == 0 and out.strip():
                since = out.strip()
                break
    if not since:
        return []
    log = git(wt, "log", "--reverse", "--format=%H%x00%s", f"{since}..HEAD")
    adopted = []
    for line in log.splitlines():
        sha, _, title = line.partition("\0")
        if not title.startswith(SUBJECT_PREFIX) or sha in known:
            continue
        touched = [p for p in git(wt, "diff-tree", "--no-commit-id", "-r", "--name-only",
                                  "-z", sha).split("\0") if p]
        if touched and set(touched) <= set(paths):
            state.setdefault("tests_commits", []).append(
                {"sha": sha, "paths": sorted(touched), "at": st.now()})
            st.add_note(state, f"adopted the tests commit {sha[:12]} state.json missed")
            adopted.append(sha)
    return adopted


def patch_for(wt, path, before):
    """A patch from the file as it was (blob `before`, or absent) to the file
    now, with `path` as its name on both sides; "" when they are the same."""
    tmp = Path(tempfile.mkdtemp(prefix="autodev-patch-"))
    try:
        old = tmp / "old" / path
        new = tmp / "new" / path
        old_arg, new_arg = "/dev/null", "/dev/null"
        if before:
            old.parent.mkdir(parents=True, exist_ok=True)
            old.write_bytes(subprocess.run(["git", "-C", wt, "cat-file", "blob", before],
                                           capture_output=True, check=True).stdout)
            old_arg = f"old/{path}"
        if (Path(wt) / path).is_file():
            new.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(Path(wt) / path, new)
            new_arg = f"new/{path}"
        # No context: the coder's lines around the change are not at HEAD, so
        # context lines would keep the change from applying there.
        r = subprocess.run(["git", "diff", "--no-index", "--no-color", "--no-ext-diff",
                            "--no-textconv", "--binary", "-U0", old_arg, new_arg], cwd=tmp,
                           capture_output=True, check=False)
        if r.returncode not in (0, 1):
            return None
        text = r.stdout.decode("utf-8", "surrogateescape")
        return (text.replace(f"a/old/{path}", f"a/{path}")
                .replace(f"b/new/{path}", f"b/{path}"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def stage(state, wt, index, changed, before):
    """Fill the scratch index (HEAD's tree) with the commit: each file's
    change since `before` alone, where it applies; else the whole file.
    Returns the paths committed whole for want of a clean apply."""
    env = {**os.environ, "GIT_INDEX_FILE": str(index)}
    git_env = ["git", "-C", wt]
    subprocess.run(git_env + ["read-tree", "HEAD"], env=env, capture_output=True,
                   check=True)
    whole = []
    for path in changed:
        if path in before:
            patch = patch_for(wt, path, before[path])
            if patch == "":
                continue
            if patch is not None:
                r = subprocess.run(git_env + ["apply", "--cached", "--recount",
                                              "--unidiff-zero", "-"],
                                   input=patch.encode("utf-8", "surrogateescape"),
                                   env=env, capture_output=True, check=False)
                if r.returncode == 0:
                    continue
            whole.append(path)
        subprocess.run(git_env + ["add", "-A", "--", path], env=env, capture_output=True,
                       check=True)
    if whole:
        st.add_note(state, "the change to " + ", ".join(whole) + " since the brief "
                    "doesn't apply on its own, so the whole file was committed, any "
                    "coder lines in it included")
    return whole


def commit_tests(state, ad, only=None, before=None):
    """Commit the check files; ("COMMITTED", sha, paths) or ("UNCHANGED", None, []).

    `before` ({path: blob or None}, from the repair's or fix's brief): commit
    only what changed in each of those files since."""
    wt = state["worktree"]
    listed = check_files(ad)
    if not listed:
        raise Fail("MANIFEST.md names no check file: there is nothing to commit",
                   FAILED, "REFUSED")
    adopt(state, listed + sorted({p for c in state.get("tests_commits") or []
                                  for p in c["paths"]}))
    earlier = sorted({p for c in state.get("tests_commits") or [] for p in c["paths"]}
                     - set(listed))
    paths = listed + earlier
    if only:
        unknown = sorted(set(only) - set(paths))
        if unknown:
            raise Fail("MANIFEST.md names no check in " + ", ".join(unknown), FAILED,
                       "REFUSED")
        paths = [p for p in paths if p in only]
    missing = [p for p in paths if p in listed and not (Path(wt) / p).is_file()]
    if missing:
        raise Fail("not in the worktree: " + ", ".join(missing), FAILED, "REFUSED")
    status = git(wt, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--",
                 *paths)
    changed = sorted({entry[3:] for entry in status.split("\0") if len(entry) > 3})
    changed = [p for p in paths if p in changed]
    if not state.get("tests_commits"):
        same = [p for p in paths if p not in changed]
        if same:
            raise Fail("no change from HEAD in " + ", ".join(same) + ": a check file "
                       "must hold the tester's new checks", FAILED, "REFUSED")
    if not changed:
        return "UNCHANGED", None, []
    # A scratch index: the commit holds the check files' change and nothing
    # else the real index holds (intent-to-add entries, the coder's work).
    index = Path(ad) / "tmp" / "tests-index"
    index.parent.mkdir(parents=True, exist_ok=True)
    index.unlink(missing_ok=True)
    try:
        stage(state, wt, index, changed, before or {})
        env = {**os.environ, "GIT_INDEX_FILE": str(index)}
        r = subprocess.run(["git", "-C", wt, "commit", "-q", "-m", subject(state), "-m",
                            TRAILER], env=env, capture_output=True, check=False)
    except subprocess.CalledProcessError as exc:
        raise Fail(f"git could not stage the checks: {exc}", CANNOT_RUN, "ERROR") from None
    finally:
        index.unlink(missing_ok=True)
    if r.returncode != 0:  # a hook said no, or git couldn't: nothing was staged
        out = (r.stderr or r.stdout).decode("utf-8", "replace").strip()
        raise Fail(f"git commit failed: {out}", FAILED, "COMMIT-FAILED")
    # The real index follows HEAD for these paths, so none reads as staged.
    git(wt, "reset", "-q", "--", *changed, check=False)
    sha = git(wt, "rev-parse", "HEAD").strip()
    state.setdefault("tests_commits", []).append(
        {"sha": sha, "paths": changed, "at": st.now()})
    st.add_note(state, f"committed the acceptance checks as {sha[:12]} "
                f"({', '.join(changed)})")
    return "COMMITTED", sha, changed


def main(args):
    try:
        state = st.load(args.dir)
    except st.StateError as exc:
        raise Fail(str(exc), CANNOT_RUN, "ERROR") from None
    before = len(state.get("tests_commits") or [])
    token, sha, paths = commit_tests(state, Path(args.dir), args.path or None)
    if token == "COMMITTED" or len(state.get("tests_commits") or []) != before:
        st.save(args.dir, state)
    if token == "COMMITTED":
        emit(args.json, "COMMITTED", sha, path=paths)
    else:
        emit(args.json, "UNCHANGED", "no check file changed since the last tests commit")
    return 0
