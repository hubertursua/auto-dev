"""Read the pipeline's strict Markdown artifacts.

The templates are in templates/. These readers are lenient about
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


def _collapse(parts):
    return " ".join(" ".join(parts).split())


def numbered_items(body):
    """The numbered items (`1.`, `S1.`) in `body`, each whole: [{id, lines,
    statement, example, edge, verify, words}], in order.

    An item runs from its numbered line over every following line that is
    blank or indented; the first other line ends it, so prose after the last
    item is not part of it. `statement` is the numbered line and its
    continuation lines before the first `- Example:/Edge:/Verify by:` sub-line;
    each sub-line's text takes its own continuation lines. `words` is the whole
    item with every whitespace run collapsed, so re-wrapping or re-indenting it
    changes nothing. A repeated id is an ArtifactError."""
    items, current, field = [], None, None
    for line in (body or "").splitlines():
        match = SPEC_ITEM_RE.match(line)
        if match:
            if any(i["id"] == match.group(1) for i in items):
                raise ArtifactError(f"item {match.group(1)} is numbered twice")
            current = {"id": match.group(1), "lines": [line],
                       "_parts": {"statement": [match.group(2)], "example": [],
                                  "edge": [], "verify": []}}
            items.append(current)
            field = "statement"
            continue
        if current is None:
            continue
        if line.strip() and not line[:1].isspace():
            current, field = None, None
            continue
        current["lines"].append(line)
        sub = SUB_LINE_RE.match(line)
        if sub:
            field = {"example": "example", "edge": "edge",
                     "verify by": "verify"}[sub.group(1).lower()]
            current["_parts"][field].append(sub.group(2))
        elif line.strip():
            current["_parts"][field].append(line)
    for item in items:
        parts = item.pop("_parts")
        for key, value in parts.items():
            item[key] = _collapse(value)
        item["words"] = _collapse(item["lines"])
    return items


def spec_items(text, where="SPEC.md"):
    """{id: item} for SPEC.md's conditions, then its Security/Compliance
    criteria, each item whole (numbered_items), in file order."""
    found = {}
    for name in ("Conditions", "Security/Compliance criteria"):
        body = find_section(text, name)
        if body is None:
            if name == "Conditions":
                raise ArtifactError(f"{where}: no `## Conditions` section")
            continue
        try:
            items = numbered_items(body)
        except ArtifactError as exc:
            raise ArtifactError(f"{where}: {exc}") from None
        for item in items:
            if item["id"] in found:
                raise ArtifactError(f"{where}: item {item['id']} is numbered twice")
            found[item["id"]] = item
    if not found or not any(not i.startswith("S") for i in found):
        raise ArtifactError(f"{where}: no numbered conditions under `## Conditions`")
    return found


def plan_steps(text, where="IMPLEMENTATION.md"):
    """{number: step} for IMPLEMENTATION.md's `## Build sequence`, each step
    whole (numbered_items: `words` ignores spacing), in file order. A missing
    section, no numbered step, or a number used twice is an ArtifactError."""
    body = find_section(text or "", "Build sequence")
    if body is None:
        raise ArtifactError(f"{where}: no `## Build sequence` section")
    try:
        items = numbered_items(body)
    except ArtifactError as exc:
        raise ArtifactError(f"{where}: build sequence {exc}") from None
    steps = {i["id"]: i for i in items if i["id"].isdigit()}
    if not steps:
        raise ArtifactError(f"{where}: no numbered step under `## Build sequence`")
    return steps


BLOCK_RE = re.compile(r"^## (P\d+)\b.*$", re.MULTILINE)
FIELD_RE = re.compile(r"^- (Target|Why|Comment|From|New text|Answer|Reason):\s*(.*)$",
                      re.IGNORECASE)


def _blocks(text):
    """[(pid, body)] for each `## P<k>` block."""
    parts = BLOCK_RE.split(text or "")
    return [(parts[i], parts[i + 1]) for i in range(1, len(parts), 2)]


def _fields(body):
    """({field: text}, the lines after `- New text:`) for one block."""
    fields, rest, field = {}, None, None
    for line in body.splitlines():
        if rest is not None:
            rest.append(line)
            continue
        match = FIELD_RE.match(line)
        if match:
            field = match.group(1).lower()
            if field == "new text":
                rest = [match.group(2)] if match.group(2).strip() else []
                continue
            fields[field] = [match.group(2)]
        elif field and line[:1].isspace() and line.strip():
            fields[field].append(line)
        elif line.strip():
            field = None
    return {k: _collapse(v) for k, v in fields.items()}, rest


def proposal_blocks(text):
    """A proposal file's `## P<k>` blocks: [{pid, target, why, comment, from,
    items, new_text}]. `items` are the numbered items under `- New text:`
    (numbered_items); a missing field is ""."""
    found = []
    for pid, body in _blocks(text):
        fields, rest = _fields(body)
        new_text = "\n".join(rest or []).strip("\n")
        found.append({"pid": pid, "target": fields.get("target", ""),
                      "why": fields.get("why", ""), "comment": fields.get("comment", ""),
                      "from": fields.get("from", ""),
                      "items": numbered_items(new_text) if rest is not None else [],
                      "new_text": new_text})
    return found


def rulings(text):
    """A rulings file's answers: {pid: {answer, reason}}. `answer` is the first
    word of `- Answer:`, lowercased; `reason` is "" when absent or `none`."""
    found = {}
    for pid, body in _blocks(text):
        fields, _ = _fields(body)
        words = fields.get("answer", "").replace("`", "").split()
        reason = fields.get("reason", "")
        if reason.strip("`*_. ").lower() == "none":
            reason = ""
        found[pid] = {"answer": words[0].strip("*_.,;").lower() if words else "",
                      "reason": reason}
    return found


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


# IMPLEMENTATION.md's `Review effort:` line: the effort the planner recommends for
# the Phase 6 code reviewers. A plan without one (written before 4.3) means xhigh.
REVIEW_EFFORTS = ("high", "xhigh")
DEFAULT_REVIEW_EFFORT = "xhigh"
REVIEW_EFFORT_RE = re.compile(r"^[-*_\s]*review effort[*_\s]*:[*_\s]*([^\s—–]*)",
                              re.IGNORECASE)


def review_effort(text):
    """The first word of the plan's `Review effort:` line, lowercased, or None
    when it has no such line. The caller checks it is one of REVIEW_EFFORTS."""
    for line in text.splitlines():
        m = REVIEW_EFFORT_RE.match(line)
        if m:
            return m.group(1).strip("*_`.,;").lower()
    return None
