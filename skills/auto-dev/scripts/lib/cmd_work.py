"""autodev.py brief / record / check-artifact — briefing workers and checking what they return.

brief <worker> [--mode M] [--set name=value ...] [--retry N] [--dir <artifact-dir>]
brief profiler --out <dir> --set repo=<path> --set base=<branch> --set draft_path=<path>
brief lookup --out <dir> --set worktree=<repo> --set question='<question>'
    Writes briefs/<worker>-<n>.md: one `name: value` line for every slot the
    worker's agent file (agents/<worker>.md) uses in that mode. It fills what it
    can from state.json and the artifacts (paths, base, the task (the ticket's
    text, verbatim, when `init --ticket-text-file` stored it), the profile's
    test command and gate, the acceptance checks' files and test names, the
    last survivors, the next review pass, the result file) and takes the rest
    from --set. The review judge's `tree` is the tree the panel reviewed, so
    the caller passes it (`--set tree=<hash noted before the panel>`). `--retry N` marks the brief
    as a re-spawn of job <worker>-N, which `record` refused: its
    `previous_issues` slot carries the issues saved for that job, after a line
    telling the worker to fix up its refused return rather than redo the job
    (none when it wrote no result file) (--set
    overrides), and job N is marked replaced, so `next` never re-spawns it
    too. Without --retry it is `none`. It refuses when a slot the worker needs has no value.
    A brief for a worker that judges against PLAN.md and may report it wrong
    (the verifier, the reviewer, the review judge, the security reviewers,
    the triager)
    keeps PLAN.md's digest on its state entry (a --retry keeps the first
    brief's): `record` refuses a return that changed PLAN.md.
    A brief for a worker that never changes the repo (the planner, the plan
    critic, the review judge, the triager)
    keeps the worktree's HEAD and the content of every file `git status` lists
    outside the artifact dir on its state entry, for `record`. A retry takes
    its own, and so does a brief `next` sends out again.
    Prints the agent type to spawn and the one-line prompt to give it.
    With --out (the profiler always; a lookup before the run exists), the
    brief goes to <dir> with no state.json: a lookup's answer goes to
    <dir>/lookup-<n>-answer.md and its symbol lookup is `grep -n`, and nothing is
    recorded (`record` needs a run; read the answer from the worker's reply).
    Exit: 0 written; 1 refused (the missing slots are listed, or --retry names
    a job `record` did not refuse).

record <worker> <n>
    `next` does this itself, before it decides, for every issued brief whose
    result file exists; run it by hand to record one result now and see its
    verdict, as `next` would.
    For a worker whose brief kept the tree (see brief), it first compares the
    worktree with it, whatever the worker returned: a file `git status` lists
    outside the artifact dir that changed is refused. It backs each changed
    file up to tree/<worker>-<n>/ and puts it back as it was at the brief (a
    file git ignored again once .gitignore is back stays). Only a change the
    worker could have made counts: a file last written after its result file
    is left alone, and the check is skipped when HEAD moved (an outside
    commit, which Phase 6 handles), for a job already recorded or replaced or
    with no result file yet, when a worker that does change the repo was
    briefed while it was out, or when init's setup commands were still
    running at its brief.
    Reads returns/<worker>-<n>.json and checks it: `status` is ok, blocked or
    failed; `next`, when given, is one the worker may return; with status ok,
    every key of the worker's `auto-dev-result` block is present. Then, for an
    ok return, it re-derives the same decision from the artifacts the worker
    wrote: the verifier's `next` against `eval-status`, and its required
    changes (one entry at least for CORRECT); the judge's
    `next`, must-fix and re-vote counts against CODE_REVIEW.md; the
    reviewer's (a standard-risk pass) against CODE_REVIEW.md and
    SECURITY_REVIEW.md; the triager's class and counts
    against its triage files (blockers in `triage_file`, acceptance check
    comments in `checks_file`); the lookup's answer at lookups/<n>.md; for
    the acceptance tester, that each file MANIFEST.md names is in the
    worktree (it leaves its checks there; `next` commits them). A coder's
    return is refused when it changed or removed a line of the committed
    acceptance checks (lib/protected.py) that was whole at its brief.
    A required-changes file that reaches the coder unedited (the verifier's,
    the judge's, the triager's) must follow its template.
    The planner's result must agree with PLAN.md (its size check and its
    `Risk:` tier, which is high when it has Security/Compliance criteria), and
    the plan critic's with its review file (plan-review/<n>.md: the verdict,
    the blocker count, the tier). Every other file the return says the
    worker wrote must pass check-artifact: SPEC_EVAL.md, a code reviewer's
    report or votes, CODE_REVIEW.md and SECURITY_REVIEW.md. Each must exist.
    Spec problems (spec-problems/<worker>-<n>.md, counted by the result's
    `spec_problems` key): only the verifier, the reviewer, the review judge in consolidate
    mode, the security reviewers and the triager in human mode may report one;
    the count must match the file's `- condition <id>: <why>` and `- missing:
    <why>` lines, and each id must be a condition or criterion PLAN.md has.
    Such a worker's return is refused, whatever its status, when PLAN.md
    changed since its brief. The coder's deviations from the plan
    (deviations/coder-<n>.md, counted by `deviations`): the count must match
    the file's list lines.
    A fixer's return is refused when its status is not ok but its `next` is
    FIXED; for FIXED, its report names every path it changed, the run's
    settings in state.json as `.auto-dev/state.json`.
    On a match it updates state.json (for the planner's write-mode return, the
    size check; a `risk: high` from the planner or the plan critic turns a run
    that FITS high-risk with the post-plan gate on, and nothing turns it off; a
    note of what came back, and the result in the log `autodev.py next` reads) and
    prints `RECORDED` with the `next` token.
    Exit: 0 recorded; 1 the return is missing or malformed (`MISSING`,
    `MALFORMED`) or disagrees with the artifacts (`MISMATCH`, both sides
    printed). Either way the issues are saved in state.json for job
    <worker>-<n>: run `autodev.py next`, which re-spawns it with a brief whose
    `previous_issues` carries them (as `brief <worker> --retry <n>` writes). A
    later RECORDED for <worker>-<n> clears them. Each refused job is counted
    once for metrics.json (by worker and token), even when it is recorded again
    or its retry is accepted. Recording a job again keeps its place in the
    log. Don't guess.

check-artifact <file>
    Checks one artifact against its template before a worker returns it:
    PLAN.md (its headings in order, each condition's Example, Edge and Verify
    by lines, a `Risk:` line of standard or high, and a `Review effort:` line
    of high or xhigh; an OVERSIZED plan may stop at its size check), a plan
    review (plan-review/<n>.md: its verdict, tier and blockers, each with
    Evidence and Change lines, at most 7), acceptance/MANIFEST.md, SPEC_EVAL.md,
    CODE_REVIEW.md, SECURITY_REVIEW.md, review/pass-<n>/R<k>.md and
    VOTES-R<k>.md, lint/<CHECK>.md, a required-changes file (corrections.md,
    triage/*.md), a spec-problems file
    (spec-problems/<worker>-<n>.md, held to the run's PLAN.md), the coder's
    deviations (deviations/coder-<n>.md), or a returns/*.json file.
    Exit: 0 it follows the template; 1 problems (each printed).

All exit 2 when they could not run — never a pass.
"""

import copy
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from . import artifacts as art
from . import (
    briefs,
    cmd_run,
    overrides,
    protected,
    tree_guard,
)
from . import state as st
from .cmd_review import pending_rows
from .output import CANNOT_RUN, FAILED, Fail, emit
from .testfiles import test_keys

SCRIPTS = Path(__file__).resolve().parent.parent
SKILL_DIR = SCRIPTS.parent
BINDING_RULES = ("the repo's CLAUDE.md or AGENTS.md, CONTRIBUTING and coding-guideline "
                 "docs, and the security directives named in {artifact_dir}/profile.md; "
                 "they override finishing the task")
# PLAN.md's headings, in order. An OVERSIZED plan stops at its size check.
PLAN_HEADINGS = ("## Context", "## Conditions", "## Assumptions", "## Size check")
STEP_HEADINGS = ("## Files", "## Design", "## Build sequence", "## Test plan",
                 "## Migrations / config")
