"""autodev.py next — print the pipeline's one next action.

Usage:
    autodev.py next [--dir <artifact-dir>] [--explain] [--reissue]
                    [--max-wait SECONDS] [--json]
    autodev.py next --repo <checkout> --task "<task>" [--ask "<restated ask>"]
                    [--ticket KEY] [--ticket-url URL] [--ticket-text-file PATH]
                    [--jira "<text>"] [--reissue] [--max-wait SECONDS] [--json]

Before the run exists (Phase 1, setup), run it with --repo, the checkout you
started in, and --task (the ticket key when there is a ticket; --ask and the
ticket flags are needed on the first call only). --ask, the task restated in
the user's words, is stored as the run's ask: the planner gets it when there
is no ticket text, and a later --task naming it finds the run (here and in
`resume`) as the task text does. It prints one step at a time, in the same
shape as below: the lookup to spawn for a saved profile (whether
each gate check's tool is adopted; when it finds one not adopted, the
gate-check question, exit 5: keep the checks, leave them out of this run, or
stop; when the repo's `.auto-dev.yml` sets `gate`, its gate replaces the
saved one: no lookup, no question), or the profiler to spawn when there is
no usable profile, then the profile question (exit 5); each question's AFTER lines run `autodev.py
setup-answer`; then it creates the worktree, branch and
run (`autodev.py init`, setup waited on for at most --max-wait seconds,
default 90) and says to move into the worktree, with `next --dir` as AFTER. A
`.auto-dev.yml` that sets both `setup` and `gate` needs no research. Run it
again at any point: it waits for a worker with no result, and points to the
run once it exists. Its files live in a private folder under the temp folder
until then. --explain needs a run.

Reads state.json (the workers' recorded results, the briefs issued, the
gates, the marks and the Phase 6 fields) and the artifacts, and
prints the one thing to do now. Run it, do exactly that, run every AFTER
command, then run `next` again. It never needs you to judge a file.

It records the workers' results itself first: each issued brief whose result
file exists and isn't recorded yet is recorded as `autodev.py record` would
(one it can't accept is refused, its issues saved for the retry), so spawned
workers need no `record` call. A brief with no result file is waited for
while its worker may still be running: the ACTION starts with `wait`, names
it, and spawns nothing. Run `next` only once every agent of the last spawn
returned; `next --reissue` sends such a brief out again, and is for when
every agent the wait names returned without writing its result file. In a
run it re-sends the same brief; before the run exists (--repo) it writes the
brief again under a new number.

It does the mechanical steps itself rather than asking you to: it writes the
brief of the worker to spawn, spends a round of the budget before a plan
revision or a correction, checks the acceptance tester's manifest and commits
its checks as their own commit (again after a repair, or a fix that edited a
check file), has the orchestrator run the quality gate as a script (no
worker) before anything is pushed, re-checks the risk tier from the diff, reads
the verifier's verdicts, plans and applies the code-review re-votes, takes the
review snapshot, and generates the PR body.

Once the build's quality gate is green, the change is committed, pushed and
opened as a draft PR; the verifier and the review then run together, alongside
CI. On a standard-risk run the review is one reviewer (code and security); a
high-risk run adds the panel of three with the judge, the separate security
reviewer, mutation and the verifier's own probes. One correction, one round,
takes what a pass left open and red CI on the pushed commit together.

Workers never negotiate the contract between themselves. A coder that finds
a plan step wrong builds it the way that works and lists the deviation
(deviations/coder-<n>.md); the ready-for-review gate summary names each one. A later worker
that finds a PLAN.md criterion wrong or missing (the verifier, the reviewer,
the review judge, a security reviewer, the triager from a PR comment) lists it in
spec-problems/<worker>-<n>.md, and `next` stops and asks the user before it
acts on that result. A check the verifier, the code review or a PR comment
questions goes to the acceptance tester's repair mode; if it rules the check
right as written (STANDS), `next` stops and asks the user. What the user keeps
at either stop is told to every later worker that judges it.

One iteration budget of rounds covers the run: the planner's one revision for
the plan critic's blockers, and each fix loop (the correction after a review
pass, red CI folded into it, a PR comment's, or red CI's alone) spend one.
Everything else is free but bounded: the tester goes once more for gaps, a
red quality gate gets one coder correction, a BLOCKED step one planner
decision; the same again is a stop. With
none left, `next` stops, except a correction in Phase 6 before the PR is marked
ready: what is open goes to the ready-for-review gate instead.

Output lines (only the ones that apply):
    ACTION:   what to do, in one line
    AGENT:    an agent to spawn (several AGENT lines: spawn them all in one
              message, in parallel); its BRIEF, PROMPT and (for a code
              reviewer) EFFORT follow it
    BRIEF:    the brief file written for it
    PROMPT:   the one-line prompt to give the Agent tool (no `model` parameter)
    EFFORT:   for a code reviewer only, after its PROMPT: the Agent tool's
              `effort` parameter to spawn it with, `high` or `xhigh`: the
              effort its review pass started at, which is the plan's
              `Review effort:` line (high when the plan has none). In --json,
              EFFORT is a list parallel to AGENT, "" for an agent with none,
              and left out when no agent has one
    BUDGET:   the round this action spent, and what is left
    SUMMARY:  lines to show the user before asking (exit 5)
    QUESTION: the AskUserQuestion JSON (exit 5)
    REPORT:   what to tell the user (exits 4 and 6)
    AFTER:    a command to run once the action is done; for a question,
              `"<answer>" → <command>`, one per answer
    RULE:     the rule that chose the action (--explain)
    RECORDED: each worker result `next` recorded before deciding,
              `<worker>-<n>: <status> <next>`, or `<worker>-<n>: refused
              (<token>)` (it is then briefed again with the issues). Under
              --explain nothing is recorded: with a result waiting, the action
              says `next` would record it first

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
       not run; with --repo: no --task, an unreadable ticket text file, an
       unsafe scratch folder) — never a pass
    3  the run is complete
    4  stop and report: tell the user the REPORT lines; with a QUESTION, ask
       how to go on and run the AFTER line for the answer (an `override`
       command; a typed answer is the fixer's instruction), then `next`;
       otherwise do nothing more
    5  ask the user: show SUMMARY, ask QUESTION, run the AFTER line for the answer
    6  a checkpoint: run the AFTER command, give the user its message, stop
`next` never exits 1: a step it could not take is a stop (4) that says why.

While Phase 1's setup is not done, `next --dir` runs `init --continue`
itself: it waits on setup (exit 0 with `next --dir` as AFTER while it still
runs), and after a failed setup the user came back to (`resume`, then
`next`), runs it again from the profile the run was made from
(`.auto-dev/profile-origin.json`: the saved file read again, less the checks
dropped at creation; the run's own profile.yml; or .auto-dev.yml). A failed
setup is a stop with no QUESTION, as is a setup stop before the run exists:
the REPORT says how to go on.

Checkpoint: once this session has written CHECKPOINT_EVENTS events to state.json
(80, or `checkpoint_events` in .auto-dev.yml), `next` ends the session at the
next clean point with exit 6 and `handoff --checkpoint`, so no session's context
grows without bound. A clean point is one where the step would be an action
(exit 0) and no brief is in flight: a stop or a question the step would print
comes first. A stop that only a write would reveal (one found
after starting a review pass) comes in the next session
instead. A new session says `auto-dev continue` and picks up where this one
stopped; resuming after a checkpoint lifts no stop, since nothing was fixed in
between.

Metrics: whenever `next` (not --explain) exits 3 or 4 for a run, it writes
.auto-dev/metrics.json from state.json: spawns per worker, rounds, stops by
their number in references/tables.md (each counted once while `next` keeps
reporting it), refused results, review findings kept and dropped, events and
the build's diff size. `next --repo` writes it too when setup failed in the
run it created (exit 4; that stop is not counted), and a step `next` could not
take (exit 4) writes it from the run as saved. It writes the same file to
<metrics-dir>/<repo folder>/<branch>.json, so it outlives the worktree;
<metrics-dir> is $AUTO_DEV_METRICS_DIR, else $XDG_CONFIG_HOME/auto-dev/metrics,
else ~/.config/auto-dev/metrics. A file it can't write is said on stderr and
changes neither the output nor the exit code, with one exception: when the copy
was not written, the worktree question and its 'Remove it' ACTION say so and
name .auto-dev/metrics.json, so the user can save it before the worktree is
removed, or keep it (the ACTION names `gate cleanup keep`). Until
`cleanup-worktree` has removed it, a later `next` gives that ACTION again, and
`resume` picks the run up (RESUME) for it; a removal git refuses records the
worktree as kept, which finishes the run.

A brief issued but not yet recorded is waited for while it was sent out in
this session, after the latest retry at a stop and less than 3 hours ago
(IN_FLIGHT_HOURS). It is re-issued as the same spawn after a new session (a
cut-off session, say), after a retry at a stop (`override retry`, or a
fixer's FIXED), once 3 hours have passed, or with `--reissue`; while any
brief is waited for, nothing is re-issued. One `next` refused is re-issued
as a new brief that carries the refused issues (as `brief --retry <n>`
writes). Spawned three times with no usable result, it stops; a brief that
stop ended is no longer waited for, so the stop is asked again. A stop on a
worker (blocked, failed twice, never returned) is lifted by `resume`: the
next session spawns that worker again. A stop on a result (a red quality gate, an impossible spec)
comes back until the user overrides it. Every stop but the budget's, a gate's
Stop, a setup stop (before the run exists, or a failed setup) and a merge of
unknown outcome prints a QUESTION and is
saved as state["stop"]: `autodev.py override` records the answer (the fixer
with the user's instruction, a retry, a sign-off where the stop allows one,
talk, leave), and the next `next` acts on it, running only the step that
stopped again, at no round. The budget used up stays until the user adds
rounds with `autodev.py budget raise --by <n>`: the next `next` takes the
step that stopped, spending one of them.
"""

import copy
import json
import re
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import artifacts as art
from . import (
    briefs,
    cmd_checks,
    cmd_gate,
    cmd_review,
    cmd_tests,
    cmd_work,
    judgment,
    metrics,
    overrides,
    tree_guard,
)
from . import state as st
from .cmd_ship import changed_paths
from .cmd_state import spend_round
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
# A brief sent out this long ago with no result is sent out again unasked: a
# backstop for a worker lost without a notification.
IN_FLIGHT_HOURS = 3
CHECKPOINT_EVENTS = 80  # about 35 workers; tune on the fixture repo
SLOTS = ("R1", "R2", "R3")
SECURITY = ("security-reviewer", "security-reviewer-sensitive")
JIRA_DEFAULTS = {"in_progress": "In Progress", "in_review": "In Review", "done": "Done"}
# Workers whose results make a change (Phases 4-6); the quality gate follows.
LOOP = ("coder", "acceptance-tester", "planner")
NONE = ("none", "", None)
ONLY_RE = re.compile(r"ONLY conditions ([^:]+):")
ENTRY_POINT_SCOPE = "ALL CONDITIONS whose checks call an entry point the revised plan changed"
GAP_NOTE = "the gaps check-manifest found:"
HUMAN_SCOPE = "ONLY the conditions whose checks the PR comments in the report question"
# The stop's number and whether it counts (metrics.json): main() reads it,
# show() drops it.
TALLY = "TALLY"
# The ACTION to print instead when the metrics copy could not be written
# (main_step's "Remove it"): main() swaps it in, show() drops it.
UNSAVED = "UNSAVED"
# The artifact dir of the run `next --repo` created and whose setup failed:
# main() writes its metrics, show() drops it.
RUN_DIR = "RUN_DIR"
FILL = ("replace each '<...>' placeholder, inside its single quotes, with text that "
        "holds no single quote (rephrase, or use the typographic apostrophe U+2019)")


def add_arguments(parser):
    parser.add_argument("--dir", default=".auto-dev", help="the run's .auto-dev/")
    parser.add_argument("--repo", help="before the run exists: the checkout to set it up "
                                       "from (Phase 1); needs --task")
    parser.add_argument("--task", help="with --repo: the task, one line (the ticket key "
                                       "when there is a ticket)")
    parser.add_argument("--ask", help="with --repo: the task restated in 1-2 sentences, "
                                      "in the user's words")
    parser.add_argument("--ticket", help="with --repo: the Jira key, when there is a ticket")
    parser.add_argument("--ticket-url", help="with --repo: the ticket's link")
    parser.add_argument("--ticket-text-file", metavar="PATH",
                        help="with --repo: a file holding the ticket's summary and "
                             "description, given to the planner verbatim")
    parser.add_argument("--jira", help="with --repo: Jira availability, for profile.md")
    parser.add_argument("--max-wait", type=int, default=90,
                        help="seconds one call waits on the run's setup (default 90)")
    parser.add_argument("--explain", action="store_true",
                        help="print the action and the rule that chose it, changing "
                             "nothing")
    parser.add_argument("--reissue", action="store_true",
                        help="send out again every brief that has no result yet, even "
                             "one sent out in this session: only once every agent it "
                             "was sent to returned without writing its result file")


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
        self.quiet = False  # state["stop"] changed: saved, but not an event of its own
        self.recorded = []  # the RECORDED lines of the results this call recorded
        self.readonly = bool(getattr(args, "explain", False))
        self.reissue = bool(getattr(args, "reissue", False))
        self.probing = False
        self.peeked = {}
        self.prev_stopped = None  # the budget stop the last `next` saved, if any

    # ------------------------------------------------------------ reading

    @property
    def log(self):
        # A result the user set aside at a stop (`override retry`, or a fix)
        # is not read: its step runs again.
        return sorted((e for e in self.state.get("log", []) if not e.get("aside")),
                      key=lambda e: e.get("seq", 0))

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
        # A retry at a stop lifts what a new session lifts (overrides.lift).
        return max(self.state.get("resumed_seq", 0), self.state.get("lifted_seq", 0))

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
        if (self.dirty or self.quiet) and not self.readonly:
            st.save(self.dir, self.state, count_event=self.dirty)

    def would(self, what, rule):
        """Under --explain, stop before a step that writes a file or git."""
        if self.readonly:
            raise Preview(what, rule)

    def peek(self, worker):
        """The brief number write_brief would give `worker` next (--explain)."""
        n = self.peeked.get(worker) or cmd_work.next_number(self.ad / "briefs", worker) - 1
        self.peeked[worker] = n + 1
        return n + 1

    def spend(self, spend_id, what):
        outcome = spend_round(self.state, spend_id, what)
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


def stop(report, rule, retry=None, signoff=None, no_signoff=None, kind=None,
         after_fix=None, number=None, count=True):
    """A stop. With `retry` (what `override retry` does: results to set aside,
    phase6 keys to clear, a stop to lift, a correction to reopen), the user can
    override it: `next` asks how (stop_point). `signoff` is what a sign-off
    does (a result to rewrite as passed, results to set aside, a correction id
    to drop); with none, `no_signoff` says why it isn't offered. `number` is
    the stop condition's number in references/tables.md (None for one it
    doesn't number), counted in metrics.json unless `count` is false (a
    hold); show() never prints it."""
    result = {"code": NEXT_STOP, "ACTION": "stop and report to the user; do nothing more",
              "REPORT": report, "RULE": rule, TALLY: {"number": number, "count": count}}
    if retry is not None:
        result["OVERRIDE"] = {"retry": retry, "signoff": signoff, "kind": kind,
                              "no_signoff": None if signoff else (
                                  no_signoff or "there is no result to accept"),
                              "after_fix": after_fix}
    return result


def job_of(rec):
    return [rec["worker"], rec["n"]]


def spawn(c, worker, mode=None, sets=None, rule="", budget=None):
    return spawn_many(c, [(worker, mode, sets or {})], rule, budget)


def spawn_many(c, jobs, rule, budget=None):
    """Spawn each (worker, mode, sets[, agent]) job in one message."""
    agents, briefs_, prompts, efforts = [], [], [], []
    for job in jobs:
        worker, mode, sets = job[:3]
        job_agent = job[3] if len(job) > 3 else None
        kept, used = kept_texts(c), briefs.slots(worker, mode)
        sets = {**sets, **{slot: kept[slot] for slot in KEPT_SLOTS.get(worker, ())
                           if slot in kept and slot in used}}
        if c.readonly:
            n = c.peek(worker)
            path = c.ad / "briefs" / f"{worker}-{n}.md"
        else:
            path, _ = cmd_work.write_brief(c.state, c.ad, worker, mode, dict(sets))
            c.dirty = True
            n = int(path.stem.rsplit("-", 1)[1])
        agents.append(job_agent or f"auto-dev:{worker}")
        briefs_.append(str(path))
        prompts.append(cmd_work.prompt_for(path))
        efforts.append(effort_for(c, worker))
    return spawn_lines(agents, briefs_, prompts, rule, budget, efforts)


def spawn_lines(agents, briefs_, prompts, rule, budget=None, efforts=None):
    """efforts, when any is set, parallels agents ("" for an agent spawned at its
    own effort). No AFTER line: the next `next` records what they return."""
    efforts = efforts if efforts and any(efforts) else None
    if len(agents) == 1:
        what = (f"spawn {agents[0]} with the PROMPT, in the foreground (the Agent "
                "tool's `run_in_background: false`); once it returned, run `next` "
                "(it records its result)")
    else:
        what = (f"spawn these {len(agents)} agents in one message, in parallel, each "
                "with its PROMPT; once every agent returned, run `next` (it records "
                "their results)")
    if efforts:
        what += ", passing its EFFORT as the Agent tool's `effort` parameter"
    return action(what, rule, AGENT=agents, BRIEF=briefs_, PROMPT=prompts,
                  EFFORT=efforts, BUDGET=budget)


