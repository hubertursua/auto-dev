"""autodev.py run gate|test|wait — run one of the profile's own commands in the
run's worktree, and save its output; or wait for a run that went to the
background.

Usage:
    autodev.py run gate <n | REPORT> --dir <artifact-dir> [--files <path> ...]
                        [--tests <id> ...] [--out <file>] [--timeout <seconds>]
                        [--tail <lines>] [--show] [--json] [-- <arg> ...]
    autodev.py run test --dir <artifact-dir> [--files <path> ...]
                        [--tests <id> ...] [--out <file>] [--timeout <seconds>]
                        [--tail <lines>] [--show] [--json] [-- <arg> ...]
    autodev.py run wait --dir <artifact-dir> [--wait <seconds>] [--tail <lines>]
                        [--json]

A worker's shell doesn't start in the worktree, and a permission check refuses
`cd <worktree> && <command>` and rewritten forms of it. This runs the command
the profile lists, exactly as written, with the worktree as its directory, so
a worker never composes one. It runs only the profile's commands (the `gate`
checks confirmed in Phase 1, from state.json), never a command it is given;
a caller adds only arguments (after `--`), each passed as one quoted word.

gate <n | REPORT>
    Runs the quality-gate check numbered <n> (1 is the first, as profile.md's
    table numbers them), or the one whose report is REPORT (`LINT.md` or
    `LINT`, any case), else the first whose kind is REPORT (`lint`).
test
    Runs the test check: the first `kind: test` check with a `files` form,
    else the first `kind: test` check (`run gate <n>` runs any other).
wait
    Waits for the `run gate` or `run test` started last under --dir (one the
    Bash tool moved to the background) to end, then prints exactly what that
    run printed, and exits with its code (0, 1 or 3). With no --tail of its
    own it shows as many last lines as the run did. It waits at most --wait
    seconds (default and most 170: the Bash tool moves a call still running
    after 180 s to the background, so a longer wait would be moved too). A
    run still going then prints `RUNNING: <command> is still running …` and
    an `output:` line, exit 4, and is left running: run `run wait` again. It
    only reads: it never stops the run, so the run's own timeout is what
    ends a hung check. Each `run gate|test` (never --show) keeps a record of
    itself, and its result once it ends, in
    <artifact-dir>/tmp/run/records/<k>.json; `wait` reads the newest. It
    reads only where `run` may save its output: a record whose output file,
    its links followed, is not under the artifact dir's evidence/,
    acceptance/base-run/ or tmp/ (where --out may write) is exit 2. Those
    folders are taken as named, never resolved, so one that is itself a link
    out of the artifact dir is refused (by `run gate|test` before it runs, and
    by `wait`). The file checked is the file read, opened without following a
    link, so swapping it for a link after the check is refused too; swapping
    one of its parent folders for a link in that moment is not covered.
--dir is required: it names the run, and a worker's shell isn't in the
worktree, so a default would find no run, or an old one.
--files <path> ...
    Runs the check's scoped form instead: its `files` command, with `<files>`
    replaced by the paths given, quoted, relative to the worktree (a relative
    path is taken from the worktree root). Each must exist inside the
    worktree. A check with no `files` form can't be scoped: exit 2, and so
    is a `files` form that holds `<tests>` or `<test>`, or whose `<files>` is
    quoted, since `run` quotes each path itself.
--tests <id> ...
    Runs the check's test-ID form instead: its `tests` command, with `<tests>`
    replaced by the IDs given, each quoted as one argument, or `<test>`
    replaced by the one ID given (a form with `<test>` takes exactly one: a
    second is exit 2, never a fallback). An ID is the runner's own syntax and
    is passed as given; one that is empty, starts with `-` or holds a control
    character is exit 2, and so is a form whose placeholder is quoted, since
    `run` quotes each ID itself, or that holds `<files>`, which it would leave
    for the shell to read. On Windows an ID that ends in a backslash or holds
    `"`, `%` or `!` (cmd.exe's delayed expansion) is exit 2 too, checked again
    with fullwidth lookalikes mapped to ASCII (NFKC), and so is a --files
    path with `"`, `%` or `!`. A repeated --tests adds its IDs to the ones
    before. When the check has no `tests` form, the `files` form runs on the
    --files paths given with it, else the whole check runs. Paths given with
    --files are always checked, whichever form runs.
-- <arg> ...
    Everything after `--` is extra arguments for the command (or the `files`
    or `tests` form that runs), such as a test-name filter or a `<path>:<line>`
    target: each is quoted, so it is one argument and never shell syntax. They
    go where the command has `<args>`, else at its end. A command with
    `<args>` run with none has the placeholder removed. On Windows an argument
    that ends in a backslash or holds `"`, `%` or `!` is exit 2, as a test ID
    is. `run wait` takes none.

--timeout <seconds>
    Stops the command after that many seconds (exit 3). With no --timeout,
    `run` stops it at a default: twice the newest whole run of the same
    command that the quality gate or `verify prep` measured (saved in
    <artifact-dir>/tmp/run/timings.json, keyed by the check's command), and
    never less than 600 seconds (600 when none was measured). A check
    expected to run longer is given its own --timeout.

Each run prints its scope on the line after the token:
`  scope: tests|files|whole`, with ` — <why>` when --tests fell back or the
check has no scoped form. When `run test` (or a `run gate` given --files or
--tests) ran the check whole and it has a scoped form that wasn't used, a
`  warning:` follows: a whole run is for the quality gate only, then the
filled-in scoped `run` lines to use instead and the profile's example test
ID. The quality gate's own `run gate <n>`, with neither flag, never warns.
Then `  timeout: <s>s — <why>` (the timeout it used: `--timeout`, the floor, or
twice a measured whole run). A `run gate <n>` that fails or times out, whole or
scoped, counts as an attempt at check <n>: it prints
`  attempt: <k> of 3 failed for check <n>`, with ` — the third has failed: stop
fixing it; it stays failing` once <k> is 3 or more. The count runs back over the
`run gate <n>` runs since the newest file under <artifact-dir>/briefs/ was
written (the current worker's spawn) and stops at one that passed; `run test`
runs are never counted.

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
`scope` (`tests`, `files` or `whole`), `warning` (the whole warning text,
its lines joined by newlines, or null), `timeout` (the seconds it used) and
`attempt` (the failed attempt's number, or null).

Exit codes:
    0  PASSED, or --show printed the command
    1  FAILED: the command exited non-zero
    2  could not run (no state, no such check, no `files` form, a path outside
       the worktree or missing, a test ID that is empty, starts with `-` or
       holds a control character, on Windows also a test ID or an argument
       after `--` that ends in a backslash, or a test ID, argument or path that
       holds `"`, `%` or `!`, each checked again with fullwidth lookalikes
       mapped to ASCII, more than one ID
       for a `<test>` form, a quoted `<files>`, `<tests>` or `<test>`, a form
       holding the other form's placeholder, --out outside the artifact dir
       or tmp/ linked out of it; wait: no run was started, the run ended
       without a result, its output not where --out may write or swapped for
       a link, an argument only gate or test takes, --wait outside 1 to 170)
       — `ERROR: …`
    3  TIMED_OUT: the command and everything it started were stopped
    4  RUNNING: wait only: the run is still going; run `run wait` again
"""

