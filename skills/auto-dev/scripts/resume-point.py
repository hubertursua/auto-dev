#!/usr/bin/env python3
"""Find where an interrupted auto-dev run resumes, from its WORK_LOG.md ledger.

Reads <artifact-dir>/WORK_LOG.md (template and resume procedure in
references/artifacts.md) and reports the first phase whose status is not
complete, the session that phase belongs to, and the remaining iteration budget.
It never writes anything.

Usage:
    python3 <skill-dir>/scripts/resume-point.py <artifact-dir> [--task "<text>"]
    python3 <skill-dir>/scripts/resume-point.py --help

<skill-dir> is the auto-dev skill's own directory, not the target repo.
<artifact-dir> is the control worktree's `.auto-dev/` directory.

--task checks that the ledger belongs to the current task. A Jira key (it
matches `^[A-Z][A-Z0-9_]+-\\d+$`, ignoring case) must appear as a whole token in
the header's Ticket line — `PROJ-12` matches `PROJ-12 https://…/browse/PROJ-12`
but not `PROJ-123`; a Jira issue URL (`…/browse/PROJ-12`) is matched by its key
the same way. Any other text matches when, ignoring case and runs of
whitespace, it appears in the header's Task line or in the ask the Ticket line
restates (the text after ` — `), or one of those appears in it.

On a multi-PR ledger a sub-task's phase table, where it has one, decides; one
with no phase table goes by its summary `status`: `done`, `skipped` or `n/a` is
complete, `blocked` is reported for the user to decide, `pending` begins at
Phase 2, and `in-progress` is MALFORMED (a started sub-task has a table).

Output:
    stdout  `RESUME: …` plus task, ticket, mode, phase and status, session, what
            the status means, and budget; or `COMPLETE: …` when nothing is left
    stderr  `MISSING: …`, `MALFORMED: …` (naming the line or field),
            `MISMATCH: …`, or `ERROR: …`

Exit codes:
    0  resume point found (printed), including a blocked phase or sub-task
       — its Action line says to ask the user
    1  WORK_LOG.md missing or malformed, or --task does not match its header
    2  could not run (bad arguments, not a directory, file unreadable) — NOT a
       result; read the ledger by hand
    3  every phase is done, skipped or n/a — nothing to resume
"""

import argparse
import re
import sys
from pathlib import Path

LEDGER = "WORK_LOG.md"

# Exit codes, as the docstring and the docs that call this script list them.
EXIT_FOUND, EXIT_BAD_LEDGER, EXIT_CANNOT_RUN, EXIT_COMPLETE = 0, 1, 2, 3

# The `status` values references/artifacts.md allows. A phase is complete when
# it finished (`done`), was deliberately bypassed (`skipped`), or cannot apply
# (`n/a`); resume step 3 restarts at the first phase with any other status.
STATUSES = {"pending", "in-progress", "done", "skipped", "n/a", "blocked"}
COMPLETE = {"done", "skipped", "n/a"}

# What resume step 3 says to do at each incomplete status, so the caller does
# not have to re-open the procedure to act on the output.
ACTIONS = {
    "pending": "run the phase normally",
    "in-progress": ("the phase was cut off mid-flight: re-run the whole phase "
                    "and overwrite its artifact; never resume inside it"),
    "blocked": ("do not retry: report the recorded reason (Notes) to the "
                "user and ask"),
}
# Resume step 4: Phase 6 is reconciled against git and gh before acting.
PHASE_6_NOTE = ("Phase 6: check the world before acting (git log, git status, "
                "whether the branch is on the remote, gh pr view) and reconcile "
                "the ledger to it")

# Which session holds each phase (SKILL.md, Session boundaries).
SESSIONS = {1: "S1 — Plan", 2: "S1 — Plan", 3: "S1 — Plan",
            4: "S2 — Build", 5: "S2 — Build", 6: "S3 — Ship"}