def plan_effort(c):
    """The code reviewers' effort the plan recommends; high when it names
    something else (a fix at a stop may have edited the line)."""
    try:
        value = art.review_effort(art.read(c.ad / "PLAN.md"))
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


def exhausted(c, what, extra=""):
    """The budget stop: no round left for `what`. Saved with the stop, so
    `budget raise` knows the run stopped here; the next `next` clears it first
    (decide) and sets it again if the step stops on the budget once more."""
    first = c.prev_stopped
    c.state["budget"]["stopped"] = {"seq": first["seq"] if first else c.seq(),
                                    "what": what}
    c.dirty = True
    return stop([f"The iteration budget is used up ({c.state['budget']['total']} "
                 f"rounds): {what}." + (f" {extra}" if extra else ""),
                 ("The user can add rounds and go on from this step: run "
                  f"`{c.cmd('budget', 'raise', '--by', '<n>')}` with the number they "
                  "give, then `next`. Or they leave the run here; the worktree stays."),
                 f"State and artifacts: {c.ad}"], f"the budget is used up: {what}", number=11)


# ---------------------------------------------------------------- overriding a stop
#
# A stop on a result (a red quality gate, an impossible spec, a disputed check,
# a commit that failed, …) or on a worker that failed twice is not final: the
# user says how to go on. `next` saves the stop as state["stop"] and asks: a
# typed answer is an instruction for the fixer, the one worker that acts only
# on the user's words; or the user fixed it themselves (retry), signs it off
# where the stop allows, talks it through, or leaves it. `autodev.py override`
# records the answer (overrides.py); the fixer's result is settled here.

STOP_OPTIONS = {
    "approve": ("Approve the fixer's proposal",
                "The fixer runs again and does what it proposed, nothing more."),
    "retry": ("I fixed it myself",
              "Only the step that stopped runs again, at no round."),
    "signoff": ("Sign off and go on",
                ("Accept the result as it is: the run goes on as if the step passed. "
                 "Named in the PR body.")),
    "talk": ("Let's talk it through",
             "Discuss the stop first; nothing is recorded, and the question comes back."),
    "leave": ("Leave it stopped",
              "The run stays here and the worktree is kept; a new session asks again."),
}
TYPED = "<a typed answer>"


def stop_point(c, result):
    """Save a stop the user can override as state["stop"] and ask how to go
    on; any other step clears the saved stop."""
    spec = result.pop("OVERRIDE", None)
    if spec is None:
        if not c.readonly and c.state.pop("stop", None) is not None:
            c.quiet = True
        return result
    report, rule = list(result.get("REPORT") or []), result.get("RULE", "")
    prev = c.state.get("stop") or {}
    entry = {"rule": rule, "report": report, **spec,
             "phase": (st.first_open_phase(c.state) or (6, None))[0],
             "seq": prev["seq"] if prev.get("rule") == rule else c.seq()}
    if not c.readonly and prev != entry:
        c.state["stop"] = entry
        c.quiet = True
    last = overrides.latest(c.state)
    if last and last["choice"] == "leave" and last["seq"] > c.resumed() and \
            last["stop"].get("rule") == rule:
        result["REPORT"] = report + [
            ("The user chose to leave the run stopped here; the worktree stays. A new "
             "session (`auto-dev continue`) asks again how to go on.")]
        return result
    return ask_at_stop(c, result, entry, last)


def ask_at_stop(c, result, entry, last):
    fix = last if last and last["choice"] == "fix" and \
        last["stop"].get("rule") == entry["rule"] else None
    summary = []
    status = (fix or {}).get("status")
    if status == "proposed":
        summary.append("The fixer needs more than the instruction allows, so it changed "
                       f"nothing. Its proposal is in {fix['report']} (section Proposal): "
                       "read it to the user before asking.")
    elif status == "cannot":
        summary.append("The fixer could not carry out the instruction and changed "
                       f"nothing; why is in {fix['report']} (section Why not).")
    elif status == "failed":
        summary.append("The fixer did not finish" + (
            f"; what it changed was put back ({', '.join(fix['undone'])})"
            if fix.get("undone") else "") + ". What it said is in its reply.")
    keys = ["approve" if status == "proposed" else "retry"]
    if entry.get("signoff"):
        keys.append("signoff")
    keys += ["talk", "leave"]
    commands = {
        "approve": c.cmd("override", "approve"),
        "retry": c.cmd("override", "retry", "--text", "<what the user changed>"),
        "signoff": c.cmd("override", "signoff", "--text", "<why the user accepts it>"),
        "talk": c.cmd("override", "talk"),
        "leave": c.cmd("override", "leave"),
    }
    question = {"question": ("The run stopped: " + entry["rule"] + ". Type how to fix it "
                             "(a fixer agent does exactly that, and nothing more), or pick "
                             "one:"),
                "header": "Stopped", "multiSelect": False,
                "options": [{"label": STOP_OPTIONS[k][0], "description": STOP_OPTIONS[k][1]}
                            for k in keys]}
    if not entry.get("signoff"):
        summary.append(f"It can't be signed off: {entry['no_signoff']}.")
    result.update({
        "ACTION": ("tell the user the REPORT lines (and SUMMARY), then ask QUESTION with "
                   "AskUserQuestion. A typed answer (Other) is the user's instruction for "
                   f'the fixer: run the "{TYPED}" AFTER line with their words. Otherwise run '
                   "the AFTER line for their pick. Then run `next`, except after \"Leave it "
                   f'stopped": stop there ({FILL})'),
        "SUMMARY": summary, "QUESTION": json.dumps({"questions": [question]}),
        "AFTER": [f'"{TYPED}" → ' + c.cmd("override", "fix", "--text",
                                            "<what the user said>")]
                 + [f'"{STOP_OPTIONS[k][0]}" → {commands[k]}' for k in keys]})
    return result


def open_fix(c):
    found = [o for o in overrides.fixes(c.state) if o.get("status") == "open"]
    return found[-1] if found else None


def fix_step(c):
    """The fixer the user asked for at a stop: spawn it, then settle its result.
    None once no fix is open."""
    fix = open_fix(c)
    if fix is None:
        return None
    job = fix.get("job")
    if job is None:
        return fixer_spawn(c, fix)
    rec = next((e for e in c.state.get("log", [])
                if e["worker"] == "fixer" and in_jobs(c, [job], "fixer", e["n"])), None)
    if rec is None:
        return pending_briefs(c) or fixer_spawn(c, fix)
    c.would("settle the fixer's result", "the fixer returned")
    brief = brief_entry(c, "fixer", rec["n"]) or {}
    fix["report"] = str(c.ad / overrides.FIX_DIR / f"fixer-{rec['n']}.md")
    fix["done_seq"] = c.seq()
    c.dirty = True
    if rec.get("status") != "ok" or rec.get("next") != "FIXED":
        fix["status"] = {"NEEDS_CONSENT": "proposed", "CANNOT_FIX": "cannot"}.get(
            rec.get("next") if rec.get("status") == "ok" else None, "failed")
        fix["undone"] = undo_fix(c, brief, rec["n"])
        st.add_note(c.state, f"fixer #{rec['n']} returned {rec.get('status')} "
                    f"{rec.get('next') or ''}: nothing it changed stays; the stop asks again")
        return None
    changed = fix_changes(c, brief)
    fix.update({"status": "fixed", "changed": changed,
                "spec_changed": any(p.endswith("/PLAN.md")
                                    for p in changed)})
    stop_ = fix["stop"]
    if stop_.get("after_fix") == "fits":
        overrides.apply_signoff(c.state, {"rewrite": (stop_.get("signoff") or {}).get(
            "rewrite"), "fits": True}, c.seq())
    else:
        overrides.apply_retry(c.state, stop_.get("retry") or {}, c.seq())
    if fix["spec_changed"]:  # a brief still out judges the spec as it is now
        cmd_work.refresh_spec(c.state, c.ad)
    st.add_note(c.state, f"fixer #{rec['n']} fixed it at the user's instruction: "
                + (", ".join(changed) if changed else "no file changed")
                + "; the step that stopped runs again")
    corrs, passes = c.p6.get("corrections") or [], c.p6.get("passes") or []
    open_corr = corrs and not corrs[-1].get("closed") and not (
        passes and passes[-1]["seq"] > corrs[-1]["seq"])
    if open_corr:
        # The open correction runs the gate again, and its review pass covers
        # the fixer's files with its own.
        return None
    if changed and st.phase(c.state, 6)["status"] == "in-progress":
        c.p6.setdefault("corrections", [])
        c.p6.setdefault("passes", [])
        return start_correction(c, "fix", None, None,
                                "the fixer changed the code or its contract at a stop: "
                                "the quality gate, then (once committed) a review pass "
                                "on what it changed, run again (no round)")
    return None


def scratch(c):
    return tree_guard.scratch(c.wt, c.ad) or ".auto-dev"


def fixer_spawn(c, fix):
    """Brief the fixer with the user's words. The tree and the watched artifacts
    are saved first (cmd_work.write_brief), so what it changed can be listed,
    and put back if it ends without fixing."""
    stop_ = fix["stop"]
    c.would("spawn the fixer with the user's instruction",
            "the user said how to fix the stop")
    result = spawn(c, "fixer", sets={
        "instruction": fix["text"],
        "stopped": "\n".join([f"Why the run stopped: {stop_.get('rule')}"]
                             + list(stop_.get("report") or []))},
        rule="the user said how to fix the stop: the fixer does that, and nothing more "
             "(no round)")
    fix["job"] = ["fixer", c.state["briefs"][-1]["n"]]
    c.dirty = True
    return result


def fix_changes(c, brief):
    """The paths fixer job `brief` changed: repo files, and the watched artifacts
    as paths under the worktree."""
    paths = []
    if brief.get("fix_tree"):
        now = tree_guard.snapshot(c.wt, c.ad)
        paths += tree_guard.changed(brief["fix_tree"], now)
    if brief.get("artifacts") is not None:
        paths += [f"{scratch(c)}/{p}"
                  for p in overrides.changed_artifacts(c.ad, brief["artifacts"])]
    if brief.get("settings") is not None and c.state.get("settings") != brief["settings"]:
        paths.append(f"{scratch(c)}/state.json")  # the run's settings
    return paths


def undo_fix(c, brief, n):
    """Put back what a fixer that did not fix changed; the paths put back."""
    undone = []
    if brief.get("fix_tree"):
        now = tree_guard.snapshot(c.wt, c.ad)
        paths = tree_guard.changed(brief["fix_tree"], now)
        if paths:
            left = tree_guard.put_back(c.wt, brief["fix_tree"], paths,
                                       c.ad / overrides.FIX_DIR / f"fixer-{n}.after")
            undone += [p for p in paths if p not in left]
            if left:
                st.add_note(c.state, f"fixer #{n}: could not put back {', '.join(left)}; "
                            "restore them by hand")
    if brief.get("artifacts") is not None:
        paths = overrides.changed_artifacts(c.ad, brief["artifacts"])
        overrides.put_back_artifacts(c.ad, brief.get("artifacts_n", n), paths)
        undone += [f"{scratch(c)}/{p}" for p in paths]
    if brief.get("settings") is not None and c.state.get("settings") != brief["settings"]:
        c.state["settings"] = copy.deepcopy(brief["settings"])  # a gate check's command
        undone.append(f"{scratch(c)}/state.json")
    return undone


# ---------------------------------------------------------------- entry point

def main(args):
    if args.repo:
        result = setup_before_run(args)
        made = result.pop(RUN_DIR, None)
        if made is not None and not args.explain and result["code"] == NEXT_STOP:
            for error in metrics.write(made):  # the run as init left it: no stop counted
                print(error, file=sys.stderr)
        return show(result, args)
    for flag in ("task", "ask", "ticket", "ticket_url", "ticket_text_file", "jira"):
        if getattr(args, flag):
            raise Fail(f"--{flag.replace('_', '-')} needs --repo (it sets a run up)",
                       CANNOT_RUN, "ERROR")
    c = Ctx(args)
    c.max_wait = args.max_wait
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
        # A step `next` could not take is a stop, never exit 1; nothing of the
        # step is saved, since it did not happen (the results recorded first were).
        failed = stop([f"`next` could not take its step ({exc.token}): {exc}",
                       ("Tell the user; it is a broken artifact or an auto-dev bug. "
                        f"State and artifacts: {c.ad}")],
                      f"a step failed: {exc.token}", count=False)
        if c.recorded:
            failed["RECORDED"] = c.recorded
        if not c.readonly:
            write_metrics(c)  # the run as saved: nothing of the step was
        return show(failed, args)
    result = stop_point(c, result)
    if not c.readonly:
        if result["code"] == NEXT_STOP:
            changed = metrics.note_stop(c.state, result.get(TALLY) or {},
                                        result.get("RULE", ""),
                                        (st.first_open_phase(c.state) or (6, None))[0])
        else:
            changed = metrics.clear_stop(c.state)
        if changed:
            c.quiet = True  # saved, but not an event of its own (as state["stop"])
    c.save()
    unsaved = result.pop(UNSAVED, None)
    if not c.readonly and result["code"] in (NEXT_COMPLETE, NEXT_STOP):
        copied = not any(e.startswith(metrics.COPY_NOT_WRITTEN) for e in write_metrics(c))
    else:  # nothing written (--explain): whether it could be, decides the same
        copied = not unsaved or metrics.copy_error(c.state) is None
    if unsaved and not copied:
        result["ACTION"] = unsaved
    return show(result, args)


def write_metrics(c):
    """metrics.json and its copy (lib/metrics.py); a file it can't write is
    said on stderr and changes neither the output nor the exit code (but for
    UNSAVED, in main()). The lines it printed."""
    errors = metrics.write(c.dir)
    for error in errors:
        print(error, file=sys.stderr)
    return errors


def setup_before_run(args):
    """`next --repo`: Phase 1, before the run exists (cmd_setup). A step it
    could not take is a stop, as for a run, never exit 1."""
    from . import cmd_setup
    try:
        return cmd_setup.run_setup(args)
    except Fail as exc:
        if exc.code == CANNOT_RUN:
            raise
        return stop([f"`next` could not take its setup step ({exc.token}): {exc}",
                     "Tell the user; nothing more was created."],
                    f"a setup step failed: {exc.token}")


def show(result, args):
    code = result.pop("code")
    result.pop(TALLY, None)
    result.pop(UNSAVED, None)
    result.pop(RUN_DIR, None)
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
    recorded = record_returns(c)
    if recorded and not c.readonly:
        # Saved before the step, as a `record` call was: a step that fails keeps
        # them and saves nothing of its own. Each counted its own event already.
        st.save(c.dir, c.state, count_event=False)
    c.recorded, c.dirty = recorded, False
    c.prev_stopped = c.state["budget"].pop("stopped", None)
    if c.prev_stopped is not None and not c.readonly:
        # Saved now, so a step that fails leaves it cleared too; exhausted()
        # sets it again if this step stops on the budget once more.
        st.save(c.dir, c.state, count_event=False)
    result = decide_step(c)
    if recorded:
        result["RECORDED"] = recorded
    return result


def record_returns(c):
    """Record every issued brief whose result file exists and is not logged yet,
    as `autodev.py record` would: one it can't accept is refused and its issues
    saved for the retry `pending_briefs` writes. A brief with no result file is
    left to `pending_briefs`, which waits for it while it is in flight and
    otherwise issues it again as it is. One line per job.
    Under --explain it records nothing (recording a tester's result writes
    files): it says it would record them first, and stops there."""
    done = {(e["worker"], e["n"]) for e in c.state.get("log", [])}
    refused = c.state.get("refused", {})
    jobs = [(b["worker"], b["n"]) for b in c.state.get("briefs", [])
            if (b["worker"], b["n"]) not in done and not b.get("retried_as")
            and cmd_work.job(b["worker"], b["n"]) not in refused
            and (c.ad / "returns" / f"{b['worker']}-{b['n']}.json").exists()]
    if jobs:
        c.would("record " + ", ".join(f"{w}-{n}" for w, n in jobs) + " first",
                "a worker's result file is written and not recorded yet")
    lines = []
    for worker, n in jobs:
        token, _, _, data = cmd_work.record_job(c.state, worker, n)
        # Each is its own event, as a separate `record` save was: later records
        # and the brief written after them are stamped (seq) after it.
        c.state["events"] = c.state.get("events", 0) + 1
        lines.append(f"{worker}-{n}: " + (
            f"refused ({token})" if token != "RECORDED" else
            f"{data.get('status')} {data.get('next', '')}".rstrip()))
    return lines


