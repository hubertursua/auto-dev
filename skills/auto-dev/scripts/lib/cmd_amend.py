"""autodev.py amend-checks — change the acceptance checks' MANIFEST.md for a fix
the user asked for at a stop.

Usage:
    autodev.py amend-checks [--drop "<path> :: <test name>"]...
                            [--row "| <#> | … |"]...
                            [--not-automatable "| <#> | … |"]...

Only the fixer runs this, and only while the fix the user asked for is open
(`override fix` or `override approve`, then `next` spawned the fixer, and
`record` has not taken its result yet). The user's instruction is the
consent. The fixer edits the check files in the worktree itself; this command
makes the matching change to acceptance/MANIFEST.md, so no agent edits it by
hand. Once the fixer's FIXED result is recorded, `next` commits the check files
it edited as a new tests commit (`commit-tests`), which they are guarded
against from then on.

--drop "<path> :: <test name>"   (repeatable)
    Removes each MANIFEST.md row that names that check: its path and test
    name as the row has them (backticks and quotes are optional). The fixer
    takes the test out of the file itself. `record` refuses the fixer's result
    while a dropped test is still in its file, or when a condition that had a
    check has none left and no Not automatable row (and is still in PLAN.md).
--row "| <#> | <condition> | `<path>` :: \"<test name>\" | … |"   (repeatable)
    Adds a row to the checks table, with as many cells as its header. A
    rename is a --drop of the old name and a --row with the new one.
--not-automatable "| <#> | … |"   (repeatable)
    Adds a row to the Not automatable table (made from the template's header
    when the section says None).

Everything is checked before anything is written. Prints `AMENDED` and a
`changed:` line for MANIFEST.md, as the fixer's report names it
(`.auto-dev/acceptance/MANIFEST.md`).

Exit codes:
    0  AMENDED
    1  refused: no fix is open, a check no row names, a row with the wrong
       number of cells, a path outside the repo, or nothing to do
    2  could not run (no state.json, an unreadable MANIFEST.md)
"""

from pathlib import Path, PurePosixPath

from . import artifacts as art
from . import overrides, tree_guard
from . import state as st
from .output import CANNOT_RUN, FAILED, Fail, emit

CHECK_COLUMN = "Check (path :: test name)"

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


def refuse(message):
    raise Fail(message, FAILED, "REFUSED")


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
    cells = art.split_row(text)
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
            rest = [line for line in lines[end:next_head]  # a "None." under the table
                    if line.strip().rstrip(".").lower() != "none"]
            lines = lines[:end] + new + rest + lines[next_head:]
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
    if not (args.drop or args.row or args.na_row):
        refuse("nothing to do: give --drop, --row or --not-automatable")
    wt = Path(state["worktree"])
    scratch = tree_guard.scratch(wt, ad) or ".auto-dev"
    manifest = ad / "acceptance" / "MANIFEST.md"
    drops = [parse_check(d) for d in args.drop]
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
    try:
        manifest.write_bytes((text.replace("\n", "\r\n") if crlf else text).encode("utf-8"))
    except OSError as exc:
        raise Fail(f"could not write {manifest}: {exc}", CANNOT_RUN, "ERROR") from None
    changed = [f"{scratch}/acceptance/MANIFEST.md"]
    fix.setdefault("dropped", [])
    fix["dropped"] += [list(d) for d in drops if list(d) not in fix["dropped"]]
    st.add_note(state, "the fixer amended the checks at the user's instruction: "
                + ", ".join(changed))
    st.save(ad, state)
    emit(args.json, "AMENDED", f"{len(changed)} file(s) changed; name each in your "
         "report's Changed section", changed=changed)
    return 0