# A sub-task with no phase table never started; it begins here (resume step 5).
SUBTASK_FIRST_PHASE = 2
# A bare Jira key passed to --task (e.g. PROJ-123); matched as a whole token.
JIRA_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]+-\d+$", re.IGNORECASE)
# What separates tokens on the Ticket line: anything that can't be in a key,
# so `PROJ-123` is a token in `PROJ-123`, `…/browse/PROJ-123` and `[PROJ-123]`.
TOKEN_SPLIT_RE = re.compile(r"[^A-Za-z0-9_-]+")
# A Jira issue URL passed to --task (`…/browse/PROJ-123`); its key is matched.
BROWSE_KEY_RE = re.compile(r"/browse/([A-Za-z][A-Za-z0-9_]+-\d+)(?:[^A-Za-z0-9_-]|$)")

# Header fields the template requires; Mode decides which table to read.
REQUIRED_FIELDS = ("Task", "Ticket", "Mode")
MODES = ("single-PR", "multi-PR")

# `- **Repo:** x   **Base:** y` holds several fields on one line.
FIELD_RE = re.compile(r"\*\*([^*]+?):\*\*\s*(.*?)(?=\s+\*\*[^*]+?:\*\*|$)")
# `<n> total revise rounds (<n> remaining)` on a single-PR header.
BUDGET_RE = re.compile(r"(\d+)\s+total\b.*?\((\d+)\s+remaining\)")
# `<remaining>/<total>` in a multi-PR sub-task's `budget` cell.
CELL_BUDGET_RE = re.compile(r"^(\d+)\s*/\s*(\d+)$")
SEPARATOR_RE = re.compile(r"^\|?[\s:|-]+\|?$")


class LedgerError(Exception):
    """WORK_LOG.md does not follow the template; the message says where."""


def norm(text):
    return re.sub(r"\s+", " ", text).strip().lower()


def split_row(line, width):
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    # A stray `|` in the last column (Notes / PR) must not shift the others.
    if width and len(cells) > width:
        cells = cells[:width - 1] + [" | ".join(cells[width - 1:])]
    return cells


def read_table(lines, start, where):
    """Parse the table that begins at or after `lines[start]`.

    Returns (header cells, [(line number, {column: cell})]).
    """
    i = start
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i >= len(lines) or not lines[i].lstrip().startswith("|"):
        raise LedgerError(f"line {start}: no table under {where}")
    header = split_row(lines[i], 0)
    i += 1
    if i < len(lines) and SEPARATOR_RE.match(lines[i].strip()):
        i += 1
    rows = []
    while i < len(lines) and lines[i].lstrip().startswith("|"):
        cells = split_row(lines[i], len(header))
        if len(cells) != len(header):
            raise LedgerError(
                f"line {i + 1}: row has {len(cells)} cells, the {where} header "
                f"has {len(header)}")
        rows.append((i + 1, dict(zip(header, cells))))
        i += 1
    return header, rows


def require_columns(header, needed, where, line_no):
    missing = [c for c in needed if c not in header]
    if missing:
        raise LedgerError(
            f"line {line_no}: the {where} table has no "
            f"{', '.join(f'`{c}`' for c in missing)} column (has: "
            f"{', '.join(header)}) — the template's column names are fixed")


def heading_index(lines, text, level="##"):
    for i, line in enumerate(lines):
        if line.strip() == f"{level} {text}":
            return i
    return None


def parse_header(lines):
    fields = {}
    for line in lines:
        if line.startswith("## "):
            break
        if line.lstrip().startswith("- **"):
            for name, value in FIELD_RE.findall(line):
                fields[name.strip()] = value.strip()
    for name in REQUIRED_FIELDS:
        if not fields.get(name):
            raise LedgerError(
                f"header: missing the `- **{name}:**` field (the template "
                f"requires {', '.join(REQUIRED_FIELDS)})")
    mode = fields["Mode"].split()[0]
    if mode not in MODES:
        raise LedgerError(
            f"header: Mode is `{fields['Mode']}`, expected one of "
            f"{', '.join(MODES)}")
    fields["Mode"] = mode
    return fields