def decide_step(c):
    fix = fix_step(c)  # first: a fix can reopen a stopped (OVERSIZED) run
    if fix is not None:
        return fix
    run_state = st.run_state(c.state)
    if run_state == "finished":
        if st.cleanup_pending(c.state):  # "Remove it", and the worktree is still here
            return remove_worktree(c)
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
        result = setup(c)
        if result is not None:
            return result
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
        stage = st.STAGES[number]
        if stage != c.state.get("stage", "plan"):
            return runbook(c, stage)
        if number >= 4:  # a repair or a fix since: its checks are committed first
            tests = tests_step(c)
            if tests:
                return tests
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
    if how == "held" and st.phase(c.state, 1)["status"] == "held":
        from .cmd_init import setup_source
        rows.append(f"Phase 1's setup failed. Tell the user to fix the cause in "
                    f"{setup_source(c.ad, c.state)}, then say `auto-dev continue` in a new "
                    "session: `next` runs setup again.")
    elif how == "held":
        rows.append("The run is held. Saying `auto-dev continue` in a new session "
                    "re-asks the gate that held it.")
    elif c.state.get("size") == "OVERSIZED":
        kept = (f"The run's files are in the user's own worktree {c.wt}, which stays."
                if c.state["repo"].get("adopted") else
                f"The worktree is kept: {c.wt} (remove it with "
                f"`git worktree remove {q(c.wt)}`).")
        rows.append("The task is too big for one PR. Tell the user the planner's reasons, the "
                    "subsystems it found and its suggested split lines, below. Jira was "
                    f"not moved. {kept}")
        rows += size_check(c)
    rows.append(f"State and artifacts: {c.ad}")
    plan = c.last("planner", mode="write")
    if how == "stopped" and c.state.get("size") == "OVERSIZED" and plan and \
            plan["next"] == "OVERSIZED":
        return stop(rows, "the planner found the task too big for one PR (OVERSIZED)",
                    retry={"aside": [job_of(plan)], "oversized": True},
                    signoff={"rewrite": [plan["worker"], plan["n"], "FITS"],
                             "fits": True},
                    kind="oversized", after_fix="fits", number=5)
    # A hold is a pause the user chose, not a stop; a gate's Stop is #19, and a
    # stopped OVERSIZED run whose planner result was set aside is still #5.
    return stop(rows, f"the run is {how}", count=how != "held",
                number=None if how == "held" else
                5 if c.state.get("size") == "OVERSIZED" else 19)


def size_check(c):
    """PLAN.md's Size check section, line by line, for the OVERSIZED report."""
    try:
        section = art.find_section(art.read(c.ad / "PLAN.md"), "Size check")
    except art.ArtifactError:
        section = None
    lines = [ln.strip() for ln in (section or "").splitlines() if ln.strip()]
    if not lines:
        return [("PLAN.md has no Size check section; its Context says what the task "
                 f"touches ({c.ad}/PLAN.md).")]
    return ["The planner's size check (PLAN.md):", *lines]


def issued(b):
    """When brief entry `b` was last sent out: (UTC ISO time, event seq). A
    re-issue stamps issued_at / issued_seq; the first issue is the entry's own
    at / seq."""
    return b.get("issued_at") or b.get("at"), b.get("issued_seq", b.get("seq", 0))


def in_flight(c, b):
    """Whether open brief `b`'s worker may still be running: sent out in this
    session, after the latest retry that lifted a stop, less than
    IN_FLIGHT_HOURS ago, with no result file, not refused, and not ended by the
    "spawned 3 times" stop."""
    if (c.ad / "returns" / f"{b['worker']}-{b['n']}.json").exists():
        return False
    if cmd_work.job(b["worker"], b["n"]) in c.state.get("refused", {}):
        return False
    at, seq = issued(b)
    if b.get("stopped_seq", 0) > seq:
        return False
    if seq < max(c.state.get("session_seq", 0), c.state.get("lifted_seq", 0)):
        return False
    try:
        age = datetime.now(timezone.utc) - datetime.fromisoformat(at)
    except (ValueError, TypeError):  # unreadable, or a naive time: stale
        return False
    return age.total_seconds() < IN_FLIGHT_HOURS * 3600


def wait_for(c, out):
    """The answer while briefs `out` are in flight: spawn nothing, and wait."""
    names = ", ".join(f"{b['worker']} #{b['n']} (sent out {issued(b)[0]})" for b in out)
    return action(
        f"wait: {names} {'has' if len(out) == 1 else 'have'} not returned yet and "
        "may still be running. Spawn "
        "nothing; once every agent you spawned has returned, run `next`. Run "
        f"`{c.cmd('next', '--reissue')}` only once every agent this wait names has "
        "returned and `next` still names it (it wrote no result file): it sends that "
        "brief out again",
        "a brief sent out in this session has no result yet: its worker may still "
        "be running")


def pending_briefs(c):
    """Re-issue the briefs issued after the last recorded result and not recorded,
    unless one is still in flight (sent out in this session, after the latest
    lifting retry, less than IN_FLIGHT_HOURS ago): then wait, unless --reissue.

    A job `record` refused (MISSING, MALFORMED, MISMATCH) is re-spawned as
    `brief --retry <n>` would: a new brief whose previous_issues carries the
    issues, replacing the old one."""
    done = {(e["worker"], e["n"]) for e in c.state.get("log", [])}
    issued_ = c.state.get("briefs", [])
    open_ = [b for b in issued_ if (b["worker"], b["n"]) not in done
             and not b.get("retried_as")]
    if not open_:
        return None
    if not c.reissue:
        out = [b for b in open_ if in_flight(c, b)]
        if out:
            return wait_for(c, out)
    refused = c.state.get("refused", {})
    for i, b in enumerate(open_):
        tries = b.get("emitted", 1) + 1
        if tries > MAX_EMITS:
            if not c.readonly:
                # The stop ends these spawns: none is waited for, so the stop is
                # asked again (after talk, leave, or a fixer's proposal).
                for x in open_:
                    if x.get("emitted", 1) >= MAX_EMITS and \
                            x.get("stopped_seq", 0) <= issued(x)[1]:
                        x["stopped_seq"] = c.seq()
                        c.quiet = True
            return stop([(f"{b['worker']} #{b['n']} was spawned {MAX_EMITS} times and "
                         "never left a result that `next` accepts. Tell the user; its "
                         f"brief is {c.ad}/briefs/{b['worker']}-{b['n']}.md. Once the "
                         "cause is fixed, `auto-dev continue` spawns it again.")],
                        "a worker failed to return three times", retry={"lift": True}, number=7)
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
            b["resent"] = b.get("resent", 0) + 1  # a spawn of its own (metrics.json)
            b["issued_at"], b["issued_seq"] = st.now(), c.seq()
            cmd_work.fresh_tree(c.state, b)  # what changed since is not this spawn's
        c.dirty = True
    agents = [f"auto-dev:{b['worker']}" for b in open_]
    paths = [c.ad / "briefs" / f"{b['worker']}-{b['n']}.md" for b in open_]
    return spawn_lines(agents, [str(p) for p in paths],
                       [cmd_work.prompt_for(p) for p in paths],
                       "a brief was issued and its result is not recorded yet: "
                       "spawn it again",
                       efforts=[effort_for(c, b["worker"]) for b in open_])


def not_ok(c):
    """A worker that stopped on purpose twice running, or failed twice running,
    stops the run; the first time, the step spawns it again (a blocked one is
    told why in its brief's previous_issues).

    Only results since the last `resume` count: once the user has fixed the
    cause and resumed, the step spawns the worker again."""
    # A pass's workers run in parallel (the verifier with the reviewer, or the
    # panel with the security reviewer): review_step re-spawns a failed one,
    # and their results would hide the security reviewer's.
    log = [e for e in c.log if e.get("seq", 0) > c.resumed()
           and e["worker"] not in ("code-reviewer", "fixer", "verifier", "reviewer")]
    if not log:
        return None
    latest = log[-1]
    if latest.get("status") == "ok":
        return None
    # By mode too: the judge's consolidate and security-verify run in parallel.
    same = [e for e in log if e["worker"] == latest["worker"]
            and e.get("mode") == latest.get("mode")]
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
                    f"a worker returned status {latest['status']}", retry={"lift": True}, number=6)
    return None  # failed or blocked once: the step re-spawns it


def setup(c):
    """Phase 1's setup is not done: wait on it, or (after a failed setup the
    user came back to) run it again from the profile the run was made from.
    None once it is done, so the phases go on."""
    from . import cmd_setup
    c.would("wait for setup, or run it again (`init --continue`)",
            "Phase 1's setup has not finished")
    code, message = cmd_setup.finish_run(c.ad, c.state, getattr(c, "max_wait", 90))
    if code == CANNOT_RUN or code not in (0, 1, 3):
        raise Fail(f"init --continue could not run (exit {code}): {message}", CANNOT_RUN,
                   "ERROR")
    c.state = st.load(c.dir)  # init wrote it
    c.p6 = c.state.setdefault("phase6", {})
    # A setup attempt ran: a stop after it is a new one (metrics.json). Saved
    # with whatever this call saves.
    c.state.pop("stop_shown", None)
    if code == 0:
        cmd_setup.remove_scratch(c.state["repo"]["main_checkout"],
                                 c.state["task"].get("text", ""))
        return None
    if code == 3:
        return action("setup is still running; run AFTER (it waits for it again)",
                      "Phase 1's setup has not finished", AFTER=[c.cmd("next")])
    return stop([f"Phase 1's setup failed: {message}",
                 ("Tell the user to fix the cause, then say `auto-dev continue` in a new "
                  "session: `next` runs setup again. "
                  f"State and artifacts: {c.ad}")], "Phase 1's setup failed", number=3)


def runbook(c, stage):
    """The run enters a new stage, in the same session: the orchestrator reads
    that stage's runbook, then goes on."""
    c.would(f"move on to the {st.STAGE_NAMES[stage]} stage", "the next phase is in it")
    c.state["stage"] = stage
    c.dirty = True
    # A HANDOFF.md from an earlier session describes an earlier stage: a
    # session resumed later must not pick up there.
    (Path(c.dir) / "HANDOFF.md").unlink(missing_ok=True)
    return action(f"the run goes on to the {st.STAGE_NAMES[stage]} stage in this session: "
                  f"read references/{stage}.md, then run `next`",
                  f"the next phase belongs to the {st.STAGE_NAMES[stage]} stage",
                  AFTER=[c.cmd("next")])


def checkpoint_due(c):
    """Whether this session has written its share of events (counted from the
    session's start, which `resume` records as session_seq)."""
    limit = _int(c.state["settings"].get("checkpoint_events")) or CHECKPOINT_EVENTS
    return c.state.get("events", 0) - c.state.get("session_seq", 0) >= limit


def checkpoint(c):
    return {"code": NEXT_BOUNDARY,
            "ACTION": "checkpoint: run AFTER, give the user its message, stop",
            "REPORT": [("This session has run long enough that a fresh one is cheaper; "
                        "the run continues from here.")],
            "AFTER": [c.cmd("handoff", "--checkpoint")],
            "RULE": "this session reached its checkpoint event count"}


# ---------------------------------------------------------------- Phase 2

def phase2(c):
    start = c.start(2)
    plan = c.last("planner", after=start, mode="write")
    if plan is None:
        return spawn(c, "planner", "write", rule="Phase 2 starts with the planner")
    jira = jira_step(c, "in_progress", "jira-in-progress")
    if jira:
        return jira
    steps = steps_step(c, plan)
    if steps:
        return steps
    critic = critic_step(c, plan["seq"])
    if critic:
        return critic
    if c.state["settings"].get("post_plan_gate"):
        # Before any check is written: the tester writes them from the plan
        # the user approved, and a revision never leaves a check stale.
        gate = post_plan_gate(c, start)
        if gate:
            return gate
    c.finish(2, f"FITS, risk: {'high' if c.state.get('high_risk') else 'standard'}")
    return None


def jira_step(c, key, step):
    ticket = c.state["task"].get("ticket")
    if not ticket or ticket == "none":
        return None
    choice = c.gate("jira")
    name = c.state["settings"].get("jira_states", {}).get(key, JIRA_DEFAULTS[key])
    if choice is None:
        already = f"Already {name}"
        out = ask(c, "Jira", [(f"The plan says the task fits one PR. Move {ticket} to "
                               f"`{name}` now?")],
                  [cmd_review.question("Jira", f"Move {ticket} to {name}?",
                                       ["Move it", already, "Leave Jira alone", "Stop"])],
                  [("Move it", c.cmd("gate", "jira", "proceed")),
                   (already, c.cmd("gate", "jira", "already")),
                   ("Leave Jira alone", c.cmd("gate", "jira", "leave")),
                   ("Stop", c.cmd("gate", "jira", "stop"))],
                  "a ticket exists and the size check says FITS")
        # Read the status first, so a ticket that is there already isn't asked about.
        out["ACTION"] = (f"first read {ticket}'s status (references/gates-and-jira.md, "
                         f"_Asking first_); if it is already `{name}` or past it, don't ask: "
                         f'tell the user and run the "{already}" AFTER line. Otherwise, '
                         + out["ACTION"])
        return out
    # `already`: the ticket was in progress when asked; later milestones move it.
    moves = choice["choice"] == "proceed" or (choice["choice"] == "already"
                                              and key != "in_progress")
    if not moves or c.mark(step):
        return None
    return action(f"move Jira ticket {ticket} to `{name}` with the Atlassian MCP tools "
                  "(references/gates-and-jira.md, _Moving a ticket_); never edit the ticket. If it "
                  "can't be moved, tell the user and run "
                  f"`{c.cmd('mark', step, '--value', 'skipped')}` instead of the AFTER line",
                  f"Jira milestone {step}",
                  AFTER=[c.cmd("mark", step)])


FITS_DIRECTION = ("the user kept this as one PR: set the Size check to FITS and write "
                  "the steps (Files, Design, Build sequence, Test plan, Migrations / "
                  "config) and the `Review effort:` line")


def steps_step(c, plan):
    """An OVERSIZED plan the user kept as one PR (a sign-off, or a fix at the
    stop) may have no steps: the planner writes them once, with no round,
    before the critic reads the plan."""
    try:
        text = art.read(c.ad / "PLAN.md")
    except art.ArtifactError:
        return None  # the critic's brief reports a missing plan
    if cmd_work.plan_has_steps(text) and cmd_work.plan_size(text) != "OVERSIZED":
        return None
    if any(r.get("sets", {}).get("direction") == FITS_DIRECTION
           for r in c.recs("planner", after=plan["seq"], mode="revise")):
        return None  # written once: the critic judges what is there
    return spawn(c, "planner", "revise", {"direction": FITS_DIRECTION},
                 rule="the plan was OVERSIZED and the user kept it as one PR: the planner "
                      "writes its steps (no round)")


def critic_step(c, after):
    """A fresh plan critic reviews PLAN.md. Blockers send it back to the planner
    once (a round), and the critic re-checks only the revision; a blocker still
    open after that goes to the user at the post-plan gate."""
    review = c.last("plan-critic", after=after, mode="review")
    if review is None:
        return spawn(c, "plan-critic", "review",
                     rule="a fresh critic reviews the plan before anything is built")
    if review["next"] == "APPROVE":
        return None
    findings = str(c.ad / "plan-review" / f"{review['n']}.md")
    # The first revision after the review answers it; a later one is the
    # user's, at the post-plan gate, which the critic doesn't see again.
    revised = (c.recs("planner", after=review["seq"], mode="revise") or [None])[0]
    if revised is None:
        budget = c.spend(f"plan-critic-{review['n']}", "plan revision")
        if budget is None:
            return exhausted(c, "no round left to revise the plan",
                             f"Tell the user each blocker in {findings}, one by one.")
        return spawn(c, "planner", "revise", {"review_file": findings},
                     rule="the critic found blockers: the planner revises once (a round)",
                     budget=budget)
    recheck = c.last("plan-critic", after=revised["seq"], mode="recheck")
    if recheck is None:
        return spawn(c, "plan-critic", "recheck", {"earlier": findings},
                     rule="the critic checks the revision and each blocker (no round)")
    answered = c.gate("post-plan", after=recheck["seq"])  # the user saw them already
    if recheck["next"] == "REVISE" and answered is None and \
            c.state.get("plan_blockers") != recheck["n"]:
        c.would("send the open blockers to the post-plan gate",
                "blockers are still open after the one revision")
        c.state["plan_blockers"] = recheck["n"]
        c.state["settings"]["post_plan_gate"] = True
        st.add_note(c.state, f"{recheck['data'].get('blockers')} plan blocker(s) still open "
                    "after the revision: the post-plan gate asks the user")
        c.dirty = True
    return None


# ---------------------------------------------------------------- Phase 3

def phase3(c):
    start = c.start(3)
    tester = acceptance_step(c, start)
    if tester:
        return tester
    tests = tests_step(c)
    if tests:
        return tests
    c.finish(3)
    return None


