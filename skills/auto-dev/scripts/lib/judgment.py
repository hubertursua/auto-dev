"""The review judge's bookkeeping, as code: the panel's findings merged into
one list for the judge (`findings.md`), and CODE_REVIEW.md built from the
judge's calls (`JUDGMENT.md`).

`next` writes review/pass-<n>/findings.md from the reviewers' R<k>.md reports
when it briefs the judge. The judge decides what only it can (which findings
are one, whether each trigger path holds, its category, the detail lines a
must-fix finding needs, the earlier must-fix findings' status, each security
lead's disposition) and writes review/pass-<n>/JUDGMENT.md. `autodev.py
review-build` then applies the rubric's fixed table and writes CODE_REVIEW.md
(templates/CODE_REVIEW.md, the shape every reader of it already parses) and
the pass's corrections.md.
"""

import re
from pathlib import Path

from . import artifacts as art

MUST_FIX_CATEGORIES = ("correctness", "tests", "acceptance-check")
ADVISORY_CATEGORIES = ("scope", "performance", "design", "conventions", "style")
CATEGORIES = MUST_FIX_CATEGORIES + ADVISORY_CATEGORIES
DETAIL_KEYS = ("Trigger path", "Judge", "Where", "Test", "Required change",
               "In plain words")
PANEL = 3
LEVEL, COUNTS = "\0level\0", "\0counts\0"  # filled in once the rows are known

FINDING_RE = re.compile(r"^\s*(\d+)\.\s+\*\*(.+?)\*\*\s+[—-]+\s+`([^`]+)`\s+[—-]+\s+"
                        r"([a-z-]+)\s*$")
SUB_RE = re.compile(r"^\s+(Trigger path|Why it is wrong):\s*(.*)$")
NEAR = 5  # lines apart at which two findings in one file are flagged as maybe one


class JudgmentError(Exception):
    """JUDGMENT.md (or a report) can't be used; the message lists why."""


# ---------------------------------------------------------------- reports

def section(text, name):
    return art.find_section(text, name)


def parse_report(text):
    """A reviewer's R<k>.md: {coverage, findings, leads, spec, pre_existing,
    problems}. `problems` lists what doesn't follow templates/R.md."""
    problems = []
    head = text.split("\n## ", 1)[0]
    coverage = re.search(r"Coverage:\s*(full|partial[^\n]*)", head)
    body = section(text, "Findings")
    findings = []
    if body is None:
        problems.append("no `## Findings` section")
        body = ""
    current = None
    for line in body.splitlines():
        if not line.strip():
            continue
        match = FINDING_RE.match(line)
        if match:
            category = match.group(4)
            if category not in CATEGORIES:
                problems.append(f"finding {match.group(1)}: category `{category}` is not one "
                                f"of {', '.join(CATEGORIES)}")
            current = {"title": match.group(2).strip(), "location": match.group(3).strip(),
                       "category": category, "Trigger path": "", "Why it is wrong": ""}
            findings.append(current)
            continue
        sub = SUB_RE.match(line)
        if sub and current is not None:
            current[sub.group(1)] = sub.group(2).strip()
            continue
        if current is not None and line.startswith("   "):
            last = "Why it is wrong" if current["Why it is wrong"] else "Trigger path"
            current[last] = (current[last] + " " + line.strip()).strip()
            continue
        if not findings and line.strip().lower().startswith("none"):
            continue
        problems.append(f"a line under Findings is not a finding in the template's shape "
                        f"(`<n>. **<title>** — `path:line` — <category>`): {line.strip()[:80]}")
    for f in findings:
        if not f["Trigger path"]:
            problems.append(f"finding `{f['title']}` has no `Trigger path:` line")
    leads = [ln.strip() for ln in (section(text, "Security leads") or "").splitlines()
             if ln.strip().startswith("- ")]
    spec = (section(text, "Spec problems") or "").strip()
    pre = re.search(r"(\d+)", section(text, "Pre-existing") or "")
    return {"coverage": coverage.group(1).strip() if coverage else "full",
            "findings": findings, "leads": leads,
            "spec": "" if spec.lower().startswith("none") else spec,
            "pre_existing": int(pre.group(1)) if pre else 0, "problems": problems}


def line_of(location):
    match = re.search(r":(\d+)", location)
    return int(match.group(1)) if match else None


def file_of(location):
    return location.split(":", 1)[0].strip()


