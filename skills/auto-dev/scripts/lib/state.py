"""The run's state: `.auto-dev/state.json`, written only by autodev.py.

`WORK_LOG.md` is generated from it after every write, for people to read.
Nothing parses the generated file except `resume-point.py`, which reads the
same template the 3.x ledger used.
"""

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = 4
STATE_FILE = "state.json"
LEDGER = "WORK_LOG.md"

PHASES = ((1, "Setup"), (2, "Define"), (3, "Plan"), (4, "Build"), (5, "Verify"),
          (6, "Ship"))
PHASE_NAMES = dict(PHASES)
# Which session holds each phase.
SESSIONS = {1: "S1", 2: "S1", 3: "S1", 4: "S2", 5: "S2", 6: "S3"}
SESSION_NAMES = {"S1": "S1 — Plan", "S2": "S2 — Build", "S3": "S3 — Ship"}

# `held` pauses the run where it is (resuming re-fires the gate that held it, or
# for Phase 1 a failed setup, which `init --continue` runs again);
# `stopped` ends it (nothing resumes on its own).
STATUSES = ("pending", "in-progress", "done", "n/a", "held", "stopped")
COMPLETE = ("done", "n/a")
# How each status reads in the generated ledger, which keeps the 3.x words.
LEDGER_STATUS = {"held": "blocked", "stopped": "blocked"}


class StateError(Exception):
    """state.json is missing, unreadable, or not a 4.x state."""


def now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def new_state(task, repo, worktree, branch, settings, budget_total):
    """A fresh state for a run whose worktree was just created."""
    return {
        "schema": SCHEMA,
        "created": now(),
        "task": task,          # text, ticket, ticket_url, ask
        "repo": repo,          # name, main_checkout, base, staging, prefix
        "worktree": str(worktree),
        "branch": branch,
        "artifact_dir": str(Path(worktree) / ".auto-dev"),
        "size": None,          # FITS | OVERSIZED, from the Define agent
        "high_risk": None,     # True | False, from the Define agent
        "phases": {str(n): {"status": "pending", "notes": ""} for n, _ in PHASES},
        "gates": [],           # {gate, choice, reason, at}
        "notes": [],           # decisions and assumptions, {text, at}
        "budget": {"total": budget_total, "remaining": budget_total, "spends": []},
        "settings": settings,  # ci, ci_timeout, mutation_max, post_plan_gate, ...
        "init": {"setup": "pending"},
        "phase6": {},
        "events": 0,
    }


def path_of(artifact_dir):
    return Path(artifact_dir) / STATE_FILE


def load(artifact_dir):
    path = path_of(artifact_dir)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise StateError(f"no {path} — not a 4.x auto-dev run") from None
    except OSError as exc:
        raise StateError(f"cannot read {path}: {exc}") from None
    try:
        state = json.loads(text)
    except ValueError as exc:
        raise StateError(f"{path} is not valid JSON: {exc}") from None
    if not isinstance(state, dict):
        raise StateError(f"{path} holds a JSON {type(state).__name__}, not a "
                         "4.x state object")
    if state.get("schema") != SCHEMA:
        raise StateError(f"{path} has schema {state.get('schema')!r}, "
                         f"expected {SCHEMA}")
    return state


def save(artifact_dir, state, count_event=True):
    """Write state.json atomically, then regenerate WORK_LOG.md from it."""
    if count_event:
        state["events"] = state.get("events", 0) + 1
    state["updated"] = now()
    directory = Path(artifact_dir)
    directory.mkdir(parents=True, exist_ok=True)
    _atomic_write(directory / STATE_FILE,
                  json.dumps(state, indent=2, sort_keys=True) + "\n")
    _atomic_write(directory / LEDGER, render_ledger(state))


def _atomic_write(path, text):
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def phase(state, number):
    return state["phases"][str(number)]


def set_phase(state, number, status, notes=None):
    if status not in STATUSES:
        raise StateError(f"status {status!r} is not one of {', '.join(STATUSES)}")
    entry = phase(state, number)
    entry["status"] = status
    if notes is not None:
        entry["notes"] = notes


def first_open_phase(state):
    """The first phase not done or n/a, as (number, status), or None."""
    for number, _ in PHASES:
        status = phase(state, number)["status"]
        if status not in COMPLETE:
            return number, status
    return None


def run_state(state):
    """`open`, `held`, `stopped` or `finished` for the run as a whole."""
    statuses = [phase(state, n)["status"] for n, _ in PHASES]
    if "stopped" in statuses:
        return "stopped"
    if all(s in COMPLETE for s in statuses):
        return "finished"
    if "held" in statuses:
        return "held"
    return "open"


def add_note(state, text):
    state["notes"].append({"text": text, "at": now()})


def ticket_line(task):
    head = task.get("ticket") or "none"
    if task.get("ticket_url"):
        head = f"{head} {task['ticket_url']}"
    ask = task.get("ask") or task.get("text", "")
    return f"{head} — {ask}"


def render_ledger(state):
    """The human-readable ledger, in the 3.x WORK_LOG.md template's shape."""
    task, repo, budget = state["task"], state["repo"], state["budget"]
    size = state.get("size") or "—"
    risk = {True: "yes", False: "no"}.get(state.get("high_risk"), "—")
    lines = [
        "# Work Log",
        "",
        ("<!-- Generated from state.json by autodev.py. Do not edit: changes "
         "here are overwritten. -->"),
        "",
        f"- **Task:** {task.get('text', '')}",
        f"- **Ticket:** {ticket_line(task)}",
        (f"- **Repo:** {repo.get('name', '')}   **Base:** {repo.get('base', '')}   "
         f"**Stack:** {state['settings'].get('stack') or '—'}"),
        f"- **Worktree:** {state['worktree']}   **Branch:** {state['branch']}",
        f"- **Size:** {size}   **High risk:** {risk}",
        (f"- **Iteration budget:** {budget['total']} total revise rounds "
         f"({budget['remaining']} remaining)"),
        "",
        "## Phase status",
        "| # | Phase | Status | Notes |",
        "|---|-------|--------|-------|",
    ]
    for number, name in PHASES:
        entry = phase(state, number)
        status = LEDGER_STATUS.get(entry["status"], entry["status"])
        notes = entry.get("notes", "").replace("|", "/").replace("\n", " ")
        if entry["status"] in LEDGER_STATUS:
            notes = f"{entry['status']}: {notes}" if notes else entry["status"]
        lines.append(f"| {number} | {name} | {status} | {notes} |")
    lines += ["", "## Decisions & assumptions"]
    for gate in state["gates"]:
        reason = f" — {gate['reason']}" if gate.get("reason") else ""
        lines.append(f"- {gate['at']} gate `{gate['gate']}`: {gate['choice']}{reason}")
    for spend in budget["spends"]:
        lines.append(f"- {spend['at']} round spent (consumer #{spend['consumer']}, "
                     f"`{spend['id']}`): {spend.get('what') or 'correction'}")
    for note in state["notes"]:
        lines.append(f"- {note['at']} {note['text']}")
    return "\n".join(lines) + "\n"
