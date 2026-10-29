"""autodev.py brief / record / check-artifact — briefing workers and checking what they return.

brief <worker> [--mode M] [--set name=value ...] [--retry N] [--dir <artifact-dir>]
brief profiler --out <dir> --set repo=<path> --set base=<branch> --set draft_path=<path>
brief lookup --out <dir> --set worktree=<repo> --set question="<question>"
    Writes briefs/<worker>-<n>.md: one `name: value` line for every slot the
    worker's agent file (agents/<worker>.md) uses in that mode. It fills what it
    can from state.json and the artifacts (paths, base, the task (the ticket's
    text, verbatim, when `init --ticket-text-file` stored it), the profile's
    test command and gate, the acceptance checks' files and test names, the
    last survivors, the next review pass, the result file) and takes the rest
    from --set. The review judge's `tree` is the tree the panel reviewed, so
    the caller passes it (`--set tree=<hash noted before the panel>`). `--retry N` marks the brief
    as a re-spawn of job <worker>-N, which `record` refused: its
    `previous_issues` slot carries the issues saved for that job (--set
    overrides), and job N is marked replaced, so `next` never re-spawns it
    too. Without --retry it is `none`. It refuses when a slot the worker needs has no value.
    A brief for a spec-proposal filer (the verifier, the review judge, the
    security reviewers, the triager), or for Define ruling on proposals, also
    copies SPEC.md to proposals/spec-<sha>.md and keeps the sha on the brief's
    state entry (a --retry keeps the first brief's): `record` compares SPEC.md
    with it. So does a planner brief in blocked mode, or in revise mode for a
    spec change or plan proposals (IMPLEMENTATION.md to
    proposals/snapshots/plan-<sha>.md), and an acceptance tester's repair brief
    (MANIFEST.md and the sealed copies to
    proposals/snapshots/acceptance-tester-<n>/).
    Prints the agent type to spawn and the one-line prompt to give it.
    With --out (the profiler always; a lookup before the run exists), the
    brief goes to <dir> with no state.json: a lookup's answer goes to
    <dir>/lookup-<n>-answer.md and its symbol lookup is `grep -n`, and nothing is
    recorded (`record` needs a run; read the answer from the worker's reply).
    Exit: 0 written; 1 refused (the missing slots are listed, or --retry names
    a job `record` did not refuse).

record <worker> <n>
    Reads returns/<worker>-<n>.json and checks it: `status` is ok, blocked or
    failed; `next`, when given, is one the worker may return; with status ok,
    every key of the worker's `auto-dev-result` block is present. Then, for an
    ok return, it re-derives the same decision from the artifacts the worker
    wrote: the verifier's `next` against `eval-status`, and its required
    changes (one entry at least for CORRECT and INSTALL_CONFLICT); the judge's
    `next`, must-fix and re-vote counts against CODE_REVIEW.md; the cleanup
    agent's GREEN against the lint reports; the triager's class and counts
    against its triage files (blockers in `triage_file`, held-out check
    comments in `checks_file`); the lookup's answer at lookups/<n>.md; for
    the acceptance tester, that each sealed copy of a file that exists only
    adds lines to it (before the build is installed, a sealed copy with no
    files/<path>.base gets one first: the file at HEAD, when it is there). A
    required-changes file that reaches the coder unedited (the verifier's, the
    judge's, the triager's) must not copy SPEC.md's wording (`spec-overlap`),
    nor may the planner's IMPLEMENTATION.md, the coder's other brief from a
    SPEC.md reader, nor the new text of the plan reviewer's FIX blocks, which
    `next` applies to IMPLEMENTATION.md. Every other file the return says the
    worker wrote must pass check-artifact: SPEC.md after Define, a reviewer's
    fix file, SPEC_EVAL.md,
    the lint reports, a code reviewer's report or votes, CODE_REVIEW.md and
    SECURITY_REVIEW.md. Each must exist, except a lint report, which only
    cleanup's GREEN requires (every report passing).
    Spec proposals (proposals/<worker>-<n>.md, counted by the result's
    `proposals` key, which a return may leave out): only the verifier, the
    review judge in consolidate mode, the security reviewers and the triager in
    human mode may file one; the count must match the file; each proposal needs
    a Target, a Why and the whole new text, names only conditions SPEC.md has,
    never an existing S row, never removes or renumbers a condition, adds at
    most one item, numbered next, changes something, and (from a PR comment)
    names the comment's id; the filer's correction file must not copy a
    proposal's new text; and a filer's SPEC.md items must read as they did when
    it was briefed (checked whatever its status). Define ruling on a batch must
    write a ruling for each proposal (stands with a reason), return REVISED
    when it applied any and STANDS when none, and leave SPEC.md changed exactly
    as the rulings say: an applied proposal's conditions changed, nothing else
    did, no condition gone or renumbered, no existing S row edited, and only
    the new items the applied proposals asked for. An acceptance tester in a
    spec redo must leave unchanged every sealed copy whose checks all belong to
    conditions outside its scope.
    Who may propose against what: SPEC.md, the filers above; the plan's build
    steps and the held-out checks, the coder (build and correction mode)
    alone. A spec filer's Target naming a step or a check is refused (a check
    is questioned only through its own route: the verifier's REPAIR, an
    `acceptance-check` finding, an ACCEPTANCE_CHECK comment). The coder's
    proposals (proposals/coder-<n>.md) each name steps the plan has (`step
    <n>`, `steps <n>, <m>`, changing them) or add one (`new step`, numbered
    after the last), never both, or name one check its brief listed that
    MANIFEST.md lists; never a condition or criterion. A coder returning
    BLOCKED writes blocked/coder-<n>.md; when it also proposes a plan change,
    the file lists each step it stopped as a line `- step <n>: <why>`, and a
    file with no such line, or a list line opening on a step in another form,
    is refused. The planner ruling on a
    batch (proposals/plan-<k>.md) writes a ruling for each (stands with a
    reason), returns REVISED or STANDS in revise mode, and leaves the build
    sequence changed exactly as the rulings say (spacing aside; in blocked
    mode the steps the coder stopped may change too); the tester ruling on a
    batch (proposals/checks-<k>.md) rules each condition repaired or stands,
    changes a sealed copy or MANIFEST.md rows only for a condition it
    repaired (another condition's row only to rename a check the two share),
    and must have changed each one it ruled repaired. Each answer is held to
    the copy taken when its batch was first briefed, a re-spawn after an
    answer that was not ok included; a planner or tester brief with no batch
    re-spawned after a not-ok answer keeps the copy of the brief it replaces,
    so the steps or conditions its log entry notes count from before the
    first attempt. Neither may write a stands reason into
    the plan or a sealed copy. The log entry notes the steps or conditions
    such an answer changed.
    On a match it updates state.json (for an ok return of the Define agent, the
    size check; after Define or its reviewer, a Security/Compliance criterion in
    SPEC.md turns a run that FITS high-risk with the post-plan gate on; a note
    of what came back, and the result in the log `autodev.py next` reads) and
    prints `RECORDED` with the `next` token.
    Exit: 0 recorded; 1 the return is missing or malformed (`MISSING`,
    `MALFORMED`) or disagrees with the artifacts (`MISMATCH`, both sides
    printed). Either way the issues are saved in state.json for job
    <worker>-<n>: run `autodev.py next`, which re-spawns it with a brief whose
    `previous_issues` carries them (as `brief <worker> --retry <n>` writes). A
    later RECORDED for <worker>-<n> clears them. Recording a job again keeps
    its place in the log. Don't guess.

check-artifact <file>
    Checks one artifact against its template before a worker returns it:
    SPEC.md, IMPLEMENTATION.md (also refused when it copies the run's SPEC.md,
    as `spec-overlap` checks, or its `Review effort:` line, when it has one, is
    not high or xhigh), acceptance/MANIFEST.md, SPEC_EVAL.md,
    CODE_REVIEW.md, SECURITY_REVIEW.md, review/pass-<n>/R<k>.md and
    VOTES-R<k>.md, lint/<CHECK>.md, a required-changes file (corrections.md,
    triage/*.md; also refused when it copies the run's SPEC.md, as
    `spec-overlap` checks), a FIX file (fixes/*.md), a spec proposal file
    (proposals/<worker>-<n>.md, held to the run's SPEC.md as `record` holds it),
    the coder's plan and check proposals (proposals/coder-<n>.md, held to the
    plan and MANIFEST.md), a batch of proposals or its rulings
    (proposals/batch-<k>.md, plan-<k>.md, checks-<k>.md and their
    -rulings.md), or a returns/*.json file.
    Exit: 0 it follows the template; 1 problems (each printed).

All exit 2 when they could not run — never a pass.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from . import artifacts as art
from . import briefs, check_props, cmd_checks, plan_props, proposals, sealed
from . import state as st
from .cmd_checks import FIX_RE, overlaps, rederive_risk
from .cmd_review import pending_rows
from .output import CANNOT_RUN, FAILED, Fail, emit

SCRIPTS = Path(__file__).resolve().parent.parent
SKILL_DIR = SCRIPTS.parent
BINDING_RULES = ("the repo's CLAUDE.md or AGENTS.md, CONTRIBUTING and coding-guideline "
                 "docs, and the security directives named in {artifact_dir}/profile.md; "
                 "they override finishing the task")
IMPLEMENTATION_HEADINGS = ("## Files", "## Design", "## Data flow", "## Build sequence",
                           "## Test plan", "## Migrations / config")
VERDICTS = {"met", "partial", "unmet", "manual"}
FIX_PREFIX = {"define-reviewer": "define", "plan-reviewer": "plan"}


def add_arguments(parser, name):
    parser.add_argument("--dir", default=".auto-dev", help="the run's .auto-dev/")
    if name == "brief":
        parser.add_argument("worker")
        parser.add_argument("--mode")
        parser.add_argument("--set", action="append", default=[], metavar="NAME=VALUE")
        parser.add_argument("--out", help="where to write a profiler brief, or a lookup "
                                          "brief before the run exists (no state.json)")
        parser.add_argument("--retry", type=int, metavar="N",
                            help="re-spawn job <worker>-N, which record refused")
    elif name == "record":
        parser.add_argument("worker")
        parser.add_argument("n", type=int)
    elif name == "check-artifact":
        parser.add_argument("file")


# ---------------------------------------------------------------- brief

def parse_sets(pairs):
    values = {}
    for pair in pairs:
        name, sep, value = pair.partition("=")
        if not sep or not name:
            raise Fail(f"--set {pair!r} is not name=value", CANNOT_RUN, "ERROR")
        values[name.strip()] = value
    return values


def next_number(directory, worker):
    taken = [int(m.group(1)) for p in directory.glob(f"{worker}-*.md")
             if (m := re.match(rf"{re.escape(worker)}-(\d+)\.md$", p.name))]
    return max(taken, default=0) + 1


def seal_bases(state, ad):
    """Give each sealed copy of a file that exists at HEAD its base (that file),
    before the build is installed; after it, refuse a new check in a file the
    repo had at the cut that holds none, and refresh the snapshot of each
    shared file whose checks are whole. Check every sealed copy with a base
    only adds lines to it. Returns the issues."""
    wt = state["worktree"]
    installed = cmd_checks.installed(ad)
    cut = None
    issues = []
    for rel in sealed.sealed_files(ad):
        base = sealed.base_path(ad, rel)
        if not base.exists() and not installed:
            r = subprocess.run(["git", "-C", wt, "show", f"HEAD:{rel}"],
                               capture_output=True, check=False)
            if r.returncode == 0:
                base.write_bytes(r.stdout)
        elif not base.exists():
            # After the build, a check with no base must be a new file: one the
            # repo had at the cut would swallow the coder's lines in it.
            cut = cut or cut_commit(wt, state["repo"]["base"])
            r = subprocess.run(["git", "-C", wt, "cat-file", "-e", f"{cut}:{rel}"],
                               capture_output=True, check=False)
            if r.returncode == 0:
                issues.append(f"files/{rel}.sealed adds checks to {rel}, which holds no "
                              "check yet; after the build, add a check only to a file "
                              "that holds one, or to a new file")
                continue
        try:
            why = sealed.adds_only(ad, rel)
            current = sealed.read(Path(wt) / rel)
            if not why and installed and base.exists() and \
                    sealed.intact(ad, rel, current):
                sealed.snapshot(ad, rel, current)  # the checks as repaired or folded
        except sealed.SealError as exc:
            raise Fail(f"cannot diff {rel}: {exc}", CANNOT_RUN, "ERROR") from None
        if why:
            issues.append(why)
    return issues


def acceptance_paths(ad):
    """Each file that holds acceptance checks, with the checks' test names: a
    file can hold the coder's own tests too."""
    try:
        rows, _ = art.manifest(ad / "acceptance" / "MANIFEST.md")
    except art.ArtifactError:
        return "none"
    names = {}
    for r in rows:
        cell = r["Check (path :: test name)"]
        path = art.check_path(cell)
        if path:
            name = cell.split("::", 1)[-1].strip().strip('"') if "::" in cell else ""
            names.setdefault(path, [])
            if name and name not in names[path]:
                names[path].append(name)
    return "; ".join(f"{p} (tests: " + ", ".join(f'"{n}"' for n in names[p]) + ")"
                     if names[p] else p for p in sorted(names)) or "none"


