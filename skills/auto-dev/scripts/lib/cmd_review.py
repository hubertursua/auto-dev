"""autodev.py votes / review-scope / gate-summary.

Each takes `--dir <artifact-dir>` (default `./.auto-dev`) and `--json`.

votes --plan
    Reads CODE_REVIEW.md's `Pending re-vote` table and the latest pass's
    R<k>.md reports, and prints which re-voter to spawn for which findings: one
    per reviewer slot that wrote a usable report and did not raise the finding.
    A pass that called one reviewer (its review/pass-<n>/PANEL file names it)
    has the other two slots re-vote on that reviewer's findings.
    Exit: 0 (`NONE` when there is nothing to re-vote).

votes --apply
    Reads review/pass-<n>/VOTES-R<k>.md and moves each pending finding in
    CODE_REVIEW.md: the reviewer who raised it plus every `agree` reaching 2 is
    must-fix, Medium; fewer is advisory, Low. Then recomputes the header counts
    and the overall confidence (High: every reviewer called finished (3/3, or
    1/1 on a small correction's re-review), full coverage, nothing decided 2-1;
    Low: fewer than 2 of 3, or 0 of 1, reviewers; Medium otherwise), and appends
    each new must-fix finding to review/pass-<n>/corrections.md, numbered after
    the entries already there: its `Required change:` line, then the `Where:`
    (else the row's Location), `Now:` (its `Trigger path:`) and `Test:` lines
    from its `### <id>` block. A new must-fix finding whose Category is
    `acceptance-check` is not added there: it is printed on the
    `acceptance_check:` line, for the acceptance tester's repair mode;
    `must_fix:` lists the ones added for the coder. Each slot --plan names must
    have voted, in its VOTES-R<k>.md, on every finding it was given. One vote
    per slot and finding counts; a vote on a finding the slot was not given
    (the raiser's own) is ignored.
    Exit: 0 applied; 1 a planned re-voter's file or vote is missing, a new
    must-fix finding for the coder has no `Required change:` line, or an empty
    one (re-spawn the judge), or an
    artifact is malformed (a vote not agree/disagree, a finding voted both
    ways, an `**Overall confidence` line without `reviewers finished: <n>/3`
    (or `<n>/1` for a pass that called one reviewer) and `coverage:`);
    nothing is written.

review-scope --snapshot | --files | --clear | --next-pass
    --snapshot  marks untracked files intent-to-add, then records the working
                tree's hash as the snapshot to diff a correction against. Keeps
                an existing snapshot: one per pending correction, not per round.
    --files     prints the files changed since the snapshot (the scope of the
                cleanup re-spawn and the next panel pass).
    --clear     forgets the snapshot once a panel pass has reviewed it.
    --next-pass creates review/pass-<n>/ for the next pass and prints <n>.
    Exit: 0; 1 --files with no snapshot recorded.

gate-summary <post-plan|pr|main> [--pr N]
    Checks the gate's preconditions, then prints the summary and the
    AskUserQuestion JSON to ask with (on the line after `QUESTION:`).
    pr: every report is fresh, one passing lint report per gate command, no
    submodule holds uncommitted edits (`git submodule foreach` lists them),
    no Unjustified integrity finding is open; then the acceptance block and
    the two reviews, and one triage question per pre-existing security finding
    whose Verdict is `for the user`, most severe first (with more than three,
    the two most severe and one question for the rest, headed `Others`). Each
    answer is recorded with `mark triage-<ID or Others> --value separate|ignore`;
    a finding sent to a separate PR is listed in the PR body as a follow-up.
    main: the PR is open and not a draft, and every result was checked on its
    head commit.
    Exit: 0 printed; 1 a precondition failed (the reason says what to do; do
    not ask the gate): `STALE` when a result no longer matches the code,
    `PRECONDITION` otherwise; 2 check-fresh.py, `git submodule foreach` or gh
    could not run.

All exit 2 when they could not run — never a pass.
"""

import json
import re
import sys
from pathlib import Path

