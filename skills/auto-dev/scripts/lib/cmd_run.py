"""autodev.py run gate|test — run one of the profile's own commands in the
run's worktree, and save its output.

Usage:
    autodev.py run gate <n | REPORT> --dir <artifact-dir> [--files <path> ...]
                        [--tests <id> ...] [--out <file>] [--timeout <seconds>]
                        [--tail <lines>] [--show] [--json]
    autodev.py run test --dir <artifact-dir> [--files <path> ...]
                        [--tests <id> ...] [--out <file>] [--timeout <seconds>]
                        [--tail <lines>] [--show] [--json]

A worker's shell doesn't start in the worktree, and a permission check refuses
`cd <worktree> && <command>` and rewritten forms of it. This runs the command
the profile lists, exactly as written, with the worktree as its directory, so
a worker never composes one. It runs only the profile's commands (the `gate`
checks confirmed in Phase 1, from state.json), never a command it is given.

gate <n | REPORT>
    Runs the quality-gate check numbered <n> (1 is the first, as profile.md's
    table numbers them), or the one whose report is REPORT (`LINT.md` or
    `LINT`, any case), else the first whose kind is REPORT (`lint`).
test
    Runs the test check: the first `kind: test` check with a `files` form,
    else the first `kind: test` check (`run gate <n>` runs any other).
--dir is required: it names the run, and a worker's shell isn't in the
worktree, so a default would find no run, or an old one.
--files <path> ...
    Runs the check's scoped form instead: its `files` command, with `<files>`
    replaced by the paths given, quoted, relative to the worktree (a relative
    path is taken from the worktree root). Each must exist inside the
    worktree. A check with no `files` form can't be scoped: exit 2, and so
    is a `files` form that holds `<tests>` or `<test>`.
--tests <id> ...
    Runs the check's test-ID form instead: its `tests` command, with `<tests>`
    replaced by the IDs given, each quoted as one argument, or `<test>`
    replaced by the one ID given (a form with `<test>` takes exactly one: a
    second is exit 2, never a fallback). An ID is the runner's own syntax and
    is passed as given; one that is empty, starts with `-` or holds a control
    character (or, on Windows, ends in a backslash) is exit 2, and so is a form whose
    placeholder is quoted, since `run` quotes each ID itself, or that holds
    `<files>`, which it would leave for the shell to read. A repeated
    --tests adds its IDs to the ones before. When the check has no `tests`
    form, the `files` form runs on the --files paths given with it, else the
    whole check runs. Paths given with --files are always checked, whichever
    form runs.

Each run prints its scope on the line after the token:
`  scope: tests|files|whole`, with ` — <why>` when --tests fell back or the
check has no scoped form. When `run test` (or a `run gate` given --files or
--tests) ran the check whole and it has a scoped form that wasn't used, a
`  warning:` follows: a whole run is for the quality gate only, then the
filled-in scoped `run` lines to use instead and the profile's example test
ID. The quality gate's own `run gate <n>`, with neither flag, never warns.

--show prints `COMMAND: <the command>` and runs nothing (exit 0), so a caller
that passes the command on uses the one `run` would run.

The command's whole output (stdout and stderr together) goes to --out, or else
to <artifact-dir>/tmp/run/<gate-<n>|test>-<k>.txt. --out must be under the
artifact dir's evidence/, acceptance/base-run/ or tmp/, so it never replaces
the run's state or its manifest; a relative --out is taken from the current
directory. When `run` is stopped (a timeout, or a signal such as the Bash
tool's own timeout), the command and everything it started are stopped too.
The script prints one token, then the command as run, the output file, the
time taken, and the output's last --tail lines (default 40):
    PASSED: `<command>` exited 0 in <s>s
    FAILED: `<command>` exited <code> in <s>s
    TIMED_OUT: `<command>` ran past <s>s and was stopped
With --json, `command`, `exit_code`, `seconds`, `output`, `lines`, `tail`,
`scope` (`tests`, `files` or `whole`) and `warning` (the whole warning text,
its lines joined by newlines, or null).

Exit codes:
    0  PASSED, or --show printed the command
    1  FAILED: the command exited non-zero
    2  could not run (no state, no such check, no `files` form, a path outside
       the worktree or missing, a test ID that is empty, starts with `-` or
       holds a control character, more than one ID for a `<test>` form, a
       quoted `<tests>` or `<test>`, a form holding the other form's
       placeholder, --out outside the artifact dir) — `ERROR: …`
    3  TIMED_OUT: the command and everything it started were stopped
"""

