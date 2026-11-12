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


def test_keys(names):
    """Each test name MANIFEST.md lists, and its last part when that is long
    enough to mean something: a runner can name a test by its whole path
    (`todos > shows the due date`, `TestX/case`, `file::test[param]`) where the
    source holds only the last part."""
    keys = set()
    for name in names:
        name = name.strip()
        if name:
            keys.add(name)
            last = re.sub(r"\[[^\]]*\]$", "", re.split(r" > |::|/", name)[-1]).strip()
            if len(last) >= 8:
                keys.add(last)
    return keys


def support_runs(ad, rel, names):
    """[(lines, into_tests)]: per run of lines the sealed check adds to <path>
    (a block), the lines besides its tests (`names`), blank ones included: the
    whole run when it names no test, else the part before its first line
    naming one (`into_tests`: the run goes on into the tests). An import line
    the checks need is one: a worker told only the tests' names can't tell it
    is sealed. [] when no line of the sealed copy names a test: then nothing
    says where the tests start."""
    sealed_lines = lines(read(sealed_files(ad)[rel])) or []
    keys = test_keys(names)

    def names_one(line):
        return any(k in line for k in keys)

    if not any(names_one(x) for x in sealed_lines):
        return []
    runs = []
    for _k, body in blocks(base_of(ad, rel), sealed_lines) or []:
        cut = next((i for i, line in enumerate(body) if names_one(line)), None)
        run = body if cut is None else body[:cut]
        if any(x.strip() for x in run):
            runs.append((run, cut is not None))
    return runs


def broken_runs(ad, rel, current):
    """[{lines, changed, after}]: each run of lines the sealed check adds to
    <path> that `current` (the worktree's text) no longer holds whole: its
    lines, the non-blank ones `current` lacks, and the base line it follows
    (None at the top or in a new file)."""
    now = lines(current) or []
    have = set(now)
    base = base_of(ad, rel) or []
    out = []
    for k, body in blocks(base, lines(read(sealed_files(ad)[rel])) or []) or []:
        n = len(body)
        if any(now[i:i + n] == body for i in range(len(now) - n + 1)):
            continue
        out.append({"lines": body, "after": base[k - 1] if 0 < k <= len(base) else None,
                    "changed": [x for x in body if x.strip() and x not in have]})
    return out


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


def reseal(ad, rel, old_sealed, old_base, current, names=()):
    """Seal <path> again after a fixer edited it in the worktree, so it never
    keeps the seal by hand. `old_sealed` and `old_base` are the sealed copy and
    base before the edit (the file was its sealed copy then); `current` is the
    file now, None when it was removed; `names` are its checks' test names.

    Each line of the file now is a check's or the file's own. A line the edit
    kept keeps its kind, and so does one it rewrote in place (paired in order
    within a changed run). A line it added is a check's when the line it
    follows in that run was one, when it is inserted next to one, or when the
    lines it came with name a check's test; otherwise it is the file's own,
    and goes into the base. It is a best guess: a misread line is held out
    too much (the coder can't edit it) or too little. The file becomes
    the sealed copy. When no check line is left, or the file is gone, the seal
    files go. Returns the seal files it wrote or removed, as paths under
    acceptance/files/."""
    files = Path(ad) / "acceptance" / "files"
    seal, base_file, snap = files / f"{rel}.sealed", base_path(ad, rel), snapshot_path(ad, rel)
    touched = [f"{rel}.sealed", f"{rel}.base"]

    def drop():
        for path in (seal, base_file, snap):
            if path.exists():
                path.unlink()
        return touched

    if current is None:
        return drop()
    if current == old_sealed:  # the file is as it was: so is its seal
        Path(seal).write_bytes(old_sealed.encode("utf-8", "surrogateescape"))
        if old_base is None:
            return []
        base_file.write_bytes(old_base.encode("utf-8", "surrogateescape"))
        return []
    if old_base is None:  # a new file: all of it is the check
        Path(seal).write_bytes(current.encode("utf-8", "surrogateescape"))
        return touched[:1]
    was, base0, now = lines(old_sealed) or [], lines(old_base) or [], lines(current)
    blks = blocks(base0, was)
    if blks is None:
        return []  # the seal was broken before the edit; `record` says so
    check, at = [False] * len(was), 0
    for k, body in blks:
        check[k + at:k + at + len(body)] = [True] * len(body)
        at += len(body)
    keys = test_keys(names)
    kinds, ai = [], 0
    for a0, ac, b0, bc in hunks(was, now):
        kinds += check[ai:a0]
        # Lines rewritten in place keep their kind, in order; lines past the
        # old ones take the last old line's kind, or, for an insertion, a
        # check's when either neighbour is one; any naming a check's test is one.
        paired = min(ac, bc)
        kinds += check[a0:a0 + paired]
        if bc > paired:
            extra = now[b0 + paired:b0 + bc]
            if ac:
                is_check = check[a0 + ac - 1]
            else:
                is_check = (a0 > 0 and check[a0 - 1]) or (a0 < len(was) and check[a0])
            is_check = is_check or any(k in line for line in extra for k in keys)
            kinds += [is_check] * len(extra)
        ai = a0 + ac
    kinds += check[ai:]
    if not any(kinds):
        return drop()
    write(base_file, [x for x, c in zip(now, kinds) if not c], current)
    Path(seal).write_bytes(current.encode("utf-8", "surrogateescape"))
    snapshot(ad, rel, current)
    return touched


def snapshot(ad, rel, current):
    """Remember a shared file as it is with its checks whole (`undo_edits`)."""
    write(snapshot_path(ad, rel), lines(current), current)
