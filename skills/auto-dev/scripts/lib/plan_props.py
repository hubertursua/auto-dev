"""Plan proposals: the coder's proposed change to a step of IMPLEMENTATION.md's
build sequence, and the planner's rulings on it.

The coder writes proposals/coder-<n>.md (templates/CODER_PROPOSAL.md) when a
step can't be right as written, or the sequence lacks one, and returns
`proposals: <k>`. A plan proposal names existing steps (`step 3`, `steps 3,
5`) or adds one (`new step`), never both, and never removes or renumbers a
step. `record` holds it to that shape here; `next` (cmd_next.py) sends the
open ones to the planner in one batch file, proposals/plan-<k>.md, and the
planner answers each in proposals/plan-<k>-rulings.md (templates/RULINGS.md):
`applied` or `stands`. `record` then holds the build sequence to those
answers, diffing it against the copy of IMPLEMENTATION.md taken when the
planner was briefed (proposals/snapshots/plan-<sha>.md). Only the build
sequence is held to the rulings: the plan's other sections may follow an
applied step.

This module holds everything but the routing.
"""

import difflib
import hashlib
import re
from pathlib import Path

from . import artifacts as art
from . import proposals

ADD_STEP = re.compile(r"\bnew\s+steps?\b")
STEP_ID = re.compile(r"\b(\d+)\b")
STOPPED_RE = re.compile(r"(?i)\bsteps?\s+(\d+(?:\s*(?:,|and|&)\s*\d+)*)")
# A blocked file's line: `- step <n>: …` (the step's number at its head).
STOPPED_LINE_RE = re.compile(r"(?i)^\s*[-*]\s*steps?\s+(\d+(?:\s*(?:,|and|&)\s*\d+)*)\s*:")
BLOCKED_FILE_RE = re.compile(r"blocked[/\\]coder-(\d+)\.md\b")
# A list line that opens on a step, however it is marked up: the line a
# coder means as a stopped step, which STOPPED_LINE_RE must read.
STEP_ITEM_RE = re.compile(r"(?i)^\s*[-*]\s*[*_`]*\s*steps?\b")
FORMS = "`step <n>`, `steps <n>, <m>` or `new step`"
CHANGE_HEADER = ("IMPLEMENTATION.md was revised after your proposals. Its new or reworded "
                 "lines, quoted as they stand now:")


def _read(path):
    try:
        return Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _num(step):
    return int(step) if str(step).isdigit() else 0


def _sort(ids):
    return sorted(ids, key=_num)


# ---------------------------------------------------------------- snapshots

def snapshot(ad):
    """Copy IMPLEMENTATION.md to proposals/snapshots/plan-<sha>.md (once per
    content); its sha, or None when there is no plan."""
    try:
        data = (Path(ad) / "IMPLEMENTATION.md").read_bytes()
    except OSError:
        return None
    sha = hashlib.sha256(data).hexdigest()[:12]
    path = snapshot_path(ad, sha)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return sha


def snapshot_path(ad, sha):
    return Path(ad) / "proposals" / "snapshots" / f"plan-{sha}.md"


def steps_now(ad):
    """The build sequence's steps now (ArtifactError when it can't be read)."""
    path = Path(ad) / "IMPLEMENTATION.md"
    return art.plan_steps(art.read(path), str(path))


def steps_of(path):
    """The steps of a copy of the plan, or None when it can't be read."""
    text = _read(path)
    if text is None:
        return None
    try:
        return art.plan_steps(text, str(path))
    except art.ArtifactError:
        return None


def _diff(before, after):
    """(changed, gone, added) step numbers between two plan_steps dicts."""
    changed = [s for s in before if s in after and before[s]["words"] != after[s]["words"]]
    gone = [s for s in before if s not in after]
    added = [s for s in after if s not in before]
    return _sort(changed), _sort(gone), _sort(added)


def changed_steps(ad, sha):
    """Every step that changed, went or was added since snapshot `sha`; []
    when either side can't be read (for the log)."""
    before = steps_of(snapshot_path(ad, sha)) if sha else None
    if before is None:
        return []
    try:
        after = steps_now(ad)
    except art.ArtifactError:
        return []
    changed, gone, added = _diff(before, after)
    return _sort(changed + gone + added)