VERDICTS = {"met", "partial", "unmet", "manual"}
# The workers that judge against PLAN.md and may report a criterion wrong or
# missing (spec-problems/<worker>-<n>.md); they never edit PLAN.md.
SPEC_JUDGES = ("verifier", "reviewer", "review-judge", "security-reviewer",
               "security-reviewer-sensitive", "triager")
# The planner's keys `next` acts on, compared word for word.
PLANNER_VALUES = {"reading": {"none", "tester", "other"},
                  "entry_points_changed": {"none", "yes", "no"}}
SPEC_PROBLEM_RE = re.compile(r"^\s*[-*]\s*(?:condition\s+(S?\d+)|missing)\s*:\s*(.*)$",
                             re.IGNORECASE)
DEVIATION_RE = re.compile(r"^\s*[-*]\s+\S")


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


def tester_issues(state, ad):
    """The acceptance tester leaves its checks in the worktree, where `next`
    commits them: each file MANIFEST.md names must be there."""
    wt = Path(state["worktree"])
    return [f"{rel} is in MANIFEST.md but not in the worktree: write its checks there "
            "(at the path the repo's test layout uses) and leave them in place"
            for rel in check_files(ad) if not (wt / rel).is_file()]


def tester_tree_issues(state, ad, nxt, n):
    """The tester changes only the check files MANIFEST.md names, and in write
    mode only adds to a file the repo had: a line it changed or removed there
    is the repo's own test, not its to touch."""
    wt = state["worktree"]
    checks = check_files(ad)
    issues = []
    if nxt == "WRITTEN":
        for rel in checks:
            try:
                tree_guard.git(wt, "cat-file", "-e", f"HEAD:{rel}")
            except Fail:
                continue  # a new file: all of it is the tester's
            try:
                hit = sorted(protected.changed_lines(wt, "HEAD", rel))
            except protected.GuardError as exc:
                raise Fail(f"cannot read {rel} at HEAD: {exc}", CANNOT_RUN, "ERROR") from None
            if hit:
                issues.append(f"{rel}: you changed or removed line(s) "
                              + ", ".join(map(str, hit)) + " the repo already had; add your "
                              "checks to the file, and leave its own lines as they were")
    issued = next((b for b in state.get("briefs", [])
                   if b["worker"] == "acceptance-tester" and b["n"] == n), {})
    before = issued.get("tester_tree")
    if before:
        after = tree_guard.snapshot(wt, ad)
        if after["head"] == before["head"]:
            other = [p for p in tree_guard.changed(before, after) if p not in checks]
            if other:
                issues.append("you changed " + ", ".join(other) + ", which MANIFEST.md names "
                              "as no check file: change only your check files (and "
                              "MANIFEST.md and base-run/); put the rest back, and remove "
                              "any file your test runs left")
    return issues


def tester_untouched_issues(state, ad, n):
    """A tester that ruled its checks right as written (STANDS), or stopped
    without a result, changed nothing in the worktree since its brief."""
    issued = next((b for b in state.get("briefs", [])
                   if b["worker"] == "acceptance-tester" and b["n"] == n), {})
    before = issued.get("tester_tree")
    if not before:
        return []
    after = tree_guard.snapshot(state["worktree"], ad)
    changed = tree_guard.changed(before, after) if after["head"] == before["head"] else []
    if not changed:
        return []
    return ["you changed " + ", ".join(changed) + " but returned no repair: a check you "
            "rule right as written (STANDS), or a return that isn't ok, leaves the "
            "worktree as it was. Put each back"]


def check_files(ad):
    """The files MANIFEST.md says hold acceptance checks, sorted; [] when it
    can't be read."""
    try:
        rows, _ = art.manifest(Path(ad) / "acceptance" / "MANIFEST.md")
    except art.ArtifactError:
        return []
    return sorted(test_names(rows))


def check_snapshot(state, ad):
    """{path: blob sha, or None when absent} for every check file MANIFEST.md
    names and every file a tests commit holds, as they are now."""
    wt = Path(state["worktree"])
    paths = sorted(set(check_files(ad)) | {p for c in state.get("tests_commits") or []
                                           for p in c["paths"]})
    present = [p for p in paths if (wt / p).is_file()]
    found = tree_guard.blobs(wt, present) if present else {}
    return {p: found.get(p) for p in paths}


def tests_shas(state):
    return [c["sha"] for c in state.get("tests_commits") or []]


def guard_locations(state):
    """Every committed acceptance check line changed or removed now, as
    `path:line` (`path` for a file that is gone)."""
    shas = tests_shas(state)
    if not shas:
        return []
    try:
        return protected.locations(state["worktree"], shas)
    except protected.GuardError as exc:
        raise Fail(f"cannot check the committed acceptance checks: {exc}", CANNOT_RUN,
                   "ERROR") from None


def test_names(rows_):
    """{check file: [its checks' test names]}, in MANIFEST.md's order, each
    name once (a file with none maps to [])."""
    names = {}
    for r in rows_:
        cell = r["Check (path :: test name)"]
        path = art.check_path(cell)
        if path:
            name = cell.split("::", 1)[-1].strip().strip('"') if "::" in cell else ""
            names.setdefault(path, [])
            if name and name not in names[path]:
                names[path].append(name)
    return names


def acceptance_paths(ad):
    """Each file that holds committed acceptance checks, with their test names:
    a file can hold the coder's own tests too."""
    try:
        rows, _ = art.manifest(ad / "acceptance" / "MANIFEST.md")
    except art.ArtifactError:
        return "none"
    names = test_names(rows)
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


def base_commit(worktree, base):
    """`cut_commit`, or '' where that fails: measured against origin/<base>,
    never the main checkout's local base branch, which can lag far behind
    (every commit merged since would count as the run's). The local branch
    is read only when origin's can't be: it can only reach back further."""
    for ref in (f"origin/{base}", base):
        out = subprocess.run(["git", "-C", str(worktree), "merge-base", ref, "HEAD"],
                             capture_output=True, text=True, check=False)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    return ""


def issues_text(issues):
    return "\n".join(f"- {i}" for i in issues)


def auto_values(worker, n, state, ad, mode):
    """Every AUTO slot's value for this run (some depend on the worker). In a
    coder correction, each test check the quality gate's latest run lists as
    failing (and the user didn't sign off) gets its run line in the gate list."""
    s = state["settings"]
    found = cmd_run.test_check(s.get("gate", []))
    test = str(found[1].get("command") or "") if found else ""
    failing = (failing_test_checks(s.get("gate", []), state)
               if worker == "coder" and mode == "correction" else None)
    gate = gate_lines(s.get("gate", []), ad, worker, failing)
    phase6 = state.get("phase6", {})
    values = {
        "worktree": state["worktree"], "artifact_dir": str(ad), "skill_dir": str(SKILL_DIR),
        "base": state["repo"]["base"], "branch": state["branch"],
        "task": (state["task"].get("ticket_text") or state["task"].get("ask")
                 or state["task"].get("text", "")),
        "ticket": st.ticket_line(state["task"]).split(" — ")[0],
        "binding_rules": BINDING_RULES.format(artifact_dir=ad),
        "test_command": test or "none", "test_notes": s.get("test_notes") or "none",
        # Mutation runs on a high-risk run only (the verifier's probes run on
        # every run: agents/verifier.md).
        "mutation_cap": (str(s.get("mutation_max", 20))
                         if state.get("high_risk") and s.get("mutation_max", 20) else
                         "0 (off)" if state.get("high_risk") else
                         "0 (off: a standard-risk run)"),
        "gate_commands": gate or "none",
        "test_runs": (test_runs(found[1], ad, worker, s.get("gate", [])) if found
                      else "none"),
        "result_file": str(ad / "returns" / f"{worker}-{n}.json"),
        "pr": str(phase6.get("pr") or "none"),
        "pass": str(phase6.get("review_pass") or 1),
        "run": str(phase6.get("security_run", 0) + 1),
        "triage_file": str(ad / "triage" / f"{mode or 'triage'}-{n}.md"),
        "checks_file": str(ad / "triage" / f"{mode or 'triage'}-{n}-checks.md"),
        "answer_file": str(ad / "lookups" / f"{n}.md"),
        "blocked_file": str(ad / "blocked" / f"coder-{n}.md"),
        "review_file": str(ad / "plan-review" / f"{n}.md"),
        "deviations_file": str(ad / "deviations" / f"coder-{n}.md"),
        "spec_problem_file": str(ad / "spec-problems" / f"{worker}-{n}.md"),
        "fix_report": str(ad / overrides.FIX_DIR / f"fixer-{n}.md"),
    }
    return values


