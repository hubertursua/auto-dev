"""autodev.py amend-checks — change the held-out acceptance checks for a fix
the user asked for at a stop.

Usage:
    autodev.py amend-checks [--drop "<path> :: <test name>"]...
                            [--sealed <path> --from <file>]...

Only the fixer runs this, and only while the fix the user asked for is open
(`override fix` or `override approve`, then `next` spawned the fixer). The
user's instruction is the consent. This command makes the change in the
checks' own files, so no agent edits acceptance/MANIFEST.md or a sealed copy
by hand.

--drop "<path> :: <test name>"   (repeatable)
    Removes each MANIFEST.md row that names that check: its path and test
    name as the row has them (backticks and quotes are optional). The fixer
    removes the test from the test file itself: once the checks are
    installed, in the worktree's file (`record` reseals it); before that,
    through --sealed. When no row names a file any more and it is a new file
    (it has no files/<path>.base), its sealed copy goes too. Once the checks
    are installed, the file in the worktree goes as well.
--sealed <path> --from <file>   (repeatable, paired in order)
    Before the checks are installed: copies <file> over files/<path>.sealed.
    Refused when the copy changes or removes a line of its base
    (files/<path>.base). After the install, edit the file in the worktree
    instead.

Prints `AMENDED` and a `changed:` line per file it wrote or removed, as the
fixer's report names it (the run's files as `.auto-dev/<path>`).

Exit codes:
    0  AMENDED
    1  refused: no fix is open, a check no row names, --sealed after the
       install or without a matching --from, a sealed copy that doesn't only
       add lines to its base, or nothing to do
    2  could not run (no state.json, an unreadable MANIFEST.md, a file that
       can't be read)
"""

from pathlib import Path

from . import artifacts as art
from . import cmd_checks, overrides, sealed, tree_guard
from . import state as st
from .check_props import CHECK_COLUMN
from .output import CANNOT_RUN, FAILED, Fail, emit


def add_arguments(parser, name=None):
    parser.add_argument("--dir", default=".auto-dev", help="the run's .auto-dev/")
    parser.add_argument("--drop", action="append", default=[],
                        metavar="PATH :: TEST NAME",
                        help="a check to remove from MANIFEST.md (repeatable)")
    parser.add_argument("--sealed", action="append", default=[], metavar="PATH",
                        help="before the install: the check file whose sealed copy "
                             "--from replaces (repeatable)")
    parser.add_argument("--from", dest="source", action="append", default=[],
                        metavar="FILE", help="the new sealed copy for each --sealed")


def refuse(message):
    raise Fail(message, FAILED, "REFUSED")


def parse_check(text):
    """`path` :: "name" (or without the marks) → (path, name)."""
    path, sep, name = text.partition("::")
    if not sep:
        refuse(f"--drop {text!r} is not `<path> :: <test name>`")
    return path.strip().strip("`").strip(), name.strip().strip('"').strip()


def row_check(cell):
    path = art.check_path(cell)
    name = cell.split("::", 1)[-1].strip().strip('"') if "::" in cell else ""
    return (path, name) if path else None


def drop_rows(text, drops):
    """MANIFEST.md's text without the checks table's rows naming a check in
    `drops`; the checks no row named."""
    head, sep, tail = text.partition("## Not automatable")
    lines = head.split("\n")
    header = next((i for i, line in enumerate(lines)
                   if line.startswith("|") and CHECK_COLUMN in line), None)
    if header is None:
        raise Fail("MANIFEST.md has no checks table", CANNOT_RUN, "ERROR")
    cells = [c.strip() for c in lines[header].strip().strip("|").split("|")]
    column = cells.index(CHECK_COLUMN)
    found, kept = set(), []
    for i, line in enumerate(lines):
        if i > header + 1 and line.startswith("|"):
            row = [c.strip() for c in line.strip().strip("|").split("|")]
            check = row_check(row[column]) if len(row) > column else None
            if check in drops:
                found.add(check)
                continue
        kept.append(line)
    return "\n".join(kept) + sep + tail, [d for d in drops if d not in found]


def main(args):
    ad = Path(args.dir)
    try:
        state = st.load(ad)
    except st.StateError as exc:
        raise Fail(str(exc), CANNOT_RUN, "ERROR") from None
    fix = next((o for o in overrides.fixes(state) if o.get("status") == "open"), None)
    if fix is None or not fix.get("job"):
        refuse("no fix is open: only the fixer the user asked for at a stop amends "
               "the checks")
    if not args.drop and not args.sealed:
        refuse("nothing to do: give --drop or --sealed")
    if len(args.sealed) != len(args.source):
        refuse("each --sealed needs its own --from")
    installed = cmd_checks.installed(ad)
    if args.sealed and installed:
        refuse("the checks are installed: edit the check file in the worktree, and "
               "`record` seals it again")
    wt = Path(state["worktree"])
    scratch = tree_guard.scratch(wt, ad) or ".auto-dev"
    files = sealed.sealed_files(ad)
    changed = []

    plans = []
    for rel, source in zip(args.sealed, args.source):
        rel = rel.strip().strip("`")
        body = sealed.read(source)
        if body is None:
            raise Fail(f"cannot read {source}", CANNOT_RUN, "ERROR")
        base = sealed.base_of(ad, rel)
        if base is not None and sealed.blocks(base, sealed.lines(body)) is None:
            refuse(f"{source} changes or removes a line of {rel}; a sealed copy may only "
                   f"add lines to its base: change that line in the worktree's {rel}")
        plans.append((rel, body))

    manifest = ad / "acceptance" / "MANIFEST.md"
    text = None
    if args.drop:
        try:
            text = manifest.read_text(encoding="utf-8")
        except OSError as exc:
            raise Fail(f"cannot read {manifest}: {exc}", CANNOT_RUN, "ERROR") from None
        drops = [parse_check(d) for d in args.drop]
        text, missing = drop_rows(text, drops)
        if missing:
            refuse("no MANIFEST.md row names " + ", ".join(
                f'`{p}` :: "{n}"' for p, n in missing))

    for rel, body in plans:
        target = ad / "acceptance" / "files" / f"{rel}.sealed"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body.encode("utf-8", "surrogateescape"))
        changed.append(f"{scratch}/acceptance/files/{rel}.sealed")
    if text is not None:
        manifest.write_text(text, encoding="utf-8")
        changed.append(f"{scratch}/acceptance/MANIFEST.md")
        rows, _ = art.manifest(manifest)
        named = {c[0] for c in map(row_check, (r[CHECK_COLUMN] for r in rows)) if c}
        for rel in sorted({p for p, _ in drops} - named):
            if rel not in files or sealed.base_of(ad, rel) is not None:
                continue
            files[rel].unlink()
            changed.append(f"{scratch}/acceptance/files/{rel}.sealed")
            snap = sealed.snapshot_path(ad, rel)
            if snap.exists():
                snap.unlink()
            if installed and (wt / rel).is_file():
                (wt / rel).unlink()
                changed.append(rel)
    st.add_note(state, "the fixer amended the checks at the user's instruction: "
                + ", ".join(changed))
    st.save(ad, state)
    emit(args.json, "AMENDED", f"{len(changed)} file(s) changed; name each in your "
         "report's Changed section", changed=changed)
    return 0

