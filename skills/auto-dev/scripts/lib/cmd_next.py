"""autodev.py next — print the pipeline's one next action.

Usage:
    autodev.py next [--dir <artifact-dir>] [--explain] [--json]

Reads state.json (the workers' recorded results, the briefs issued, the FIX
outcomes, the gates, the marks and the Phase 6 fields) and the artifacts, and
prints the one thing to do now. Run it, do exactly that, run every AFTER
command, then run `next` again. It never needs you to judge a file.

It does the mechanical steps itself rather than asking you to: it writes the
brief of the worker to spawn, spends a round of the budget before a
correction, installs the sealed acceptance checks before Phase 5's cleanup,
applies a reviewer's FIX blocks, checks the acceptance tester's
manifest, reads the verifier's verdicts, plans and applies the code-review
re-votes, takes the review snapshot, and generates the PR body.

Output lines (only the ones that apply):
    ACTION:   what to do, in one line
    AGENT:    an agent to spawn (several AGENT lines: spawn them all in one
              message, in parallel); its BRIEF and PROMPT follow it
    BRIEF:    the brief file written for it
    PROMPT:   the one-line prompt to give the Agent tool (no `model` parameter)
    EFFORT:   for a code reviewer only, after its PROMPT: the Agent tool's
              `effort` parameter to spawn it with (`high` or `xhigh`, from the
              plan's `Review effort:` line; xhigh when the plan has none)
    BUDGET:   the round this action spent, and what is left
    SUMMARY:  lines to show the user before asking (exit 5)
    QUESTION: the AskUserQuestion JSON (exit 5)
    REPORT:   what to tell the user (exits 4 and 6)
    AFTER:    a command to run once the action is done; for a question,
              `"<answer>" → <command>`, one per answer
    RULE:     the rule that chose the action (--explain)

--explain only looks: it prints the action `next` would take and the rule that
chose it, but writes no brief, spends no round, applies nothing and saves
nothing. Run `next` without it to act.

Every path and value in a printed command is shell-quoted. A `<...>`
placeholder (a reason, a commit subject) sits in single quotes: replace it,
inside them, with text that holds no single quote (rephrase, or use the
typographic apostrophe U+2019). Nothing else is special inside single quotes,
so the text needs no other escaping.

Exit codes:
    0  an action to take
    2  could not run (no state.json, an artifact unreadable, a check that could
       not run) — never a pass
    3  the run is complete
    4  stop and report: tell the user the REPORT lines; do nothing more
    5  ask the user: show SUMMARY, ask QUESTION, run the AFTER line for the answer
    6  session boundary, or a checkpoint: run the AFTER command, give the user its
       message, stop
`next` never exits 1: a step it could not take is a stop (4) that says why.

Checkpoint: once this session has written CHECKPOINT_EVENTS events to state.json
(80, or `checkpoint_events` in .auto-dev.yml), `next` ends the session at the
next clean point with exit 6 and `handoff --checkpoint`, so no session's context
grows without bound. A clean point is one where the step would be an action
(exit 0) and no brief is in flight: a stop, a question or a session boundary the
step would print comes first. A stop that only a write would reveal (one found
after applying FIX blocks or starting a review pass) comes in the next session
instead. A new session says `auto-dev continue` and picks up where this one
stopped; resuming after a checkpoint lifts no stop, since nothing was fixed in
between.

A brief issued but not yet recorded is re-issued as the same spawn (after a
cut-off session, say); one `record` refused is re-issued as a new brief that
carries the refused issues (as `brief --retry <n>` writes). Spawned three
times with no usable result, it stops. A stop on a worker (blocked, failed
twice, never returned) lasts until `resume`: after the user fixes the cause,
the next session spawns that worker again. A stop on a result (a red quality
gate, an impossible spec, the budget used up) stays.
"""

import copy
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

from . import artifacts as art
from . import cmd_checks, cmd_review, cmd_work
from . import state as st
from .cmd_ship import changed_paths
from .cmd_state import ON_EXHAUSTED, spend_round
from .output import (
    ACTION_KEYS,
    CANNOT_RUN,
    NEXT_ACTION,
    NEXT_ASK,
    NEXT_BOUNDARY,
    NEXT_COMPLETE,
    NEXT_STOP,
    Fail,
    action_lines,
)
from .proc import git, run

SCRIPTS = Path(__file__).resolve().parent.parent
AUTODEV = SCRIPTS / "autodev.py"
MAX_EMITS = 3
CHECKPOINT_EVENTS = 80  # about 35 workers; tune on the fixture repo
SLOTS = ("R1", "R2", "R3")
JIRA_DEFAULTS = {"in_progress": "In Progress", "in_review": "In Review", "done": "Done"}
# Workers whose results drive the build-verify loop (Phases 4-6).
LOOP = ("verifier", "coder", "cleanup", "acceptance-tester", "planner")
NONE = ("none", "", None)
ONLY_RE = re.compile(r"ONLY conditions ([^:]+):")
FILL = ("replace each '<...>' placeholder, inside its single quotes, with text that "
        "holds no single quote (rephrase, or use the typographic apostrophe U+2019)")


def add_arguments(parser):
    parser.add_argument("--dir", default=".auto-dev", help="the run's .auto-dev/")
    parser.add_argument("--explain", action="store_true",
                        help="print the action and the rule that chose it, changing "
                             "nothing")


def q(value):
    """`value` quoted for a shell command the orchestrator copies."""
    return shlex.quote(str(value))


class Preview(Exception):
    """--explain reached a step that writes: what it would do, and why."""

    def __init__(self, what, rule):
        super().__init__(what)
        self.what, self.rule = what, rule


class Ctx:
    """The run as `next` sees it, and the one action it decides on."""

    def __init__(self, args):
        try:
            self.state = st.load(args.dir)
        except st.StateError as exc:
            raise Fail(str(exc), CANNOT_RUN, "ERROR") from None
        self.dir = args.dir
        self.ad = Path(self.state["artifact_dir"])
        self.wt = self.state["worktree"]
        self.p6 = self.state.setdefault("phase6", {})
        self.dirty = False
        self.readonly = bool(getattr(args, "explain", False))
        self.probing = False
        self.peeked = {}

    # ------------------------------------------------------------ reading

    @property
    def log(self):
        return sorted(self.state.get("log", []), key=lambda e: e.get("seq", 0))

    def recs(self, workers=None, after=0, mode=None, ok=True, before=None):
        if isinstance(workers, str):
            workers = (workers,)
        return [e for e in self.log
                if (workers is None or e["worker"] in workers)
                and e.get("seq", 0) > after
                and (before is None or e.get("seq", 0) < before)
                and (mode is None or e.get("mode") == mode)
                and (not ok or e.get("status") == "ok")]

    def last(self, workers=None, **kw):
        found = self.recs(workers, **kw)
        return found[-1] if found else None

    def gate(self, name, after=0):
        found = [g for g in self.state["gates"]
                 if g["gate"] == name and g.get("seq", 0) > after]
        return found[-1] if found else None

    def mark(self, step):
        return self.state.get("marks", {}).get(step)

    def cmd(self, *args):
        return " ".join(q(w) for w in ("python3", AUTODEV, *args, "--dir", self.ad))

    def resumed(self):
        return self.state.get("resumed_seq", 0)

    def probe(self):
        """A read-only copy, to see what `next` would do without doing it."""
        other = copy.copy(self)
        other.state = copy.deepcopy(self.state)
        other.p6 = other.state.setdefault("phase6", {})
        other.readonly, other.dirty, other.peeked = True, False, {}
        other.probing = True  # it still fetches, so a new push is seen before a checkpoint
        return other

    # ------------------------------------------------------------ writing

    def seq(self):
        return st.seq(self.state)

    def start(self, number):
        entry = st.phase(self.state, number)
        if entry["status"] == "pending":
            st.set_phase(self.state, number, "in-progress")
            entry["started_seq"] = self.seq()
            self.dirty = True
        return entry.get("started_seq", 0)

    def finish(self, number, notes=None):
        st.set_phase(self.state, number, "done", notes)
        self.dirty = True

    def save(self):
        if self.dirty and not self.readonly:
            st.save(self.dir, self.state)

    def would(self, what, rule):
        """Under --explain, stop before a step that writes a file or git."""
        if self.readonly:
            raise Preview(what, rule)

    def peek(self, worker):
        """The brief number write_brief would give `worker` next (--explain)."""
        n = self.peeked.get(worker) or cmd_work.next_number(self.ad / "briefs", worker) - 1
        self.peeked[worker] = n + 1
        return n + 1

    def spend(self, consumer, spend_id, what):
        outcome = spend_round(self.state, consumer, spend_id, what)
        if outcome == "spent":
            self.dirty = True
        b = self.state["budget"]
        if outcome == "exhausted":
            return None
        verb = ("already spent" if outcome != "spent" else
                "would spend" if self.readonly else "spent")
        return f"{verb} `{spend_id}` ({what}); {b['remaining']} of {b['total']} left"


# ---------------------------------------------------------------- actions

def action(text, rule, **lines):
    return {"code": NEXT_ACTION, "ACTION": text, "RULE": rule, **lines}


def stop(report, rule):
    return {"code": NEXT_STOP, "ACTION": "stop and report to the user; do nothing more",
            "REPORT": report, "RULE": rule}


def spawn(c, worker, mode=None, sets=None, rule="", budget=None, agent=None):
    return spawn_many(c, [(worker, mode, sets or {})], rule, budget, agent)


def spawn_many(c, jobs, rule, budget=None, agent=None):
    agents, briefs_, prompts, after, efforts = [], [], [], [], []
    for worker, mode, sets in jobs:
        if c.readonly:
            n = c.peek(worker)
            path = c.ad / "briefs" / f"{worker}-{n}.md"
        else:
            path, _ = cmd_work.write_brief(c.state, c.ad, worker, mode, dict(sets))
            c.dirty = True
            n = int(path.stem.rsplit("-", 1)[1])
        agents.append(agent or f"auto-dev:{worker}")
        briefs_.append(str(path))
        prompts.append(cmd_work.prompt_for(path))
        after.append(c.cmd("record", worker, n))
        efforts.append(effort_for(c, worker))
    return spawn_lines(agents, briefs_, prompts, after, rule, budget, efforts)


