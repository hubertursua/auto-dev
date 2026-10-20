"""autodev.py votes / review-scope / gate-summary.

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
    decided 2-1; Low: fewer than 2 reviewers; Medium otherwise), and adds each
    new must-fix finding's `Required change:` line to
    review/pass-<n>/corrections.md.
    Exit: 0 applied; 1 a re-voter's file is missing or malformed, or a new
    must-fix finding has no Required change line (re-spawn the judge).

review-scope --snapshot | --files | --clear | --next-pass
    --snapshot  marks untracked files intent-to-add, then records the working
                tree's hash as the snapshot to diff a correction against. Keeps
                an existing snapshot: one per pending correction, not per round.
    --files     prints the files changed since the snapshot (the scope of the
                cleanup re-spawn and the next panel pass).
    --clear     forgets the snapshot once a panel pass has reviewed it.
    --next-pass creates review/pass-<n>/ for the next pass and prints <n>.
    Exit: 0; 1 --files with no snapshot recorded.

gate-summary <post-plan|pr|staging|main> [--pr N]
    Checks the gate's preconditions, then prints the summary and the
    AskUserQuestion JSON to ask with (on the line after `QUESTION:`).
    pr: every report is fresh, one passing lint report per gate command, no
    submodule holds uncommitted edits, no Unjustified integrity finding is
    open; then the acceptance block and the two reviews, and one triage
    question per pre-existing security finding (at most three).
    Exit: 0 printed; 1 a precondition failed (the reason says what to do; do
    not ask the gate).

All exit 2 when they could not run — never a pass.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

from . import artifacts as art
from . import state as st
from .cmd_checks import git_add_intent
from .output import CANNOT_RUN, FAILED, Fail, emit
from .proc import git, run

SCRIPTS = Path(__file__).resolve().parent.parent
PASS_RE = re.compile(r"Latest pass:\s*(\d+)")
REVIEWERS_RE = re.compile(r"reviewers finished:\s*(\d)/3")
COVERAGE_RE = re.compile(r"coverage:\s*(full|partial)")
GATE_OPTIONS = {
    "post-plan": ["Approve & build", "Revise plan (tell me what to change)", "Stop"],
    "pr": ["Open PR", "Hold (don't push yet)", "Stop"],
    "staging": ["Merge to staging", "Skip staging", "Stop"],
    "main": ["Merge PR to main", "Hold", "Stop"],
}
TRIAGE = ["Separate PR (note it as a follow-up)", "Fix it in this PR", "Ignore it"]


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


def read_votes(pass_dir):
    """{finding id: [(slot, agree?)]} from every VOTES-R<k>.md."""
    found = {}
    for path in sorted(pass_dir.glob("VOTES-R*.md")):
        slot = path.stem.split("-")[-1]
        _, rows = art.first_table(art.read(path), ("Finding", "Vote"), str(path))
        for row in rows:
            vote = row["Vote"].strip().lower()
            if vote not in ("agree", "disagree"):
                raise art.ArtifactError(f"{path}: vote `{row['Vote']}` is not "
                                        "agree/disagree")
            found.setdefault(row["Finding"].strip(), []).append((slot, vote == "agree"))
    return found


def apply_votes(args, path, text, pass_dir, pending):
    if not pending:
        emit(args.json, "NONE", "no pending re-votes")
        return 0
    must, advisory = apply_vote_files(path, text, pass_dir, pending)
    emit(args.json, "APPLIED", f"{len(must)} must-fix, {advisory} advisory",
         must_fix=", ".join(must) or "none")
    return 0


def apply_vote_files(path, text, pass_dir, pending, votes_expected=True):
    """Move each pending finding by its votes; returns (new must-fix ids, advisory count).

    With votes_expected False (fewer than two usable reports, so nobody re-voted)
    every pending finding counts its raiser alone and stays advisory."""
    cast = read_votes(pass_dir) if votes_expected else {}
    missing = [r["ID"] for r in pending if r["ID"].strip() not in cast]
    if missing and votes_expected:
        raise art.ArtifactError(f"no re-vote recorded for {', '.join(missing)} in "
                                f"{pass_dir}: re-spawn those re-voters")
    must, advisory, decided_2_1 = [], [], []
    for row in pending:
        fid = row["ID"].strip()
        count = 1 + sum(1 for _, agree in cast.get(fid, []) if agree)
        cells = (fid, row.get("Finding", ""), row.get("Location", ""),
                 row.get("Category", ""))
        if count >= 2:
            must.append(f"| {' | '.join(cells)} | {count}/3 (re-vote) | Medium | open |")
            if count == 2:
                decided_2_1.append(fid)
        else:
            advisory.append(f"| {' | '.join(cells)} | {count}/3 (re-vote) | Low | "
                            f"lone finding; re-vote {count}/3 |")
    text = add_rows(text, "Must-fix", must)
    text = add_rows(text, "Advisory", advisory)
    text = clear_pending(text)
    text = recount(text, decided_2_1)
    tmp = path.with_name(".CODE_REVIEW.md.votes")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
    ids = [r.split("|")[1].strip() for r in must]
    add_corrections(text, pass_dir / "corrections.md", ids)
    return ids, len(advisory)


def add_corrections(text, path, ids):
    """Append each new must-fix finding's Required change to corrections.md."""
    if not ids:
        return
    entries = []
    for fid in ids:
        block = re.search(rf"^### {re.escape(fid)}\b.*?(?=^### |^## |\Z)", text,
                          re.MULTILINE | re.DOTALL)
        change = re.search(r"^Required change:\s*(.+)$", block.group(0),
                           re.MULTILINE) if block else None
        if not change:
            raise art.ArtifactError(f"CODE_REVIEW.md: {fid} has no `Required change:` "
                                    "line under its heading; re-spawn the judge")
        location = re.search(r"Trigger path:\s*(.+)$", block.group(0), re.MULTILINE)
        entries.append(f"{fid}: {change.group(1).strip()}"
                       + (f"\n   Now: {location.group(1).strip()}" if location else ""))
    existing = path.read_text(encoding="utf-8") if path.exists() else "# Required changes\n"
    existing = re.sub(r"^None\.\s*$", "", existing, flags=re.MULTILINE).rstrip() + "\n"
    count = len(re.findall(r"^\d+\. ", existing, re.MULTILINE))
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
    finished = int(reviewers.group(1)) if reviewers else 3
    full = (coverage.group(1) if coverage else "full") == "full"
    prior = re.search(r"must-fix decided 2–1:\s*([^>*\n]*)", head)
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
    if head:
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
               "staging": staging_summary, "main": main_summary}[args.gate]
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
    sec = art.read(ad / "SECURITY_REVIEW.md")
    pre = []
    body = art.find_section(sec, "Findings") or ""
    for header, rows in art.tables(body):
        if "Origin" in header:
            pre = [r for r in rows if r.get("Origin", "").strip() == "pre-existing"]
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


