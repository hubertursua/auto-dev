"""autodev.py votes / review-build, and the gate summaries `next` asks with.

Each takes `--dir <artifact-dir>` (default `./.auto-dev`) and `--json`.

votes --plan
    Reads CODE_REVIEW.md's `Pending re-vote` table and the latest pass's
    R<k>.md reports, and prints which re-voter to spawn for which findings: one
    per reviewer slot that wrote a usable report and did not raise the finding.
    Exit: 0 (`NONE` when there is nothing to re-vote).

votes --apply
    Reads review/pass-<n>/VOTES-R<k>.md and moves each pending finding in
    CODE_REVIEW.md: the reviewer who raised it plus every `agree` reaching 2 is
    must-fix, Medium; fewer is advisory, Low. Then recomputes the header counts
    and the overall confidence (High: 3/3 reviewers, full coverage, nothing
    decided 2-1; Low: fewer than 2 reviewers; Medium otherwise), and appends
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
    and `coverage:`); nothing is written.

review-build [--solo]
    The review judge runs it once it has written review/pass-<n>/JUDGMENT.md
    (templates/JUDGMENT.md) for the panel's pass <n>, from the merged
    findings `next` wrote to review/pass-<n>/findings.md (lib/judgment.py).
    It applies the rubric's fixed table: a judged finding that holds in a
    must-fix category is must-fix (High with 3 votes, Medium with 2) or, with
    one vote, pending a re-vote by the other reviewers who finished; one in an
    advisory category is advisory; one that doesn't hold is noise; a
    pre-existing one is counted only. It carries the earlier passes' rows,
    detail blocks, security leads and Passes rows forward (from the report
    as it stood before this pass, kept in review/pass-<n>/CODE_REVIEW.before.md,
    which `next` takes when it briefs the judge),
    marks each earlier must-fix finding fixed or open as JUDGMENT.md says,
    writes the Tree line (the panel's tree when the code is unchanged, else
    `changed during the run`), the counts and the overall confidence, then
    CODE_REVIEW.md and review/pass-<n>/corrections.md (an entry per open
    must-fix finding that is not acceptance-check).
    Prints `BUILT` with `next:` (REVOTE, MUST_FIX or CLEAN), `must_fix_open:`
    and `revote:`, the values for the judge's result.
    Exit: 0 built; 1 JUDGMENT.md can't be used (`MALFORMED`, a `problem:`
    line each; nothing is written); 2 no findings.md, judgment or judge brief,
    or CODE_REVIEW.md already holds this pass with no snapshot from before it.
    --solo: a standard-risk pass's one reviewer runs it on the JUDGMENT.md it
    wrote for its own findings (no findings.md, no `From:` lines, no security
    leads): each that holds in a must-fix category is must-fix (Medium, 1/1)
    and the overall confidence is Medium at best; the scope and tree come from
    the reviewer's brief, and nothing is ever pending a re-vote.

The gate summaries (post-plan, pr, ready, main)
    `next` builds one when it asks a gate: it checks the gate's
    preconditions, then shows the summary and asks the AskUserQuestion it
    prints.
    ready (the ready-for-review gate, on the draft PR once its reviews have
    settled): every report is fresh, one passing lint report per gate command
    (or skipped, for a test check the quality gate left to CI),
    no submodule holds uncommitted edits (`git submodule foreach` lists them),
    no Unjustified integrity finding is open; then the draft PR and its CI, the
    acceptance block and the two reviews, and one triage question per
    pre-existing security finding whose Verdict is `for the user`, most severe
    first (with more than three, the two most severe and one question for the
    rest, headed `Others`). Each answer is recorded with `mark triage-<ID or
    Others> --value separate|ignore`; a finding sent to a separate PR is listed
    in the PR body as a follow-up. When a review pass left findings open for
    want of a round (phase6.exhausted) and the PR is not marked ready, the
    gate offers a fourth answer, ADD_ROUND ("Add a round and fix it",
    gate_options), whose AFTER line is `budget raise --by 1`.
    pr (the open-the-PR gate, before the first push, only with `gates.open_pr`
    on): the same checks and summary, without the reviews, which have not run.
    main: the PR is open and not a draft, and every result was checked on its
    head commit.
    Each but post-plan also lists each deviation from the plan the coder
    recorded (deviations/coder-<n>.md), and each sign-off and fix made at a stop.
    A precondition that fails is a stop (`STALE` when a result no longer
    matches the code, which `next` re-checks, `PRECONDITION` otherwise);
    check-fresh.py, `git submodule foreach` or gh that could not run is exit 2.

All exit 2 when they could not run — never a pass.
"""

import json
import re
import sys
from pathlib import Path

