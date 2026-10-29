"""Check proposals: a claim that a held-out acceptance check is wrong, and the
acceptance tester's rulings on it, one per condition.

Four sources question a check: the coder, in its proposal file
(proposals/coder-<n>.md, templates/CODER_PROPOSAL.md), naming one check it
was shown as MANIFEST.md writes it (`check `<path>` :: "<test name>"`); the
verifier's `REPAIR` (SPEC_EVAL.md, Defective acceptance checks); the review
judge's must-fix row of category `acceptance-check`; and the triager's
ACCEPTANCE_CHECK entries (its checks file). The item ruled on is a condition:
every condition with a MANIFEST.md row naming the questioned check (a check
under conditions 1 and S1 is ruled on twice), or, for a finding or comment,
every condition with a check in the file it names. One that names no file
MANIFEST.md knows is an unnamed item. `next` (cmd_next.py) sends them to the
tester's repair mode as one batch file, proposals/checks-<k>.md, and the
tester answers each in proposals/checks-<k>-rulings.md (templates/RULINGS.md):
`repaired` or `stands`. `record` then holds the sealed copies and MANIFEST.md
to those answers, against the copy taken when the tester was briefed
(proposals/snapshots/acceptance-tester-<n>/).

This module holds everything but the routing.
"""

import re
import shutil
from pathlib import Path

from . import artifacts as art
from . import cmd_checks, proposals, sealed

CHECK_REF_RE = re.compile(r"`[^`]+`\s*::")
CHECK_TARGET_RE = re.compile(r'(?:\bcheck\s+)?`([^`]+)`\s*::\s*(?:"([^"]+)"|([^`"\n]+?)\s*$)',
                             re.IGNORECASE)
CONDITION_RE = re.compile(r"^condition (S?\d+)\b")
WHERE_RE = re.compile(r"^\s*Where:\s*(.*)$")
ENTRY_RE = re.compile(r"^(\d+)\.\s")
CHECK_COLUMN = "Check (path :: test name)"
FORM = "check `<path>` :: \"<test name>\""


def _read(path):
    try:
        return Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _sort(ids):
    return sorted(ids, key=cmd_checks.sort_key)


# ---------------------------------------------------------------- MANIFEST.md

def rows_of(path):
    """MANIFEST.md's check rows, [] when it is missing or malformed."""
    try:
        rows, _ = art.manifest(path)
    except art.ArtifactError:
        return []
    return rows


def rows(ad):
    return rows_of(Path(ad) / "acceptance" / "MANIFEST.md")


def ref(cell):
    """(path, test name) of a MANIFEST.md check cell, or None."""
    match = cmd_checks.CHECK_REF_RE.search(cell or "")
    return (match.group(1).strip(), match.group(2).strip()) if match else None


def owners(rows_, path, name):
    """Every condition with a row naming check `path` :: `name`."""
    want = (str(path).strip(), str(name).strip())
    return _sort({r["#"].strip() for r in rows_ if ref(r[CHECK_COLUMN]) == want})


def file_owners(rows_):
    """{file: set of conditions with a check in it}."""
    found = {}
    for r in rows_:
        rel = art.check_path(r[CHECK_COLUMN])
        if rel:
            found.setdefault(rel, set()).add(r["#"].strip())
    return found


def in_file(rows_, rel):
    return _sort(file_owners(rows_).get(str(rel).strip(), set()))


def checks_of(rows_, cid, rel=None):
    """The check cells of condition `cid` (in file `rel`, when given)."""
    return [r[CHECK_COLUMN].strip() for r in rows_ if r["#"].strip() == cid
            and (rel is None or art.check_path(r[CHECK_COLUMN]) == rel)]


# ---------------------------------------------------------------- one proposal

def parse_target(raw):
    """((path, test name), problem) for a check proposal's `Target:`."""
    text = str(raw or "")
    named = CHECK_REF_RE.findall(text)
    if len(named) > 1:
        return None, "names more than one check: file one proposal per check"
    match = CHECK_TARGET_RE.search(text)
    if not named or not match:
        return None, f"names no check: write {FORM}"
    name = (match.group(2) or match.group(3) or "").strip()
    if not name:
        return None, f"names no check: write {FORM}"
    return (match.group(1).strip(), name), None


