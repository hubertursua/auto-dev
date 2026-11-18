"""The run's metrics: `.auto-dev/metrics.json`, and a copy outside the worktree.

`next` writes both whenever it completes a run's step (exit 3) or stops it
(exit 4), so the numbers the pipeline's guesses are tuned against (the
checkpoint's event count, the risk re-check's size thresholds, the iteration
budget) can be read once runs end, even after the worktree is removed.

Most counts are derived from state.json and the review files when the file is
written. What state would forget is kept as it happens, in optional keys:
`stops` and `stop_shown` (note_stop / clear_stop, called by `next`),
`refusals` (cmd_work.record_job), a brief's `resent` (cmd_next.pending_briefs)
and the risk re-check's `files` / `lines`.

The file holds counts, worker names, round ids and texts, and stop rule texts
only: no task text, path or code.
"""

import json
import os
import re
from pathlib import Path

from . import artifacts as art
from . import judgment
from . import state as st

FILE = "metrics.json"
FORMAT = 1
UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


def metrics_dir():
    """The per-user folder the copies go to: $AUTO_DEV_METRICS_DIR, else
    $XDG_CONFIG_HOME/auto-dev/metrics, else ~/.config/auto-dev/metrics (the
    saved profiles' order, profile-path.py)."""
    explicit = os.environ.get("AUTO_DEV_METRICS_DIR")
    if explicit:
        return Path(explicit).expanduser()
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return base / "auto-dev" / "metrics"


def safe(segment):
    """`segment` as one path segment: each character other than a letter, a
    digit, `.`, `_` or `-` becomes `-`, and no leading dot, so it can't climb
    out of the folder."""
    return UNSAFE.sub("-", str(segment or "")).lstrip(".") or "run"


def saved_path(state):
    """Where the run's metrics copy goes: <metrics-dir>/<repo folder>/<branch>.json."""
    return metrics_dir() / safe(state["repo"].get("name")) / (safe(state.get("branch"))
                                                              + ".json")


def tally(items, key):
    counts = {}
    for item in items:
        name = key(item)
        counts[name] = counts.get(name, 0) + 1
    return counts


def build(state, ad):
    """The metrics of the run as `state` and the review files in `ad` stand.
    Read-only; every key is always there."""
    ad = Path(ad)
    first = st.first_open_phase(state)
    spawns = {}
    for b in state.get("briefs") or []:
        spawns[b["worker"]] = spawns.get(b["worker"], 0) + 1 + int(b.get("resent", 0) or 0)
    budget = state.get("budget") or {}
    spends = budget.get("spends") or []
    stops = state.get("stops") or []
    refusals = state.get("refusals") or []
    return {
        "metrics": FORMAT,
        "written": st.now(),
        "run": {"state": st.run_state(state), "phase": first[0] if first else None,
                "size": state.get("size"), "high_risk": state.get("high_risk")},
        "events": state.get("events", 0),
        "spawns": {"total": sum(spawns.values()), "by_worker": spawns},
        "rounds": {"total": budget.get("total"), "spent": len(spends),
                   "remaining": budget.get("remaining"),
                   "raised": sum(int(r.get("by", 0) or 0)
                                 for r in budget.get("raises") or []),
                   "spends": [{"id": s.get("id"), "what": s.get("what")} for s in spends]},
        "stops": {"total": len(stops),
                  "by_number": tally(stops, lambda s: "none" if s.get("number") is None
                                     else str(s["number"])),
                  "list": [{"number": s.get("number"), "rule": s.get("rule"),
                            "phase": s.get("phase")} for s in stops]},
        "refused": {"total": len(refusals),
                    "by_worker": tally(refusals, lambda r: r.get("worker")),
                    "by_token": tally(refusals, lambda r: r.get("token"))},
        "code_review": code_review(state, ad),
        "security_review": security_review(ad),
        "diff": diff(state),
    }


def code_review(state, ad):
    """CODE_REVIEW.md's findings, kept (must-fix, advisory) and dropped (noise,
    pre-existing); None with no review, or one that can't be read."""
    path = ad / "CODE_REVIEW.md"
    if not path.is_file():
        return None
    try:
        text = art.read(path)
        earlier = judgment.earlier_report(text) or {}
        pending = judgment.table_rows(text, "Pending re-vote")[1]
    except (art.ArtifactError, judgment.JudgmentError):
        return None
    must, advisory = len(earlier.get("must_fix") or []), len(earlier.get("advisory") or [])
    noise, dropped = len(earlier.get("noise") or []), int(earlier.get("dropped") or 0)
    return {"passes": len((state.get("phase6") or {}).get("passes") or []),
            "must_fix": must, "advisory": advisory, "pending": len(pending),
            "noise": noise, "pre_existing": dropped,
            "kept": must + advisory, "dropped": noise + dropped}


def security_review(ad):
    """SECURITY_REVIEW.md's findings: kept (not refuted) and dropped (refuted);
    None with no review, or one that can't be read."""
    path = ad / "SECURITY_REVIEW.md"
    if not path.is_file():
        return None
    try:
        text = art.read(path)
        _, rows = art.first_table(art.find_section(text, "Findings") or "",
                                  ("ID", "Verdict", "Status"), "SECURITY_REVIEW.md")
    except art.ArtifactError:
        return None
    rows = [r for r in rows if r.get("ID", "").strip()]
    refuted = sum(1 for r in rows if r.get("Verified", "").strip().lower() == "refuted")
    return {"findings": len(rows), "refuted": refuted, "kept": len(rows) - refuted,
            "dropped": refuted}


def diff(state):
    """The build's diff size from the post-build risk re-check, or None before it."""
    check = state.get("risk_recheck")
    if not check:
        return None
    return {"files": check.get("files"), "lines": check.get("lines"),
            "high": bool(check.get("high"))}


def write(artifact_dir):
    """Write metrics.json into the run's artifact dir, and the same text to
    saved_path(). Raises nothing: returns one line for each file it could not
    write (an empty list once both are written)."""
    try:
        state = st.load(artifact_dir)
    except st.StateError as exc:
        return [f"metrics.json not written: {exc}"]
    text = json.dumps(build(state, Path(state["artifact_dir"])), indent=2,
                      sort_keys=True) + "\n"
    errors = []
    try:
        st._atomic_write(Path(artifact_dir) / FILE, text)
    except OSError as exc:
        errors.append(f"metrics.json not written: {exc}")
    copy = saved_path(state)
    try:
        copy.parent.mkdir(parents=True, exist_ok=True)
        st._atomic_write(copy, text)
    except OSError as exc:
        errors.append(f"metrics copy not written to {copy}: {exc}")
    return errors


def note_stop(state, tally_, rule, phase):
    """Count the stop `next` is printing, once: `tally_` is the {number, count}
    the stop carried. A stop that isn't counted (a hold), or the one counted
    last and not cleared since (reported again), changes nothing. Whether state
    changed."""
    if not tally_.get("count", True) or state.get("stop_shown") == rule:
        return False
    state.setdefault("stops", []).append({
        "number": tally_.get("number"), "rule": rule, "phase": phase,
        "at": st.now(), "seq": st.seq(state)})
    state["stop_shown"] = rule
    return True


def clear_stop(state):
    """Something other than a stop ran: the next stop counts again. Whether
    state changed."""
    return state.pop("stop_shown", None) is not None