from . import artifacts as art
from . import overrides
from . import state as st
from .cmd_ship import check_fresh
from .output import CANNOT_RUN, FAILED, Fail, emit
from .proc import git, run

SCRIPTS = Path(__file__).resolve().parent.parent
PASS_RE = re.compile(r"Latest pass:\s*(\d+)")
REVIEWERS_RE = re.compile(r"reviewers finished:\s*([0-3])/3")
COVERAGE_RE = re.compile(r"coverage:\s*(full|partial)")
GATE_OPTIONS = {
    "post-plan": ["Approve & build", "Revise plan (tell me what to change)", "Stop"],
    "pr": ["Open PR", "Hold (don't push yet)", "Stop"],
    "ready": ["Mark ready for review", "Hold (keep it a draft)", "Stop"],
    "main": ["Merge PR to main", "Hold", "Stop"],
}
# The ready gate's fourth answer, offered only when a review pass left findings
# open for want of a round (gate_options).
ADD_ROUND = "Add a round and fix it"


def gate_options(state, gate):
    """The answers `gate` offers in `state`: GATE_OPTIONS[gate], plus ADD_ROUND
    at the ready gate when no round was left to correct what is open and the PR
    is not marked ready yet."""
    options = list(GATE_OPTIONS[gate])
    if gate == "ready" and (state.get("phase6") or {}).get("exhausted") and \
            not (state.get("marks") or {}).get("pr-ready"):
        options.append(ADD_ROUND)
    return options

# A pre-existing security finding's triage answers, and the value `mark
# triage-<id>` records for each.
TRIAGE_VALUES = {"Separate PR (note it as a follow-up)": "separate", "Ignore it": "ignore"}
TRIAGE = list(TRIAGE_VALUES)


def add_arguments(parser, name):
    parser.add_argument("--dir", default=".auto-dev", help="the run's .auto-dev/")
    if name == "review-build":
        parser.add_argument("--solo", action="store_true",
                            help="the one reviewer's own judgment (a standard-risk pass)")
        parser.add_argument("--pass", dest="pass_n", type=int,
                            help="the pass (default: the run's current pass)")
    if name == "votes":
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument("--plan", action="store_true")
        mode.add_argument("--apply", action="store_true")


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


def vote_plan(pass_dir, pending):
    """{reviewer slot: [finding ids]}: who re-votes on what."""
    slots = [f"R{k}" for k in (1, 2, 3) if usable(pass_dir / f"R{k}.md")]
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
    text = recount(text, decided_2_1)
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


def recount(text, decided_2_1):
    open_, fixed = count_rows(text, "Must-fix", "open"), count_rows(text, "Must-fix", "fixed")
    advisory, noise = count_rows(text, "Advisory"), count_rows(text, "Noise")
    head = art.header_line(text, "**Overall confidence")
    reviewers = REVIEWERS_RE.search(head)
    coverage = COVERAGE_RE.search(head)
    if not reviewers or not coverage:
        raise art.ArtifactError("CODE_REVIEW.md: the `**Overall confidence` line does "
                                "not say `reviewers finished: <n>/3` and `coverage: "
                                "full|partial`; re-spawn the judge")
    finished = int(reviewers.group(1))
    full = coverage.group(1) == "full"
    prior = re.search(r"must-fix decided 2[–-]1:\s*([^>*\n]*)", head)
    earlier = [x.strip() for x in (prior.group(1) if prior else "").split(",")
               if x.strip() and x.strip() != "none"]
    two_one = earlier + [x for x in decided_2_1 if x not in earlier]
    if finished < 2:
        level = "Low"
    elif finished == 3 and full and not two_one:
        level = "High"
    else:
        level = "Medium"
    new_head = (f"**Overall confidence: {level}** — reviewers finished: {finished}/3; "
                f"coverage: {'full' if full else 'partial'}; must-fix decided 2–1: "
                f"{', '.join(two_one) or 'none'}")
    text = text.replace(head, new_head, 1)
    dropped = re.search(r"Dropped \(pre-existing\):\s*(\d+)", text)
    counts = (f"Must-fix: {open_} open · {fixed} fixed   ·   Advisory: {advisory}   ·   "
              f"Noise: {noise}   ·   Dropped (pre-existing): "
              f"{dropped.group(1) if dropped else 0}")
    return re.sub(r"^Must-fix: \d+ open.*$", counts, text, count=1, flags=re.MULTILINE)


def print_tree(wt):
    code, out, err = run([sys.executable, str(SCRIPTS / "check-fresh.py"),
                          "--print-tree", wt], check=False)
    if code != 0:
        raise Fail(f"check-fresh.py --print-tree failed: {err.strip()}", CANNOT_RUN, "ERROR")
    return out.strip()