# After every `run` line a brief gives: the Bash tool's default 120 s would cut
# a check short (a call still running at 180 s moves to the background, where
# `run wait` waits for it; `run` ends a hung check at its own timeout).
BASH = " with that Bash call's timeout set to 300000 ms"


def whole_runner(gate):
    """Who runs the gate's test checks whole, for the coder's brief: CI when the
    gate has one `kind: test` check (the quality gate scopes it to the change),
    the quality gate when it has two or more (it runs them all whole)."""
    several = sum(c.get("kind") == "test" for c in gate) > 1
    return (("the quality gate", "the quality gate runs it whole") if several
            else ("CI", "left to CI"))


def failing_test_checks(gate, state):
    """The numbers of the `kind: test` checks the quality gate's latest run (the
    newest one no retry set aside, as `next` reads it) lists as failing, less
    the reports the user signed off (counted green for the rest of the run).
    Only the gate's own result counts: no correction text is read, so a check
    red in CI or in the verifier's or a reviewer's corrections gets no extra
    line."""
    runs = [g for g in state.get("gate_runs") or [] if not g.get("aside")]
    failing = set(runs[-1].get("failing") or []) if runs else set()
    failing -= overrides.signed_reports(state)
    return {i for i, c in enumerate(gate, 1)
            if c.get("kind") == "test" and c.get("report") in failing}


FAILING_HEAD = ("(a test check the quality gate's latest run found failing: run it only "
                "with the line below, to check your fix)")


def gate_lines(gate, ad, worker, failing=None):
    """The gate_commands slot: each check with the `run:` line that runs it
    whole; for the coder, the test check `run test` uses only scoped (no line
    for one with no scoped form) and every other test check with no line, since
    CI (one test check) or the quality gate (two or more) runs them whole. In a
    correction, a test check in `failing` (one the quality gate's latest run
    lists as failing) gets its `--files` line when it has a `files` form, else
    its whole line."""
    found = cmd_run.test_check(gate)
    chosen = found[0] if found else None
    who, whole = whole_runner(gate)
    failing = failing or set()
    entries = []
    for i, c in enumerate(gate, 1):
        invocation = f"run gate {i}"
        if worker != "coder" or c.get("kind") != "test":
            entries.append(f"{i}. `{c['command']}`\n"
                           f"   run: `{cmd_run.run_line(ad, invocation)}`{BASH}")
            continue
        if i in failing and not cmd_run.has_form(c, "files"):
            # No file form: its whole line, and (for the check `run test`
            # uses) its test-ID line too.
            lines = [cmd_run.run_line(ad, invocation)]
            if i == chosen:
                lines += [line for line, _ in cmd_run.scoped_runs(ad, c, invocation,
                                                                    ("tests",))]
            entries.append("\n".join([f"{i}. `{c['command']}` {FAILING_HEAD}"]
                                     + [f"   run: `{line}`{BASH}" for line in lines]))
            continue
        if i in failing and i != chosen:
            line = cmd_run.scoped_runs(ad, c, invocation, ("files",))[0][0]
            entries.append(f"{i}. `{c['command']}` {FAILING_HEAD}\n"
                           f"   run: `{line}`{BASH}")
            continue
        if i != chosen:
            entries.append(f"{i}. `{c['command']}` (a test check `run test` doesn't use: "
                           f"{whole}; don't run it)")
            continue
        runs = cmd_run.scoped_runs(ad, c, invocation)
        if not runs:
            entries.append(f"{i}. `{c['command']}` (a test check with no scoped form: "
                           f"{whole}; don't run it, and name it in one line above your "
                           "result block)")
            continue
        head = (f"{i}. `{c['command']}` (a test check: run it only scoped, on your "
                f"tests; never whole — {who} runs it whole)")
        entries.append("\n".join(
            [head] + [f"   run: `{line}`{BASH}" + (f" ({note})" if note else "")
                      for line, note in runs]))
    return "\n".join(entries)


def test_runs(check, ad, worker=None, gate=()):
    """The test_runs slot: the run's scoped test commands, filled in and ready to
    copy, and that a whole run of the test check is for the quality gate only;
    for a check with no scoped form, the one line that runs it whole (the
    coder's: no line, since CI or the quality gate runs it, as `gate` says)."""
    runs = cmd_run.scoped_runs(ad, check)
    if not runs and worker == "coder":
        who = whole_runner(gate or [check])[0]
        whole = "that is left to CI" if who == "CI" else "the quality gate runs it whole"
        return (f"No line: the test check (`{check.get('command', '')}`) has no scoped "
                f"form, so it runs only whole, and {whole}: don't run it, and "
                "name it in one line above your result block.")
    if not runs:
        return (f"- `{cmd_run.run_line(ad)}`{BASH}\n"
                "The test check has no scoped form, so it only runs whole: this line "
                "is the way to run its tests.")
    lines = [f"- `{line}`{BASH}" + (f" ({note})" if note else "") for line, note in runs]
    if not cmd_run.has_form(check, "tests"):
        lines.append("- no test-ID form: scope by file")
    # Who runs it whole depends on the gate alone, so every worker gets the same text.
    why = ("with two or more test checks it runs each one whole"
           if whole_runner(gate or [check])[0] == "the quality gate" else
           "CI is the one full run of the test suite when it is watched")
    lines.append(f"A whole run of the test check is for the quality gate only ({why}); "
                 "never run `run test` with neither flag to test your change.")
    return "\n".join(lines)


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
    lifted = max(state.get("resumed_seq", 0), state.get("lifted_seq", 0))
    log = [e for e in state.get("log") or []
           if e.get("seq", 0) > lifted
           and e.get("worker") != "code-reviewer"
           and not (e.get("worker") == worker and e.get("mode") != mode)]
    return bool(log) and log[-1].get("worker") == worker and \
        log[-1].get("status") == "blocked"


REFUSED_RETRY = ("`record` refused your last return for this job, and the files you wrote "
                 "for it are still in place. If they are complete, and any Tree line in "
                 "them is the tree now, start from them: fix each issue below, redo what "
                 "your fix makes stale (re-run, re-save, re-judge and re-stamp "
                 "the Tree line of whatever depends on what you change, as your "
                 "instructions say), and redo nothing else, even where your instructions "
                 "say to start clean or from scratch. If they are missing, partial or "
                 "from an earlier pass, do the job as your instructions say.")
NO_RESULT = "you wrote no result file at"  # MISSING: nothing returned to fix up
# The note a worker with a turn cap gets when its last spawn ended with no
# result file (next's pending_briefs): it may have run out of turns mid-job.
NO_RESULT_RETRY = ("Your last spawn for this job ended without writing its result file "
                   "(it may have run out of turns). What it changed is still in the "
                   "worktree: keep those edits, don't revert them or start over. Check "
                   "them against your instructions, finish what is left, and write your "
                   "result file. This is your one re-spawn for that: ending without a "
                   "result file again stops the run.")
# After the issues the replaced brief carried (a refusal's, BLOCKED_ONCE): they
# still stand, and one that says to undo an edit wins over "keep those edits".
NO_RESULT_AFTER = ("Fix each issue above too: where one says to undo an edit, undo it, "
                   "and keep the rest.")


def saved_issues(state, worker, retry):
    """The issues record saved for job <worker>-<retry>, after a line saying to
    fix up the refused return rather than redo the job; None without --retry."""
    if retry is None:
        return None
    issues = state.get("refused", {}).get(job(worker, retry))
    if not issues:
        raise Fail(f"--retry {retry}: record refused no return for {job(worker, retry)}",
                   FAILED, "REFUSED")
    if issues[0].startswith(NO_RESULT):
        return issues_text(issues)
    return REFUSED_RETRY + "\n" + issues_text(issues)


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