def strip_check(raw):
    """The Target with its check reference taken out, so the words of a test
    name never count as a step or a condition."""
    text = str(raw or "")
    match = CHECK_TARGET_RE.search(text)
    if match:
        return text[:match.start()] + " " + text[match.end():]
    start = text.find("`")
    return text[:start] if CHECK_REF_RE.search(text) and start >= 0 else text


def names_check(raw):
    return bool(CHECK_REF_RE.search(str(raw or "")))


def shown_paths(ad, worker, n):
    """The check files job <worker>-<n>'s brief listed (its acceptance_paths
    line): each MANIFEST.md file that starts an entry there."""
    text = _read(Path(ad) / "briefs" / f"{worker}-{n}.md") or ""
    match = re.search(r"^acceptance_paths: (.*)$", text, re.MULTILINE)
    value = match.group(1).strip() if match else ""
    if value.lower() in ("", "none"):
        return set()
    return {rel for rel in file_owners(rows(ad))
            if re.search(rf"(?:^|; ){re.escape(rel)}(?= \(tests:|;|$)", value)}


def problems(p, rows_, shown):
    """What is wrong with one coder check proposal: it names one check, from a
    file its brief listed (`shown`; None when unknown), that MANIFEST.md lists
    as a held-out check. Each message starts with its id."""
    pid = p["pid"]
    out = []
    if str(p.get("why", "")).strip().lower() in proposals.NONE:
        out.append(f"{pid} has no `Why:` (a missing part): say what the check asserts "
                   "that the change shouldn't do")
    check, problem = parse_target(p["target"])
    if problem:
        return out + [f"{pid} {problem}"]
    path, name = check
    if shown is not None and not shown:
        return out + [(f"{pid} questions a check, but you were shown no check: your brief "
                       "listed no acceptance check file, so you may question only steps")]
    if shown is not None and path not in shown:
        return out + [(f"{pid} questions a check in `{path}`, which is not one of the check "
                       f"files your brief listed (it listed: {', '.join(sorted(shown))})")]
    if not owners(rows_, path, name):
        out.append(f"{pid} names \"{name}\" in `{path}`, which MANIFEST.md lists as no "
                   "check: that is one of your own tests, not a held-out check")
    return out


def label(item):
    """`the checks of condition 4 (the verifier)`, or for the coder the check
    itself: the check `<path>` :: "<test name>" (the coder)."""
    check = item.get("check")
    if check:
        return f"the check `{check[0]}` :: \"{check[1]}\" (the coder)"
    who = item.get("who") or "the verifier"
    cid = item.get("cid")
    return (f"the checks of condition {cid} ({who})" if cid else
            f"the checks {who} questions")


# ---------------------------------------------------------------- snapshots

def snapshot_dir(ad, name):
    return Path(ad) / "proposals" / "snapshots" / str(name)


def snapshot(ad, name):
    """Copy MANIFEST.md and every sealed copy into
    proposals/snapshots/<name>/ (MANIFEST.md, files/<path>.sealed), once."""
    where = snapshot_dir(ad, name)
    if where.exists():
        return name
    (where / "files").mkdir(parents=True, exist_ok=True)
    manifest = Path(ad) / "acceptance" / "MANIFEST.md"
    if manifest.exists():
        shutil.copyfile(manifest, where / "MANIFEST.md")
    for rel, path in sealed.sealed_files(ad).items():
        target = where / "files" / f"{rel}.sealed"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    return name


def _bytes(path):
    try:
        return Path(path).read_bytes()
    except OSError:
        return None


def _groups(rows_):
    """{condition: its MANIFEST.md rows, each a tuple of whitespace-collapsed
    cells, sorted}."""
    found = {}
    for r in rows_:
        found.setdefault(r["#"].strip(), []).append(
            tuple(" ".join(str(v).split()) for v in r.values()))
    return {cid: tuple(sorted(group)) for cid, group in found.items()}


def diff(ad, name):
    """(changed sealed files, row groups before, row groups now, file owners
    before, file owners now) between snapshot `name` and now."""
    where = snapshot_dir(ad, name)
    root = where / "files"
    before = ({str(p.relative_to(root).with_suffix("")).replace("\\", "/"): p
               for p in root.rglob("*.sealed")} if root.is_dir() else {})
    now = sealed.sealed_files(ad)
    changed = sorted(rel for rel in set(before) | set(now)
                     if _bytes(before.get(rel, root / "-")) != _bytes(now.get(rel, root / "-")))
    rows_before, rows_after = rows_of(where / "MANIFEST.md"), rows(ad)
    return (changed, _groups(rows_before), _groups(rows_after), file_owners(rows_before),
            file_owners(rows_after))


