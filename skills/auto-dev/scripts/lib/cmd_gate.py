"""autodev.py quality-gate — run the profile's quality gate in the run's
worktree (its test checks only on the change's tests when CI is watched) and
write its reports.

Usage:
    autodev.py quality-gate --dir <artifact-dir> [--timeout <seconds>] [--json]

The coder runs the quality gate to green before it returns; `next` confirms it
before anything is pushed by having the orchestrator run this, so no worker is
spawned for it. It runs each check of the profile's `gate` (state.json's
settings, confirmed in Phase 1) in order, exactly as written, in the worktree
(the same runner as `autodev.py run gate <n>`), and writes one
<artifact-dir>/lint/<REPORT>.md per check in the shape of templates/lint.md
(removing the report of a check the gate no longer has):
the command, pass, fail or skipped, its scope, the last 20 lines of its output
and the `Tree:` line of the code it checked. Every check runs, even after one
fails. Each check's whole output is saved under <artifact-dir>/tmp/run/.

CI is the one full run of the test suite when it is watched: the run's CI
provider is neither `none` nor `gitlab` (which `ci-watch` can't read) and its
last CI watch didn't end `unavailable` or `timeout`. Then each non-test check
runs whole, and each `kind: test` check that has a `files` form runs only on
the change's test files: the test files the branch added or changed since its
cut, committed or not, that still exist, plus the acceptance check files
MANIFEST.md names. A `kind: test` check with no `files` form, or one when the
change has no test file, is not run: its report says `skipped` and CI runs it.
When CI isn't watched, or the cut can't be found, every check runs whole.

The time each whole run that finished took is saved in
<artifact-dir>/tmp/run/timings.json, keyed by its command: `autodev.py run`
stops a check at twice that time (at least 600 s) when given no --timeout.

A check that rewrites the code (a formatter that writes) changes the tree: the
gate then runs once more on the rewritten code, and a tree that changes again
is RED (something rewrites the code on every run). --timeout stops each check
after that many seconds; a check stopped fails.

It records the run in state.json (`gate_runs`: the tree, GREEN or RED, the
failing reports, a digest of the gate it ran, the reports run on the change's
tests (`scoped`) and left to CI (`skipped`), and whether CI was watched
(`ci_watched`)), which `next` reads: a run counts only for that tree and that
gate. It never commits, stages or edits a file itself.

Prints one token, then one line per check (`pass`, `fail` or `skipped`, the
report, the command, and for a scoped or skipped check why):
    GREEN: every check passed on tree <hash>
    GREEN: every check run passed on tree <hash>; <k> left to CI
    RED: <k> of <n> checks failed on tree <hash>
      pass: <report> — `<command>` (the change's tests; CI runs the whole check)
      skipped: <report> — `<command>` (no scoped form | no test file changed; CI runs it)
With --json, `result`, `message`, `tree`, `failing` and `checks` (each with
`status`, `report`, `command` and `scope`: `whole`, `files` or `skipped`).

Exit codes:
    0  GREEN
    1  RED: the failing reports are listed
    2  could not run (no state, no gate, no worktree, a command that could not
       start)
"""

import hashlib
import json
from pathlib import Path

from . import cmd_run
from . import state as st
from .cmd_review import print_tree
from .output import CANNOT_RUN, FAILED, OK, Fail
from .proc import CommandError, git
from .testfiles import is_test_file

TAIL = 20
FENCE = "````"
# CI providers `ci-watch` can't read, and the watch results that saw no CI run.
UNWATCHED_CI = ("none", "gitlab")
UNWATCHED_STATUS = ("unavailable", "timeout")
SCOPED_NOTE = " (the change's tests; CI runs the whole check)"


