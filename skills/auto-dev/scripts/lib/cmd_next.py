"""autodev.py next — print the pipeline's one next action.

Usage:
    autodev.py next [--dir <artifact-dir>] [--explain] [--json]

Reads state.json (the workers' recorded results, the briefs issued, the FIX
outcomes, the gates, the marks and the Phase 6 fields) and the artifacts, and
prints the one thing to do now. Run it, do exactly that, run every AFTER
command, then run `next` again. It never needs you to judge a file.

It records the workers' results itself first: each issued brief whose result
file exists and isn't recorded yet is recorded as `autodev.py record` would
(one it can't accept is refused, its issues saved for the retry), so spawned
workers need no `record` call. A brief with no result file is issued again as
it is. Run `next` only once every agent of the last spawn returned.

It does the mechanical steps itself rather than asking you to: it writes the
brief of the worker to spawn, spends a round of the budget before a
re-review or a correction, installs the sealed acceptance checks before Phase 5's cleanup,
applies a reviewer's FIX blocks, checks the acceptance tester's
manifest, reads the verifier's verdicts, plans and applies the code-review
re-votes, takes the review snapshot, and generates the PR body.

Workers never negotiate the contract between themselves. A coder that finds
a plan step wrong builds it the way that works and lists the deviation
(deviations/coder-<n>.md); the ready-for-review gate summary names each one. A later worker
that finds a SPEC.md criterion wrong or missing (the verifier, the review
judge, a security reviewer, the triager from a PR comment) lists it in
spec-problems/<worker>-<n>.md, and `next` stops and asks the user before it
acts on that result. A check the verifier, the code review or a PR comment
questions goes to the acceptance tester's repair mode; if it rules the check
right as written (STANDS), `next` stops and asks the user. What the user keeps
at either stop is told to every later worker that judges it.

One iteration budget of rounds covers the run: a re-review after FIX blocks,
a tester re-spawn for gaps, a re-dispatched BLOCKED step, and each correction
(after verification, a review pass, a PR comment or red CI) spend one. With
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
       not run) — never a pass
    3  the run is complete
    4  stop and report: tell the user the REPORT lines; with a QUESTION, ask
       how to go on and run the AFTER line for the answer (an `override`
       command; a typed answer is the fixer's instruction), then `next`;
       otherwise do nothing more
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
cut-off session, say); one `next` refused is re-issued as a new brief that
carries the refused issues (as `brief --retry <n>` writes). Spawned three
times with no usable result, it stops. A stop on a worker (blocked, failed
twice, never returned) is lifted by `resume`: the next session spawns that
worker again. A stop on a result (a red quality gate, an impossible spec)
comes back until the user overrides it. Every stop but the budget's, a gate's
Stop, a failed setup and a merge of unknown outcome prints a QUESTION and is
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
from pathlib import Path

from . import artifacts as art
from . import (
    briefs,
    cmd_checks,
    cmd_review,
    cmd_work,
    judgment,
    overrides,
    sealed,
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
CHECKPOINT_EVENTS = 80  # about 35 workers; tune on the fixture repo
SLOTS = ("R1", "R2", "R3")
SECURITY = ("security-reviewer", "security-reviewer-sensitive")
JIRA_DEFAULTS = {"in_progress": "In Progress", "in_review": "In Review", "done": "Done"}
# Workers whose results drive the build-verify loop (Phases 4-6).
LOOP = ("verifier", "coder", "cleanup", "acceptance-tester", "planner")
NONE = ("none", "", None)
ONLY_RE = re.compile(r"ONLY conditions ([^:]+):")
ENTRY_POINT_SCOPE = "ALL CONDITIONS whose checks call an entry point the revised plan changed"
GATE_SCOPE = "ONLY the conditions whose checks fail the quality gate"
HUMAN_SCOPE = "ONLY the conditions whose checks the PR comments in the report question"
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
        self.quiet = False  # state["stop"] changed: saved, but not an event of its own
        self.recorded = []  # the RECORDED lines of the results this call recorded
        self.readonly = bool(getattr(args, "explain", False))
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
         after_fix=None):
    """A stop. With `retry` (what `override retry` does: results to set aside,
    phase6 keys to clear, a stop to lift, a correction to reopen), the user can
    override it: `next` asks how (stop_point). `signoff` is what a sign-off
    does (a result to rewrite as passed, results to set aside, a correction id
    to drop); with none, `no_signoff` says why it isn't offered."""
    result = {"code": NEXT_STOP, "ACTION": "stop and report to the user; do nothing more",
              "REPORT": report, "RULE": rule}
    if retry is not None:
        result["OVERRIDE"] = {"retry": retry, "signoff": signoff, "kind": kind,
                              "no_signoff": None if signoff else (
                                  no_signoff or "there is no result to accept"),
                              "after_fix": after_fix}
    return result


def job_of(rec):
    return [rec["worker"], rec["n"]]


def spawn(c, worker, mode=None, sets=None, rule="", budget=None, agent=None):
    return spawn_many(c, [(worker, mode, sets or {})], rule, budget, agent)


def spawn_many(c, jobs, rule, budget=None, agent=None):
    """Spawn each (worker, mode, sets[, agent]) job in one message."""
    agents, briefs_, prompts, efforts = [], [], [], []
    for job in jobs:
        worker, mode, sets = job[:3]
        job_agent = job[3] if len(job) > 3 else agent
        kept, used = kept_texts(c), briefs.slots(worker, mode)
        sets = {**sets, **{slot: kept[slot] for slot in KEPT_SLOTS.get(worker, ())
                           if slot in kept and slot in used}}
        if c.readonly:
            n = c.peek(worker)
            path = c.ad / "briefs" / f"{worker}-{n}.md"
        else:
            if worker == "acceptance-tester" and mode == "repair":
                rebase_installed(c)
            path, _ = cmd_work.write_brief(c.state, c.ad, worker, mode, dict(sets))
            c.dirty = True
            n = int(path.stem.rsplit("-", 1)[1])
        agents.append(job_agent or f"auto-dev:{worker}")
        briefs_.append(str(path))
        prompts.append(cmd_work.prompt_for(path))
        efforts.append(effort_for(c, worker))
    return spawn_lines(agents, briefs_, prompts, rule, budget, efforts)


