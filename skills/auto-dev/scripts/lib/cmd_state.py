"""autodev.py show / phase / note / size / budget / gate — read and write state.json.

Usage (each takes `--dir <artifact-dir>`, default `./.auto-dev`, and `--json`):
    autodev.py show
    autodev.py phase <1-6> <pending|in-progress|done|n/a|held|stopped> [--notes TEXT]
    autodev.py note "<decision or assumption>"
    autodev.py size <FITS|OVERSIZED> --high-risk <yes|no>
    autodev.py budget show
    autodev.py budget spend --consumer <1-5> --id <correction-id> [--what TEXT]
    autodev.py gate <gate> <choice> [--reason TEXT]

Only these commands (and init) write state.json; WORK_LOG.md is regenerated on
every write.

`size` records the Define agent's size check. OVERSIZED also marks Phase 2
stopped (Notes `OVERSIZED`) and Phases 3-6 n/a, and prints `STOP`.

`budget spend` spends one revise round for a correction, before it is
dispatched. Consumers (references/correction-loop.md): 1 Define re-review,
2 plan re-review or acceptance-tester re-spawn, 3 build/acceptance correction,
4 review-finding correction, 5 CI-red correction. Spending an id that was
already spent is a no-op (exit 0, `ALREADY-SPENT`), so a resumed run never pays
twice. At zero it spends nothing, prints `EXHAUSTED` and what to do for that
consumer, and exits 3.

`gate` records a gate decision. Gates: post-plan, pr, staging, main, profile,
jira, cleanup. Choices: proceed, hold, stop, skip (staging only), revise
(post-plan only), leave (jira only: start work but leave Jira alone).
`hold` marks the gate's phase held (resuming re-fires the gate); `stop` marks it
stopped (the run ends); `skip` records the staging gate as n/a.

Exit codes:
    0  done (and for `budget spend`, a round was spent or was already spent)
    1  refused: a bad value, or a choice the gate doesn't offer
    2  could not run (no state.json, unreadable) — not a pass
    3  `budget spend` only: the budget is exhausted; nothing was spent
"""

from . import state as st
from .output import FAILED, Fail, emit

EXIT_EXHAUSTED = 3

GATE_PHASE = {"post-plan": 3, "pr": 6, "staging": 6, "main": 6, "profile": 1,
              "jira": 2, "cleanup": 6}
GATE_CHOICES = {"post-plan": {"proceed", "revise", "stop"},
                "pr": {"proceed", "hold", "stop"},
                "staging": {"proceed", "skip", "hold", "stop"},
                "main": {"proceed", "hold", "stop"},
                "profile": {"proceed", "stop"},
                "jira": {"proceed", "leave", "stop"},
                "cleanup": {"proceed", "stop"}}
CONSUMERS = {
    1: "Define re-review",
    2: "plan re-review or acceptance-tester re-spawn",
    3: "build or acceptance correction",
    4: "review-finding correction",
    5: "CI-red correction",
}
# What to do at zero, per consumer (references/correction-loop.md, On exhaustion).
ON_EXHAUSTED = {
    1: "stop and report the Define review's open blockers, one by one",
    2: "stop and report the plan review's open blockers or the acceptance gaps, "
       "one by one",
    3: "stop and report each unmet condition by name and what was tried; do not "
       "run cleanup or Phase 6",
    4: "go to the PR gate with every open must-fix finding named; if the user "
       "opens the PR anyway, list them in the PR body",
    5: "hold at the next gate (the main gate once the PR is open) with each red "
       "check named; never merge over it",
}


def add_arguments(parser, name):
    parser.add_argument("--dir", default=".auto-dev", help="the run's .auto-dev/")
    if name == "phase":
        parser.add_argument("number", type=int, choices=range(1, 7))
        parser.add_argument("status", choices=st.STATUSES)
        parser.add_argument("--notes")
    elif name == "note":
        parser.add_argument("text")
    elif name == "size":
        parser.add_argument("size", choices=("FITS", "OVERSIZED"))
        parser.add_argument("--high-risk", choices=("yes", "no"), required=True)
    elif name == "budget":
        parser.add_argument("action", choices=("show", "spend"))
        parser.add_argument("--consumer", type=int, choices=sorted(CONSUMERS))
        parser.add_argument("--id", dest="spend_id")
        parser.add_argument("--what", default="")
    elif name == "gate":
        parser.add_argument("gate", choices=sorted(GATE_PHASE))
        parser.add_argument("choice")
        parser.add_argument("--reason", default="")


def load(args):
    try:
        return st.load(args.dir)
    except st.StateError as exc:
        raise Fail(str(exc), 2, "ERROR") from None