def gate_key(state):
    """A digest of the profile's gate as state.json holds it: a run of another
    gate (a check added, a command the fixer changed) says nothing of this one."""
    text = json.dumps(state["settings"].get("gate") or [], sort_keys=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def add_arguments(parser):
    parser.add_argument("--dir", required=True, help="the run's .auto-dev/")
    parser.add_argument("--timeout", type=float,
                        help="stop each check after this many seconds (it fails)")


def ci_watched(state):
    """Whether CI runs the whole test suite on the push and the run watches it:
    a provider `ci-watch` can read, and no last watch that saw no CI run."""
    ci = str(state["settings"].get("ci") or "none").lower()
    status = (state.get("phase6", {}).get("ci") or {}).get("status")
    return ci not in UNWATCHED_CI and status not in UNWATCHED_STATUS


def change_test_files(ad, state, worktree):
    """The change's test files, sorted: the test files the branch added or
    changed since its cut (committed or not) that still exist, and the
    acceptance check files; None when the cut can't be found."""
    from .cmd_work import check_files, cut_commit  # cmd_work imports cmd_review
    wt = str(worktree)
    try:
        cut = cut_commit(wt, state["repo"]["base"])
        names = git(wt, "diff", "--name-only", "--no-renames", "-z", cut).split("\0")
        names += git(wt, "ls-files", "--others", "--exclude-standard", "-z").split("\0")
    except (Fail, CommandError, KeyError):
        return None
    found = {p for p in names if p and is_test_file(p) and not p.startswith(".auto-dev/")}
    found |= set(check_files(ad))
    return sorted(p for p in found if (Path(worktree) / p).is_file())


def plan_checks(ad, state, worktree, gate):
    """[(mode, detail)] per check, decided once before the runs: ("whole", None),
    ("files", [paths]) or ("skip", why)."""
    watched = ci_watched(state)
    files = change_test_files(ad, state, worktree) if watched else None
    plan = []
    for check in gate:
        if not watched or files is None or check.get("kind") != "test":
            plan.append(("whole", None))
        elif not cmd_run.has_form(check, "files"):
            plan.append(("skip", "no scoped form"))
        elif not files:
            plan.append(("skip", "no test file changed"))
        else:
            plan.append(("files", files))
    return plan


def scope_text(mode, detail):
    if mode == "files":
        count = f"{len(detail)} file" + ("" if len(detail) == 1 else "s")
        return f"the change's tests ({count}); CI runs the whole check"
    if mode == "skip":
        return f"not run: {detail}; CI runs it"
    return "whole"


def run_all(ad, worktree, gate, timeout, plan):
    """[(report, command, status, tail, mode, detail)] for one run of every
    check: status `pass`, `fail` or `skipped`."""
    results = []
    for n, (check, (mode, detail)) in enumerate(zip(gate, plan), 1):
        report = str(check["report"])
        if mode == "skip":
            command = cmd_run.command_for(n, check, worktree, None)
            results.append((report, command, "skipped", ["(not run: CI runs this check)"],
                            mode, detail))
            continue
        command = cmd_run.command_for(n, check, worktree,
                                      detail if mode == "files" else None)
        path = cmd_run.output_file(ad, None, f"gate-{n}")
        code, seconds = cmd_run.execute(command, worktree, path, timeout)
        if code is not None and mode == "whole":
            cmd_run.save_timing(ad, command, seconds, "quality-gate")
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        tail = lines[-TAIL:]
        if code is None:
            tail = tail + [f"(stopped after {timeout:g}s)"]
        results.append((report, command, "pass" if code == 0 else "fail", tail, mode,
                        detail))
    return results


def report_text(report, command, status, tail, tree, scope):
    name = Path(report).stem.upper()
    return "\n".join([
        f"# {name} — {status}", "",
        f"- **Command:** `{command}`",
        f"- **Final status:** {status}",
        f"- **Scope:** {scope}",
        f"- **Runs:** {0 if status == 'skipped' else 1}",
        f"- **Tree:** {tree}", "",
        "## Fixed to get here",
        "- none: run by `autodev.py quality-gate`, which changes no file", "",
        "## Output tail (final run)",
        FENCE, *tail, FENCE, "",
        "**Suppressions:** none", ""])


def main(args):
    ad = Path(args.dir)
    try:
        state = st.load(ad)
    except st.StateError as exc:
        raise Fail(str(exc), CANNOT_RUN, "ERROR") from None
    worktree = Path(state["worktree"])
    if not worktree.is_dir():
        raise Fail(f"the worktree {worktree} does not exist", CANNOT_RUN, "ERROR")
    gate = state["settings"].get("gate") or []
    if not gate:
        raise Fail("the profile has no quality gate", CANNOT_RUN, "ERROR")
    if args.timeout is not None and args.timeout <= 0:
        raise Fail("--timeout must be more than 0", CANNOT_RUN, "ERROR")
    watched = ci_watched(state)
    before = print_tree(str(worktree))
    plan = plan_checks(ad, state, worktree, gate)
    results = run_all(ad, worktree, gate, args.timeout, plan)
    tree = print_tree(str(worktree))
    rewrites = 0
    if tree != before:  # a check rewrote the code: check what it wrote
        rewrites = 1
        before = tree
        results = run_all(ad, worktree, gate, args.timeout, plan)
        tree = print_tree(str(worktree))
    changing = tree != before
    # The code changed on every run: no check that ran can pass.
    results = [(r, c, "fail" if changing and s == "pass" else s, t, m, d)
               for r, c, s, t, m, d in results]
    lint = ad / "lint"
    lint.mkdir(parents=True, exist_ok=True)
    for old in lint.glob("*.md"):  # a check the gate no longer has: its report goes
        if old.name not in {r[0] for r in results}:
            old.unlink()
    for report, command, status, tail, mode, detail in results:
        (lint / report).write_text(report_text(report, command, status, tail, tree,
                                               scope_text(mode, detail)), encoding="utf-8")
    failing = [r for r, _, status, _, _, _ in results if status == "fail"]
    scoped = [r for r, _, _, _, mode, _ in results if mode == "files"]
    skipped = [r for r, _, _, _, mode, _ in results if mode == "skip"]
    result = "RED" if failing else "GREEN"
    state.setdefault("gate_runs", []).append(
        {"seq": st.seq(state), "tree": tree, "result": result, "failing": failing,
         "gate": gate_key(state), "scoped": scoped, "skipped": skipped,
         "ci_watched": watched, "at": st.now()})
    why = " (the code changed on every run)" if changing else (
        " (a check rewrote the code; the gate ran again on it)" if rewrites else "")
    split = [f"{', '.join(scoped)} scoped to the change"] if scoped else []
    split += [f"{', '.join(skipped)} left to CI"] if skipped else []
    st.add_note(state, f"quality gate {result} on tree {tree[:12]}{why}"
                + (f" ({', '.join(split)})" if split else "")
                + (f": {', '.join(failing)} fail" if failing else ""))
    st.save(ad, state)
    if failing:
        message = f"{len(failing)} of {len(results)} checks failed on tree {tree}{why}"
    elif skipped:
        message = f"every check run passed on tree {tree}; {len(skipped)} left to CI"
    else:
        message = f"every check passed on tree {tree}"
    scopes = {"whole": "whole", "files": "files", "skip": "skipped"}
    if args.json:
        print(json.dumps({"result": result, "message": message, "tree": tree,
                          "failing": failing,
                          "checks": [{"status": s, "report": r, "command": c,
                                      "scope": scopes[m]}
                                     for r, c, s, _, m, _ in results]},
                         indent=2, sort_keys=True))
    else:
        print(f"{result}: {message}")
        for report, command, status, _, mode, detail in results:
            note = (SCOPED_NOTE if mode == "files" else
                    f" ({detail}; CI runs it)" if mode == "skip" else "")
            print(f"  {status}: {ad / 'lint' / report} — `{command}`{note}")
    return FAILED if failing else OK