def write_brief(state, where, worker, mode, given, retry=None, note=None):
    """Write briefs/<worker>-<n>.md and log it in `state` (the caller saves).

    `where` is the artifact dir, or with no run (state None: the profiler, a
    lookup before init) the folder to write into. `retry` re-spawns job
    <worker>-<retry>, which record refused: its saved issues fill
    previous_issues. With `note` (and `retry`), `record` need not have refused
    the job: previous_issues is the issues the brief of job <worker>-<retry>
    carried (its `carried` text: a refusal's issues, BLOCKED_ONCE), when it
    carried any, followed by the note; `next` re-spawns a worker that ended
    with no result file this way. Returns (path, the slot values)."""
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
        ad, directory, previous, carried = None, where, None, None
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
        if note is not None:
            # The replaced brief's issues still stand: the note goes after them.
            replaced = next((b for b in state.get("briefs") or []
                             if b["worker"] == worker and b["n"] == retry), {})
            carried = replaced.get("carried")
            previous = f"{carried}\n{note} {NO_RESULT_AFTER}" if carried else note
        else:
            carried = previous = saved_issues(state, worker, retry)
            if previous is None and blocked_last(state, worker, mode):
                carried = previous = BLOCKED_ONCE
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
        for sub in ("returns", "plan-review", "triage", "lookups", "blocked", "deviations",
                    "spec-problems", overrides.FIX_DIR):
            (ad / sub).mkdir(exist_ok=True)
    path = directory / f"{worker}-{n}.md"
    path.write_text(briefs.render(worker, n, mode, values), encoding="utf-8")
    if state is not None:
        entry = {"worker": worker, "n": n, "mode": mode, "sets": given, "at": st.now(),
                 "retry": retry, "seq": st.seq(state)}
        if carried and briefs.max_turns(worker):
            # A capped re-spawn of this brief carries them on (`note`).
            entry["carried"] = carried
        watch_spec(state, ad, worker, retry, entry)
        if retry is None and worker == "coder":
            # A check line broken already is not this worker's doing.
            entry["broken"] = guard_locations(state)
        if worker in tree_guard.GUARDED:
            entry["tree"] = tree_guard.snapshot(auto["worktree"], ad)
        if worker == "acceptance-tester" and retry is None:
            # It may change only its check files: compared at `record`.
            entry["tester_tree"] = tree_guard.snapshot(auto["worktree"], ad)
        if retry is None and (worker == "fixer" or (worker == "acceptance-tester"
                                                    and mode == "repair")):
            # The check files as they are: its tests commit takes only its change.
            entry["check_blobs"] = check_snapshot(state, ad)
        if worker == "fixer" and retry is None:
            # What it changes is listed, and put back if it ends without fixing.
            entry["fix_tree"] = tree_guard.snapshot(auto["worktree"], ad)
            entry["artifacts"] = overrides.save_artifacts(ad, n)
            entry["artifacts_n"] = n
            entry["settings"] = copy.deepcopy(state["settings"])  # never the fixer's
        state.setdefault("briefs", []).append(entry)
        for old in state["briefs"]:
            if retry is not None and old["worker"] == worker and old["n"] == retry:
                old["retried_as"] = n  # replaced: `next` never re-issues it
    return path, values


def watch_spec(state, ad, worker, retry, entry):
    """A worker that judges against PLAN.md is held to it as it was when it was
    briefed: keep PLAN.md's digest on its brief entry. A retry keeps the first
    brief's copies, so the base never moves."""
    if retry is not None:
        old = next((b for b in state.get("briefs", [])
                    if b["worker"] == worker and b["n"] == retry), {})
        for key in ("spec", "broken", "tester_tree", "check_blobs", "fix_tree",
                    "artifacts", "artifacts_n", "settings"):
            if key in old:
                entry[key] = old[key]
        return
    if worker in SPEC_JUDGES:
        entry["spec"] = digest(ad / "PLAN.md")


def digest(path):
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def fresh_tree(state, issued):
    """A brief `next` sends out again (no result came back) is held to the tree
    and PLAN.md as they are now: what changed while no worker was out is not
    this spawn's."""
    if issued.get("tree"):
        issued["tree"] = tree_guard.snapshot(state["worktree"], state["artifact_dir"])
    if issued.get("spec"):
        issued["spec"] = digest(Path(state["artifact_dir"]) / "PLAN.md")


def refresh_spec(state, ad):
    """After a fix at a stop changed PLAN.md: every brief not yet recorded is
    held to PLAN.md as it is now, not as it was before the fix."""
    done = {(e["worker"], e["n"]) for e in state.get("log") or []}
    for b in state.get("briefs") or []:
        if b.get("spec") and (b["worker"], b["n"]) not in done:
            b["spec"] = digest(Path(ad) / "PLAN.md")


# ---------------------------------------------------------------- record

class Refused(Exception):
    """The return can't be recorded: (token, message, issues)."""


def load_return(ad, worker, n):
    path = ad / "returns" / f"{worker}-{n}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise Refused("MISSING", f"no {path}: the worker wrote no result file",
                      [f"{NO_RESULT} {path}"]) from None
    except ValueError as exc:
        raise Refused("MALFORMED", f"{path} is not JSON",
                      [f"{path} is not JSON: {exc}"]) from None
    mode = mode_of(ad, worker, n)
    problems = return_problems(worker, data, mode)
    if problems:
        raise Refused("MALFORMED", f"{path} is malformed", problems)
    return data


def mode_of(ad, worker, n):
    """The mode job <worker>-<n> was briefed in (None when it has none, or the
    brief isn't in state.json)."""
    try:
        state = st.load(ad)
    except st.StateError:
        return None
    issued = next((b for b in state.get("briefs") or []
                   if b["worker"] == worker and b["n"] == n), {})
    return issued.get("mode")


def return_problems(worker, data, mode=None):
    problems = []
    if not isinstance(data, dict):
        return ["not a JSON object"]
    if not isinstance(worker, str):
        return [f"worker is {worker!r}, not a worker's name"]
    if data.get("worker") != worker:
        problems.append(f"worker is {data.get('worker')!r}, expected {worker!r}")
    if data.get("status") not in briefs.STATUSES:
        problems.append(f"status {data.get('status')!r} is not ok/blocked/failed")
    allowed = briefs.MODE_RESULTS.get((worker, mode)) or briefs.RESULTS.get(worker, set())
    nxt = data.get("next")
    if data.get("status") == "ok" or nxt not in (None, "", "none"):
        if nxt not in allowed:
            problems.append(f"next {nxt!r} is not one of {', '.join(sorted(allowed))}"
                            + (f" (in {mode} mode)" if (worker, mode) in briefs.MODE_RESULTS
                               else ""))
    if data.get("status") == "ok" and worker in briefs.RESULTS:
        missing = [k for k in briefs.result_keys(worker) if k not in data]
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
    if worker in SPEC_JUDGES and issued.get("spec") and \
            digest(ad / "PLAN.md") != issued["spec"]:
        # Whatever the status: only the user changes PLAN.md (a fix at a stop).
        issues.append("PLAN.md changed since your brief: never edit it. Put it back as "
                      "it was, and report a criterion you find wrong or missing in "
                      "spec_problems instead")
    if worker == "fixer":
        if data.get("status") != "ok" and data.get("next") == "FIXED":
            issues.append(f"status is {data.get('status')} but next is FIXED: return "
                          "FIXED only with status ok, once you carried out the whole "
                          "instruction; stopped part way, return blocked with next "
                          "none (what you changed is put back) and say why")
    # Whatever the status: a coder never leaves a committed check's line
    # changed (the next coder's brief would count it as broken already), and a
    # tester that wrote nothing it returns leaves the tree as it found it.
    if worker == "coder":
        issues += edited_check_issues(state, issued.get("broken", []))
    if worker == "acceptance-tester" and (data.get("status") != "ok" or
                                          data.get("next") == "STANDS"):
        issues += tester_untouched_issues(state, ad, n)
    if data.get("status") != "ok":
        return issues
    issues += result_issues(worker, data, ad, state, n) + artifact_issues(
        worker, data, ad, state, n)
    issues += spec_problem_issues(worker, issued.get("mode"), data, ad, n)
    if worker == "coder":
        issues += deviation_issues(data, ad, n)
    return issues