def task_matches(wanted, fields):
    """Whether the --task value names this ledger's task (see the docstring)."""
    wanted = wanted.strip()
    url_key = BROWSE_KEY_RE.search(wanted)
    if url_key:  # a Jira issue URL matches as its key, never as a substring
        wanted = url_key.group(1)
    if JIRA_KEY_RE.match(wanted):
        # Strip `_` from token ends so a markdown-italic `_PROJ-12_` still counts.
        tokens = {t.strip("_")
                  for t in TOKEN_SPLIT_RE.split(fields["Ticket"].lower())}
        return wanted.lower() in tokens
    wanted = norm(wanted)
    if not wanted:
        return False
    # Free text matches the Task line or the ask the Ticket line restates
    # (after ` — `) — never the key, link or a bare "none" before it.
    ask = fields["Ticket"].partition(" — ")[2]
    return any(wanted in have or have in wanted
               for have in (norm(fields["Task"]), norm(ask))
               if have)


def first_open_phase(rows, where):
    """Return (phase number, phase name, status, notes) or None if complete."""
    for line_no, row in rows:
        status = row["Status"].lower()
        if status not in STATUSES:
            raise LedgerError(
                f"line {line_no}: Status `{row['Status']}` in the {where} table "
                f"is not one of {', '.join(sorted(STATUSES))}")
        try:
            number = int(row["#"])
        except ValueError:
            raise LedgerError(
                f"line {line_no}: phase number `{row['#']}` in the {where} "
                f"table is not 1–6")
        if number not in SESSIONS:
            raise LedgerError(
                f"line {line_no}: phase number {number} in the {where} table "
                f"is not 1–6")
        if status not in COMPLETE:
            return number, row["Phase"], status, row.get("Notes", "")
    return None


def phase_rows(lines, index, where):
    header, rows = read_table(lines, index + 1, where)
    require_columns(header, ("#", "Phase", "Status"), where, index + 1)
    if not rows:
        raise LedgerError(f"line {index + 1}: the {where} table has no rows")
    return rows


def single_pr(lines, fields):
    index = heading_index(lines, "Phase status")
    if index is None:
        raise LedgerError("no `## Phase status` heading — a single-PR ledger "
                          "needs its phase table under it")
    found = first_open_phase(phase_rows(lines, index, "Phase status"),
                             "Phase status")
    match = BUDGET_RE.search(fields.get("Iteration budget", ""))
    budget = (f"{match.group(2)} remaining of {match.group(1)}" if match
              else "not recorded")
    return None, found, budget