import json
import math
import os
import re
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import unicodedata
from pathlib import Path

from . import cmd_init
from . import state as st
from .output import CANNOT_RUN, FAILED, OK, Fail, emit

TIMED_OUT = 3
RUNNING = 4
WAIT_MAX = 170  # under the 180 s after which the Bash tool backgrounds a call
# A record's replace Windows refuses while a reader has the file open: tries, and
# the seconds between them.
REPLACE_TRIES, REPLACE_DELAY = 10, 0.1
PLACEHOLDER = "<files>"
TESTS_PLACEHOLDER = "<tests>"  # a list of test IDs
TEST_PLACEHOLDER = "<test>"  # exactly one test ID
ARGS_PLACEHOLDER = "<args>"  # the caller's arguments after `--`
SCRIPT = Path(__file__).resolve().parents[1] / "autodev.py"
TAIL = 40
# Where --out may write, under the artifact dir: never state.json, PLAN.md or
# MANIFEST.md.
OUT_DIRS = ("evidence", "acceptance/base-run", "tmp")
# The default timeout: twice the newest measured whole run, never less than this.
TIMEOUT_FLOOR = 600
TIMINGS = "timings.json"
ATTEMPTS = 3  # failed runs of a check before the worker stops fixing it


class Stopped(Exception):
    """A signal asked `run` to stop."""


