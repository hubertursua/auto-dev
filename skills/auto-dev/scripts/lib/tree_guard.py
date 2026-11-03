"""Hold the workers that never change the repo to that.

`brief` takes a snapshot of the worktree for each worker in GUARDED: HEAD, and
for every path `git status` lists outside the artifact dir, its content (a
blob written to the repo's object store, so it can be put back) or that it
is gone. `record` takes another and compares them. A path that differs is
backed up to <artifact dir>/tree/<worker>-<n>/ and put back as it was at
the brief, and the return is refused naming it. Files git ignores are not
compared.

Only a change the worker could have made counts: `record` skips the check
when anything else may have written to the tree in the meantime (see
cmd_work.tree_issues), and leaves alone a file last written after the
worker's result file.
"""

import os
import shutil
import subprocess
from pathlib import Path

from .output import CANNOT_RUN, Fail

# Workers that run alone and never change a repo file. The code reviewers and
# the security reviewers run side by side, so a change could not be pinned on
# one; the verifier and cleanup run the repo's tests and tools.
# Lookups are left out: the orchestrator sends one to answer the user at a gate,
# while the user may be editing the code.
GUARDED = ("define", "define-reviewer", "planner", "plan-reviewer", "review-judge",
           "triager")
CLEAN = "clean"  # the path matches HEAD: `git status` doesn't list it
SUBMODULE = "dir"


def git(worktree, *args, data=None):
    out = subprocess.run(["git", "-C", str(worktree), *args], input=data,
                         capture_output=True, check=False)
    if out.returncode != 0:
        raise Fail(f"git {' '.join(args[:2])} exited {out.returncode} in {worktree}: "
                   f"{out.stderr.decode('utf-8', 'replace').strip()}", CANNOT_RUN, "ERROR")
    return out.stdout


def scratch(worktree, ad):
    """The artifact dir's path inside the worktree, or None when it lies outside."""
    try:
        return Path(ad).resolve().relative_to(Path(worktree).resolve()).as_posix()
    except ValueError:
        return None


def listed(worktree, ad):
    """The paths `git status` lists (untracked ones included), outside the artifact dir."""
    raw = git(worktree, "status", "--porcelain=v1", "-z", "--untracked-files=all",
              "--no-renames", "--ignore-submodules=none")
    skip = scratch(worktree, ad)
    paths = set()
    for item in raw.decode("utf-8", "surrogateescape").split("\0"):
        path = item[3:]
        if len(item) > 3 and not (skip and (path == skip or path.startswith(skip + "/"))):
            paths.add(path)
    return sorted(paths)


def blobs(worktree, paths):
    """Each path's bytes as written, with no clean filter, stored in the object
    store: one git call for all of them (a path holding a newline goes alone)."""
    plain = [p for p in paths if "\n" not in p]
    ids = []
    if plain:
        data = "".join(p + "\n" for p in plain).encode("utf-8", "surrogateescape")
        ids = git(worktree, "hash-object", "-w", "--no-filters", "--stdin-paths",
                  data=data).decode().split()
    found = dict(zip(plain, ids))
    for path in paths:
        if path not in found:
            found[path] = git(worktree, "hash-object", "-w", "--no-filters", "--",
                              path).decode().strip()
    return found


def snapshot(worktree, ad):
    """HEAD and, for each path `git status` lists, how it is now."""
    worktree = Path(worktree)
    head = git(worktree, "rev-parse", "HEAD").decode().strip()
    files, regular = {}, []
    for path in listed(worktree, ad):
        full = worktree / path
        if full.is_symlink():
            files[path] = "link " + os.readlink(full)
        elif full.is_file():
            regular.append(path)
        elif full.exists():
            files[path] = SUBMODULE
        else:
            files[path] = None  # deleted
    for path, sha in blobs(worktree, regular).items():
        files[path] = f"{sha} {(worktree / path).stat().st_mode & 0o777:o}"
    return {"head": head, "files": files}


def changed(before, after):
    """The paths whose state differs between two snapshots."""
    paths = set(before["files"]) | set(after["files"])
    return sorted(p for p in paths
                  if before["files"].get(p, CLEAN) != after["files"].get(p, CLEAN))


