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

It runs at a stop, on the user's word, in place of the stop's answer: `next`
stopped and asks how to go on, and the user's answer only changes how a gate
check runs. It records the change as a fix the user made at the stop, and the
step that stopped runs again (as after "I fixed it myself"); in Phase 5 the
quality gate runs again before the loop ends, on the new command. In Phase 6
it is refused: there the user's words go to the fixer, whose change the
gate, the verifier and a review check again. It also runs from the fixer
while the fix the user asked for is open (its report names
`.auto-dev/state.json`, and the change is put back unless it returns FIXED).

--profile <saved profile.yml>
    At a stop only, when the user said yes to saving it for later runs: the
    same change in the saved profile (`profile-path.py` names it), to its
    check with the same report. Each changed value is replaced in place when
    the file has it as that key's value exactly once and it is the value this
    run used, and the edited file must read back (PyYAML)
    as the old one with only those values changed and pass
    `validate-config.py --profile`; then it replaces the file whole.
    Otherwise (dropping a scoped form included) the file is left as it was
    and `profile:` says what to change by hand. A repo's committed `.auto-dev.yml` that sets
    `gate` wins over the saved profile.

Prints `GATE-CHECK` with a `changed:` line for each value (from → to), a
`changed: .auto-dev/state.json` line for the fixer's report, and with
--profile a `profile:` line. The change is noted in WORK_LOG.md and listed in
the PR body.

Exit codes:
    0  GATE-CHECK: changed (a profile left as it was still exits 0)
    1  refused: no stop and no open fix, a stop in Phase 6 or on the task's
       size, an unknown or
       ambiguous check, nothing to change, a --files form with no <files>, a
       value on more than one line or still a placeholder (`<…>`), or
       --profile from the fixer
    2  could not run (no state.json, unreadable)
"""

import copy
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from . import overrides
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
    if len(by_report) == 1:
        return by_report[0]
    if by_report:
        refuse(f"{key!r} is the report of more than one check: give its number")
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
        if value.startswith("<") and value.endswith(">"):
            refuse(f"--{field} {value!r} is a placeholder: put the user's command there, "
                   "or leave the option out when it doesn't change")
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
        return json.dumps(new, ensure_ascii=False)[1:-1]
    if before == "'":
        return new.replace("'", "''")
    return json.dumps(new, ensure_ascii=False)


def at_key(text, field, old):
    """Where `old` starts as the value of a `field:` key (after an optional
    anchor and opening quote), when it does exactly once; else None."""
    found = [m.end(1) for m in re.finditer(
        rf"(?<![\w-]){re.escape(field)}\s*:[ \t]*(?:&[\w-]+[ \t]+)?[\"']?({re.escape(old)})",
        text)]
    return found[0] - len(old) if len(found) == 1 else None


def save_profile(path, report, changes, old_run):
    """Make `changes` to the check with `report` in the saved profile at `path`, in
    place; None when done, or why not. The file is written only when the
    edited text passes validate-config.py and reads back as the old file with
    just those values changed."""
    path = Path(path).expanduser().resolve()  # a symlinked profile: its target
    try:
        import yaml
    except ImportError:
        return "PyYAML is not installed, so the change could not be checked"
    try:
        with open(path, encoding="utf-8", newline="") as f:  # keep its line endings
            text = f.read()
        before = yaml.safe_load(text) or {}
    except (OSError, yaml.YAMLError) as exc:
        return f"could not read it ({exc})"
    gate = before.get("gate") if isinstance(before, dict) else None
    found = [k for k, c in enumerate(gate if isinstance(gate, list) else [])
             if isinstance(c, dict) and c.get("report") == report]
    if len(found) != 1:
        return f"it has no single check with report {report}"
    index = found[0]
    expected = copy.deepcopy(before)
    new_text = text
    for field, value in changes.items():
        old = gate[index].get(field)
        if value is None:
            return f"dropping its `{field}` is not done in place"
        if not isinstance(old, str):
            return f"its {report} check has no `{field}` to replace in place"
        if old != old_run.get(field):
            return (f"its {report} check's `{field}` is `{old}`, not what this run used "
                    f"(`{old_run.get(field)}`)")
        at = at_key(new_text, field, old)
        if at is None:
            return f"it does not have `{field}: {old}` exactly once"
        new_text = new_text[:at] + scalar(new_text, at, value) + new_text[at + len(old):]
        expected["gate"][index][field] = value
    try:
        got = yaml.safe_load(new_text)
    except yaml.YAMLError:
        got = None
    if got != expected:
        return "the edited file does not read back with only those values changed"
    tmp = path.with_name(f".{path.name}.gate-check")
    try:
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            f.write(new_text)
        shutil.copymode(path, tmp)  # a 0600 profile stays 0600
        r = subprocess.run([sys.executable, str(SCRIPTS / "validate-config.py"),
                            "--profile", str(tmp)], capture_output=True, text=True,
                           check=False)
        if r.returncode != 0:
            return ("the edited file did not pass validate-config.py" if r.returncode == 1
                    else "validate-config.py could not check the edited file")
        os.replace(tmp, path)  # whole or not at all
    except OSError as exc:
        return f"could not write it ({exc})"
    finally:
        tmp.unlink(missing_ok=True)
    return None


def settle_stop(state, stop, what):
    """The user's answer at `stop`: a fix they made, already settled, so the
    step that stopped runs again and, in Phase 5, the gate runs again on the
    new command before the loop ends (cmd_next.last_fix)."""
    seq = st.seq(state)
    overrides.apply_retry(state, stop.get("retry") or {}, seq)
    for earlier in overrides.fixes(state):
        if earlier.get("status") == "open":
            earlier["status"] = "dropped"
    state.setdefault("overrides", []).append({
        "k": len(state.get("overrides") or []) + 1, "choice": "fix", "gate": True,
        "text": f"change a quality-gate check: {what}", "stop": stop, "seq": seq,
        "at": st.now(), "status": "fixed", "changed": [".auto-dev/state.json"],
        "code_changed": True, "spec_changed": False, "done_seq": seq})
    st.add_note(state, f"override at the stop ({stop.get('rule') or 'the stop'}): the "
                "user changed a quality-gate check; the step that stopped runs again")
    state.pop("stop", None)


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
    stop = state.get("stop") if not fixing else None
    if stop and (stop.get("phase") == 6 or st.phase(state, 6).get("status") == "in-progress"):
        refuse("in Phase 6, give the change to the fixer as the user's instruction (the "
               "typed answer's line): the gate, the verifier and a review then check it")
    if stop and (stop.get("retry") or {}).get("oversized"):
        refuse("this stop is about the task's size, not a gate check")
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
        why = save_profile(args.profile, check.get("report"), changes, old)
        profile = (f"updated {args.profile}" if why is None else
                   f"left as it was: {why}. Change it by hand: "
                   + "; ".join(lines))
        st.add_note(state, f"saved profile {profile}")
    if stop:
        settle_stop(state, stop, "; ".join(lines))
    st.save(args.dir, state)
    refresh_profile_md(ad, state["settings"])
    emit(args.json, "GATE-CHECK", f"check {i + 1} ({check.get('report')})",
         changed=lines + [".auto-dev/state.json"], profile=profile)
    return 0