def add_arguments(parser):
    parser.add_argument("what", choices=("gate", "test", "wait"))
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
                                                      "many seconds (exit 3; default: "
                                                      "twice its measured whole run, at "
                                                      f"least {TIMEOUT_FLOOR})")
    parser.add_argument("--show", action="store_true",
                        help="print the command it would run, and run nothing")
    parser.add_argument("--tail", type=int, default=None,
                        help=f"how many of the output's last lines to print (default "
                             f"{TAIL}; wait: the run's own)")
    parser.add_argument("--wait", type=int, default=None,
                        help=f"wait: seconds to wait for the run, 1 to {WAIT_MAX} "
                             f"(default {WAIT_MAX})")


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


def windows_forms(text):
    """The text, and its NFKC form when that differs: a Windows program that
    reads its command line through the ANSI API gets the fullwidth forms
    (U+FF0D, U+FF02, U+FF3C, U+FF05, U+FF01) best-fit mapped to `-` `"` `\\`
    `%` `!`."""
    folded = unicodedata.normalize("NFKC", text)
    return (text,) if folded == text else (text, folded)


def quote(words):
    if os.name == "nt":  # cmd.exe: double quotes, and no word it would expand
        for w in words:
            for form in windows_forms(w):
                if '"' in form or "%" in form:
                    why = "`\"` would end the quotes around it, and `%` expand a variable"
                elif "!" in form:
                    why = ("cmd.exe's delayed expansion would replace `!…!` with a "
                           "variable's value, inside the quotes too")
                elif form.endswith("\\"):
                    why = "a trailing backslash would escape the quote around it"
                else:
                    continue
                lookalike = " (as a fullwidth lookalike)" if form != w else ""
                raise Fail(f"{w}: a name, test ID or argument with `\"`, `%` or `!`, or "
                           f"ending in `\\`{lookalike}, can't be passed safely on "
                           f"Windows: {why}", CANNOT_RUN, "ERROR")
        return " ".join(f'"{w}"' for w in words)
    return " ".join(shlex.quote(w) for w in words)


def fill(command, values):
    """The command with each placeholder in `values` replaced in one pass, so
    a value that contains a placeholder is never filled in again. A
    placeholder with an empty value goes, with the space before it."""
    def sub(m):
        value = values[m.group(2)]
        return m.group(1) + value if value else ""
    pattern = "|".join(re.escape(k) for k in values)
    return re.sub(rf"( ?)({pattern})", sub, command)


def with_args(command, extra, filled=None):
    """The command with the caller's extra arguments, quoted, where it has
    ARGS_PLACEHOLDER, else at its end; `filled` gives other placeholders'
    values (<files>), replaced in the same pass."""
    words = quote(extra) if extra else ""
    values = {**(filled or {}), ARGS_PLACEHOLDER: words}
    if words and ARGS_PLACEHOLDER not in command:
        return f"{fill(command, values)} {words}"
    return fill(command, values)


