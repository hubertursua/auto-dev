"""autodev.py gate-check — change how one quality-gate check runs, for a stop
the user answered or a fix the user asked for.

Usage:
    autodev.py gate-check <check> [--command "<command>"]
                          [--files "<command with <files>>" | --no-files]
                          [--profile <saved profile.yml>]

<check> is the check's number in profile.md's Quality gate table (1 is the
first), its report (`TEST.md`, or `TEST`), or its kind when only one check has
that kind. The command changes the run's own copy of the check, in
state.json's settings, and profile.md's Quality gate table:

--command "<command>"
    What the check runs, whole (for example an env wrapper the repo needs
    in front of the old command).
--files "<command>"
    The check scoped to some files, with `<files>` where the paths go.
--no-files
    Drop the scoped form: the check then only runs whole.

It runs at a stop, on the user's word (`next` stopped and asks how to go on;
then answer the stop, usually "I fixed it myself", so the step that stopped
runs again), or from the fixer while the fix the user asked for is open (its
report names `.auto-dev/state.json`, and the change is put back unless it
returns FIXED).

--profile <saved profile.yml>
    At a stop only, when the user said yes to saving it for later runs: the
    same change in the saved profile (`profile-path.py` names it). Each
    changed value is replaced in place when the file has it exactly once, and
    the result must pass `validate-config.py --profile` and read back with
    the new values; otherwise the file is left as it was and `profile:` says
    what to change by hand. A repo's committed `.auto-dev.yml` that sets
    `gate` wins over the saved profile.

Prints `GATE-CHECK` with a `changed:` line for each value (from → to), a
`changed: .auto-dev/state.json` line for the fixer's report, and with
--profile a `profile:` line. The change is noted in WORK_LOG.md and listed in
the PR body.

Exit codes:
    0  GATE-CHECK: changed (a profile left as it was still exits 0)
    1  refused: no stop and no open fix, an unknown or ambiguous check,
       nothing to change, a --files form with no <files>, a value on more
       than one line, or --profile from the fixer
    2  could not run (no state.json, unreadable)
"""

import json
import subprocess
import sys
from pathlib import Path

from . import state as st
from .cmd_amend import open_fix
from .cmd_init import SETUP_HEADING, TEST_NOTES, setup_and_gate_lines
from .output import CANNOT_RUN, FAILED, Fail, emit

SCRIPTS = Path(__file__).resolve().parent.parent
FILES = "<files>"


def add_arguments(parser, name=None):
    parser.add_argument("--dir", default=".auto-dev", help="the run's .auto-dev/")
    parser.add_argument("check", help="the check's number, report or kind")
    parser.add_argument("--command", dest="new_command", help="the command the check runs, whole")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--files", help="the check scoped to some files, with <files>")
    group.add_argument("--no-files", action="store_true", help="drop the scoped form")
    parser.add_argument("--profile", help="at a stop: the saved profile to change too")


def refuse(message):
    raise Fail(message, FAILED, "REFUSED")


def find_check(gate, key):
    """The index of the check `key` names: number, report or a unique kind."""
    key = key.strip()
    if key.isdigit():
        if 1 <= int(key) <= len(gate):
            return int(key) - 1
        refuse(f"there is no check {key}: the gate has {len(gate)}")
    want = key.lower().removesuffix(".md")
    by_report = [i for i, c in enumerate(gate)
                 if str(c.get("report", "")).lower().removesuffix(".md") == want]
    if by_report:
        return by_report[0]
    by_kind = [i for i, c in enumerate(gate) if str(c.get("kind", "")).lower() == want]
    if len(by_kind) == 1:
        return by_kind[0]
    names = ", ".join(f"{i} {c.get('report')}" for i, c in enumerate(gate, 1))
    refuse(f"{key!r} names " + ("more than one check" if by_kind else "no check")
           + f": give its number or report ({names})")


def wanted(args, check):
    """{field: new value or None (drop)} for each field that changes."""
    out = {}
    for field, value in (("command", args.new_command), ("files", args.files)):
        if value is None:
            continue
        value = value.strip()
        if not value or "\n" in value:
            refuse(f"--{field} must be one non-empty line")
        if field == "files" and FILES not in value:
            refuse(f"--files must have {FILES} where the paths go")
        if value != check.get(field):
            out[field] = value
    if args.no_files and check.get("files"):
        out["files"] = None
    if not out:
        refuse("nothing to change: the check already runs that way")
    return out