import json
import os
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path

from . import state as st
from .output import CANNOT_RUN, FAILED, OK, Fail, emit

TIMED_OUT = 3
PLACEHOLDER = "<files>"
TESTS_PLACEHOLDER = "<tests>"  # a list of test IDs
TEST_PLACEHOLDER = "<test>"  # exactly one test ID
SCRIPT = Path(__file__).resolve().parents[1] / "autodev.py"
TAIL = 40
# Where --out may write, under the artifact dir: never state.json, PLAN.md or
# MANIFEST.md.
OUT_DIRS = ("evidence", "acceptance/base-run", "tmp")


class Stopped(Exception):
    """A signal asked `run` to stop."""


def add_arguments(parser):
    parser.add_argument("what", choices=("gate", "test"))
    parser.add_argument("check", nargs="?",
                        help="gate: the check's number or its report name")
    parser.add_argument("--files", nargs="+", default=None,
                        help="run the check's scoped form on these paths")
    # extend: a repeated --tests adds its IDs, so none is dropped unseen
    parser.add_argument("--tests", nargs="+", action="extend", default=None,
                        help="run the check's test-ID form on these test IDs")
    parser.add_argument("--dir", required=True, help="the run's .auto-dev/")
    parser.add_argument("--out", help="the file to save the output to (under --dir's "
                                      "evidence/, acceptance/base-run/ or tmp/)")
    parser.add_argument("--timeout", type=float, help="stop the command after this "
                                                      "many seconds (exit 3)")
    parser.add_argument("--show", action="store_true",
                        help="print the command it would run, and run nothing")
    parser.add_argument("--tail", type=int, default=TAIL,
                        help="how many of the output's last lines to print")


def test_check(gate):
    """(number, check) of the test check: the first `kind: test` check whose
    `files` form holds <files> (it runs the given files and names each test),
    else the first `kind: test` check; None when the gate has none."""
    tests = [(i, c) for i, c in enumerate(gate, 1) if c.get("kind") == "test"]
    scoped = [(i, c) for i, c in tests if PLACEHOLDER in str(c.get("files") or "")]
    return (scoped or tests or [None])[0]


def pick(gate, what, check):
    """(the check's number, the check) the arguments name."""
    if what == "test":
        if check:
            raise Fail("`run test` takes no check name; use `run gate <n>`",
                       CANNOT_RUN, "ERROR")
        found = test_check(gate)
        if found:
            return found
        raise Fail("the profile's gate has no `kind: test` check", CANNOT_RUN, "ERROR")
    if not check:
        raise Fail("`run gate` needs the check's number or report name", CANNOT_RUN,
                   "ERROR")
    if check.isdigit():
        n = int(check)
        if 1 <= n <= len(gate):
            return n, gate[n - 1]
        raise Fail(f"the profile's gate has {len(gate)} check(s); there is no check {n}",
                   CANNOT_RUN, "ERROR")
    want = check.upper().removesuffix(".MD")
    for i, c in enumerate(gate, 1):
        if str(c.get("report", "")).upper().removesuffix(".MD") == want:
            return i, c
    for i, c in enumerate(gate, 1):  # else the first check of that kind
        if str(c.get("kind", "")).upper() == want:
            return i, c
    names = ", ".join(str(c.get("report", "")) for c in gate) or "none"
    raise Fail(f"no gate check has the report or kind {check!r} (reports: {names})",
               CANNOT_RUN, "ERROR")


def relative_paths(worktree, files):
    """Each path as the worktree-relative POSIX path the command is given: its
    own name (a symlink is not swapped for its target), checked to resolve
    inside the worktree."""
    root = worktree.resolve()
    out = []
    for name in files:
        path = Path(name)
        given = path if path.is_absolute() else root / path
        rel = None
        try:
            given.resolve().relative_to(root)
        except ValueError:
            raise Fail(f"{name} is outside the worktree {root}", CANNOT_RUN,
                       "ERROR") from None
        # Its own name, from the worktree as stored or as resolved (a folder
        # above it may be a symlink); its target's only when neither fits.
        for base in (worktree.absolute(), root):
            try:
                rel = Path(os.path.normpath(given)).relative_to(base)
                break
            except ValueError:
                continue
        if rel is None:
            rel = given.resolve().relative_to(root)
        if not given.exists():
            raise Fail(f"{name} does not exist in the worktree {root}", CANNOT_RUN,
                       "ERROR")
        text = rel.as_posix() or "."
        out.append(f"./{text}" if text.startswith("-") else text)  # never an option
    return out