def command_for(n, check, worktree, files, extra=()):
    if files is None:
        command = str(check.get("command") or "")
        if not command:
            raise Fail(f"gate check {n} has no command", CANNOT_RUN, "ERROR")
        return with_args(command, extra)
    form = str(check.get("files") or "")
    if PLACEHOLDER not in form:
        raise Fail(f"gate check {n} (`{check.get('command', '')}`) has no scoped form: "
                   f"the profile gives it no `files` command with {PLACEHOLDER}, so "
                   f"it can only run whole (drop --files)", CANNOT_RUN, "ERROR")
    unfilled(n, form, "files", (TESTS_PLACEHOLDER, TEST_PLACEHOLDER))
    refuse_quoted(n, form, "files", (PLACEHOLDER,), "path")
    return with_args(form, extra, {PLACEHOLDER: quote(relative_paths(worktree, files))})


def refuse_quoted(n, form, key, placeholders, what):
    """Refuse a form that quotes its placeholder: `run` quotes each value
    itself, so the form's own quotes would reach the runner, or let the shell
    expand what the value holds (a file named `$(…)`)."""
    bad = quoted_placeholder(form, placeholders)
    if bad:
        raise Fail(f"gate check {n}'s `{key}` form (`{form}`) has {bad} inside quotes "
                   f"or next to a quote or backslash: `run` quotes each {what} itself, "
                   f"so write {bad} unquoted, as a word of its own, in the profile",
                   CANNOT_RUN, "ERROR")


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
    Windows no trailing backslash, for the ID as given or (on Windows) its
    fullwidth lookalikes mapped to ASCII. `quote` refuses the rest."""
    for test in ids:
        why = not_a_test_id(test)
        folded = windows_forms(test)[-1] if os.name == "nt" else test
        if not why and folded != test and not_a_test_id(folded):
            why = (f"{not_a_test_id(folded)}, once Windows maps its fullwidth "
                   f"lookalikes to ASCII ({folded!r})")
        if why:
            raise Fail(f"{test!r} is not a test ID: {why}", CANNOT_RUN, "ERROR")
    return ids


def not_a_test_id(test):
    """Why `test` can't be passed as a test ID, or ''."""
    if not test:
        return "it is empty"
    if test.startswith("-"):
        return "it starts with `-`, so the runner would read it as an option"
    if any(c < " " or c == "\x7f" for c in test):
        return "it holds a control character, such as a newline"
    if os.name == "nt" and test.endswith("\\"):
        # The C runtime reads `\"` as a literal quote, so the closing quote
        # `quote` adds would be lost and the next ID's words would shift.
        return "on Windows a trailing backslash would escape the quote around it"
    return ""


def quoted_placeholder(form, placeholders=(TESTS_PLACEHOLDER, TEST_PLACEHOLDER)):
    """The first of `placeholders` that `form` holds inside a quoted span, with
    a quote, backtick or backslash right beside it, or with a `$` right before
    it, else None. `run` quotes each value itself, so a placeholder the form
    quotes again hands the runner those quotes too, or lets the shell expand
    what the value holds; a `$` would turn `run`'s own quotes into bash's
    `$'…'`, where a backslash escapes the closing quote."""
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
            if (quoted[at] or (at and form[at - 1] in marks + ("$",))
                    or (end < len(form) and form[end] in marks)):
                return p
            at = form.find(p, end)
    return None


def has_form(check, key):
    form = str(check.get(key) or "")
    if key == "files":
        return PLACEHOLDER in form
    return TESTS_PLACEHOLDER in form or TEST_PLACEHOLDER in form