def acceptance_step(c, after):
    tester = c.last("acceptance-tester", after=after)
    if tester is None:
        return spawn(c, "acceptance-tester", "write",
                     {"scope": "ALL CONDITIONS"},
                     rule="the acceptance tester writes checks from the approved plan")
    ambiguous = str(tester["data"].get("ambiguous", "none")).strip()
    if ambiguous.lower() not in ("none", ""):
        planner = next((r for r in c.recs("planner", after=tester["seq"], mode="revise")
                        if r.get("sets", {}).get("ambiguous")), None)
        decided = [r for r in c.recs("planner", after=after, before=tester["seq"],
                                     mode="revise") if r.get("sets", {}).get("ambiguous")]
        if planner is None and decided:  # the planner decided once: no second loop
            return stop([(f"The acceptance tester still finds condition(s) {ambiguous} "
                          "reading two ways after the planner said which reading is "
                          f"meant. Tell the user both readings ({c.ad}/acceptance/"
                          f"AMBIGUOUS.md) and the planner's choice ({c.ad}/PLAN.md).")],
                        "a condition still reads two ways after the planner's decision",
                        retry={"aside": [job_of(tester)]},
                        no_signoff="a check of an ambiguous condition tests a guess", number=22)
        if planner is None:
            return spawn(c, "planner", "revise", {
                "ambiguous": f"conditions {ambiguous}; both readings, one line each, are "
                             f"in {c.ad}/acceptance/AMBIGUOUS.md"},
                rule="the acceptance tester found a condition that reads two ways: "
                     "the planner decides which is meant")
        if planner["data"].get("reading") == "other":
            return spawn(c, "acceptance-tester", "write", {
                "scope": f"ONLY conditions {ambiguous}: PLAN.md now says which reading "
                         "is meant, and it is not the one your checks test"},
                rule="the planner chose the other reading: rewrite those checks (no round)")
    gaps = manifest_gaps(c)
    if gaps:
        ids, lines = gaps
        if GAP_NOTE in tester.get("sets", {}).get("scope", ""):  # its one more go
            return stop([("The acceptance checks still have gaps after the tester's second "
                          "try. Tell the user each one:"), *lines,
                         f"State and artifacts: {c.ad}"],
                        "check-manifest found gaps twice", retry={"aside": [job_of(tester)]},
                        no_signoff="a condition with no check is not tested", number=22)
        return spawn(c, "acceptance-tester", "write", {
            "scope": f"ONLY conditions {', '.join(ids)}: {GAP_NOTE} " + "; ".join(lines)},
            rule="check-manifest found gaps in the tester's return: it goes once more "
                 "(no round)")
    return None


def tests_step(c):
    """Commit the acceptance checks as their own commit after each tester
    result that wrote or repaired them, and after a fix that edited a check
    file: once each (state's tests_synced). The tests commits are what
    check-tests.py guards the checks' lines against."""
    synced = set(c.state.get("tests_synced") or [])
    pending = []
    for rec in c.recs(("acceptance-tester", "fixer")):
        job = f"{rec['worker']}-{rec['n']}"
        if job in synced:
            continue
        if rec["worker"] == "acceptance-tester" and rec["next"] in ("WRITTEN", "REPAIRED"):
            pending.append((job, None))
        elif rec["worker"] == "fixer" and rec["next"] == "FIXED":
            pending.append((job, fixer_check_files(c, rec)))
    if not pending:
        return None
    only = None
    if all(paths is not None for _, paths in pending):  # fixes only: the files they edited
        only = sorted({p for _, paths in pending for p in paths})
    if only == [] and c.readonly:
        return None  # nothing to commit: only the bookkeeping, which --explain skips
    if only != []:
        c.would("commit the acceptance checks as their own commit",
                "the tester wrote or repaired them, or a fix edited them")
        before = {}
        for job, _ in pending:  # the earliest brief's copy of each file
            worker, _, n = job.rpartition("-")
            brief = next((b for b in c.state.get("briefs", [])
                          if b["worker"] == worker and b["n"] == int(n)), {})
            for path, blob in (brief.get("check_blobs") or {}).items():
                before.setdefault(path, blob)
        try:
            token, _sha, _paths = cmd_tests.commit_tests(c.state, c.ad, only, before)
        except Fail as exc:
            if exc.code == CANNOT_RUN:
                raise
            return stop([f"The acceptance checks could not be committed: {exc}",
                         "Tell the user; nothing was committed."],
                        "commit-tests refused", retry={},
                        no_signoff="the build needs its checks committed first", number=None)
        if token == "COMMITTED":
            # The commit is in git now: state.json says so at once, whatever
            # this `next` does after (the event is counted when it ends).
            st.save(c.dir, c.state, count_event=False)
    c.state["tests_synced"] = sorted(synced | {job for job, _ in pending})
    c.dirty = True
    return None


def fixer_check_files(c, rec):
    """The acceptance check files fixer `rec` edited in the worktree: ones
    MANIFEST.md names, and ones an earlier tests commit holds (a dropped check)."""
    brief = next((b for b in c.state.get("briefs", [])
                  if b["worker"] == "fixer" and b["n"] == rec["n"]), {})
    checks = set(cmd_work.check_files(c.ad)) | {
        p for commit in c.state.get("tests_commits") or [] for p in commit["paths"]}
    return sorted(p for p in fix_changes(c, brief) if p in checks)


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
        if c.state.get("plan_blockers") is not None and not c.readonly:
            # The user has seen the open blockers and revised: the gate's next
            # summary no longer lists them as left open. Bookkeeping, so
            # --explain previews the gate question rather than this.
            c.state.pop("plan_blockers")
            c.dirty = True
    latest = max([e["seq"] for e in c.recs("planner", after=after)] + [after])
    if gate is None or (gate["choice"] == "revise" and gate["seq"] < latest):
        return gate_question(c, "post-plan", {
            "Approve & build": c.cmd("gate", "post-plan", "proceed"),
            "Revise plan (tell me what to change)":
                c.cmd("gate", "post-plan", "revise", "--reason", "<what the user said>"),
            "Stop": c.cmd("gate", "post-plan", "stop")},
            "the post-plan gate is on (high risk, plan blockers left open, or the config)")
    return None


def gate_question(c, gate, answers, rule):
    builder = {"post-plan": cmd_review.post_plan_summary, "pr": cmd_review.open_pr_summary,
               "ready": cmd_review.ready_summary, "main": cmd_review.main_summary}[gate]
    ns = type("Args", (), {"pr": None, "dir": c.dir, "json": False})()
    try:
        lines, extra = builder(c.state, c.ad, ns)
    except Fail as exc:
        if exc.code == CANNOT_RUN:
            raise
        if gate in ("pr", "ready") and exc.token == "STALE":
            return stale_again(c, str(exc))
        return stop([f"The {gate} gate's checks failed, so it can't be asked: {exc}"],
                    f"a {gate} gate precondition failed", retry={},
                    no_signoff="the gate's checks protect what ships", number=None)
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
        return spawn(c, "coder", "build", rule="Phase 4: the coder builds from the plan "
                     "and runs the quality gate to green")
    result = change_step(c, start, first=None)
    if result is DONE_MARK:
        c.finish(4)
        return None
    return result

# The risk tier is re-checked from the diff once the quality gate is green
# (the end of Phase 5), before anything is pushed or reviewed: a path that names a
# sensitive area or matches a glob the repo declares sensitive (settings'
# sensitive_paths), a sensitive word on a line the build adds, or a large change
# makes the run high-risk. The tier never goes down. A path or an added line is
# split into whole words, at non-alphanumerics and camelCase humps (`UserAuth.ts`
# is user, auth, ts; `author.ts` is author, ts), and each word is looked up in
# SENSITIVE_WORDS. Lock files are left out of the line count and the word scan.
SENSITIVE_WORDS = frozenset((
    "auth", "authn", "authz", "authentication", "authorization", "login", "logout",
    "signin", "signup", "session", "sessions", "password", "passwords", "passwd",
    "credential", "credentials", "secret", "secrets", "token", "tokens", "oauth", "saml",
    "jwt", "sso", "crypto", "encrypt", "encryption", "decrypt", "permission",
    "permissions", "acl", "rbac", "payment", "payments", "billing", "invoice",
    "invoices", "checkout", "migration", "migrations", "migrate", "security"))
LARGE_FILES = 25
LARGE_LINES = 800
LOCK_FILE_RE = re.compile(r"(^|[-._])lock([-._]|$)|^go\.sum$", re.IGNORECASE)


def risk_recheck(c):
    """Re-check the tier from the build's diff, once (state's risk_recheck)."""
    if "risk_recheck" in c.state or c.readonly:
        return  # --explain shows the step after it; the next `next` re-checks
    paths, lines, added = build_diff(c)
    # .get: a run started before 5.1 has no sensitive_paths in its settings.
    declared = [glob_regex(g) for g in c.state["settings"].get("sensitive_paths") or []
                if isinstance(g, str) and g.strip("/")]
    why = []
    sensitive = [p for p in paths if sensitive_path(p) or declared_path(p, declared)]
    if sensitive:
        why.append("it touches " + ", ".join(printable(p) for p in sensitive[:5])
                   + (f" and {len(sensitive) - 5} more" if len(sensitive) > 5 else ""))
    hits = [(p, sorted(words)[:3]) for p, words in sorted(added.items())
            if words and p not in sensitive]
    if hits:
        why.append("it adds lines naming a sensitive area: "
                   + ", ".join(f"{printable(p)} ({', '.join(w)})" for p, w in hits[:5])
                   + (f" and {len(hits) - 5} more" if len(hits) > 5 else ""))
    if len(paths) > LARGE_FILES or lines > LARGE_LINES:
        why.append(f"it is large ({len(paths)} files, {lines} lines changed)")
    c.state["risk_recheck"] = {"seq": c.seq(), "high": bool(why), "why": why,
                               "files": len(paths), "lines": lines}
    if why and not c.state.get("high_risk"):
        c.state["high_risk"] = True
        st.add_note(c.state, "risk raised to high after the build: " + "; ".join(why))
    c.dirty = True


def printable(path):
    """`path` as text the ledger can write: a byte that isn't UTF-8 (read with
    surrogateescape) shows as `\\xe9`, so state.json and WORK_LOG.md save."""
    return path.encode("utf-8", "surrogateescape").decode("utf-8", "backslashreplace")


def path_words(path):
    """The whole words of a path, lowercased: split at non-alphanumerics and at
    camelCase humps (`OAuthToken` is o, auth, token; `HTTPServer` is http, server)."""
    words = []
    for part in re.split(r"[^A-Za-z0-9]+", path):
        words += re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|[0-9]+", part)
    return [w.lower() for w in words]


def sensitive_path(path):
    return any(word in SENSITIVE_WORDS for word in path_words(path))


def lock_file(path):
    return bool(LOCK_FILE_RE.search(Path(path).name))


def glob_regex(pattern):
    """A declared glob as a regex to fullmatch against a repo path. A pattern
    with a `/` anywhere is anchored at the repo root (a trailing `/` means
    everything under it); one without matches a file name at any depth. `*` and
    `?` stop at `/`; a whole `**` segment spans any number of folders, none
    included. Anything else, `[` included, is literal."""
    anchored = "/" in pattern
    body = pattern.lstrip("/")
    if body.endswith("/"):
        body += "**"
    segments = body.split("/")
    out = []
    for i, seg in enumerate(segments):
        last = i == len(segments) - 1
        if seg == "**":
            out.append(".*" if last else "(?:[^/]+/)*")
            continue
        out.append("".join("[^/]*" if ch == "*" else "[^/]" if ch == "?"
                           else re.escape(ch) for ch in seg))
        if not last:
            out.append("/")
    return re.compile(("" if anchored else "(?:.*/)?") + "".join(out), re.DOTALL)


def declared_path(path, regexes):
    return any(r.fullmatch(path) for r in regexes)


GIT_ESCAPES = {"a": 7, "b": 8, "t": 9, "n": 10, "v": 11, "f": 12, "r": 13,
               '"': 34, "\\": 92}


def diff_name(text):
    """The path in a `+++ b/<path>` header, as `git status` names it: one
    trailing tab dropped (git adds it after a name holding a space), and a
    C-quoted name unquoted. None for `/dev/null` (a deletion)."""
    if text.endswith("\t"):
        text = text[:-1]
    if len(text) >= 2 and text[0] == text[-1] == '"':
        raw, body, i = bytearray(), text[1:-1], 0
        while i < len(body):
            ch = body[i]
            if ch == "\\" and i + 1 < len(body):
                nxt = body[i + 1]
                if re.fullmatch(r"[0-7]{3}", body[i + 1:i + 4]):
                    raw.append(int(body[i + 1:i + 4], 8) & 0xFF)
                    i += 4
                    continue
                if nxt in GIT_ESCAPES:
                    raw.append(GIT_ESCAPES[nxt])
                    i += 2
                    continue
            raw += ch.encode("utf-8", "surrogateescape")
            i += 1
        text = raw.decode("utf-8", "surrogateescape")
    if text == "/dev/null" or not text.startswith("b/"):
        return None
    return text[2:]


def line_words(line):
    return {w for w in path_words(line) if w in SENSITIVE_WORDS}


def added_words(c, base, untracked):
    """{path: the SENSITIVE_WORDS on the lines the build adds}: the `+` lines of
    the diff from `base` to the working tree, and every line of an untracked
    file. Lock files, binary files and .auto-dev/ are left out."""
    def counted(p):
        return p and not p.startswith(".auto-dev/") and not lock_file(p)

    found = {}
    # The prefixes, colour, quoting, renames and submodule format are pinned, so
    # the user's diff config (diff.noprefix, diff.mnemonicPrefix, diff.renames,
    # diff.submodule) can't change the headers and lines parsed here. A moved
    # file's lines count as added, as an untracked move's do.
    code, text, _ = git(c.wt, "-c", "core.quotePath=false", "diff", "-U0", "--no-color",
                        "--no-ext-diff", "--no-textconv", "--no-renames",
                        "--submodule=short", "--src-prefix=a/", "--dst-prefix=b/",
                        base or "HEAD", check=False, errors="surrogateescape")
    current, in_hunk = None, False
    for line in (text.split("\n") if code == 0 else ()):
        if line.startswith("diff --git "):
            current, in_hunk = None, False
        elif not in_hunk and line.startswith("+++ "):
            name = diff_name(line[4:])
            current = name if counted(name) else None
        elif line.startswith("@@"):
            in_hunk = True
        elif in_hunk and current and line.startswith("+"):
            found.setdefault(current, set()).update(line_words(line[1:]))
    for p in untracked:
        if not counted(p):
            continue
        try:
            body = (Path(c.wt) / p).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "\0" in body:
            continue  # binary
        words = set()
        for line in body.splitlines():
            words |= line_words(line)
        found[p] = words
    return found


def build_diff(c):
    """(changed paths outside .auto-dev/, lines changed, {path: the sensitive
    words on its added lines}) between the branch's merge base and the working
    tree, untracked files included."""
    def out(*args):
        code, text, _ = git(c.wt, *args, check=False, errors="surrogateescape")
        return text if code == 0 else ""

    # Names are read NUL-separated and unquoted, as `changed_paths` reads them,
    # so a name git quotes (non-ASCII, `"`, `\`) is the same string everywhere.
    add, remove = changed_paths(c.wt)
    base = out("merge-base", c.state["repo"]["base"], "HEAD").strip()
    committed = out("-c", "core.quotePath=false", "diff", "--name-only", "-z",
                    "--no-renames", f"{base}..HEAD").split("\0") if base else []
    paths = sorted({p for p in add + remove + committed
                    if p and not p.startswith(".auto-dev/")})
    lines = 0
    for row in out("diff", "--numstat", base or "HEAD").splitlines():
        cells = row.split("\t")
        if len(cells) == 3 and not cells[2].startswith(".auto-dev/") and \
                not lock_file(cells[2]):
            lines += sum(int(n) for n in cells[:2] if n.isdigit())
    tracked = set(out("ls-files", "-z").split("\0"))
    for p in add:
        if p not in tracked and not lock_file(p):
            try:
                lines += len((Path(c.wt) / p).read_text(encoding="utf-8",
                                                          errors="replace").splitlines())
            except OSError:
                pass
    return paths, lines, added_words(c, base, [p for p in add if p not in tracked])


# ---------------------------------------------------------------- the change loop
#
# A change (the build, a correction, a fix at a stop, code changed outside the
# pipeline) runs its workers (the acceptance tester first when a check is
# questioned, then the coder; the planner when the coder stops a step), then
# the quality gate, which `next` has the orchestrator run as a script
# (`autodev.py quality-gate`), never a worker. A red gate gets one coder
# correction (no round); red again after it, the run stops and the user decides.

DONE_MARK = object()


def change_step(c, start, first):
    """One step of a change's workers after `start`: an action, or DONE_MARK
    once the change is made (the gate follows). `first` starts the change
    (None in Phase 4, where the coder's build is the change)."""
    recs = c.recs(LOOP, after=start)
    if not recs:
        return first() if first else DONE_MARK
    latest = recs[-1]
    worker, nxt = latest["worker"], latest["next"]
    if worker == "coder":
        return blocked_step(c, latest, start) if nxt == "BLOCKED" else DONE_MARK
    if worker == "planner":
        coder = c.last("coder", after=start, before=latest["seq"])
        return blocked_step(c, coder, start)
    # the acceptance tester
    trigger = next((r for r in reversed(recs[:-1])
                    if r["worker"] != "acceptance-tester"), None)
    if trigger and trigger["worker"] == "planner":
        coder = c.last("coder", after=start, before=trigger["seq"])
        return blocked_step(c, coder, start)
    if nxt == "STANDS" and questioned(latest) and not latest.get("signed_off"):
        corr = (c.p6.get("corrections") or [None])[-1]
        who = ("a PR comment" if (corr or {}).get("entry") == "human" else
               "the verifier or the code review")
        return disputed_stop(c, latest, who, str(((corr or {}).get("checks") or {})
                                                 .get("report") or c.ad))
    return DONE_MARK


def gate_runs(c, after):
    """The quality-gate runs since seq `after` that no retry set aside."""
    return [g for g in c.state.get("gate_runs") or []
            if g.get("seq", 0) >= after and not g.get("aside")]


