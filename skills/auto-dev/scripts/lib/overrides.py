"""autodev.py override — the user's way past a step that stopped the run.

Usage:
    autodev.py override fix --text "<the user's instruction>"
    autodev.py override approve
    autodev.py override retry [--text "<what the user changed>"]
    autodev.py override signoff --text "<why the user accepts it>"
    autodev.py override talk
    autodev.py override leave

A stop that can be overridden (a red quality gate, an impossible spec, a
check the tester and the verifier disagree on, a worker that failed twice, a
commit or merge that failed, …) prints a QUESTION with its REPORT, and `next`
saves which step stopped in state.json. Each command here answers that
question; it is refused when `next` did not just stop on such a step.

    fix      The user said how to fix it. `next` spawns the fixer with their
             words, the instruction it may act on and nothing more. Once it
             returns FIXED, the step that stopped runs again (no round), and
             whatever depends on what the fixer changed runs again too. A fixer
             that needs more than the instruction allows returns
             NEEDS_CONSENT: it changes nothing, and the stop's question then
             offers its proposal.
    approve  The user approved the fixer's proposal: the fixer runs again,
             told to do what it proposed.
    retry    The user fixed the cause themselves: the step that stopped runs
             again (no round).
    signoff  The user accepts the result and the run goes on as if the step
             had passed. Only where the stop offers it: never on a red CI run,
             a security criterion, or a mutation that may have left changes. It
             is named in WORK_LOG.md, the PR gate's summary and the PR body.
    talk     Records nothing: talk the stop through with the user, then run
             `next`, which asks the question again.
    leave    The run stays stopped: `next` reports the stop without the
             question for the rest of this session; a new session asks again.

Exit codes:
    0  recorded (talk: nothing to record)
    1  refused: `next` did not just stop on a step that can be overridden, a
       sign-off the stop does not offer, fix or signoff with no --text, or
       approve with no proposal to approve
    2  could not run (no state.json, unreadable)
"""

import hashlib
import shutil
from pathlib import Path

from . import state as st
from .output import FAILED, Fail, emit

CHOICES = ("fix", "approve", "retry", "signoff", "talk", "leave")
# The artifacts a fixer may change with the user's consent, besides repo
# files: compared before and after it runs, and put back when it changes
# nothing on purpose (NEEDS_CONSENT, CANNOT_FIX) or fails.
WATCHED = ("SPEC.md", "IMPLEMENTATION.md", "acceptance")
FIX_DIR = "override"


def add_arguments(parser, name=None):
    parser.add_argument("--dir", default=".auto-dev", help="the run's .auto-dev/")
    parser.add_argument("choice", choices=CHOICES)
    parser.add_argument("--text", default="",
                        help="fix: the user's instruction; signoff: why they accept "
                             "it; retry: what they changed (optional)")


def load(args):
    try:
        return st.load(args.dir)
    except st.StateError as exc:
        raise Fail(str(exc), 2, "ERROR") from None


def fixes(state):
    return [o for o in state.get("overrides") or [] if o["choice"] == "fix"]


def latest(state):
    found = state.get("overrides") or []
    return found[-1] if found else None


def proposed(state):
    """The last fix, when it ended NEEDS_CONSENT on the stop the run is at now."""
    stop = state.get("stop")
    found = fixes(state)
    if not stop or not found or found[-1].get("status") != "proposed":
        return None
    return found[-1] if found[-1]["stop"].get("rule") == stop.get("rule") else None