def edited_check_issues(state, broken):
    """The committed acceptance checks' lines the coder changed or
    removed (those `broken` already at its brief aside), one issue per file."""
    new = [loc for loc in guard_locations(state) if loc not in set(broken)]
    by_file = {}
    for loc in new:
        path, _, line = loc.rpartition(":") if ":" in loc else (loc, "", "")
        by_file.setdefault(path or loc, []).append(line)
    issues = []
    for path, lines in sorted(by_file.items()):
        what = (f"{path} was removed or moved: put it back at that path" if lines == [""]
                else f"you changed the committed acceptance checks in {path} at line(s) "
                     + ", ".join(lines))
        issues.append(
            f"{what}. The acceptance checks are committed and never yours to edit: "
            "put each line back exactly as the tests commit has it (`git diff "
            "<tests commit> -- <path>` shows what changed), and make your code fit "
            "them; add your own tests and imports around them")
    return issues


def spec_problem_items(path):
    """[(condition id, or `missing`, why)] of a spec-problems file."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return []
    items = []
    for line in text.splitlines():
        match = SPEC_PROBLEM_RE.match(line)
        if match:
            cid = match.group(1).upper() if match.group(1) else "missing"
            items.append((cid, match.group(2).strip()))
    return items


def spec_problem_lines(path, spec):
    """Problems with a spec-problems file: no item, an item with no why, or a
    condition the run's PLAN.md does not have."""
    items = spec_problem_items(path)
    if not items:
        return ["no `- condition <id>: <why>` or `- missing: <why>` line"]
    try:
        ids = {c["id"] for c in art.spec_conditions(spec)} if spec else None
    except art.ArtifactError:
        ids = None
    out = []
    for cid, why in items:
        if not why:
            out.append(f"{cid}: say what is wrong and what shows it")
        elif ids is not None and cid != "missing" and cid not in ids:
            out.append(f"condition {cid} is not in PLAN.md (an added criterion is "
                       "`- missing: <why>`)")
    return out


def spec_problem_issues(worker, mode, data, ad, n):
    """The `spec_problems` count against spec-problems/<worker>-<n>.md."""
    count = as_int(data, "spec_problems")
    if count == 0:
        return []
    if worker not in SPEC_JUDGES or (worker, mode) in (("review-judge", "security-verify"),
                                                         ("triager", "ci")):
        return [(f"spec_problems is {count}, but {worker} ({mode or 'no mode'}) never "
                 "reports a spec problem: return 0")]
    path = ad / "spec-problems" / f"{worker}-{n}.md"
    if not path.is_file():
        return [f"spec_problems is {count} but {path} does not exist"]
    issues = [f"{path.name}: {p}" for p in spec_problem_lines(path, ad / "PLAN.md")]
    found = len(spec_problem_items(path))
    if found and found != count:
        issues.append(f"spec_problems is {count} but {path.name} lists {found}")
    return issues


def deviation_lines(path):
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return []
    return [ln for ln in text.splitlines() if DEVIATION_RE.match(ln)]


def deviation_issues(data, ad, n):
    """The coder's `deviations` count against deviations/coder-<n>.md."""
    count = as_int(data, "deviations")
    path = ad / "deviations" / f"coder-{n}.md"
    found = len(deviation_lines(path))
    if count == 0:
        return [f"deviations is 0 but {path} lists {found}"] if found else []
    if not path.is_file():
        return [f"deviations is {count} but {path} does not exist"]
    if found != count:
        return [(f"deviations is {count} but {path.name} lists {found} `- step <n>: …` "
                 "line(s)")]
    return []


def written_files(worker, data, ad, state, n):
    """[(path, required)]: the files this result says the worker wrote that no
    other check reads (required-changes files are checked by coder_bound)."""
    nxt = data.get("next")
    issued = next((b for b in state.get("briefs", [])
                   if b["worker"] == worker and b["n"] == n), {})
    mode, sets = issued.get("mode"), issued.get("sets", {})
    review = ad / "review" / f"pass-{state.get('phase6', {}).get('review_pass') or 1}"
    files = []
    if worker == "plan-critic":  # it has no shell to run check-artifact itself
        files.append((ad / "plan-review" / f"{n}.md", True))
    elif worker == "verifier" and nxt != "MUTATION_LEFT_CHANGES":
        files.append((ad / "SPEC_EVAL.md", True))
    elif worker == "code-reviewer" and sets.get("reviewer"):
        name = "VOTES-" if mode == "re-vote" else ""
        files.append((review / f"{name}{sets['reviewer']}.md", True))
    elif worker == "review-judge":
        files.append((ad / ("SECURITY_REVIEW.md" if nxt == "VERIFIED" else "CODE_REVIEW.md"),
                      True))
    elif worker in ("security-reviewer", "security-reviewer-sensitive"):
        files.append((ad / "SECURITY_REVIEW.md", True))
    elif worker == "reviewer":
        files += [(ad / "CODE_REVIEW.md", True), (ad / "SECURITY_REVIEW.md", True)]
    return files


def artifact_issues(worker, data, ad, state, n):
    """Each file the worker wrote must follow its template."""
    issues = []
    for path, required in written_files(worker, data, ad, state, n):
        if not path.exists():
            if required:
                issues.append(f"{path} does not exist")
            continue
        issues += [f"{path.name}: {p}" for p in check_file(path)]
    return issues


def result_issues(worker, data, ad, state, n):
    nxt = data.get("next")
    issues = []
    if worker == "planner" and nxt in ("FITS", "OVERSIZED", "REVISED", "PLAN_REVISED",
                                       "UPDATE_OLD_TEST"):
        problems = check_file(ad / "PLAN.md")
        issues += [f"PLAN.md: {p}" for p in problems]
        if not problems:
            issues += plan_result_issues(data, ad / "PLAN.md", nxt)
        for key, values in PLANNER_VALUES.items():
            value = str(data.get(key, "none")).strip()
            if value not in values:
                issues.append(f"{key} is {data.get(key)!r}: write one of "
                              + ", ".join(sorted(values)))
    elif worker == "plan-critic":
        issues += critic_result_issues(data, ad / "plan-review" / f"{n}.md", ad / "PLAN.md",
                                       state)
    elif worker == "acceptance-tester" and nxt in ("WRITTEN", "REPAIRED"):
        # Gaps are not a disagreement: `next` re-spawns the tester for them.
        art.manifest(ad / "acceptance" / "MANIFEST.md")
        if str(data.get("ambiguous", "none")).strip().lower() not in ("none", "") and \
                not (ad / "acceptance" / "AMBIGUOUS.md").is_file():
            issues.append(f"ambiguous is {data.get('ambiguous')} but "
                          f"{ad / 'acceptance' / 'AMBIGUOUS.md'} does not exist: write "
                          "both readings of each condition there")
        issues += tester_issues(state, ad)
        issues += tester_tree_issues(state, ad, nxt, n)
    elif worker == "coder":
        if (nxt == "BLOCKED") != (as_int(data, "blocked") > 0):
            issues.append(f"next is {nxt} but blocked is {data.get('blocked')}")
        listed = ad / "blocked" / f"coder-{n}.md"
        if nxt == "BLOCKED" and not listed.exists():
            issues.append(f"next is BLOCKED but {listed} does not exist")
    elif worker == "verifier":
        issues += derive_verifier(nxt, ad)
    elif worker == "reviewer":
        issues += derive_reviewer(data, ad, state)
    elif worker in ("security-reviewer", "security-reviewer-sensitive"):
        issues += derive_security(data, ad)
    elif worker == "review-judge":
        issues += derive_judge(data, ad, state)
    elif worker == "triager":
        issues += derive_triager(data, ad, n)
    elif worker == "lookup":
        issues += lookup_issues(nxt, ad / "lookups" / f"{n}.md")
    elif worker == "fixer":
        issues += fixer_issues(nxt, ad, state, n)
    return issues


