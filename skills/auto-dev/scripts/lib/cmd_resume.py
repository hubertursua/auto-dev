"""autodev.py resume — find the run to continue, if any.

Usage:
    autodev.py resume [--repo <the directory you are in>] [--task "<ticket or task>"] [--json]

Scans every tree `git worktree list` names for `.auto-dev/state.json` (a run;
schema 4 is a 4.x run) or a `WORK_LOG.md` with no state.json (a 3.x run), and
prints one decision on the first line:

    FRESH            --task names no run here: start a fresh run (init)
    RESUME <tree>    continue this run: its stage (and that stage's runbook,
                     references/<stage>.md), phase and status follow. It
                     records that a new session holds the run, and un-holds a
                     phase held at a gate, so `next` asks that gate again. A
                     stop on a worker (blocked, failed twice, never returned)
                     is lifted: `next` spawns that worker again. A session
                     that ended at a checkpoint (`handoff --checkpoint`) lifts
                     nothing: nothing was stopped
    ASK              ask the user: several runs fit, a run only nearly matches
                     the task (NEAR-MISS), or no task was given and no run is open
    FINISHED <tree>  the run the task names already finished or was stopped (a
                     run stopped on a step the user can still override, an
                     OVERSIZED task, is RESUMEd instead: `next` asks how to go on;
                     so is a finished run whose worktree the user chose to remove
                     and is still there: `next` gives the `cleanup-worktree`
                     command, as its `action:` line says)
    OLD-VERSION <tree>  the run was started on auto-dev 3.x or 4.x, which this
                     version does not resume: finish it on that version (3.9,
                     or 4.27), or remove its worktree and start again

Pass --task whenever the user states the task (its Jira key or what it does);
omit it on a bare `auto-dev continue` or a loose name like "the dark-mode run".
Without --task, the run in the worktree --repo is in wins: starting inside a
run's worktree decides on that run (RESUME, FINISHED or OLD-VERSION) even when
others are open.
Being given a task never resumes a run that doesn't match it.

A run whose setup is not done is open: RESUME at Phase 1, with an action
saying `next` finishes setup (it waits for it, or runs it again once the
cause is fixed).

Exit codes:
    0  a decision was printed
    2  could not run (not a git checkout, git failed), or a run's state.json is
       unreadable and no readable run matches (`ERROR` names the tree) — not a
       decision
"""

import json
from pathlib import Path

from . import state as st
from .output import CANNOT_RUN, Fail, emit
from .proc import CommandError, git
from .taskmatch import FIELD_RE, NEAR_MISS, task_matches


def add_arguments(parser):
    parser.add_argument("--repo", default=".", help="any checkout of the repo")
    parser.add_argument("--task", default="", help="the ticket key or task text")


def worktrees(repo):
    try:
        out = git(str(Path(repo).resolve()), "worktree", "list", "--porcelain")
    except CommandError as exc:
        raise Fail(f"git worktree list failed: {exc}", CANNOT_RUN, "ERROR") from None
    return [line[len("worktree "):] for line in out.splitlines()
            if line.startswith("worktree ")]


def old_ledger_fields(path):
    fields = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return fields
    for line in lines:
        if line.startswith("## "):
            break
        if line.lstrip().startswith("- **"):
            for name, value in FIELD_RE.findall(line):
                fields[name.strip()] = value.strip()
    return fields


def candidates(repo):
    """(kind, tree, fields, state) for every tree holding a run."""
    found = []
    for tree in worktrees(repo):
        artifact_dir = Path(tree) / ".auto-dev"
        if (artifact_dir / st.STATE_FILE).exists():
            old = old_state_fields(artifact_dir)
            if old is not None:
                found.append(("old", tree, old, None))
                continue
            try:
                state = st.load(artifact_dir)
            except st.StateError as exc:
                found.append(("broken", tree, {"error": str(exc)}, None))
                continue
            fields = {"Task": state["task"].get("text", ""),
                      "Ticket": st.ticket_line(state["task"])}
            found.append(("run", tree, fields, state))
        elif (artifact_dir / st.LEDGER).exists():
            found.append(("old", tree, {**old_ledger_fields(artifact_dir / st.LEDGER),
                                        "version": "3.x"}, None))
    return found