def survivors(ad):
    try:
        rows = art.spec_eval(ad / "SPEC_EVAL.md")["survivors"]
    except art.ArtifactError:
        return "none"
    keys = ("Mutant", "Location", "Change", "Condition", "Judgment")
    lines = ["| " + " | ".join(keys) + " |"] + [
        "| " + " | ".join(r.get(k, "") for k in keys) + " |" for r in rows]
    return "\n".join(lines) if rows else "none"


def symbol_lookup(ad):
    profile = ad / "profile.md"
    if profile.exists():
        for line in profile.read_text(encoding="utf-8").splitlines():
            if line.startswith("- **Symbol lookup:**"):
                return line.split(":**", 1)[1].strip()
    return "`grep -n`"


def print_tree(worktree):
    out = subprocess.run([sys.executable, str(SCRIPTS / "check-fresh.py"), "--print-tree",
                          worktree], capture_output=True, text=True, check=False)
    tree = out.stdout.strip()
    if out.returncode != 0 or not tree:
        raise Fail(f"check-fresh.py --print-tree exited {out.returncode}: "
                   f"{(out.stderr or out.stdout).strip()}", CANNOT_RUN, "ERROR")
    return tree


def cut_commit(worktree, base):
    """The commit the worktree was cut from, as a literal sha, so a worker's
    git commands need no `$(...)` and stay put when origin/<base> moves."""
    out = subprocess.run(["git", "-C", worktree, "merge-base", f"origin/{base}", "HEAD"],
                         capture_output=True, text=True, check=False)
    cut = out.stdout.strip()
    if out.returncode != 0 or not cut:
        raise Fail(f"git merge-base origin/{base} HEAD exited {out.returncode}: "
                   f"{(out.stderr or out.stdout).strip()}", CANNOT_RUN, "ERROR")
    return cut