def spawn_lines(agents, briefs_, prompts, after, rule, budget=None, efforts=None):
    """efforts, when any is set, parallels agents ("" for an agent spawned at its
    own effort)."""
    efforts = efforts if efforts and any(efforts) else None
    what = (f"spawn {agents[0]} with the PROMPT" if len(agents) == 1 else
            f"spawn these {len(agents)} agents in one message, in parallel, each "
            "with its PROMPT")
    if efforts:
        what += ", passing its EFFORT as the Agent tool's `effort` parameter"
    return action(what, rule, AGENT=agents, BRIEF=briefs_, PROMPT=prompts,
                  EFFORT=efforts, BUDGET=budget, AFTER=after)


def plan_effort(c):
    """The code reviewers' effort the plan recommends; xhigh when it names none
    (a plan written before 4.3) or names something else."""
    try:
        value = art.review_effort(art.read(c.ad / "IMPLEMENTATION.md"))
    except art.ArtifactError:
        value = None
    return value if value in art.REVIEW_EFFORTS else art.DEFAULT_REVIEW_EFFORT


def effort_for(c, worker):
    """The Agent tool's `effort` for a spawn: a code reviewer runs at its review
    pass's effort (the plan's, noted when the pass started); every other worker
    at its agent file's, so ""."""
    if worker != "code-reviewer":
        return ""
    passes = c.p6.get("passes") or []
    return (passes[-1].get("effort") if passes else None) or plan_effort(c)


def ask(c, gate, summary, questions, answers, rule):
    """A gate or pause: answers is [(option label, command)]."""
    return {"code": NEXT_ASK,
            "ACTION": f"show the user SUMMARY, then ask QUESTION with AskUserQuestion "
                      f"({gate}); run the AFTER line for their answer ({FILL})",
            "SUMMARY": summary, "QUESTION": json.dumps({"questions": questions}),
            "AFTER": [f'"{label}" → {command}' for label, command in answers],
            "RULE": rule}


def exhausted(c, consumer, rule, extra=""):
    return stop([f"The iteration budget is used up ({c.state['budget']['total']} "
                 f"rounds): {ON_EXHAUSTED[consumer]}." + (f" {extra}" if extra else ""),
                 f"State and artifacts: {c.ad}"], rule)


# ---------------------------------------------------------------- entry point

def main(args):
    c = Ctx(args)
    try:
        result = decide(c)
    except Preview as exc:
        result = action(f"next would {exc.what}", exc.rule)
    except art.ArtifactError as exc:
        c.save()
        raise Fail(f"{exc} — a broken artifact: tell the user and stop (the worker "
                   "that wrote it may need re-running)", CANNOT_RUN, "ERROR") from None
    except AssertionError as exc:
        raise Fail(f"next has no rule for this state ({exc}); report it as an "
                   "auto-dev bug", CANNOT_RUN, "ERROR") from None
    except Fail as exc:
        if exc.code == CANNOT_RUN:
            raise
        # A step `next` could not take is a stop, never exit 1; nothing is saved,
        # since the step did not happen.
        return show(stop([f"`next` could not take its step ({exc.token}): {exc}",
                          ("Tell the user; it is a broken artifact or an auto-dev bug. "
                           f"State and artifacts: {c.ad}")],
                         f"a step failed: {exc.token}"), args)
    c.save()
    return show(result, args)


def show(result, args):
    code = result.pop("code")
    if not args.explain:
        result.pop("RULE", None)
    elif result.get("ACTION"):
        result["ACTION"] = ("(--explain: nothing was done; run `next` to act) "
                            + result["ACTION"])
    if args.json:
        print(json.dumps({"exit": code, **{k: v for k, v in result.items() if v}},
                         indent=2))
        return code
    lines = []
    keys = list(ACTION_KEYS) + [k for k in result if k not in ACTION_KEYS]
    for key in keys:
        value = result.get(key)
        if not value:
            continue
        if key == "AGENT":  # interleave each agent with its brief, prompt and effort
            efforts = result.get("EFFORT") or []
            for i, agent in enumerate(value):
                lines += [f"AGENT: {agent}", f"BRIEF: {result['BRIEF'][i]}",
                          f"PROMPT: {result['PROMPT'][i]}"]
                if i < len(efforts) and efforts[i]:
                    lines.append(f"EFFORT: {efforts[i]}")
            continue
        if key in ("BRIEF", "PROMPT", "EFFORT") and result.get("AGENT"):
            continue
        lines.append(action_lines({key: value}))
    print("\n".join(lines))
    return code


def decide(c):
    run_state = st.run_state(c.state)
    if run_state == "finished":
        return {"code": NEXT_COMPLETE, "ACTION": "the run is complete; nothing more to do",
                "RULE": "every phase is done"}
    if run_state in ("stopped", "held"):
        return ended(c, run_state)
    pending = pending_briefs(c)
    if pending:
        return pending
    bad = not_ok(c)
    if bad:
        return bad
    if st.phase(c.state, 1)["status"] != "done":
        return setup(c)
    if checkpoint_due(c):
        # Only at a clean point: a stop, a question or a boundary comes first.
        probe = c if c.readonly else c.probe()
        try:
            would = phases(probe)
        except Preview:
            would = {"code": NEXT_ACTION}
        if would["code"] == NEXT_ACTION:
            return checkpoint(c)
        if c.readonly:
            return would
    return phases(c)


def phases(c):
    for number in (2, 3, 4, 5, 6):
        if st.phase(c.state, number)["status"] in st.COMPLETE:
            continue
        session = st.SESSIONS[number]
        if session != c.state.get("session", "S1"):
            return boundary(c, session)
        result = PHASES[number](c)
        if result is not None:
            return result
        if st.phase(c.state, number)["status"] not in st.COMPLETE:
            raise AssertionError(f"Phase {number} returned no action and is not done")
    return {"code": NEXT_COMPLETE, "ACTION": "the run is complete; nothing more to do",
            "RULE": "every phase is done"}


def ended(c, how):
    rows = [f"Phase {n} — {name}: {st.phase(c.state, n)['status']}"
            + (f" ({st.phase(c.state, n)['notes']})" if st.phase(c.state, n)["notes"] else "")
            for n, name in st.PHASES if st.phase(c.state, n)["status"] in ("stopped", "held")]
    if how == "held":
        rows.append("The run is held. Saying `auto-dev continue` in a new session "
                    "re-asks the gate that held it.")
    elif c.state.get("size") == "OVERSIZED":
        rows.append("The task is too big for one PR. Tell the user Define's reasons, the "
                    "subsystems it found and its suggested split lines, below. Jira was "
                    f"not moved. The worktree is kept: {c.wt} (remove it with "
                    f"`git worktree remove {q(c.wt)}`).")
        rows += size_check(c)
    rows.append(f"State and artifacts: {c.ad}")
    return stop(rows, f"the run is {how}")


def size_check(c):
    """SPEC.md's Size check section, line by line, for the OVERSIZED report."""
    try:
        section = art.find_section(art.read(c.ad / "SPEC.md"), "Size check")
    except art.ArtifactError:
        section = None
    lines = [ln.strip() for ln in (section or "").splitlines() if ln.strip()]
    if not lines:
        return [("SPEC.md has no Size check section; Define's reply gave the reasons "
                 f"({c.ad}/SPEC.md).")]
    return ["Define's size check (SPEC.md):", *lines]


def pending_briefs(c):
    """Re-issue the briefs issued after the last recorded result and not recorded.

    A job `record` refused (MISSING, MALFORMED, MISMATCH) is re-spawned as
    `brief --retry <n>` would: a new brief whose previous_issues carries the
    issues, replacing the old one."""
    done = {(e["worker"], e["n"]) for e in c.state.get("log", [])}
    issued = c.state.get("briefs", [])
    open_ = [b for b in issued if (b["worker"], b["n"]) not in done
             and not b.get("retried_as")]
    if not open_:
        return None
    refused = c.state.get("refused", {})
    for i, b in enumerate(open_):
        tries = b.get("emitted", 1) + 1
        if tries > MAX_EMITS:
            return stop([(f"{b['worker']} #{b['n']} was spawned {MAX_EMITS} times and "
                         "never left a result that `record` accepts. Tell the user; its "
                         f"brief is {c.ad}/briefs/{b['worker']}-{b['n']}.md. Once the "
                         "cause is fixed, `auto-dev continue` spawns it again.")],
                        "a worker failed to return three times")
        if c.readonly:  # --explain counts nothing and writes no retry brief
            if cmd_work.job(b["worker"], b["n"]) in refused:
                open_[i] = {"worker": b["worker"], "n": c.peek(b["worker"])}
            continue
        if cmd_work.job(b["worker"], b["n"]) in refused:
            cmd_work.write_brief(c.state, c.ad, b["worker"], b.get("mode"),
                                 dict(b.get("sets", {})), retry=b["n"])
            new = c.state["briefs"][-1]  # write_brief marked b retried_as it
            new["emitted"] = tries
            open_[i] = new
        else:
            b["emitted"] = tries
        c.dirty = True
    agents = [f"auto-dev:{b['worker']}" for b in open_]
    paths = [c.ad / "briefs" / f"{b['worker']}-{b['n']}.md" for b in open_]
    return spawn_lines(agents, [str(p) for p in paths],
                       [cmd_work.prompt_for(p) for p in paths],
                       [c.cmd("record", b["worker"], b["n"]) for b in open_],
                       "a brief was issued and its result is not recorded yet: "
                       "spawn it again",
                       efforts=[effort_for(c, b["worker"]) for b in open_])


def not_ok(c):
    """A worker that stopped on purpose twice running, or failed twice running,
    stops the run; the first time, the step spawns it again (a blocked one is
    told why in its brief's previous_issues).

    Only results since the last `resume` count: once the user has fixed the
    cause and resumed, the step spawns the worker again."""
    log = [e for e in c.log if e.get("seq", 0) > c.resumed()]
    if not log:
        return None
    latest = log[-1]
    if latest.get("status") == "ok" or latest["worker"] == "code-reviewer":
        return None
    same = [e for e in log if e["worker"] == latest["worker"]]
    twice = len(same) >= 2 and same[-2].get("status") != "ok"
    if twice:
        statuses = {latest["status"], same[-2].get("status")}
        why = ("stopped on purpose twice running" if statuses == {"blocked"} else
               "failed twice running" if statuses == {"failed"} else
               "did not return ok twice running")
        return stop([(f"{latest['worker']} #{latest['n']} {why}. Tell the user what it "
                     "said above its result block, and that the run is paused here: "
                     "once the cause is fixed, `auto-dev continue` spawns it again."),
                     f"State and artifacts: {c.ad}"],
                    f"a worker returned status {latest['status']}")
    return None  # failed or blocked once: the step re-spawns it