# ---------------------------------------------------------------- one proposal

def parse_target(raw):
    """(kind, ids, problem) for a plan proposal's `Target:`; kind is `change`
    or `add`."""
    text = " ".join(str(raw or "").replace("`", "").split()).lower()
    if proposals.TAKES_OUT.search(text):
        return None, [], ("would take a step out or renumber one: a plan proposal changes "
                          "named steps or adds one")
    adds = ADD_STEP.findall(text)
    ids = []
    for token in STEP_ID.findall(ADD_STEP.sub(" ", text)):
        if token not in ids:
            ids.append(token)
    if adds and ids:
        return None, ids, "adds a step and changes steps at once: file two proposals"
    if len(adds) > 1 or any(a.endswith("steps") for a in adds):
        return None, [], "adds more than one step: file one proposal per added step"
    if adds:
        return "add", [], None
    if not ids:
        return None, [], f"names no step: write {FORMS}"
    return "change", ids, None


def problems(p, steps):
    """What is wrong with one coder plan proposal, against `steps`
    (plan_steps of IMPLEMENTATION.md now); each message starts with its id."""
    pid = p["pid"]
    out = []
    if str(p.get("why", "")).strip().lower() in proposals.NONE:
        out.append(f"{pid} has no `Why:` (a missing part): say what building the code "
                   "showed is wrong with the step")
    kind, ids, problem = parse_target(p["target"])
    if problem:
        return out + [f"{pid} {problem}"]
    items = p["items"]
    item_ids = [i["id"] for i in items]
    if not items:
        out.append(f"{pid} has no `New text:` (a missing part): give the whole new text "
                   "of each step it names, or of the step it adds")
    if kind == "change":
        missing = [s for s in ids if s not in steps]
        for s in missing:
            out.append(f"{pid} names step {s}, which IMPLEMENTATION.md's build sequence "
                       f"lacks (it has steps {', '.join(steps)})")
        if items and set(item_ids) != set(ids):
            out.append(f"{pid}: its new text numbers {', '.join(item_ids) or 'nothing'} but "
                       f"its target names step(s) {', '.join(ids)}: a step is never "
                       "renumbered, and each named step needs its new text")
        for item in items:
            if item["id"] in steps and item["id"] not in missing and \
                    item["words"] == steps[item["id"]]["words"]:
                out.append(f"{pid}: new text for step {item['id']} is what it says now "
                           "(spacing aside): it changes nothing")
        return out
    want = str(max((_num(s) for s in steps), default=0) + 1)
    if len(items) > 1:
        out.append(f"{pid} adds more than one step: file one proposal per added step")
    elif items and items[0]["id"] != want:
        out.append(f"{pid}: the new step must be numbered {want}, after the last step (it "
                   f"says {items[0]['id']})")
    return out


def label(item):
    """`step 3`, `steps 3, 5`, `a new step`."""
    if item.get("kind") == "add":
        return "a new step"
    ids = item.get("targets") or []
    return ("step " if len(ids) == 1 else "steps ") + ", ".join(ids)


# ---------------------------------------------------------------- the batch file

def render_batch(entries, steps):
    """The batch file the planner reads: each entry's proposal renumbered P1…,
    with a `- From:` line, only the steps still sent, and additions numbered
    in batch order after the last step. `entries`: [{block, kind, targets, n,
    trimmed}]. Returns (text, numbers): numbers[i] is the number an addition
    is printed with, else None."""
    next_step = max((_num(s) for s in steps), default=0) + 1
    out, numbers = ["# Plan proposals", ""], []
    for k, e in enumerate(entries, 1):
        block, kind = e["block"], e["kind"]
        items = [i for i in block["items"] if kind != "change" or i["id"] in e["targets"]]
        number = None
        if kind == "add":
            number, next_step = str(next_step), next_step + 1
        numbers.append(number)
        source = f"the coder (coder #{e['n']}), its {block['pid']}"
        if e.get("trimmed"):
            source += ("; part of this proposal was not sent, since that step was already "
                       "ruled on: rule only on the steps in its Target")
        target = "new step" if kind == "add" else label({"targets": e["targets"]})
        out += [f"## P{k}", f"- Target: {target}", f"- Why: {block['why']}",
                f"- From: {source}", "- New text:"]
        for item in items[:1] if kind == "add" else items:
            lines = list(item["lines"])
            while lines and not lines[-1].strip():
                lines.pop()
            if number:
                lines[0] = re.sub(r"^\d+\.", f"{number}.", lines[0], count=1)
            out += lines
        out.append("")
    return "\n".join(out), numbers


