"""Read the pipeline's strict Markdown artifacts.

The templates are in references/artifacts.md. These readers are lenient about
whitespace and strict about structure: a missing heading, table or column is an
ArtifactError naming the file and what is wrong, so a worker can be re-spawned
to fix it rather than a script guessing.
"""

import re
from pathlib import Path


class ArtifactError(Exception):
    """An artifact doesn't follow its template; the message says where."""


SEPARATOR_RE = re.compile(r"^\|?[\s:|-]+\|?$")
# `1.` and `S1.` items under SPEC.md's Conditions / Security sections.
SPEC_ITEM_RE = re.compile(r"^(S?\d+)\.\s+(.*)$")
SUB_LINE_RE = re.compile(r"^\s+-\s+(Example|Edge|Verify by):\s*(.*)$", re.IGNORECASE)
LEVELS = ("unit", "integration", "end-to-end")


def read(path):
    try:
        return Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ArtifactError(f"{path} does not exist") from None
    except (OSError, UnicodeDecodeError) as exc:
        raise ArtifactError(f"cannot read {path}: {exc}") from None


def sections(text, level="##"):
    """{heading text: body} for each `## heading` (level given)."""
    out, current, body = {}, None, []
    prefix = level + " "
    for line in text.splitlines():
        if line.startswith(prefix) and not line.startswith(prefix + "#"):
            if current is not None:
                out[current] = "\n".join(body)
            current, body = line[len(prefix):].strip(), []
        elif current is not None:
            body.append(line)
    if current is not None:
        out[current] = "\n".join(body)
    return out


def find_section(text, name, level="##"):
    """The body of the first section whose heading starts with `name`, or None."""
    for heading, body in sections(text, level).items():
        if heading.lower().startswith(name.lower()):
            return body
    return None


def split_cells(line):
    """A table row's cells, split on each `|` that is neither escaped (`\\|`) nor
    inside a backtick code span; `\\|` reads as `|`. A backtick run with no
    closing run of the same length is plain text."""
    line = line.strip()
    cells, cell, i = [], [], 0
    while i < len(line):
        ch = line[i]
        if ch == "\\" and line[i + 1:i + 2] == "|":
            cell.append("|")
            i += 2
        elif ch == "`":
            run = len(line[i:]) - len(line[i:].lstrip("`"))
            ticks = "`" * run
            close = re.search(rf"(?<!`){ticks}(?!`)", line[i + run:])
            if close is None:
                cell.append(ticks)
                i += run
                continue
            end = i + run + close.end()
            cell.append(line[i:end].replace("\\|", "|"))
            i = end
        elif ch == "|":
            cells.append("".join(cell))
            cell, i = [], i + 1
        else:
            cell.append(ch)
            i += 1
    cells.append("".join(cell))
    if cells and not cells[0].strip() and line.startswith("|"):
        cells = cells[1:]
    if len(cells) > 1 and not cells[-1].strip() and line.endswith("|"):
        cells = cells[:-1]
    return [c.strip() for c in cells]


def split_row(line, width=0):
    cells = split_cells(line)
    if width and len(cells) > width:  # a stray `|` in the last column
        cells = cells[:width - 1] + [" | ".join(cells[width - 1:])]
    return cells


def tables(body):
    """Every Markdown table in `body`, as (header, [row dicts])."""
    found, lines, i = [], body.splitlines(), 0
    while i < len(lines):
        if lines[i].lstrip().startswith("|") and i + 1 < len(lines) \
                and SEPARATOR_RE.match(lines[i + 1].strip()):
            header = split_row(lines[i])
            rows, i = [], i + 2
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                cells = split_row(lines[i], len(header))
                cells += [""] * (len(header) - len(cells))
                rows.append(dict(zip(header, cells)))
                i += 1
            found.append((header, rows))
        else:
            i += 1
    return found


def first_table(body, needed, where):
    for header, rows in tables(body or ""):
        if all(col in header for col in needed):
            return header, rows
    raise ArtifactError(f"{where}: no table with columns {', '.join(needed)}")