from . import artifacts as art
from . import state as st
from .cmd_checks import git_add_intent
from .cmd_ship import check_fresh
from .output import CANNOT_RUN, FAILED, Fail, emit
from .proc import git, run

SCRIPTS = Path(__file__).resolve().parent.parent
PASS_RE = re.compile(r"Latest pass:\s*(\d+)")
REVIEWERS_RE = re.compile(r"reviewers finished:\s*([0-3])/([13])")
COVERAGE_RE = re.compile(r"coverage:\s*(full|partial)")
GATE_OPTIONS = {
    "post-plan": ["Approve & build", "Revise plan (tell me what to change)", "Stop"],
    "pr": ["Open PR", "Hold (don't push yet)", "Stop"],
    "main": ["Merge PR to main", "Hold", "Stop"],
}
# A pre-existing security finding's triage answers, and the value `mark
# triage-<id>` records for each.
TRIAGE_VALUES = {"Separate PR (note it as a follow-up)": "separate", "Ignore it": "ignore"}
TRIAGE = list(TRIAGE_VALUES)


def add_arguments(parser, name):
    parser.add_argument("--dir", default=".auto-dev", help="the run's .auto-dev/")
    if name == "votes":
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument("--plan", action="store_true")
        mode.add_argument("--apply", action="store_true")
    elif name == "review-scope":
        mode = parser.add_mutually_exclusive_group(required=True)
        for flag in ("--snapshot", "--files", "--clear", "--next-pass"):
            mode.add_argument(flag, action="store_true")
    elif name == "gate-summary":
        parser.add_argument("gate", choices=sorted(GATE_OPTIONS))
        parser.add_argument("--pr", help="the PR number (default: from state)")


def wrap(fn):
    def run_it(args):
        try:
            return fn(args)
        except art.ArtifactError as exc:
            missing = "does not exist" in str(exc) or "cannot read" in str(exc)
            raise Fail(str(exc), CANNOT_RUN if missing else FAILED,
                       "ERROR" if missing else "MALFORMED") from None
        except st.StateError as exc:
            raise Fail(str(exc), CANNOT_RUN, "ERROR") from None
    return run_it


# ---------------------------------------------------------------- votes

def latest_pass(text):
    match = PASS_RE.search(text)
    if not match:
        raise art.ArtifactError("CODE_REVIEW.md: no `Latest pass: <n>` line")
    return int(match.group(1))


def pending_rows(text):
    body = art.find_section(text, "Pending re-vote")
    if body is None:
        raise art.ArtifactError("CODE_REVIEW.md: no `## Pending re-vote` section")
    for header, rows in art.tables(body):
        if "ID" in header:
            return [r for r in rows if r.get("ID", "").strip()]
    return []


def raisers(cell):
    return set(re.findall(r"R\d", cell))


@wrap
def votes(args):
    ad = Path(args.dir)
    path = ad / "CODE_REVIEW.md"
    text = art.read(path)
    n = latest_pass(text)
    pass_dir = ad / "review" / f"pass-{n}"
    pending = pending_rows(text)
    if args.plan:
        return plan_votes(args, pass_dir, pending)
    return apply_votes(args, path, text, pass_dir, pending)


def usable(path):
    try:
        return "## Findings" in path.read_text(encoding="utf-8")
    except OSError:
        return False


PANEL_FILE = "PANEL"


def write_panel(pass_dir, slots):
    """Note the reviewers a pass called, when fewer than three (a small fix)."""
    path = pass_dir / PANEL_FILE
    if len(slots) < 3:
        path.write_text(", ".join(slots) + "\n", encoding="utf-8")
    elif path.exists():
        path.unlink()


def called(pass_dir):
    """The reviewer slots pass_dir's pass called: all three unless PANEL says."""
    path = pass_dir / PANEL_FILE
    if not path.exists():
        return ["R1", "R2", "R3"]
    return [s.strip() for s in path.read_text(encoding="utf-8").split(",") if s.strip()]