def issues_text(issues):
    return "\n".join(f"- {i}" for i in issues)


def auto_values(worker, n, state, ad, mode):
    """Every AUTO slot's value for this run (some depend on the worker)."""
    s = state["settings"]
    test = next((c["command"] for c in s.get("gate", []) if c.get("kind") == "test"), "")
    gate = "\n".join(f"{i}. `{c['command']}` → {ad}/lint/{c.get('report', '')}"
                     for i, c in enumerate(s.get("gate", []), 1))
    phase6 = state.get("phase6", {})
    values = {
        "worktree": state["worktree"], "artifact_dir": str(ad), "skill_dir": str(SKILL_DIR),
        "base": state["repo"]["base"], "branch": state["branch"],
        "task": (state["task"].get("ticket_text") or state["task"].get("ask")
                 or state["task"].get("text", "")),
        "ticket": st.ticket_line(state["task"]).split(" — ")[0],
        "binding_rules": BINDING_RULES.format(artifact_dir=ad),
        "test_command": test or "none", "test_notes": s.get("test_notes") or "none",
        "mutation_cap": str(s.get("mutation_max", 20)) if s.get("mutation_max", 20) else "0 (off)",
        "gate_commands": gate or "none",
        "result_file": str(ad / "returns" / f"{worker}-{n}.json"),
        "pr": str(phase6.get("pr") or "none"),
        "pass": str(phase6.get("review_pass") or 1),
        "run": str(phase6.get("security_run", 0) + 1),
        "triage_file": str(ad / "triage" / f"{mode or 'triage'}-{n}.md"),
        "checks_file": str(ad / "triage" / f"{mode or 'triage'}-{n}-checks.md"),
        "answer_file": str(ad / "lookups" / f"{n}.md"),
        "blocked_file": str(ad / "blocked" / f"coder-{n}.md"),
        "fix_file": str(ad / "fixes" / f"{FIX_PREFIX.get(worker, 'plan')}-{n}.md"),
        "proposal_file": str(ad / "proposals" / f"{worker}-{n}.md"),
    }
    return values


def job(worker, n):
    return f"{worker}-{n}"


BLOCKED_ONCE = ("Your last spawn for this job returned `blocked`, and the run spawned "
                "you again once. If a tool call was refused because of how it was "
                "written, write it out in full (literal paths, `git -C <path>`, no shell "
                "variable or `$(…)`) and go on. If a person denied the call, don't ask "
                "again: return `blocked` at once. Otherwise return `blocked` again only "
                "for a reason a new attempt can't fix, and say what it is.")


def blocked_last(state, worker, mode=None):
    """Whether the newest result since the last resume is this worker's (in
    `mode`), blocked. Never for the code reviewers, who run in parallel: the
    newest result may be another slot's. Their results are skipped for the
    others too, so the security reviewer spawned beside them is told, and so
    are the same worker's results in another mode (the judge's two modes run
    in parallel)."""
    if worker == "code-reviewer":
        return False
    log = [e for e in state.get("log") or []
           if e.get("seq", 0) > state.get("resumed_seq", 0)
           and e.get("worker") != "code-reviewer"
           and not (e.get("worker") == worker and e.get("mode") != mode)]
    return bool(log) and log[-1].get("worker") == worker and \
        log[-1].get("status") == "blocked"


def saved_issues(state, worker, retry):
    """The issues record saved for job <worker>-<retry>; None without --retry."""
    if retry is None:
        return None
    issues = state.get("refused", {}).get(job(worker, retry))
    if not issues:
        raise Fail(f"--retry {retry}: record refused no return for {job(worker, retry)}",
                   FAILED, "REFUSED")
    return issues_text(issues)


LAZY = {"acceptance_paths": acceptance_paths, "survivors": survivors,
        "symbol_lookup": symbol_lookup}


def brief(args):
    worker = args.worker
    given = parse_sets(args.set)
    if worker == "profiler" or (worker == "lookup" and args.out):
        if not args.out:
            raise Fail("a profiler brief needs --out <dir> (there is no run yet)",
                       CANNOT_RUN, "ERROR")
        if args.retry is not None:
            raise Fail(f"a {worker} brief with --out takes no --retry", CANNOT_RUN,
                       "ERROR")
        path, values = write_brief(None, Path(args.out).resolve(), worker, args.mode, given)
    else:
        try:
            state = st.load(args.dir)
        except st.StateError as exc:
            raise Fail(str(exc), CANNOT_RUN, "ERROR") from None
        path, values = write_brief(state, Path(state["artifact_dir"]), worker,
                                   args.mode, given, args.retry)
        st.save(args.dir, state)
    n = int(path.stem.rsplit("-", 1)[1])
    emit(args.json, "BRIEF", str(path), agent=f"auto-dev:{worker}", n=n,
         prompt=prompt_for(path), result_file=values.get("result_file", ""))
    return 0


def prompt_for(path):
    return f"Your brief is at {path}. Read it first."


