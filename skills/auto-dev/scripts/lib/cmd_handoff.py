"""autodev.py handoff — write HANDOFF.md from state and print the restart message.

Usage:
    autodev.py handoff [--dir <artifact-dir>] [--checkpoint]
                       [--assumption "<text>" ...] [--do-not "<text>" ...]
                       [--pick-up-at "<text>"] [--json]

The run goes straight through in one session; a session ends only at a
checkpoint (`next` exits 6 with `handoff --checkpoint`, so no session's context
grows without bound), or when the user asks to stop (SKILL.md). Writes `<artifact-dir>/HANDOFF.md`
for the session that picks the run up: the task (a `Task:` line, and an `Ask:`
line with the restated ask), what is done, the stage and phase it is in and
that stage's runbook (references/<stage>.md), the run files its orchestrator
may open (the workers read the rest; `next` names them), and the slots only you
can fill (`--assumption`, `--do-not`, `--pick-up-at`). Without `--pick-up-at`,
the pick-up point is `auto-dev continue`: `next` decides the step.
`--checkpoint` records the checkpoint, so the `resume` that follows lifts no
stop: nothing was stopped.

Then prints the message to give the user: start a fresh session in the
worktree and say `auto-dev continue`. Stop after that.

Exit codes:
    0  HANDOFF.md written; the message is printed
    1  nothing to hand off: the run is finished or stopped
    2  could not run (no state.json) — not a pass
"""

from pathlib import Path

from . import state as st
from .output import Fail, emit

# The run files the next session's orchestrator may open, by stage. The
# workers read the rest; the Ship stage writes the PR's Summary from PLAN.md.
FILES = {"plan": ["profile.md", "WORK_LOG.md"], "build": ["profile.md"],
         "ship": ["profile.md", "PLAN.md"]}


def add_arguments(parser):
    parser.add_argument("--dir", default=".auto-dev", help="the run's .auto-dev/")
    parser.add_argument("--checkpoint", action="store_true")
    parser.add_argument("--assumption", action="append", default=[])
    parser.add_argument("--do-not", dest="do_not", action="append", default=[])
    parser.add_argument("--pick-up-at", default="")


def main(args):
    try:
        state = st.load(args.dir)
    except st.StateError as exc:
        raise Fail(str(exc), 2, "ERROR") from None
    opened = st.first_open_phase(state)
    if opened is None or st.run_state(state) == "stopped":
        raise Fail("nothing to hand off: the run is finished or stopped")
    number, _status = opened
    stage = st.STAGES[number]
    artifact_dir = Path(state["artifact_dir"])
    kind = "checkpoint" if args.checkpoint else "session ended"
    pick_up = args.pick_up_at or "say `auto-dev continue`; `next` decides the step"
    budget = state["budget"]
    done = [f"- Phase {n} {name}: {st.phase(state, n)['notes'] or 'done'}"
            for n, name in st.PHASES if st.phase(state, n)["status"] in st.COMPLETE]
    files = [f"- {artifact_dir / f}" for f in FILES[stage]
             if (artifact_dir / f).exists()]
    task = state["task"]
    ticket = task.get("ticket")
    title = ticket if ticket and ticket != "none" else task.get("text", "")
    lines = [
        f"# Handoff — {title} → {st.STAGE_NAMES[stage]} stage ({kind})",
        "",
        f"Task: {' '.join(str(task.get('text', '')).split())}",
        *([f"Ask: {' '.join(str(task['ask']).split())}"] if task.get("ask") else []),
        f"Re-enter with: `cd {state['worktree']}`",
        f"Branch: {state['branch']}   Base: origin/{state['repo']['base']}",
        f"Iteration budget remaining: {budget['remaining']}/{budget['total']}",
        "",
        "## Done",
        *(done or ["- nothing yet"]),
        "",
        "## Next",
        (f"Phase {number} — {st.PHASE_NAMES[number]}, in the {st.STAGE_NAMES[stage]} stage "
         f"(runbook: references/{stage}.md). Say `auto-dev continue`."),
        f"Pick up at: {pick_up}",
        "",
        "## Files you may open",
        *(files or ["- profile.md"]),
        "",
        "## Open assumptions",
        *([f"- {a}" for a in args.assumption] or ["- none"]),
        "",
        "## Do not",
        "- re-run Phase 1 or re-resolve the profile",
        *[f"- {d}" for d in args.do_not],
    ]
    (artifact_dir / "HANDOFF.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    st.add_note(state, f"handoff written for the {st.STAGE_NAMES[stage]} stage ({kind})")
    if args.checkpoint:
        state["checkpoint_seq"] = st.seq(state)
    st.save(args.dir, state)
    message = (f"{'Checkpoint: progress' if args.checkpoint else 'Progress'} saved in "
               f"{artifact_dir}. Start a fresh session in {state['worktree']} and say "
               "`auto-dev continue`: the run picks up where it is.")
    emit(args.json, "HANDOFF", str(artifact_dir / "HANDOFF.md"), tell_user=message,
         then="stop here")
    return 0