def vote_plan(pass_dir, pending):
    """{reviewer slot: [finding ids]}: who re-votes on what. A pass that called
    one reviewer (a small correction) has the other two re-vote."""
    slots = [f"R{k}" for k in (1, 2, 3) if usable(pass_dir / f"R{k}.md")]
    if len(called(pass_dir)) == 1 and slots == called(pass_dir):
        slots = ["R1", "R2", "R3"]
    plan = {}
    if len(slots) >= 2:
        for row in pending:
            for slot in slots:
                if slot not in raisers(row.get("Raised by", "")):
                    plan.setdefault(slot, []).append(row["ID"].strip())
    return plan


def plan_votes(args, pass_dir, pending):
    plan = vote_plan(pass_dir, pending)
    if not plan:
        emit(args.json, "NONE", "no re-votes: nothing pending, or fewer than two "
             "usable reports (every lone finding stays advisory)")
        return 0
    emit(args.json, "REVOTE", f"spawn {len(plan)} auto-dev:code-reviewer(s) in "
         f"re-vote mode, in parallel, writing {pass_dir}/VOTES-R<k>.md",
         spawn=[f"{slot}: {', '.join(ids)}" for slot, ids in sorted(plan.items())])
    return 0


def read_votes(pass_dir, plan):
    """{finding id: {slot: agree?}}: each planned slot's one vote per finding.

    A vote on a finding not planned for that slot (the raiser's own, or one it
    was not asked about) is ignored."""
    found, missing = {}, []
    for slot, ids in sorted(plan.items()):
        path = pass_dir / f"VOTES-{slot}.md"
        if not path.exists():
            missing += [f"{fid} ({slot}: no {path.name})" for fid in ids]
            continue
        _, rows = art.first_table(art.read(path), ("Finding", "Vote"), str(path))
        mine = {}
        for row in rows:
            fid, vote = row["Finding"].strip(), row["Vote"].strip().lower()
            if vote not in ("agree", "disagree"):
                raise art.ArtifactError(f"{path}: vote `{row['Vote']}` is not "
                                        "agree/disagree")
            if fid not in ids:
                continue
            if mine.get(fid, vote == "agree") != (vote == "agree"):
                raise art.ArtifactError(f"{path}: {fid} is voted both agree and disagree")
            mine[fid] = vote == "agree"
        missing += [f"{fid} ({slot})" for fid in ids if fid not in mine]
        for fid, agree in mine.items():
            found.setdefault(fid, {})[slot] = agree
    return found, missing


def apply_votes(args, path, text, pass_dir, pending):
    if not pending:
        emit(args.json, "NONE", "no pending re-votes")
        return 0
    must, advisory, tester = apply_vote_files(path, text, pass_dir, pending)
    of_them = f" ({len(tester)} acceptance-check)" if tester else ""
    emit(args.json, "APPLIED", f"{len(must) + len(tester)} must-fix{of_them}, "
         f"{advisory} advisory",
         must_fix=", ".join(must) or "none", acceptance_check=", ".join(tester))
    return 0