def write_brief(state, where, worker, mode, given, retry=None):
    """Write briefs/<worker>-<n>.md and log it in `state` (the caller saves).

    `where` is the artifact dir, or with no run (state None: the profiler, a
    lookup before init) the folder to write into. `retry` re-spawns job
    <worker>-<retry>, which record refused: its saved issues fill
    previous_issues. Returns (path, the slot values)."""
    if worker not in briefs.RESULTS:
        raise Fail(f"unknown worker {worker!r}; one of {', '.join(sorted(briefs.RESULTS))}",
                   CANNOT_RUN, "ERROR")
    worker_modes = briefs.modes(worker)
    if worker_modes and mode not in worker_modes:
        raise Fail(f"{worker} needs --mode, one of {', '.join(worker_modes)}",
                   FAILED, "REFUSED")
    if not worker_modes and mode:
        raise Fail(f"{worker} has no modes", FAILED, "REFUSED")
    if state is None:
        ad, directory, previous = None, where, None
        n = next_number(directory, worker)
        auto = {"skill_dir": str(SKILL_DIR),
                "result_file": str(where / f"{worker}-{n}.json"),
                "answer_file": str(where / f"{worker}-{n}-answer.md"),
                "symbol_lookup": "`grep -n`"}
    else:
        ad = where
        # Workers spill long output here: a path they can write out in full,
        # where TMPDIR would be a shell variable a permission check refuses.
        (ad / "tmp").mkdir(parents=True, exist_ok=True)
        directory = ad / "briefs"
        n = next_number(directory, worker)
        auto = auto_values(worker, n, state, ad, mode)
        previous = saved_issues(state, worker, retry)
        if previous is None and blocked_last(state, worker, mode):
            previous = BLOCKED_ONCE
    needed = briefs.slots(worker, mode)
    values, missing = {}, []
    for slot in sorted(needed):
        kind = briefs.kind(worker, slot)
        if slot in given:
            values[slot] = given[slot]
        elif kind == "auto" and slot in auto:
            values[slot] = auto[slot]
        elif kind == "auto" and slot == "tree" and ad is not None:
            values[slot] = print_tree(auto["worktree"])
        elif kind == "auto" and slot == "cut" and ad is not None:
            values[slot] = cut_commit(auto["worktree"], auto["base"])
        elif kind == "auto" and slot in LAZY and ad is not None:
            values[slot] = LAZY[slot](ad)
        elif slot == "previous_issues" and previous:
            values[slot] = previous
        elif kind == "optional":
            values[slot] = "none"
        else:
            missing.append(slot)
    unknown = sorted(set(given) - needed)
    if missing:
        raise Fail(f"{worker} needs " + ", ".join(f"--set {m}=..." for m in missing),
                   FAILED, "REFUSED")
    if unknown:
        raise Fail(f"{worker} ({mode or 'no mode'}) uses no slot named "
                   f"{', '.join(unknown)}", FAILED, "REFUSED")
    directory.mkdir(parents=True, exist_ok=True)
    if ad is not None:
        for sub in ("returns", "fixes", "triage", "lookups", "blocked", "proposals"):
            (ad / sub).mkdir(exist_ok=True)
    path = directory / f"{worker}-{n}.md"
    path.write_text(briefs.render(worker, n, mode, values), encoding="utf-8")
    if state is not None:
        entry = {"worker": worker, "n": n, "mode": mode, "sets": given, "at": st.now(),
                 "retry": retry, "seq": st.seq(state)}
        watch_spec(state, ad, worker, given, retry, entry)
        if retry is None:
            watch_owner(state, ad, worker, mode, given, entry, n)
        state.setdefault("briefs", []).append(entry)
        for old in state["briefs"]:
            if retry is not None and old["worker"] == worker and old["n"] == retry:
                old["retried_as"] = n  # replaced: `next` never re-issues it
    return path, values


def watch_spec(state, ad, worker, given, retry, entry):
    """A filer, or Define ruling on proposals, is held to SPEC.md as it was
    when it was briefed: copy SPEC.md (proposals/spec-<sha>.md) and keep the
    sha on its brief entry. A retry keeps the first brief's copy (and the
    sealed files a redo tester was held to), so the base never moves."""
    if retry is not None:
        old = next((b for b in state.get("briefs", [])
                    if b["worker"] == worker and b["n"] == retry), {})
        for key in ("spec", "held", "plan", "sealed"):
            if key in old:
                entry[key] = old[key]
        return
    ruling = worker == "define" and str(given.get("proposals") or "none").strip().lower() \
        not in ("", "none")
    if worker in proposals.FILERS or ruling:
        sha = proposals.snapshot(ad)
        if sha:
            entry["spec"] = sha


def is_set(value):
    return str(value or "none").strip().lower() not in ("", "none")


def watch_owner(state, ad, worker, mode, given, entry, n):
    """The planner revising the plan (blocked mode, or revise mode for a spec
    change or plan proposals) and the tester repairing checks are held to
    what they were briefed on: copy IMPLEMENTATION.md
    (proposals/snapshots/plan-<sha>.md) or MANIFEST.md and the sealed copies
    (proposals/snapshots/acceptance-tester-<n>/), and keep the key on the
    brief's entry. `record` diffs against it; a retry keeps the first brief's
    (watch_spec), and so does a new brief on the same batch of proposals (a
    re-spawn after an answer that was not ok), so an edit the first attempt
    left behind is never taken for the base. A brief with no batch does the
    same through replaced(): the brief a re-spawn after a not-ok answer
    replaces lends it its copy."""
    key = {"planner": "plan", "acceptance-tester": "sealed"}.get(worker)
    batch = proposals._batch_path(given) if is_set(given.get("proposals")) else None
    first = next((b for b in state.get("briefs", []) if batch and b["worker"] == worker
                  and key in b and is_set(b.get("sets", {}).get("proposals"))
                  and proposals._batch_path(b["sets"]) == batch), None)
    if first is None and key and batch is None:
        first = replaced(state, worker, mode, given, key)
    if first is not None:
        entry[key] = first[key]
    elif worker == "planner" and (mode == "blocked" or (mode == "revise" and (
            is_set(given.get("spec_change")) or is_set(given.get("proposals"))))):
        sha = plan_props.snapshot(ad)
        if sha:
            entry["plan"] = sha
    elif worker == "acceptance-tester" and mode == "repair":
        entry["sealed"] = check_props.snapshot(ad, f"{worker}-{n}")


def replaced(state, worker, mode, given, key):
    """The brief a new one with no batch replaces, or None: the latest earlier
    brief for the same worker and mode, also with no batch, briefed on the same
    `blocked` (the planner) or `scope` (the tester), that holds a copy
    (`key`), whose job returned a status other than ok, with no ok result from
    that worker since. Its copy is the base from before the first attempt."""
    same = "blocked" if worker == "planner" else "scope"
    want = str(given.get(same) or "").strip()
    last = next((b for b in reversed(state.get("briefs", []))
                 if b["worker"] == worker and b.get("mode") == mode
                 and not is_set(b.get("sets", {}).get("proposals"))
                 and str(b.get("sets", {}).get(same) or "").strip() == want), None)
    if last is None or key not in last:
        return None
    log = [e for e in state.get("log") or [] if e.get("worker") == worker]
    done = next((e for e in log if e.get("n") == last["n"]), None)
    if done is None or done.get("status") == "ok":
        return None
    if any(e.get("status") == "ok" and e.get("seq", 0) > done.get("seq", 0) for e in log):
        return None
    return last


# ---------------------------------------------------------------- record

