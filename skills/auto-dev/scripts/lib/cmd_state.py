"""autodev.py show / phase / note / budget / gate — read and write state.json.

Usage (each takes `--dir <artifact-dir>`, default `./.auto-dev`, and `--json`):
    autodev.py show
    autodev.py phase <1-6> <pending|in-progress|done|n/a|held|stopped> [--notes TEXT]
    autodev.py note "<decision or assumption>"
    autodev.py budget show
    autodev.py budget spend --id <round-id> [--what TEXT]
    autodev.py budget raise --by <n>
    autodev.py gate <gate> <choice> [--reason TEXT]
    autodev.py mark <step> [--value TEXT]

`show` prints the task, the restated ask (an `ask:` line, when there is one), the
run's state, the first open phase, the size, the budget, the worktree and the
branch.

Only these commands (and init) write state.json; WORK_LOG.md is regenerated on
every write.

`budget spend` spends one round of the run's one iteration budget, before the
re-review or correction it pays for is dispatched (references/tables.md, _The
iteration budget_). Spending an id that was already spent is a no-op (exit 0,
`ALREADY-SPENT`), so a resumed run never pays twice. At zero it spends nothing,
prints `EXHAUSTED` and exits 3.

`budget raise` adds <n> rounds (1 to 10) to a run `next` stopped because no
round was left, and is refused otherwise; the next `next` takes the step that
stopped. It prints `RAISED`.

`mark` records a step done outside autodev.py, so `next` moves past it. Steps:
jira-in-progress, jira-in-review, jira-done (a Jira transition made through the
MCP tools, or skipped: --value skipped), pushed (--value <the sha pushed>),
pr-ready (the draft PR marked ready for review), final-report, main-ci (CI on
main checked after the merge); and triage-<ID> (the user's answer at
the ready-for-review gate for a pre-existing security finding, `triage-Others` for the
grouped rest: --value separate or ignore; it is also noted in WORK_LOG.md).

`gate` records a gate decision. Gates: post-plan, pr (open the PR, only with
`gates.open_pr`), ready (ready for review), main, profile, jira, cleanup.
Choices: proceed, hold, stop, revise (post-plan only), leave (jira
only: start work but leave Jira alone), already (jira only: the ticket is in
progress already, so start work without moving it now; later milestones move
it as after proceed), keep (cleanup only: keep the worktree). `hold` marks the
gate's phase held (resuming re-fires the gate); `stop` marks it stopped (the
run ends).

Exit codes:
    0  done (and for `budget spend`, a round was spent or was already spent)
    1  refused: a bad value, a choice the gate doesn't offer, or a `mark` step
       that is not one of those above (or a triage answer not separate/ignore),
       or a `budget raise` when the run is not stopped on the budget or <n> is
       not 1 to 10
    2  could not run (no state.json, unreadable) — not a pass
    3  `budget spend` only: the budget is exhausted; nothing was spent
"""

import re

from . import state as st
from .output import FAILED, Fail, emit

EXIT_EXHAUSTED = 3
MAX_RAISE = 10

GATE_PHASE = {"post-plan": 3, "pr": 6, "ready": 6, "main": 6, "profile": 1, "jira": 2,
              "cleanup": 6}
GATE_CHOICES = {"post-plan": {"proceed", "revise", "stop"},
                "pr": {"proceed", "hold", "stop"},
                "ready": {"proceed", "hold", "stop"},
                "main": {"proceed", "hold", "stop"},
                "profile": {"proceed", "stop"},
                "jira": {"proceed", "already", "leave", "stop"},
                "cleanup": {"proceed", "keep"}}
MARKS = ("jira-in-progress", "jira-in-review", "jira-done", "pushed", "pr-ready",
         "final-report", "main-ci")
TRIAGE_RE = re.compile(r"triage-[A-Za-z0-9]+")
TRIAGE_ANSWERS = ("separate", "ignore")