def rebase_installed(c):
    """Before a repair in place, make each shared test file's own lines (the file
    without the checks in it) its base and the file its sealed copy, so the
    coder's edits to that file since the checks went in aren't read as the
    tester's, whether or not the repair touches it."""
    if not cmd_checks.installed(c.ad):
        return
    wt = Path(c.state["worktree"])
    for rel in sealed.sealed_files(c.ad):
        if sealed.base_of(c.ad, rel) is not None:
            sealed.rebase(c.ad, rel, sealed.read(wt / rel))


def spawn_lines(agents, briefs_, prompts, rule, budget=None, efforts=None):
    """efforts, when any is set, parallels agents ("" for an agent spawned at its
    own effort). No AFTER line: the next `next` records what they return."""
    efforts = efforts if efforts and any(efforts) else None
    what = (f"spawn {agents[0]} with the PROMPT" if len(agents) == 1 else
            f"spawn these {len(agents)} agents in one message, in parallel, each "
            "with its PROMPT")
    what += "; once every agent returned, run `next` (it records their results)"
    if efforts:
        what += ", passing its EFFORT as the Agent tool's `effort` parameter"
    return action(what, rule, AGENT=agents, BRIEF=briefs_, PROMPT=prompts,
                  EFFORT=efforts, BUDGET=budget)


def plan_effort(c):
    """The code reviewers' effort the plan recommends; high when it names none
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
                 f"State and artifacts: {c.ad}"], f"the budget is used up: {what}")


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
                "spec_changed": any(p.endswith("/SPEC.md") or p.endswith("/IMPLEMENTATION.md")
                                    for p in changed),
                # A gate check's command in the settings counts: the gate runs again.
                "code_changed": any(not p.startswith(scratch(c) + "/") or
                                    p.startswith(scratch(c) + "/acceptance/") or
                                    p == scratch(c) + "/state.json"
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
        # The open correction's loop runs the gate and the verifier again, and
        # its review pass covers the fixer's files with its own.
        return None
    if changed and st.phase(c.state, 6)["status"] == "in-progress":
        c.p6.setdefault("corrections", [])
        c.p6.setdefault("passes", [])
        return start_correction(c, "fix", None, None,
                                "the fixer changed the code or its contract at a stop: "
                                "the quality gate, the verifier and (once committed) a "
                                "review of what it changed run again (no round)")
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
    rebase_installed(c)  # each whole check file is its sealed copy: `record` reseals an edit
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
        for p in paths:  # `record` may have resealed it: its snapshot goes back too
            rel = p[len("acceptance/files/"):-len(".sealed")]
            if p.startswith("acceptance/files/") and p.endswith(".sealed") and \
                    sealed.base_of(c.ad, rel) is not None:
                sealed.snapshot(c.ad, rel, sealed.read(c.ad / p))
    if brief.get("settings") is not None and c.state.get("settings") != brief["settings"]:
        c.state["settings"] = copy.deepcopy(brief["settings"])  # a gate check's command
        undone.append(f"{scratch(c)}/state.json")
    return undone


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
        # A step `next` could not take is a stop, never exit 1; nothing of the
        # step is saved, since it did not happen (the results recorded first were).
        failed = stop([f"`next` could not take its step ({exc.token}): {exc}",
                       ("Tell the user; it is a broken artifact or an auto-dev bug. "
                        f"State and artifacts: {c.ad}")],
                      f"a step failed: {exc.token}")
        if c.recorded:
            failed["RECORDED"] = c.recorded
        return show(failed, args)
    result = stop_point(c, result)
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
    left to `pending_briefs`, which issues it again as it is. One line per job.
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
        kept = (f"The run's files are in the user's own worktree {c.wt}, which stays."
                if c.state["repo"].get("adopted") else
                f"The worktree is kept: {c.wt} (remove it with "
                f"`git worktree remove {q(c.wt)}`).")
        rows.append("The task is too big for one PR. Tell the user Define's reasons, the "
                    "subsystems it found and its suggested split lines, below. Jira was "
                    f"not moved. {kept}")
        rows += size_check(c)
    rows.append(f"State and artifacts: {c.ad}")
    define = c.last("define", mode="write")
    if how == "stopped" and c.state.get("size") == "OVERSIZED" and define and \
            define["next"] == "OVERSIZED":
        return stop(rows, "Define found the task too big for one PR (OVERSIZED)",
                    retry={"aside": [job_of(define)], "oversized": True},
                    signoff={"rewrite": [define["worker"], define["n"], "FITS"],
                             "fits": True},
                    kind="oversized", after_fix="fits")
    return stop(rows, f"the run is {how}")


def size_check(c):
    """SPEC.md's Size check section, line by line, for the OVERSIZED report."""
    try:
        section = art.find_section(art.read(c.ad / "SPEC.md"), "Size check")
    except art.ArtifactError:
        section = None
    lines = [ln.strip() for ln in (section or "").splitlines() if ln.strip()]
    if not lines:
        return [("SPEC.md has no Size check section; its Context says what the task "
                 f"touches ({c.ad}/SPEC.md).")]
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
                         "never left a result that `next` accepts. Tell the user; its "
                         f"brief is {c.ad}/briefs/{b['worker']}-{b['n']}.md. Once the "
                         "cause is fixed, `auto-dev continue` spawns it again.")],
                        "a worker failed to return three times", retry={"lift": True})
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
    # The code reviewers run in parallel with each other and with the security
    # reviewer: review_step re-spawns a failed slot, and their results would hide
    # the security reviewer's.
    log = [e for e in c.log if e.get("seq", 0) > c.resumed()
           and e["worker"] not in ("code-reviewer", "fixer")]
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
                    f"a worker returned status {latest['status']}", retry={"lift": True})
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
    review = review_loop(c, "define-reviewer", "define", c.ad / "SPEC.md", define["seq"])
    if review:
        return review
    c.finish(2, f"FITS, high risk: {'yes' if c.state.get('high_risk') else 'no'}")
    return None