def quote(paths):
    if os.name == "nt":  # cmd.exe: double quotes, and no name it would expand
        bad = [p for p in paths if '"' in p or "%" in p]
        if bad:
            raise Fail(f"{bad[0]}: a name with `\"` or `%` can't be passed safely on "
                       "Windows", CANNOT_RUN, "ERROR")
        return " ".join(f'"{p}"' for p in paths)
    return " ".join(shlex.quote(p) for p in paths)


def command_for(n, check, worktree, files):
    if files is None:
        command = str(check.get("command") or "")
        if not command:
            raise Fail(f"gate check {n} has no command", CANNOT_RUN, "ERROR")
        return command
    form = str(check.get("files") or "")
    if PLACEHOLDER not in form:
        raise Fail(f"gate check {n} (`{check.get('command', '')}`) has no scoped form: "
                   f"the profile gives it no `files` command with {PLACEHOLDER}, so "
                   f"it can only run whole (drop --files)", CANNOT_RUN, "ERROR")
    unfilled(n, form, "files", (TESTS_PLACEHOLDER, TEST_PLACEHOLDER))
    return form.replace(PLACEHOLDER, quote(relative_paths(worktree, files)))


def unfilled(n, form, key, placeholders):
    """Refuse a form that holds a placeholder it doesn't fill: left in the
    command, the shell would read `<files> <path>` as two redirects."""
    for p in placeholders:
        if p in form:
            raise Fail(f"gate check {n}'s `{key}` form (`{form}`) holds {p}, which only "
                       f"the other form fills: `run` would leave it in the command, "
                       f"where the shell reads it as a redirect. Remove {p} from the "
                       f"`{key}` form in the profile", CANNOT_RUN, "ERROR")


def test_ids(ids):
    """The IDs, unchanged, once each is checked to be data the runner can only
    read as a test ID: not empty, not an option, no control character, and on
    Windows no trailing backslash."""
    for test in ids:
        if not test:
            why = "it is empty"
        elif test.startswith("-"):
            why = "it starts with `-`, so the runner would read it as an option"
        elif any(c < " " or c == "\x7f" for c in test):
            why = "it holds a control character, such as a newline"
        elif os.name == "nt" and test.endswith("\\"):
            # The C runtime reads `\"` as a literal quote, so the closing quote
            # `quote` adds would be lost and the next ID's words would shift.
            why = "on Windows a trailing backslash would escape the quote around it"
        else:
            continue
        raise Fail(f"{test!r} is not a test ID: {why}", CANNOT_RUN, "ERROR")
    return ids


def quoted_placeholder(form, placeholders=(TESTS_PLACEHOLDER, TEST_PLACEHOLDER)):
    """The first of `placeholders` that `form` holds inside a quoted span or
    with a quote, backtick or backslash right beside it, else None. `run`
    quotes each value itself, so a placeholder the form quotes again hands the
    runner those quotes too, or lets the shell expand what the value holds."""
    marks = ("'", '"', "`", "\\")
    quoted = [False] * len(form)
    inside, i = None, 0
    while i < len(form):
        c = form[i]
        if inside:
            quoted[i] = True
            if c == "\\" and inside != "'":
                quoted[i + 1:i + 2] = [True] * len(form[i + 1:i + 2])
                i += 2
                continue
            if c == inside:
                inside = None
        elif c == "\\":
            quoted[i:i + 2] = [True] * len(form[i:i + 2])
            i += 2
            continue
        elif c in marks:
            quoted[i], inside = True, c
        i += 1
    for p in placeholders:
        at = form.find(p)
        while at != -1:
            end = at + len(p)
            if (quoted[at] or (at and form[at - 1] in marks)
                    or (end < len(form) and form[end] in marks)):
                return p
            at = form.find(p, end)
    return None


def has_form(check, key):
    form = str(check.get(key) or "")
    if key == "files":
        return PLACEHOLDER in form
    return TESTS_PLACEHOLDER in form or TEST_PLACEHOLDER in form