def pr_summary(state, ad, args):
    wt = state["worktree"]
    code, out, err = run([sys.executable, str(SCRIPTS / "check-fresh.py"), wt, str(ad)],
                         check=False)
    if code != 0:
        raise Fail(f"results are stale; re-run them first, never ask this gate on "
                   f"them:\n{(err or out).strip()}", FAILED, "PRECONDITION")
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
    subs = subprocess.run(["git", "submodule", "foreach", "--quiet",
                           "git status --porcelain | sed \"s|^|$sm_path: |\""],
                          cwd=wt, capture_output=True, text=True, check=False).stdout
    status = git(wt, "status", "--porcelain", "--untracked-files=all", "--no-renames",
                 "--ignore-submodules=dirty")
    files = [ln[3:] for ln in status.splitlines() if not ln[3:].startswith(".auto-dev/")]
    lines = [f"Branch {state['branch']} → {state['repo']['base']}",
             f"Files changed: {len(files)}" + (f" ({', '.join(files[:8])}"
                                               f"{', …' if len(files) > 8 else ''})"
                                               if files else ""),
             "Quality gate: " + ", ".join(f"{c.get('report', '')} pass"
                                          for c in state["settings"].get("gate", []))]
    if subs.strip():
        lines.append("Submodules with uncommitted edits (stop if any is source):")
        lines += [f"  {ln}" for ln in subs.strip().splitlines()]
    lines += acceptance_block(ad)
    review_lines, questions = review_block(ad)
    lines += review_lines
    if state["budget"]["remaining"] <= 0:
        lines.append("Budget exhausted: `Fix it in this PR` is not offered")
        for q in questions:
            q["options"] = [o for o in q["options"] if o["label"] != TRIAGE[1]]
    return lines, questions


def pr_number(state, args):
    pr = args.pr or state.get("phase6", {}).get("pr")
    if not pr:
        raise Fail("no PR number: pass --pr", CANNOT_RUN, "ERROR")
    return str(pr)


def staging_summary(state, ad, args):
    pr = pr_number(state, args)
    ci = state.get("phase6", {}).get("ci", {}).get("status", "not watched")
    return [f"PR #{pr}, CI: {ci}",
            (f"Direct merge (no PR) of {state['branch']} into "
             f"{state['repo'].get('staging') or 'n/a'}")], []


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
    code, out, err = run([sys.executable, str(SCRIPTS / "check-fresh.py"), wt, str(ad),
                          "--ref", head], check=False)
    if code != 0:
        raise Fail(f"the PR's head {head[:12]} holds code no result checked: bring it "
                   f"in and re-run the stale results first.\n{(err or out).strip()}",
                   FAILED, "PRECONDITION")
    ci = state.get("phase6", {}).get("ci", {}).get("status", "not watched")
    if state["settings"].get("ci") == "none":
        ci = "none"
    review_lines, _ = review_block(ad)
    comments = len(info.get("comments") or []) + len(info.get("reviews") or [])
    lines = [f"PR {info.get('url', '#' + pr)}, CI: {ci}",
             (f"Review decision: {info.get('reviewDecision') or 'none'}; "
              f"{comments} human review(s)/comment(s): triage them before asking"),
             f"Mergeable: {info.get('mergeable')} / {info.get('mergeStateStatus')}",
             f"Head {head}: every result was checked on it; the merge is locked to it",
             *review_lines]
    return lines, []