# ---------------------------------------------------------------- the planner's answer

def stopped_steps(ad, sets):
    """The steps the coder stopped, when the brief is a blocked-mode one (its
    `blocked` value names the file); None otherwise. The file is
    <ad>/blocked/coder-<n>.md, found by its number (never a path read out of
    the prose, which may hold spaces), and a step counts only at the head of
    one of its `- step <n>:` lines: a step a line merely mentions is not
    stopped. A value that names no file is read as it stands."""
    value = str(sets.get("blocked") or "").strip()
    if value.lower() in proposals.NONE:
        return None
    match = BLOCKED_FILE_RE.search(value)
    if not match:
        return {n for group in STOPPED_RE.findall(value) for n in re.findall(r"\d+", group)}
    text = _read(Path(ad) / "blocked" / f"coder-{match.group(1)}.md") or ""
    found = set()
    for line in text.splitlines():
        head = STOPPED_LINE_RE.match(line)
        if head:
            found |= set(re.findall(r"\d+", head.group(1)))
    return found


def files_plan_proposal(ad, n):
    """Whether coder `n`'s proposal file holds a proposal on the plan (a step
    it changes or adds): the one case where the planner's combined answer
    reads the stopped steps out of its blocked file. A file record can't
    parse is refused on its own, so it counts as holding none here."""
    text = _read(proposals.file_of(ad, "coder", n))
    try:
        blocks = art.proposal_blocks(text) if text else []
    except art.ArtifactError:
        return False
    return any(proposals.classify(b["target"], coder=True)[0] == "plan" for b in blocks)


def blocked_file_issues(path):
    """A coder's blocked file must name each step it stopped the way
    stopped_steps reads it, so the planner's brief can tell which steps may
    change: a file with no `- step <n>:` line, or a list line opening on a
    step in another form, is refused while the coder can still fix it.
    `record` asks this only of a coder that also proposes a plan change
    (files_plan_proposal); without one, any blocked file that exists is read
    as it stands."""
    text = _read(path) or ""
    lines = text.splitlines()
    read = [ln for ln in lines if STOPPED_LINE_RE.match(ln)]
    odd = [ln.strip() for ln in lines if STEP_ITEM_RE.match(ln) and not STOPPED_LINE_RE.match(ln)]
    form = ("write one line per stopped step in the form `- step <n>: <why>`, the step's "
            "number in the build sequence right after `step` and a colon after it")
    issues = [f"{Path(path).name} names a step as {line!r}, which can't be read as a "
              f"stopped step: {form}" for line in odd]
    if not read and not odd:
        issues.append(f"{Path(path).name} names no stopped step: {form}")
    return issues