class Refused(Exception):
    """The return can't be recorded: (token, message, issues)."""


def load_return(ad, worker, n):
    path = ad / "returns" / f"{worker}-{n}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise Refused("MISSING", f"no {path}: the worker wrote no result file",
                      [f"you wrote no result file at {path}"]) from None
    except ValueError as exc:
        raise Refused("MALFORMED", f"{path} is not JSON",
                      [f"{path} is not JSON: {exc}"]) from None
    problems = return_problems(worker, data)
    if problems:
        raise Refused("MALFORMED", f"{path} is malformed", problems)
    return data


def return_problems(worker, data):
    problems = []
    if not isinstance(data, dict):
        return ["not a JSON object"]
    if not isinstance(worker, str):
        return [f"worker is {worker!r}, not a worker's name"]
    if data.get("worker") != worker:
        problems.append(f"worker is {data.get('worker')!r}, expected {worker!r}")
    if data.get("status") not in briefs.STATUSES:
        problems.append(f"status {data.get('status')!r} is not ok/blocked/failed")
    allowed = briefs.RESULTS.get(worker, set())
    nxt = data.get("next")
    if data.get("status") == "ok" or nxt not in (None, "", "none"):
        if nxt not in allowed:
            problems.append(f"next {nxt!r} is not one of {', '.join(sorted(allowed))}")
    if data.get("status") == "ok" and worker in briefs.RESULTS:
        missing = [k for k in briefs.result_keys(worker)
                   if k not in data and k not in briefs.LENIENT_KEYS]
        if missing:
            problems.append("no " + ", ".join(f"`{k}`" for k in missing) +
                            " (every key of the result block is required)")
    return problems


def as_int(data, key):
    value = str(data.get(key, "")).strip()
    if value.lower() in ("", "none"):
        return 0
    try:
        return int(value)
    except ValueError:
        raise Refused("MALFORMED", "a count is not a number",
                      [f"`{key}` is {data.get(key)!r}, not a number (write 0 for none)"]) from None


def is_yes(value):
    return str(value).strip().lower() in ("yes", "true")


def run_autodev(*args):
    out = subprocess.run([sys.executable, str(SCRIPTS / "autodev.py"), *args],
                         capture_output=True, text=True, check=False)
    return out.returncode, out.stdout, out.stderr


def entries(path):
    text = Path(path).read_text(encoding="utf-8") if Path(path).exists() else ""
    return len(re.findall(r"^\d+\.\s", text, re.MULTILINE))


def derive(worker, data, ad, state, n):
    """Return a list of disagreements between the return and the artifacts."""
    issued = next((b for b in state.get("briefs", [])
                   if b["worker"] == worker and b["n"] == n), {})
    issues = []
    if worker in proposals.FILERS and issued.get("spec"):
        # Whatever the status: a filer that edited SPEC.md never gets past it.
        issues += proposals.spec_edit_issues(ad, issued["spec"])
    if data.get("status") != "ok":
        return issues
    issues += result_issues(worker, data, ad, state, n) + artifact_issues(
        worker, data, ad, state, n)
    as_int(data, "proposals")  # a count that is not a number is MALFORMED
    shown = check_props.shown_paths(ad, worker, n) if worker == "coder" else None
    issues += proposals.filer_issues(worker, issued.get("mode"), data, ad, n,
                                     handed_correction(worker, issued, data, ad, state),
                                     shown=shown)
    sets = issued.get("sets", {})
    if worker == "define" and is_set(sets.get("proposals")):
        issues += proposals.answer_issues(ad, sets, issued.get("spec"), data.get("next"))
    if worker == "planner" and is_set(sets.get("proposals")):
        issues += plan_props.answer_issues(ad, sets, issued, data.get("next"))
    if worker == "acceptance-tester" and is_set(sets.get("proposals")):
        issues += check_props.answer_issues(ad, sets, issued, data.get("next"))
    if worker == "acceptance-tester" and issued.get("held"):
        issues += proposals.held_issues(ad, issued["held"])
    return issues


def handed_correction(worker, issued, data, ad, state):
    """The required-changes file a filer's result hands the coder, which must
    not copy its proposals' new text either; None when it hands none."""
    nxt = data.get("next")
    if worker == "verifier" and nxt in ("CORRECT", "INSTALL_CONFLICT"):
        return ad / "evidence" / "corrections.md"
    if worker == "review-judge" and issued.get("mode") == "consolidate" and \
            nxt in ("MUST_FIX", "REVOTE"):
        n = state.get("phase6", {}).get("review_pass") or 1
        path = ad / "review" / f"pass-{n}" / "corrections.md"
        return path if path.exists() else None
    if worker == "triager" and issued.get("mode") == "human" and \
            as_int(data, "blockers") > 0:
        given = str(data.get("triage_file") or "").strip()
        return Path(given) if given not in ("", "none") else None
    return None


def written_files(worker, data, ad, state, n):
    """[(path, required)]: the files this result says the worker wrote that no
    other check reads (required-changes files are checked by coder_bound)."""
    nxt = data.get("next")
    issued = next((b for b in state.get("briefs", [])
                   if b["worker"] == worker and b["n"] == n), {})
    mode, sets = issued.get("mode"), issued.get("sets", {})
    review = ad / "review" / f"pass-{state.get('phase6', {}).get('review_pass') or 1}"
    files = []
    if worker == "define":  # it has no shell to run check-artifact itself
        files.append((ad / "SPEC.md", True))
    elif worker in ("define-reviewer", "plan-reviewer"):
        fix = str(data.get("fix_file", "none")).strip()
        if fix not in ("none", ""):
            files.append((Path(fix), False))  # result_issues reports a missing one
    elif worker == "verifier" and nxt not in ("INSTALL_CONFLICT", "MUTATION_LEFT_CHANGES"):
        files.append((ad / "SPEC_EVAL.md", True))
    elif worker == "cleanup":
        files += [(ad / "lint" / c["report"], False)
                  for c in state["settings"].get("gate", []) if c.get("report")]
    elif worker == "code-reviewer" and sets.get("reviewer"):
        name = "VOTES-" if mode == "re-vote" else ""
        files.append((review / f"{name}{sets['reviewer']}.md", True))
    elif worker == "review-judge":
        files.append((ad / ("SECURITY_REVIEW.md" if nxt == "VERIFIED" else "CODE_REVIEW.md"),
                      True))
    elif worker in ("security-reviewer", "security-reviewer-sensitive"):
        files.append((ad / "SECURITY_REVIEW.md", True))
    return files