def apply_vote_files(path, text, pass_dir, pending, votes_expected=True):
    """Move each pending finding by its votes.

    Returns (new must-fix ids for the coder, advisory count, new must-fix ids
    whose Category is acceptance-check, for the acceptance tester). Every slot
    vote_plan names must have voted on each finding it was given.

    With votes_expected False (fewer than two usable reports, so nobody re-voted)
    every pending finding counts its raiser alone and stays advisory."""
    if not votes_expected:
        cast, missing = {}, []
    else:
        plan = vote_plan(pass_dir, pending)
        cast, missing = read_votes(pass_dir, plan)
        if not plan:
            missing = [r["ID"].strip() for r in pending]
    if missing:
        raise art.ArtifactError(f"no re-vote recorded for {', '.join(missing)} in "
                                f"{pass_dir}: re-spawn those re-voters")
    must, advisory, decided_2_1 = [], [], []
    coder, tester, where = [], [], {}
    for row in pending:
        fid = row["ID"].strip()
        count = 1 + sum(1 for agree in cast.get(fid, {}).values() if agree)
        cells = (fid, row.get("Finding", ""), row.get("Location", ""),
                 row.get("Category", ""))
        if count >= 2:
            must.append(f"| {' | '.join(cells)} | {count}/3 (re-vote) | Medium | open |")
            if row.get("Category", "").strip().strip("`").lower() == "acceptance-check":
                tester.append(fid)
            else:
                coder.append(fid)
                where[fid] = row.get("Location", "").strip()
            if count == 2:
                decided_2_1.append(fid)
        else:
            advisory.append(f"| {' | '.join(cells)} | {count}/3 (re-vote) | Low | "
                            f"lone finding; re-vote {count}/3 |")
    text = add_rows(text, "Must-fix", must)
    text = add_rows(text, "Advisory", advisory)
    text = clear_pending(text)
    text = recount(text, decided_2_1, len(called(pass_dir)))
    # Corrections first: it raises before writing if a Required change is missing,
    # so a failure leaves both files as they were.
    add_corrections(text, pass_dir / "corrections.md", coder, where)
    tmp = path.with_name(".CODE_REVIEW.md.votes")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
    return coder, len(advisory), tester


def detail_line(block, key):
    """The non-empty value of a `<key>: <value>` line in a finding's block, or None."""
    match = re.search(rf"^[ \t]*{key}:[ \t]*(\S.*)$", block, re.MULTILINE)
    return match.group(1).strip() if match else None


def add_corrections(text, path, ids, where=None):
    """Append each new must-fix finding's Required change to corrections.md.

    Each entry also carries the finding's Where (else `where[id]`, the row's
    Location), Now (its Trigger path) and Test lines, when it has them."""
    if not ids:
        return
    entries = []
    for fid in ids:
        found = re.search(rf"^### {re.escape(fid)}\b.*?(?=^### |^## |\Z)", text,
                          re.MULTILINE | re.DOTALL)
        block = found.group(0) if found else ""
        change = detail_line(block, "Required change")
        if not change:
            raise art.ArtifactError(f"CODE_REVIEW.md: {fid} has no `Required change:` "
                                    "line under its heading; re-spawn the judge")
        lines = [f"{fid}: {change}"]
        for label, value in (("Where", detail_line(block, "Where")
                              or (where or {}).get(fid)),
                             ("Now", detail_line(block, "Trigger path")),
                             ("Test", detail_line(block, "Test"))):
            if value:
                lines.append(f"   {label}: {value}")
        entries.append("\n".join(lines))
    existing = path.read_text(encoding="utf-8") if path.exists() else "# Required changes\n"
    existing = re.sub(r"^[ \t]*None\.[ \t]*$", "", existing,
                      flags=re.MULTILINE).rstrip() + "\n"
    count = len(re.findall(r"^[ \t]*\d+\. ", existing, re.MULTILINE))
    for i, entry in enumerate(entries, count + 1):
        existing += f"{i}. {entry}\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(existing, encoding="utf-8")


def section_span(lines, name):
    start = next((i for i, ln in enumerate(lines) if ln.startswith(f"## {name}")), None)
    if start is None:
        raise art.ArtifactError(f"CODE_REVIEW.md: no `## {name}` section")
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")),
               len(lines))
    return start, end


def add_rows(text, name, rows):
    if not rows:
        return text
    lines = text.split("\n")
    start, end = section_span(lines, name)
    # Drop a lone `none` line the judge wrote for an empty section.
    lines = [ln for i, ln in enumerate(lines)
             if not (start < i < end and ln.strip().lower() == "none")]
    start, end = section_span(lines, name)
    table = [i for i in range(start, end) if lines[i].lstrip().startswith("|")]
    if not table:
        raise art.ArtifactError(f"CODE_REVIEW.md: `## {name}` has no table")
    lines[table[-1] + 1:table[-1] + 1] = rows
    return "\n".join(lines)