def spec_conditions(path):
    """SPEC.md's conditions and criteria: [{id, text, example, edge, verify}]."""
    text = read(path)
    items = []
    for name in ("Conditions", "Security/Compliance criteria"):
        body = find_section(text, name)
        if body is None:
            if name == "Conditions":
                raise ArtifactError(f"{path}: no `## Conditions` section")
            continue
        current = None
        for line in body.splitlines():
            match = SPEC_ITEM_RE.match(line)
            if match:
                current = {"id": match.group(1), "text": match.group(2).strip(),
                           "example": "", "edge": "", "verify": ""}
                items.append(current)
                continue
            sub = SUB_LINE_RE.match(line)
            if sub and current is not None:
                key = {"example": "example", "edge": "edge",
                       "verify by": "verify"}[sub.group(1).lower()]
                current[key] = sub.group(2).strip()
    if not items:
        raise ArtifactError(f"{path}: no numbered conditions under `## Conditions`")
    return items


LEVEL_RE = re.compile(r"\b(end-to-end|e2e|integration|unit)", re.IGNORECASE)


def level_of(text):
    """The first test level named in `text`, or None (manual, unknown)."""
    match = LEVEL_RE.search(text)
    if not match:
        return None
    word = match.group(1).lower()
    return "end-to-end" if word == "e2e" else word


def manifest(path):
    """MANIFEST.md: (check rows, not-automatable rows)."""
    text = read(path)
    _, rows = first_table(text.split("## Not automatable")[0],
                          ("#", "Check (path :: test name)", "Kind", "Base run"),
                          f"{path} (checks table)")
    na_body = find_section(text, "Not automatable")
    na_rows = []
    if na_body is not None and not na_body.strip().lower().startswith("none"):
        try:
            _, na_rows = first_table(na_body, ("#",), f"{path} (Not automatable)")
        except ArtifactError:
            na_rows = []
    return rows, na_rows


CHECK_PATH_RE = re.compile(r"`([^`]+)`\s*::")


def check_path(cell):
    match = CHECK_PATH_RE.search(cell)
    return match.group(1).strip() if match else None


def base_run_results(path):
    """{test name: result text} from a base-run/C<n>.txt file's Result lines."""
    results, in_result = {}, False
    for line in read(path).splitlines():
        if line.startswith("Result:"):
            in_result, line = True, line[len("Result:"):]
        elif line.startswith(("Output:", "Commit:", "Command:")):
            in_result = False
            continue
        if not in_result or not line.strip():
            continue
        name, sep, result = line.strip().rpartition(": ")
        # `<name>: failed: <reason>` — split at the first `: failed`/`: passed`.
        match = re.match(r"(.*?):\s*(failed\b.*|passed\b.*|not re-run \(repair\).*)$",
                         line.strip())
        if match:
            results[match.group(1).strip().strip('"')] = match.group(2).strip()
        elif sep:
            results[name.strip().strip('"')] = result.strip()
    return results


def spec_eval(path):
    """SPEC_EVAL.md: {rows, integrity, survivors, defective, unresolved}."""
    text = read(path)
    head = text.split("\n## ")[0]
    _, rows = first_table(head, ("#", "Verdict", "Tier", "Evidence"),
                          f"{path} (verdict table)")
    integrity = []
    body = find_section(text, "Test integrity")
    if body is not None:
        for header, table in tables(body):
            if "Judgment" in header:
                integrity = table
    survivors = []
    body = find_section(text, "Mutation")
    if body is not None:
        for header, table in tables(body):
            if "Mutant" in header:
                survivors = table
    defective = (find_section(text, "Defective acceptance checks") or "").strip()
    unresolved = (find_section(text, "Unresolved") or "").strip()
    mutation_line = ""
    if body is not None:
        mutation_line = next((ln for ln in body.splitlines() if ln.strip()), "")
    return {"rows": rows, "integrity": integrity, "survivors": survivors,
            "defective": "" if defective.lower().startswith("none") else defective,
            "unresolved": unresolved, "mutation_line": mutation_line.strip()}


def header_line(text, prefix):
    for line in text.splitlines():
        if line.strip().startswith(prefix):
            return line.strip()
    return ""
