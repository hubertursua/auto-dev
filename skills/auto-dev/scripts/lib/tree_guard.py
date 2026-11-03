"""Hold the workers that never change the repo to that.

`brief` takes a snapshot of the worktree for each worker in GUARDED: HEAD, and
for every path `git status` lists outside the artifact dir, its content (a
blob written to the repo's object store, so it can be put back) or that it
is gone. `record` takes another and compares them. A path that differs is
backed up to <artifact dir>/tree/<worker>-<n>/ and put back as it was at
the brief, and the return is refused naming it.
"""

import os
import shutil
import subprocess
from pathlib import Path

from .output import CANNOT_RUN, Fail

# Workers that run alone and never change a repo file. The code reviewers and
# the security reviewers run side by side, so a change could not be pinned on
# one; the verifier and cleanup run the repo's tests and tools.
GUARDED = ("define", "define-reviewer", "planner", "plan-reviewer", "lookup",
           "review-judge", "triager")
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


def mode_of(full):
    return "100755" if os.access(full, os.X_OK) else "100644"


def blob(worktree, path):
    """The path's bytes as written, with no clean filter, stored in the object store."""
    return git(worktree, "hash-object", "-w", "--no-filters", "--", path).decode().strip()


def snapshot(worktree, ad):
    """HEAD and, for each path `git status` lists, how it is now."""
    worktree = Path(worktree)
    head = git(worktree, "rev-parse", "HEAD").decode().strip()
    files = {}
    for path in listed(worktree, ad):
        full = worktree / path
        if full.is_symlink():
            files[path] = "link " + os.readlink(full)
        elif full.is_file():
            files[path] = f"{blob(worktree, path)} {mode_of(full)}"
        elif full.exists():
            files[path] = SUBMODULE
        else:
            files[path] = None  # deleted
    return {"head": head, "files": files}


def changed(before, after):
    """The paths whose state differs between two snapshots."""
    paths = set(before["files"]) | set(after["files"])
    return sorted(p for p in paths
                  if before["files"].get(p, CLEAN) != after["files"].get(p, CLEAN))


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


def put_back(worktree, before, paths, backup):
    """Copy each path as it is now into `backup`, then restore it as `before`
    has it. Paths that were clean and are new now go last, once the files
    that might have ignored them (a .gitignore) are back: one git ignores
    again was there before, so it stays."""
    worktree = Path(worktree)
    for path in paths:
        full = worktree / path
        if full.is_symlink() or full.is_file():
            copy = backup / path
            copy.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(full, copy, follow_symlinks=False)
    new = []
    for path in paths:
        full = worktree / path
        was = before["files"].get(path, CLEAN)
        if was == SUBMODULE or (full.is_dir() and not full.is_symlink()):
            continue  # left for the user: the issue names it
        if was == CLEAN:
            if at_head(worktree, path):
                remove(full)
                git(worktree, "checkout", "HEAD", "--", path)
            else:
                new.append(path)
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
            full.chmod(0o755 if mode == "100755" else 0o644)
    for path in new:
        if not ignored(worktree, path):
            remove(worktree / path)


def issues(worker, n, before, worktree, ad):
    """Why job <worker>-<n> changed the repo, after putting the change back,
    or [] when the tree is as the brief found it."""
    after = snapshot(worktree, ad)
    if after["head"] != before["head"]:
        return [(f"{worker}-{n} moved HEAD from {before['head'][:12]} to "
                f"{after['head'][:12]} (a commit, checkout or reset); a {worker} never "
                "changes the repo. `record` leaves HEAD where it is: the run can't go "
                "on until HEAD is back where it was")]
    paths = changed(before, after)
    if not paths:
        return []
    backup = Path(ad) / "tree" / f"{worker}-{n}"
    put_back(worktree, before, paths, backup)
    left = changed(before, snapshot(worktree, ad))
    found = (f"{worker}-{n} changed {len(paths)} repo file(s) outside "
             f"{scratch(worktree, ad) or 'the artifact dir'}/: {', '.join(paths)}. A "
             f"{worker} never changes a repo file; write only the files your brief names. "
             f"`record` put them back as they were when you were briefed; the versions it "
             f"found are in {backup}/")
    if left:
        found += f". It could not put back {', '.join(left)}: restore them by hand"
    return [found]