def written_after(full, when):
    """Whether the file at `full` was last written after `when` (a timestamp);
    a path with nothing there now can't say, so it counts as the worker's.
    Where file times are coarse, a worker's own last edit shares its result
    file's time, so it still counts."""
    try:
        return when is not None and full.lstat().st_mtime > when
    except OSError:
        return False


def at_head(worktree, path):
    out = subprocess.run(["git", "-C", str(worktree), "cat-file", "-e", f"HEAD:{path}"],
                         capture_output=True, check=False)
    return out.returncode == 0


def ignored(worktree, path):
    out = subprocess.run(["git", "-C", str(worktree), "check-ignore", "-q", "--", path],
                         capture_output=True, check=False)
    return out.returncode == 0


def remove(full):
    if full.is_symlink() or full.is_file():
        full.unlink()


def clear_up(full, top):
    """Remove the folders between `full` and `top` (included) left empty."""
    folder = full.parent
    while folder != top.parent and folder.is_dir() and not any(folder.iterdir()):
        folder.rmdir()
        folder = folder.parent


def restore(worktree, path, was):
    full = worktree / path
    if was == CLEAN:  # tracked at HEAD (the caller checked)
        remove(full)
        git(worktree, "checkout", "HEAD", "--", path)
    elif was is None:
        remove(full)
    elif was.startswith("link "):
        remove(full)
        full.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(was[len("link "):], full)
    else:
        sha, mode = was.split(" ")
        remove(full)
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_bytes(git(worktree, "cat-file", "blob", sha))
        full.chmod(int(mode, 8))


def put_back(worktree, before, paths, backup):
    """Copy each path as it is now into `backup`, then restore it as `before`
    has it. Returns the paths it could not put back. A new file goes last,
    once the rest (a .gitignore) is back: one git ignores then was there
    before, so it stays. Only a new file standing where a folder must come
    back goes first."""
    worktree = Path(worktree)
    for path in paths:
        full = worktree / path
        if full.is_symlink() or full.is_file():
            copy = backup / path
            copy.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(full, copy, follow_symlinks=False)
    left, new, rest = [], [], []
    for path in paths:
        was = before["files"].get(path, CLEAN)
        if was == CLEAN and not at_head(worktree, path):
            new.append(path)
        else:
            rest.append(path)
    for path in new:  # first, only what stands in the way of a path coming back
        under = next((other for other in rest if path.startswith(other + "/")), None)
        if any(other.startswith(path + "/") for other in rest) or under:
            try:
                remove(worktree / path)
                if under:  # a file turned into a folder: empty it back out
                    clear_up(worktree / path, worktree / under)
            except OSError:
                left.append(path)
    for path in rest:
        full = worktree / path
        was = before["files"].get(path, CLEAN)
        if was == SUBMODULE or (full.is_dir() and not full.is_symlink()):
            left.append(path)
            continue
        try:
            restore(worktree, path, was)
        except (OSError, Fail):
            left.append(path)
    for path in new:
        full = worktree / path
        if full.exists() and not ignored(worktree, path):
            try:
                remove(full)
            except OSError:
                left.append(path)
    return sorted(set(left))


def issues(worker, n, before, worktree, ad, returned_at):
    """Why job <worker>-<n> changed the repo, after putting the change back,
    or [] when the tree is as the brief found it. A file last written after
    `returned_at` (the result file's time) was not the worker's."""
    worktree = Path(worktree)
    after = snapshot(worktree, ad)
    if after["head"] != before["head"]:
        return []  # a commit since the brief: an outside commit, which Phase 6 checks
    paths = [p for p in changed(before, after)
             if not written_after(worktree / p, returned_at)]
    if not paths:
        return []
    backup = Path(ad) / "tree" / f"{worker}-{n}"
    left = put_back(worktree, before, paths, backup)
    found = (f"{worker}-{n} changed {len(paths)} repo file(s) outside "
             f"{scratch(worktree, ad) or 'the artifact dir'}/: {', '.join(paths)}. A "
             f"{worker} never changes a repo file; write only the files your brief names. "
             f"`record` put them back as they were when you were briefed; the versions it "
             f"found are in {backup}/")
    if left:
        found += f". It could not put back {', '.join(left)}: restore them by hand"
    return [found]