def gate_step(c, start):
    """The quality gate on the code as it is now, after the change that began
    at `start`: DONE_MARK once it is green (or fails only on checks the user
    signed off)."""
    now = cmd_review.print_tree(c.wt)
    key = cmd_gate.gate_key(c.state)
    signed = overrides.signed_reports(c.state)
    last = (gate_runs(c, 0) or [None])[-1]
    if last and last["tree"] == now and last.get("gate") == key and (
            last["result"] == "GREEN" or set(last.get("failing") or ["?"]) <= signed):
        return DONE_MARK  # the code and the gate are what a green run checked
    runs = gate_runs(c, start)
    if not runs or runs[-1]["tree"] != now or runs[-1].get("gate") != key or \
            c.last(LOOP, after=runs[-1]["seq"]) is not None:
        return ask_gate(c, now)
    latest = runs[-1]
    failing = latest.get("failing") or []
    if latest["result"] == "GREEN" or (failing and set(failing) <= signed):
        return DONE_MARK
    reports = ", ".join(f"{c.ad}/lint/{r}" for r in failing)
    earlier = [g for g in runs[:-1] if g["result"] == "RED"]
    if earlier and c.last("coder", after=earlier[-1]["seq"]) is not None:
        return stop([("The quality gate is still red after the coder's correction for "
                     f"it; never ship a red build. Tell the user which checks fail: "
                     f"{reports}.")], "the quality gate is red after its correction",
                    retry={"gate": True},
                    signoff={"reports": failing}, kind="red-gate", number=9)
    return spawn(c, "coder", "correction", {
        "corrections_file": f"the failing quality-gate checks: {reports} (each report's "
                            f"output tail says what fails; the whole output is under "
                            f"{c.ad}/tmp/run/)"},
        rule="the quality gate is red: the coder makes it green (no round; red again "
             "after it is a stop)")


GATE_ASKS = 3  # the gate asked for this many times on one tree, with no run recorded


def ask_gate(c, tree):
    """Ask the orchestrator to run the quality gate; a stop once it was asked
    GATE_ASKS times on this tree and no run was recorded (it never finishes)."""
    asked = c.state.setdefault("gate_asked", {})
    if asked.get(tree, 0) >= GATE_ASKS:
        return stop([(f"The quality gate was asked for {GATE_ASKS} times on this code and "
                     "no run was recorded: it never finished (the whole gate may take "
                     "longer than a command may run). Tell the user; a check's own "
                     f"output is under {c.ad}/tmp/run/. Once it can finish (run it in "
                     "the background, or the profile's slow check made faster), "
                     "`auto-dev continue` asks for it again.")],
                    "the quality gate never finished", retry={"gate": True},
                    no_signoff="nothing says the gate is green", number=9)
    if not c.readonly:
        asked[tree] = asked.get(tree, 0) + 1
        c.dirty = True
    return action(f"run the quality gate: `{c.cmd('quality-gate')}`. It runs every check "
                  "of the profile's gate and writes their reports. Run it with the Bash "
                  "tool's timeout at 600000 ms; if the gate can take longer than that, "
                  "run it in the background and wait for it to finish. Then run AFTER "
                  "whatever it exits", "the code changed since the quality gate last "
                  "ran: `next` confirms it before anything is pushed (no worker)",
                  AFTER=[c.cmd("next")])


def settle_change(c, start, first):
    """The change's workers, then the quality gate: DONE_MARK when both are done."""
    result = change_step(c, start, first)
    if result is not DONE_MARK:
        return result
    return gate_step(c, start)


def questioned(tester):
    """Whether a tester repair answered a worker that questioned its checks
    (not the entry-point repair after a plan revision)."""
    scope = tester.get("sets", {}).get("scope", "")
    return tester.get("mode") == "repair" and scope != ENTRY_POINT_SCOPE


def coder_correction(c, corrections_file, budget, rule):
    return spawn(c, "coder", "correction", {"corrections_file": corrections_file},
                 rule=rule, budget=budget)


def blocked_step(c, coder, start):
    """The coder stopped steps: the planner decides; then the coder again, at no
    round. Stopped again after that, in the same change: the user decides."""
    planner = c.last("planner", after=coder["seq"], mode="blocked")
    if planner is None and c.last("planner", after=start, before=coder["seq"],
                                  mode="blocked"):
        listed = c.ad / "blocked" / f"coder-{coder['n']}.md"
        return stop([("The coder stopped a step again after the planner's decision on "
                      f"the first. Tell the user the steps it stopped ({listed}) and what "
                      f"the planner decided ({c.ad}/PLAN.md).")],
                    "the coder returned BLOCKED again", retry={"aside": [job_of(coder)]},
                    no_signoff="the stopped steps aren't built", number=22)
    if planner is None:
        listed = c.ad / "blocked" / f"coder-{coder['n']}.md"
        return spawn(c, "planner", "blocked", {"blocked": f"the steps listed in {listed}"},
                     rule="the coder returned BLOCKED: the planner decides why")
    if planner["next"] == "SPEC_IMPOSSIBLE":
        return stop([("The planner judged the spec impossible to meet as written. Tell "
                     f"the user its reasons (its reply, and {c.ad}/PLAN.md).")],
                    "the planner returned SPEC_IMPOSSIBLE",
                    retry={"aside": [job_of(planner)]},
                    no_signoff="the plan has no way to meet the spec; say how to change it",
                    number=8)
    if planner["data"].get("entry_points_changed") == "yes" and \
            c.last("acceptance-tester", after=planner["seq"]) is None:
        return spawn(c, "acceptance-tester", "repair", {
            "scope": ENTRY_POINT_SCOPE,
            "report": f"the plan was revised after a blocked step: see {c.ad}/"
                      "PLAN.md"},
            rule="the revised plan changed the checks' entry points (no round)")
    # Only a planner's result or a tester after it leads here, so the coder
    # has not gone again yet.
    return spawn(c, "coder", coder.get("mode") or "build", dict(coder.get("sets") or {}),
                 rule=f"the planner returned {planner['next']}: the coder goes again "
                      "(no round)")


# ---------------------------------------------------------------- what the user decides
#
# Workers never negotiate the contract between themselves. A criterion a later
# worker finds wrong or missing (its `spec_problems`), and a questioned check
# the acceptance tester rules right as written (STANDS), are stops: the user
# decides through the stop's question (a fix, a retry, or a sign-off that keeps
# the spec or the check as written). What the user kept is told to every later
# worker that judges it (KEPT_SLOTS), so it is not raised again.

# The workers told what the user kept, by the slot each is told it in.
KEPT_SLOTS = {"verifier": ("spec_kept", "checks_kept"),
              "review-judge": ("spec_kept", "checks_kept"),
              "reviewer": ("spec_kept",),
              "code-reviewer": ("spec_kept",),
              "security-reviewer": ("spec_kept",),
              "security-reviewer-sensitive": ("spec_kept",),
              "triager": ("spec_kept", "checks_kept")}


def brief_entry(c, worker, n):
    return next((e for e in c.state.get("briefs", [])
                 if e["worker"] == worker and e["n"] == n), None)


def in_jobs(c, jobs, worker, n):
    """Whether job worker-n is one of `jobs`, or a retry of one."""
    seen = set()
    while n is not None and n not in seen:
        if [worker, n] in jobs:
            return True
        seen.add(n)
        entry = brief_entry(c, worker, n)
        n = entry.get("retry") if entry else None
    return False


def spec_problems(rec):
    """How many criteria an ok result found wrong or missing."""
    if not rec or rec.get("status") != "ok":
        return 0
    return _int(rec.get("data", {}).get("spec_problems"))


def spec_stop(c, recs, where, review_pass=None):
    """The stop for the results in `recs` that found a criterion wrong or
    missing, or None. Retrying sets them aside, so their step runs again;
    signing off keeps PLAN.md as written and acts on them as if they found
    nothing."""
    found = [r for r in recs if r and spec_problems(r)]
    if not found:
        return None
    lines, kept = [], []
    for r in found:
        path = c.ad / "spec-problems" / f"{r['worker']}-{r['n']}.md"
        lines.append(f"{r['worker']} #{r['n']} ({path}):")
        for cid, why in cmd_work.spec_problem_items(path):
            lines.append(f"- {'a missing criterion' if cid == 'missing' else 'condition ' + cid}"
                         f": {why}")
            if cid not in kept:
                kept.append(cid)
    return stop([(f"A worker found PLAN.md wrong {where}: a criterion that can't or "
                  "shouldn't be met as written, or one that is missing. Workers never "
                  "change the spec; the user decides. Tell the user each item:"),
                 *lines,
                 ("To change the spec, the user says how (the fixer edits PLAN.md, and the "
                  "plan and checks when they say so); signing off keeps PLAN.md as written. "
                  f"State and artifacts: {c.ad}")],
                "a worker found a criterion wrong",
                # A judge set aside consolidates again: its pass's re-votes too.
                retry={"aside": [job_of(r) for r in found],
                       **({"revote": review_pass} if review_pass is not None and
                          any(r["worker"] == "review-judge" for r in found) else {})},
                signoff={"rewrites": [[r["worker"], r["n"], r["next"], {"spec_problems": "0"}]
                                      for r in found],
                         "kept": kept},
                kind="spec-problem", number=20)


def disputed_stop(c, tester, who, where):
    """The acceptance tester ruled checks `who` questioned right as written
    (STANDS): the user decides. Signing off keeps the checks as written."""
    scope = tester.get("sets", {}).get("scope", "")
    ids = only_ids(scope)
    which = (f"the checks of condition(s) {', '.join(ids)}" if ids else
             f"the checks {where} questions")
    return stop([(f"The acceptance tester ruled {which} right as written (against "
                  f"PLAN.md), and {who} judges them wrong. Workers never settle it "
                  f"between themselves. Tell the user both sides: {where}, and the "
                  f"reason acceptance-tester #{tester['n']} gave above its result "
                  "block. Signing off keeps the checks as written.")],
                "the acceptance tester and the worker that questioned a check disagree",
                retry={"aside": [job_of(tester)]},
                signoff={"rewrite": [tester["worker"], tester["n"], "STANDS"],
                         "kept": ids or [where]},
                kind="disputed-check", number=21)


def only_ids(scope):
    match = ONLY_RE.match(scope or "")
    return [x.strip() for x in match.group(1).split(",") if x.strip()] if match else []


def kept_texts(c):
    """{slot: text} of what the user kept at a stop, for a later worker's brief."""
    spec, checks = [], []
    for o in c.state.get("overrides") or []:
        if o["choice"] != "signoff":
            continue
        kind = o["stop"].get("kind")
        kept = (o["stop"].get("signoff") or {}).get("kept") or []
        words = (o.get("text") or "").splitlines()[0] if o.get("text") else ""
        named = ", ".join("a missing criterion" if k == "missing" else k for k in kept)
        if kind == "spec-problem" and kept:
            spec.append(f"{named} (the user's words: {words})")
        elif kind == "disputed-check" and kept:
            checks.append(f"{named} (the user's words: {words})")
    out = {}
    if spec:
        out["spec_kept"] = ("the user kept PLAN.md as written for: " + "; ".join(spec)
                            + ". Judge these as worded; never report them as spec "
                              "problems again")
    if checks:
        out["checks_kept"] = ("the user kept these acceptance checks as written: "
                              + "; ".join(checks) + ". Judge them as written, never as "
                              "defective")
    return out


# ---------------------------------------------------------------- Phase 5

def phase5(c):
    """The quality gate, run by `next` (no worker) on the built code, then the
    risk tier re-checked from the diff. A red gate goes back to the coder."""
    start = c.start(5)
    result = settle_change(c, start, first=None)
    if result is not DONE_MARK:
        return result
    risk_recheck(c)
    c.finish(5)
    return None


# ---------------------------------------------------------------- Phase 6
#
# 5.0's order: the verified build is committed, pushed and opened as a draft
# PR before any review (CI starts there), then the review runs alongside CI,
# then the ready-for-review gate, the PR marked ready, CI watched once more,
# people's comments, the main gate and the merge. Every correction lands on
# top of a commit: it runs, its review pass reviews the uncommitted
# correction, and it is committed and pushed in turn. The one change before
# the first commit is the re-check of code changed outside the pipeline since
# the Build stage. The open-the-PR gate (`gates.open_pr`, off by default) asks before the
# first push, for repos that must not push unreviewed code.

def phase6(c):
    c.start(6)
    p6 = c.p6
    p6.setdefault("passes", [])
    p6.setdefault("corrections", [])
    if p6.get("merged"):  # nothing before the merge runs again on a merged branch
        return main_step(c, p6["merged"])
    result = open_correction(c)
    if result is not None:
        return result
    if not p6.get("verified_sha") and not p6["passes"]:
        stale = check_fresh(c, "--phase", "5")
        if stale and not any(k["entry"] == "outside" for k in p6["corrections"]):
            return start_correction(c, "outside", None, None,
                                    "the code changed outside the pipeline since the Build stage: "
                                    "the quality gate runs on it first")
    if p6["passes"]:
        review = review_step(c, p6["passes"][-1])
        if review is not None:
            return review
    head = publish_step(c)
    if head is not None:
        return head
    if not reviewed_whole(c):
        return start_pass(c, "first", None, "the draft PR is open: the verifier and the "
                          "review check the whole change while CI runs")
    if (p6.get("body") or {}).get("reviewed") != p6["passes"][-1]["n"]:
        # The description reports an earlier pass, or (the draft's) none yet.
        body = body_step(c, p6["verified_sha"])
        if body is not None:
            return body
    return ship_step(c, p6["verified_sha"])


def open_correction(c):
    corrections = c.p6["corrections"]
    if not corrections:
        return None
    corr = corrections[-1]
    passes = c.p6["passes"]
    if corr.get("closed") or (passes and passes[-1]["seq"] > corr["seq"]):
        return None
    if corr.get("checks") and corr.get("file"):
        # The tester went first; the coder's part runs in the same round.
        tester = c.last("acceptance-tester", after=corr["seq"])
        settled = tester and (tester["next"] != "STANDS" or tester.get("signed_off"))
        if settled and c.last("coder", after=corr["seq"]) is None:
            return coder_correction(c, corr["file"], None, "the checks are settled; now "
                                    "the code's part of the correction (the same round)")
    result = settle_change(c, corr["seq"], first=lambda: first_of(c, corr))
    if result is not DONE_MARK:
        return result
    corr["closed"] = True
    c.dirty = True
    # Even when the budget ran out, the code changed: reviews are free, and the
    # gates need reports on the code as it is.
    if corr.get("since"):
        # Committed outside changes: a working-tree pass would see nothing. The
        # working tree against `since` holds the commits and any edit the
        # correction made on top (the coder's), new files included.
        if not c.readonly:
            cmd_checks.git_add_intent(c.wt)
        files = [f for f in git(c.wt, "diff", "--name-only", corr["since"]).splitlines()
                 if f and not f.startswith(".auto-dev/")]
        return start_pass(c, "outside", files, "the outside commits are re-checked: the "
                          "verifier and the review check what they changed", since=corr["since"])
    if not corr["after_commit"]:
        return None  # before the first commit: the first pass reviews the whole change
    sha = c.p6.get("verified_sha")
    past = past_by(c, sha)
    if past:
        # HEAD is past the verified commit: a repair or a fix committed as a
        # tests commit on top of it, or commits the run did not make (a base
        # merged in by hand while the correction ran, as a CONFLICT line says,
        # or the branch rebased onto it). A working-tree pass would see nothing
        # of them, and with a clean tree `commit` would find nothing to commit.
        # `commit` verifies HEAD instead (or commits the correction on top), and
        # the pass reviews everything since `sha`. HEAD is recorded with an edit
        # on top too: the pass reviews it, so a PR branch pushed to it is no new
        # outside push for moved_head while the pass's own findings are open.
        tests = past == "tests"
        add, remove = changed_paths(c.wt)
        head = git(c.wt, "rev-parse", "HEAD").strip()
        if c.p6.get("unverified_commit") != head:
            what = "tests commit" if tests else "commits"
            c.would(f"have `commit` verify the {what} on top of the verified one"
                    if not add and not remove else
                    f"record the {what} on top of the verified one as under re-check, "
                    "the correction to be committed on top of them",
                    "the correction was committed as a tests commit" if tests else
                    "HEAD moved past the verified commit through commits the run did "
                    "not make")
            c.p6["unverified_commit"] = head
            c.dirty = True
        if not reviewed_whole(c):
            return None
        if not c.readonly:
            cmd_checks.git_add_intent(c.wt)
        files = [f for f in git(c.wt, "diff", "--name-only", sha).splitlines()
                 if f and not f.startswith(".auto-dev/")]
        return start_pass(c, "outside", files, (
            "the correction's tests commit is on top of the verified commit"
            if tests else "commits the run did not make are past the verified commit "
            "(a base merged in by hand, say)") + ": the pass checks everything "
            "since it", since=sha)
    if unchanged(c):  # nothing to review or commit: the verified commit stands
        mark_committed(c, "the correction changed nothing")
        return None
    if not reviewed_whole(c):
        # A fix at a stop before the first review pass: it is committed on top,
        # and the first pass then reviews the whole change, the fix with it.
        return None
    return start_pass(c, "after-commit", None, "the correction is made and the gate is "
                      "green: the verifier and the review check it before it is "
                      "committed on top")