def show(args):
    state = load(args)
    opened = st.first_open_phase(state)
    phase = (f"{opened[0]} — {st.PHASE_NAMES[opened[0]]} ({opened[1]})"
             if opened else "none")
    emit(args.json, "STATE", state["task"].get("text", ""), run=st.run_state(state),
         phase=phase, size=state.get("size") or "—",
         budget=f"{state['budget']['remaining']} of {state['budget']['total']}",
         worktree=state["worktree"], branch=state["branch"])
    return 0


def phase(args):
    state = load(args)
    st.set_phase(state, args.number, args.status, args.notes)
    st.save(args.dir, state)
    emit(args.json, "PHASE", f"{args.number} — {st.PHASE_NAMES[args.number]}: "
         f"{args.status}")
    return 0


def note(args):
    state = load(args)
    st.add_note(state, args.text)
    st.save(args.dir, state)
    emit(args.json, "NOTED", args.text)
    return 0


def size(args):
    state = load(args)
    state["size"], state["high_risk"] = args.size, args.high_risk == "yes"
    if args.size == "OVERSIZED":
        st.set_phase(state, 2, "stopped", "OVERSIZED")
        for number in (3, 4, 5, 6):
            st.set_phase(state, number, "n/a", "")
        st.save(args.dir, state)
        emit(args.json, "STOP", "OVERSIZED: report Define's reasons, subsystems and "
             "suggested split lines to the user; keep the worktree; leave Jira alone",
             worktree=state["worktree"], branch=state["branch"])
        return 0
    if state["high_risk"]:
        state["settings"]["post_plan_gate"] = True
    st.save(args.dir, state)
    emit(args.json, "SIZE", f"FITS, high risk: {args.high_risk}",
         post_plan_gate="on" if state["settings"]["post_plan_gate"] else "off")
    return 0


def budget(args):
    state = load(args)
    b = state["budget"]
    if args.action == "show":
        emit(args.json, "BUDGET", f"{b['remaining']} of {b['total']} remaining",
             spent=[f"#{s['consumer']} {s['id']}" for s in b["spends"]])
        return 0
    if args.consumer is None or not args.spend_id:
        raise Fail("budget spend needs --consumer and --id", FAILED, "ERROR")
    if any(s["id"] == args.spend_id for s in b["spends"]):
        emit(args.json, "ALREADY-SPENT", f"`{args.spend_id}` was already paid for; "
             "dispatch without spending again", remaining=b["remaining"])
        return 0
    if b["remaining"] <= 0:
        emit(args.json, "EXHAUSTED", f"no revise rounds left ({CONSUMERS[args.consumer]})",
             action=ON_EXHAUSTED[args.consumer])
        return EXIT_EXHAUSTED
    b["remaining"] -= 1
    b["spends"].append({"id": args.spend_id, "consumer": args.consumer,
                        "what": args.what, "at": st.now()})
    st.save(args.dir, state)
    emit(args.json, "SPENT", f"`{args.spend_id}` — {b['remaining']} of {b['total']} left",
         remaining=b["remaining"])
    return 0


def gate(args):
    state = load(args)
    choice = args.choice.lower()
    if choice not in GATE_CHOICES[args.gate]:
        raise Fail(f"gate {args.gate} offers {', '.join(sorted(GATE_CHOICES[args.gate]))}, "
                   f"not {args.choice!r}", FAILED, "ERROR")
    state["gates"].append({"gate": args.gate, "choice": choice,
                           "reason": args.reason, "at": st.now()})
    number = GATE_PHASE[args.gate]
    after = "continue"
    if choice == "hold":
        st.set_phase(state, number, "held", f"held at the {args.gate} gate: "
                     f"{args.reason}".rstrip(": "))
        after = "stop here; resuming re-fires this gate, starting with its checks"
    elif choice == "stop":
        st.set_phase(state, number, "stopped", f"stopped at the {args.gate} gate: "
                     f"{args.reason}".rstrip(": "))
        after = "write the final report and end the run"
    elif choice == "skip":
        notes = st.phase(state, 6)["notes"]
        st.phase(state, 6)["notes"] = ((notes + "; " if notes else "")
                                       + "staging gate: n/a (skipped by the user)")
        after = "go on to the main gate"
    elif choice == "revise":
        after = ("spawn the planner in revise mode with the user's direction, "
                 "then ask this gate again (no round is spent)")
    elif choice == "leave":
        after = "start work without moving Jira"
    elif st.phase(state, number)["status"] == "held":
        st.set_phase(state, number, "in-progress")
    st.save(args.dir, state)
    emit(args.json, "GATE", f"{args.gate}: {choice}", after=after)
    return 0