def findings_text(pass_n, reports):
    """review/pass-<n>/findings.md from {reviewer: parsed report}."""
    items = []
    for reviewer in sorted(reports):
        for f in reports[reviewer]["findings"]:
            items.append({**f, "raised_by": reviewer})
    for i, item in enumerate(items, 1):
        item["id"] = f"F{i}"
    finished = len(reports)
    partial = [r for r, rep in sorted(reports.items()) if rep["coverage"] != "full"]
    coverage = "full" if not partial else "partial: " + "; ".join(
        f"{r} {reports[r]['coverage']}" for r in partial)
    out = [f"# Findings to judge — pass {pass_n}", "",
           (f"Reviewers finished: {', '.join(sorted(reports)) or 'none'} ({finished}/{PANEL})"
           f" · coverage: {coverage}"),
           (f"Pre-existing (dropped, counted only): "
           f"{sum(r['pre_existing'] for r in reports.values())}"), ""]
    for item in items:
        near = [o["id"] for o in items if o is not item
                and file_of(o["location"]) == file_of(item["location"])
                and line_of(o["location"]) is not None and line_of(item["location"]) is not None
                and abs(line_of(o["location"]) - line_of(item["location"])) <= NEAR]
        out += [f"## {item['id']} — {item['title']}",
                f"- Raised by: {item['raised_by']}",
                f"- Location: `{item['location']}`",
                f"- Category: {item['category']}",
                f"- Trigger path: {item['Trigger path'] or 'none given'}",
                f"- Why it is wrong: {item['Why it is wrong'] or 'none given'}"]
        if near:
            out.append(f"- Near: {', '.join(near)} (the same file, within {NEAR} lines: "
                       "maybe the same finding)")
        out.append("")
    if not items:
        out += ["No findings.", ""]
    out += ["## Security leads"]
    leads = [f"{lead} (raised by {r})" for r, rep in sorted(reports.items())
             for lead in rep["leads"] if not lead[2:].strip().lower().startswith("none")]
    out += leads or ["none"]
    out += ["", "## Spec problems"]
    specs = [f"- {r}: {rep['spec']}" for r, rep in sorted(reports.items()) if rep["spec"]]
    out += specs or ["none"]
    return "\n".join(out) + "\n"


def write_findings(ad, pass_n, reviewers):
    """Write review/pass-<n>/findings.md from the named reviewers' reports."""
    folder = Path(ad) / "review" / f"pass-{pass_n}"
    reports = {}
    for r in reviewers:
        try:
            reports[r] = parse_report(art.read(folder / f"{r}.md"))
        except art.ArtifactError:
            continue
    path = folder / "findings.md"
    path.write_text(findings_text(pass_n, reports), encoding="utf-8")
    return path


def parse_findings(text):
    """findings.md: ({id: {title, location, category, raised_by}}, finished,
    coverage, pre_existing, [lead lines])."""
    found = {}
    for block in re.split(r"^## ", text, flags=re.MULTILINE)[1:]:
        head, _, body = block.partition("\n")
        match = re.match(r"(F\d+) — (.*)", head)
        if not match:
            continue
        fields = dict(re.findall(r"^- ([A-Za-z ]+):\s*(.*)$", body, re.MULTILINE))
        found[match.group(1)] = {"title": match.group(2).strip(),
                                 "location": fields.get("Location", "").strip("`"),
                                 "category": fields.get("Category", ""),
                                 "raised_by": fields.get("Raised by", "").strip()}
    head = re.search(r"Reviewers finished: .*\((\d)/\d\) · coverage: (.*)", text)
    pre = re.search(r"Pre-existing \(dropped, counted only\): (\d+)", text)
    leads = [ln for ln in (section(text, "Security leads") or "").splitlines()
             if ln.startswith("- ")]
    return (found, int(head.group(1)) if head else 0,
            head.group(2).strip() if head else "full",
            int(pre.group(1)) if pre else 0, leads)


# ---------------------------------------------------------------- the judgment