def add_arguments(parser, name):
    parser.add_argument("--dir", default=".auto-dev", help="the run's .auto-dev/")
    if name == "phase":
        parser.add_argument("number", type=int, choices=range(1, 7))
        parser.add_argument("status", choices=st.STATUSES)
        parser.add_argument("--notes")
    elif name == "note":
        parser.add_argument("text")
    elif name == "budget":
        parser.add_argument("action", choices=("show", "spend", "raise"))
        parser.add_argument("--id", dest="spend_id")
        parser.add_argument("--what", default="")
        parser.add_argument("--by", type=int, help="raise only: rounds to add")
    elif name == "mark":
        parser.add_argument("step", help=f"one of {', '.join(MARKS)}, or triage-<ID>")
        parser.add_argument("--value", default="done")
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
    emit(args.json, "STATE", state["task"].get("text", ""),
         ask=" ".join(str(state["task"].get("ask") or "").split()) or None,
         run=st.run_state(state),
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


def budget(args):
    state = load(args)
    b = state["budget"]
    if args.action == "show":
        emit(args.json, "BUDGET", f"{b['remaining']} of {b['total']} remaining",
             spent=[s["id"] for s in b["spends"]])
        return 0
    if args.action == "raise":
        return raise_budget(args, state)
    if not args.spend_id:
        raise Fail("budget spend needs --id", FAILED, "ERROR")
    outcome = spend_round(state, args.spend_id, args.what)
    if outcome == "already":
        emit(args.json, "ALREADY-SPENT", f"`{args.spend_id}` was already paid for; "
             "dispatch without spending again", remaining=b["remaining"])
        return 0
    if outcome == "exhausted":
        emit(args.json, "EXHAUSTED", "no revise rounds left",
             action="stop and report what is still open, by name")
        return EXIT_EXHAUSTED
    st.save(args.dir, state)
    emit(args.json, "SPENT", f"`{args.spend_id}` — {b['remaining']} of {b['total']} left",
         remaining=b["remaining"])
    return 0


def raise_budget(args, state):
    b = state["budget"]
    stopped = b.get("stopped")
    if not stopped:
        raise Fail("the run is not stopped on the budget: rounds are added only after "
                   "`next` stopped because none was left", FAILED, "ERROR")
    if args.by is None or not 1 <= args.by <= MAX_RAISE:
        raise Fail(f"budget raise needs --by <n>, 1 to {MAX_RAISE}", FAILED, "ERROR")
    b["total"] += args.by
    b["remaining"] += args.by
    b.setdefault("raises", []).append({"by": args.by, "at": st.now(),
                                       "seq": st.seq(state)})
    del b["stopped"]
    st.add_note(state, f"the user raised the iteration budget by {args.by} after it ran "
                f"out ({stopped.get('what') or 'no round left'}): {b['remaining']} of "
                f"{b['total']} left")
    st.save(args.dir, state)
    emit(args.json, "RAISED", f"{b['remaining']} of {b['total']} left",
         after="run `next`: it takes the step that stopped")
    return 0


def spend_round(state, spend_id, what=""):
    """Spend one round in `state` (not saved): `spent`, `already` or `exhausted`."""
    b = state["budget"]
    if any(s["id"] == spend_id for s in b["spends"]):
        return "already"
    if b["remaining"] <= 0:
        return "exhausted"
    b["remaining"] -= 1
    b["spends"].append({"id": spend_id, "what": what, "at": st.now(),
                        "seq": st.seq(state)})
    return "spent"


def mark(args):
    triage = TRIAGE_RE.fullmatch(args.step)
    if args.step not in MARKS and not triage:
        raise Fail(f"no step {args.step!r}: one of {', '.join(MARKS)}, or triage-<ID>",
                   FAILED, "ERROR")
    if triage and args.value not in TRIAGE_ANSWERS:
        raise Fail(f"{args.step} takes --value {' or '.join(TRIAGE_ANSWERS)}", FAILED,
                   "ERROR")
    state = load(args)
    state.setdefault("marks", {})[args.step] = {"value": args.value, "at": st.now(),
                                                "seq": st.seq(state)}
    if triage:
        st.add_note(state, f"ready-for-review gate triage, {args.step[len('triage-'):]}: "
                    f"{args.value}")
    st.save(args.dir, state)
    emit(args.json, "MARKED", f"{args.step}: {args.value}")
    return 0


def gate(args):
    state = load(args)
    choice = args.choice.lower()
    if choice not in GATE_CHOICES[args.gate]:
        raise Fail(f"gate {args.gate} offers {', '.join(sorted(GATE_CHOICES[args.gate]))}, "
                   f"not {args.choice!r}", FAILED, "ERROR")
    entry = {"gate": args.gate, "choice": choice, "reason": args.reason, "at": st.now(),
             "seq": st.seq(state)}
    number = GATE_PHASE[args.gate]
    state["gates"].append(entry)
    after = "continue"
    if choice == "hold":
        st.set_phase(state, number, "held", f"held at the {args.gate} gate: "
                     f"{args.reason}".rstrip(": "))
        after = "stop here; resuming re-fires this gate, starting with its checks"
    elif choice == "stop":
        st.set_phase(state, number, "stopped", f"stopped at the {args.gate} gate: "
                     f"{args.reason}".rstrip(": "))
        after = "write the final report and end the run"
    elif choice == "revise":
        after = ("spawn the planner in revise mode with the user's direction, "
                 "then ask this gate again (no round is spent)")
    elif choice == "leave":
        after = "start work without moving Jira"
    elif choice == "already":
        after = "start work without moving Jira now; later milestones move it"
    elif st.phase(state, number)["status"] == "held":
        st.set_phase(state, number, "in-progress")
    st.save(args.dir, state)
    emit(args.json, "GATE", f"{args.gate}: {choice}", after=after)
    return 0