def old_state_fields(artifact_dir):
    """The task fields of a 4.x run's state.json (schema 4), or None for any
    other file: this version's runs, and ones `st.load` reports as unreadable."""
    try:
        state = json.loads((artifact_dir / st.STATE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(state, dict) or state.get("schema") != 4:
        return None
    task = state.get("task") if isinstance(state.get("task"), dict) else {}
    phases = state.get("phases") if isinstance(state.get("phases"), dict) else {}
    statuses = [p.get("status") for p in phases.values() if isinstance(p, dict)]
    ended = bool(statuses) and (all(s in st.COMPLETE for s in statuses)
                                or "stopped" in statuses)
    return {"Task": task.get("text", ""), "Ticket": st.ticket_line(task), "version": "4.x",
            "ended": ended}


def current_tree(repo):
    """The root of the checkout `repo` is in, resolved; None when it is in
    none (a bare repo, or inside .git/)."""
    try:
        top = git(str(Path(repo).resolve()), "rev-parse", "--show-toplevel")
    except CommandError:
        return None
    return Path(top.strip()).resolve() if top.strip() else None


def describe(tree, state):
    opened = st.first_open_phase(state)
    if opened is None and st.cleanup_pending(state):
        return {"tree": tree, "run": st.run_state(state),
                "stage": st.STAGE_NAMES["ship"], "runbook": "references/ship.md",
                "task": state["task"].get("text", ""),
                "action": ("the user chose to remove the worktree and it is still here: "
                           "run `next`, which gives the `cleanup-worktree` command")}
    if opened is None:
        return {"tree": tree, "run": st.run_state(state)}
    number, status = opened
    info = {"tree": tree, "run": st.run_state(state),
            "stage": st.STAGE_NAMES[st.STAGES[number]],
            "runbook": f"references/{st.STAGES[number]}.md",
            "phase": f"{number} — {st.PHASE_NAMES[number]}", "status": status,
            "task": state["task"].get("text", ""),
            "budget": f"{state['budget']['remaining']} of {state['budget']['total']}"}
    if info["run"] == "stopped" and st.resumable(state):
        info["action"] = ("the run stopped on a step the user can override: run `next`, "
                          "which asks how to go on")
    if number == 1 and state["init"].get("setup") != "done":
        info["setup"] = state["init"].get("setup", "pending")
        info["action"] = ("setup is not done: run `next` (it waits for setup, or runs it "
                          "again once the cause is fixed)")
    return info


def unreadable(found):
    """Stop on runs whose state.json can't be read: one may be the run wanted."""
    broken = [item for item in found if item[0] == "broken"]
    if broken:
        raise Fail("; ".join(f"the run in {tree} is unreadable: {fields['error']}"
                             for _, tree, fields, _ in broken)
                   + ". Fix or remove it, then run resume again", CANNOT_RUN, "ERROR")


def main(args):
    found = candidates(args.repo)
    task = args.task.strip()
    if task:
        matched, near = [], []
        for item in found:
            _, _, fields, _ = item
            if not fields.get("Task") or not fields.get("Ticket"):
                continue
            verdict = task_matches(task, fields)
            if verdict is True:
                matched.append(item)
            elif verdict == NEAR_MISS:
                near.append(item)
        if not matched:
            unreadable(found)
        if len(matched) > 1 or (not matched and near):
            pool = matched or near
            emit(args.json, "ASK", "several runs may be this task; ask the user "
                 "which one, or whether to start fresh" if len(pool) > 1 else
                 "a run nearly matches this task; ask the user whether it is theirs",
                 candidates=[f"{t} — {f.get('Task', '')}" for _, t, f, _ in pool])
            return 0
        if not matched:
            emit(args.json, "FRESH", "no run here matches the task: start a fresh run")
            return 0
        return decide_one(matched[0], args)
    here = current_tree(args.repo) if found else None
    mine = [i for i in found if Path(i[1]).resolve() == here]
    if mine:  # started inside a run's worktree: that is the run
        if mine[0][0] == "broken":
            unreadable(mine)
        return decide_one(mine[0], args)
    open_runs = [i for i in found if i[0] == "run" and st.resumable(i[3])]
    if len(open_runs) == 1:
        return decide_one(open_runs[0], args)
    if len(open_runs) > 1:
        emit(args.json, "ASK", "several runs are open; ask the user which one",
             candidates=[f"{t} — {f.get('Task', '')}" for _, t, f, _ in open_runs])
        return 0
    unreadable(found)
    old = [i for i in found if i[0] == "old" and not i[2].get("ended")]
    if len(old) == 1:
        return decide_one(old[0], args)
    emit(args.json, "ASK", "no open run to continue; ask the user what to work on",
         candidates=[f"{t} — {f.get('Task', '')} ({f['version']} run)"
                     for _, t, f, _ in old])
    return 0


def decide_one(item, args):
    kind, tree, fields, state = item
    if kind == "old" and fields.get("ended"):  # nothing left to finish on 4.x
        emit(args.json, "FINISHED", tree, run="ended on auto-dev 4.x",
             task=fields.get("Task", ""))
        return 0
    if kind == "old":
        version = fields["version"]
        last = {"3.x": "3.9", "4.x": "4.27"}[version]
        emit(args.json, "OLD-VERSION", tree, task=fields.get("Task", ""),
             action=f"this run was started on auto-dev {version}; finish it on {last}, "
                    "or remove its worktree and start again")
        return 0
    info = describe(tree, state)
    if info["run"] in ("finished", "stopped") and not st.resumable(state):
        emit(args.json, "FINISHED", tree, run=info["run"],
             task=state["task"].get("text", ""))
        return 0
    start_session(tree, state)
    emit(args.json, "RESUME", tree, **{k: v for k, v in info.items() if k != "tree"})
    return 0


def start_session(tree, state):
    """A new session picks the run up in the first open phase's stage (the
    orchestrator reads its runbook), and a held gate is asked again (`next`
    re-fires it)."""
    number, _ = st.first_open_phase(state) or (6, None)  # finished: its cleanup is left
    state["stage"] = st.STAGES[number]
    for n, _ in st.PHASES:
        if st.phase(state, n)["status"] == "held":
            st.set_phase(state, n, "in-progress")
    # A checkpoint ended the last session at a clean point, with nothing to fix:
    # the stops' windows (failed twice, stale twice, a refused publish) go on.
    after_checkpoint = state.get("checkpoint_seq", 0) > state.get("session_seq", 0)
    if not after_checkpoint:
        for brief in state.get("briefs", []):
            brief.pop("emitted", None)  # a worker that never returned gets new tries
        state["resumed_seq"] = st.seq(state)
    state["session_seq"] = st.seq(state)
    st.add_note(state, f"resumed in a new session ({st.STAGE_NAMES[state['stage']]} stage)")
    st.save(Path(tree) / ".auto-dev", state)