def resolve(n, check, worktree, files, tests, extra=()):
    """(command, scope, why): the command --files and --tests choose, `tests`,
    `files` or `whole`, with the caller's `extra` arguments (after `--`) in it,
    and why it fell back ('' when it didn't)."""
    if tests is None:
        command = command_for(n, check, worktree, files, extra)
        if files:
            return command, "files", ""
        bare = not (has_form(check, "files") or has_form(check, "tests"))
        return command, "whole", "the check has no scoped form" if bare else ""
    test_ids(tests)
    if files:
        relative_paths(worktree, files)  # a given path is checked whatever runs
    form = str(check.get("tests") or "")
    unfilled(n, form, "tests", (PLACEHOLDER,))
    refuse_quoted(n, form, "tests", (TESTS_PLACEHOLDER, TEST_PLACEHOLDER), "test ID")
    if TESTS_PLACEHOLDER in form:
        return with_args(form, extra, {TESTS_PLACEHOLDER: quote(tests)}), "tests", ""
    if TEST_PLACEHOLDER in form:
        if len(tests) > 1:
            raise Fail(f"gate check {n}'s test-ID form (`{form}`) takes one test ID "
                       f"({TEST_PLACEHOLDER}), and {len(tests)} were given: run it once "
                       "per ID, or give one pattern the runner matches", CANNOT_RUN,
                       "ERROR")
        return with_args(form, extra, {TEST_PLACEHOLDER: quote(tests)}), "tests", ""
    if files and has_form(check, "files"):
        return (command_for(n, check, worktree, files, extra), "files",
                "the check has no tests form")
    why = ("the check has no tests form and no --files was given"
           if has_form(check, "files") else "the check has no scoped form")
    return command_for(n, check, worktree, None, extra), "whole", why


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


def may_save(root, path):
    """Whether `path` (resolved) is a file under one of OUT_DIRS of the
    resolved artifact dir `root`: where `run` may save its output."""
    return any(path.is_relative_to(root / d) and path != root / d for d in OUT_DIRS)


def out_dirs(root):
    return ", ".join(f"{root}/{d}/" for d in OUT_DIRS)


def output_file(ad, out, label):
    """The file to save to: --out (under one of OUT_DIRS), else the next free
    tmp/run/<label>-<k>.txt."""
    root = ad.resolve()
    if out:
        path = Path(out)
        path = (path if path.is_absolute() else Path.cwd() / path).resolve()
        if not may_save(root, path):
            raise Fail(f"--out {out} is not under {out_dirs(root)}", CANNOT_RUN, "ERROR")
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    folder = root / "tmp" / "run"
    if not may_save(root, folder.resolve() / f"{label}-1.txt"):  # a linked tmp/
        raise Fail(f"{folder} resolves to {folder.resolve()}, not under "
                   f"{out_dirs(root)}: `run` saves its output only there", CANNOT_RUN,
                   "ERROR")
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


def timings_path(ad):
    return ad.resolve() / "tmp" / "run" / TIMINGS


