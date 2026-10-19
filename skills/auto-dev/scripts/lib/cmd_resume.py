"""autodev.py resume — find the run to continue, if any.

Usage:
    autodev.py resume [--repo <main checkout>] [--task "<ticket or task>"] [--json]

Scans every tree `git worktree list` names for `.auto-dev/state.json` (a 4.x
run) or a `WORK_LOG.md` with no state.json (a 3.x run), and prints one
decision on the first line:

    FRESH            --task names no run here: start a fresh run (init)
    RESUME <tree>    continue this run: session, phase and status follow
    ASK              ask the user: several runs fit, a run only nearly matches
                     the task (NEAR-MISS), or no task was given and no run is open
    FINISHED <tree>  the run the task names already finished or was stopped
    OLD-VERSION <tree>  the run was started on auto-dev 3.x, which 4.x does not
                     resume: finish it on 3.9, or remove its worktree and start
                     again

Pass --task whenever the user states the task (its Jira key or what it does);
omit it on a bare `auto-dev continue` or a loose name like "the dark-mode run".
Being given a task never resumes a run that doesn't match it.

Exit codes:
    0  a decision was printed
    2  could not run (not a git checkout, git failed) — not a decision
"""

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
            try:
                state = st.load(artifact_dir)
            except st.StateError:
                found.append(("broken", tree, {}, None))
                continue
            fields = {"Task": state["task"].get("text", ""),
                      "Ticket": st.ticket_line(state["task"])}
            found.append(("v4", tree, fields, state))
        elif (artifact_dir / st.LEDGER).exists():
            found.append(("v3", tree, old_ledger_fields(artifact_dir / st.LEDGER), None))
    return found


def describe(tree, state):
    opened = st.first_open_phase(state)
    if opened is None:
        return {"tree": tree, "run": st.run_state(state)}
    number, status = opened
    return {"tree": tree, "run": st.run_state(state),
            "session": st.SESSION_NAMES[st.SESSIONS[number]],
            "phase": f"{number} — {st.PHASE_NAMES[number]}", "status": status,
            "task": state["task"].get("text", ""),
            "budget": f"{state['budget']['remaining']} of {state['budget']['total']}"}


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
    open_runs = [i for i in found if i[0] == "v4"
                 and st.run_state(i[3]) in ("open", "held")]
    if len(open_runs) == 1:
        return decide_one(open_runs[0], args)
    if len(open_runs) > 1:
        emit(args.json, "ASK", "several runs are open; ask the user which one",
             candidates=[f"{t} — {f.get('Task', '')}" for _, t, f, _ in open_runs])
        return 0
    old = [i for i in found if i[0] == "v3"]
    if len(old) == 1:
        return decide_one(old[0], args)
    emit(args.json, "ASK", "no open run to continue; ask the user what to work on",
         candidates=[f"{t} — {f.get('Task', '')} (3.x run)" for _, t, f, _ in old])
    return 0


def decide_one(item, args):
    kind, tree, fields, state = item
    if kind == "v3":
        emit(args.json, "OLD-VERSION", tree, task=fields.get("Task", ""),
             action="this run was started on auto-dev 3.x; finish it on 3.9, or "
                    "remove its worktree and start again on 4.x")
        return 0
    if kind == "broken":
        raise Fail(f"{tree}/.auto-dev/state.json is unreadable", CANNOT_RUN, "ERROR")
    info = describe(tree, state)
    if info["run"] in ("finished", "stopped"):
        emit(args.json, "FINISHED", tree, run=info["run"],
             task=state["task"].get("text", ""))
        return 0
    emit(args.json, "RESUME", tree, **{k: v for k, v in info.items() if k != "tree"})
    return 0