def changed_conditions(ad, name):
    """The conditions whose checks changed since snapshot `name`: every owner
    of a changed sealed file, and every condition whose MANIFEST.md rows
    differ; [] without the snapshot."""
    if not name or not snapshot_dir(ad, name).is_dir():
        return []
    changed, before, after, owned_before, owned_after = diff(ad, name)
    ids = set()
    for rel in changed:
        ids |= owned_before.get(rel, set()) | owned_after.get(rel, set())
    ids |= {cid for cid in set(before) | set(after) if before.get(cid) != after.get(cid)}
    return _sort(ids)


# ---------------------------------------------------------------- triage

def triage_entries(path):
    """[(entry number, file or None)] for a checks file: each numbered entry's
    first `Where:` file (its first backticked span, else its first word), with
    a trailing `:<line>` or `:<a>-<b>` taken off."""
    found, current = [], None
    for line in (_read(path) or "").splitlines():
        match = ENTRY_RE.match(line)
        if match:
            current = [match.group(1), None]
            found.append(current)
            continue
        where = WHERE_RE.match(line)
        if where and current is not None and current[1] is None:
            value = where.group(1).strip()
            span = re.search(r"`([^`]+)`", value)
            token = span.group(1).strip() if span else (value.split() or [""])[0]
            token = re.sub(r":\d+(?:-\d+)?$", "", token.strip())
            current[1] = token or None
    return [tuple(e) for e in found]


# ---------------------------------------------------------------- the batch file

def render_batch(items, rows_):
    """The batch file the tester reads: one `## P<k>` block per condition (or
    one for the checks a report names with no condition), its questioned
    checks and one `- From:` line per source."""
    out = ["# Check proposals", ""]
    for k, item in enumerate(items, 1):
        cid = item.get("cid")
        target = (f"condition {cid}" if cid else
                  "no condition named — the checks the report names")
        checks = []
        for src in item.get("srcs", []):
            for cell in src.get("checks") or []:
                if cell not in checks:
                    checks.append(cell)
        if not checks and cid:
            checks = checks_of(rows_, cid)
        out += [f"## P{k}", f"- Target: {target}",
                "- Checks: " + ("; ".join(checks) or "the ones the report names")]
        out += [f"- From: {src['what']}" for src in item.get("srcs", [])]
        out.append("")
    return "\n".join(out)


# ---------------------------------------------------------------- the tester's answer