# ---------------------------------------------------------------- the gate summaries

def question(header, text, options):
    return {"question": text, "header": header, "multiSelect": False,
            "options": [{"label": o, "description": ""} for o in options]}


def post_plan_summary(state, ad, args):
    """The plan, before any check is written: the tester writes them from the
    plan the user approves here."""
    conditions = art.spec_conditions(ad / "PLAN.md")
    lines = [f"Task: {state['task'].get('text', '')}",
             f"Plan: {ad / 'PLAN.md'}",
             f"Conditions ({len(conditions)}):",
             *(f"- {c['id']}. {c['text']}" for c in conditions),
             f"Risk: {'high' if state.get('high_risk') else 'standard'}"]
    blockers = state.get("plan_blockers")
    if blockers is not None:
        review = ad / "plan-review" / f"{blockers}.md"
        lines.append(f"The plan critic left these blockers open after the planner's one "
                     f"revision ({review}); decide whether to build anyway:")
        try:
            lines += [f"- {b['id']}. {b['text']} (evidence: {b['evidence']}; change: "
                      f"{b['change']})" for b in art.plan_review(review)["blockers"]]
        except art.ArtifactError as exc:
            lines.append(f"- the review can't be read: {exc}")
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
        raise Fail("SPEC_EVAL.md has an Unjustified integrity finding still open: the "
                   "review pass did not settle; do not ask the gate", FAILED,
                   "PRECONDITION")
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


def open_pr_summary(state, ad, args):
    """The opt-in gate before the first push: the checked build, no review yet."""
    lines, _ = pr_summary(state, ad, args, reviewed=False)
    return lines + [("Not verified or reviewed yet: the verifier and the review run on "
                     "the draft PR, alongside CI, once it is open")], []


def ready_summary(state, ad, args):
    """The ready-for-review gate: the reviews on the draft, its CI, and the PR."""
    lines, questions = pr_summary(state, ad, args)
    p6 = state.get("phase6", {})
    pr = p6.get("pr")
    lines.insert(0, f"Draft PR {p6.get('pr_url') or ('#' + str(pr))}, CI on the draft: "
                 f"{ci_text(state)}")
    if p6.get("exhausted"):
        open_ = "; ".join(str(x) for x in p6["exhausted"].get("open") or [] if x)
        lines.append("No round was left to correct what is still open"
                     + (f" ({open_})" if open_ else "") + ": marking the PR ready ships "
                     "it, listed in its description")
    recheck = state.get("risk_recheck") or {}
    if recheck.get("high"):
        lines.append("Risk: high after the build (" + "; ".join(recheck.get("why") or [])
                     + ")")
    return lines, questions


def pr_summary(state, ad, args, reviewed=True):
    wt = state["worktree"]
    fresh_or_fail(wt, ad, "results are stale; re-run them first, never ask this gate "
                  "on them:", *(() if reviewed else ("--phase", "5")))
    missing, gate_entries = [], []
    for check in state["settings"].get("gate", []):
        name = check.get("report", "")
        found = art.lint_report(ad / "lint" / name)
        if found["status"] not in ("pass", "skipped"):
            missing.append(name)
            gate_entries.append(f"{name} failing, signed off by the user")
        elif found["status"] == "skipped":
            gate_entries.append(f"{name} skipped (CI runs it)")
        elif found["scope"].startswith(art.SCOPED_PREFIX):
            gate_entries.append(f"{name} pass (the change's tests; CI runs the whole check)")
        else:
            gate_entries.append(f"{name} pass")
    if missing and not set(missing) <= overrides.signed_reports(state):
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
    # The branch's whole change: the tests commits, any build commit, and the
    # working tree on top (untracked files too).
    from .cmd_work import cut_commit
    cut = cut_commit(wt, state["repo"]["base"])
    names = git(wt, "diff", "--name-only", "--no-renames", cut).splitlines()
    names += git(wt, "ls-files", "--others", "--exclude-standard").splitlines()
    files = sorted({f for f in names if f and not f.startswith(".auto-dev/")})
    lines = [f"Branch {state['branch']} → {state['repo']['base']}",
             f"Files changed: {len(files)}" + (f" ({', '.join(files[:8])}"
                                               f"{', …' if len(files) > 8 else ''})"
                                               if files else ""),
             "Quality gate: " + ", ".join(gate_entries)]
    if reviewed:
        lines += acceptance_block(ad)
    questions = []
    if reviewed:
        review_lines, questions = review_block(ad)
        lines += review_lines
    if state["budget"]["remaining"] <= 0:
        lines.append("Budget exhausted: no round is left for a fix; an open must-fix "
                     "finding ships listed in the PR body")
    lines += deviation_lines(state, ad)
    lines += overrides.summary_lines(state)
    return lines, questions