def first_of(c, corr):
    """The first step of correction `corr`: the tester for questioned checks,
    else the coder; DONE_MARK when there is nothing for a worker (code changed
    outside the pipeline, or by the fixer at a stop): the gate runs on it."""
    if corr.get("checks"):  # acceptance checks first: the tester's repair mode
        checks = corr["checks"]
        rule = ("a finding questions an acceptance check: the tester decides first"
                + (", then the coder" if corr.get("file") else ""))
        return spawn(c, "acceptance-tester", "repair", dict(checks), rule=rule,
                     budget=corr.get("budget"))
    if corr["entry"] == "outside" or not corr.get("file"):
        return DONE_MARK
    return coder_correction(c, corr["file"], corr.get("budget"), corr["rule"])


def closed_correction(c, spend_id):
    """The closed correction paid for as `spend_id`, or None."""
    return next((k for k in c.p6.get("corrections", [])
                 if (k.get("spend_id") == spend_id or spend_id in (k.get("also") or []))
                 and k.get("closed") and not k.get("aside")), None)


def unchanged(c):
    """Whether the tree is the verified commit's: nothing to review or commit."""
    sha = c.p6.get("verified_sha")
    if not sha:
        return False
    add, remove = changed_paths(c.wt)
    return not add and not remove and git(c.wt, "rev-parse", "HEAD").strip() == sha


def past_by(c, sha):
    """How HEAD is past `sha`: None when no commit is (`rev-list sha..HEAD` is
    empty), "tests" when by recorded tests commits alone, else "outside": the
    commits include one the run did not make (a base merged in by hand, or the
    branch rebased onto it or amended, when `sha` is no ancestor of HEAD)."""
    if not sha:
        return None
    code, out, _ = git(c.wt, "rev-list", f"{sha}..HEAD", check=False)
    revs = out.split() if code == 0 else []
    if not revs:
        return None
    return "tests" if set(revs) <= set(cmd_work.tests_shas(c.state)) else "outside"


def mark_committed(c, why):
    """The verified commit holds the code as it is: no commit is needed."""
    c.p6["commit_seq"] = c.seq()
    st.add_note(c.state, f"{why}: commit {c.p6.get('verified_sha')} stands")
    c.dirty = True


def reviewed_whole(c):
    """Whether a first pass (the whole change) has started."""
    return any(p["scope"] == "first" for p in c.p6.get("passes") or [])


def marked_ready(c):
    return c.mark("pr-ready")


def start_correction(c, entry, file, spend_id, rule, checks=None, why="", since=None,
                     also=None):
    """A Phase 6 correction: the coder gets `file` (when given); `checks` (scope,
    report) sends acceptance checks to the tester's repair mode first. `why`
    goes into the report when no round is left (the red checks, for CI).
    `since` (an outside correction only): the outside changes are the commits
    after it, so the review pass that follows reviews `git diff <since>`.

    With no round left, a review pass's correction before the ready-for-review
    gate is not a stop: its open findings go to that gate, which names them.
    Every other correction with no round left stops the run."""
    after_commit = bool(c.p6.get("verified_sha"))
    budget = None
    if spend_id:
        budget = c.spend(spend_id, f"{entry} correction")
        what = file or (checks or {}).get("report")
        if budget is None and entry == "review" and not marked_ready(c):
            c.p6["exhausted"] = {"seq": c.seq(), "open": [what]}
            c.dirty = True
            return None
        if budget is None:
            return exhausted(c, "no round left for a correction",
                             (f"{why} " if why else "") + f"Tell the user what is open: {what}")
    # After the budget check (in memory only under --explain or a probe), so a
    # budget-exhausted stop is never hidden behind the step that would follow.
    c.would(f"start a {entry} correction ("
            f"{file or (checks or {}).get('report') or 'the fixer'})", rule)
    corr = {"entry": entry, "file": file, "checks": checks, "seq": c.seq(),
            "after_commit": after_commit, "rule": rule, "budget": budget,
            "spend_id": spend_id}
    if since:
        corr["since"] = since
    if also:  # red CI folded in: its own correction id is settled by this one
        corr["also"] = also
    c.p6["corrections"].append(corr)
    c.dirty = True
    return open_correction(c)  # its first step: a worker, or the gate


def check_fresh(c, *extra):
    code, out, err = run([sys.executable, str(SCRIPTS / "check-fresh.py"), c.wt,
                          str(c.ad), *extra], check=False)
    if code == 2:
        raise Fail(f"check-fresh.py could not run: {err.strip()}", CANNOT_RUN, "ERROR")
    return (err or out).strip() if code else ""


def start_pass(c, scope, files, rule, since=None):
    """A review pass: the verifier and the code review, on the draft PR while
    CI runs. On a standard-risk run the verifier and one reviewer (code and
    security) are spawned together; on a high-risk one the verifier goes first
    (its mutants are planted in the tree), then the panel of three and the
    security reviewer, then the judge."""
    n = c.p6.get("review_pass", 0) + 1
    high = bool(c.state.get("high_risk"))
    c.would(f"start review pass {n} ({scope}) and spawn the verifier and "
            + ("the panel and the security reviewer" if high else "the reviewer"), rule)
    c.p6["review_pass"] = n
    (c.ad / "review" / f"pass-{n}").mkdir(parents=True, exist_ok=True)
    cmd_checks.git_add_intent(c.wt)
    tree = cmd_review.print_tree(c.wt)
    if scope == "first":
        files = first_pass_files(c)
    effort = plan_effort(c)
    p = {"n": n, "scope": scope, "files": files or [], "tree": tree, "seq": c.seq(),
         "effort": effort, "lane": "high" if high else "standard"}
    if since:
        p["since"] = since
    c.p6["passes"].append(p)
    st.add_note(c.state, f"review pass {n}: " + (
        f"the panel runs at effort {effort}, with the security reviewer" if high else
        "one reviewer (code and security)") + ", alongside the verifier")
    c.dirty = True
    jobs = [verifier_job(c, p)]
    if not high:
        judgment.snapshot_before(c.ad, n)  # the report as it stood, for review-build
        jobs.append(("reviewer", None, solo_sets(c, p)))
        return spawn_many(c, jobs, rule + "; the verifier and the reviewer run together")
    # The verifier's mutation run plants code in the worktree: the panel and
    # the security reviewer follow it, so they never read a planted mutant.
    return spawn_many(c, jobs, rule + "; on a high-risk run the verifier goes first (its "
                      "mutants are planted in the tree), then the panel and the security "
                      "reviewer")


def verifier_job(c, p):
    """The pass's verifier: a first pass on the whole change, a re-check on a
    correction (a first pass again when the spec changed since it last ran)."""
    if p["scope"] == "after-commit" and not spec_changed(c):
        return ("verifier", None, {"mode": "re-check",
                                   "what_changed": "a correction (the uncommitted working "
                                                   "tree against HEAD)"})
    return ("verifier", None, {"mode": "first pass"})


def spec_changed(c):
    """Whether a fix changed PLAN.md, a retry at a spec-problem stop, or a
    planner revision (a blocked step settled) came after the last verifier was
    briefed: it judges every condition again."""
    changed = [f.get("done_seq") for f in overrides.fixes(c.state) if f.get("spec_changed")]
    changed += [o["seq"] for o in c.state.get("overrides") or []
                if o["choice"] == "retry" and o["stop"].get("kind") == "spec-problem"]
    changed += [r["seq"] for r in c.recs("planner", mode="blocked")
                if r["next"] in ("PLAN_REVISED", "UPDATE_OLD_TEST")]
    last = max([e.get("seq", 0) for e in c.state.get("briefs", [])
                if e["worker"] == "verifier"] + [0])
    return any(done is not None and done >= last for done in changed)


def solo_sets(c, p):
    """The one reviewer's brief: as a panelist's, plus the tree it reviews."""
    sets = {k: v for k, v in reviewer_sets(c, p, "R1").items() if k != "reviewer"}
    sets["tree"] = p["tree"]
    return sets


def focus_text(p):
    """The security reviewer's focus: the correction a re-review pass covers, or
    `none` (the whole change, with /security-review) on a first or outside pass."""
    if p["scope"] == "after-commit":
        return "the uncommitted correction (the working tree against HEAD)"
    return "none"


def first_pass_files(c):
    """The files a first pass's /code-review gets: those the branch adds or
    modifies against the commit it was cut from, outside .auto-dev/. A name
    that isn't UTF-8 can't go in a brief; the reviewer still sees it in its
    own diff."""
    cut = cmd_work.cut_commit(c.wt, c.state["repo"]["base"])
    names = git(c.wt, "diff", "--name-only", "--diff-filter=d", cut, "HEAD").splitlines()
    return [f for f in names if f and not f.startswith(".auto-dev/") and utf8(f)]


def utf8(text):
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def reviewer_sets(c, p, slot):
    """A panelist's brief: its pass's scope, the files it names, and the effort
    its /code-review runs at (the pass's, which the plan set)."""
    scope = p["scope"]
    sets = {"reviewer": slot, "scope": scope,
            "review_effort": p.get("effort") or plan_effort(c)}
    if scope in ("first", "outside"):
        sets["files"] = ", ".join(p["files"]) or "none"
    if scope == "outside":
        sets["since"] = p.get("since") or "HEAD"
    return sets


def review_step(c, p):
    """Pass p: the verifier and the review, then one correction for whatever
    they left open. On a high-risk run the review is
    the panel and the security review, the judge (with its check of the
    security findings), the re-votes, or a security run on leads it has not
    seen."""
    vjobs, vrec, vstop = verifier_part(c, p)
    if vstop is not None:
        return vstop
    if p.get("lane") == "standard":
        return solo_step(c, p, vjobs, vrec)
    if vjobs:  # the panel waits for the verifier (mutation plants code in the tree)
        return spawn_many(c, vjobs, "the verifier goes first on a high-risk run: it gets "
                          "one re-spawn" if c.recs("verifier", after=p["seq"], ok=False)
                          else "the verifier goes first on a high-risk run")
    reviews = c.recs("code-reviewer", after=p["seq"], mode="review", ok=False)
    respawn, usable = [], []
    for slot in SLOTS:
        mine = [r for r in reviews if r.get("sets", {}).get("reviewer") == slot]
        if any(r["status"] == "ok" for r in mine):
            if "## Findings" in _read(c.ad / "review" / f"pass-{p['n']}" / f"{slot}.md"):
                usable.append(slot)
        elif len(mine) <= 1:  # none: a retry at a stop set the slot's results aside
            respawn.append(slot)
    jobs = [("code-reviewer", "review", reviewer_sets(c, p, slot)) for slot in respawn]
    secs = c.recs(SECURITY, after=p["seq"], ok=False)
    if not secs or secs[-1]["status"] != "ok":
        # It failed once (or a retry at a stop set it aside): not_ok stops the
        # run when it fails twice running.
        last = secs[-1].get("sets", {}) if secs else {}
        # The pass's first security run comes before this pass's panel has
        # written anything: its leads reach a later run (unreviewed_leads).
        leads = last.get("leads") if secs else "none"
        first = not secs and not reviews
        return spawn_security(c, jobs, leads or "none",
                              "the verifier is done: the panel and the security reviewer "
                              "review the same tree" if first else
                              "a worker of the pass failed: it gets one re-spawn"
                              if secs or jobs else
                              "the security review covers the whole change",
                              focus=last.get("focus") or focus_text(p))
    if jobs:
        return spawn_many(c, jobs, "a code reviewer failed: it gets one re-spawn")
    sec = secs[-1]
    data = sec["data"]
    verify = _int(data.get("must_fix")) or _int(data.get("pre_existing"))
    verified = c.last("review-judge", after=sec["seq"], mode="security-verify")
    judge = c.last("review-judge", after=p["seq"], mode="consolidate")
    if judge is None:
        if not usable:
            return stop([("No code reviewer wrote a usable report, twice. Tell the user; "
                         f"see {c.ad}/review/pass-{p['n']}/.")], "the panel produced nothing",
                        retry={"aside": [job_of(r) for r in reviews]},
                        no_signoff="no review was written to accept", number=13)
        if not c.readonly:  # the panel's findings, merged for the judge
            judgment.write_findings(c.ad, p["n"], usable)
        jobs = [("review-judge", "consolidate", {
            "reviewers": ", ".join(usable), "scope": scope_text(p), "tree": p["tree"]})]
        if verify and verified is None:
            jobs.append(("review-judge", "security-verify", {}))
        return spawn_many(c, jobs, "the panel and the security review are done: the "
                          "judge consolidates the panel's reports" +
                          (", and in parallel verifies every High or Medium security "
                           "finding" if len(jobs) > 1 else ""))
    if judge["next"] == "REVOTE":
        result = revotes(c, p, judge)
        if result is not None:
            return result
    if verify and verified is None:
        return spawn(c, "review-judge", "security-verify",
                     rule="the judge verifies every High or Medium security finding")
    # With no round left before the ready-for-review gate, open findings go to
    # that gate. After it, that covers only the passes the user marked the PR
    # ready with: once they add rounds, a later pass's findings get their
    # correction.
    spent_out = spent_before(c, p)
    rows = open_must_fix(art.read(c.ad / "CODE_REVIEW.md"))
    security_open = bool(verify) and bool(confirmed_security(c))
    spec = spec_stop(c, [vrec, judge] + c.recs(SECURITY, after=p["seq"]),
                     f"in review pass {p['n']}", review_pass=p["n"])
    if spec is not None:
        return spec
    settled = settle_pass(c, p, vrec, rows, sec if security_open else None, spent_out)
    if settled is not DONE_MARK and settled is not None:
        return settled
    # Even with no round left for a correction, the leads get their security
    # run: a lead nobody checked is not something the gate can name.
    leads = unreviewed_leads(c, p)
    if leads:
        return spawn_security(c, [], leads, "the panel passed the security review leads "
                              "it had not seen: it checks them", focus=LEADS_FOCUS)
    return None


def spent_before(c, p):
    """Whether no round was left for pass p's correction before the
    ready-for-review gate: its open findings go to that gate. After it, that
    covers only the passes the user marked the PR ready with: once they add
    rounds, a later pass's findings get their correction."""
    ready = marked_ready(c)
    return bool(c.p6.get("exhausted")) and (ready is None or p["seq"] < ready.get("seq", 0))


def verifier_part(c, p):
    """([the verifier's job to re-spawn], its ok result or None, a stop or None)."""
    recs = c.recs("verifier", after=p["seq"], ok=False)
    if recs and recs[-1]["status"] == "ok":
        rec = recs[-1]
        if rec["next"] == "MUTATION_LEFT_CHANGES":
            return [], rec, stop([("The mutation step may have left changes in the "
                                  "source; the tree may not be the code that was built. "
                                  "Tell the user the paths the verifier named; build "
                                  "nothing more on it.")],
                                 "the verifier returned MUTATION_LEFT_CHANGES",
                                 retry={"aside": [job_of(rec)]},
                                 no_signoff="the tree may hold a planted change; check "
                                            "it, then retry", number=10)
        return [], rec, None
    twice = failed_twice(c, recs, "verifier")
    if twice is not None:
        return [], None, twice
    return [verifier_job(c, p)], None, None


def failed_twice(c, recs, who):
    """The stop for a pass's worker that did not return ok twice since the last
    resume, or None (it gets one re-spawn). The pass's workers run in parallel,
    so not_ok, which reads only the latest result, leaves them to the pass."""
    tries = [r for r in recs if r.get("seq", 0) > c.resumed()]
    if len(tries) < 2 or tries[-1]["status"] == "ok" or tries[-2]["status"] == "ok":
        return None
    last = tries[-1]
    return stop([(f"{who} #{last['n']} did not return ok twice running. Tell the user "
                 "what it said above its result block, and that the run is paused here: "
                 "once the cause is fixed, `auto-dev continue` spawns it again."),
                 f"State and artifacts: {c.ad}"],
                f"the pass's {who} returned status {last['status']} twice",
                retry={"lift": True}, number=13)


def solo_step(c, p, vjobs, vrec):
    """A standard-risk pass: the verifier and the one reviewer, then the
    correction for what they left open."""
    recs = c.recs("reviewer", after=p["seq"], ok=False)
    rec = recs[-1] if recs and recs[-1]["status"] == "ok" else None
    rjobs = []
    if rec is None:
        twice = failed_twice(c, recs, "reviewer")
        if twice is not None:
            return twice
        rjobs = [("reviewer", None, solo_sets(c, p))]
    if vjobs or rjobs:
        return spawn_many(c, vjobs + rjobs, "a worker of the pass failed: it gets one "
                          "re-spawn")
    rows = open_must_fix(art.read(c.ad / "CODE_REVIEW.md"))
    security_open = bool(confirmed_security(c))
    spec = spec_stop(c, [vrec, rec], f"in review pass {p['n']}")
    if spec is not None:
        return spec
    settled = settle_pass(c, p, vrec, rows, rec if security_open else None,
                          spent_before(c, p))
    return None if settled is DONE_MARK else settled