def plan_result_issues(data, plan, nxt):
    """The planner's result agrees with PLAN.md: its size check, its tier."""
    text = art.read(plan)
    issues = []
    tier = art.risk(text)
    if str(data.get("risk", "")).strip().lower() != tier:
        issues.append(f"risk is {data.get('risk')} but PLAN.md's `Risk:` line says {tier}")
    said = plan_size(text)
    if nxt in ("FITS", "OVERSIZED"):
        if said != nxt:
            issues.append(f"next is {nxt} but PLAN.md's size check says {said or 'nothing'}")
    elif said == "OVERSIZED":
        issues.append("a revision keeps the plan FITS: its size check says OVERSIZED. Set "
                      "it back to FITS and put the size concern in Assumptions")
    if tier != "high" and any(c["id"].startswith("S") for c in art.spec_conditions(plan)):
        issues.append("PLAN.md has Security/Compliance criteria but its `Risk:` is not high")
    return issues


def critic_result_issues(data, path, plan, state):
    """The critic's result agrees with its review file, and doesn't lower the
    tier: the plan's or the run's high risk stays high."""
    if not path.exists():
        return []  # written_files reports it
    review = art.plan_review(path)
    issues = []
    if data.get("next") != review["verdict"]:
        issues.append(f"next is {data.get('next')} but the review's verdict is "
                      f"{review['verdict'] or 'missing'}")
    if as_int(data, "blockers") != len(review["blockers"]):
        issues.append(f"blockers is {data.get('blockers')} but the review lists "
                      f"{len(review['blockers'])}")
    if str(data.get("risk", "")).strip().lower() != review["risk"]:
        issues.append(f"risk is {data.get('risk')} but the review's `Risk:` says "
                      f"{review['risk']}")
    try:
        planned = art.risk(art.read(plan))
    except art.ArtifactError:
        planned = None
    if review["risk"] == "standard" and (planned == "high" or state.get("high_risk")):
        issues.append("the review's `Risk:` is standard but the run is high-risk: the "
                      "critic can't lower the tier; write `Risk: high`")
    return issues


def raise_risk(state, why):
    """Turn high risk and the post-plan gate on; never off. Notes why when it
    changes anything."""
    settings = state.setdefault("settings", {})
    if state.get("high_risk") and settings.get("post_plan_gate"):
        return
    state["high_risk"] = True
    settings["post_plan_gate"] = True
    st.add_note(state, f"high risk, post-plan gate on: {why}")


def settings_changed(state, issued):
    """Whether the fixer of brief `issued` changed the run's settings in
    state.json since its brief, while its fix is still open (a new answer
    at the stop may change them once the fix is dropped)."""
    before = issued.get("settings")
    first = issued.get("artifacts_n", issued.get("n"))  # a retry keeps the first's
    if before is None or not any(o.get("status") == "open" and
                                 (o.get("job") or [None, None])[1] == first
                                 for o in overrides.fixes(state)):
        return False
    return state.get("settings") != before


FIX_SECTIONS = {"FIXED": "Changed", "NEEDS_CONSENT": "Proposal", "CANNOT_FIX": "Why not"}


def fixer_issues(nxt, ad, state, n):
    """A fixer's report must say what it did: for FIXED, name every path it
    changed (repo files, and the run's PLAN.md or acceptance checks as
    `.auto-dev/<path>`; an acceptance check file it edited is committed as a
    new tests commit by `next`); for NEEDS_CONSENT its proposal, for
    CANNOT_FIX why. Whatever a fixer changed without fixing is put back by
    `next`, so only FIXED is held to its list."""
    report = ad / overrides.FIX_DIR / f"fixer-{n}.md"
    if not report.is_file():
        return [f"{report} does not exist: write your report there"]
    text = report.read_text(encoding="utf-8")
    section = FIX_SECTIONS.get(nxt)
    body = (art.find_section(text, section) or "").strip() if section else ""
    issued = next((b for b in state.get("briefs", [])
                   if b["worker"] == "fixer" and b["n"] == n), {})
    wt = state["worktree"]
    if issued.get("fix_tree"):
        head = tree_guard.git(wt, "rev-parse", "HEAD").decode().strip()
        if head != issued["fix_tree"]["head"]:
            return [(f"HEAD moved from {issued['fix_tree']['head'][:12]} to {head[:12]}: "
                     "you never commit, reset or check out. Put HEAD back with "
                     f"`git -C {wt} reset --soft {issued['fix_tree']['head']}`, keeping "
                     "your changes in the working tree")]
    if section and nxt != "FIXED" and body.lower() in ("", "none"):
        return [f"{report.name} has no `## {section}` section saying "
                + ("what else the fix needs" if nxt == "NEEDS_CONSENT" else "why not")]
    if nxt != "FIXED":
        return []
    if art.find_section(text, "Changed") is None:
        return [(f"{report.name} has no `## Changed` section (write `none` in it when you "
                 "changed no file)")]
    scratch = tree_guard.scratch(wt, ad) or ".auto-dev"
    changed = []
    if issued.get("fix_tree"):
        changed += tree_guard.changed(issued["fix_tree"], tree_guard.snapshot(wt, ad))
    if issued.get("artifacts") is not None:
        changed += [f"{scratch}/{p}"
                    for p in overrides.changed_artifacts(ad, issued["artifacts"])]
    if settings_changed(state, issued):
        changed.append(f"{scratch}/state.json")
    listed = set(re.findall(r"`([^`]+)`", body))
    issues = [f"you changed {p} but your report's Changed section does not name it "
              f"(as `{p}`): name every path you changed, with what and why"
              for p in changed if p not in listed]
    issues += amended_issues(state, ad, issued)
    issues += tester_issues(state, ad)
    return issues


