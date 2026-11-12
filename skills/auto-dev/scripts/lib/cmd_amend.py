"""autodev.py amend-checks — change the held-out acceptance checks for a fix
the user asked for at a stop.

Usage:
    autodev.py amend-checks [--drop "<path> :: <test name>"]...
                            [--row "| <#> | … |"]...
                            [--not-automatable "| <#> | … |"]...
                            [--add <path>]...
                            [--sealed <path> --from <file>]...

Only the fixer runs this, and only while the fix the user asked for is open
(`override fix` or `override approve`, then `next` spawned the fixer, and
`record` has not taken its result yet). The user's instruction is the
consent. This command makes the change in the checks' own files, so no agent
edits acceptance/MANIFEST.md or a sealed copy by hand. "Installed" below
means acceptance/INSTALLED exists: the checks are in the worktree.

--drop "<path> :: <test name>"   (repeatable)
    Removes each MANIFEST.md row that names that check: its path and test
    name as the row has them (backticks and quotes are optional). The fixer
    takes the test out of the test file itself: once installed, in the
    worktree's file (`record` reseals it); before, through --sealed. When no
    row names a file any more and it is a new file (it has no
    files/<path>.base), its sealed copy goes too, and, once installed, the
    file in the worktree. `record` refuses the fixer's result while a dropped
    test is still in its file, or when a condition that had a check has none
    left and no Not automatable row (and is still in SPEC.md).
--row "| <#> | <condition> | `<path>` :: \"<test name>\" | … |"   (repeatable)
    Adds a row to the checks table, with as many cells as its header. A
    rename is a --drop of the old name and a --row with the new one.
--not-automatable "| <#> | … |"   (repeatable)
    Adds a row to the Not automatable table (made from the template's header
    when the section says None).
--add <path>   (repeatable)
    Once installed: seals the worktree's <path>, a new check file, whole as
    files/<path>.sealed. Refused when it already has a sealed copy.
--sealed <path> --from <file>   (repeatable, paired in order)
    Before the install: copies <file> over files/<path>.sealed. Refused when
    the copy changes or removes a line of its base (files/<path>.base).
    Once installed, edit the file in the worktree instead.

Everything is checked before anything is written. Prints `AMENDED` and a
`changed:` line per file it wrote or removed, as the fixer's report names it
(the run's files as `.auto-dev/<path>`).

Exit codes:
    0  AMENDED
    1  refused: no fix is open, a check no row names, a row with the wrong
       number of cells, --sealed once installed or --add before, a path
       outside the repo, a sealed copy that doesn't only add lines to its
       base, or nothing to do
    2  could not run (no state.json, an unreadable MANIFEST.md, a file that
       can't be read or written)
"""

from pathlib import Path, PurePosixPath

from . import artifacts as art
from . import overrides, sealed, tree_guard
from . import state as st
from .check_props import CHECK_COLUMN
from .output import CANNOT_RUN, FAILED, Fail, emit

NA_HEADER = ("| # | Condition | Why no check can drive it | Proxy a verifier can run |\n"
             "|---|-----------|---------------------------|--------------------------|")


def add_arguments(parser, name=None):
    parser.add_argument("--dir", default=".auto-dev", help="the run's .auto-dev/")
    parser.add_argument("--drop", action="append", default=[],
                        metavar="PATH :: TEST NAME",
                        help="a check to remove from MANIFEST.md (repeatable)")
    parser.add_argument("--row", action="append", default=[], metavar="ROW",
                        help="a row to add to MANIFEST.md's checks table (repeatable)")
    parser.add_argument("--not-automatable", dest="na_row", action="append", default=[],
                        metavar="ROW",
                        help="a row to add to MANIFEST.md's Not automatable table")
    parser.add_argument("--add", action="append", default=[], metavar="PATH",
                        help="once installed: seal a new check file whole (repeatable)")
    parser.add_argument("--sealed", action="append", default=[], metavar="PATH",
                        help="before the install: the check file whose sealed copy "
                             "--from replaces (repeatable)")
    parser.add_argument("--from", dest="source", action="append", default=[],
                        metavar="FILE", help="the new sealed copy for each --sealed")