def setup(c):
    status = c.state["init"].get("setup")
    if status in ("running", "pending"):
        return action(f"run `python3 {q(AUTODEV)} init --continue {q(c.wt)}` (setup is "
                      "still running)", "Phase 1's setup has not finished",
                      AFTER=[c.cmd("next")])
    return stop([(f"Phase 1 did not finish: {st.phase(c.state, 1)['notes'] or status}. "
                 "Tell the user; fix the cause, then run init --continue.")],
                "Phase 1 is not done")


def boundary(c, session):
    return {"code": NEXT_BOUNDARY,
            "ACTION": "end this session: run AFTER, give the user its message, stop",
            "REPORT": [(f"{st.SESSION_NAMES[c.state.get('session', 'S1')]} is done; "
                       f"{st.SESSION_NAMES[session]} runs in a fresh session.")],
            "AFTER": [c.cmd("handoff")],
            "RULE": f"the next phase belongs to {session}"}


def checkpoint_due(c):
    """Whether this session has written its share of events (counted from the
    session's start, which `resume` records as session_seq)."""
    limit = _int(c.state["settings"].get("checkpoint_events")) or CHECKPOINT_EVENTS
    return c.state.get("events", 0) - c.state.get(
        "session_seq", c.state.get("resumed_seq", 0)) >= limit


def checkpoint(c):
    name = st.SESSION_NAMES[c.state.get("session", "S1")]
    return {"code": NEXT_BOUNDARY,
            "ACTION": "checkpoint: run AFTER, give the user its message, stop",
            "REPORT": [(f"{name} has run long enough that a fresh session is cheaper; "
                        "it continues from here.")],
            "AFTER": [c.cmd("handoff", "--checkpoint")],
            "RULE": "this session reached its checkpoint event count"}


# ---------------------------------------------------------------- Phase 2

def phase2(c):
    start = c.start(2)
    define = c.last("define", after=start, mode="write")
    if define is None:
        return spawn(c, "define", "write", rule="Phase 2 starts with the Define agent")
    jira = jira_step(c, "in_progress", "jira-in-progress")
    if jira:
        return jira
    review = review_loop(c, "define-reviewer", "define", c.ad / "SPEC.md", 1,
                         define["seq"])
    if review:
        return review
    c.finish(2, f"FITS, high risk: {'yes' if c.state.get('high_risk') else 'no'}")
    return None


def jira_step(c, key, step):
    ticket = c.state["task"].get("ticket")
    if not ticket or ticket == "none":
        return None
    choice = c.gate("jira")
    if choice is None:
        name = c.state["settings"].get("jira_states", {}).get(key, JIRA_DEFAULTS[key])
        return ask(c, "Jira", [(f"Define confirmed the task fits one PR. Move {ticket} to "
                               f"`{name}` now?")],
                   [cmd_review.question("Jira", f"Move {ticket} to {name}?",
                                        ["Move it", "Leave Jira alone", "Stop"])],
                   [("Move it", c.cmd("gate", "jira", "proceed")),
                    ("Leave Jira alone", c.cmd("gate", "jira", "leave")),
                    ("Stop", c.cmd("gate", "jira", "stop"))],
                   "a ticket exists and the size check says FITS")
    if choice["choice"] != "proceed" or c.mark(step):
        return None
    name = c.state["settings"].get("jira_states", {}).get(key, JIRA_DEFAULTS[key])
    return action(f"move Jira ticket {ticket} to `{name}` with the Atlassian MCP tools "
                  "(references/gates-and-jira.md, _Moving a ticket_); never edit the ticket. If it "
                  "can't be moved, tell the user and run "
                  f"`{c.cmd('mark', step, '--value', 'skipped')}` instead of the AFTER line",
                  f"Jira milestone {step}",
                  AFTER=[c.cmd("mark", step)])


def review_loop(c, reviewer, author, target, consumer, after):
    """Define or plan review: review, apply the FIX blocks, re-review (a round).

    A CLEAN review's FIX blocks (should-fix and nits) are applied once, with no
    re-review and no round; if they don't apply, the author revises (no round)."""
    review = c.last(reviewer, after=after)
    if review is None:
        return spawn(c, reviewer, rule=f"the first {reviewer} pass is free")
    clean = review["next"] == "CLEAN"
    fix = review["data"].get("fix_file", "none")
    if clean and fix in NONE:
        return None
    spend_id = f"{reviewer}-{review['n']}"
    revised = [r for r in c.recs(author, after=review["seq"], mode="revise")
               if r.get("sets", {}).get("fix_file") == fix]
    if revised:
        return None if clean else re_review(c, reviewer, consumer, spend_id, fix)
    if fix in NONE:
        return stop([(f"{reviewer} #{review['n']} found {review['data'].get('blockers')} "
                     "blocker(s) but wrote no FIX block. Tell the user; the review is "
                     f"in its reply and {c.ad}.")], "blockers with nothing to apply")
    if apply_once(c, target, fix) == "applied":
        return None if clean else re_review(c, reviewer, consumer, spend_id, fix)
    return spawn(c, author, "revise", {"fix_file": fix},
                 rule=f"{Path(fix).name} did not apply as written: its author revises "
                      f"{target.name} " + ("(no round: the review was clean)" if clean
                                           else "(the re-review after it spends the round)"))


def apply_once(c, target, fix):
    """Apply a FIX file to `target` once; `applied` or `no-match`, recorded."""
    key = str(Path(fix).resolve())
    outcome = c.state.setdefault("fixes", {}).get(key)
    if outcome is None:
        c.would(f"apply the FIX blocks in {fix} to {target.name}",
                "a reviewer wrote FIX blocks: next applies them")
        blocks, failed = cmd_checks.apply_fix_file(target, fix)
        outcome = {"outcome": "applied" if blocks and not failed else "no-match",
                   "seq": c.seq(), "failed": failed}
        c.state["fixes"][key] = outcome
        c.dirty = True
        if outcome["outcome"] == "applied" and Path(target).name == "SPEC.md":
            try:  # a fix can add a Security/Compliance criterion: the gate turns on
                if cmd_checks.rederive_risk(c.state, target):
                    st.add_note(c.state, "SPEC.md gained a Security/Compliance "
                                "criterion: high risk, post-plan gate on")
            except art.ArtifactError:
                pass  # SPEC.md is checked when it is used
    return outcome["outcome"]


def re_review(c, reviewer, consumer, spend_id, fix):
    budget = c.spend(consumer, spend_id, f"{reviewer} re-review")
    if budget is None:
        return exhausted(c, consumer, f"no round left for a {reviewer} re-review",
                         f"The open blockers are in {fix}.")
    return spawn(c, reviewer, rule="the fixes changed the file: review it again "
                 f"(consumer {consumer})", budget=budget)


# ---------------------------------------------------------------- Phase 3

def phase3(c):
    start = c.start(3)
    plan = c.last("planner", after=start, mode="write")
    if plan is None:
        return spawn(c, "planner", "write", rule="Phase 3 starts with the planner")
    review = review_loop(c, "plan-reviewer", "planner", c.ad / "IMPLEMENTATION.md", 2,
                         plan["seq"])
    if review:
        return review
    reviewed = c.last("plan-reviewer", after=plan["seq"])
    tester = acceptance_step(c, reviewed["seq"])
    if tester:
        return tester
    if c.state["settings"].get("post_plan_gate"):
        gate = post_plan_gate(c, reviewed["seq"])
        if gate:
            return gate
    c.finish(3)
    return None


def acceptance_step(c, after):
    tester = c.last("acceptance-tester", after=after)
    if tester is None:
        return spawn(c, "acceptance-tester", "write",
                     {"scope": "ALL CONDITIONS"},
                     rule="the acceptance tester writes checks once the plan is reviewed")
    ambiguous = str(tester["data"].get("ambiguous", "none")).strip()
    if ambiguous.lower() not in ("none", ""):
        define = c.last("define", after=tester["seq"], mode="revise")
        if define is None:
            return spawn(c, "define", "revise", {
                "ambiguous": f"conditions {ambiguous}; both readings, one line each, are "
                             f"in {c.ad}/acceptance/AMBIGUOUS.md"},
                rule="the acceptance tester found a condition that reads two ways: "
                     "Define decides which is meant")
        if define["data"].get("reading") == "other":
            budget = c.spend(2, f"acceptance-tester-{tester['n']}", "tester re-spawn")
            if budget is None:
                return exhausted(c, 2, "no round left to rewrite the checks")
            return spawn(c, "acceptance-tester", "write", {
                "scope": f"ONLY conditions {ambiguous}: SPEC.md now says which reading "
                         "is meant, and it is not the one your checks test"},
                rule="Define chose the other reading: rewrite those checks", budget=budget)
    gaps = manifest_gaps(c)
    if gaps:
        ids, lines = gaps
        budget = c.spend(2, f"acceptance-tester-{tester['n']}", "tester re-spawn")
        if budget is None:
            return exhausted(c, 2, "no round left for the acceptance gaps",
                             "Gaps: " + "; ".join(lines))
        return spawn(c, "acceptance-tester", "write", {
            "scope": f"ONLY conditions {', '.join(ids)}: " + "; ".join(lines)},
            rule="check-manifest found gaps in the tester's return (consumer 2)",
            budget=budget)
    return None


def manifest_gaps(c):
    """(condition ids, gap lines) from check-manifest, or None."""
    code, out, err = run_autodev(c, "check-manifest", "--json")
    if code == 0:
        return None
    try:
        data = json.loads(out)
    except ValueError:
        data = None
    data = data if isinstance(data, dict) else {}
    ids = [i.strip() for i in str(data.get("respawn", "")).split(",") if i.strip()]
    if code != 1 or data.get("result") != "GAPS" or not ids:
        # MALFORMED (or anything else) is a broken artifact, never a round.
        raise art.ArtifactError(
            f"check-manifest did not check the acceptance tester's return (exit {code}, "
            f"{data.get('result') or 'no result'}): "
            f"{data.get('message') or (err or out).strip()}")
    return ids, data.get("gap", [])


