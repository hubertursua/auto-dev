"""Sealed acceptance checks, and how they go into the worktree.

A sealed check is acceptance/files/<path>.sealed: the test file as the
acceptance tester left it. Its base, acceptance/files/<path>.base, is the file
it added to (the file at HEAD when the tester sealed it, or the coder's file
when the tester folded its tests into it). A check with no base is a new file.

A sealed copy may only add lines to its base, so it is a list of blocks: lines
inserted before a base line. Installing puts each block back into the file now
in the worktree, next to the base line it followed, and leaves every other line
alone. That is how the coder's own tests and the held-out checks share one file.

Lines are compared without their line ending; files are written with `\\n`
between lines and a final newline when the file they replace had one.
"""

import re
import subprocess
import tempfile
from pathlib import Path

HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


class SealError(Exception):
    """git could not diff two versions of a file."""


def lines(text):
    if text is None:
        return None
    parts = text.split("\n")
    return parts[:-1] if parts and parts[-1] == "" else parts


def read(path):
    try:
        return Path(path).read_bytes().decode("utf-8", "surrogateescape")
    except OSError:
        return None


def write(path, body, like=None):
    """Write `body` (lines) to `path`, ending with a newline unless `like`, the
    text it replaces, had none."""
    end = "" if like is not None and like and not like.endswith("\n") else "\n"
    data = "\n".join(body) + (end if body else "")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data.encode("utf-8", "surrogateescape"))


def sealed_files(ad):
    """{repo-relative path: sealed copy} for every sealed check."""
    root = Path(ad) / "acceptance" / "files"
    return {str(s.relative_to(root).with_suffix("")).replace("\\", "/"): s
            for s in sorted(root.rglob("*.sealed"))} if root.is_dir() else {}


def base_path(ad, rel):
    return Path(ad) / "acceptance" / "files" / f"{rel}.base"


def base_of(ad, rel):
    """The lines the sealed copy adds to, or None for a new file."""
    return lines(read(base_path(ad, rel)))


def hunks(old, new):
    """git's line diff of two line lists: [(old start, old count, new start,
    new count)], 0-based. A hunk with an old count of 0 inserts before old
    line `old start`."""
    if old == new:
        return []
    with tempfile.TemporaryDirectory() as tmp:
        a, b = Path(tmp) / "a", Path(tmp) / "b"
        for path, body in ((a, old), (b, new)):
            path.write_bytes(("".join(f"{x}\n" for x in body)).encode(
                "utf-8", "surrogateescape"))
        r = subprocess.run(["git", "diff", "--no-index", "--no-color", "--no-ext-diff",
                            "--no-textconv", "-U0", "a", "b"],
                           cwd=tmp, capture_output=True, check=False)
    if r.returncode not in (0, 1):
        raise SealError(r.stderr.decode("utf-8", "replace").strip() or "git diff failed")
    out = []
    for line in r.stdout.decode("utf-8", "surrogateescape").splitlines():
        m = HUNK.match(line)
        if m:
            a0, ac = int(m.group(1)), int(m.group(2) or 1)
            b0, bc = int(m.group(3)), int(m.group(4) or 1)
            out.append((a0 if ac == 0 else a0 - 1, ac, b0 if bc == 0 else b0 - 1, bc))
    return out


def blocks(base, sealed):
    """[(k, lines)]: the lines the sealed copy inserts before base line k. None
    when it changes or removes a base line. A new file is one block."""
    if not base:
        return [(0, list(sealed))] if sealed else []
    out = []
    for a0, ac, b0, bc in hunks(base, sealed):
        if ac:
            return None
        out.append((a0, sealed[b0:b0 + bc]))
    return out


def locate(current, blks):
    """Where each block sits in `current`, in order, each one whole; None when one
    is missing or changed. It matches by content: a block that repeats lines
    already in the file (a one-line import the coder also wrote) can be found
    there, so it proves a check is whole, not where it came from."""
    starts, at = [], 0
    for _k, body in blks:
        n = len(body)
        found = next((i for i in range(at, len(current) - n + 1)
                      if current[i:i + n] == body), None)
        if found is None:
            return None
        starts.append(found)
        at = found + n
    return starts


def strip(current, blks, starts):
    """`current` without the blocks `locate` found."""
    drop = set()
    for (_k, body), s in zip(blks, starts):
        drop.update(range(s, s + len(body)))
    return [x for i, x in enumerate(current) if i not in drop]