def refuse(message):
    raise Fail(message, FAILED, "REFUSED")


def installed(ad):
    return (Path(ad) / "acceptance" / "INSTALLED").exists()


def unmark(text):
    return text.strip().strip("`").strip().strip('"').strip()


def repo_path(text):
    rel = text.strip().strip("`").strip()
    parts = PurePosixPath(rel).parts
    if not rel or PurePosixPath(rel).is_absolute() or ".." in parts or "\\" in rel:
        refuse(f"{text!r} is not a path inside the repo")
    return rel


def parse_check(text):
    """`path` :: "name" (or without the marks) → (path, name)."""
    path, sep, name = text.partition("::")
    if not sep:
        refuse(f"--drop {text!r} is not `<path> :: <test name>`")
    return repo_path(path), unmark(name)


def row_check(cell):
    path = art.check_path(cell)
    return (path, unmark(cell.split("::", 1)[1])) if path and "::" in cell else None


def open_fix(state):
    """The fix the fixer is working on now: open, spawned, and not recorded."""
    fix = next((o for o in overrides.fixes(state) if o.get("status") == "open"), None)
    if fix is None or not fix.get("job"):
        return None
    first = fix["job"][1]
    if any(e["worker"] == "fixer" and e["n"] >= first for e in state.get("log", [])):
        return None
    return fix


def find_table(lines, start, end, column):
    """The index of the header line of the table, within lines[start:end],
    whose header has `column`; None."""
    for i in range(start, min(end, len(lines)) - 1):
        if lines[i].lstrip().startswith("|") and column in art.split_row(lines[i]) \
                and art.SEPARATOR_RE.match(lines[i + 1].strip()):
            return i
    return None


def table_end(lines, header):
    i = header + 2
    while i < len(lines) and lines[i].lstrip().startswith("|"):
        i += 1
    return i


def checked_row(text, header_line, what):
    width = len(art.split_row(header_line))
    cells = art.split_row(text, width)
    if not text.strip().startswith("|") or len(cells) != width:
        refuse(f"{what} {text!r} needs {width} cells, as the table's header has")
    return text.strip()


def amend_manifest(text, drops, rows, na_rows):
    """MANIFEST.md's text with the drops and the new rows; the drops no row
    named."""
    lines = text.split("\n")
    na_at = next((i for i, line in enumerate(lines)
                  if line.strip().lower().startswith("## not automatable")), len(lines))
    header = find_table(lines, 0, na_at, CHECK_COLUMN)
    if header is None:
        raise Fail("MANIFEST.md has no checks table", CANNOT_RUN, "ERROR")
    names = art.split_row(lines[header])
    column = names.index(CHECK_COLUMN)
    end = table_end(lines, header)
    found, body = set(), []
    for line in lines[header + 2:end]:
        cells = art.split_row(line, len(names))
        check = row_check(cells[column]) if len(cells) > column else None
        if check in drops:
            found.add(check)
            continue
        body.append(line)
    body += [checked_row(r, lines[header], "--row") for r in rows]
    lines = lines[:header + 2] + body + lines[end:]
    if na_rows:
        na_at = next((i for i, line in enumerate(lines)
                      if line.strip().lower().startswith("## not automatable")), None)
        if na_at is None:
            raise Fail("MANIFEST.md has no Not automatable section", CANNOT_RUN, "ERROR")
        next_head = next((i for i in range(na_at + 1, len(lines))
                          if lines[i].startswith("## ")), len(lines))
        na_header = find_table(lines, na_at + 1, next_head, "#")
        if na_header is None:  # "None.": the template's table, with these rows
            new = NA_HEADER.split("\n")
            new += [checked_row(r, new[0], "--not-automatable") for r in na_rows]
            lines = lines[:na_at + 1] + [""] + new + [""] + lines[next_head:]
        else:
            end = table_end(lines, na_header)
            new = [checked_row(r, lines[na_header], "--not-automatable") for r in na_rows]
            lines = lines[:end] + new + lines[end:]
    return "\n".join(lines), [d for d in drops if d not in found]