def read_timings(ad):
    """{command: {"seconds", "by", "at"}}: the measured whole runs; {} when
    there are none or the file can't be read."""
    try:
        data = json.loads(timings_path(ad).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_timing(ad, command, seconds, by):
    """Save how long a whole, finished run of `command` took, for the default
    timeout; a failed write never changes the caller's result."""
    path = timings_path(Path(ad))
    data = read_timings(Path(ad))
    data[command] = {"seconds": seconds, "by": by, "at": st.now()}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        write_record(path, data)
    except OSError:
        pass


def default_timeout(ad, check):
    """(seconds, why): twice the newest measured whole run of the check's
    command, never less than TIMEOUT_FLOOR. A run is saved under the command
    as it ran whole, with no <args>, so that is the key."""
    entry = read_timings(ad).get(with_args(str(check.get("command") or ""), ()))
    try:
        measured = float(entry["seconds"])
        by = str(entry.get("by") or "a whole run")
    except (TypeError, KeyError, ValueError):
        return TIMEOUT_FLOOR, "the floor: no whole run of this check measured yet"
    timeout = max(TIMEOUT_FLOOR, math.ceil(2 * measured))
    if timeout > TIMEOUT_FLOOR:
        return timeout, f"twice the {measured:g}s whole run {by} measured"
    return TIMEOUT_FLOOR, f"the floor: twice the {measured:g}s whole run {by} measured is less"


def spawn_start(ad):
    """When the current worker was spawned: the newest mtime among the files
    under briefs/ (a brief is written for each spawn), or None."""
    try:
        times = [p.stat().st_mtime for p in (ad.resolve() / "briefs").iterdir()
                 if p.is_file()]
    except OSError:
        return None
    return max(times) if times else None


def failed_attempts(ad, n, record):
    """How many `run gate <n>` runs in a row have failed, this one included:
    back from the newest to one that passed or one started before the current
    worker's spawn. `run test` runs neither count nor reset it."""
    start = spawn_start(ad)
    folder = records_dir(ad)
    mine = record_number(record) if record is not None else None
    try:
        found = sorted((record_number(p), p) for p in folder.iterdir()
                       if record_number(p) is not None)
    except OSError:
        found = []
    count = 1
    for k, path in reversed(found):
        if mine is not None and k >= mine:
            continue
        rec = read_record(path)
        if not rec or rec.get("what") != "gate" or rec.get("check") != n:
            continue
        if start is not None and float(rec.get("started") or 0) < start:
            break
        token = rec.get("token")
        if token == "PASSED":
            break
        if token in ("FAILED", "TIMED_OUT"):
            count += 1
    return count


def records_dir(ad):
    return ad.resolve() / "tmp" / "run" / "records"


def record_number(path):
    """<k> of a record file <k>.json, else None."""
    return int(path.stem) if path.suffix == ".json" and path.stem.isdigit() else None


def newest_record(ad):
    """The record of the run started last under `ad`, or None."""
    folder = records_dir(ad)
    if not folder.is_dir():
        return None
    found = [(record_number(p), p) for p in folder.iterdir()]
    found = [(k, p) for k, p in found if k is not None]
    return max(found)[1] if found else None


def claim_record(ad):
    """A new record file, numbered after every one there."""
    folder = records_dir(ad)
    folder.mkdir(parents=True, exist_ok=True)
    newest = newest_record(ad)
    k = record_number(newest) + 1 if newest else 1
    while True:
        path = folder / f"{k}.json"
        try:
            with open(path, "x", encoding="utf-8"):
                return path
        except FileExistsError:
            k += 1


def write_record(path, rec):
    """Write the record whole (a reader never sees half of it), through a new
    temporary file `mkstemp` makes, so a link planted where it writes is never
    followed. Windows refuses the replace while `run wait` has the record open,
    so a refused one is tried again; when every try fails, the temporary file
    is removed."""
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=f"{path.name}.", suffix=".tmp")
    tmp = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(json.dumps(rec))
        for attempt in range(REPLACE_TRIES):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if attempt == REPLACE_TRIES - 1:
                    raise
                time.sleep(REPLACE_DELAY)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def read_record(path):
    """The record as a dict, or None while it can't be read (being written)."""
    try:
        rec = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return rec if isinstance(rec, dict) else None


def keep(path, rec):
    """Save the record; a failed write never changes `run`'s own result."""
    if path is None:
        return
    try:
        write_record(path, rec)
    except OSError:
        pass