def main(args):
    state = load(args)
    stop = state.get("stop")
    if not stop:
        raise Fail("`next` did not just stop on a step that can be overridden: run "
                   "`next` and answer the question its stop prints", FAILED, "REFUSED")
    choice, text = args.choice, args.text.strip()
    if choice == "talk":
        emit(args.json, "TALK", "nothing recorded: talk the stop through with the user "
             "(send a lookup for any fact about the code), then run `next`, which asks "
             "the question again")
        return 0
    if choice in ("fix", "signoff") and not text:
        what = "the user's instruction" if choice == "fix" else "why the user accepts it"
        raise Fail(f"override {choice} needs --text: {what}", FAILED, "REFUSED")
    if choice == "signoff" and not stop.get("signoff"):
        why = stop.get("no_signoff") or "it has no pass to accept"
        raise Fail(f"this stop can't be signed off: {why}", FAILED, "REFUSED")
    if choice == "approve":
        fix = proposed(state)
        if fix is None:
            raise Fail("no fixer proposal to approve at this stop", FAILED, "REFUSED")
        text = (f"{fix['text']}\nThe user approved the proposal in your report "
                f"{fix['report']} (its Proposal section): do what it proposes, and "
                "nothing more.")
        if args.text.strip():
            text += f"\nThe user added: {args.text.strip()}"
    seq = st.seq(state)
    entry = {"k": len(state.get("overrides") or []) + 1, "choice": choice, "text": text,
             "stop": stop, "seq": seq, "at": st.now()}
    for earlier in fixes(state):  # a new answer replaces a fix not yet settled
        if earlier.get("status") == "open":
            earlier["status"] = "dropped"
    label = stop.get("rule") or "the stop"
    if choice in ("fix", "approve"):
        entry["choice"], entry["status"] = "fix", "open"
        if choice == "approve":
            entry["approved"] = True
        st.add_note(state, f"override at the stop ({label}): the user asked for a fix: "
                    f"{text.splitlines()[0]}")
        after = "run `next`: it spawns the fixer with the user's instruction"
    elif choice == "retry":
        apply_retry(state, stop.get("retry") or {}, seq)
        st.add_note(state, f"override at the stop ({label}): the user fixed the cause "
                    "and asked to run the step again" + (f": {text}" if text else ""))
        after = "run `next`: it runs the step that stopped again"
    elif choice == "signoff":
        apply_signoff(state, stop["signoff"], seq)
        st.add_note(state, f"override at the stop ({label}): the user signed off: {text}")
        after = "run `next`: the run goes on as if the step had passed"
    else:  # leave
        st.add_note(state, f"override at the stop ({label}): the user left the run stopped")
        after = "stop here and tell the user the worktree stays; a new session asks again"
    state.setdefault("overrides", []).append(entry)
    if choice != "leave":
        state.pop("stop", None)
    st.save(args.dir, state)
    emit(args.json, "OVERRIDE", f"{entry['choice']}: {label}", after=after)
    return 0


# ---------------------------------------------------------------- applying

def log_entry(state, job):
    worker, n = job
    return next((e for e in state.get("log") or []
                 if e["worker"] == worker and e["n"] == n), None)


def set_aside(state, jobs, seq):
    """Hide recorded results from `next`, which then takes their step again.
    They stay in the log (recorded, never recorded twice)."""
    for job in jobs or []:
        entry = log_entry(state, job)
        if entry is not None:
            entry["aside"] = seq


def apply_retry(state, retry, seq):
    set_aside(state, retry.get("aside"), seq)
    p6 = state.setdefault("phase6", {})
    for key in retry.get("clear") or []:
        p6.pop(key, None)
    if retry.get("reopen"):
        for corr in p6.get("corrections") or []:
            if corr.get("spend_id") == retry["reopen"] and corr.get("closed"):
                corr["aside"] = seq
    if retry.get("lift"):
        lift(state, seq)
    if retry.get("oversized"):
        reopen_define(state)


def lift(state, seq):
    """What `auto-dev continue` lifts, now: a worker that failed twice, never
    returned, or a result stale twice gets new tries."""
    for brief in state.get("briefs") or []:
        brief.pop("emitted", None)
    state["lifted_seq"] = seq


def reopen_define(state):
    """An OVERSIZED run goes back to Phase 2: Define runs again (retry), or the
    run goes on as FITS (sign-off, or a fix that narrowed SPEC.md)."""
    st.set_phase(state, 2, "in-progress", "")
    for number in (3, 4, 5, 6):
        st.set_phase(state, number, "pending", "")
    state["size"] = None


