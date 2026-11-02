"""autodev.py run gate|test — run one of the profile's own commands in the
run's worktree, and save its output.

Usage:
    autodev.py run gate <n | REPORT> [--files <path> ...] [--dir <artifact-dir>]
                        [--out <file>] [--timeout <seconds>] [--tail <lines>] [--json]
    autodev.py run test [--files <path> ...] [--dir <artifact-dir>]
                        [--out <file>] [--timeout <seconds>] [--tail <lines>] [--json]

A worker's shell doesn't start in the worktree, and a permission check refuses
`cd <worktree> && <command>` and rewritten forms of it. This runs the command
the profile lists, exactly as written, with the worktree as its directory, so
a worker never composes one. It runs only the profile's commands (the `gate`
checks confirmed in Phase 1, from state.json), never a command it is given.

gate <n | REPORT>
    Runs the quality-gate check numbered <n> (1 is the first, as profile.md's
    table numbers them), or the one whose report is REPORT (`LINT.md` or
    `LINT`, any case).
test
    Runs the first `kind: test` check.
--files <path> ...
    Runs the check's scoped form instead: its `files` command, with `<files>`
    replaced by the paths given, quoted, relative to the worktree. Each must
    exist inside the worktree. A check with no `files` form can't be scoped:
    exit 2.

The command's whole output (stdout and stderr together) goes to --out, a file
under the artifact dir, or else to <artifact-dir>/tmp/run/<gate-<n>|test>-<k>.txt.
The script prints one token, then the command as run, the output file, the
time taken, and the output's last --tail lines (default 40):
    PASSED: `<command>` exited 0 in <s>s
    FAILED: `<command>` exited <code> in <s>s
    TIMED_OUT: `<command>` ran past <s>s and was stopped
With --json, `command`, `exit_code`, `seconds`, `output`, `lines` and `tail`.

Exit codes:
    0  PASSED
    1  FAILED: the command exited non-zero
    2  could not run (no state, no such check, no `files` form, a path outside
       the worktree or missing, --out outside the artifact dir) — `ERROR: …`
    3  TIMED_OUT: the command and everything it started were stopped
"""

import json
import os
import shlex
import signal
import subprocess
import time
from pathlib import Path

from . import state as st
from .output import CANNOT_RUN, FAILED, OK, Fail

TIMED_OUT = 3
PLACEHOLDER = "<files>"
TAIL = 40


def add_arguments(parser):
    parser.add_argument("what", choices=("gate", "test"))
    parser.add_argument("check", nargs="?",
                        help="gate: the check's number or its report name")
    parser.add_argument("--files", nargs="+", default=None,
                        help="run the check's scoped form on these paths")
    parser.add_argument("--dir", default=".auto-dev", help="the run's .auto-dev/")
    parser.add_argument("--out", help="the file to save the output to (under --dir)")
    parser.add_argument("--timeout", type=float, help="stop the command after this "
                                                      "many seconds (exit 3)")
    parser.add_argument("--tail", type=int, default=TAIL,
                        help="how many of the output's last lines to print")


def pick(gate, what, check):
    """(the check's number, the check) the arguments name."""
    if what == "test":
        if check:
            raise Fail("`run test` takes no check name; use `run gate <n>`",
                       CANNOT_RUN, "ERROR")
        for i, c in enumerate(gate, 1):
            if c.get("kind") == "test":
                return i, c
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
    names = ", ".join(str(c.get("report", "")) for c in gate) or "none"
    raise Fail(f"no gate check has the report {check!r} (reports: {names})",
               CANNOT_RUN, "ERROR")


def relative_paths(worktree, files):
    """Each path as the worktree-relative POSIX path the command is given."""
    root = worktree.resolve()
    out = []
    for name in files:
        path = Path(name)
        full = (path if path.is_absolute() else root / path).resolve()
        try:
            rel = full.relative_to(root)
        except ValueError:
            raise Fail(f"{name} is outside the worktree {root}", CANNOT_RUN,
                       "ERROR") from None
        if not full.exists():
            raise Fail(f"{name} does not exist in the worktree {root}", CANNOT_RUN,
                       "ERROR")
        out.append(rel.as_posix() or ".")
    return out


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
    quoted = " ".join(shlex.quote(p) for p in relative_paths(worktree, files))
    return form.replace(PLACEHOLDER, quoted)


def output_file(ad, out, label):
    """The file to save to: --out (inside the artifact dir), else the next free
    tmp/run/<label>-<k>.txt."""
    root = ad.resolve()
    if out:
        path = Path(out)
        path = (path if path.is_absolute() else Path.cwd() / path).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            raise Fail(f"--out {out} is outside the artifact dir {root}", CANNOT_RUN,
                       "ERROR") from None
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
    """Stop the command and everything it started."""
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            proc.kill()
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except OSError:
        pass
    proc.wait()


def execute(command, worktree, path, timeout):
    """(exit code or None on a timeout, seconds)."""
    start = time.monotonic()
    with open(path, "w", encoding="utf-8", errors="replace") as log:
        try:
            proc = subprocess.Popen(command, shell=True, cwd=worktree, stdout=log,
                                    stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                    start_new_session=(os.name != "nt"))
        except OSError as exc:
            raise Fail(f"could not start `{command}`: {exc}", CANNOT_RUN, "ERROR") from None
        try:
            code = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            code = None
        finally:
            stop(proc)
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
    command = command_for(n, check, worktree, args.files)
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
    if args.json:
        print(json.dumps({"result": token, "message": message, "command": command,
                          "exit_code": code, "seconds": seconds, "output": str(path),
                          "lines": len(lines), "tail": tail}, indent=2, sort_keys=True))
        return result
    print(f"{token}: {message}")
    print(f"  output: {path} ({len(lines)} lines)")
    if tail:
        shown = "all" if len(tail) == len(lines) else f"the last {len(tail)}"
        print(f"  {shown} of its lines:")
        for line in tail:
            print(f"    {line}")
    return result