def parse_judgment(text, findings, earlier_open):
    """JUDGMENT.md: ([judged finding], {earlier id: fixed|open}, [lead lines]),
    or JudgmentError listing every problem."""
    problems, judged, seen = [], [], {}
    blocks = re.split(r"^## ", text, flags=re.MULTILINE)[1:]
    earlier, leads = {}, None
    for block in blocks:
        head, _, body = block.partition("\n")
        head = head.strip()
        if head == "Earlier must-fix":
            for fid, status in re.findall(r"^- (C\d+):\s*(\S+)", body, re.MULTILINE):
                if status not in ("fixed", "open"):
                    problems.append(f"Earlier must-fix: {fid} is `{status}`, not fixed or open")
                earlier[fid] = status
            continue
        if head == "Security leads":
            leads = [ln.strip() for ln in body.splitlines() if ln.strip().startswith("- ")]
            continue
        if not re.fullmatch(r"J\d+", head):
            problems.append(f"`## {head}`: a judged finding's heading is `## J<k>`")
            continue
        fields = {}
        for line in body.splitlines():
            match = re.match(r"^- ([A-Za-z ]+?):\s*(.*)$", line)
            if match:
                fields[match.group(1)] = match.group(2).strip()
            elif line.strip() and fields:
                problems.append(f"{head}: keep each line on one line (`{line.strip()[:60]}`)")
        item = {"label": head, **fields}
        sources = [s.strip() for s in fields.get("From", "").split(",") if s.strip()]
        if not sources:
            problems.append(f"{head}: no `From:` line naming the F findings it judges")
        for s in sources:
            if s not in findings:
                problems.append(f"{head}: From names `{s}`, which findings.md does not have")
            elif s in seen:
                problems.append(f"{s} is judged twice ({seen[s]} and {head})")
            else:
                seen[s] = head
        item["sources"] = sources
        category = fields.get("Category", "")
        if category not in CATEGORIES:
            problems.append(f"{head}: Category `{category}` is not one of "
                            f"{', '.join(CATEGORIES)}")
        holds = fields.get("Holds", "")
        kind = holds.split(" ", 1)[0].rstrip(":—-").lower()
        if kind not in ("yes", "no", "pre-existing"):
            problems.append(f"{head}: Holds is `yes`, `no — <why>` or `pre-existing — "
                            f"<why>`, not `{holds[:40]}`")
        elif kind != "yes" and len(holds.split()) < 3:
            problems.append(f"{head}: `Holds: {kind}` needs the reason after it")
        item["holds"] = kind
        item["why"] = re.sub(r"^\S+\s*[—-]*\s*", "", holds).strip()
        for key in ("Finding", "Location"):
            if not fields.get(key):
                problems.append(f"{head}: no `{key}:` line")
        if kind == "yes" and category in MUST_FIX_CATEGORIES:
            for key in DETAIL_KEYS:
                if not fields.get(key):
                    problems.append(f"{head}: a must-fix candidate needs `{key}:`")
        judged.append(item)
    for fid in findings:
        if fid not in seen:
            problems.append(f"{fid} is judged nowhere: name it in one `From:` line")
    for fid in earlier_open:
        if fid not in earlier:
            problems.append(f"Earlier must-fix: say whether {fid} is fixed or open")
    if leads is None:
        problems.append("no `## Security leads` section (write `none` under it when there "
                        "are none)")
        leads = []
    leads = [ln for ln in leads if not ln[2:].strip().lower().startswith("none")]
    for ln in leads:
        if "→" not in ln:
            problems.append(f"Security leads: `{ln[:60]}` needs `→ passed to the security "
                            "review` or `→ covered by S<n>`")
    if problems:
        raise JudgmentError("\n".join(problems))
    return judged, earlier, leads


# ---------------------------------------------------------------- the earlier report

def table_rows(text, name, key="ID"):
    body = section(text, name) or ""
    for header, rows in art.tables(body):
        if key in header:
            return header, [r for r in rows if r.get(key, "").strip()]
    return None, []


def detail_blocks(text):
    """{id: the `### <id> — …` block, verbatim}, wherever it sits: a re-voted
    finding's block stays under `## Pending re-vote` after `votes --apply`."""
    return {m.group(1): m.group(0).rstrip()
            for m in re.finditer(r"^### (C\d+)\b.*?(?=^### |^## |\Z)", text,
                                 re.MULTILINE | re.DOTALL)}