def place(target, base, blks):
    """`target` with each block inserted after the base line it followed (or
    before the one it preceded, when that one was changed). None when the lines
    on both sides of a block changed: nothing says where it goes."""
    if not blks:
        return list(target)
    if not base:
        return list(blks[0][1]) if not any(x.strip() for x in target) else None
    where, run, ai, bi = {}, {}, 0, 0
    for n, (a0, ac, b0, bc) in enumerate(hunks(base, target) + [(len(base), 0, 0, 0)]):
        while ai < a0:
            where[ai], run[ai] = bi, n
            ai, bi = ai + 1, bi + 1
        ai, bi = a0 + ac, b0 + bc
    # A run of unchanged lines anchors a block only if one of them says
    # something: `});` or a blank line alone matches anywhere.
    real = {run[i] for i in run if any(ch.isalnum() for ch in base[i])}

    def anchor(i):
        return i in where and run[i] in real

    spots = []
    for i, (k, body) in enumerate(blks):
        if k > 0 and anchor(k - 1):
            pos = where[k - 1] + 1
        elif k < len(base) and anchor(k):
            pos = where[k]
        elif k == 0:
            pos = 0
        elif k == len(base):
            pos = len(target)
        else:
            return None
        spots.append((pos, i, body))
    out = list(target)
    for pos, _i, body in sorted(spots, reverse=True):
        out[pos:pos] = body
    return out


def snapshot_path(ad, rel):
    return Path(ad) / "acceptance" / "files" / f"{rel}.installed"


def undo_edits(current, snap, blks):
    """`current` with every edit since `snap` that touched a block undone: the
    other edits stay. `snap` is the file as it was the last time its blocks were
    whole. None when they weren't whole in it either."""
    starts = locate(snap, blks)
    if starts is None:
        return None
    spans = [(s, s + len(body)) for (_k, body), s in zip(blks, starts)]

    def touches(a0, ac):
        if ac:
            return any(a0 < e and a0 + ac > s for s, e in spans)
        return any(s < a0 < e for s, e in spans)

    out, ai = [], 0
    for a0, ac, b0, bc in hunks(snap, current):
        out += snap[ai:a0]
        out += snap[a0:a0 + ac] if touches(a0, ac) else current[b0:b0 + bc]
        ai = a0 + ac
    return out + snap[ai:]


def installed_text(ad, rel, current, recheck=False):
    """What <path> should hold with its sealed check in: (lines, conflict).
    Lines are None when nothing needs writing. `current` is the file's text in
    the worktree, None when it is absent. With `recheck`, a check that was edited
    is put back: a new file whole, a shared one by undoing the edits that
    touched it since the snapshot taken when it was last whole."""
    sealed = lines(read(sealed_files(ad)[rel]))
    base = base_of(ad, rel)
    if current is None:
        return (None, True) if base else (sealed, False)
    now = lines(current)
    if now == sealed:
        return None, False
    blks = blocks(base, sealed)
    if blks is None:
        return None, True
    if locate(now, blks) is not None:
        return None, False
    if recheck:
        if not base:
            return sealed, False
        snap = lines(read(snapshot_path(ad, rel)))
        merged = undo_edits(now, snap, blks) if snap is not None else None
    else:
        merged = place(now, base, blks)
    if merged is None or locate(merged, blks) is None:
        return None, True
    return merged, False


def intact(ad, rel, current):
    """True when the worktree's <path> holds its sealed check unchanged."""
    if current is None:
        return False
    sealed = lines(read(sealed_files(ad)[rel]))
    now = lines(current)
    if now == sealed:
        return True
    blks = blocks(base_of(ad, rel), sealed)
    return blks is not None and locate(now, blks) is not None


def adds_only(ad, rel):
    """None when the sealed copy only adds lines to its base, else why not."""
    base = base_of(ad, rel)
    if base is None:
        return None
    if blocks(base, lines(read(sealed_files(ad)[rel]))) is None:
        return (f"files/{rel}.sealed changes or removes a line of {rel}; an acceptance "
                "check may only add lines to a file that exists")
    return None


def rebase(ad, rel, current):
    """Make the worktree's file, without the checks in it, the base, and the
    file itself the sealed copy, so a repair in place re-seals against the
    coder's lines as they are now. False when the checks aren't whole in it."""
    sealed = lines(read(sealed_files(ad)[rel]))
    now = lines(current) if current is not None else None
    if now is None:
        return False
    blks = blocks(base_of(ad, rel), sealed)
    starts = locate(now, blks) if blks is not None else None
    if starts is None:
        return False
    write(base_path(ad, rel), strip(now, blks, starts), current)
    # The blocks are whole, so the file is the new base plus the same blocks.
    Path(sealed_files(ad)[rel]).write_bytes(current.encode("utf-8", "surrogateescape"))
    snapshot(ad, rel, current)
    return True


def snapshot(ad, rel, current):
    """Remember a shared file as it is with its checks whole (`undo_edits`)."""
    write(snapshot_path(ad, rel), lines(current), current)