def settle_pass(c, p, vrec, rows, sec, spent_out):
    """One correction for what pass p left open (the verifier's open items, the
    review's must-fix rows, a confirmed security finding when `sec` is its
    reviewer's result), with red CI on the pushed commit folded in; DONE_MARK
    when nothing is open, or no round is left before the ready-for-review gate
    (the gate names what is open)."""
    verifier_open = vrec["next"] in ("CORRECT", "REPAIR")
    if not (rows or sec or verifier_open):
        return DONE_MARK
    if spent_out:
        return None
    ci, triage = ci_fold(c)
    if ci is not None:
        return ci
    return review_correction(c, p, rows, sec, vrec if verifier_open else None, triage)


def ci_fold(c):
    """(an action or stop to take first, or None; the CI triage to fold into
    the correction, or None). Before a pass's correction, CI settles on the
    pushed commit, so one correction takes red CI too; not while a PR head
    pushed outside the run is under re-check, and a newly moved head is
    re-checked (moved_head) before any wait."""
    if c.state["settings"].get("ci", "none") == "none":
        return None, None
    outside = next((k for k in reversed(c.p6["corrections"]) if k["entry"] == "outside"),
                   None)
    if outside and outside.get("since") and outside["seq"] > c.p6.get("commit_seq", 0):
        # A moved PR head is under re-check: CI on the old commit never reports,
        # and the new head is watched once `commit` verifies it.
        return None, None
    sha = c.p6.get("verified_sha")
    moved = moved_head(c, sha)
    if moved:
        return moved, None
    ci = c.p6.get("ci") or {}
    if ci.get("sha") != sha or ci.get("status") == "pending":
        return ci_watch(c, "findings are open: CI settles on the pushed commit first, so "
                        "one correction takes red CI too", sha), None
    if ci.get("status") != "red":
        return None, None
    triage = c.last("triager", after=ci["seq"], mode="ci")
    if triage is None or triage["next"] != "CODE":
        return ci_step(c, sha), None  # the triager, or its stop
    if closed_correction(c, f"ci-{triage['n']}"):
        return None, None
    return None, triage


def review_carry(c, p, rows, sec, vrec=None):
    """What pass p's correction hands out: `files` for the coder (the
    verifier's required changes when it found the code wrong, the pass's
    corrections.md when a must-fix row other than a check's is open, and the
    security corrections), and `checks` (scope, report) for the tester's repair
    mode: the checks the verifier judged defective and the review's
    acceptance-check findings."""
    checks = [r for r in rows if _category(r) == "acceptance-check"]
    ids, reports, who = [], [], []
    if vrec is not None:
        _token, fields = cmd_checks.eval_decision(c.ad)
        repair = [x.strip() for x in fields.get("repair", "").split(",") if x.strip()]
        if repair:
            ids += repair
            reports.append(f"{c.ad}/SPEC_EVAL.md, section Defective acceptance checks")
            who.append("the verifier")
    if checks:  # a finding about a check goes to the tester, never the coder
        found = check_ids(c, checks)
        ids += [x for x in found if x not in ids]
        names = ", ".join(r["ID"].strip() for r in checks)
        reports.append(f"{c.ad}/CODE_REVIEW.md, must-fix finding(s) {names}: each "
                       "one's `### <id>` block says what is wrong with the check")
        who.append("the code review")
    spec = None
    if reports:
        scope = (f"ONLY conditions {', '.join(sorted(ids, key=cmd_checks.sort_key))}: "
                 f"{' and '.join(who)} found their checks wrong" if ids and (
                     not checks or check_ids(c, checks)) else
                 "ONLY the conditions whose checks the findings in the report name")
        spec = {"scope": scope, "report": " and ".join(reports)}
    files = []
    if vrec is not None and vrec["next"] == "CORRECT":
        files.append(f"{c.ad}/evidence/corrections.md")
    if len(checks) < len(rows):
        files.append(f"{c.ad}/review/pass-{p['n']}/corrections.md")
    if sec:
        files.append(f"{c.ad}/review/security-corrections.md")
    return {"files": files, "checks": spec}


def review_correction(c, p, rows, sec, vrec=None, triage=None):
    """One correction, one round, for what pass p left open: the verifier's
    items, the open must-fix rows, the security review's confirmed must-fix
    findings (when `sec` is given), and red CI the triager put on the code
    (when `triage` is given)."""
    carry = review_carry(c, p, rows, sec, vrec)
    files, why = carry["files"], []
    if triage is not None:
        files.append(triage_file(c, triage))
    spec = carry["checks"]
    if vrec is not None:
        why.append("the verifier found open items")
    if rows:
        why.append(f"pass {p['n']} left {len(rows)} must-fix finding(s) open")
    if sec:
        why.append("the security review found a confirmed must-fix finding")
    if triage is not None:
        why.append("CI is red because of the code")
    return must_fix(c, " and ".join(files) or f"{c.ad}/CODE_REVIEW.md", f"pass-{p['n']}",
                    " and ".join(why), checks=spec, coder=bool(files), security=bool(sec),
                    also=[f"ci-{triage['n']}"] if triage is not None else None)


def panel_leads(c):
    """CODE_REVIEW.md's security leads, for the security reviewer's brief."""
    return (art.find_section(_read(c.ad / "CODE_REVIEW.md"), "Security leads")
            or "").strip() or "none"


PASSED_LEAD = "passed to the security review"
# A run on leads alone: the pass's earlier security run covered the change, so
# this one skips /security-review and follows only the leads.
LEADS_FOCUS = "only the code review panel's leads (the brief's `leads`)"


def unreviewed_leads(c, p):
    """The leads CODE_REVIEW.md passes to the security review that no security
    run of pass p was given, as one text; "" when there are none. A lead marked
    covered by a finding the judge refuted counts as passed on."""
    given = " ".join(" ".join(str(r.get("sets", {}).get("leads", "")).split())
                     for r in c.recs(SECURITY, after=p["seq"], ok=False))
    refuted = refuted_security(c)
    items = []
    for item in judgment.lead_items(panel_leads(c)):
        covered = re.search(r"covered by (S\d+)", item)
        if PASSED_LEAD not in item and not (covered and covered.group(1) in refuted):
            continue
        if "<lead>" in item or " ".join(item.split()) in given:
            continue  # the template's placeholder, or seen already
        items.append(item)
    return "\n".join(items)


def refuted_security(c):
    """The IDs of SECURITY_REVIEW.md's findings the judge refuted."""
    try:
        _, rows = art.first_table(art.find_section(_read(c.ad / "SECURITY_REVIEW.md"),
                                                   "Findings") or "",
                                  ("ID", "Verified"), "SECURITY_REVIEW.md")
    except art.ArtifactError:
        return set()
    return {r["ID"].strip() for r in rows if r["Verified"].strip().lower() == "refuted"}


def spawn_security(c, jobs, leads, rule, focus="none"):
    """Spawn `jobs` and the security reviewer, given `leads` and `focus`, in one
    message."""
    agent = cmd_checks.security_agent(c.ad)
    jobs = jobs + [(agent.split(":", 1)[1], None, {"leads": leads, "focus": focus},
                    agent)]
    result = spawn_many(c, jobs, rule)
    c.p6["security_run"] = c.p6.get("security_run", 0) + 1
    return result


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
                    "a re-voter gave no usable vote twice", retry={"lift": True},
                    no_signoff="a lone finding's vote is still open", number=None)
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


def confirmed_security(c):
    text = art.read(c.ad / "SECURITY_REVIEW.md")
    _, rows = art.first_table(art.find_section(text, "Findings") or "",
                              ("ID", "Verdict", "Status"), "SECURITY_REVIEW.md")
    return sum(1 for r in rows if r["Verdict"].strip().lower() == "must-fix"
               and r["Status"].strip().lower().startswith("open")
               and r.get("Verified", "").strip().lower() != "refuted")


def must_fix(c, file, tag, rule, checks=None, coder=True, security=False, also=None):
    spend_id = tag
    if overrides.signed_off(c.state, spend_id):
        return None  # the user signed the open findings off: the gate names them
    closed = closed_correction(c, spend_id)
    if closed and kept_checks(c, closed):
        return None  # the user kept the questioned checks: the gate names the rest
    if closed:
        # It ran and changed nothing (a change starts a new pass): never again,
        # unless the user retries it.
        return stop([(f"The correction for {tag}'s open finding(s) changed nothing, so "
                     f"they are still open ({file}). Tell the user; the verified commit "
                     "is unchanged.")], "a correction changed nothing",
                    retry={"reopen": spend_id},
                    signoff=None if security else {"drop": spend_id},
                    no_signoff="a confirmed security finding is open" if security else None,
                    kind="open-findings", number=None)
    return start_correction(c, "review", file if coder else None, spend_id,
                            rule, checks=checks, also=also)


def kept_checks(c, corr):
    """Whether correction `corr` was the tester's alone (no code part) and the
    user kept the checks it questioned, at the stop the tester's STANDS made:
    nothing was left for it to change."""
    if corr.get("file") or not corr.get("checks"):
        return False
    tester = c.last("acceptance-tester", after=corr["seq"])
    return bool(tester and tester["next"] == "STANDS" and tester.get("signed_off"))


def open_must_fix(text):
    """CODE_REVIEW.md's open must-fix rows."""
    for header, rows in art.tables(art.find_section(text, "Must-fix") or ""):
        if "Status" in header:
            return [r for r in rows if r.get("Status", "").strip().startswith("open")]
    return []


def _category(row):
    return row.get("Category", "").strip().strip("`").lower()


def check_ids(c, rows):
    """The conditions whose checks are in the files the findings' Locations name."""
    try:
        manifest, _ = art.manifest(c.ad / "acceptance" / "MANIFEST.md")
    except art.ArtifactError:
        manifest = []
    ids = set()
    for row in rows:
        where = re.sub(r":\d+$", "", row.get("Location", "").strip().strip("`"))
        ids |= {m["#"].strip() for m in manifest
                if art.check_path(m["Check (path :: test name)"]) == where}
    return sorted(ids, key=cmd_checks.sort_key)


def scope_text(p):
    if p["scope"] == "outside":
        return (f"the commits pushed to the PR branch outside the pipeline (`git diff "
                f"{p.get('since', 'HEAD')}`): " + (", ".join(p["files"]) or "none"))
    return {"first": "the whole change, as committed on the branch: "
                     + (", ".join(p["files"]) or "none"),
            "after-commit": "the uncommitted correction (the working tree against HEAD)",
            }.get(p["scope"], p["scope"])


# ---------------------------------------------------------------- Phase 6: shipping

def publish_step(c):
    """Commit what is verified (and, after a correction, reviewed), push it, and
    publish the PR's description for it: a draft PR on the first publish. None
    once the PR describes the current commit."""
    p6 = c.p6
    sha = p6.get("verified_sha")
    last_fix = next((k for k in reversed(p6["corrections"]) if k["after_commit"]), None)
    needs_commit = sha is None or (last_fix and last_fix["seq"] > p6.get("commit_seq", 0))
    if needs_commit and sha and unchanged(c):
        mark_committed(c, "the correction after the commit changed nothing")
        needs_commit = False
    if needs_commit:
        if sha is None and c.state["settings"].get("open_pr_gate"):
            # Asked again after a re-check changed the code it was asked on.
            gate = c.gate("pr", after=max([k["seq"] for k in p6["corrections"]] + [0]))
            if gate is None or gate["choice"] != "proceed":  # a hold re-asks on resume
                return open_pr_gate(c)
        return commit_step(c)
    if (c.mark("pushed") or {}).get("value") != sha:
        # A pushed value the run didn't record may be a head someone else
        # pushed: re-check it rather than push and record `sha` again.
        moved = moved_head(c, sha)
        if moved:
            return moved
        return action(f"push the branch: `git -C {q(c.wt)} push -u origin HEAD` (never "
                      "--force)", "the verified commit is not pushed yet",
                      AFTER=[c.cmd("mark", "pushed", "--value", sha)])
    if p6.get("published_sha") != sha:
        return body_step(c, sha)
    return None


def reviewed_pass(c):
    """The review pass the PR's description reports: the latest one, or None
    before the first review. Only asked once that pass has settled (phase6
    publishes nothing while a pass is open)."""
    passes = c.p6.get("passes") or []
    return passes[-1]["n"] if passes else None


def ship_step(c, sha):
    """After the reviews: CI on the draft, the ready-for-review gate, the PR
    marked ready, Jira In Review, CI once more, people's comments, the main gate
    and the merge. A commit pushed to the PR branch outside the run is
    re-checked (or stops the run) before any of them."""
    moved = moved_head(c, sha)
    if moved:
        return moved
    p6 = c.p6
    ready = marked_ready(c)
    if not ready:
        ci = ci_step(c, sha)
        if ci is not None:
            return ci
        gate = c.gate("ready", after=p6.get("commit_seq", 0))
        if gate is None or gate["choice"] != "proceed":  # a hold re-asks on resume
            return ready_gate(c)
        body = p6.get("body") or {}
        if not body.get("ready") or triage_seq(c) > body.get("seq", 0):
            # The description gets the gate's answers before the PR is ready:
            # the follow-ups sent to a separate PR, and the open findings the
            # user chose to ship. Inline findings are posted then.
            return body_step(c, sha)
        return action(f"mark the PR ready for review: `gh pr ready {q(p6.get('pr'))}` "
                      f"(run in {q(c.wt)})", "the ready-for-review gate said proceed",
                      AFTER=[c.cmd("mark", "pr-ready")])
    jira = jira_step(c, "in_review", "jira-in-review")
    if jira:
        return jira
    if c.state["settings"].get("ci", "none") != "none" and \
            (p6.get("ci") or {}).get("seq", 0) < ready["seq"]:
        # Workflows that skip drafts run only now: watch CI once more.
        return ci_watch(c, "the PR was marked ready: workflows that skip drafts run now",
                        sha)
    ci = ci_step(c, sha)
    if ci is not None:
        return ci
    human = human_step(c)
    if human:
        return human
    return main_step(c, sha)


def ready_answered(c):
    """Whether the user marked the PR ready at the ready-for-review gate."""
    gate = c.gate("ready")
    return bool(gate and gate["choice"] == "proceed")


def triage_seq(c):
    """The seq of the last answer for a pre-existing security finding (0: none)."""
    return max([m.get("seq", 0) for k, m in (c.state.get("marks") or {}).items()
                if k.startswith("triage-")] + [0])


def open_pr_gate(c):
    """The opt-in gate before the first push (`gates.open_pr` in .auto-dev.yml)."""
    return gate_question(c, "pr", {
        "Open PR": c.cmd("gate", "pr", "proceed"),
        "Hold (don't push yet)": c.cmd("gate", "pr", "hold", "--reason", "<why>"),
        "Stop": c.cmd("gate", "pr", "stop", "--reason", "<why>")},
        "gates.open_pr is on: the user decides before anything is pushed")


def ready_gate(c):
    return gate_question(c, "ready", {
        "Mark ready for review": c.cmd("gate", "ready", "proceed"),
        "Hold (keep it a draft)": c.cmd("gate", "ready", "hold", "--reason", "<why>"),
        "Stop": c.cmd("gate", "ready", "stop", "--reason", "<why>")},
        "the reviews have settled on the draft: the ready-for-review gate")


def last_asked(c):
    """The seq of the last open-the-PR or ready-for-review answer."""
    return max([g["seq"] for g in (c.gate("pr"), c.gate("ready")) if g] + [0])


def stale_twice(c, detail, since=None):
    """The stop for a result stale again right after its own re-run (nobody
    answered a gate or resumed since), or None. Commits brought in on top of a
    newly verified commit (`since`) are a new push, never a second run."""
    outside = next((k for k in reversed(c.p6["corrections"]) if k["entry"] == "outside"),
                   None)
    asked = max(last_asked(c), c.resumed())
    if not outside or outside["seq"] <= asked or (since and outside.get("since") != since):
        return None
    return stop([("A report is stale again right after its own re-run: something "
                 "rewrites the code on every run. Tell the user:"), detail],
                "stale twice running", retry={"lift": True},
                no_signoff="a stale report says nothing about the code that ships", number=12)


def stale_again(c, detail, since=None):
    """A result went stale: re-check the outside changes, unless that re-check
    itself just ran (stale_twice). `since`: the outside changes are commits on
    top of that one (see outside_push)."""
    twice = stale_twice(c, detail, since)
    if twice:
        return twice
    return start_correction(c, "outside", None, None,
                            "the code changed outside the pipeline: re-check it",
                            since=since)


def commit_step(c):
    attempt = c.p6.get("commit_attempt")
    since = max([last_asked(c)] + [k["seq"] for k in c.p6["corrections"]])
    if attempt and attempt["seq"] > since:
        if attempt["result"] == "stale":
            return stale_again(c, "commit found stale results")
        return stop([(f"The commit step failed ({attempt['result']}). Tell the user what "
                     "`autodev.py commit` printed; nothing was pushed.")],
                    "the commit failed", retry={"clear": ["commit_attempt"]},
                    no_signoff="nothing was committed to go on with", number=14)
    # A commit made but not yet checked (`unverified_commit`) leaves a clean tree:
    # `commit` checks it without committing again, so it is offered as usual.
    if not c.p6.get("verified_sha") and not c.p6.get("unverified_commit"):
        add, remove = changed_paths(c.wt)
        if not add and not remove:
            return stop([("There is nothing to commit: the working tree holds no change "
                         "outside .auto-dev/. Tell the user; nothing was pushed.")],
                        "an empty change", retry={},
                        no_signoff="there is no change to ship", number=14)
    first = not c.p6.get("verified_sha")
    return action(f"commit: run `{c.cmd('commit', '--message', '<type>(<scope>): <summary>')}`"
                  f", with a Conventional Commits subject you write for the change ({FILL})",
                  "the build is verified: it is committed and pushed as a draft PR before "
                  "any review" if first else "a correction is verified and reviewed: it is "
                  "committed on top", AFTER=[c.cmd("next")])