def answer_issues(ad, sets, issued, nxt):
    """The tester's answer to a batch of check proposals: a ruling for each
    item, `next` that agrees with them, and the sealed copies and MANIFEST.md
    changed only as the rulings allow."""
    batch = Path(proposals._batch_path(sets))
    rulings_path = Path(str(sets.get("rulings_file") or ""))
    text = _read(batch)
    if text is None:
        return [f"the batch file {batch} is missing"]
    blocks = art.proposal_blocks(text)
    answers_text = _read(rulings_path)
    if answers_text is None:
        return [f"no rulings file at {rulings_path}: write it to templates/RULINGS.md"]
    answers = art.rulings(answers_text)
    issues = []
    for b in blocks:
        ruling = answers.get(b["pid"])
        if ruling is None:
            issues.append(f"{rulings_path.name} has no ruling for {b['pid']}")
        elif ruling["answer"] not in ("repaired", "stands"):
            issues.append(f"{b['pid']}'s answer is {ruling['answer'] or 'empty'!r}, not "
                          "repaired or stands")
        elif ruling["answer"] == "stands" and not ruling["reason"]:
            issues.append(f"{b['pid']} stands with no reason: say why its checks are right "
                          "against SPEC.md as written")
    ruled = {b["pid"]: answers.get(b["pid"], {}).get("answer") for b in blocks}
    want = "REPAIRED" if "repaired" in ruled.values() else "STANDS"
    if nxt != want:
        issues.append(f"next is {nxt} but the rulings repair "
                      f"{list(ruled.values()).count('repaired')} item(s), which is {want}")
    cids = {}
    for b in blocks:
        match = CONDITION_RE.match(" ".join(b["target"].replace("`", "").split()))
        cids[b["pid"]] = match.group(1).upper() if match else None
    repaired = {cids[p] for p, a in ruled.items() if a == "repaired" and cids[p]}
    stood = {cids[p] for p, a in ruled.items() if a == "stands" and cids[p]}
    unnamed = any(c is None for c in cids.values())
    name = issued.get("sealed")
    if not name or not snapshot_dir(ad, name).is_dir():
        return issues + [("the copy of the sealed checks taken when you were briefed "
                          f"({snapshot_dir(ad, name or 'none')}) is missing, so the "
                          "answer can't be checked")]
    changed, before, after, owned_before, owned_after = diff(ad, name)
    for cid in _sort(repaired):
        files = {rel for rel, ids in list(owned_before.items()) + list(owned_after.items())
                 if cid in ids}
        if not files & set(changed) and before.get(cid) == after.get(cid):
            issues.append(f"condition {cid} is ruled repaired, but none of the sealed copies "
                          "with its checks changed, and its MANIFEST.md rows are as they "
                          "were")
    root = snapshot_dir(ad, name) / "files"
    for rel in changed:
        # A file the snapshot had is held by its owners then; with no unnamed
        # item, a new one by its owners now.
        existed = (root / f"{rel}.sealed").is_file()
        holders = owned_before.get(rel, set()) if existed else (
            set() if unnamed else owned_after.get(rel, set()))
        if not holders:
            continue
        held = holders <= stood if unnamed else not holders & repaired
        if held:
            issues.append(f"acceptance/files/{rel}.sealed changed, but it is outside your "
                          "scope: no condition it holds checks for was ruled repaired in "
                          "this batch; leave it as it was")
    for cid in _sort(stood):
        if before.get(cid) != after.get(cid):
            issues.append(f"MANIFEST.md's rows for condition {cid} changed, though it "
                          "stands: restore them")
    if not unnamed:
        issues += outside_rows(ad, name, repaired, stood)
    reasons = [(p, answers[p]["reason"]) for p, a in ruled.items() if a == "stands"]
    now = sealed.sealed_files(ad)
    for rel in changed:
        if rel not in now:
            continue
        for pid, phrase in proposals.repeats(_read(root / f"{rel}.sealed") or "",
                                             _read(now[rel]) or "", reasons):
            issues.append(f"acceptance/files/{rel}.sealed repeats {pid}'s stands reason "
                          f"(\"{phrase}\"): a coder's correction brief names this file, so "
                          "keep the reason out of it")
    return issues


def _row_key(r):
    return tuple(" ".join(str(v).split()) for v in r.values())


def outside_rows(ad, name, repaired, stood):
    """A named batch changes MANIFEST.md's rows only for a condition it ruled
    repaired: each condition outside the batch whose rows changed is refused,
    unless the change is the rename of a check it shares with a repaired
    condition. Each row it lost must name a check (path and test name) a
    repaired condition's row named in the snapshot, each row it gained one a
    repaired condition's row names now, and the two pair one to one, so a
    deleted row, a row moved to another condition and a new row are refused."""
    rows_before = rows_of(snapshot_dir(ad, name) / "MANIFEST.md")
    rows_after = rows(ad)
    keys_before = {_row_key(r) for r in rows_before}
    keys_after = {_row_key(r) for r in rows_after}
    gone, added = {}, {}
    for r in rows_before:
        if _row_key(r) not in keys_after:
            gone.setdefault(r["#"].strip(), []).append(ref(r[CHECK_COLUMN]))
    for r in rows_after:
        if _row_key(r) not in keys_before:
            added.setdefault(r["#"].strip(), []).append(ref(r[CHECK_COLUMN]))
    shared_before = {ref(r[CHECK_COLUMN]) for r in rows_before
                     if r["#"].strip() in repaired} - {None}
    shared_after = {ref(r[CHECK_COLUMN]) for r in rows_after
                    if r["#"].strip() in repaired} - {None}
    issues = []
    for cid in _sort((set(gone) | set(added)) - set(repaired) - set(stood)):
        lost, gained = gone.get(cid, []), added.get(cid, [])
        renamed = (len(lost) == len(gained)
                   and all(check in shared_before for check in lost)
                   and all(check in shared_after for check in gained))
        if not renamed:
            issues.append(f"MANIFEST.md's rows for condition {cid} changed, but no ruling in "
                          "this batch repaired it: change rows only for a condition you "
                          "ruled repaired, and another condition's row only to rename a "
                          "check the two share; restore them")
    return issues