def amended_issues(state, ad, issued):
    """After `amend-checks`: each test the fixer dropped is gone from its
    file, and no condition that had a check before the fix is left with none
    and no Not automatable row while PLAN.md still has it."""
    issues = []
    fix = next((o for o in overrides.fixes(state) if o.get("status") == "open"), {})
    before = overrides.backup_dir(ad, issued.get("artifacts_n", issued["n"])) / \
        "acceptance" / "MANIFEST.md"
    if not fix.get("dropped"):
        return issues
    try:
        rows, na_rows = art.manifest(ad / "acceptance" / "MANIFEST.md")
        ids = {c["id"] for c in art.spec_conditions(ad / "PLAN.md")}
        had = {row_id(r["#"]) for r in art.manifest(before)[0]} if before.is_file() else set()
    except art.ArtifactError as exc:
        return [str(exc)]
    names = test_names(rows)
    wt = Path(state["worktree"])
    for rel, name in fix["dropped"]:
        if name in names.get(rel, []):
            continue  # a row names it again: kept, moved or re-added
        others = test_keys(names.get(rel, []))
        keys = [k for k in test_keys([name]) if not any(k in other for other in others)]
        try:
            text = (wt / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        if any(names_test(text, k) for k in keys):
            issues.append(f'you dropped "{name}" from MANIFEST.md but {rel} still holds '
                          "its test: take it out of the file")
    covered = {row_id(r["#"]) for r in rows} | {row_id(r.get("#", "")) for r in na_rows}
    for cid in sorted((had & ids) - covered):
        issues.append(f"condition {cid} has no check left and no Not automatable row: "
                      "remove it from PLAN.md if the instruction says so, add a row with "
                      "`amend-checks --not-automatable`, or return NEEDS_CONSENT")
    return issues


def row_id(cell):
    """A MANIFEST.md row's condition id: `3 (Edge)` is 3's."""
    return (cell.strip().split() or [""])[0].split("(")[0]


def names_test(text, key):
    """Whether source text names a test `key`: as a quoted string, or, for a
    name shaped like a function name (`testAdds`, `test_adds`), as a whole
    word. A plain lowercase word is only found quoted: as a word it would
    match inside another test's name."""
    if any(f"{q}{key}{q}" in text for q in ('"', "'", "`")):
        return True
    function = re.fullmatch(r"\w+", key) and re.search(r"[A-Z_0-9]", key)
    return bool(function) and re.search(rf"(?<!\w){re.escape(key)}(?!\w)", text) is not None


# A decline's line, under any markdown a model wraps it in: `OUT_OF_SCOPE:`,
# `**OUT_OF_SCOPE**:`, `> OUT_OF_SCOPE:`. The colon keeps a symbol such as
# OUT_OF_SCOPE_ERROR in a real answer from reading as a decline.
DECLINE_RE = re.compile(r"[*_`#>\s]*OUT_OF_SCOPE[*_`]*\s*:")
ASK_INSTEAD_RE = re.compile(r"[*_`#>\-\s]*ask instead\b", re.IGNORECASE)
FILE_LINE_RE = re.compile(r"\S\.\w+:\d")


def lookup_issues(nxt, answer):
    """A lookup's `next` must agree with its answer file: an answer for
    ANSWERED, and for OUT_OF_SCOPE only the `OUT_OF_SCOPE:` line (and an
    `ask instead:` line), since the orchestrator acts on what a lookup says
    without checking it. Blank lines and code fences don't count."""
    text = answer.read_text(encoding="utf-8").strip() if answer.is_file() else ""
    lines = [line for line in text.splitlines()
             if line.strip() and not line.strip().startswith("```")]
    declined = bool(lines) and DECLINE_RE.match(lines[0]) is not None
    if nxt == "ANSWERED" and not text:
        return [f"next is ANSWERED but {answer} holds no answer"]
    if nxt == "ANSWERED" and declined:
        return [(f"next is ANSWERED but {answer} starts with OUT_OF_SCOPE: return "
                 "`next: OUT_OF_SCOPE`, or answer the question")]
    if nxt != "OUT_OF_SCOPE":
        return []
    if not declined:
        return [f"next is OUT_OF_SCOPE but {answer} holds no `OUT_OF_SCOPE: <why>` line"]
    rest = [line for line in lines[1:] if not ASK_INSTEAD_RE.match(line)]
    if rest:
        return [(f"next is OUT_OF_SCOPE but {answer} holds more than the `OUT_OF_SCOPE:` "
                 "line: decline a verdict question in one line, with no part of an answer")]
    if FILE_LINE_RE.search(lines[0]):
        return [(f"next is OUT_OF_SCOPE but {answer}'s decline cites a `file:line`: decline "
                 "a verdict question without reading the code, and give no part of an answer")]
    return []


def coder_bound(path, ad, what):
    """Problems with a required-changes file the coder gets unedited."""
    if not path.exists():
        return [f"{what}: {path} does not exist"]
    return [f"{what}: {p}" for p in check_corrections(art.read(path))]


def derive_verifier(nxt, ad):
    issues = []
    corrections = ad / "evidence" / "corrections.md"
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
    n = state.get("phase6", {}).get("review_pass") or 1
    folder = ad / "review" / f"pass-{n}"
    if (folder / "findings.md").exists() and not (folder / "JUDGMENT.md").exists():
        issues.append(f"no {folder / 'JUDGMENT.md'}: write your calls there and run "
                      "`autodev.py review-build`, which writes CODE_REVIEW.md")
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
        issues += coder_bound(ad / "review" / f"pass-{n}" / "corrections.md", ad,
                              f"review/pass-{n}/corrections.md")
    return issues


def derive_reviewer(data, ad, state):
    """A standard-risk pass's one reviewer: its counts and `next` against the
    CODE_REVIEW.md that `review-build --solo` wrote and its SECURITY_REVIEW.md."""
    nxt = data.get("next")
    n = state.get("phase6", {}).get("review_pass") or 1
    folder = ad / "review" / f"pass-{n}"
    issues = []
    if not (folder / "JUDGMENT.md").exists():
        issues.append(f"no {folder / 'JUDGMENT.md'}: write your calls there and run "
                      "`autodev.py review-build --solo`, which writes CODE_REVIEW.md")
    open_rows = count_open(art.read(ad / "CODE_REVIEW.md"))
    if as_int(data, "must_fix_open") != open_rows:
        issues.append(f"must_fix_open is {data.get('must_fix_open')} but CODE_REVIEW.md "
                      f"has {open_rows} open must-fix rows")
    security = security_open(art.read(ad / "SECURITY_REVIEW.md"))
    if as_int(data, "must_fix") != security:
        issues.append(f"must_fix is {data.get('must_fix')} but SECURITY_REVIEW.md has "
                      f"{security} open must-fix findings")
    want = "MUST_FIX" if open_rows or security else "CLEAN"
    if nxt != want:
        issues.append(f"next is {nxt} but the reports hold {open_rows} open must-fix "
                      f"code finding(s) and {security} security one(s), which is {want}")
    if open_rows:
        issues += coder_bound(folder / "corrections.md", ad,
                              f"review/pass-{n}/corrections.md")
    if security:
        issues += coder_bound(ad / "review" / "security-corrections.md", ad,
                              "review/security-corrections.md")
    return issues


def derive_security(data, ad):
    """A high-risk pass's security reviewer: `must_fix` and `pre_existing`
    against SECURITY_REVIEW.md, since `next` sends the judge to verify only
    when they say there is something to verify."""
    text = art.read(ad / "SECURITY_REVIEW.md")
    issues = []
    must, pending = security_open(text), for_the_user_pending(text)
    if as_int(data, "must_fix") != must:
        issues.append(f"must_fix is {data.get('must_fix')} but SECURITY_REVIEW.md has "
                      f"{must} open must-fix findings")
    if as_int(data, "pre_existing") != pending:
        issues.append(f"pre_existing is {data.get('pre_existing')} but SECURITY_REVIEW.md "
                      f"has {pending} pre-existing finding(s) for the user, Verified "
                      "pending")
    want = "MUST_FIX" if must else "CLEAN"
    if data.get("next") != want:
        issues.append(f"next is {data.get('next')} but SECURITY_REVIEW.md has {must} open "
                      f"must-fix findings, which is {want}")
    return issues


def for_the_user_pending(text):
    """SECURITY_REVIEW.md's pre-existing findings for the user that the judge
    has yet to verify."""
    _, rows = art.first_table(art.find_section(text, "Findings") or "",
                              ("ID", "Verdict", "Status"), "SECURITY_REVIEW.md")
    return sum(1 for r in rows if r["Verdict"].strip().lower() == "for the user"
               and r.get("Verified", "").strip().lower() == "pending")


def security_open(text):
    """SECURITY_REVIEW.md's open must-fix findings (a refuted one aside)."""
    _, rows = art.first_table(art.find_section(text, "Findings") or "",
                              ("ID", "Verdict", "Status"), "SECURITY_REVIEW.md")
    return sum(1 for r in rows if r["Verdict"].strip().lower() == "must-fix"
               and r["Status"].strip().lower().startswith("open")
               and r.get("Verified", "").strip().lower() != "refuted")


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
    token, message, issues, data = record_job(state, args.worker, args.n)
    st.save(args.dir, state)
    if issues:
        fields = {"issue": issues}
        if data is not None:
            fields["returned"] = json.dumps(data)
        emit(args.json, token, f"{args.worker}-{args.n}: {message}; run `autodev.py "
             "next`: it re-spawns the worker with a brief whose previous_issues carries "
             "these issues. Don't guess",
             **fields)
        return FAILED
    emit(args.json, "RECORDED", f"{args.worker}-{args.n}", status=data.get("status"),
         next=data.get("next", ""))
    return 0


def record_job(state, worker, n):
    """Record job <worker>-<n>'s return into `state` (the caller saves it).
    Returns (token, message, issues, data): RECORDED with no issues, or the
    refusal (MISSING, MALFORMED, MISMATCH), whose issues are saved for the retry."""
    ad = Path(state["artifact_dir"])
    data = None
    try:
        moved = tree_issues(state, ad, worker, n)
        try:
            data = load_return(ad, worker, n)
        except Refused as exc:
            if moved:
                raise Refused(exc.args[0], exc.args[1], moved + exc.args[2]) from None
            raise
        try:
            issues = moved + derive(worker, data, ad, state, n)
        except art.ArtifactError as exc:
            issues = moved + [str(exc)]
        if issues:
            raise Refused("MISMATCH", "the return and the artifacts disagree", issues)
    except Refused as exc:
        token, message, issues = exc.args
        if job(worker, n) not in state.get("refused", {}):  # not the same return again
            state.setdefault("refusals", []).append(
                {"worker": worker, "n": n, "token": token, "seq": st.seq(state)})
        state.setdefault("refused", {})[job(worker, n)] = issues
        st.add_note(state, f"{worker} #{n} refused ({token})")
        return token, message, issues, data
    record_ok(state, ad, worker, n, data)
    return "RECORDED", f"{worker}-{n}", [], data


def tree_issues(state, ad, worker, n):
    """Whether job <worker>-<n>, which never changes the repo, changed it
    (tree_guard). Skipped when the change could be someone else's: the job was
    already recorded or replaced, left no result file yet, a worker that does
    change the repo was out while it ran, or the setup commands had not
    finished when it was briefed. A brief from before the check holds no
    snapshot."""
    issued = next((b for b in state.get("briefs", [])
                   if b["worker"] == worker and b["n"] == n), {})
    if not issued.get("tree") or issued.get("retried_as") is not None:
        return []
    if any(e["worker"] == worker and e["n"] == n for e in state.get("log") or []):
        return []
    if writer_out(state, issued) or setup_running(state, ad, issued):
        return []
    result = ad / "returns" / f"{worker}-{n}.json"
    if not result.is_file():
        return []  # it may still be running; `record` refuses it as MISSING
    return tree_guard.issues(worker, n, issued["tree"], state["worktree"], ad,
                             result.stat().st_mtime)


def writer_out(state, issued):
    """Whether a brief for a worker outside tree_guard.GUARDED was out at any
    time between `issued` and now: briefed since, or briefed before and not
    yet recorded or replaced when `issued` was."""
    seq = issued.get("seq", 0)
    briefs_ = state.get("briefs", [])
    by_job = {(b["worker"], b["n"]): b for b in briefs_}
    logged = {(e["worker"], e["n"]): e.get("seq", 0) for e in state.get("log") or []}
    for b in briefs_:
        if b["worker"] in tree_guard.GUARDED:
            continue
        if b.get("seq", 0) > seq:
            return True
        done = logged.get((b["worker"], b["n"]))
        if done is not None and done < seq:
            continue
        again = by_job.get((b["worker"], b.get("retried_as")))
        if again is not None and again.get("seq", 0) < seq:
            continue
        return True
    return False


def setup_running(state, ad, issued):
    """Whether init's setup commands were still running when `issued` was
    briefed: they write setup.json when they end."""
    if not (state.get("init") or {}).get("setup_pid"):
        return False
    done = ad / "setup.json"
    if not done.is_file():
        return True
    try:
        briefed = datetime.fromisoformat(issued["at"]).timestamp()
    except (KeyError, TypeError, ValueError):
        return True
    return done.stat().st_mtime > briefed


def record_ok(state, ad, worker, n, data):
    """Log an accepted return, and what it settles in state."""
    state.get("refused", {}).pop(job(worker, n), None)
    ok = data.get("status") == "ok"
    if ok and worker == "planner" and data.get("next") in ("FITS", "OVERSIZED"):
        state["size"] = data["next"]
        if state.get("high_risk") is None:
            state["high_risk"] = False
        if data["next"] == "OVERSIZED":
            st.set_phase(state, 2, "stopped", "OVERSIZED")
            for number in (3, 4, 5, 6):
                st.set_phase(state, number, "n/a", "")
    # The tier only goes up: the planner proposes it, the critic confirms or
    # raises it, and `next` re-checks it from the diff after the build.
    if ok and worker in ("planner", "plan-critic") and state.get("size") == "FITS" and \
            str(data.get("risk", "")).strip().lower() == "high":
        raise_risk(state, f"the {'plan critic' if worker == 'plan-critic' else 'plan'} "
                   "says the risk is high")
    issued = next((b for b in state.get("briefs", [])
                   if b["worker"] == worker and b["n"] == n), {})
    log = state.setdefault("log", [])
    entry = {"worker": worker, "n": n, "mode": issued.get("mode"),
             "sets": issued.get("sets", {}), "status": data.get("status"),
             "next": data.get("next", ""), "data": data, "seq": st.seq(state)}
    again = next((i for i, e in enumerate(log)
                  if e["worker"] == worker and e["n"] == n), None)
    if again is None:
        log.append(entry)
    else:  # recorded again: it keeps its place, so `next` reads the same order
        entry["seq"] = log[again].get("seq", entry["seq"])
        log[again] = entry
    st.add_note(state, f"{worker} #{n} returned {data.get('status')} "
                f"{data.get('next', '')}".rstrip())


# ---------------------------------------------------------------- check-artifact

def check_file(path):
    """Problems with one artifact, by its name; [] when it follows its template."""
    path = Path(path)
    name, parent = path.name, path.parent.name
    try:
        text = art.read(path)
    except art.ArtifactError as exc:
        return [str(exc)]
    try:
        if parent == "spec-problems":
            return spec_problem_lines(path, run_spec(path))
        if parent == "deviations":
            return [] if deviation_lines(path) else [
                "no `- step <n>: <what you built instead, and why>` line"]
        if name == "PLAN.md":
            return check_plan(path, text)
        if parent == "plan-review":
            return art.plan_review(path)["problems"]
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
        if re.match(r"R\d\.md$", name):
            from .judgment import parse_report
            return need_sections(text, ("Findings", "Security leads", "Pre-existing")) + \
                parse_report(text)["problems"]
        if re.match(r"VOTES-R\d\.md$", name):
            art.first_table(text, ("Finding", "Vote", "Reason"), str(path))
            return []
        if name.endswith("corrections.md") or parent == "triage":
            return check_corrections(text)
        if parent == "returns" and name.endswith(".json"):
            data = json.loads(text)
            return return_problems(data.get("worker", "") if isinstance(data, dict) else "",
                                   data)
    except art.ArtifactError as exc:
        return [str(exc)]
    except ValueError as exc:
        return [f"not valid JSON: {exc}"]
    return [f"no template is known for {name}"]


def run_spec(path):
    """The run's PLAN.md for a file under .auto-dev/ (up to two levels down)."""
    for parent in list(Path(path).resolve().parents)[:3]:
        if (parent / "PLAN.md").is_file():
            return parent / "PLAN.md"
    return None


def plan_size(text):
    """The first word of PLAN.md's Size check, uppercased (FITS, OVERSIZED), or ""."""
    size = (art.find_section(text, "Size check") or "").split()
    return size[0].strip("*_`.,:;—-").upper() if size else ""


def plan_has_steps(text):
    """Whether PLAN.md has every step heading (an OVERSIZED plan may have none)."""
    heads = {ln.strip() for ln in text.splitlines() if ln.startswith("## ")}
    return all(h in heads for h in STEP_HEADINGS)


def check_plan(path, text):
    """PLAN.md: its headings in order (an OVERSIZED plan may stop at its size
    check), each condition's lines, its `Risk:` and `Review effort:` lines."""
    heads = [ln.strip() for ln in text.splitlines() if ln.startswith("## ")]
    oversized = plan_size(text) == "OVERSIZED"
    want = list(PLAN_HEADINGS) + ([] if oversized else list(STEP_HEADINGS))
    problems = [] if [h for h in heads if h in want] == want else [
        f"headings must be, in order: {', '.join(want)} (found: {', '.join(heads)})"]
    tier = art.risk(text)
    if tier not in art.RISKS:
        problems.append(f"`Risk:` must be {' or '.join(art.RISKS)} (found: {tier or 'nothing'})")
    effort = art.review_effort(text)
    if not oversized and effort not in art.REVIEW_EFFORTS:
        problems.append(f"`Review effort:` must be {' or '.join(art.REVIEW_EFFORTS)}"
                        f" (found: {effort or 'nothing'})")
    return problems + check_conditions(path)


def check_conditions(path):
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