def deviation_lines(state, ad):
    """Each deviation from the plan a coder recorded, by result, for the gate
    summaries: the coder built a step the way that works and said why."""
    out = []
    for e in state.get("log") or []:
        if e["worker"] != "coder" or e.get("status") != "ok" or e.get("aside"):
            continue
        path = Path(ad) / "deviations" / f"coder-{e['n']}.md"
        items = [ln.strip() for ln in _text(path).splitlines()
                 if re.match(r"\s*[-*]\s+\S", ln)]
        if items:
            out.append(f"Coder #{e['n']} deviated from the plan ({path}):")
            out += [f"  {item}" for item in items]
    return out


def _text(path):
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError:
        return ""


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
    if ci == "conflict":
        base = (state.get("repo") or {}).get("base") or "branch"
        return (f"not run — the PR conflicts with its base {base}, so GitHub ran no "
                "pull_request checks; bring the base in — never assume green")
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
             *review_lines, *deviation_lines(state, ad),
             *overrides.summary_lines(state)]
    return lines, []


# ---------------------------------------------------------------- review-build

# A solo reviewer's scope, as CODE_REVIEW.md says it (the judge's brief holds
# the same text, which `next` writes for a panel's pass).
SOLO_SCOPES = {
    "first": "the whole change, as committed on the branch: {files}",
    "after-commit": "the uncommitted correction (the working tree against HEAD)",
    "outside": ("the commits pushed to the PR branch outside the pipeline "
                "(`git diff {since}`): {files}"),
}

@wrap
def review_build(args):
    from . import judgment
    ad = Path(args.dir)
    state = st.load(ad)
    n = args.pass_n or (state.get("phase6") or {}).get("review_pass") or 1
    folder = ad / "review" / f"pass-{n}"
    solo = bool(getattr(args, "solo", False))
    brief = next((b for b in reversed(state.get("briefs") or [])
                  if (b.get("worker") == "reviewer" if solo else
                      b.get("worker") == "review-judge" and b.get("mode") == "consolidate")),
                 None)
    if brief is None:
        raise Fail("no reviewer brief in state.json" if solo else
                   "no review-judge consolidate brief in state.json", CANNOT_RUN, "ERROR")
    sets = brief.get("sets") or {}
    findings = "" if solo else art.read(folder / "findings.md")
    judgment_md = art.read(folder / "JUDGMENT.md")
    report = ad / "CODE_REVIEW.md"
    earlier = judgment.snapshot_before(ad, n)
    if earlier is None:
        raise Fail(f"CODE_REVIEW.md already holds pass {n} or later and no snapshot of it "
                   f"before pass {n} was taken ({folder / 'CODE_REVIEW.before.md'}), so "
                   "the earlier passes' rows can't be carried: tell the user",
                   CANNOT_RUN, "ERROR")
    panel_tree = str(sets.get("tree") or "").strip()
    tree = panel_tree if panel_tree and print_tree(state["worktree"]) == panel_tree \
        else "changed during the run"
    scope = sets.get("scope") or ""
    if solo:  # the reviewer's brief holds the scope's name: the report says what it is
        scope = SOLO_SCOPES.get(scope, scope).format(
            files=sets.get("files") or "none", since=sets.get("since") or "HEAD")
    try:
        text, result = judgment.build(
            branch=state.get("branch", ""), pass_n=n, scope=scope,
            tree=tree, findings_md=findings, judgment_md=judgment_md,
            earlier_md=earlier, solo=solo)
    except judgment.JudgmentError as exc:
        emit(args.json, "MALFORMED", f"{folder / 'JUDGMENT.md'} can't be used; fix it and "
             "run review-build again", problem=str(exc).splitlines())
        return FAILED
    coder = [i for i in result["open_ids"]
             if result["categories"].get(i, "").strip("`").lower() != "acceptance-check"]
    corrections = folder / "corrections.md"
    staged = folder / ".corrections.md.build"  # both written whole, or neither
    tmp = report.with_name(".CODE_REVIEW.md.build")
    try:
        staged.write_text("# Required changes\n" + ("" if coder else "None.\n"),
                          encoding="utf-8")
        add_corrections(text, staged, coder)
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(report)
        staged.replace(corrections)
    finally:
        staged.unlink(missing_ok=True)
        tmp.unlink(missing_ok=True)
    emit(args.json, "BUILT", f"{report} and {corrections}", next=result["next"],
         must_fix_open=result["must_fix_open"], revote=result["revote"])
    return 0