def clear_pending(text):
    lines = text.split("\n")
    start, end = section_span(lines, "Pending re-vote")
    table = [i for i in range(start, end) if lines[i].lstrip().startswith("|")]
    keep = set(table[:2])  # the header and separator
    lines = [ln for i, ln in enumerate(lines) if not (i in table and i not in keep)]
    return "\n".join(lines)


def count_rows(text, name, status=None):
    body = art.find_section(text, name) or ""
    for header, rows in art.tables(body):
        if "ID" in header:
            rows = [r for r in rows if r.get("ID", "").strip()]
            if status:
                rows = [r for r in rows if r.get("Status", "").startswith(status)]
            return len(rows)
    return 0


def recount(text, decided_2_1, total=None):
    """The header's counts and overall confidence, recomputed. `total` is how
    many reviewers the pass called (its PANEL file); without it, the header's."""
    open_, fixed = count_rows(text, "Must-fix", "open"), count_rows(text, "Must-fix", "fixed")
    advisory, noise = count_rows(text, "Advisory"), count_rows(text, "Noise")
    head = art.header_line(text, "**Overall confidence")
    reviewers = REVIEWERS_RE.search(head)
    coverage = COVERAGE_RE.search(head)
    if not reviewers or not coverage:
        raise art.ArtifactError("CODE_REVIEW.md: the `**Overall confidence` line does "
                                "not say `reviewers finished: <n>/<3 or 1>` and `coverage: "
                                "full|partial`; re-spawn the judge")
    finished = int(reviewers.group(1))
    total = total or int(reviewers.group(2))
    finished = min(finished, total)
    full = coverage.group(1) == "full"
    prior = re.search(r"must-fix decided 2[–-]1:\s*([^>*\n]*)", head)
    earlier = [x.strip() for x in (prior.group(1) if prior else "").split(",")
               if x.strip() and x.strip() != "none"]
    two_one = earlier + [x for x in decided_2_1 if x not in earlier]
    if finished < min(2, total):
        level = "Low"
    elif finished == total and full and not two_one:
        level = "High"
    else:
        level = "Medium"
    new_head = (f"**Overall confidence: {level}** — reviewers finished: {finished}/{total}; "
                f"coverage: {'full' if full else 'partial'}; must-fix decided 2–1: "
                f"{', '.join(two_one) or 'none'}")
    text = text.replace(head, new_head, 1)
    dropped = re.search(r"Dropped \(pre-existing\):\s*(\d+)", text)
    counts = (f"Must-fix: {open_} open · {fixed} fixed   ·   Advisory: {advisory}   ·   "
              f"Noise: {noise}   ·   Dropped (pre-existing): "
              f"{dropped.group(1) if dropped else 0}")
    return re.sub(r"^Must-fix: \d+ open.*$", counts, text, count=1, flags=re.MULTILINE)


# ---------------------------------------------------------------- review-scope

@wrap
def review_scope(args):
    state = st.load(args.dir)
    wt = state["worktree"]
    phase6 = state.setdefault("phase6", {})
    if args.next_pass:
        n = phase6.get("review_pass", 0) + 1
        (Path(args.dir) / "review" / f"pass-{n}").mkdir(parents=True, exist_ok=True)
        phase6["review_pass"] = n
        st.save(args.dir, state)
        emit(args.json, "PASS", str(n), dir=str(Path(args.dir) / "review" / f"pass-{n}"))
        return 0
    if args.clear:
        phase6.pop("snapshot", None)
        st.save(args.dir, state)
        emit(args.json, "CLEARED", "snapshot forgotten")
        return 0
    git_add_intent(wt)
    tree = print_tree(wt)
    if args.snapshot:
        if phase6.get("snapshot"):
            emit(args.json, "KEPT", phase6["snapshot"], reason="a correction is still "
                 "unreviewed; its snapshot covers this one too")
            return 0
        phase6["snapshot"] = tree
        st.add_note(state, f"review snapshot {tree}")
        st.save(args.dir, state)
        emit(args.json, "SNAPSHOT", tree)
        return 0
    snap = phase6.get("snapshot")
    if not snap:
        raise Fail("no snapshot recorded: take one with --snapshot before dispatching "
                   "the correction", FAILED, "NO-SNAPSHOT")
    files = [f for f in git(wt, "diff", "--name-only", snap, tree).splitlines()
             if f and not f.startswith(".auto-dev/")]
    emit(args.json, "FILES", f"{len(files)} file(s) changed since {snap[:12]}", file=files)
    return 0