def read_output(path):
    """The text of the output file at `path`, opened without following a link
    at it (where the system can tell)."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    with os.fdopen(os.open(path, flags), encoding="utf-8", errors="replace") as text:
        return text.read()


def report(args, rec, tail, source=None):
    """Print a finished run's result from its record, as `run` does; its exit code.
    It reads `source` (`run wait`'s checked file) when given, else the record's
    output; it always shows the record's output."""
    path = Path(rec["output"])
    if source is None:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    else:
        lines = read_output(source).splitlines()
    shown = lines[-tail:] if tail else []
    token, message, warning = rec["token"], rec["message"], rec.get("warning")
    if args.json:
        print(json.dumps({"result": token, "message": message, "command": rec["command"],
                          "exit_code": rec.get("exit_code"), "seconds": rec.get("seconds"),
                          "output": str(path), "lines": len(lines), "tail": shown,
                          "scope": rec["scope"], "warning": warning,
                          "timeout": rec.get("timeout"), "attempt": rec.get("attempt")},
                         indent=2, sort_keys=True))
        return rec["exit"]
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")  # output that isn't UTF-8 never crashes
    print(f"{token}: {message}")
    why = rec.get("why")
    print(f"  scope: {rec['scope']}" + (f" — {why}" if why else ""))
    if warning:
        first, *more = warning.split("\n")
        print(f"  warning: {first}")
        for line in more:
            print(f"    {line}")
    if rec.get("timeout") is not None:
        why = rec.get("timeout_why")
        print(f"  timeout: {rec['timeout']:g}s" + (f" — {why}" if why else ""))
    if rec.get("attempt"):
        k = rec["attempt"]
        print(f"  attempt: {k} of {ATTEMPTS} failed for check {rec.get('check')}"
              + (" — the third has failed: stop fixing it; it stays failing"
                 if k >= ATTEMPTS else ""))
    print(f"  output: {path} ({len(lines)} lines)")
    if shown:
        which = "all" if len(shown) == len(lines) else f"the last {len(shown)}"
        print(f"  {which} of its lines:")
        for line in shown:
            print(f"    {line}")
    return rec["exit"]


def check_wait_arguments(args):
    if args.what == "wait":
        given = [name for name, value in (("a check name", args.check),
                                          ("--files", args.files), ("--tests", args.tests),
                                          ("--out", args.out), ("--timeout", args.timeout),
                                          ("--show", args.show or None),
                                          ("arguments after `--`",
                                           getattr(args, "extra", None) or None))
                 if value is not None]
        if given:
            raise Fail(f"`run wait` takes only --dir, --wait, --tail and --json, not "
                       f"{', '.join(given)}", CANNOT_RUN, "ERROR")
        if args.wait is not None and not 1 <= args.wait <= WAIT_MAX:
            raise Fail(f"--wait must be 1 to {WAIT_MAX} seconds: the Bash tool moves a call "
                       "still running after 180 s to the background", CANNOT_RUN, "ERROR")
        if args.tail is not None and args.tail < 0:
            raise Fail("--tail must be 0 or more", CANNOT_RUN, "ERROR")
    elif args.wait is not None:
        raise Fail(f"--wait is for `run wait` only, not `run {args.what}`", CANNOT_RUN,
                   "ERROR")


def own_output(ad, path, rec):
    """The run's output file, its links followed, when it is where `run` may
    save one (`may_save`, as --out is checked); else `run wait` reads nothing."""
    root = ad.resolve()
    output = rec.get("output")
    if not isinstance(output, str) or not output:
        raise Fail(f"the run record {path} names no output file", CANNOT_RUN, "ERROR")
    resolved = Path(output).resolve()
    if may_save(root, resolved):
        return resolved
    raise Fail(f"the run record {path} names the output {output!r}, which resolves to "
               f"{resolved}, not under {out_dirs(root)}: `run wait` reads only where "
               "`run` may save its output", CANNOT_RUN, "ERROR")


def finished(args, ad, path, rec):
    """A run's recorded result, printed as `run` printed it."""
    if rec["token"] == "ERROR":
        raise Fail(f"{rec.get('message')} (its output: {rec.get('output')})", CANNOT_RUN,
                   "ERROR")
    source = own_output(ad, path, rec)
    tail = rec.get("tail", TAIL) if args.tail is None else args.tail
    try:
        return report(args, rec, tail, source)
    except OSError as exc:
        raise Fail(f"the run's output {rec['output']} can't be read: {exc}", CANNOT_RUN,
                   "ERROR") from exc


def wait(args, ad):
    """Wait up to --wait seconds for the run started last; print its result,
    or RUNNING."""
    path = newest_record(ad)
    if path is None:
        raise Fail(f"no `run test` or `run gate` was started under {os.path.abspath(ad)}",
                   CANNOT_RUN, "ERROR")
    deadline = time.monotonic() + (args.wait or WAIT_MAX)
    rec = None
    while True:
        rec = read_record(path) or rec
        if rec and rec.get("token"):
            return finished(args, ad, path, rec)
        if rec and not cmd_init.runner_alive(rec.get("pid")):
            time.sleep(0.2)  # it may have written its result as it ended
            again = read_record(path)
            if again and again.get("token"):
                return finished(args, ad, path, again)
            raise Fail(f"the run of `{rec.get('command')}` ended without a result (its "
                       f"output: {rec.get('output')})", CANNOT_RUN, "ERROR")
        left = deadline - time.monotonic()
        if left <= 0:
            break
        time.sleep(min(0.5, left))
    if rec is None:
        raise Fail(f"the run record {path} can't be read", CANNOT_RUN, "ERROR")
    resolved, output = own_output(ad, path, rec), Path(rec["output"])
    try:
        count = len(read_output(resolved).splitlines())
    except OSError:
        count = 0
    seconds = round(time.time() - rec.get("started", time.time()), 1)
    message = (f"`{rec['command']}` is still running after {seconds:g}s; run "
               f"`{run_line(ad, 'run wait')}` again")
    if args.json:
        print(json.dumps({"result": "RUNNING", "message": message,
                          "command": rec["command"], "output": str(output),
                          "seconds": seconds}, indent=2, sort_keys=True))
        return RUNNING
    print(f"RUNNING: {message}")
    print(f"  output: {output} ({count} lines so far)")
    return RUNNING


def main(args):
    ad = Path(args.dir)
    check_wait_arguments(args)
    if args.what == "wait":
        st.load(ad)  # a run's artifact dir
        return wait(args, Path(os.path.abspath(ad)))
    state = st.load(ad)
    worktree = Path(state["worktree"])
    if not worktree.is_dir():
        raise Fail(f"the worktree {worktree} does not exist", CANNOT_RUN, "ERROR")
    tail = TAIL if args.tail is None else args.tail
    if tail < 0 or (args.timeout is not None and args.timeout <= 0):
        raise Fail("--tail must be 0 or more and --timeout more than 0", CANNOT_RUN,
                   "ERROR")
    n, check = pick(state["settings"].get("gate", []), args.what, args.check)
    command, scope, why = resolve(n, check, worktree, args.files, args.tests,
                                  getattr(args, "extra", ()))
    if args.show:
        emit(args.json, "COMMAND", command)
        return OK
    path = output_file(ad, args.out, "test" if args.what == "test" else f"gate-{n}")
    warning = warning_text(Path(os.path.abspath(ad)), n, check, args.what, args.files,
                           args.tests, scope)
    if args.timeout is not None:
        timeout, timeout_why = args.timeout, "given with --timeout"
    else:
        timeout, timeout_why = default_timeout(ad, check)
    rec = {"pid": os.getpid(), "what": args.what, "check": n, "command": command,
           "output": str(path), "scope": scope, "why": why, "warning": warning,
           "tail": tail, "timeout": timeout, "timeout_why": timeout_why,
           "flagged": bool(args.files or args.tests), "attempt": None,
           "started": time.time()}
    try:
        record = claim_record(ad)
    except OSError:
        record = None
    keep(record, rec)
    try:
        code, seconds = execute(command, worktree, path, timeout)
    except BaseException as exc:
        keep(record, {**rec, "token": "ERROR", "exit": CANNOT_RUN,
                      "message": str(exc) or type(exc).__name__})
        raise
    if code is None:
        token, result = "TIMED_OUT", TIMED_OUT
        message = f"`{command}` ran past {timeout:g}s and was stopped"
    else:
        token, result = ("PASSED", OK) if code == 0 else ("FAILED", FAILED)
        message = f"`{command}` exited {code} in {seconds:g}s"
    rec.update(token=token, message=message, exit=result, exit_code=code, seconds=seconds)
    if args.what == "gate" and token in ("FAILED", "TIMED_OUT"):
        rec["attempt"] = failed_attempts(ad, n, record)
    keep(record, rec)
    return report(args, rec, tail)