def earlier_report(text):
    """What a later pass carries forward from the previous CODE_REVIEW.md."""
    if not text:
        return None
    head = art.header_line(text, "**Overall confidence") or ""
    decided = re.search(r"must-fix decided 2[–-]1:\s*([^>*\n]*)", head)
    dropped = re.search(r"Dropped \(pre-existing\):\s*(\d+)", text)
    leads = [ln for ln in (section(text, "Security leads") or "").splitlines()
             if ln.startswith("- ")]
    return {"must_fix": table_rows(text, "Must-fix")[1],
            "must_fix_blocks": detail_blocks(text),
            "advisory": table_rows(text, "Advisory")[1],
            "noise": table_rows(text, "Noise")[1],
            "passes": table_rows(text, "Passes", key="Pass")[1],
            "leads": leads,
            "decided": [x.strip() for x in (decided.group(1) if decided else "").split(",")
                        if x.strip() and x.strip() != "none"],
            "dropped": int(dropped.group(1)) if dropped else 0}


def ids_in(earlier):
    if not earlier:
        return []
    return [r["ID"].strip() for key in ("must_fix", "advisory", "noise")
            for r in earlier[key]]


# ---------------------------------------------------------------- the build

def row(*cells):
    return "| " + " | ".join(str(c).replace("|", "\\|") for c in cells) + " |"


def raisers(item, findings):
    return sorted({findings[s]["raised_by"] for s in item["sources"]})