def resolve(n, check, worktree, files, tests):
    """(command, scope, why): the command --files and --tests choose, `tests`,
    `files` or `whole`, and why it fell back ('' when it didn't)."""
    if tests is None:
        command = command_for(n, check, worktree, files)
        if files:
            return command, "files", ""
        bare = not (has_form(check, "files") or has_form(check, "tests"))
        return command, "whole", "the check has no scoped form" if bare else ""
    test_ids(tests)
    if files:
        relative_paths(worktree, files)  # a given path is checked whatever runs
    form = str(check.get("tests") or "")
    unfilled(n, form, "tests", (PLACEHOLDER,))
    bad = quoted_placeholder(form)
    if bad:
        raise Fail(f"gate check {n}'s test-ID form (`{form}`) has {bad} inside quotes "
                   f"or next to a quote or backslash: `run` quotes each test ID itself, "
                   f"so write {bad} unquoted, as a word of its own, in the profile",
                   CANNOT_RUN, "ERROR")
    if TESTS_PLACEHOLDER in form:
        return form.replace(TESTS_PLACEHOLDER, quote(tests)), "tests", ""
    if TEST_PLACEHOLDER in form:
        if len(tests) > 1:
            raise Fail(f"gate check {n}'s test-ID form (`{form}`) takes one test ID "
                       f"({TEST_PLACEHOLDER}), and {len(tests)} were given: run it once "
                       "per ID, or give one pattern the runner matches", CANNOT_RUN,
                       "ERROR")
        return form.replace(TEST_PLACEHOLDER, quote(tests)), "tests", ""
    if files and has_form(check, "files"):
        return command_for(n, check, worktree, files), "files", "the check has no tests form"
    why = ("the check has no tests form and no --files was given"
           if has_form(check, "files") else "the check has no scoped form")
    return command_for(n, check, worktree, None), "whole", why


def run_line(ad, invocation="run test"):
    """The `run` command with the script and artifact dir filled in."""
    return f"python3 {shlex.quote(str(SCRIPT))} {invocation} --dir {shlex.quote(str(ad))}"


def scoped_runs(ad, check, invocation="run test", forms=("files", "tests")):
    """[(run line, note)] for each of `forms` the check has: the `run` command
    that runs it, with the script and artifact dir filled in and only the test
    file or ID left, and a note ('' when none)."""
    head = run_line(ad, invocation)
    runs = []
    if "files" in forms and has_form(check, "files"):
        runs.append((f"{head} --files <test file> …", ""))
    if "tests" in forms and has_form(check, "tests"):
        one = TESTS_PLACEHOLDER not in str(check.get("tests"))
        notes = ["one test ID per run"] if one else []
        if check.get("tests_example"):
            notes.append(f"a test ID looks like `{check['tests_example']}`")
        runs.append((f"{head} --tests <test id>{'' if one else ' …'}", "; ".join(notes)))
    return runs


def warning_text(ad, n, check, what, files, tests, scope):
    """The warning for a whole run a worker made where a scoped form would do,
    as one string (lines joined by newlines), or None."""
    if scope != "whole" or (what != "test" and not files and not tests):
        return None
    unused = [f for f in ("files", "tests")
              if has_form(check, f) and not (files if f == "files" else tests)]
    runs = scoped_runs(ad, check, "run test" if what == "test" else f"run gate {n}",
                       unused)
    if not runs:
        return None
    ran = "the whole test check" if what == "test" else f"check {n} whole"
    head = (f"this ran {ran}; a whole run is for the quality gate only. "
            "Run only the tests you need with:")
    return "\n".join([head] + [f"{line}  ({note})" if note else line
                               for line, note in runs])


def output_file(ad, out, label):
    """The file to save to: --out (under one of OUT_DIRS), else the next free
    tmp/run/<label>-<k>.txt."""
    root = ad.resolve()
    if out:
        path = Path(out)
        path = (path if path.is_absolute() else Path.cwd() / path).resolve()
        if not any(path.is_relative_to(root / d) and path != root / d
                   for d in OUT_DIRS):
            raise Fail(f"--out {out} is not under {', '.join(f'{root}/{d}/' for d in OUT_DIRS)}",
                       CANNOT_RUN, "ERROR")
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    folder = root / "tmp" / "run"
    folder.mkdir(parents=True, exist_ok=True)
    k = 1
    while True:
        path = folder / f"{label}-{k}.txt"
        try:
            with open(path, "x", encoding="utf-8"):
                return path
        except FileExistsError:
            k += 1