def artifact_issues(worker, data, ad, state, n):
    """Each file the worker wrote must follow its template; the plan reviewer's
    FIX text, which goes into the plan the coder is briefed with, must not copy
    SPEC.md's wording (the planner's own plan is checked by check_file)."""
    issues = []
    for path, required in written_files(worker, data, ad, state, n):
        if not path.exists():
            if required:
                issues.append(f"{path} does not exist")
            continue
        issues += [f"{path.name}: {p}" for p in check_file(path)]
    fix = str(data.get("fix_file", "none")).strip()
    if worker == "plan-reviewer" and fix not in ("none", "") and Path(fix).exists():
        # `next` applies these blocks to IMPLEMENTATION.md with no planner in
        # between, so their new text is held to the plan's rule. Old text was
        # copied from the plan, which already passed.
        try:
            new = "\n".join(b[2] for b in FIX_RE.findall(art.read(Path(fix))))
            issues += [f"{Path(fix).name}'s new text copies SPEC.md's wording ({hit}): "
                       "the coder never sees SPEC.md, so say what the code must do in "
                       "the plan's own words"
                       for hit in overlaps(Path(fix), ad / "SPEC.md", text=new)]
        except art.ArtifactError as exc:
            issues.append(f"{Path(fix).name}: {exc}")
    return issues


def result_issues(worker, data, ad, state, n):
    nxt = data.get("next")
    issues = []
    if worker == "define":
        if nxt in ("FITS", "OVERSIZED"):
            conds = art.spec_conditions(ad / "SPEC.md")
            has_security = any(c["id"].startswith("S") for c in conds)
            if has_security and not is_yes(data.get("high_risk")):
                issues.append("SPEC.md has Security/Compliance criteria but high_risk is not yes")
    elif worker in ("define-reviewer", "plan-reviewer"):
        blockers = as_int(data, "blockers")
        if (nxt == "CLEAN") != (blockers == 0):
            issues.append(f"next is {nxt} but blockers is {blockers}")
        fix = str(data.get("fix_file", "none")).strip()
        if fix not in ("none", "") and not Path(fix).exists():
            issues.append(f"fix_file {fix} does not exist")
    elif worker == "planner" and nxt in ("WRITTEN", "REVISED", "STANDS", "PLAN_REVISED",
                                         "UPDATE_OLD_TEST"):
        issues += [f"IMPLEMENTATION.md: {p}" for p in check_file(ad / "IMPLEMENTATION.md")]
    elif worker == "acceptance-tester" and nxt in ("SEALED", "REPAIRED", "FOLDED"):
        # Gaps are not a disagreement: `next` re-spawns the tester for them.
        art.manifest(ad / "acceptance" / "MANIFEST.md")
        issues += seal_bases(state, ad)
    elif worker == "coder":
        if (nxt == "BLOCKED") != (as_int(data, "blocked") > 0):
            issues.append(f"next is {nxt} but blocked is {data.get('blocked')}")
        listed = ad / "blocked" / f"coder-{n}.md"
        if nxt == "BLOCKED" and not listed.exists():
            issues.append(f"next is BLOCKED but {listed} does not exist")
        elif nxt == "BLOCKED" and plan_props.files_plan_proposal(ad, n):
            # Only the planner's combined answer reads the stopped steps out of
            # the file; with no plan proposal it is read as prose, as before.
            issues += plan_props.blocked_file_issues(listed)
    elif worker == "verifier":
        issues += derive_verifier(nxt, ad)
    elif worker == "cleanup":
        failing = [c.get("report", "") for c in state["settings"].get("gate", [])
                   if not lint_passes(ad / "lint" / c.get("report", ""))]
        if (nxt == "GREEN") != (not failing):
            issues.append(f"next is {nxt} but these lint reports don't pass: "
                          f"{', '.join(failing) or 'none'}")
    elif worker == "review-judge":
        issues += derive_judge(data, ad, state)
    elif worker == "triager":
        issues += derive_triager(data, ad, n)
    elif worker == "lookup" and nxt == "ANSWERED":
        answer = ad / "lookups" / f"{n}.md"
        if not answer.is_file() or not answer.read_text(encoding="utf-8").strip():
            issues.append(f"next is ANSWERED but {answer} holds no answer")
    return issues


def coder_bound(path, ad, what):
    """Problems with a required-changes file the coder gets unedited."""
    if not path.exists():
        return [f"{what}: {path} does not exist"]
    problems = [f"{what}: {p}" for p in check_corrections(art.read(path))]
    problems += [f"{what} copies SPEC.md's wording ({hit}): say what the code must do "
                 "and where, in your own words"
                 for hit in overlaps(path, ad / "SPEC.md", quoted=False)]
    return problems


def derive_verifier(nxt, ad):
    issues = []
    corrections = ad / "evidence" / "corrections.md"
    if nxt == "INSTALL_CONFLICT":
        if entries(corrections) == 0:
            issues.append("next is INSTALL_CONFLICT but evidence/corrections.md has no "
                          "entry naming a conflicting path")
        return issues
    if nxt == "MUTATION_LEFT_CHANGES":
        return issues
    code, out, err = run_autodev("eval-status", "--dir", str(ad))
    decision = out.split(":", 1)[0].strip() if code == 0 else f"error: {err.strip()}"
    if decision != nxt:
        issues.append(f"next is {nxt} but eval-status says {decision}")
    if nxt == "CORRECT":
        if entries(corrections) == 0:
            issues.append("next is CORRECT but evidence/corrections.md has no entries")
        else:
            issues += coder_bound(corrections, ad, "evidence/corrections.md")
    return issues


def derive_judge(data, ad, state):
    nxt = data.get("next")
    issues = []
    if nxt == "VERIFIED":
        return coder_bound(ad / "review" / "security-corrections.md", ad,
                           "review/security-corrections.md")
    text = art.read(ad / "CODE_REVIEW.md")
    open_rows, pending = count_open(text), len(pending_rows(text))
    if as_int(data, "must_fix_open") != open_rows:
        issues.append(f"must_fix_open is {data.get('must_fix_open')} but CODE_REVIEW.md "
                      f"has {open_rows} open must-fix rows")
    if as_int(data, "revote") != pending:
        issues.append(f"revote is {data.get('revote')} but CODE_REVIEW.md has {pending} "
                      "rows pending a re-vote")
    # The judge's rule: REVOTE while any re-vote is pending, else MUST_FIX while
    # any must-fix row is open, else CLEAN.
    want = "REVOTE" if pending else "MUST_FIX" if open_rows else "CLEAN"
    if nxt != want:
        issues.append(f"next is {nxt} but CODE_REVIEW.md has {open_rows} open must-fix "
                      f"and {pending} pending re-vote rows, which is {want}")
    if nxt == "MUST_FIX":
        n = state.get("phase6", {}).get("review_pass") or 1
        issues += coder_bound(ad / "review" / f"pass-{n}" / "corrections.md", ad,
                              f"review/pass-{n}/corrections.md")
    return issues