def jira_step(c, key, step):
    ticket = c.state["task"].get("ticket")
    if not ticket or ticket == "none":
        return None
    choice = c.gate("jira")
    name = c.state["settings"].get("jira_states", {}).get(key, JIRA_DEFAULTS[key])
    if choice is None:
        already = f"Already {name}"
        out = ask(c, "Jira", [(f"Define confirmed the task fits one PR. Move {ticket} to "
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


def review_loop(c, reviewer, author, target, after):
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
        return None if clean else re_review(c, reviewer, spend_id, fix)
    if fix in NONE:
        return stop([(f"{reviewer} #{review['n']} found {review['data'].get('blockers')} "
                     "blocker(s) but wrote no FIX block. Tell the user; the review is "
                     f"in its reply and {c.ad}.")], "blockers with nothing to apply",
                    retry={"aside": [job_of(review)]},
                    signoff={"rewrite": [review["worker"], review["n"], "CLEAN",
                                         {"blockers": "0", "fix_file": "none"}]},
                    kind="review-no-fix")
    if apply_once(c, target, fix) == "applied":
        return None if clean else re_review(c, reviewer, spend_id, fix)
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


def re_review(c, reviewer, spend_id, fix):
    budget = c.spend(spend_id, f"{reviewer} re-review")
    if budget is None:
        return exhausted(c, f"no round left for a {reviewer} re-review",
                         f"Tell the user each open blocker in {fix}, one by one.")
    return spawn(c, reviewer, rule="the fixes changed the file: review it again (a round)",
                 budget=budget)


# ---------------------------------------------------------------- Phase 3

def phase3(c):
    start = c.start(3)
    plan = c.last("planner", after=start, mode="write")
    if plan is None:
        return spawn(c, "planner", "write", rule="Phase 3 starts with the planner")
    review = review_loop(c, "plan-reviewer", "planner", c.ad / "IMPLEMENTATION.md",
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
            budget = c.spend(f"acceptance-tester-{tester['n']}", "tester re-spawn")
            if budget is None:
                return exhausted(c, "no round left to rewrite the checks",
                                 f"Conditions {ambiguous} read the other way now.")
            return spawn(c, "acceptance-tester", "write", {
                "scope": f"ONLY conditions {ambiguous}: SPEC.md now says which reading "
                         "is meant, and it is not the one your checks test"},
                rule="Define chose the other reading: rewrite those checks", budget=budget)
    gaps = manifest_gaps(c)
    if gaps:
        ids, lines = gaps
        budget = c.spend(f"acceptance-tester-{tester['n']}", "tester re-spawn")
        if budget is None:
            return exhausted(c, "no round left for the acceptance gaps",
                             "Tell the user each gap: " + "; ".join(lines))
        return spawn(c, "acceptance-tester", "write", {
            "scope": f"ONLY conditions {', '.join(ids)}: " + "; ".join(lines)},
            rule="check-manifest found gaps in the tester's return (a round)",
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
                    no_signoff="the gate's checks protect what ships")
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
    result = loop_step(c, start, "phase5", first=None)
    if result is DONE_MARK:
        c.finish(4)
        return None
    return result


# ---------------------------------------------------------------- Phases 5 and 6:
# the build-verify loop

DONE_MARK = object()


def loop_step(c, start, scope, first, files=None, after_change="a correction"):
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
            return blocked_step(c, latest)
        if in_phase4:
            return DONE_MARK
        if scope != "phase5" or c.recs("cleanup", after=start):
            return cleanup_spawn(c, scope, files, "the code changed: the cleanup agent "
                                 "simplifies it and runs the quality gate (no round)")
        return recheck(c, start, after_change)
    if worker == "planner":
        coder = c.last("coder", after=start, before=latest["seq"])
        return blocked_step(c, coder)
    if worker == "acceptance-tester":
        if latest.get("mode") == "fold" and first is not None:
            return first()  # install the rest, then cleanup
        trigger = next((r for r in reversed(recs[:-1])
                        if r["worker"] != "acceptance-tester"), None)
        if trigger and trigger["worker"] == "planner":
            coder = c.last("coder", after=start, before=trigger["seq"])
            return blocked_step(c, coder)
        if trigger and trigger["worker"] == "cleanup":
            if nxt == "STANDS":
                return stop([("The quality gate fails on an acceptance check, and the "
                             "acceptance tester ruled the check right as written, so "
                             "neither can fix it. Tell the user both sides: the cleanup "
                             f"agent's reports in {c.ad}/lint/ and the tester's reply.")],
                            "the tester ruled a check that fails the quality gate stands",
                            retry={"aside": [job_of(latest), job_of(trigger)]},
                            signoff={"aside": [job_of(latest)],
                                     "rewrite": [trigger["worker"], trigger["n"], "GREEN"],
                                     "reports": failing_reports(c)},
                            kind="red-gate")
            return cleanup_spawn(c, scope, files, "the repaired check passes the gate now? "
                                 "Run the cleanup agent again (no round)")
        if nxt == "STANDS" and questioned(latest) and not latest.get("signed_off"):
            if trigger and trigger["worker"] == "verifier":
                return disputed_stop(c, latest, "the verifier",
                                     f"{c.ad}/SPEC_EVAL.md (Defective acceptance checks)")
            corr = (c.p6.get("corrections") or [None])[-1]
            who = "a PR comment" if (corr or {}).get("entry") == "human" else "the code review"
            return disputed_stop(c, latest, who, str(((corr or {}).get("checks") or {})
                                                     .get("report") or c.ad))
        if trigger and trigger["worker"] == "verifier" and trigger["next"] in (
                "CORRECT", "INSTALL_CONFLICT"):
            return coder_correction(c, f"{c.ad}/evidence/corrections.md", None,
                                    "the checks are repaired; now the code's correction "
                                    "(the round is already spent)")
        if in_phase4:
            return DONE_MARK if c.last("coder", after=start)["next"] == "BUILT" else None
        if nxt == "STANDS":
            return recheck(c, start, "the user kept the questioned acceptance checks as "
                           "written (judge them as written)")
        if scope == "phase5" and c.recs("cleanup", after=start):
            # The repaired check is a changed file: the gate runs on it before the
            # re-check, so Phase 5 never ends on stale lint reports.
            return cleanup_spawn(c, scope, files, "an acceptance check was repaired: the "
                                 "cleanup agent runs the quality gate on it (no round)")
        return recheck(c, start, "an acceptance-check repair")
    if worker == "cleanup":
        if nxt != "GREEN" and gate_signed(c):
            nxt = "GREEN"  # only checks the user signed off still fail
        if nxt == "GREEN":
            if scope == "phase5" and not c.recs("verifier", after=start):
                return verifier_first(c, "the quality gate is green: the verifier's first "
                                      "pass checks the code that ships")
            return recheck(c, start, "the cleanup pass" if scope == "phase5" else
                           after_change)
        if nxt == "RED":
            return stop([("The quality gate can't be made green; never ship a red build. "
                         f"Tell the user which checks fail: {c.ad}/lint/.")],
                        "the cleanup agent returned RED",
                        retry={"aside": [job_of(latest)]},
                        signoff={"rewrite": [worker, n, "GREEN"],
                                 "reports": failing_reports(c)}, kind="red-gate")
        budget = c.spend(f"cleanup-{n}", "acceptance-check repair")
        if budget is None:
            return exhausted(c, "no round left for an acceptance-check repair",
                             f"The quality gate fails on an acceptance check: {c.ad}/lint/.")
        return spawn(c, "acceptance-tester", "repair", {
            "scope": GATE_SCOPE,
            "report": f"the quality gate fails on an acceptance check's lines: see the "
                      f"cleanup agent's reports in {c.ad}/lint/"},
            rule="an acceptance check fails the quality gate: the tester repairs it",
            budget=budget)
    # the verifier
    if nxt == "MUTATION_LEFT_CHANGES":
        return stop([("The mutation step may have left changes in the source; the tree "
                     "may not be the code that was built. Tell the user the paths the "
                     "verifier named; build nothing more on it.")],
                    "the verifier returned MUTATION_LEFT_CHANGES",
                    retry={"aside": [job_of(latest)]},
                    no_signoff="the tree may hold a planted change; check it, then retry")
    spec = spec_stop(c, [latest], "while verifying the build")
    if spec is not None:
        return spec
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
        fixed = last_fix(c, after=max(start, changed["seq"] if changed else 0))
        cleaned = c.recs("cleanup", after=(fixed["done_seq"] if fixed else
                                           changed["seq"] if changed else start))
        if (cleaned and (cleaned[-1]["next"] == "GREEN" or gate_signed(c))) or (
                coder is None and fixed is None and scope != "phase5"):
            return DONE_MARK
        return cleanup_spawn(c, scope, files, "every condition is met: the cleanup agent "
                             "simplifies and runs the quality gate (no round)")
    _token, fields = cmd_checks.eval_decision(
        c.ad, install_conflict=nxt == "INSTALL_CONFLICT")
    budget = c.spend(f"verifier-{n}", "correction after verification")
    if budget is None:
        return exhausted_loop(c, fields)
    ids = [x.strip() for x in fields.get("repair", "").split(",") if x.strip()]
    if ids and c.last("acceptance-tester", after=latest["seq"]) is None:
        return spawn(c, "acceptance-tester", "repair", {
            "scope": f"ONLY conditions {', '.join(ids)}: the verifier judged their checks "
                     "defective",
            "report": f"{c.ad}/SPEC_EVAL.md, section Defective acceptance checks"},
            rule="defective checks are repaired first (the same round)", budget=budget)
    return coder_correction(c, f"{c.ad}/evidence/corrections.md", budget,
                            "the verifier found open items (a round)")


def failing_reports(c):
    """The quality-gate reports that fail now."""
    return [g.get("report", "") for g in c.state["settings"].get("gate", [])
            if not cmd_work.lint_passes(c.ad / "lint" / g.get("report", ""))]


def gate_signed(c):
    """Whether the gate fails only on checks the user signed off."""
    failing = failing_reports(c)
    return bool(failing) and set(failing) <= overrides.signed_reports(c.state)


def last_fix(c, after):
    """The last fix at a stop, after seq `after`, that changed the code or a
    check: the quality gate runs on it before the loop ends."""
    found = [f for f in overrides.fixes(c.state) if f.get("status") == "fixed"
             and f.get("code_changed") and f.get("done_seq", 0) > after]
    return found[-1] if found else None


def exhausted_loop(c, fields):
    """No round left for a correction: in Phase 6 before the PR is marked ready,
    the loop goes on to the ready-for-review gate, which names what is open;
    anywhere else the run stops."""
    if st.phase(c.state, 6)["status"] == "in-progress" and not marked_ready(c):
        c.p6["exhausted"] = {"seq": c.seq(), "open": fields.get("correct", [])}
        c.dirty = True
        return DONE_MARK
    return exhausted(c, "no round left for a correction",
                     "Tell the user each unmet condition by name and what was tried: "
                     + "; ".join(fields.get("correct", [])))


def questioned(tester):
    """Whether a tester repair answered a worker that questioned its checks
    (not the entry-point repair after a plan revision, nor a gate repair)."""
    scope = tester.get("sets", {}).get("scope", "")
    return tester.get("mode") == "repair" and scope not in (ENTRY_POINT_SCOPE, GATE_SCOPE)


def coder_correction(c, corrections_file, budget, rule):
    return spawn(c, "coder", "correction", {"corrections_file": corrections_file},
                 rule=rule, budget=budget)


def cleanup_spawn(c, scope, files, rule):
    return spawn(c, "cleanup", sets={"scope": scope}, rule=rule)


def verifier_spawn(c, what_changed):
    return spawn(c, "verifier", sets={"mode": "re-check", "what_changed": what_changed},
                 rule=f"re-check after {what_changed} (a check, no round)")


def blocked_step(c, coder):
    """The coder stopped steps: the planner decides; then the coder again."""
    planner = c.last("planner", after=coder["seq"], mode="blocked")
    if planner is None:
        listed = c.ad / "blocked" / f"coder-{coder['n']}.md"
        return spawn(c, "planner", "blocked", {"blocked": f"the steps listed in {listed}"},
                     rule="the coder returned BLOCKED: the planner decides why")
    if planner["next"] == "SPEC_IMPOSSIBLE":
        return stop([("The planner judged the spec impossible to meet as written. Tell "
                     f"the user its reasons (its reply, and {c.ad}/IMPLEMENTATION.md).")],
                    "the planner returned SPEC_IMPOSSIBLE",
                    retry={"aside": [job_of(planner)]},
                    no_signoff="the plan has no way to meet the spec; say how to change it")
    budget = c.spend(f"planner-{planner['n']}", "blocked step re-dispatched")
    if budget is None:
        return exhausted(c, "no round left to re-dispatch a blocked step",
                         f"The stopped steps are in {c.ad}/blocked/coder-{coder['n']}.md.")
    if planner["data"].get("entry_points_changed") == "yes" and \
            c.last("acceptance-tester", after=planner["seq"]) is None:
        return spawn(c, "acceptance-tester", "repair", {
            "scope": "ALL CONDITIONS whose checks call an entry point the revised plan "
                     "changed",
            "report": f"the plan was revised after a blocked step: see {c.ad}/"
                      "IMPLEMENTATION.md"},
            rule="the revised plan changed the checks' entry points", budget=budget)
    if c.last("coder", after=planner["seq"]) is None:
        return spawn(c, "coder", coder.get("mode") or "build", dict(coder.get("sets") or {}),
                     rule=f"the planner returned {planner['next']}: the coder goes again "
                          "(a round)", budget=budget)
    return None


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
    signing off keeps SPEC.md as written and acts on them as if they found
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
    return stop([(f"A worker found SPEC.md wrong {where}: a criterion that can't or "
                  "shouldn't be met as written, or one that is missing. Workers never "
                  "change the spec; the user decides. Tell the user each item:"),
                 *lines,
                 ("To change the spec, the user says how (the fixer edits SPEC.md, and the "
                  "plan and checks when they say so); signing off keeps SPEC.md as written. "
                  f"State and artifacts: {c.ad}")],
                "a worker found a criterion wrong",
                # A judge set aside consolidates again: its pass's re-votes too.
                retry={"aside": [job_of(r) for r in found],
                       **({"revote": review_pass} if review_pass is not None and
                          any(r["worker"] == "review-judge" for r in found) else {})},
                signoff={"rewrites": [[r["worker"], r["n"], r["next"], {"spec_problems": "0"}]
                                      for r in found],
                         "kept": kept},
                kind="spec-problem")


def disputed_stop(c, tester, who, where):
    """The acceptance tester ruled checks `who` questioned right as written
    (STANDS): the user decides. Signing off keeps the checks as written."""
    scope = tester.get("sets", {}).get("scope", "")
    ids = only_ids(scope)
    which = (f"the checks of condition(s) {', '.join(ids)}" if ids else
             f"the checks {where} questions")
    return stop([(f"The acceptance tester ruled {which} right as written (against "
                  f"SPEC.md), and {who} judges them wrong. Workers never settle it "
                  f"between themselves. Tell the user both sides: {where}, and the "
                  f"reason acceptance-tester #{tester['n']} gave above its result "
                  "block. Signing off keeps the checks as written.")],
                "the acceptance tester and the worker that questioned a check disagree",
                retry={"aside": [job_of(tester)]},
                signoff={"rewrite": [tester["worker"], tester["n"], "STANDS"],
                         "kept": ids or [where]},
                kind="disputed-check")


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
        out["spec_kept"] = ("the user kept SPEC.md as written for: " + "; ".join(spec)
                            + ". Judge these as worded; never report them as spec "
                              "problems again")
    if checks:
        out["checks_kept"] = ("the user kept these acceptance checks as written: "
                              + "; ".join(checks) + ". Judge them as written, never as "
                              "defective")
    return out


def recheck(c, start, what_changed):
    """The verifier after a change: a first pass when a fix at a stop changed
    SPEC.md or the plan since the loop began and no verifier ran since, since
    the contract changed."""
    # A fix that changed SPEC.md or the plan, or a retry at a spec-problem stop
    # (the user may have changed SPEC.md themselves).
    changed = [f.get("done_seq") for f in overrides.fixes(c.state) if f.get("spec_changed")]
    changed += [o["seq"] for o in c.state.get("overrides") or []
                if o["choice"] == "retry" and o["stop"].get("kind") == "spec-problem"]
    for done in changed:
        if done is not None and done >= start and \
                not any(e["worker"] == "verifier" and e.get("seq", 0) >= done
                        for e in c.state.get("briefs", [])):
            return verifier_first(c, "the spec changed: the verifier's first pass judges "
                                  "every condition again")
    return verifier_spawn(c, what_changed)


# ---------------------------------------------------------------- Phase 5

def verifier_first(c, rule):
    return spawn(c, "verifier", sets={"mode": "first pass"}, rule=rule)


def fold_spawn(c, conflicts):
    """The coder's file is where a sealed check goes, and the lines can't be
    merged mechanically (the coder made the same new test file, or rewrote the
    lines around an added test). The tester adds its tests to the coder's file:
    that file, as it is now, becomes the check's base."""
    c.would("make the coder's files the base of the checks that go into them",
            "the tester folds its tests into the coder's version of those files")
    wt = Path(c.state["worktree"])
    again = any(b["worker"] == "acceptance-tester" and b.get("mode") == "fold"
                for b in c.state.get("briefs", []))
    for rel in conflicts if not again else ():  # a re-spawn: the file may hold its tests
        current = sealed.read(wt / rel)
        sealed.write(sealed.base_path(c.ad, rel), sealed.lines(current or ""), current)
    return spawn(c, "acceptance-tester", "fold", {
        "files": ", ".join(conflicts),
        "scope": "ONLY the checks in the files the fold names; no condition is rewritten"},
                 rule="a sealed check can't be merged into the coder's file: the tester "
                      "adds its tests to that file (no round)")


def install_checks(c):
    """Install every sealed acceptance check at its path in the worktree, so the
    cleanup agent's quality gate runs on them before the verifier's first pass.

    Returns the paths where a check can't go in (lib/sealed.py): then nothing
    is installed, and the tester folds its tests into those files once; if one
    still can't go in, the verifier goes first, as before 4.1, to report it.
    Writes acceptance/INSTALLED (the paths, one per line), which tells the
    verifier the checks went in before cleanup."""
    marker = c.ad / "acceptance" / "INSTALLED"
    if marker.exists():  # installed already: a change since is an edit the audit records
        return []
    wt = c.state["worktree"]
    pairs = cmd_checks.sealed_pairs(c.ad, wt)
    _none, conflicts = cmd_checks.install_sealed(c.ad, wt, dry=True)
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
    conflicts = install_checks(c)
    if conflicts:
        folded = [r for r in c.recs("acceptance-tester", after=c.start(5), mode="fold")
                  if r.get("status") == "ok"]
        if not folded:
            return fold_spawn(c, conflicts)
        return verifier_first(c, "a sealed check still can't go in after the tester "
                              "folded it: the verifier's first pass goes first and "
                              "reports it")
    return cleanup_spawn(c, "phase5", None, "the code is built and the sealed checks are "
                         "installed: the cleanup agent simplifies it and runs the quality "
                         "gate before the verifier's first pass (no round)")


def phase5(c):
    start = c.start(5)
    result = loop_step(c, start, "phase5", first=lambda: phase5_first(c))
    if result is not DONE_MARK:
        return result
    stale = check_fresh(c, "--phase", "5")  # could not run: exit 2, never "stale"
    if stale:
        return stop([("A Phase 5 report is stale right after its own re-run: something "
                     "rewrites the code on every run. Tell the user the files below."),
                     stale], "check-fresh --phase 5 found a stale report",
                    retry={"aside": [job_of(r) for r in c.recs("cleanup", after=start)[-1:]]},
                    no_signoff="a stale report says nothing about the code that ships")
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
# S2. The open-the-PR gate (`gates.open_pr`, off by default) asks before the
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
                                    "the code changed outside the pipeline since S2: "
                                    "re-run the quality gate and the verifier first")
    if p6["passes"]:
        review = review_step(c, p6["passes"][-1])
        if review is not None:
            return review
    head = publish_step(c)
    if head is not None:
        return head
    if not reviewed_whole(c):
        return start_pass(c, "first", None, "the draft PR is open: the code review panel "
                          "reviews the whole change while CI runs")
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
    scope = "after-commit" if corr["after_commit"] else "outside"
    if corr.get("checks") and corr.get("file"):
        # The tester went first; the coder's part runs in the same round.
        tester = c.last("acceptance-tester", after=corr["seq"])
        settled = tester and (tester["next"] != "STANDS" or tester.get("signed_off"))
        if settled and c.last("coder", after=corr["seq"]) is None:
            return coder_correction(c, corr["file"], None, "the checks are settled; now "
                                    "the code's part of the correction (the same round)")
    result = loop_step(c, corr["seq"], scope, first=lambda: first_of(c, corr),
                       after_change="a Phase 6 correction")
    if result is not DONE_MARK:
        return result
    corr["closed"] = True
    c.dirty = True
    # Even when the budget ran out, the code changed: reviews are free, and the
    # gates need reports on the code as it is.
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
    if not corr["after_commit"]:
        return None  # before the first commit: the first pass reviews the whole change
    if unchanged(c):  # nothing to review or commit: the verified commit stands
        corr["unchanged"] = True
        mark_committed(c, "the correction changed nothing")
        return None
    if not reviewed_whole(c):
        # A fix at a stop before the first review pass: it is committed on top,
        # and the first pass then reviews the whole change, the fix with it.
        return None
    return start_pass(c, "after-commit", None, "the correction is verified: the panel "
                      "reviews it before it is committed on top")


def first_of(c, corr):
    if corr["entry"] == "outside":
        return spawn(c, "cleanup", sets={"scope": "outside"},
                     rule="the code changed outside the pipeline: the quality gate runs "
                          "again (no round)")
    if corr.get("checks"):  # acceptance checks first: the tester's repair mode
        checks = corr["checks"]
        rule = ("a finding questions an acceptance check: the tester decides first"
                + (", then the coder" if corr.get("file") else ""))
        return spawn(c, "acceptance-tester", "repair", dict(checks), rule=rule,
                     budget=corr.get("budget"))
    if not corr.get("file"):  # a fix at a stop: nothing for the coder
        return cleanup_spawn(c, "after-commit" if corr["after_commit"] else "phase5", None,
                             "the fixer changed the code at a stop: the cleanup agent runs "
                             "the quality gate (no round)")
    return coder_correction(c, corr["file"], corr.get("budget"), corr["rule"])


def closed_correction(c, spend_id):
    """The closed correction paid for as `spend_id`, or None."""
    return next((k for k in c.p6.get("corrections", [])
                 if k.get("spend_id") == spend_id and k.get("closed")
                 and not k.get("aside")), None)


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


def reviewed_whole(c):
    """Whether a first pass (the whole change) has started."""
    return any(p["scope"] == "first" for p in c.p6.get("passes") or [])


def marked_ready(c):
    return c.mark("pr-ready")


def start_correction(c, entry, file, spend_id, rule, checks=None, why="", since=None):
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
    c.p6["corrections"].append(corr)
    c.dirty = True
    return first_of(c, corr)


def check_fresh(c, *extra):
    code, out, err = run([sys.executable, str(SCRIPTS / "check-fresh.py"), c.wt,
                          str(c.ad), *extra], check=False)
    if code == 2:
        raise Fail(f"check-fresh.py could not run: {err.strip()}", CANNOT_RUN, "ERROR")
    return (err or out).strip() if code else ""


def start_pass(c, scope, files, rule, since=None):
    n = c.p6.get("review_pass", 0) + 1
    c.would(f"start code-review pass {n} ({scope}) and spawn the panel and the "
            "security reviewer", rule)
    c.p6["review_pass"] = n
    (c.ad / "review" / f"pass-{n}").mkdir(parents=True, exist_ok=True)
    cmd_checks.git_add_intent(c.wt)
    tree = cmd_review.print_tree(c.wt)
    if scope == "first":
        files = first_pass_files(c)
    effort = plan_effort(c)
    p = {"n": n, "scope": scope, "files": files or [], "tree": tree, "seq": c.seq(),
         "effort": effort}
    if since:
        p["since"] = since
    c.p6["passes"].append(p)
    st.add_note(c.state, f"code-review pass {n}: the reviewers run at effort {effort}")
    c.dirty = True
    jobs = [("code-reviewer", "review", reviewer_sets(c, p, slot)) for slot in SLOTS]
    return spawn_security(c, jobs, panel_leads(c), rule + "; the security review runs "
                          "alongside the panel, on the same tree", focus=focus_text(p))


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
    """Pass p: the panel and the security review (spawned together), the judge
    (with its check of the security findings), the re-votes, then one correction
    for whatever both left open, or a security run on leads it has not seen."""
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
        leads = last.get("leads") if secs else panel_leads(c)
        return spawn_security(c, jobs, leads or "none",
                              "a code reviewer or the security reviewer failed: it gets "
                              "one re-spawn" if secs or jobs else
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
                        no_signoff="no review was written to accept")
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
    ready = marked_ready(c)
    spent_out = bool(c.p6.get("exhausted")) and (
        ready is None or p["seq"] < ready.get("seq", 0))
    rows = open_must_fix(art.read(c.ad / "CODE_REVIEW.md"))
    security_open = bool(verify) and bool(confirmed_security(c))
    spec = spec_stop(c, [judge] + c.recs(SECURITY, after=p["seq"]),
                     f"in code-review pass {p['n']}", review_pass=p["n"])
    if spec is not None:
        return spec
    if rows or security_open:  # with no round left, they go to the ready gate
        if not spent_out:
            return review_correction(c, p, rows, sec if security_open else None)
        return None
    leads = unreviewed_leads(c, p)
    if leads:
        return spawn_security(c, [], leads, "the panel passed the security review leads "
                              "it had not seen: it checks them", focus=LEADS_FOCUS)
    return None


def review_carry(c, p, rows, sec):
    """What pass p's correction hands out: `files` for the coder (the pass's
    corrections.md when a must-fix row other than a check's is open, and the
    security corrections), and `checks` (scope, report) for the tester's repair
    mode."""
    checks = [r for r in rows if _category(r) == "acceptance-check"]
    spec = None
    if checks:  # a finding about a check goes to the tester, never the coder
        ids = ", ".join(r["ID"].strip() for r in checks)
        spec = {"scope": check_scope(c, checks),
                "report": (f"{c.ad}/CODE_REVIEW.md, must-fix finding(s) {ids}: each "
                           "one's `### <id>` block says what is wrong with the check")}
    files = []
    if len(checks) < len(rows):
        files.append(f"{c.ad}/review/pass-{p['n']}/corrections.md")
    if sec:
        files.append(f"{c.ad}/review/security-corrections.md")
    return {"files": files, "checks": spec}


def review_correction(c, p, rows, sec):
    """One correction for pass p's open must-fix rows and, when `sec` is given,
    the security review's confirmed must-fix findings: one round for both."""
    carry = review_carry(c, p, rows, sec)
    files, why = carry["files"], []
    spec = carry["checks"]
    if rows:
        why.append(f"pass {p['n']} left {len(rows)} must-fix finding(s) open")
    if sec:
        why.append("the security review found a confirmed must-fix finding")
    tag = f"pass-{p['n']}" if rows else f"security-{sec['n']}"
    return must_fix(c, " and ".join(files) or f"{c.ad}/CODE_REVIEW.md", tag,
                    " and ".join(why), checks=spec, coder=bool(files), security=bool(sec))


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
                    no_signoff="a lone finding's vote is still open")
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


def must_fix(c, file, tag, rule, checks=None, coder=True, security=False):
    spend_id = tag
    if overrides.signed_off(c.state, spend_id):
        return None  # the user signed the open findings off: the gate names them
    if closed_correction(c, spend_id):
        # It ran and changed nothing (a change starts a new pass): never again,
        # unless the user retries it.
        return stop([(f"The correction for {tag}'s open finding(s) changed nothing, so "
                     f"they are still open ({file}). Tell the user; the verified commit "
                     "is unchanged.")], "a correction changed nothing",
                    retry={"reopen": spend_id},
                    signoff=None if security else {"drop": spend_id},
                    no_signoff="a confirmed security finding is open" if security else None,
                    kind="open-findings")
    return start_correction(c, "review", file if coder else None, spend_id,
                            rule, checks=checks)


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


def check_scope(c, rows):
    """The tester's scope for findings about checks: their conditions, by the
    check files the findings' Locations name."""
    ids = check_ids(c, rows)
    if ids:
        return (f"ONLY conditions {', '.join(ids)}: the code review found their checks "
                "wrong")
    return "ONLY the conditions whose checks the code-review findings in the report name"


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
    and the merge."""
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
        return ci_watch(c, "the PR was marked ready: workflows that skip drafts run now")
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
                no_signoff="a stale report says nothing about the code that ships")


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
                    no_signoff="nothing was committed to go on with")
    # A commit made but not yet checked (`unverified_commit`) leaves a clean tree:
    # `commit` checks it without committing again, so it is offered as usual.
    if not c.p6.get("verified_sha") and not c.p6.get("unverified_commit"):
        add, remove = changed_paths(c.wt)
        if not add and not remove:
            return stop([("There is nothing to commit: the working tree holds no change "
                         "outside .auto-dev/. Tell the user; nothing was pushed.")],
                        "an empty change", retry={},
                        no_signoff="there is no change to ship")
    first = not c.p6.get("verified_sha")
    return action(f"commit: run `{c.cmd('commit', '--message', '<type>(<scope>): <summary>')}`"
                  f", with a Conventional Commits subject you write for the change ({FILL})",
                  "the build is verified: it is committed and pushed as a draft PR before "
                  "any review" if first else "a correction is verified and reviewed: it is "
                  "committed on top", AFTER=[c.cmd("next")])


def body_step(c, sha):
    from . import cmd_pr  # imported here: cmd_pr imports this module's helpers
    body = c.p6.get("body") or {}
    # A description written before 4.21.1 left some of what it copies outside
    # a quoted region (before 4.0.2, it had none), so the lint refuses an ID
    # it copied: write it again, unless a PR already carries it.
    old = "quoted" not in c.p6 or "verbatim" not in c.p6
    reviewed, ready = reviewed_pass(c), ready_answered(c)
    if body.get("sha") != sha or body.get("reviewed") != reviewed or \
            bool(body.get("ready")) != ready or triage_seq(c) > body.get("seq", 0) or \
            (old and not c.p6.get("pr")):
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
                        no_signoff="the PR description must pass its checks")
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
                  "replace every `<!-- WRITE: ... -->` line (references/S3-ship.md, "
                  "_The PR body_), in plain words for a "
                  "developer who has never heard of auto-dev; change nothing else. Then "
                  "run AFTER" + (". `pr publish` refused the last one: " + "; ".join(refused)
                                 if refused else ""), rule, AFTER=[c.cmd("pr", "publish")])


def ci_watch(c, rule):
    return action(f"watch CI: run `{c.cmd('ci-watch')}` (it waits up to 9 minutes), "
                  "then run AFTER whatever it exits: `next` asks for another watch "
                  "while CI is still pending", rule, AFTER=[c.cmd("next")])


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
                        "a CI correction changed nothing",
                        retry={"reopen": f"ci-{triage['n']}"},
                        no_signoff="never merge over red CI")
        return start_correction(c, "ci", triage_file(c, triage), f"ci-{triage['n']}",
                                "CI is red because of the code (a round)",
                                why=f"Red checks: {red}.")
    if kind == "SECRET":
        return stop([("CI failed on a secret or credential problem. Tell the user the "
                     f"red checks ({red}) and what the triager said "
                     f"({triage_file(c, triage)}). Once the secret is fixed and CI re-run, "
                     "`auto-dev continue` watches it again.")],
                    "the triager returned SECRET", retry={"lift": True},
                    no_signoff="never merge over red CI")
    # INFRA, FLAKY or UNKNOWN: not the coder's to fix. Stop here, before Jira
    # moves on a red build; a resume watches CI again.
    return stop([(f"CI is red, and the triager classed it {kind}: not something the code "
                 f"can fix. Tell the user the red checks ({red}) and what the triager "
                 f"found ({triage_file(c, triage)}). The run stops here; once CI is fixed "
                 "or re-run, `auto-dev continue` watches it again.")],
                f"the triager returned {kind}", retry={"lift": True},
                no_signoff="never merge over red CI")


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
                        "merge-pr did not merge", retry={"clear": ["merge_attempt"]},
                        no_signoff="the PR is not merged")
        ci = p6.get("ci") or {}
        if ci.get("status") == "red":
            return stop(["CI is red on the PR; never merge over it. Tell the user each "
                         "red check: " + "; ".join(ci.get("failing", []))],
                        "red CI at the main gate", retry={"lift": True},
                        no_signoff="never merge over red CI")
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
    if c.state["repo"].get("adopted"):  # the user made the worktree: never remove it
        c.finish(6, f"merged PR #{p6.get('pr')}")
        return {"code": NEXT_COMPLETE, "ACTION": "the run is complete; nothing more to do",
                "RULE": "the run used the user's own worktree, which stays"}
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
                  "main gate again:"), stale], "the PR head moved", retry={},
                no_signoff="the pipeline never ships commits it did not check")


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