def main(args):
    ad = Path(args.dir)
    try:
        state = st.load(ad)
    except st.StateError as exc:
        raise Fail(str(exc), CANNOT_RUN, "ERROR") from None
    fix = open_fix(state)
    if fix is None:
        refuse("no fix is open: only the fixer the user asked for at a stop amends "
               "the checks, before its result is recorded")
    if not (args.drop or args.row or args.na_row or args.add or args.sealed):
        refuse("nothing to do: give --drop, --row, --not-automatable, --add or --sealed")
    if len(args.sealed) != len(args.source):
        refuse("each --sealed needs its own --from")
    on = installed(ad)
    if args.sealed and on:
        refuse("the checks are installed: edit the check file in the worktree, and "
               "`record` seals it again")
    if args.add and not on:
        refuse("the checks are not installed: write a new check file's sealed copy "
               "with --sealed")
    wt = Path(state["worktree"])
    scratch = tree_guard.scratch(wt, ad) or ".auto-dev"
    files = sealed.sealed_files(ad)
    root = ad / "acceptance" / "files"
    writes, removes = {}, []  # {Path: bytes}, [Path]

    for rel in args.add:
        rel = repo_path(rel)
        if rel in files:
            refuse(f"{rel} has a sealed copy already: `record` reseals an edit to it")
        body = sealed.read(wt / rel)
        if body is None:
            refuse(f"{rel} is not in the worktree: write the new check file first")
        writes[root / f"{rel}.sealed"] = body.encode("utf-8", "surrogateescape")
    for rel, source in zip(args.sealed, args.source):
        rel = repo_path(rel)
        body = sealed.read(source)
        if body is None:
            raise Fail(f"cannot read {source}", CANNOT_RUN, "ERROR")
        base = sealed.base_of(ad, rel)
        if base is not None and sealed.blocks(base, sealed.lines(body)) is None:
            refuse(f"{source} changes or removes a line of {rel}; a sealed copy may only "
                   f"add lines to its base: change that line in the worktree's {rel}")
        writes[root / f"{rel}.sealed"] = body.encode("utf-8", "surrogateescape")

    manifest = ad / "acceptance" / "MANIFEST.md"
    drops = [parse_check(d) for d in args.drop]
    if drops or args.row or args.na_row:
        try:
            raw = manifest.read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise Fail(f"cannot read {manifest}: {exc}", CANNOT_RUN, "ERROR") from None
        crlf = "\r\n" in raw
        text, missing = amend_manifest(raw.replace("\r\n", "\n"), drops, args.row,
                                       args.na_row)
        if missing:
            refuse("no MANIFEST.md row names " + ", ".join(
                f'`{p}` :: "{n}"' for p, n in missing))
        writes[manifest] = (text.replace("\n", "\r\n") if crlf else text).encode("utf-8")
        rows, _ = art.manifest_text(text)
        named = {c[0] for c in map(row_check, (r[CHECK_COLUMN] for r in rows)) if c}
        for rel in sorted({p for p, _ in drops} - named):
            if rel in files and sealed.base_of(ad, rel) is None \
                    and root / f"{rel}.sealed" not in writes:
                removes += [files[rel], sealed.snapshot_path(ad, rel)]
                if on:
                    removes.append(wt / rel)

    changed = []
    try:
        for path, data in writes.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        for path in removes:
            if path.exists():
                path.unlink()
    except OSError as exc:
        raise Fail(f"could not write the checks: {exc}", CANNOT_RUN, "ERROR") from None
    for path in list(writes) + removes:
        if path.name.endswith(".installed"):
            continue
        try:
            shown = f"{scratch}/{path.relative_to(ad).as_posix()}"
        except ValueError:
            shown = path.relative_to(wt).as_posix()
        if shown not in changed:
            changed.append(shown)
    fix.setdefault("dropped", [])
    fix["dropped"] += [list(d) for d in drops if list(d) not in fix["dropped"]]
    st.add_note(state, "the fixer amended the checks at the user's instruction: "
                + ", ".join(changed))
    st.save(ad, state)
    emit(args.json, "AMENDED", f"{len(changed)} file(s) changed; name each in your "
         "report's Changed section", changed=changed)
    return 0