def print_tree(wt):
    code, out, err = run([sys.executable, str(SCRIPTS / "check-fresh.py"),
                          "--print-tree", wt], check=False)
    if code != 0:
        raise Fail(f"check-fresh.py --print-tree failed: {err.strip()}", CANNOT_RUN, "ERROR")
    return out.strip()


# ---------------------------------------------------------------- gate-summary

def question(header, text, options):
    return {"question": text, "header": header, "multiSelect": False,
            "options": [{"label": o, "description": ""} for o in options]}


@wrap
def gate_summary(args):
    state = st.load(args.dir)
    ad = Path(args.dir)
    builder = {"post-plan": post_plan_summary, "pr": pr_summary,
               "main": main_summary}[args.gate]
    lines, extra_questions = builder(state, ad, args)
    questions = [question("Gate", f"{args.gate} gate: how do you want to proceed?",
                          GATE_OPTIONS[args.gate])] + extra_questions
    if args.json:
        print(json.dumps({"result": "SUMMARY", "summary": lines,
                          "questions": questions}, indent=2))
    else:
        print("SUMMARY:")
        print("\n".join(f"  {ln}" for ln in lines))
        print("QUESTION:")
        print(json.dumps({"questions": questions}))
    return 0


def post_plan_summary(state, ad, args):
    rows, na_rows = art.manifest(ad / "acceptance" / "MANIFEST.md")
    per = {}
    for row in rows:
        per[row["#"].strip()] = per.get(row["#"].strip(), 0) + 1
    lines = [f"Task: {state['task'].get('text', '')}",
             f"Spec: {ad / 'SPEC.md'}", f"Plan: {ad / 'IMPLEMENTATION.md'}",
             "Acceptance checks per condition: "
             + ", ".join(f"{k}: {v}" for k, v in per.items()),
             "Not automatable: " + (", ".join(r.get("#", "") for r in na_rows) or "none")]
    return lines, []


def acceptance_block(ad):
    ev = art.spec_eval(ad / "SPEC_EVAL.md")
    verdicts, tiers = {}, {}
    named = []
    for row in ev["rows"]:
        verdict, tier = row["Verdict"].strip().lower(), row["Tier"].strip()
        verdicts[verdict] = verdicts.get(verdict, 0) + 1
        if verdict == "met":
            tiers[tier] = tiers.get(tier, 0) + 1
            if tier == "Adequate":
                named.append(f"{row['#']} Adequate: {row.get('Evidence', '')}")
        else:
            named.append(f"{row['#']} {verdict}: {row.get('Evidence', '')}")
    unjustified = [f for f in ev["integrity"]
                   if f.get("Judgment", "").strip().lower() == "unjustified"]
    if unjustified:
        raise Fail("SPEC_EVAL.md has an Unjustified integrity finding still open: Phase 5 "
                   "did not settle; do not ask the PR gate", FAILED, "PRECONDITION")
    justified = [f"{f.get('Location', '')} {f.get('Finding', '')} ({f.get('Reason', '')})"
                 for f in ev["integrity"]
                 if f.get("Judgment", "").strip().lower() == "justified"]
    tier_text = ", ".join(f"{v} {k}" for k, v in tiers.items())
    lines = [(f"Acceptance — {verdicts.get('met', 0)} met ({tier_text}) · "
              f"{verdicts.get('partial', 0)} partial · {verdicts.get('unmet', 0)} unmet · "
              f"{verdicts.get('manual', 0)} manual"),
             f"  {ev['mutation_line'] or 'Mutation: not recorded'}"]
    lines += [f"  {n}" for n in named]
    if justified:
        lines.append(f"  Test changes: {len(justified)} justified — " + "; ".join(justified))
    if ev["unresolved"] and not ev["unresolved"].lower().startswith("none"):
        lines.append("  Unresolved: " + " ".join(ev["unresolved"].split())[:600])
    return lines