def apply_signoff(state, signoff, seq):
    set_aside(state, signoff.get("aside"), seq)
    rewrite = signoff.get("rewrite")
    if rewrite:
        entry = log_entry(state, rewrite[:2])
        if entry is not None:
            entry["signed_off"] = {"from": entry.get("next"), "seq": seq}
            entry["next"] = rewrite[2]
            entry["data"] = {**entry.get("data", {}), "next": rewrite[2],
                             **(rewrite[3] if len(rewrite) > 3 else {})}
    if signoff.get("drop"):
        state.setdefault("phase6", {}).setdefault("signed_off", []).append(signoff["drop"])
    if signoff.get("fits"):
        reopen_define(state)
        state["size"] = "FITS"
        if state.get("high_risk"):
            state["settings"]["post_plan_gate"] = True


def signed_off(state, spend_id):
    return spend_id in (state.get("phase6") or {}).get("signed_off", [])


def signed_reports(state):
    """The quality-gate reports (lint/<report>) the user signed off failing:
    while only these fail, the gate counts as green for the rest of the run."""
    return {r for o in state.get("overrides") or []
            if o["choice"] == "signoff" and o["stop"].get("kind") == "red-gate"
            for r in (o["stop"].get("signoff") or {}).get("reports") or []}


# ---------------------------------------------------------------- the fixer's watch

def digests(ad):
    """{path under the artifact dir: sha256} of the artifacts a fix may change."""
    ad = Path(ad)
    out = {}
    for name in WATCHED:
        path = ad / name
        files = sorted(p for p in path.rglob("*") if p.is_file()) if path.is_dir() else (
            [path] if path.is_file() else [])
        for f in files:
            if f.name.endswith(".installed"):
                continue  # the pipeline's own snapshot of a shared check file
            out[f.relative_to(ad).as_posix()] = hashlib.sha256(f.read_bytes()).hexdigest()
    return out


def backup_dir(ad, n):
    return Path(ad) / FIX_DIR / f"fixer-{n}.before"


def save_artifacts(ad, n):
    """Copy the watched artifacts aside before fixer #n runs; their digests."""
    ad = Path(ad)
    folder = backup_dir(ad, n)
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    for rel in digests(ad):
        target = folder / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ad / rel, target)
    return digests(ad)


def changed_artifacts(ad, before):
    now = digests(ad)
    return sorted(p for p in set(before) | set(now) if before.get(p) != now.get(p))


def put_back_artifacts(ad, n, paths):
    """Restore each changed artifact from the copy taken before fixer #n."""
    ad, folder = Path(ad), backup_dir(ad, n)
    for rel in paths:
        saved, target = folder / rel, Path(ad) / rel
        if saved.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(saved, target)
        elif target.exists():
            target.unlink()


# ---------------------------------------------------------------- reports

def summary_lines(state):
    """One line per sign-off and per fix made at a stop, for the PR gate's
    summary, the PR body and the final report."""
    out = []
    for o in state.get("overrides") or []:
        what = o["stop"].get("rule") or "a stop"
        first = (o.get("text") or "").splitlines()[0] if o.get("text") else ""
        if o["choice"] == "signoff":
            out.append(f"Signed off by the user at a stop ({what}): {first}")
        elif o["choice"] == "fix" and o.get("status") == "fixed":
            files = o.get("changed") or []
            out.append(f"Fixed at the user's instruction at a stop ({what}): {first}"
                       + (f" ({len(files)} file(s): {', '.join(files[:6])}"
                          f"{', …' if len(files) > 6 else ''})" if files else
                          " (no file changed)"))
        elif o["choice"] == "retry":
            out.append(f"Run again after the user fixed the cause at a stop ({what})"
                       + (f": {first}" if first else ""))
    return out