def post_plan_gate(c, after):
    gate = c.gate("post-plan")
    if gate and gate["choice"] == "revise":
        revised = c.last("planner", after=gate["seq"], mode="revise")
        if revised is None:
            return spawn(c, "planner", "revise", {"direction": gate["reason"] or
                                                  "the user asked for changes"},
                         rule="the user chose to revise the plan (no round is spent)")
        if revised["data"].get("entry_points_changed") == "yes" and \
                c.last("acceptance-tester", after=revised["seq"]) is None:
            return spawn(c, "acceptance-tester", "repair", {
                "scope": "ALL CONDITIONS whose checks call an entry point the revised "
                         "plan changed",
                "report": f"the plan was revised at the user's request and its entry "
                          f"points changed: see {c.ad}/IMPLEMENTATION.md"},
                rule="a plan revision changed the checks' entry points (no round)")
    latest = max([e["seq"] for e in c.recs(("planner", "acceptance-tester"), after=after)]
                 + [after])
    if gate is None or (gate["choice"] == "revise" and gate["seq"] < latest):
        return gate_question(c, "post-plan", {
            "Approve & build": c.cmd("gate", "post-plan", "proceed"),
            "Revise plan (tell me what to change)":
                c.cmd("gate", "post-plan", "revise", "--reason", "<what the user said>"),
            "Stop": c.cmd("gate", "post-plan", "stop")},
            "the post-plan gate is on (HIGH_RISK, or the config)")
    return None


def gate_question(c, gate, answers, rule):
    builder = {"post-plan": cmd_review.post_plan_summary, "pr": cmd_review.pr_summary,
               "main": cmd_review.main_summary}[gate]
    ns = type("Args", (), {"pr": None, "dir": c.dir, "json": False})()
    try:
        lines, extra = builder(c.state, c.ad, ns)
    except Fail as exc:
        if exc.code == CANNOT_RUN:
            raise
        if gate == "pr" and exc.token == "STALE":
            return stale_again(c, str(exc))
        return stop([f"The {gate} gate's checks failed, so it can't be asked: {exc}"],
                    f"a {gate} gate precondition failed")
    questions = [cmd_review.question("Gate", f"{gate} gate: how do you want to proceed?",
                                     cmd_review.GATE_OPTIONS[gate])] + extra
    pairs = [(label, answers[label]) for label in cmd_review.GATE_OPTIONS[gate]]
    for triage in extra:  # one answer per pre-existing security finding
        for label, value in cmd_review.TRIAGE_VALUES.items():
            pairs.append((f"{triage['header']}: {label}",
                          c.cmd("mark", f"triage-{triage['header']}", "--value", value)))
    return ask(c, f"the {gate} gate", lines, questions, pairs, rule)


# ---------------------------------------------------------------- Phase 4

def phase4(c):
    start = c.start(4)
    coder = c.last("coder", after=start)
    if coder is None:
        return spawn(c, "coder", "build", rule="Phase 4: the coder builds from the plan")
    result = loop_step(c, start, 3, "phase5", first=None)
    if result is DONE_MARK:
        c.finish(4)
        return None
    return result


# ---------------------------------------------------------------- Phases 5 and 6:
# the build-verify loop

DONE_MARK = object()


def loop_step(c, start, consumer, scope, first, files=None, after_change="a correction"):
    """One step of the coder / cleanup / verifier loop after `start`.

    Returns an action, or DONE_MARK once the verifier finds everything met after
    the cleanup agent has run on the latest code. In Phase 4 (scope `phase5`,
    `first` None) it ends as soon as the coder has built without a block.
    """
    recs = c.recs(LOOP, after=start)
    if not recs:
        return first()
    latest = recs[-1]
    worker, nxt, n = latest["worker"], latest["next"], latest["n"]
    in_phase4 = first is None
    if worker == "coder":
        if nxt == "BLOCKED":
            return blocked_step(c, latest, consumer)
        if in_phase4:
            return DONE_MARK
        if scope != "phase5" or c.recs("cleanup", after=start):
            return cleanup_spawn(c, scope, files, "the code changed: the cleanup agent "
                                 "simplifies it and runs the quality gate (no round)")
        return verifier_spawn(c, after_change)
    if worker == "planner":
        coder = c.last("coder", after=start, before=latest["seq"])
        return blocked_step(c, coder, consumer)
    if worker == "acceptance-tester":
        trigger = next((r for r in reversed(recs[:-1])
                        if r["worker"] != "acceptance-tester"), None)
        if trigger and trigger["worker"] == "planner":
            coder = c.last("coder", after=start, before=trigger["seq"])
            return blocked_step(c, coder, consumer)
        if trigger and trigger["worker"] == "cleanup":
            if nxt == "STANDS":
                return stop([("The quality gate fails on an acceptance check, and the "
                             "acceptance tester ruled the check right as written, so "
                             "neither can fix it. Tell the user both sides: the cleanup "
                             f"agent's reports in {c.ad}/lint/ and the tester's reply.")],
                            "the tester ruled a check that fails the quality gate stands")
            return cleanup_spawn(c, scope, files, "the repaired check passes the gate now? "
                                 "Run the cleanup agent again (no round)")
        if trigger and trigger["worker"] == "verifier" and trigger["next"] in (
                "CORRECT", "INSTALL_CONFLICT"):
            return coder_correction(c, f"{c.ad}/evidence/corrections.md", None,
                                    "the checks are repaired; now the code's correction "
                                    "(the round is already spent)")
        if in_phase4:
            return DONE_MARK if c.last("coder", after=start)["next"] == "BUILT" else None
        if nxt == "STANDS":
            return verifier_spawn(c, stands_note(latest))
        if scope == "phase5" and c.recs("cleanup", after=start):
            # The repaired check is a changed file: the gate runs on it before the
            # re-check, so Phase 5 never ends on stale lint reports.
            return cleanup_spawn(c, scope, files, "an acceptance check was repaired: the "
                                 "cleanup agent runs the quality gate on it (no round)")
        return verifier_spawn(c, "an acceptance-check repair")
    if worker == "cleanup":
        if nxt == "GREEN":
            if scope == "phase5" and not c.recs("verifier", after=start):
                return verifier_first(c, "the quality gate is green: the verifier's first "
                                      "pass checks the code that ships")
            return verifier_spawn(c, "the cleanup pass" if scope == "phase5" else
                                  after_change)
        if nxt == "RED":
            return stop([("The quality gate can't be made green; never ship a red build. "
                         f"Tell the user which checks fail: {c.ad}/lint/.")],
                        "the cleanup agent returned RED")
        budget = c.spend(consumer, f"cleanup-{n}", "acceptance-check repair")
        if budget is None:
            return exhausted(c, consumer, "no round left for an acceptance-check repair")
        return spawn(c, "acceptance-tester", "repair", {
            "scope": "ONLY the conditions whose checks fail the quality gate",
            "report": f"the quality gate fails on an acceptance check file: see the "
                      f"cleanup agent's reports in {c.ad}/lint/"},
            rule="an acceptance check fails the quality gate: the tester repairs it",
            budget=budget)
    # the verifier
    if nxt == "MUTATION_LEFT_CHANGES":
        return stop([("The mutation step may have left changes in the source; the tree "
                     "may not be the code that was built. Tell the user the paths the "
                     "verifier named; build nothing more on it.")],
                    "the verifier returned MUTATION_LEFT_CHANGES")
    if nxt == "ALL_MET":
        coder = c.last("coder", after=start)
        changed = coder
        # A repaired check changed the tree too. The tester's branch above already
        # sends it to cleanup; this covers a re-check briefed before 4.1.
        if scope == "phase5":
            repaired = c.last("acceptance-tester", after=start, mode="repair")
            if repaired and repaired["next"] != "STANDS" and (
                    not changed or repaired["seq"] > changed["seq"]):
                changed = repaired
        cleaned = c.recs("cleanup", after=changed["seq"] if changed else start)
        if (cleaned and cleaned[-1]["next"] == "GREEN") or (coder is None and scope != "phase5"):
            return DONE_MARK
        return cleanup_spawn(c, scope, files, "every condition is met: the cleanup agent "
                             "simplifies and runs the quality gate (no round)")
    _token, fields = cmd_checks.eval_decision(
        c.ad, install_conflict=nxt == "INSTALL_CONFLICT")
    repair = [x.strip() for x in fields.get("repair", "").split(",") if x.strip()]
    stood, unnamed = stood_conditions(c, start)
    again = list(repair) if unnamed else [x for x in repair if x in stood]
    if again:  # never a second round on a check the tester ruled right
        if not fields.get("correct"):
            return stop([(f"The verifier still judges the checks of condition(s) "
                         f"{', '.join(again)} defective after the acceptance tester ruled "
                         "they stand as written. Tell the user both sides: "
                         f"{c.ad}/SPEC_EVAL.md (Defective acceptance checks) and the "
                         "tester's reply. No round is spent on it.")],
                        "the verifier and the acceptance tester disagree about a check")
        fields["repair"] = ", ".join(x for x in repair if x not in again)
    budget = c.spend(consumer, f"verifier-{n}", "correction after verification")
    if budget is None:
        return exhausted_loop(c, consumer, fields)
    if fields.get("repair") and c.last("acceptance-tester", after=latest["seq"]) is None:
        return spawn(c, "acceptance-tester", "repair", {
            "scope": f"ONLY conditions {fields['repair']}: the verifier judged their checks "
                     "defective",
            "report": f"{c.ad}/SPEC_EVAL.md, section Defective acceptance checks"},
            rule="defective checks are repaired first (the same round)", budget=budget)
    return coder_correction(c, f"{c.ad}/evidence/corrections.md", budget,
                            f"the verifier found open items (consumer {consumer})")


def exhausted_loop(c, consumer, fields):
    if consumer == 4 and not c.p6.get("verified_sha"):
        c.p6["exhausted"] = {"consumer": consumer, "seq": c.seq(),
                             "open": fields.get("correct", [])}
        c.dirty = True
        return DONE_MARK
    return exhausted(c, consumer, "no round left for a correction",
                     "Unmet: " + "; ".join(fields.get("correct", [])))