def review_block(ad):
    lines, questions = [], []
    for name in ("CODE_REVIEW.md", "SECURITY_REVIEW.md"):
        text = art.read(ad / name)
        head = art.header_line(text, "**Overall confidence")
        counts = art.header_line(text, "Must-fix:")
        lines.append(f"{name.split('_')[0].title()} review — "
                     f"{head.replace('**', '').replace('Overall ', '')}")
        lines.append(f"  {counts}")
        if head and "Low" in head.split("—")[0]:
            lines.append("  WARNING: Low confidence is not a clean pass; say what failed")
    pre = for_the_user(art.read(ad / "SECURITY_REVIEW.md"))
    if pre:
        lines.append(f"  Pre-existing, for you: {len(pre)}")
        for row in pre:
            lines.append(f"    {row['ID']} ({row.get('Confidence', '')}) "
                         f"{row.get('Location', '')}, {row.get('Finding', '')}")
        shown = pre if len(pre) <= 3 else pre[:2]
        for row in shown:
            questions.append(question(row["ID"], f"Pre-existing security finding "
                                      f"{row['ID']}: {row.get('Finding', '')}", TRIAGE))
        if len(pre) > 3:
            rest = ", ".join(r["ID"] for r in pre[2:])
            questions.append(question("Others", f"The other pre-existing findings "
                                      f"({rest})", TRIAGE))
    return lines, questions


SEVERITY = {"high": 0, "medium": 1, "low": 2}


def for_the_user(sec):
    """SECURITY_REVIEW.md's pre-existing findings whose Verdict is `for the user`,
    most severe (by Confidence) first, in table order within a level."""
    body = art.find_section(sec, "Findings") or ""
    tables = [rows for header, rows in art.tables(body) if "Origin" in header]
    if not tables:
        return []  # no findings table: nothing was found
    _, rows = art.first_table(body, ("ID", "Origin", "Confidence", "Verdict"),
                              "SECURITY_REVIEW.md (Findings)")
    pre = [r for r in rows if r.get("Origin", "").strip().lower() == "pre-existing"
           and r.get("Verdict", "").strip().lower() == "for the user"]
    return sorted(pre, key=lambda r: SEVERITY.get(r.get("Confidence", "").strip().lower(),
                                                   len(SEVERITY)))


def fresh_or_fail(wt, ad, stale_message, *extra):
    """Run check-fresh.py: exit 1 is a STALE refusal, exit 2 could not run."""
    code, detail = check_fresh(wt, str(ad), *extra)
    if code != 0:
        raise Fail(f"{stale_message}\n{detail}", FAILED, "STALE")


def submodule_edits(wt):
    """`<submodule path>: <status line>` for each uncommitted edit in a submodule."""
    # No pipe: a `git status` failing inside a submodule fails the foreach.
    code, out, err = run(["git", "submodule", "foreach", "git status --porcelain"],
                         cwd=wt, check=False)
    if code != 0:
        raise Fail(f"git submodule foreach failed, so the submodules are unchecked: "
                   f"{(err or out).strip()}", CANNOT_RUN, "ERROR")
    edits, sub = [], "?"
    for line in out.splitlines():
        header = re.match(r"^Entering '(.*)'$", line)
        if header:
            sub = header.group(1)
        elif line.strip():
            edits.append(f"{sub}: {line}")
    return edits