def derive_triager(data, ad, n):
    nxt = data.get("next")
    triage = ad / "triage"
    issues = []
    expected = {str(triage / f"{m}-{n}.md") for m in ("ci", "human")}
    triage_file = str(data.get("triage_file", "")).strip()
    checks_file = str(data.get("checks_file", "none")).strip()
    if nxt == "CODE" or (nxt == "TRIAGED" and as_int(data, "blockers") > 0):
        if not any(same_path(triage_file, e) for e in expected):
            issues.append(f"triage_file is {triage_file!r}, not this triage's file "
                          f"({' or '.join(sorted(expected))})")
        elif entries(triage_file) == 0:
            issues.append(f"next is {nxt} but {triage_file} holds no required change")
        else:
            issues += coder_bound(Path(triage_file), ad, triage_file)
    if nxt == "TRIAGED" and as_int(data, "acceptance_checks") > 0:
        want = str(triage / f"human-{n}-checks.md")
        if not same_path(checks_file, want):
            issues.append(f"checks_file is {checks_file!r}, not {want}")
        elif entries(checks_file) == 0:
            issues.append(f"acceptance_checks is {data.get('acceptance_checks')} but "
                          f"{checks_file} holds no entry")
    return issues


def same_path(given, want):
    """Whether an absolute path a worker returned names `want`, through any
    symlink (on macOS the temp dir's /var is /private/var). A relative path never
    does: the coder it is handed to may run in another directory."""
    return os.path.isabs(given) and os.path.realpath(given) == os.path.realpath(want)


def lint_passes(path):
    if not path.exists():
        return False
    first = path.read_text(encoding="utf-8").splitlines()[:1]
    return bool(first) and first[0].rstrip().endswith("pass")


def count_open(text):
    body = art.find_section(text, "Must-fix") or ""
    for header, rows in art.tables(body):
        if "Status" in header:
            return sum(1 for r in rows if r.get("Status", "").strip().startswith("open"))
    return 0


def record(args):
    try:
        state = st.load(args.dir)
    except st.StateError as exc:
        raise Fail(str(exc), CANNOT_RUN, "ERROR") from None
    ad = Path(state["artifact_dir"])
    data = None
    try:
        data = load_return(ad, args.worker, args.n)
        try:
            issues = derive(args.worker, data, ad, state, args.n)
        except art.ArtifactError as exc:
            issues = [str(exc)]
        if issues:
            raise Refused("MISMATCH", "the return and the artifacts disagree", issues)
    except Refused as exc:
        token, message, issues = exc.args
        state.setdefault("refused", {})[job(args.worker, args.n)] = issues
        st.add_note(state, f"{args.worker} #{args.n} refused ({token})")
        st.save(args.dir, state)
        fields = {"issue": issues}
        if data is not None:
            fields["returned"] = json.dumps(data)
        emit(args.json, token, f"{args.worker}-{args.n}: {message}; run `autodev.py "
             "next`: it re-spawns the worker with a brief whose previous_issues carries "
             "these issues. Don't guess",
             **fields)
        return FAILED
    state.get("refused", {}).pop(job(args.worker, args.n), None)
    ok = data.get("status") == "ok"
    if ok and args.worker == "define" and data.get("next") in ("FITS", "OVERSIZED"):
        state["size"] = data["next"]
        state["high_risk"] = is_yes(data.get("high_risk"))
        if data["next"] == "OVERSIZED":
            st.set_phase(state, 2, "stopped", "OVERSIZED")
            for number in (3, 4, 5, 6):
                st.set_phase(state, number, "n/a", "")
        elif state["high_risk"]:
            state["settings"]["post_plan_gate"] = True
    if ok and args.worker in ("define", "define-reviewer"):
        try:
            if rederive_risk(state, ad / "SPEC.md"):
                st.add_note(state, "SPEC.md has a Security/Compliance criterion: "
                            "high risk, post-plan gate on")
        except art.ArtifactError:
            pass  # the reviewer's verdict stands; SPEC.md is checked when it is used
    issued = next((b for b in state.get("briefs", [])
                   if b["worker"] == args.worker and b["n"] == args.n), {})
    log = state.setdefault("log", [])
    entry = {"worker": args.worker, "n": args.n, "mode": issued.get("mode"),
             "sets": issued.get("sets", {}), "status": data.get("status"),
             "next": data.get("next", ""), "data": data, "seq": st.seq(state)}
    if ok and args.worker == "planner" and issued.get("plan"):
        entry["steps_changed"] = plan_props.changed_steps(ad, issued["plan"])
    if ok and args.worker == "acceptance-tester" and issued.get("sealed"):
        entry["checks_changed"] = check_props.changed_conditions(ad, issued["sealed"])
    again = next((i for i, e in enumerate(log)
                  if e["worker"] == args.worker and e["n"] == args.n), None)
    if again is None:
        log.append(entry)
    else:  # recorded again: it keeps its place, so `next` reads the same order
        entry["seq"] = log[again].get("seq", entry["seq"])
        log[again] = entry
    st.add_note(state, f"{args.worker} #{args.n} returned {data.get('status')} "
                f"{data.get('next', '')}".rstrip())
    st.save(args.dir, state)
    emit(args.json, "RECORDED", f"{args.worker}-{args.n}", status=data.get("status"),
         next=data.get("next", ""))
    return 0


# ---------------------------------------------------------------- check-artifact

def is_snapshot(path):
    """Whether `path` lies in a run's proposals/snapshots/ folder: `proposals`
    then `snapshots`, directly inside the artifact dir (`.auto-dev`). The same
    names elsewhere in the clone's path never count."""
    parts = Path(os.path.abspath(path)).parts
    return any(parts[i - 1] == ".auto-dev" and parts[i] == "proposals"
               and parts[i + 1] == "snapshots" for i in range(1, len(parts) - 2))


