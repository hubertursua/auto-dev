"""The acceptance checks' lines: committed first, guarded after.

The acceptance tester writes its checks as ordinary test files and `next`
commits them as their own commit before the build (`autodev.py
commit-tests`). A repair, or a fix the user asked for, is committed the same
way, as a later tests commit. Every line a tests commit added is protected:
for each file, the last tests commit that touched it is its reference, and
`git blame` at that commit says which of its lines a tests commit wrote. The
working tree may add lines around them but never change or remove one.

Shared by `check-tests.py --tests-commit` and `autodev.py record` (which
refuses a coder or cleanup return that broke one). Language-blind: it reads
plain line diffs.
"""

import difflib
import re
import subprocess
from pathlib import Path

# A commit id, SHA-1 or SHA-256, at the start of a `git blame --porcelain` line.
BLAME_RE = re.compile(r"^([0-9a-f]{40}|[0-9a-f]{64}) \d+ (\d+)")


class GuardError(Exception):
    """git could not read a tests commit or a file in it."""


def git(wt, *args):
    r = subprocess.run(["git", "-C", str(wt), *args], capture_output=True, check=False)
    if r.returncode != 0:
        raise GuardError(r.stderr.decode("utf-8", "replace").strip()
                         or f"git {' '.join(args)} failed")
    return r.stdout.decode("utf-8", "surrogateescape")


def full_shas(wt, shas):
    out = []
    for sha in shas:
        try:
            out.append(git(wt, "rev-parse", "--verify", "--quiet",
                           f"{sha}^{{commit}}").strip())
        except GuardError:
            raise GuardError(f"tests commit {sha} does not resolve") from None
    return out


def references(wt, shas):
    """{path: the last tests commit (in the order given) that touched it}."""
    last = {}
    for sha in full_shas(wt, shas):
        names = git(wt, "diff-tree", "--root", "--no-commit-id", "-r", "--name-only",
                    "-z", sha)
        for path in names.split("\0"):
            if path:
                last[path] = sha
    return last


def protected(wt, shas):
    """{path: (reference commit, {line numbers at it a tests commit wrote})}."""
    ours = set(full_shas(wt, shas))
    out = {}
    for path, ref in references(wt, shas).items():
        try:
            git(wt, "cat-file", "-e", f"{ref}:{path}")
        except GuardError:
            continue  # the tests commit removed the file: nothing to guard
        # No ignored revisions: every line is blamed on the commit that wrote it.
        blame = git(wt, "blame", "--porcelain", "--ignore-revs-file=", ref, "--", path)
        lines = set()
        for line in blame.splitlines():
            m = BLAME_RE.match(line)
            if m and m.group(1) in ours:
                lines.add(int(m.group(2)))
        out[path] = (ref, lines)
    return out


def text_lines(data):
    """Lines without their endings: a last line with no newline reads the same
    as one with, so appending after it changes nothing above."""
    return data.decode("utf-8", "surrogateescape").splitlines()


def changed_lines(wt, ref, path):
    """The line numbers at `ref` that the working tree changed or removed,
    by content (no textconv, no diff driver)."""
    old = text_lines(git(wt, "cat-file", "blob", f"{ref}:{path}")
                     .encode("utf-8", "surrogateescape"))
    try:
        new = text_lines((Path(wt) / path).read_bytes())
    except OSError:
        return set(range(1, len(old) + 1))
    hit = set()
    matcher = difflib.SequenceMatcher(None, old, new, autojunk=False)
    for op, i1, i2, _j1, _j2 in matcher.get_opcodes():
        if op in ("replace", "delete"):
            hit.update(range(i1 + 1, i2 + 1))
    return hit


def broken(wt, shas):
    """{path: "missing" or the sorted guarded line numbers changed or removed}."""
    out = {}
    for path, (ref, lines) in sorted(protected(wt, shas).items()):
        if not lines:
            continue
        if not (Path(wt) / path).exists():
            out[path] = "missing"
            continue
        hit = sorted(changed_lines(wt, ref, path) & lines)
        if hit:
            out[path] = hit
    return out


def locations(wt, shas):
    """Every broken guarded line as `path:line`, and a gone file as `path`."""
    return sorted(p if hit == "missing" else f"{p}:{n}"
                  for p, hit in broken(wt, shas).items()
                  for n in ([None] if hit == "missing" else hit))


def findings(wt, shas):
    """[(KIND, location, detail)]: ACCEPTANCE_MISSING for a guarded file that
    is gone, ACCEPTANCE_MODIFIED at the first guarded line changed or removed."""
    refs = references(wt, shas) if shas else {}
    out = []
    for path, hit in broken(wt, shas).items():
        ref = refs[path][:12]
        if hit == "missing":
            out.append(("ACCEPTANCE_MISSING", path,
                        f"the acceptance checks committed in {ref} are gone"))
        else:
            out.append(("ACCEPTANCE_MODIFIED", f"{path}:{hit[0]}",
                        (f"{len(hit)} line(s) of the acceptance checks committed in "
                         f"{ref} changed or removed")))
    return out


def untouched(wt, shas):
    """The guarded files the working tree still holds exactly as their tests
    commit left them."""
    out = set()
    for path, ref in references(wt, shas).items():
        try:
            blob = git(wt, "cat-file", "blob", f"{ref}:{path}").encode(
                "utf-8", "surrogateescape")
            if (Path(wt) / path).read_bytes() == blob:
                out.add(path)
        except (GuardError, OSError):
            continue
    return out