def refresh_profile_md(ad, settings):
    path = Path(ad) / "profile.md"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    start, end = text.find(SETUP_HEADING), text.find("\n" + TEST_NOTES)
    if start != -1 and end > start:
        path.write_text(text[:start] + "\n".join(setup_and_gate_lines(settings)) + "\n"
                        + text[end:], encoding="utf-8")


def scalar(text, at, new):
    """`new` written in the quoting of the YAML scalar that starts at `at`."""
    before = text[at - 1] if at else ""
    if before == '"':
        return json.dumps(new)[1:-1]
    if before == "'":
        return new.replace("'", "''")
    return json.dumps(new)


def save_profile(ad, path, check, old, changes):
    """Make `changes` to `path` in place; None when done, or why not."""
    path = Path(path).expanduser()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return f"could not read it ({exc})"
    new_text = text
    for field, value in changes.items():
        before = old.get(field)
        if value is None or before is None:
            return f"it has no `{field}` to replace in place"
        if new_text.count(before) != 1:
            return f"it does not have `{before}` exactly once"
        at = new_text.index(before)
        new_text = new_text[:at] + scalar(new_text, at, value) + new_text[at + len(before):]
    tmp = Path(ad) / "tmp" / "gate-check-profile.yml"
    tmp.parent.mkdir(exist_ok=True)
    tmp.write_text(new_text, encoding="utf-8")
    try:
        r = subprocess.run([sys.executable, str(SCRIPTS / "validate-config.py"),
                            "--profile", str(tmp)], capture_output=True, text=True,
                           check=False)
        if r.returncode != 0:
            return "the changed file did not pass validate-config.py"
        try:
            import yaml
            got = yaml.safe_load(new_text) or {}
        except Exception:  # any failure means "not checked"
            return "could not read the changed file back"
        match = [c for c in got.get("gate") or []
                 if isinstance(c, dict) and c.get("report") == check.get("report")]
        if len(match) != 1 or any(match[0].get(f) != v for f, v in changes.items()):
            return "the changed file does not read back with the new values"
    finally:
        tmp.unlink(missing_ok=True)
    path.write_text(new_text, encoding="utf-8")
    return None


def main(args):
    try:
        state = st.load(args.dir)
    except st.StateError as exc:
        raise Fail(str(exc), CANNOT_RUN, "ERROR") from None
    ad = Path(state["artifact_dir"])
    fixing = open_fix(state) is not None
    if not fixing and not state.get("stop"):
        refuse("change a gate check only at a stop, on the user's word, or from the "
               "fixer while its fix is open")
    if fixing and args.profile:
        refuse("the fixer never changes the saved profile: say in your report what to "
               "change there")
    gate = state["settings"]["gate"]
    i = find_check(gate, args.check)
    check = gate[i]
    changes = wanted(args, check)
    old = dict(check)
    for field, value in changes.items():
        if value is None:
            check.pop(field, None)
        else:
            check[field] = value
    who = "the fixer" if fixing else "the user at a stop"
    lines = [f"{field} of check {i + 1} ({check.get('report')}): "
             f"{old.get(field) or 'none'} → {value or 'none'}"
             for field, value in changes.items()]
    state.setdefault("gate_changes", []).append(
        {"check": i + 1, "report": check.get("report"), "by": who, "seq": st.seq(state),
         "changes": {f: [old.get(f), v] for f, v in changes.items()}})
    for line in lines:
        st.add_note(state, f"gate check changed by {who}: {line}")
    profile = None
    if args.profile:
        why = save_profile(ad, args.profile, check, old, changes)
        profile = (f"updated {args.profile}" if why is None else
                   f"left as it was: {why}. Change it by hand: "
                   + "; ".join(lines))
        st.add_note(state, f"saved profile {profile}")
    st.save(args.dir, state)
    refresh_profile_md(ad, state["settings"])
    emit(args.json, "GATE-CHECK", f"check {i + 1} ({check.get('report')})",
         changed=lines + [".auto-dev/state.json"], profile=profile)
    return 0