def stood_conditions(c, start):
    """(conditions, unnamed) the acceptance tester ruled right (STANDS) in this
    loop, after `start`. `unnamed` is true when a STANDS answered a scope that
    names no condition (a PR comment, a review finding): then any repair the
    verifier asks for in this loop is the same disagreement."""
    stood, unnamed = set(), False
    for r in c.recs("acceptance-tester", after=start, mode="repair"):
        if r["next"] != "STANDS":
            continue
        match = ONLY_RE.match(r.get("sets", {}).get("scope", ""))
        if match:
            stood |= {x.strip() for x in match.group(1).split(",") if x.strip()}
        else:
            unnamed = True
    return stood, unnamed


def stands_note(tester):
    """What the verifier's re-check is told after the tester answered STANDS."""
    match = ONLY_RE.match(tester.get("sets", {}).get("scope", ""))
    which = f"the checks of conditions {match.group(1)}" if match else "the questioned checks"
    return (f"the acceptance tester's ruling: {which} stand as written (right against "
            "SPEC.md); judge them as written, not as defective")


def coder_correction(c, corrections_file, budget, rule):
    return spawn(c, "coder", "correction", {"corrections_file": corrections_file},
                 rule=rule, budget=budget)


def cleanup_spawn(c, scope, files, rule):
    sets = {"scope": scope}
    if scope in ("review-fix",):
        sets["files"] = ", ".join(files or []) or "none"
    return spawn(c, "cleanup", sets=sets, rule=rule)


def verifier_spawn(c, what_changed):
    return spawn(c, "verifier", sets={"mode": "re-check", "what_changed": what_changed},
                 rule=f"re-check after {what_changed} (a check, no round)")


def blocked_step(c, coder, consumer):
    """The coder stopped steps: the planner decides; then the coder again."""
    planner = c.last("planner", after=coder["seq"], mode="blocked")
    if planner is None:
        listed = c.ad / "blocked" / f"coder-{coder['n']}.md"
        return spawn(c, "planner", "blocked", {"blocked": f"the steps listed in {listed}"},
                     rule="the coder returned BLOCKED: the planner decides why")
    if planner["next"] == "SPEC_IMPOSSIBLE":
        return stop([("The planner judged the spec impossible to meet as written. Tell "
                     f"the user its reasons (its reply, and {c.ad}/IMPLEMENTATION.md).")],
                    "the planner returned SPEC_IMPOSSIBLE")
    budget = c.spend(consumer, f"planner-{planner['n']}", "blocked step re-dispatched")
    if budget is None:
        return exhausted(c, consumer, "no round left to re-dispatch a blocked step")
    if planner["data"].get("entry_points_changed") == "yes" and \
            c.last("acceptance-tester", after=planner["seq"]) is None:
        return spawn(c, "acceptance-tester", "repair", {
            "scope": "ALL CONDITIONS whose checks call an entry point the revised plan "
                     "changed",
            "report": f"the plan was revised after a blocked step: see {c.ad}/"
                      "IMPLEMENTATION.md"},
            rule="the revised plan changed the checks' entry points", budget=budget)
    if c.last("coder", after=planner["seq"]) is None:
        return spawn(c, "coder", coder.get("mode") or "build", coder.get("sets", {}),
                     rule=f"the planner returned {planner['next']}: the coder goes again "
                          f"(consumer {consumer})", budget=budget)
    return None


# ---------------------------------------------------------------- Phase 5

def verifier_first(c, rule):
    return spawn(c, "verifier", sets={"mode": "first pass"}, rule=rule)


def install_checks(c):
    """Install every sealed acceptance check at its path in the worktree, so the
    cleanup agent's quality gate runs on them before the verifier's first pass.

    Returns the paths already there with other content: then nothing is
    installed and the verifier goes first, as before 4.1, to report the
    conflict. Writes acceptance/INSTALLED (the paths, one per line), which
    tells the verifier the checks went in before cleanup."""
    marker = c.ad / "acceptance" / "INSTALLED"
    if marker.exists():  # installed already: a change since is an edit the audit records
        return []
    wt = c.state["worktree"]
    pairs = cmd_checks.sealed_pairs(c.ad, wt)
    conflicts = [str(t.relative_to(wt)) for s, t in pairs
                 if t.exists() and t.read_bytes() != s.read_bytes()]
    if conflicts:
        return conflicts
    c.would("install the sealed acceptance checks in the worktree",
            "the code is built: the checks go in before the cleanup agent's gate")
    _written, conflicts = cmd_checks.install_sealed(c.ad, wt)
    if conflicts:  # a file appeared since the check above
        return conflicts
    marker.write_text("".join(f"{t.relative_to(wt)}\n" for _, t in pairs), encoding="utf-8")
    return []


def phase5_first(c):
    """Phase 5 runs cleanup before the verifier's first pass, so the happy path
    verifies once, on the code that ships."""
    if install_checks(c):
        return verifier_first(c, "a sealed check's path holds another file: the "
                              "verifier's first pass goes first and reports it")
    return cleanup_spawn(c, "phase5", None, "the code is built and the sealed checks are "
                         "installed: the cleanup agent simplifies it and runs the quality "
                         "gate before the verifier's first pass (no round)")


def phase5(c):
    start = c.start(5)
    result = loop_step(c, start, 3, "phase5", first=lambda: phase5_first(c))
    if result is not DONE_MARK:
        return result
    stale = check_fresh(c, "--phase", "5")  # could not run: exit 2, never "stale"
    if stale:
        return stop([("A Phase 5 report is stale right after its own re-run: something "
                     "rewrites the code on every run. Tell the user the files below."),
                     stale], "check-fresh --phase 5 found a stale report")
    c.finish(5)
    return None


# ---------------------------------------------------------------- Phase 6

def phase6(c):
    c.start(6)
    p6 = c.p6
    p6.setdefault("passes", [])
    p6.setdefault("corrections", [])
    result = open_correction(c)
    if result is not None:
        return result
    if not p6["passes"]:
        stale = check_fresh(c, "--phase", "5")
        if stale and not any(k["entry"] == "outside" for k in p6["corrections"]):
            return start_correction(c, "outside", 4, None, None,
                                    "the code changed outside the pipeline since S2: "
                                    "re-run the quality gate and the verifier first")
        return start_pass(c, "first", None, "Phase 6a: the code review panel reviews "
                          "the whole change")
    review = review_step(c, p6["passes"][-1])
    if review is not None:
        return review
    return ship_step(c)


def open_correction(c):
    corrections = c.p6["corrections"]
    if not corrections:
        return None
    corr = corrections[-1]
    passes = c.p6["passes"]
    if corr.get("closed") or (passes and passes[-1]["seq"] > corr["seq"]):
        return None
    scope = "after-commit" if corr["after_commit"] else (
        "outside" if corr["entry"] == "outside" else "review-fix")
    if corr.get("checks") and corr.get("file"):
        # The tester went first; the coder's part runs in the same round.
        tester = c.last("acceptance-tester", after=corr["seq"])
        if tester and c.last("coder", after=corr["seq"]) is None:
            return coder_correction(c, corr["file"], None, "the checks are settled; now "
                                    "the code's part of the correction (the same round)")
    files = snapshot_files(c, corr) if scope == "review-fix" else None
    result = loop_step(c, corr["seq"], corr["consumer"], scope,
                       first=lambda: first_of(c, corr), files=files,
                       after_change="a Phase 6 correction")
    if result is not DONE_MARK:
        return result
    corr["closed"] = True
    c.dirty = True
    # Even when the budget ran out, the code changed: reviews are free, and the
    # gate needs reports on the code as it is.
    if corr.get("since"):
        # Committed outside changes: a working-tree pass would see nothing. The
        # working tree against `since` holds the commits and any edit the
        # correction made on top (cleanup, the coder), new files included.
        if not c.readonly:
            cmd_checks.git_add_intent(c.wt)
        files = [f for f in git(c.wt, "diff", "--name-only", corr["since"]).splitlines()
                 if f and not f.startswith(".auto-dev/")]
        return start_pass(c, "outside", files, "the outside commits are re-checked: the "
                          "panel reviews what they changed", since=corr["since"])
    if corr["entry"] == "outside":
        return start_pass(c, "first", None, "the outside changes are re-checked: the "
                          "panel reviews the whole change")
    if corr["after_commit"]:
        if unchanged(c):  # nothing to review or commit: the verified commit stands
            corr["unchanged"] = True
            mark_committed(c, "the correction after the commit changed nothing")
            return None
        return start_pass(c, "after-commit", None, "the correction is verified: the "
                          "panel reviews it before it is committed")
    return start_pass(c, "review-fix", snapshot_files(c, corr),
                      "the correction is verified: the panel reviews the files it changed")


def first_of(c, corr):
    if corr["entry"] == "outside":
        return spawn(c, "cleanup", sets={"scope": "outside"},
                     rule="the code changed outside the pipeline: the quality gate runs "
                          "again (no round)")
    if corr.get("checks"):  # acceptance checks first: the tester's repair mode
        return spawn(c, "acceptance-tester", "repair", dict(corr["checks"]),
                     rule="a finding questions an acceptance check: the tester decides "
                          "first" + (", then the coder" if corr.get("file") else ""),
                     budget=corr.get("budget"))
    return coder_correction(c, corr["file"], corr.get("budget"), corr["rule"])


def closed_correction(c, spend_id):
    """The closed correction paid for as `spend_id`, or None."""
    return next((k for k in c.p6.get("corrections", [])
                 if k.get("spend_id") == spend_id and k.get("closed")), None)


def unchanged(c):
    """Whether the tree is the verified commit's: nothing to review or commit."""
    sha = c.p6.get("verified_sha")
    if not sha:
        return False
    add, remove = changed_paths(c.wt)
    return not add and not remove and git(c.wt, "rev-parse", "HEAD").strip() == sha


def mark_committed(c, why):
    """The verified commit holds the code as it is: no commit is needed."""
    c.p6["commit_seq"] = c.seq()
    st.add_note(c.state, f"{why}: commit {c.p6.get('verified_sha')} stands")
    c.dirty = True