def build(*, branch, pass_n, scope, tree, findings_md, judgment_md, earlier_md):
    """(CODE_REVIEW.md text, {next, must_fix_open, revote, new_must_fix: [ids],
    open_ids: [ids]}), or JudgmentError."""
    findings, finished, coverage, pre, _leads = parse_findings(findings_md)
    earlier = earlier_report(earlier_md)
    earlier_open = [r["ID"].strip() for r in (earlier or {}).get("must_fix", [])
                    if r.get("Status", "").strip().startswith("open")]
    judged, statuses, new_leads = parse_judgment(judgment_md, findings, earlier_open)
    used = [int(i[1:]) for i in ids_in(earlier)]
    next_id = max(used, default=0) + 1
    must, pending, advisory, noise, dropped = [], [], [], [], 0
    decided = list((earlier or {}).get("decided", []))
    for item in judged:
        votes = raisers(item, findings)
        if item["holds"] == "pre-existing":
            dropped += 1
            continue
        item["id"] = f"C{next_id}"
        next_id += 1
        item["raisers"] = votes
        category = item["Category"]
        if item["holds"] == "no":
            noise.append(item)
        elif category in ADVISORY_CATEGORIES:
            advisory.append(item)
        elif len(votes) >= 2:
            must.append(item)
            if len(votes) == 2:
                decided.append(item["id"])
        elif finished >= 2:
            item["revoters"] = [f"R{k}" for k in range(1, PANEL + 1)
                                if f"R{k}" not in votes][:max(finished - 1, 0)]
            pending.append(item)
        else:
            advisory.append(item)  # no one left to re-vote: one vote of three
    lines = [f"# Code review — {branch}", ""]
    level = "provisional (re-votes pending)" if pending else LEVEL
    full = "full" if coverage == "full" else "partial"
    lines += [(f"**Overall confidence: {level}** — reviewers finished: {finished}/{PANEL}; "
              f"coverage: {full}; must-fix decided 2–1: {', '.join(decided) or 'none'}"),
              f"Latest pass: {pass_n} — scope: {scope}",
              f"Tree: {tree}",
              COUNTS, "", "## Must-fix",
              "| ID | Finding | Location | Category | Votes | Confidence | Status |",
              "|----|---------|----------|----------|-------|------------|--------|"]
    blocks = []
    for r in (earlier or {}).get("must_fix", []):
        rid = r["ID"].strip()
        status = r.get("Status", "").strip()
        if status.startswith("open") and statuses.get(rid) == "fixed":
            status = f"fixed (pass {pass_n})"
        lines.append(row(rid, r.get("Finding", ""), r.get("Location", ""),
                         r.get("Category", ""), r.get("Votes", ""), r.get("Confidence", ""),
                         status))
        if rid in earlier["must_fix_blocks"]:
            blocks.append(earlier["must_fix_blocks"][rid])
    for item in must:
        n = len(item["raisers"])
        lines.append(row(item["id"], item["Finding"], fmt_loc(item["Location"]),
                         item["Category"], f"{n}/{PANEL}", "High" if n >= 3 else "Medium",
                         "open"))
        blocks.append(detail(item))
    lines.append("")
    for block in blocks:
        lines += [block, ""]
    lines += ["## Pending re-vote",
              "| ID | Finding | Location | Category | Raised by | Re-voters | Votes |",
              "|----|---------|----------|----------|-----------|-----------|-------|"]
    for item in pending:
        lines.append(row(item["id"], item["Finding"], fmt_loc(item["Location"]),
                         item["Category"], ", ".join(item["raisers"]),
                         ", ".join(item["revoters"]), ""))
    lines.append("")
    for item in pending:
        lines += [detail(item), ""]
    lines += ["## Advisory",
              "| ID | Finding | Location | Category | Votes | Confidence | Why advisory |",
              "|----|---------|----------|----------|-------|------------|--------------|"]
    for r in (earlier or {}).get("advisory", []):
        lines.append(row(r["ID"].strip(), r.get("Finding", ""), r.get("Location", ""),
                         r.get("Category", ""), r.get("Votes", ""), r.get("Confidence", ""),
                         r.get("Why advisory", "")))
    for item in advisory:
        why = (f"{item['Category']} is an advisory category"
               if item["Category"] in ADVISORY_CATEGORIES
               else "one vote of three, and no reviewer left to re-vote")
        lines.append(row(item["id"], item["Finding"], fmt_loc(item["Location"]),
                         item["Category"], f"{len(item['raisers'])}/{PANEL}", "Low", why))
    lines += ["", "## Noise", "| ID | Finding | Raised by | Why dismissed |",
              "|----|---------|-----------|---------------|"]
    for r in (earlier or {}).get("noise", []):
        lines.append(row(r["ID"].strip(), r.get("Finding", ""), r.get("Raised by", ""),
                         r.get("Why dismissed", "")))
    for item in noise:
        lines.append(row(item["id"], item["Finding"], ", ".join(item["raisers"]),
                         item["why"]))
    lines += ["", "## Security leads"]
    leads = (earlier or {}).get("leads", []) + new_leads
    lines += leads or ["none"]
    lines += ["", "## Passes",
              "| Pass | Scope | Reviewers finished | Must-fix found | Re-votes |",
              "|------|-------|--------------------|----------------|----------|"]
    for r in (earlier or {}).get("passes", []):
        if r.get("Pass", "").strip() != str(pass_n):
            lines.append(row(r.get("Pass", ""), r.get("Scope", ""),
                             r.get("Reviewers finished", ""), r.get("Must-fix found", ""),
                             r.get("Re-votes", "")))
    lines.append(row(pass_n, scope, f"{finished}/{PANEL}", len(must), len(pending)))
    text = "\n".join(lines) + "\n"
    open_ids = [r["ID"].strip() for r in (earlier or {}).get("must_fix", [])
                if r.get("Status", "").strip().startswith("open")
                and statuses.get(r["ID"].strip()) != "fixed"] + [i["id"] for i in must]
    fixed = sum(1 for r in (earlier or {}).get("must_fix", [])
                if not r.get("Status", "").strip().startswith("open")
                or statuses.get(r["ID"].strip()) == "fixed")
    advisory_n = len((earlier or {}).get("advisory", [])) + len(advisory)
    noise_n = len((earlier or {}).get("noise", [])) + len(noise)
    counts = (f"{len(open_ids)} open · {fixed} fixed   ·   Advisory: {advisory_n}   ·   "
              f"Noise: {noise_n}   ·   Dropped (pre-existing): "
              f"{(earlier or {}).get('dropped', 0) + pre + dropped}")
    text = text.replace(COUNTS, f"Must-fix: {counts}", 1)
    if not pending:
        if finished < 2:
            lvl = "Low"
        elif finished == PANEL and full == "full" and not decided:
            lvl = "High"
        else:
            lvl = "Medium"
        text = text.replace(LEVEL, lvl, 1)
    nxt = "REVOTE" if pending else "MUST_FIX" if open_ids else "CLEAN"
    return text, {"next": nxt, "must_fix_open": len(open_ids), "revote": len(pending),
                  "open_ids": open_ids,
                  "categories": {**{r["ID"].strip(): r.get("Category", "").strip()
                                    for r in (earlier or {}).get("must_fix", [])},
                                 **{i["id"]: i["Category"] for i in must}}}


def fmt_loc(location):
    location = location.strip()
    return location if location.startswith("`") else f"`{location.strip('`')}`"


def detail(item):
    return "\n".join([f"### {item['id']} — {item['Finding']}"] +
                     [f"{key}: {item[key]}" for key in DETAIL_KEYS])
