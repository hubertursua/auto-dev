"""autodev.py quality-gate — run the profile's whole quality gate in the run's
worktree and write its reports.

Usage:
    autodev.py quality-gate --dir <artifact-dir> [--timeout <seconds>] [--json]

The coder runs the quality gate to green before it returns; `next` confirms it
before anything is pushed by having the orchestrator run this, so no worker is
spawned for it. It runs each check of the profile's `gate` (state.json's
settings, confirmed in Phase 1) in order, exactly as written, in the worktree
(the same runner as `autodev.py run gate <n>`), and writes one
<artifact-dir>/lint/<REPORT>.md per check in the shape of templates/lint.md:
the command, pass or fail, the last 20 lines of its output and the `Tree:`
line of the code it checked. Every check runs, even after one fails. Each
check's whole output is saved under <artifact-dir>/tmp/run/.

A check that rewrites the code (a formatter that writes) changes the tree: the
gate then runs once more on the rewritten code, and a tree that changes again
is RED (something rewrites the code on every run). --timeout stops each check
after that many seconds; a check stopped fails.

It records the run in state.json (`gate_runs`: the tree, GREEN or RED, the
failing reports), which `next` reads. It never commits, stages or edits a file
itself.

Prints one token, then one line per check (`pass` or `fail`, the report, the
command):
    GREEN: every check passed on tree <hash>
    RED: <k> of <n> checks failed on tree <hash>

Exit codes:
    0  GREEN
    1  RED: the failing reports are listed
    2  could not run (no state, no gate, no worktree, a command that could not
       start)
"""

import json
from pathlib import Path

from . import cmd_run
from . import state as st
from .cmd_review import print_tree
from .output import CANNOT_RUN, FAILED, OK, Fail

TAIL = 20
FENCE = "````"


def add_arguments(parser):
    parser.add_argument("--dir", required=True, help="the run's .auto-dev/")
    parser.add_argument("--timeout", type=float,
                        help="stop each check after this many seconds (it fails)")


def run_all(ad, worktree, gate, timeout):
    """[(report, command, passed, tail)] for one run of every check."""
    results = []
    for n, check in enumerate(gate, 1):
        command = cmd_run.command_for(n, check, worktree, None)
        path = cmd_run.output_file(ad, None, f"gate-{n}")
        code, _seconds = cmd_run.execute(command, worktree, path, timeout)
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        tail = lines[-TAIL:]
        if code is None:
            tail = tail + [f"(stopped after {timeout:g}s)"]
        results.append((str(check.get("report") or f"GATE-{n}.md"), command,
                        code == 0, tail))
    return results


def report_text(report, command, passed, tail, tree):
    name = Path(report).stem.upper()
    status = "pass" if passed else "fail"
    return "\n".join([
        f"# {name} — {status}", "",
        f"- **Command:** `{command}`",
        f"- **Final status:** {status}",
        "- **Runs:** 1",
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
    before = print_tree(str(worktree))
    results = run_all(ad, worktree, gate, args.timeout)
    tree = print_tree(str(worktree))
    rewrites = 0
    if tree != before:  # a check rewrote the code: check what it wrote
        rewrites = 1
        before = tree
        results = run_all(ad, worktree, gate, args.timeout)
        tree = print_tree(str(worktree))
    changing = tree != before
    lint = ad / "lint"
    lint.mkdir(parents=True, exist_ok=True)
    for report, command, passed, tail in results:
        (lint / report).write_text(report_text(report, command, passed and not changing,
                                               tail, tree), encoding="utf-8")
    failing = [r for r, _, passed, _ in results if not passed or changing]
    result = "RED" if failing else "GREEN"
    state.setdefault("gate_runs", []).append(
        {"seq": st.seq(state), "tree": tree, "result": result, "failing": failing,
         "at": st.now()})
    why = " (the code changed on every run)" if changing else (
        " (a check rewrote the code; the gate ran again on it)" if rewrites else "")
    st.add_note(state, f"quality gate {result} on tree {tree[:12]}{why}"
                + (f": {', '.join(failing)} fail" if failing else ""))
    st.save(ad, state)
    lines = [(("pass" if passed and not changing else "fail"), report, command)
             for report, command, passed, _ in results]
    message = (f"every check passed on tree {tree}" if not failing else
               f"{len(failing)} of {len(results)} checks failed on tree {tree}{why}")
    if args.json:
        print(json.dumps({"result": result, "message": message, "tree": tree,
                          "failing": failing,
                          "checks": [{"status": s, "report": r, "command": c}
                                     for s, r, c in lines]}, indent=2, sort_keys=True))
    else:
        print(f"{result}: {message}")
        for status, report, command in lines:
            print(f"  {status}: {ad / 'lint' / report} — `{command}`")
    return FAILED if failing else OK