def pr_summary(state, ad, args):
    wt = state["worktree"]
    fresh_or_fail(wt, ad, "results are stale; re-run them first, never ask this gate "
                  "on them:")
    missing = []
    for check in state["settings"].get("gate", []):
        report = ad / "lint" / check.get("report", "")
        first = report.read_text(encoding="utf-8").splitlines()[0] if report.exists() else ""
        if not first.rstrip().endswith("pass"):
            missing.append(check.get("report", ""))
    if missing:
        raise Fail(f"quality gate not green ({', '.join(missing)} missing or failing): "
                   "that is Phase 5's stop-and-report, not this gate", FAILED,
                   "PRECONDITION")
    subs = submodule_edits(wt)
    if subs:
        raise Fail("a submodule holds uncommitted edits, which this PR will not carry. "
                   "If any is source, stop and report: the pipeline never commits inside "
                   "a submodule. If all are generated output this run made, delete them "
                   "and run the gate summary again:\n" + "\n".join(subs), FAILED,
                   "PRECONDITION")
    status = git(wt, "status", "--porcelain", "--untracked-files=all", "--no-renames",
                 "--ignore-submodules=dirty")
    files = [ln[3:] for ln in status.splitlines() if not ln[3:].startswith(".auto-dev/")]
    lines = [f"Branch {state['branch']} → {state['repo']['base']}",
             f"Files changed: {len(files)}" + (f" ({', '.join(files[:8])}"
                                               f"{', …' if len(files) > 8 else ''})"
                                               if files else ""),
             "Quality gate: " + ", ".join(f"{c.get('report', '')} pass"
                                          for c in state["settings"].get("gate", []))]
    lines += acceptance_block(ad)
    review_lines, questions = review_block(ad)
    lines += review_lines
    if state["budget"]["remaining"] <= 0:
        lines.append("Budget exhausted: no round is left for a fix; an open must-fix "
                     "finding ships listed in the PR body")
    return lines, questions


def pr_number(state, args):
    pr = args.pr or state.get("phase6", {}).get("pr")
    if not pr:
        raise Fail("no PR number: pass --pr", CANNOT_RUN, "ERROR")
    return str(pr)


def ci_text(state):
    """The PR's CI result as a gate shows it: a result never watched to the end
    is never shown as if it might be green."""
    if state["settings"].get("ci") == "none":
        return "none"
    ci = state.get("phase6", {}).get("ci", {}).get("status", "not watched")
    if ci in ("unavailable", "timeout"):
        return f"not monitored ({ci}) — never assume green"
    return ci


def main_summary(state, ad, args):
    pr = pr_number(state, args)
    wt = state["worktree"]
    code, out, err = run(["gh", "pr", "view", pr, "--json",
                          ("url,isDraft,reviewDecision,reviews,comments,mergeable,"
                           "mergeStateStatus,headRefOid,state")], cwd=wt, check=False)
    if code != 0:
        raise Fail(f"gh pr view failed: {(err or out).strip()}", CANNOT_RUN, "ERROR")
    info = json.loads(out)
    if info.get("state") in ("MERGED", "CLOSED"):
        raise Fail(f"PR #{pr} is already {info['state']}: report it and stop", FAILED,
                   "PRECONDITION")
    if info.get("isDraft"):
        raise Fail(f"PR #{pr} is still a draft: mark it ready (`gh pr ready {pr}`) and "
                   "confirm its checks ran first", FAILED, "PRECONDITION")
    head = info.get("headRefOid", "")
    fresh_or_fail(wt, ad, f"the PR's head {head[:12]} holds code no result checked: "
                  "bring it in and re-run the stale results first.", "--ref", head)
    from .cmd_pr import MARKER  # the pipeline's own posts are not people's
    review_lines, _ = review_block(ad)
    comments = len([x for x in (info.get("comments") or []) + (info.get("reviews") or [])
                    if MARKER not in (x.get("body") or "")])
    lines = [f"PR {info.get('url', '#' + pr)}, CI: {ci_text(state)}",
             (f"Review decision: {info.get('reviewDecision') or 'none'}; "
              f"{comments} human review(s)/comment(s): triage them before asking"),
             f"Mergeable: {info.get('mergeable')} / {info.get('mergeStateStatus')}",
             f"Head {head}: every result was checked on it; the merge is locked to it",
             *review_lines]
    return lines, []