def stop(proc):
    """Stop everything the command started: its process group (POSIX, even once
    the shell itself has exited) or, while it runs, its process tree (Windows)."""
    try:
        if os.name == "nt":
            if proc.poll() is None:
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                               capture_output=True, check=False)
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except OSError:
        pass
    proc.wait()


def on_signal(signum, _frame):
    raise Stopped(f"signal {signum}")


def execute(command, worktree, path, timeout):
    """(exit code or None on a timeout, seconds)."""
    start = time.monotonic()
    # A signal ignored on purpose (nohup's SIGHUP) stays ignored.
    caught = [s for s in ("SIGTERM", "SIGHUP", "SIGINT") if hasattr(signal, s)
              and signal.getsignal(getattr(signal, s)) is not signal.SIG_IGN]
    old = {s: signal.signal(getattr(signal, s), on_signal) for s in caught}
    proc = None
    try:
        with open(path, "w", encoding="utf-8", errors="replace") as log:
            flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
            try:
                proc = subprocess.Popen(command, shell=True, cwd=worktree, stdout=log,
                                        stderr=subprocess.STDOUT,
                                        stdin=subprocess.DEVNULL, creationflags=flags,
                                        start_new_session=(os.name != "nt"))
                code = proc.wait(timeout=timeout)
            except OSError as exc:
                raise Fail(f"could not start `{command}`: {exc}", CANNOT_RUN,
                           "ERROR") from None
            except subprocess.TimeoutExpired:
                code = None
            except Stopped as exc:
                raise Fail(f"`{command}` was stopped by a {exc}; nothing it started "
                           "is left running", CANNOT_RUN, "ERROR") from None
            finally:
                if proc is not None:
                    for name in caught:  # a second signal can't cut the stop short
                        signal.signal(getattr(signal, name), signal.SIG_IGN)
                    stop(proc)
    finally:
        for name, handler in old.items():
            signal.signal(getattr(signal, name), handler)
    return code, round(time.monotonic() - start, 1)


def main(args):
    ad = Path(args.dir)
    state = st.load(ad)
    worktree = Path(state["worktree"])
    if not worktree.is_dir():
        raise Fail(f"the worktree {worktree} does not exist", CANNOT_RUN, "ERROR")
    if args.tail < 0 or (args.timeout is not None and args.timeout <= 0):
        raise Fail("--tail must be 0 or more and --timeout more than 0", CANNOT_RUN,
                   "ERROR")
    n, check = pick(state["settings"].get("gate", []), args.what, args.check)
    command, scope, why = resolve(n, check, worktree, args.files, args.tests)
    if args.show:
        emit(args.json, "COMMAND", command)
        return OK
    path = output_file(ad, args.out, "test" if args.what == "test" else f"gate-{n}")
    code, seconds = execute(command, worktree, path, args.timeout)
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    tail = lines[-args.tail:] if args.tail else []
    if code is None:
        token, result = "TIMED_OUT", TIMED_OUT
        message = f"`{command}` ran past {args.timeout:g}s and was stopped"
    else:
        token, result = ("PASSED", OK) if code == 0 else ("FAILED", FAILED)
        message = f"`{command}` exited {code} in {seconds:g}s"
    warning = warning_text(Path(os.path.abspath(ad)), n, check, args.what, args.files,
                           args.tests, scope)
    if args.json:
        print(json.dumps({"result": token, "message": message, "command": command,
                          "exit_code": code, "seconds": seconds, "output": str(path),
                          "lines": len(lines), "tail": tail, "scope": scope,
                          "warning": warning}, indent=2, sort_keys=True))
        return result
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")  # output that isn't UTF-8 never crashes
    print(f"{token}: {message}")
    print(f"  scope: {scope}" + (f" — {why}" if why else ""))
    if warning:
        first, *more = warning.split("\n")
        print(f"  warning: {first}")
        for line in more:
            print(f"    {line}")
    print(f"  output: {path} ({len(lines)} lines)")
    if tail:
        shown = "all" if len(tail) == len(lines) else f"the last {len(tail)}"
        print(f"  {shown} of its lines:")
        for line in tail:
            print(f"    {line}")
    return result