def multi_pr(lines):
    index = heading_index(lines, "Sub-tasks")
    if index is None:
        raise LedgerError("Mode is multi-PR but there is no `## Sub-tasks` "
                          "heading with the sub-task table")
    header, rows = read_table(lines, index + 1, "Sub-tasks")
    require_columns(header, ("id", "slug", "budget", "status"), "Sub-tasks",
                    index + 1)
    if not rows:
        raise LedgerError(f"line {index + 1}: the Sub-tasks table has no rows")
    for line_no, row in rows:
        name = f"{row['id']}-{row['slug']}"
        table_at = heading_index(lines, name, level="###")
        if table_at is None:  # tolerate a slug edited in one place only
            table_at = next((i for i, line in enumerate(lines)
                             if line.startswith(f"### {row['id']}-")), None)
        match = CELL_BUDGET_RE.match(row["budget"])
        budget = (f"{match.group(1)} remaining of {match.group(2)}" if match
                  else "not recorded")
        if table_at is None:
            # No phase table, so the summary `status` is all there is to read.
            status = row["status"].lower()
            if status not in STATUSES:
                raise LedgerError(
                    f"line {line_no}: status `{row['status']}` of sub-task "
                    f"{name} is not one of {', '.join(sorted(STATUSES))}")
            if status in COMPLETE:
                continue  # finished (e.g. merged): never re-run it
            if status == "blocked":
                return name, (None, None, "blocked",
                              "sub-task status is blocked and it has no "
                              "phase table"), budget
            if status == "in-progress":
                raise LedgerError(
                    f"line {line_no}: sub-task {name} is in-progress but has "
                    f"no `### {name}` phase table — a started sub-task "
                    f"writes its table when it starts")
            # Never started: begin it at Phase 2 (resume step 5).
            phase = (SUBTASK_FIRST_PHASE, "Define", "pending",
                     "no phase table yet — this sub-task never started")
            return name, phase, budget
        # The phase table is authoritative over the summary `status` cell.
        found = first_open_phase(phase_rows(lines, table_at, name), name)
        if found:
            return name, found, budget
    return None, None, None


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
        usage="python3 %(prog)s <artifact-dir> [--task TEXT]")
    parser.add_argument("artifact_dir", help="the run's .auto-dev/ directory")
    parser.add_argument("--task", help="exit 1 unless the ledger header "
                        "names this task or ticket")
    args = parser.parse_args()  # bad arguments exit 2 via argparse

    directory = Path(args.artifact_dir)
    ledger = directory / LEDGER
    if directory.exists() and not directory.is_dir():
        print(f"ERROR: {directory} is not a directory — pass the .auto-dev/ "
              f"directory that holds {LEDGER}.", file=sys.stderr)
        return EXIT_CANNOT_RUN
    if not ledger.is_file():
        print(f"MISSING: no {ledger} — this directory holds no auto-dev run.",
              file=sys.stderr)
        return EXIT_BAD_LEDGER
    try:
        lines = ledger.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError as exc:
        print(f"MALFORMED: {ledger} is not UTF-8 text ({exc.reason} at byte "
              f"{exc.start}).", file=sys.stderr)
        return EXIT_BAD_LEDGER
    except OSError as exc:
        print(f"ERROR: could not read {ledger}: {exc}", file=sys.stderr)
        return EXIT_CANNOT_RUN

    try:
        fields = parse_header(lines)
        if args.task is not None:
            if not task_matches(args.task, fields):
                print(f"MISMATCH: {ledger} belongs to a different task.\n"
                      f"  ledger Task:   {fields['Task']}\n"
                      f"  ledger Ticket: {fields['Ticket']}\n"
                      f"  --task:        {args.task}", file=sys.stderr)
                return EXIT_BAD_LEDGER
        if fields["Mode"] == "single-PR":
            subtask, found, budget = single_pr(lines, fields)
        else:
            subtask, found, budget = multi_pr(lines)
    except LedgerError as exc:
        print(f"MALFORMED: {ledger}: {exc}. Template: references/artifacts.md, "
              f"WORK_LOG.md.", file=sys.stderr)
        return EXIT_BAD_LEDGER

    if found is None:
        print(f"COMPLETE: every phase in {ledger} is done, skipped or n/a — "
              f"nothing to resume.\n  Task:   {fields['Task']}\n"
              f"  Ticket: {fields['Ticket']}")
        return EXIT_COMPLETE

    number, name, status, notes = found
    out = [f"RESUME: {ledger}",
           f"  Task:      {fields['Task']}",
           f"  Ticket:    {fields['Ticket']}",
           f"  Mode:      {fields['Mode']}"]
    if subtask:
        out.append(f"  Sub-task:  {subtask}")
    if number is None:  # a blocked sub-task with no phase table
        out.append("  Phase:     none — the sub-task is blocked and has no "
                   "phase table (status: blocked)")
    else:
        out += [f"  Phase:     {number} — {name} (status: {status})",
                f"  Session:   {SESSIONS[number]}"]
    if status == "blocked":
        out.append("  Blocked:   blocked — ask the user; do not start or retry it")
    out.append(f"  Action:    {ACTIONS[status]}")
    if number == 6:
        out.append(f"  Note:      {PHASE_6_NOTE}")
    if notes:
        out.append(f"  Notes:     {notes}")
    out.append(f"  Budget:    {budget}")
    print("\n".join(out))
    return EXIT_FOUND


if __name__ == "__main__":
    sys.exit(main())