def body_step(c, sha):
    from . import cmd_pr  # imported here: cmd_pr imports this module's helpers
    body = c.p6.get("body") or {}
    reviewed, ready = reviewed_pass(c), ready_answered(c)
    if body.get("sha") != sha or body.get("reviewed") != reviewed or \
            bool(body.get("ready")) != ready or triage_seq(c) > body.get("seq", 0):
        c.would("generate the PR description for the verified commit",
                "the commit is pushed: the PR opens next" if reviewed is None else
                "the reviews have settled: the PR's description gets them")
        path = cmd_pr.generate(c.state, c.ad, sha, reviewed=reviewed is not None,
                               ready=ready)
        body = {"sha": sha, "path": str(path), "seq": c.seq(), "reviewed": reviewed,
                "ready": ready}
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
                         (f"The description is {body['path']}"
                          + (f", and the sections the orchestrator writes are in "
                             f"{Path(body['path']).parent / 'pr-write.md'}"
                             if (Path(body['path']).parent / 'pr-write.md').exists()
                             else "")
                          + ". Once the cause is fixed (the description edited, or "
                          "GitHub working again), `auto-dev continue` publishes it "
                          "again.")],
                        "pr publish was refused", retry={"lift": True},
                        no_signoff="the PR description must pass its checks", number=None)
        if "rewrite" not in body:
            body["rewrite"] = attempt["seq"]
            c.dirty = True
        return write_body(c, body, "the description still holds a WRITE line",
                          refused=attempt.get("problems"))
    if c.p6.get("pr") and (body.get("published_seq") or 0) < body["seq"]:
        return action(f"publish the refreshed PR body: run `{c.cmd('pr', 'publish')}`",
                      "the PR body describes an older commit, or the code before its "
                      "reviews", AFTER=[c.cmd("next")])
    if c.p6.get("pr"):
        return None
    return write_body(c, body, "the commit is pushed: the draft PR opens next")


def write_body(c, body, rule, refused=None):
    slots = Path(body["path"]).parent / "pr-write.md"
    target = (f"{slots}, the sections you write of the PR body {body['path']} "
              "(don't read that file: pr publish puts them in)" if slots.exists() else
              f"the PR body {body['path']}")
    return action(f"fill in {target}: "
                  "replace every `<!-- WRITE: ... -->` line (references/ship.md, "
                  "_The PR body_), in plain words for a "
                  "developer who has never heard of auto-dev; change nothing else. Then "
                  "run AFTER" + (". `pr publish` refused the last one: " + "; ".join(refused)
                                 if refused else ""), rule, AFTER=[c.cmd("pr", "publish")])


def ci_watch(c, rule, sha=None):
    """Watch CI on `sha`, the pushed commit, named so that a tests commit made
    on top of it (and not pushed) doesn't stand in for it. A watch run since
    `sha` was committed (and since the last resume or retry) that reported on
    another commit stops the run, rather than asking for a watch that would
    never settle on `sha`."""
    ci = c.p6.get("ci") or {}
    other = ci.get("sha")
    if sha and other and other != sha and \
            ci.get("seq", 0) > max(c.p6.get("commit_seq", 0), c.resumed()):
        return stop([(f"CI is to settle on the pushed commit {sha[:12]}, but `ci-watch` "
                      f"reported on {other[:12]} instead, so CI never reported on "
                      f"{sha[:12]}. Tell the user; `auto-dev continue` watches "
                      f"{sha[:12]} again.")],
                    "CI reported on another commit", retry={"lift": True},
                    no_signoff="CI never reported on the commit that ships")
    watch = c.cmd("ci-watch", "--sha", sha) if sha else c.cmd("ci-watch")
    return action(f"watch CI: run `{watch}` (it waits up to 9 minutes), "
                  "then run AFTER whatever it exits: `next` asks for another watch "
                  "while CI is still pending", rule, AFTER=[c.cmd("next")])


def ci_step(c, sha):
    if c.state["settings"].get("ci", "none") == "none":
        return None
    ci = c.p6.get("ci") or {}
    rewatch = c.resumed() > ci.get("seq", 0)
    if ci.get("sha") != sha or ci.get("status") == "pending" or (rewatch and \
            ci.get("status") != "green"):
        return ci_watch(c, "CI has not settled on the pushed commit", sha)
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
                        "a CI correction changed nothing",
                        retry={"reopen": f"ci-{triage['n']}"},
                        no_signoff="never merge over red CI", number=None)
        return start_correction(c, "ci", triage_file(c, triage), f"ci-{triage['n']}",
                                "CI is red because of the code (a round)",
                                why=f"Red checks: {red}.")
    if kind == "SECRET":
        return stop([("CI failed on a secret or credential problem. Tell the user the "
                     f"red checks ({red}) and what the triager said "
                     f"({triage_file(c, triage)}). Once the secret is fixed and CI re-run, "
                     "`auto-dev continue` watches it again.")],
                    "the triager returned SECRET", retry={"lift": True},
                    no_signoff="never merge over red CI", number=15)
    # INFRA, FLAKY or UNKNOWN: not the coder's to fix. Stop here, before Jira
    # moves on a red build; a resume watches CI again.
    return stop([(f"CI is red, and the triager classed it {kind}: not something the code "
                 f"can fix. Tell the user the red checks ({red}) and what the triager "
                 f"found ({triage_file(c, triage)}). The run stops here; once CI is fixed "
                 "or re-run, `auto-dev continue` watches it again.")],
                f"the triager returned {kind}", retry={"lift": True},
                no_signoff="never merge over red CI", number=15)


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
    spec = spec_stop(c, [triage], "from a comment on the PR")
    if spec is not None:
        return spec
    blockers = _int(triage["data"].get("blockers"))
    checks = None
    if _int(triage["data"].get("acceptance_checks")):
        checks = {"scope": HUMAN_SCOPE, "report": triage_file(c, triage, "checks_file")}
    if blockers or checks:
        return start_correction(c, "human", triage_file(c, triage) if blockers else None,
                                spend_id, "people's comments on the PR need a correction "
                                "(a round): checks to the tester, blockers to the coder",
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
            ruling = {"STANDS": "ruled them right as written, and the user kept them",
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
                         "what it says.")], "a merge whose outcome is unknown", number=None)
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
                        "merge-pr did not merge", retry={"clear": ["merge_attempt"]},
                        no_signoff="the PR is not merged", number=18)
        ci = p6.get("ci") or {}
        if ci.get("status") == "red":
            return stop(["CI is red on the PR; never merge over it. Tell the user each "
                         "red check: " + "; ".join(ci.get("failing", []))],
                        "red CI at the main gate", retry={"lift": True},
                        no_signoff="never merge over red CI", number=17)
        return action(f"merge: run `{c.cmd('merge-pr', '--pr', p6.get('pr'), '--sha', sha)}`",
                      "the main gate said proceed", AFTER=[c.cmd("next")])
    if not c.mark("main-ci"):
        return action(f"check CI on {c.state['repo']['base']} for the merge of PR "
                      f"#{p6.get('pr')} (references/ship.md, CI after the merge; its "
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
        return action("write the final report for the user (references/ship.md, "
                      "_The final report_): what shipped, the PR, the checks for a "
                      "person, the budget used, anything left open"
                      + (f"; and that the review findings could not all be posted on "
                         f"the PR ({failed}): they are in CODE_REVIEW.md and "
                         "SECURITY_REVIEW.md" if failed else ""),
                      "the PR is merged", AFTER=[c.cmd("mark", "final-report")])
    if c.state["repo"].get("adopted"):  # the user made the worktree: never remove it
        c.finish(6, f"merged PR #{p6.get('pr')}")
        return {"code": NEXT_COMPLETE, "ACTION": "the run is complete; nothing more to do",
                "RULE": "the run used the user's own worktree, which stays"}
    gate = c.gate("cleanup")
    if gate is None:
        saved, inside = metrics.saved_path(c.state), c.ad / metrics.FILE
        if metrics.copy_error(c.state) is None:
            told = f"That deletes .auto-dev/ too; its metrics.json stays at {saved}."
        else:
            told = ("That deletes .auto-dev/ too, and the run's metrics with it: the "
                    f"metrics copy could not be written to {saved}, so {inside}, written "
                    "when you answer, is their only copy; save it first if you want them.")
        return ask(c, "the worktree", [f"The run is finished. Remove the worktree {c.wt}? "
                                       + told],
                   [cmd_review.question("Cleanup", f"Remove the worktree {c.wt}?",
                                        ["Remove it", "Keep it"])],
                   [("Remove it", c.cmd("gate", "cleanup", "proceed")),
                    ("Keep it", c.cmd("gate", "cleanup", "keep"))],
                   "the final report is written")
    c.finish(6, f"merged PR #{p6.get('pr')}")
    if gate["choice"] == "proceed":
        return remove_worktree(c)
    return {"code": NEXT_COMPLETE, "ACTION": "the run is complete; nothing more to do",
            "RULE": "the worktree stays: " + (gate.get("reason") or "the user kept it")}


def remove_worktree(c):
    """The user answered the worktree question "Remove it": the
    `cleanup-worktree` command (UNSAVED, the ACTION main() prints instead when
    the metrics copy could not be written, which also names `gate cleanup keep`
    for a user who keeps the worktree after all). Given again by every `next`
    until the worktree is gone or recorded as kept, as `cleanup-worktree` does
    when git refuses (st.cleanup_pending, which counts only a removal a
    `next` gave: state["cleanup_given"], never saved under --explain)."""
    if not c.readonly and not c.state.get("cleanup_given"):
        c.state["cleanup_given"] = True
        c.dirty = True
    saved, inside = metrics.saved_path(c.state), c.ad / metrics.FILE
    cleanup, home = c.cmd("cleanup-worktree"), q(c.state["repo"]["main_checkout"])
    keep = c.cmd("gate", "cleanup", "keep")
    return {"code": NEXT_COMPLETE, "RULE": "the user chose to remove the worktree",
            "ACTION": (f"run `{cleanup}` from {home}; then the run is complete (its "
                       "state goes with the worktree; its metrics stay at "
                       f"{saved})"),
            UNSAVED: (f"the metrics copy could not be written to {saved}: tell the "
                      f"user that {inside} is the run's only metrics file and goes "
                      f"with the worktree, and run `{cleanup}` from {home} only once "
                      "they have saved it or said to go on; then the run is complete "
                      "(its state and metrics go with the worktree). If they decide to "
                      f"keep the worktree instead, run `{keep}`: then the run is complete "
                      "and the worktree stays")}


def moved_head(c, sha):
    """The step for a PR branch moved to a commit the run did not make (see
    outside_push), or None. Fetches the branch (also when probing for a
    checkpoint; a fetch that can't reach origin uses the last one fetched) and
    compares commits, not trees: during a correction the reports describe the
    corrected working tree, which is no outside push. None before the run's
    first recorded push and when origin has no such branch (a tracking ref left
    from an earlier branch of that name is no PR's head), when the branch is at
    `sha` or at the commit under re-check, behind `sha` (the run's own commit
    not pushed yet), or past it by the run's own tests commits alone. A branch
    still at the commit the run verified and recorded as pushed, which `sha`
    doesn't descend from, is no outside push either: the worktree's branch was
    rewritten (see rewritten_push)."""
    pushed = (c.mark("pushed") or {}).get("value")
    if not sha or not pushed:
        return None
    branch = c.state["branch"]
    if not c.readonly or c.probing:
        code, _, _ = git(c.wt, "fetch", "-q", "origin", branch, check=False)
        if code != 0:
            # ls-remote exits 2 when origin answers without the branch (deleted
            # on GitHub, say), and otherwise when origin can't be reached.
            code, _, _ = git(c.wt, "ls-remote", "--exit-code", "origin",
                             f"refs/heads/{branch}", check=False)
            if code == 2:
                return None
    code, out, _ = git(c.wt, "rev-parse", "--verify", "--quiet",
                       f"origin/{branch}^{{commit}}", check=False)
    remote = out.strip() if code == 0 else ""
    if not remote or remote in (sha, c.p6.get("unverified_commit")):
        return None
    code, _, _ = git(c.wt, "merge-base", "--is-ancestor", remote, sha, check=False)
    if code == 0:
        return None
    code, out, _ = git(c.wt, "rev-list", f"{sha}..{remote}", check=False)
    revs = out.split() if code == 0 else []
    if revs and set(revs) <= set(cmd_work.tests_shas(c.state)):
        return None
    if remote == pushed and pushed in (c.p6.get("verified_shas") or []):
        return rewritten_push(c, sha, remote)
    # From the merge base: when the run's own unpushed commit and the outside
    # commits diverged, only what the outside commits changed.
    _, out, _ = git(c.wt, "diff", "--name-only", f"{sha}...{remote}", check=False)
    files = [f for f in out.splitlines() if f and not f.startswith(".auto-dev/")]
    detail = (f"the PR's branch is at {remote[:12]}, past the checked commit {sha[:12]}; "
              "files changed on it: " + (", ".join(files) or "none"))
    return outside_push(c, sha, detail)


def rewritten_push(c, sha, remote):
    """The PR's branch is still at `remote`, the commit the run pushed, but
    `sha` doesn't descend from it: the user rebased or amended the branch in
    the worktree and didn't push it. No one else pushed, so stop 16's merge
    would bring the old commits back over the rewrite; the push needs a force,
    which the run never uses, so the user pushes it."""
    wt = q(c.wt)
    return stop([(f"The PR's branch is still at {remote[:12]}, the commit the run "
                  "pushed, but the branch in the worktree was rewritten since (rebased "
                  f"or amended there), so its head {sha[:12]} doesn't build on that "
                  "commit and a plain push would be refused. No one else pushed to the "
                  "PR. The run never force-pushes. Tell the user: to ship the rewritten "
                  f"branch, they push it themselves with `git -C {wt} push "
                  "--force-with-lease origin HEAD` and say `auto-dev continue`; the run "
                  "then goes on from the push.")],
                "the worktree's branch was rewritten", retry={},
                no_signoff="the run never force-pushes", number=16)


def outside_push(c, sha, stale):
    """The PR's branch moved past the verified commit: seen by moved_head before
    a CI watch, a push or a gate, and by the main gate's freshness check. Once
    the user has brought those commits into the worktree (HEAD is the PR's
    head), they are re-checked like any outside change (the quality gate, the
    verifier, then a review pass on what changed since `sha`, the working tree
    with it: a correction the run left uncommitted is reviewed with them), and
    `commit` then verifies HEAD, or commits the re-check's edits on top.
    With such a correction in the worktree, the report has the user stash it
    around the merge, which git would otherwise refuse. `stale` names what
    changed."""
    branch = c.state["branch"]
    head = git(c.wt, "rev-parse", "HEAD").strip()
    code, remote, _ = git(c.wt, "rev-parse", f"origin/{branch}", check=False)
    if code == 0 and remote.strip() == head and head != sha:
        twice = stale_twice(c, stale, since=sha)  # before c.would: --explain shows it
        if twice:
            return twice
        c.would("re-check the PR branch's commits brought into the worktree",
                "the user brought the outside commits in")
        c.p6["unverified_commit"] = head  # a clean `commit` verifies it, no new commit
        c.dirty = True
        return stale_again(c, stale, since=sha)
    ref = q("origin/" + branch)
    behind = code == 0 and git(c.wt, "merge-base", "--is-ancestor", "HEAD",
                               f"origin/{branch}", check=False)[0] == 0
    wt = q(c.wt)
    if code != 0 or behind:
        bring = f"`git -C {wt} merge --ff-only {ref}`"
    else:
        # The run's own unpushed commit and the outside commits diverged: a
        # fast-forward can't take them, a merge pushed to the branch can.
        bring = (f"`git -C {wt} merge {ref}` (resolving any conflict and "
                 f"committing the merge), then push it with `git -C {wt} push "
                 "origin HEAD`,")
    add, remove = changed_paths(c.wt)
    if add or remove:
        # git refuses a merge that would overwrite the uncommitted correction.
        # Staged first, a file the correction added comes back from the stash
        # as a merge, not as an untracked file the pop refuses to restore.
        paths = sorted(printable(p) for p in add + remove)
        named = ", ".join(paths[:5]) + (f" and {len(paths) - 5} more"
                                        if len(paths) > 5 else "")
        how = (f"the run's correction is uncommitted ({named}), so to ship those "
               f"commits they first set it aside with `git -C {wt} add -A` and "
               f"`git -C {wt} stash push --include-untracked`, bring the commits "
               f"into the worktree with {bring.rstrip(',')}, then bring the "
               f"correction back with `git -C {wt} stash pop`, resolving any "
               "conflict it reports,")
    else:
        how = f"to ship them, they bring them into the worktree with {bring}"
    return stop([("The PR's branch holds commits the pipeline did not check (someone "
                  f"pushed to it). Tell the user: {how} and say `auto-dev continue`; "
                  "the pipeline then re-checks them (quality gate, verifier, review) "
                  "before it goes on:"), stale], "the PR head moved", retry={},
                no_signoff="the pipeline never ships commits it did not check", number=16)


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