def check_file(path):
    """Problems with one artifact, by its name; [] when it follows its template."""
    path = Path(path)
    name, parent = path.name, path.parent.name
    if is_snapshot(path):
        return []  # a copy taken at brief time, not a worker's file
    try:
        text = art.read(path)
    except art.ArtifactError as exc:
        return [str(exc)]
    try:
        if parent == "proposals":
            return check_proposals(path, text)
        if name == "SPEC.md":
            return check_spec(path)
        if name == "IMPLEMENTATION.md":
            heads = [ln.strip() for ln in text.splitlines() if ln.startswith("## ")]
            want = list(IMPLEMENTATION_HEADINGS)
            problems = [] if [h for h in heads if h in want] == want else [
                f"headings must be, in order: {', '.join(want)} (found: {', '.join(heads)})"]
            effort = art.review_effort(text)  # no line (a plan before 4.3): xhigh
            if effort is not None and effort not in art.REVIEW_EFFORTS:
                problems.append(f"`Review effort:` must be {' or '.join(art.REVIEW_EFFORTS)}"
                                f" (found: {effort or 'nothing'})")
            # The coder never sees SPEC.md: a plan that echoes it lets a test name
            # echo it too. In a run (state.json beside it), a missing SPEC.md is
            # reported, not skipped.
            spec = run_spec(path)
            if spec is None and (path.parent / "state.json").is_file():
                spec = path.parent / "SPEC.md"
            if spec is not None:
                problems += [f"copies SPEC.md's wording ({hit}): the coder never sees "
                             "SPEC.md, so say what the code must do in your own words"
                             for hit in overlaps(path, spec)]
            return problems
        if name == "MANIFEST.md":
            rows, _ = art.manifest(path)
            return [f"row {r['#']}: Kind `{r['Kind']}` is not fail-to-pass/pass-to-pass"
                    for r in rows if r["Kind"].strip() not in ("fail-to-pass", "pass-to-pass")]
        if name == "SPEC_EVAL.md":
            ev = art.spec_eval(path)
            problems = [f"row {r['#']}: verdict `{r['Verdict']}` is not one of "
                        f"{', '.join(sorted(VERDICTS))}" for r in ev["rows"]
                        if r["Verdict"].strip().lower() not in VERDICTS]
            if not art.header_line(text, "Tree:"):
                problems.append("no `Tree:` line")
            return problems
        if name == "CODE_REVIEW.md":
            return need_lines(text, ("**Overall confidence", "Latest pass:", "Tree:",
                                     "Must-fix:")) + need_sections(
                text, ("Must-fix", "Pending re-vote", "Advisory", "Noise", "Passes"))
        if name == "SECURITY_REVIEW.md":
            return need_lines(text, ("**Overall confidence", "Tree:", "Must-fix:")) + \
                need_sections(text, ("Findings", "Coverage"))
        if parent == "lint":
            first = text.splitlines()[:1]
            problems = [] if first and re.match(r"^# .+ — (pass|fail)\s*$", first[0]) else [
                "first line must be `# <CHECK> — pass` or `— fail`"]
            return problems + ([] if "Tree:" in text else ["no `Tree:` line"])
        if re.match(r"R\d\.md$", name):
            return need_sections(text, ("Findings", "Security leads", "Pre-existing"))
        if re.match(r"VOTES-R\d\.md$", name):
            art.first_table(text, ("Finding", "Vote", "Reason"), str(path))
            return []
        if name.endswith("corrections.md") or parent == "triage":
            problems = check_corrections(text)
            spec = run_spec(path)
            if spec is not None:
                problems += [f"copies SPEC.md's wording ({hit}): say what the code must "
                             "do and where, in your own words"
                             for hit in overlaps(path, spec, quoted=False)]
            return problems
        if parent == "fixes":
            blocks = FIX_RE.findall(text)
            declared = len(re.findall(r"^FIX\s+\S+", text, re.MULTILINE))
            if not blocks:
                return ["no FIX block"]
            return [] if declared == len(blocks) else [
                f"{declared} FIX headers but only {len(blocks)} well-formed blocks"]
        if parent == "returns" and name.endswith(".json"):
            data = json.loads(text)
            return return_problems(data.get("worker", ""), data)
    except art.ArtifactError as exc:
        return [str(exc)]
    except ValueError as exc:
        return [f"not valid JSON: {exc}"]
    return [f"no template is known for {name}"]


def run_spec(path):
    """The run's SPEC.md for a file under .auto-dev/ (up to two levels down)."""
    for parent in list(Path(path).resolve().parents)[:3]:
        if (parent / "SPEC.md").is_file():
            return parent / "SPEC.md"
    return None


def check_rulings(text, answers):
    """A rulings file: a block per proposal, each answered one of `answers`,
    a stands with a reason."""
    found = art.rulings(text)
    if not found:
        return ["no `## P<k>` ruling block"]
    problems = []
    for pid, ruling in found.items():
        if ruling["answer"] not in answers:
            problems.append(f"{pid}: `Answer:` must be {' or '.join(answers)}")
        elif ruling["answer"] == "stands" and not ruling["reason"]:
            problems.append(f"{pid} stands with no reason")
    return problems


def check_proposals(path, text):
    """A file under proposals/: a filer's proposals, a batch, or its rulings."""
    name = path.name
    if name.startswith("spec-"):
        return []  # a copy of SPEC.md, not a worker's file
    if re.match(r"(batch|plan)-\d+-rulings\.md$", name):
        return check_rulings(text, ("applied", "stands"))
    if re.match(r"checks-\d+-rulings\.md$", name):
        return check_rulings(text, ("repaired", "stands"))
    blocks = art.proposal_blocks(text)
    if not blocks:
        return ["no `## P<k>` proposal block"]
    if re.match(r"(batch|plan|checks)-\d+\.md$", name):
        return []  # next wrote it; once applied, its new text is the artifact's own
    ad = path.resolve().parent.parent
    if re.match(r"coder-\d+\.md$", name):
        # The brief's check files are unknown here: record checks those.
        return proposals.coder_problems(blocks, ad, shown=None)
    spec = run_spec(path)
    if spec is None:
        return ["no SPEC.md beside it to check the proposals against"]
    items = art.spec_items(art.read(spec), str(spec))
    worker = re.sub(r"-\d+\.md$", "", name)
    label = proposals.WORKER_LABEL.get(worker, "a filer")
    out = []
    for block in blocks:
        artifact, _ = proposals.classify(block["target"])
        if artifact == "plan":
            out.append(f"{block['pid']} names a plan step: {label} may not propose against "
                       "the plan; only the coder files plan proposals")
        elif artifact == "checks":
            route = proposals.CHECK_ROUTE.get(worker)
            out.append(f"{block['pid']} names a check: {label} questions a check only "
                       f"through {route}, never in a proposal file" if route else
                       f"{block['pid']} names a check: {label} may not question a check; "
                       "it files against SPEC.md alone")
        else:
            out += proposals.problems(block, items, from_comment=name.startswith("triager-"))
    return out


def check_spec(path):
    problems = []
    for c in art.spec_conditions(path):
        needed = ("example", "verify") if c["id"].startswith("S") else ("example", "edge", "verify")
        for key in needed:
            if not c[key]:
                label = {"verify": "Verify by"}.get(key, key.title())
                problems.append(f"condition {c['id']} has no `{label}:` line")
    return problems


def check_corrections(text):
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines or lines[0].strip() != "# Required changes":
        return ["the first line must be `# Required changes`"]
    body = "\n".join(lines[1:]).strip()
    if body == "None.":
        return []
    if not re.search(r"^\d+\.\s", body, re.MULTILINE):
        return ["no numbered entry, and not `None.`"]
    return []


def need_lines(text, prefixes):
    return [f"no `{p}` line" for p in prefixes if not art.header_line(text, p)]


def need_sections(text, names):
    found = art.sections(text)
    return [f"no `## {n}` section" for n in names
            if not any(h.startswith(n) for h in found)]


def check_artifact(args):
    if not Path(args.file).exists():
        raise Fail(f"{args.file} does not exist", CANNOT_RUN, "ERROR")
    problems = check_file(args.file)
    if problems:
        emit(args.json, "PROBLEMS", f"{args.file} does not follow its template",
             problem=problems)
        return FAILED
    emit(args.json, "OK", f"{args.file} follows its template")
    return 0