def answer_issues(ad, sets, issued, nxt):
    """The planner's answer to a batch of plan proposals: a ruling for each,
    `next` that agrees with them (revise mode), and the build sequence changed
    exactly as the rulings say. When the same answer decides a BLOCKED result
    (blocked mode), the steps the coder stopped may change too, and steps may
    be added beyond the applied additions."""
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
        elif ruling["answer"] not in ("applied", "stands"):
            issues.append(f"{b['pid']}'s answer is {ruling['answer'] or 'empty'!r}, not "
                          "applied or stands")
        elif ruling["answer"] == "stands" and not ruling["reason"]:
            issues.append(f"{b['pid']} stands with no reason: say why the step is right "
                          "as written")
    applied = [b for b in blocks if answers.get(b["pid"], {}).get("answer") == "applied"]
    stood = [b for b in blocks if answers.get(b["pid"], {}).get("answer") == "stands"]
    if issued.get("mode") == "revise":
        want = "REVISED" if applied else "STANDS"
        if nxt != want:
            issues.append(f"next is {nxt} but the rulings apply {len(applied)} proposal(s), "
                          f"which is {want}")
    sha = issued.get("plan")
    where = snapshot_path(ad, sha) if sha else None
    before = steps_of(where) if where else None
    if before is None:
        return issues + [("the copy of IMPLEMENTATION.md taken when you were briefed "
                          f"({where or 'none'}) is missing, so the answer can't be checked")]
    try:
        after = steps_now(ad)
    except art.ArtifactError as exc:
        return issues + [(f"IMPLEMENTATION.md's build sequence can't be read ({exc}): "
                          f"restore it as it reads in {where}, changing only what your "
                          "rulings allow")]
    changed, gone, added = _diff(before, after)
    targets = {b["pid"]: parse_target(b["target"]) for b in blocks}
    allowed = {s for b in applied if targets[b["pid"]][0] == "change"
               for s in targets[b["pid"]][1]}
    stood_named = {s for b in stood if targets[b["pid"]][0] == "change"
                   for s in targets[b["pid"]][1]}
    stopped = stopped_steps(ad, sets)
    for s in _sort(changed + gone):
        if stopped is not None:
            if s not in stood_named or s in allowed or s in stopped:
                continue
        elif s in allowed and s not in gone:
            continue
        standing = [b["pid"] for b in stood if s in targets[b["pid"]][1]]
        if s in gone:
            issues.append(f"step {s} is gone: a step is never removed or renumbered; "
                          f"restore it as it reads in {where}")
        elif standing:
            issues.append(f"step {s} changed, though {', '.join(standing)}, which names it, "
                          f"stands; restore it as it reads in {where}")
        else:
            issues.append(f"step {s} changed, but no applied proposal named it; restore it "
                          f"as it reads in {where}")
    for b in applied:
        kind, ids, _ = targets[b["pid"]]
        if kind != "change":
            continue
        for s in ids:
            if s in before and s not in changed and s not in gone:
                issues.append(f"{b['pid']} is applied but step {s} reads as before "
                              "(spacing aside)")
    adds = sum(1 for b in applied if targets[b["pid"]][0] == "add")
    last = max((_num(s) for s in before), default=0)
    want_ids = [str(last + 1 + i) for i in range(adds)]
    if (stopped is None and added != want_ids) or \
            (stopped is not None and not set(want_ids) <= set(added)):
        issues.append(f"the build sequence adds step(s) {', '.join(added) or 'none'}, but "
                      f"the applied proposals asked for {adds} new step(s) "
                      f"({', '.join(want_ids) or 'none'})")
    reasons = [(b["pid"], answers[b["pid"]]["reason"]) for b in stood]
    plan_text = _read(Path(ad) / "IMPLEMENTATION.md") or ""
    for pid, phrase in proposals.repeats(_read(where) or "", plan_text, reasons):
        issues.append(f"IMPLEMENTATION.md repeats {pid}'s stands reason (\"{phrase}\"): the "
                      "coder reads the plan, so keep the reason out of it")
    return issues


# ---------------------------------------------------------------- what the coder sees

def change_text(before, after):
    """The plan's revised lines for the coder's brief, as they read now (never
    the old ones); None when the plan is unchanged."""
    if before is None or after is None or before == after:
        return None
    old, new = before.splitlines(), after.splitlines()
    quoted = []
    for tag, _i1, _i2, j1, j2 in difflib.SequenceMatcher(None, old, new).get_opcodes():
        if tag in ("replace", "insert"):
            quoted += [f"> {line}".rstrip() for line in new[j1:j2]]
        elif tag == "delete":
            quoted.append(f"> (lines removed after line {j1})")
    if not quoted:
        return None
    return "\n".join([CHANGE_HEADER, *quoted])