def start_correction(c, entry, consumer, file, spend_id, rule, checks=None, why="",
                     since=None):
    """A Phase 6 correction: the coder gets `file` (when given); `checks` (scope,
    report) sends acceptance checks to the tester's repair mode first. `why`
    goes into the report when no round is left (the red checks, for CI).
    `since` (an outside correction only): the outside changes are the commits
    after it, so the review pass that follows reviews `git diff <since>`."""
    after_commit = bool(c.p6.get("verified_sha"))
    budget = None
    if spend_id:
        budget = c.spend(consumer, spend_id, f"{entry} correction")
        if budget is None and after_commit:
            return exhausted(c, consumer, "no round left for a correction after the "
                             "commit", (f"{why} " if why else "") + f"What is open: {file}")
        if budget is None:
            c.p6["exhausted"] = {"consumer": consumer, "seq": c.seq(), "open": [file]}
            c.dirty = True
            return review_step(c, c.p6["passes"][-1]) or ship_step(c)
    # After the budget check (in memory only under --explain or a probe), so a
    # budget-exhausted stop is never hidden behind the step that would follow.
    c.would(f"start a {entry} correction ({file or (checks or {}).get('report')})", rule)
    snapshot = None
    if not after_commit and entry != "outside":
        cmd_checks.git_add_intent(c.wt)
        snapshot = cmd_review.print_tree(c.wt)
    corr = {"entry": entry, "consumer": consumer, "file": file, "checks": checks,
            "seq": c.seq(), "after_commit": after_commit, "snapshot": snapshot,
            "rule": rule, "budget": budget, "spend_id": spend_id}
    if since:
        corr["since"] = since
    c.p6["corrections"].append(corr)
    c.dirty = True
    return first_of(c, corr)


def snapshot_files(c, corr):
    snap = corr.get("snapshot")
    if not snap:
        return []
    if not c.readonly:
        cmd_checks.git_add_intent(c.wt)
    tree = cmd_review.print_tree(c.wt)
    return [f for f in git(c.wt, "diff", "--name-only", snap, tree).splitlines()
            if f and not f.startswith(".auto-dev/")]


def check_fresh(c, *extra):
    code, out, err = run([sys.executable, str(SCRIPTS / "check-fresh.py"), c.wt,
                          str(c.ad), *extra], check=False)
    if code == 2:
        raise Fail(f"check-fresh.py could not run: {err.strip()}", CANNOT_RUN, "ERROR")
    return (err or out).strip() if code else ""


def start_pass(c, scope, files, rule, since=None):
    n = c.p6.get("review_pass", 0) + 1
    c.would(f"start code-review pass {n} ({scope}) and spawn the panel", rule)
    c.p6["review_pass"] = n
    (c.ad / "review" / f"pass-{n}").mkdir(parents=True, exist_ok=True)
    cmd_checks.git_add_intent(c.wt)
    tree = cmd_review.print_tree(c.wt)
    effort = plan_effort(c)
    p = {"n": n, "scope": scope, "files": files or [], "tree": tree, "seq": c.seq(),
         "effort": effort}
    if since:
        p["since"] = since
    c.p6["passes"].append(p)
    st.add_note(c.state, f"code-review pass {n}: the reviewers run at effort {effort}")
    c.dirty = True
    return spawn_many(c, [("code-reviewer", "review", reviewer_sets(scope, files, slot,
                                                                    since))
                          for slot in SLOTS], rule)


def reviewer_sets(scope, files, slot, since=None):
    sets = {"reviewer": slot, "scope": scope}
    if scope in ("review-fix", "outside"):
        sets["files"] = ", ".join(files or []) or "none"
    if scope == "outside":
        sets["since"] = since or "HEAD"
    return sets


def review_step(c, p):
    """The panel, the judge, the re-votes, then the security review, for pass p."""
    reviews = c.recs("code-reviewer", after=p["seq"], mode="review", ok=False)
    respawn, usable = [], []
    for slot in SLOTS:
        mine = [r for r in reviews if r.get("sets", {}).get("reviewer") == slot]
        if any(r["status"] == "ok" for r in mine):
            if "## Findings" in _read(c.ad / "review" / f"pass-{p['n']}" / f"{slot}.md"):
                usable.append(slot)
        elif len(mine) == 1:
            respawn.append(slot)
    if respawn:
        return spawn_many(c, [("code-reviewer", "review",
                               reviewer_sets(p["scope"], p["files"], slot,
                                             p.get("since")))
                              for slot in respawn],
                          "a code reviewer failed: it gets one re-spawn")
    judge = c.last("review-judge", after=p["seq"], mode="consolidate")
    if judge is None:
        if not usable:
            return stop([("No code reviewer wrote a usable report, twice. Tell the user; "
                         f"see {c.ad}/review/pass-{p['n']}/.")], "the panel produced nothing")
        return spawn(c, "review-judge", "consolidate", {
            "reviewers": ", ".join(usable), "scope": scope_text(p), "tree": p["tree"]},
            rule="the panel is done: the judge consolidates its reports")
    after = judge["seq"]
    if judge["next"] == "REVOTE":
        result = revotes(c, p, judge)
        if result is not None:
            return result
        after = c.p6["votes"][str(p["n"])]
    spent_out = bool(c.p6.get("exhausted"))  # open findings go to the PR gate
    rows = open_must_fix(art.read(c.ad / "CODE_REVIEW.md"))
    if rows and not spent_out:
        checks = [r for r in rows if _category(r) == "acceptance-check"]
        spec = None
        if checks:  # a finding about a check goes to the tester, never the coder
            ids = ", ".join(r["ID"].strip() for r in checks)
            spec = {"scope": check_scope(c, checks),
                    "report": (f"{c.ad}/CODE_REVIEW.md, must-fix finding(s) {ids}: each "
                               "one's `### <id>` block says what is wrong with the check")}
        return must_fix(c, f"{c.ad}/review/pass-{p['n']}/corrections.md", f"pass-{p['n']}",
                        f"pass {p['n']} left {len(rows)} must-fix finding(s) open",
                        checks=spec, coder=len(checks) < len(rows))
    sec = c.last(("security-reviewer", "security-reviewer-sensitive"), after=after)
    if sec is None:
        return security_spawn(c)
    data = sec["data"]
    if _int(data.get("must_fix")) or _int(data.get("pre_existing")):
        verify = c.last("review-judge", after=sec["seq"], mode="security-verify")
        if verify is None:
            return spawn(c, "review-judge", "security-verify",
                         rule="the judge verifies every High or Medium security finding")
        if confirmed_security(c) and not spent_out:
            return must_fix(c, f"{c.ad}/review/security-corrections.md",
                            f"security-{sec['n']}", "the security review found a "
                            "confirmed must-fix finding")
    return None


def revotes(c, p, judge):
    pass_dir = c.ad / "review" / f"pass-{p['n']}"
    votes = c.p6.setdefault("votes", {})
    if str(p["n"]) in votes:
        return None
    text = art.read(c.ad / "CODE_REVIEW.md")
    pending = cmd_review.pending_rows(text)
    plan = cmd_review.vote_plan(pass_dir, pending)
    cast = c.recs("code-reviewer", after=judge["seq"], mode="re-vote", ok=False)
    jobs, gave_up = [], []
    for slot, ids in sorted(plan.items()):
        mine = [r for r in cast if r.get("sets", {}).get("reviewer") == slot]
        tries = [r for r in mine if r.get("seq", 0) > c.resumed()]
        if any(r["status"] == "ok" for r in mine):
            missing = unvoted(pass_dir, slot, ids)
            if not missing:
                continue
            if len(tries) >= 2:  # voted, but not on everything, twice
                gave_up.append(f"{slot} (no vote on {', '.join(missing)})")
                continue
        elif len(tries) >= 2:
            gave_up.append(f"{slot} (failed twice)")
            continue
        rows = [r for r in pending if r["ID"].strip() in ids]
        findings = "\n".join(f"- {r['ID'].strip()}: {r.get('Finding', '')} at "
                             f"{r.get('Location', '')} ({r.get('Category', '')})"
                             for r in rows)
        jobs.append(("code-reviewer", "re-vote", {"reviewer": slot, "findings": findings}))
    if jobs:
        return spawn_many(c, jobs, "lone findings go to the other reviewers for a re-vote")
    if gave_up:
        return stop([("The code-review re-vote can't finish: re-voter "
                     f"{'; '.join(gave_up)}. The lone findings stay pending in "
                     f"{c.ad}/CODE_REVIEW.md. Tell the user; once the cause is fixed, "
                     "`auto-dev continue` spawns those re-voters again.")],
                    "a re-voter gave no usable vote twice")
    if pending:  # with no plan (under two usable reports) each stays advisory
        c.would("apply the re-votes to CODE_REVIEW.md", "every re-voter has voted")
        cmd_review.apply_vote_files(c.ad / "CODE_REVIEW.md", text, pass_dir, pending,
                                    votes_expected=bool(plan))
    votes[str(p["n"])] = c.seq()
    c.dirty = True
    return None


def unvoted(pass_dir, slot, ids):
    """The findings `slot` was given that its VOTES-<slot>.md has no vote on."""
    try:
        _, missing = cmd_review.read_votes(pass_dir, {slot: ids})
    except art.ArtifactError:
        return list(ids)  # a malformed votes file counts as no vote
    return [m.split()[0] for m in missing]


def security_spawn(c):
    agent = cmd_checks.security_agent(c.ad)
    worker = agent.split(":", 1)[1]
    leads = (art.find_section(art.read(c.ad / "CODE_REVIEW.md"), "Security leads")
             or "").strip() or "none"
    result = spawn(c, worker, sets={"leads": leads}, agent=agent,
                   rule="the panel left nothing open: the security review covers the "
                        "whole change")
    c.p6["security_run"] = c.p6.get("security_run", 0) + 1
    return result


def confirmed_security(c):
    text = art.read(c.ad / "SECURITY_REVIEW.md")
    _, rows = art.first_table(art.find_section(text, "Findings") or "",
                              ("ID", "Verdict", "Status"), "SECURITY_REVIEW.md")
    return sum(1 for r in rows if r["Verdict"].strip().lower() == "must-fix"
               and r["Status"].strip().lower().startswith("open")
               and r.get("Verified", "").strip().lower() != "refuted")


def must_fix(c, file, tag, rule, checks=None, coder=True):
    previous = c.p6["corrections"][-1] if c.p6["corrections"] else None
    after_commit = bool(c.p6.get("verified_sha"))
    consumer = previous["consumer"] if after_commit and previous else 4
    spend_id = f"{tag}-c{consumer}"
    if closed_correction(c, spend_id):
        # It ran and changed nothing (a change starts a new pass): never again.
        return stop([(f"The correction for {tag}'s open finding(s) changed nothing, so "
                     f"they are still open ({file}). Tell the user; the verified commit "
                     "is unchanged.")], "a correction changed nothing")
    return start_correction(c, "review", consumer, file if coder else None, spend_id,
                            rule, checks=checks)


def open_must_fix(text):
    """CODE_REVIEW.md's open must-fix rows."""
    for header, rows in art.tables(art.find_section(text, "Must-fix") or ""):
        if "Status" in header:
            return [r for r in rows if r.get("Status", "").strip().startswith("open")]
    return []


def _category(row):
    return row.get("Category", "").strip().strip("`").lower()


def check_scope(c, rows):
    """The tester's scope for findings about checks: their conditions, by the
    check files the findings' Locations name."""
    try:
        manifest, _ = art.manifest(c.ad / "acceptance" / "MANIFEST.md")
    except art.ArtifactError:
        manifest = []
    ids = set()
    for row in rows:
        where = re.sub(r":\d+$", "", row.get("Location", "").strip().strip("`"))
        ids |= {m["#"].strip() for m in manifest
                if art.check_path(m["Check (path :: test name)"]) == where}
    if ids:
        return (f"ONLY conditions {', '.join(sorted(ids, key=cmd_checks.sort_key))}: the "
                "code review found their checks wrong")
    return "ONLY the conditions whose checks the code-review findings in the report name"


def scope_text(p):
    if p["scope"] == "review-fix":
        return "only the files a correction changed: " + (", ".join(p["files"]) or "none")
    if p["scope"] == "outside":
        return (f"the commits pushed to the PR branch outside the pipeline (`git diff "
                f"{p.get('since', 'HEAD')}`): " + (", ".join(p["files"]) or "none"))
    return {"first": "the whole change (the uncommitted working tree against HEAD)",
            "after-commit": "the uncommitted correction (the working tree against HEAD)",
            }.get(p["scope"], p["scope"])


# ---------------------------------------------------------------- Phase 6: shipping

def ship_step(c):
    p6 = c.p6
    if p6.get("merged"):  # nothing before the merge runs again on a merged branch
        return main_step(c, p6["merged"])
    sha = p6.get("verified_sha")
    corrections = p6["corrections"]
    last_fix = next((k for k in reversed(corrections) if k["after_commit"]), None)
    needs_commit = sha is None or (last_fix and last_fix["seq"] > p6.get("commit_seq", 0))
    if needs_commit and sha and unchanged(c):
        mark_committed(c, "the correction after the commit changed nothing")
        needs_commit = False
    if needs_commit:
        if sha is None:
            gate = c.gate("pr", after=p6["passes"][-1]["seq"])
            if gate is None or gate["choice"] != "proceed":  # a hold re-asks on resume
                return pr_gate(c)
        return commit_step(c)
    if (c.mark("pushed") or {}).get("value") != sha:
        return action(f"push the branch: `git -C {q(c.wt)} push -u origin HEAD` (never "
                      "--force)", "the verified commit is not pushed yet",
                      AFTER=[c.cmd("mark", "pushed", "--value", sha)])
    if p6.get("published_sha") != sha:
        return body_step(c, sha)
    ci = ci_step(c, sha)
    if ci is not None:
        return ci
    jira = jira_step(c, "in_review", "jira-in-review")
    if jira:
        return jira
    human = human_step(c)
    if human:
        return human
    ready = c.mark("pr-ready")
    if not ready:
        return action(f"mark the PR ready for review: `gh pr ready {q(p6.get('pr'))}` "
                      f"(run in {q(c.wt)})", "the draft PR is checked and reviewed",
                      AFTER=[c.cmd("mark", "pr-ready")])
    if c.state["settings"].get("ci", "none") != "none" and \
            (p6.get("ci") or {}).get("seq", 0) < ready["seq"]:
        # Workflows that skip drafts run only now: watch CI once more.
        return ci_watch(c, "the PR was marked ready after CI was watched: workflows "
                        "that skip drafts run now")
    return main_step(c, sha)


def pr_gate(c):
    return gate_question(c, "pr", {
        "Open PR": c.cmd("gate", "pr", "proceed"),
        "Hold (don't push yet)": c.cmd("gate", "pr", "hold", "--reason", "<why>"),
        "Stop": c.cmd("gate", "pr", "stop", "--reason", "<why>")},
        "the reviews have settled: the PR gate")


def stale_twice(c, detail, since=None):
    """The stop for a result stale again right after its own re-run (nobody
    answered the PR gate or resumed since), or None. Commits brought in on top
    of a newly verified commit (`since`) are a new push, never a second run."""
    outside = next((k for k in reversed(c.p6["corrections"]) if k["entry"] == "outside"),
                   None)
    gate = c.gate("pr")
    asked = max(gate["seq"] if gate else 0, c.resumed())
    if not outside or outside["seq"] <= asked or (since and outside.get("since") != since):
        return None
    return stop([("A report is stale again right after its own re-run: something "
                 "rewrites the code on every run. Tell the user:"), detail],
                "stale twice running")


def stale_again(c, detail, since=None):
    """A result went stale: re-check the outside changes, unless that re-check
    itself just ran (stale_twice). `since`: the outside changes are commits on
    top of that one (see outside_push)."""
    twice = stale_twice(c, detail, since)
    if twice:
        return twice
    return start_correction(c, "outside", 4, None, None,
                            "the code changed outside the pipeline: re-check it",
                            since=since)


def commit_step(c):
    attempt = c.p6.get("commit_attempt")
    since = max([c.gate("pr")["seq"] if c.gate("pr") else 0]
                + [k["seq"] for k in c.p6["corrections"]])
    if attempt and attempt["seq"] > since:
        if attempt["result"] == "stale":
            return stale_again(c, "commit found stale results")
        return stop([(f"The commit step failed ({attempt['result']}). Tell the user what "
                     "`autodev.py commit` printed; nothing was pushed.")],
                    "the commit failed")
    # A commit made but not yet checked (`unverified_commit`) leaves a clean tree:
    # `commit` checks it without committing again, so it is offered as usual.
    if not c.p6.get("verified_sha") and not c.p6.get("unverified_commit"):
        add, remove = changed_paths(c.wt)
        if not add and not remove:
            return stop([("There is nothing to commit: the working tree holds no change "
                         "outside .auto-dev/. Tell the user; nothing was pushed.")],
                        "an empty change")
    return action(f"commit: run `{c.cmd('commit', '--message', '<type>(<scope>): <summary>')}`"
                  f", with a Conventional Commits subject you write for the change ({FILL})",
                  "the PR gate said proceed (or a correction is verified and reviewed)",
                  AFTER=[c.cmd("next")])


def body_step(c, sha):
    from . import cmd_pr  # imported here: cmd_pr imports this module's helpers
    body = c.p6.get("body") or {}
    # A description written before 4.0.2 has no quoted regions, so the lint
    # refuses an ID it quotes: write it again, unless a PR already carries it.
    if body.get("sha") != sha or ("quoted" not in c.p6 and not c.p6.get("pr")):
        c.would("generate the PR description for the verified commit",
                "the commit is pushed: the PR opens next")
        path = cmd_pr.generate(c.state, c.ad, sha)
        body = {"sha": sha, "path": str(path), "seq": c.seq()}
        c.p6["body"] = body
        c.dirty = True
    attempt = c.p6.get("publish_attempt")
    if attempt and attempt["seq"] > max(body["seq"], c.resumed()):
        # A WRITE line left goes back to the write step once; anything else stops.
        if attempt["result"] != "unwritten" or body.get("rewrite", attempt["seq"]) != \
                attempt["seq"]:
            return stop([(f"`pr publish` refused the PR description "
                          f"({attempt['result']}). Tell the user what it found:"),
                         *attempt.get("problems", []),
                         (f"The description is {body['path']}. Once the cause is "
                          "fixed (the description edited, or GitHub working again), "
                          "`auto-dev continue` publishes it again.")],
                        "pr publish was refused")
        if "rewrite" not in body:
            body["rewrite"] = attempt["seq"]
            c.dirty = True
        return write_body(c, body, "the description still holds a WRITE line")
    if c.p6.get("pr"):
        return action(f"publish the refreshed PR body: run `{c.cmd('pr', 'publish')}`",
                      "a new commit was pushed: the PR body describes the old one",
                      AFTER=[c.cmd("next")])
    return write_body(c, body, "the commit is pushed: the PR opens next")


def write_body(c, body, rule):
    return action(f"fill in the PR body {body['path']}: "
                  "replace every `<!-- WRITE: ... -->` line (references/S3-ship.md, "
                  "_The PR body_), in plain words for a "
                  "developer who has never heard of auto-dev; change nothing else. Then "
                  "run AFTER", rule, AFTER=[c.cmd("pr", "publish")])


def ci_watch(c, rule):
    return action(f"watch CI: run `{c.cmd('ci-watch')}` (it waits up to 9 minutes; "
                  "run it again while it says PENDING)", rule, AFTER=[c.cmd("next")])


def ci_step(c, sha):
    if c.state["settings"].get("ci", "none") == "none":
        return None
    ci = c.p6.get("ci") or {}
    rewatch = c.resumed() > ci.get("seq", 0)
    if ci.get("sha") != sha or ci.get("status") == "pending" or (rewatch and \
            ci.get("status") != "green"):
        return ci_watch(c, "CI has not settled on the pushed commit")
    if ci["status"] != "red":
        return None  # green, timeout or unavailable: the main gate says which
    triage = c.last("triager", after=ci["seq"], mode="ci")
    if triage is None:
        return spawn(c, "triager", "ci", {"failing": "\n".join(ci.get("failing", []))
                                          or "see `gh pr checks`"},
                     rule="CI is red: the triager reads the logs (you don't)")
    kind = triage["next"]
    red = "; ".join(ci.get("failing", [])) or "see `gh pr checks`"
    if kind == "CODE":
        if closed_correction(c, f"ci-{triage['n']}"):  # it changed nothing
            return stop([("CI is red because of the code, and the correction changed "
                         f"nothing. Tell the user the red checks ({red}) and what the "
                         f"triager found ({triage_file(c, triage)}); never merge over it.")],
                        "a CI correction changed nothing")
        return start_correction(c, "ci", 5, triage_file(c, triage), f"ci-{triage['n']}",
                                "CI is red because of the code (consumer 5)",
                                why=f"Red checks: {red}.")
    if kind == "SECRET":
        return stop([("CI failed on a secret or credential problem. Tell the user the "
                     f"red checks ({red}) and what the triager said "
                     f"({triage_file(c, triage)}). Once the secret is fixed and CI re-run, "
                     "`auto-dev continue` watches it again.")],
                    "the triager returned SECRET")
    # INFRA, FLAKY or UNKNOWN: not the coder's to fix. Stop here, before Jira
    # moves on a red build; a resume watches CI again.
    return stop([(f"CI is red, and the triager classed it {kind}: not something the code "
                 f"can fix. Tell the user the red checks ({red}) and what the triager "
                 f"found ({triage_file(c, triage)}). The run stops here; once CI is fixed "
                 "or re-run, `auto-dev continue` watches it again.")],
                f"the triager returned {kind}")


def triage_file(c, triage, key="triage_file"):
    """The triager's file: its result's path, else the one its brief named."""
    given = str(triage.get("data", {}).get(key) or "").strip()
    if given not in NONE:
        return given
    suffix = "-checks" if key == "checks_file" else ""
    return str(c.ad / "triage" / f"{triage.get('mode') or 'triage'}-{triage['n']}{suffix}.md")


def human_step(c):
    published = (c.p6.get("body") or {}).get("published_seq", 0)
    triage = c.last("triager", after=published, mode="human")
    if triage is None:
        earlier = earlier_triage(c)
        return spawn(c, "triager", "human", sets={"earlier": earlier} if earlier else None,
                     rule="before the main gate, the triager sorts what people said on "
                     "the PR (you never read it)")
    spend_id = f"human-{triage['n']}"
    if closed_correction(c, spend_id):
        return None  # handled; a change would have re-published and re-triaged
    blockers = _int(triage["data"].get("blockers"))
    checks = None
    if _int(triage["data"].get("acceptance_checks")):
        checks = {"scope": "ONLY the conditions whose checks the PR comments in the "
                           "report question",
                  "report": triage_file(c, triage, "checks_file")}
    if blockers or checks:
        return start_correction(c, "human", 4, triage_file(c, triage) if blockers else None,
                                spend_id, "people's comments on the PR need a correction "
                                "(consumer 4): checks to the tester, blockers to the coder",
                                checks=checks)
    return None


def earlier_triage(c):
    """Each earlier human triage whose correction closed: its files and what
    became of them, so the next triager doesn't sort the same comments again."""
    rounds = []
    for t in c.recs("triager", mode="human"):
        corr = closed_correction(c, f"human-{t['n']}")
        if corr is None:
            continue
        done = []
        if corr.get("file"):
            done.append(f"the coder worked on the blockers in {corr['file']}")
        if corr.get("checks"):
            tester = next(iter(c.recs("acceptance-tester", after=corr["seq"],
                                      mode="repair")), None)
            ruling = {"STANDS": "ruled they stand as written (right against SPEC.md)",
                      "REPAIRED": "repaired them"}.get((tester or {}).get("next"),
                                                       "answered")
            done.append(f"the acceptance tester {ruling} for the comments in "
                        f"{corr['checks']['report']}")
        at = next((b.get("at") for b in c.state.get("briefs", [])
                   if b["worker"] == "triager" and b["n"] == t["n"]), None)
        rounds.append(f"human-{t['n']}" + (f" (triaged {at})" if at else "") + ": "
                      + "; ".join(done))
    return "\n".join(rounds)


def main_step(c, sha):
    p6 = c.p6
    attempt = p6.get("merge_attempt")
    if not p6.get("merged") and attempt and attempt["result"] == "unknown":
        # merge-pr merged but could not read the PR back: never offer it again.
        pr = p6.get("pr")
        if pr_state(c, pr) != "MERGED":
            return stop([(f"`merge-pr` merged PR #{pr} but could not read its state, and "
                         "it still can't be read as MERGED. Never merge again: tell the "
                         f"user to check `gh pr view {q(pr)} --json state` and report "
                         "what it says.")], "a merge whose outcome is unknown")
        p6["merged"] = attempt.get("sha") or sha
        st.add_note(c.state, f"PR #{pr} is merged (read back after an unknown merge)")
        c.dirty = True
    if not p6.get("merged"):
        stale = fetch_and_check(c)
        if stale:
            return outside_push(c, sha, stale)
        attempt = p6.get("merge_attempt")
        gate = c.gate("main", after=max(p6.get("commit_seq", 0),
                                        attempt["seq"] if attempt and
                                        attempt["result"] == "head-moved" else 0))
        if gate is None or gate["choice"] != "proceed":  # a hold re-asks on resume
            return gate_question(c, "main", {
                "Merge PR to main": c.cmd("gate", "main", "proceed"),
                "Hold": c.cmd("gate", "main", "hold", "--reason", "<why>"),
                "Stop": c.cmd("gate", "main", "stop", "--reason", "<why>")},
                "the PR is checked and reviewed: the main gate")
        if attempt and attempt["seq"] > gate["seq"]:
            return stop([(f"GitHub did not merge the PR ({attempt['result']}). Tell the "
                         "user what `merge-pr` printed; Jira stays as it is.")],
                        "merge-pr did not merge")
        ci = p6.get("ci") or {}
        if ci.get("status") == "red":
            return stop(["CI is red on the PR; never merge over it. Tell the user each "
                         "red check: " + "; ".join(ci.get("failing", []))],
                        "red CI at the main gate")
        return action(f"merge: run `{c.cmd('merge-pr', '--pr', p6.get('pr'), '--sha', sha)}`",
                      "the main gate said proceed", AFTER=[c.cmd("next")])
    if not c.mark("main-ci"):
        return action(f"check CI on {c.state['repo']['base']} for the merge of PR "
                      f"#{p6.get('pr')} (references/S3-ship.md, CI after the merge; its "
                      f"merge commit: `gh pr view {q(p6.get('pr'))} --json mergeCommit -q "
                      ".mergeCommit.oid`); a failure there is reported, never fixed by "
                      "re-pushing", "the PR is merged",
                      AFTER=[c.cmd("mark", "main-ci", "--value",
                                   "<green | red | not watched>")])
    jira = jira_step(c, "done", "jira-done")
    if jira:
        return jira
    if not c.mark("final-report"):
        failed = (p6.get("inline") or {}).get("error")
        return action("write the final report for the user (references/S3-ship.md, "
                      "_The final report_): what shipped, the PR, the checks for a "
                      "person, the budget used, anything left open"
                      + (f"; and that the review findings could not all be posted on "
                         f"the PR ({failed}): they are in CODE_REVIEW.md and "
                         "SECURITY_REVIEW.md" if failed else ""),
                      "the PR is merged", AFTER=[c.cmd("mark", "final-report")])
    gate = c.gate("cleanup")
    if gate is None:
        return ask(c, "the worktree", [(f"The run is finished. Remove the worktree {c.wt}? "
                                       "That deletes .auto-dev/ too.")],
                   [cmd_review.question("Cleanup", f"Remove the worktree {c.wt}?",
                                        ["Remove it", "Keep it"])],
                   [("Remove it", c.cmd("gate", "cleanup", "proceed")),
                    ("Keep it", c.cmd("gate", "cleanup", "keep"))],
                   "the final report is written")
    c.finish(6, f"merged PR #{p6.get('pr')}")
    if gate["choice"] == "proceed":
        return {"code": NEXT_COMPLETE, "RULE": "the user chose to remove the worktree",
                "ACTION": (f"run `{c.cmd('cleanup-worktree')}` from "
                           f"{q(c.state['repo']['main_checkout'])}; then the run is "
                           "complete (its state goes with the worktree)")}
    return {"code": NEXT_COMPLETE, "ACTION": "the run is complete; nothing more to do",
            "RULE": "the user kept the worktree"}


def outside_push(c, sha, stale):
    """The PR's branch moved past the verified commit. Once the user has brought
    those commits into the worktree, they are re-checked like any outside
    change (the quality gate, the verifier, then a review pass on what they
    changed since `sha`), and `commit` then verifies HEAD, or commits the
    re-check's edits on top."""
    branch = c.state["branch"]
    head = git(c.wt, "rev-parse", "HEAD").strip()
    code, remote, _ = git(c.wt, "rev-parse", f"origin/{branch}", check=False)
    add, remove = changed_paths(c.wt)
    if code == 0 and remote.strip() == head and head != sha and not add and not remove:
        twice = stale_twice(c, stale, since=sha)  # before c.would: --explain shows it
        if twice:
            return twice
        c.would("re-check the PR branch's commits brought into the worktree",
                "the user brought the outside commits in")
        c.p6["unverified_commit"] = head  # a clean `commit` verifies it, no new commit
        c.dirty = True
        return stale_again(c, stale, since=sha)
    return stop([("The PR's branch holds commits the pipeline did not check (someone "
                  "pushed to it). Tell the user: to ship them, they bring them into the "
                  f"worktree with `git -C {q(c.wt)} merge --ff-only "
                  f"{q('origin/' + branch)}` and say `auto-dev continue`; the pipeline "
                  "then re-checks them (quality gate, verifier, review) and asks the "
                  "main gate again:"), stale], "the PR head moved")


def fetch_and_check(c):
    branch, base = c.state["branch"], c.state["repo"]["base"]
    if not c.readonly or c.probing:
        git(c.wt, "fetch", "-q", "origin", branch, base, check=False)
    return check_fresh(c, "--ref", f"origin/{branch}")


def pr_state(c, pr):
    """The PR's state on GitHub (MERGED, OPEN, CLOSED), or '' when unreadable."""
    code, out, _ = run(["gh", "pr", "view", str(pr), "--json", "state"], cwd=c.wt,
                       check=False)
    try:
        return json.loads(out).get("state", "") if code == 0 else ""
    except (ValueError, AttributeError):
        return ""


# ---------------------------------------------------------------- helpers

PHASES = {2: phase2, 3: phase3, 4: phase4, 5: phase5, 6: phase6}


def run_autodev(c, *args):
    out = subprocess.run([sys.executable, str(AUTODEV), *args, "--dir", str(c.ad)],
                         capture_output=True, text=True, check=False)
    return out.returncode, out.stdout, out.stderr


def _read(path):
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError:
        return ""


def _int(value):
    match = re.match(r"\s*(\d+)", str(value or "0"))
    return int(match.group(1)) if match else 0

