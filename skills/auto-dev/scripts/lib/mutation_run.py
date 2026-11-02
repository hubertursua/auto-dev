"""The verifier's mutation run, as a script: `autodev.py mutants run` and
`mutants wait` (lib/cmd_mutants.py). The rules are agents/verifier.md's step 7
as of 4.19, now in code.

`run` resolves the scoped command, takes the runner lock and starts a
detached runner (`autodev.py _mutants-runner <dir>`), then waits for it up to
--wait seconds; `wait` waits again. The runner, in order:
  1. deletes this pass's stale files (mutate.exit, mutate.log, the results);
  2. with --new-set or --extended, saves `git diff <cut>` as
     evidence/mutation-base.diff, and saves the scoped command to
     evidence/mutation-cmd.txt;
  3. with mutants to run, sizes the run by one cold run (a pass that chose the
     set always measures; a kept set reuses evidence/mutation-cold-run.txt
     when it holds a number above 0), the timeout 3 x that, and runs mutate.py
     with each changed file's state saved before and compared after;
  4. re-times once a pass when the timeout was likely too short (the baseline
     timed out; more than half the applied mutants timed out; a survivor of
     the last finished pass timed out; or, with a reused value, a mutant timed
     out that the last finished pass did not record as `timeout`), and
     re-runs with the larger of 3 x the new value and 2 x the old timeout;
     runs mutate.py again after leftover backups (exit 5, restored first), an
     interruption (exit 6), or another run still alive (exit 9, waited for);
  5. runs `mutants record --tree <evidence/tree-start.txt>`; an all-invalid
     run is recorded only when it is the pass's second.
It ends only once no backup or mutate.py lock is left, or with LEFT_CHANGES,
and writes evidence/mutation-run.json, `{"id", "token", "message", "lines"}`.
evidence/mutation-pass.json keeps what one pass may do only once (a re-time,
the first all-invalid run); `verify prep` deletes it.
"""

import hashlib
import json
import math
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

from . import cmd_init, cmd_work
from . import state as st
from .output import CANNOT_RUN, Fail

SCRIPTS = Path(__file__).resolve().parent.parent
EV = "evidence"
FILES = {"exit": "mutate.exit", "log": "mutate.log", "results": "mutants.json.results.json",
         "mutants": "mutants.json", "cold": "mutation-cold-run.txt",
         "base": "mutation-base.diff", "cmd": "mutation-cmd.txt",
         "args": "mutation-run-args.json", "result": "mutation-run.json",
         "lock": "mutation-run.lock", "runner": "mutation-run.log",
         "pass": "mutation-pass.json", "coldlog": "mutation-cold.log"}
COLD_CAP = 600      # a cold run past this is no basis for sizing mutants
WAIT = 270
POLL = 2
YOUNG = 30          # seconds a lock without a pid yet counts as a runner starting
LIVE_CAP = 4 * 3600  # the longest the runner waits on another live mutate.py run
TIMED_OUT = re.compile(r"timed out after \d+(\.\d+)?s")

# Tokens `run` and `wait` print, and their exit codes.
CODES = {"DONE": 0, "INCOMPLETE": 1, "RUNNING": 3, "LEFT_CHANGES": 4, "FAILING": 5,
         "NOT_RUN": 6, "MALFORMED": 7, "ALL_INVALID": 8, "KEPT": 9, "BUSY": 10,
         "NOT_STARTED": 2}


class Outcome(Exception):
    """The runner's result: a token, a message and lines."""

    def __init__(self, token, message, lines=()):
        super().__init__(message)
        self.token, self.message, self.lines = token, message, list(lines)


def ev(ad, key):
    return Path(ad) / EV / FILES[key]


def mutate_lock(ad):
    return Path(f"{ev(ad, 'mutants')}.lock")


def mutate_backup(ad):
    return Path(f"{ev(ad, 'mutants')}.backup")


# ---------------------------------------------------------------- the runner lock

def runner_alive(ad):
    """Whether a runner holds the lock: its pid is alive, or it was taken so
    recently that the pid isn't written yet."""
    path = ev(ad, "lock")
    try:
        text = path.read_text().strip()
        age = time.time() - path.stat().st_mtime
    except OSError:
        return False
    if not text.isdigit():
        return age < YOUNG
    return cmd_init.runner_alive(int(text))


def take_lock(ad):
    """Create the runner lock, or return False while a runner holds it."""
    path = ev(ad, "lock")
    for _ in range(2):
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            os.close(fd)
            return True
        except FileExistsError:
            if runner_alive(ad):
                return False
            path.unlink(missing_ok=True)  # a dead runner's
    return False


# ---------------------------------------------------------------- per-pass state

def pass_state(ad):
    try:
        data = json.loads(ev(ad, "pass").read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def note_pass(ad, **values):
    data = {**pass_state(ad), **values}
    ev(ad, "pass").write_text(json.dumps(data), encoding="utf-8")


# ---------------------------------------------------------------- helpers

def git(wt, *args):
    done = subprocess.run(["git", "-C", str(wt), *args], capture_output=True,
                          env={**os.environ, "GIT_LITERAL_PATHSPECS": "1"}, check=False)
    if done.returncode != 0:
        raise Fail(f"git {' '.join(args)} exited {done.returncode}: "
                   f"{done.stderr.decode('utf-8', 'replace').strip()}", CANNOT_RUN, "ERROR")
    return done.stdout


def snapshot(wt, cut):
    """{path: (status, content hash)} for every path the change set or `git
    status` names, renames as their two paths, so any file a run writes, edits
    or deletes is named, an untracked one included."""
    status = {}
    for entry in git(wt, "status", "--porcelain", "-z", "--no-renames",
                     "--untracked-files=all").split(b"\0"):
        if len(entry) > 3:
            status[os.fsdecode(entry[3:])] = entry[:2].decode("utf-8", "replace")
    names = {os.fsdecode(n) for n in git(wt, "diff", "--name-only", "--no-renames", "-z",
                                         cut).split(b"\0") if n}
    return {name: (status.get(name, ""), path_state(Path(wt) / name))
            for name in sorted(names | set(status))}


def path_state(path):
    """A path's mode and content (a symlink's target, as git sees it), hashed in
    chunks so a big file is never read whole."""
    try:
        info = os.lstat(path)
        if os.path.islink(path):
            return f"link {os.readlink(path)}"
        if not os.path.isfile(path):
            return f"{info.st_mode:o}"
        digest = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                digest.update(chunk)
        return f"{info.st_mode:o} {digest.hexdigest()}"
    except OSError:
        return "missing"


def touch_forward(path):
    """Move a file's mtime past now, so a build cache rebuilds it."""
    try:
        later = max(time.time(), os.stat(path).st_mtime) + 1
        os.utime(path, (later, later))
    except OSError:
        pass


def cold_run(ad, wt, command, mutants):
    """(seconds rounded up, at least 1, None, []) or (None, FAILING | NOT_RUN,
    why, the output's tail)."""
    from . import cmd_run
    if mutants:
        touch_forward(Path(wt) / mutants[0]["file"])
    log = ev(ad, "coldlog")
    code, seconds = cmd_run.execute(command, wt, log, COLD_CAP)
    if code == 0:
        return max(1, math.ceil(seconds)), None, None, []
    tail = log.read_text(encoding="utf-8", errors="replace").splitlines()[-20:]
    if code is None:
        return None, "NOT_RUN", f"the cold run of `{command}` ran past {COLD_CAP}s", tail
    return None, "FAILING", f"`{command}` fails on the unmutated code (exit {code})", tail


def saved_cold(ad):
    try:
        value = float(ev(ad, "cold").read_text().strip())
    except (OSError, ValueError):
        return None
    return value if value > 0 and math.isfinite(value) else None


def write_cold(ad, value):
    text = f"{value:g}" if value != int(value) else str(int(value))
    ev(ad, "cold").write_text(text + "\n", encoding="utf-8")


def run_mutate(ad, wt, command, cap, timeout):
    """mutate.py's exit code (None when it wrote no exit file)."""
    discard(ad)
    with open(ev(ad, "log"), "w", encoding="utf-8") as log:
        subprocess.run([sys.executable, str(SCRIPTS / "mutate.py"), str(wt), "--mutants",
                        str(ev(ad, "mutants")), "--max", str(cap), "--timeout",
                        str(timeout), "--cmd", command, "--exit-file", str(ev(ad, "exit"))],
                       stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                       check=False)
    try:
        return int(ev(ad, "exit").read_text().strip())
    except (OSError, ValueError):
        return None


def restore(ad, wt):
    """mutate.py --restore's exit code and output lines."""
    done = subprocess.run([sys.executable, str(SCRIPTS / "mutate.py"), str(wt), "--restore",
                           "--mutants", str(ev(ad, "mutants"))], capture_output=True,
                          text=True, check=False)
    return done.returncode, (done.stdout + done.stderr).strip().splitlines()


def restore_left(ad, wt, deadline=None):
    """Put back whatever a mutate.py run left, waiting while one is alive (until
    `deadline`, if given; LIVE_CAP at most). None when the tree holds no
    mutant, else an Outcome (LEFT_CHANGES, or RUNNING when `deadline` passed)."""
    cap = time.monotonic() + LIVE_CAP
    while mutate_backup(ad).exists() or mutate_lock(ad).exists():
        rc, lines = restore(ad, wt)
        if rc == 0:
            return None
        if rc == 4:
            return Outcome("LEFT_CHANGES", "mutate.py --restore could not put a file back",
                           lines)
        if rc != 9:
            return Outcome("LEFT_CHANGES", f"mutate.py --restore exited {rc}: the tree may "
                           "hold a mutant", lines)
        if deadline is not None and time.monotonic() >= deadline:
            return Outcome("RUNNING", "a mutate.py run is still alive")
        if time.monotonic() >= cap:
            return Outcome("LEFT_CHANGES", f"a mutate.py run has held {mutate_lock(ad)} "
                           f"for over {LIVE_CAP // 3600} hours: check that pid, then run "
                           f"`python3 {SCRIPTS / 'mutate.py'} {wt} --restore --mutants "
                           f"{ev(ad, 'mutants')}`", lines)
        time.sleep(POLL)
    return None


def results(ad):
    try:
        data = json.loads(ev(ad, "results").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return data if isinstance(data, list) else []


def last_record(ad):
    """{mutant id: status} the last finished pass recorded."""
    from .cmd_mutants import load_record
    data, problem = load_record(ad)
    return {} if problem else {r["id"]: r["status"] for r in data["results"]}


def baseline_timed_out(ad):
    """Whether mutate.py's baseline error ends `timed out after <n>s`."""
    try:
        lines = ev(ad, "log").read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return False
    last = next((ln.strip() for ln in reversed(lines) if ln.strip()), "")
    return bool(TIMED_OUT.fullmatch(last))


def retime_reason(ad, res, measured, code):
    """Why the timeout was likely too short, or None."""
    if code == 3:
        return ("the unmutated scoped command ran past the timeout"
                if baseline_timed_out(ad) else None)
    applied = [r for r in res if r.get("status") in ("killed", "timeout", "survived")]
    timed = [r for r in applied if r.get("status") == "timeout"]
    if applied and len(timed) * 2 > len(applied):
        return f"{len(timed)} of {len(applied)} applied mutants timed out"
    before = last_record(ad)
    for r in timed:
        if before.get(r["id"]) == "survived":
            return f"{r['id']}, a survivor of the last pass, timed out"
        if not measured and before.get(r["id"]) != "timeout":
            return f"{r['id']} timed out, which the last pass did not record"
    return None


def log_tail(ad, n=20):
    try:
        return ev(ad, "log").read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
    except OSError:
        return []


def discard(ad):
    for key in ("exit", "log", "results"):
        ev(ad, key).unlink(missing_ok=True)


# ---------------------------------------------------------------- the pass

class Stop:
    """A SIGTERM asks the runner to stop between steps, never mid-restore."""
    asked = False

    @classmethod
    def handler(cls, _signum, _frame):
        cls.asked = True

    @classmethod
    def check(cls):
        if cls.asked:
            raise Outcome("NOT_RUN", "the mutation runner was stopped by a signal")


def mutate_until_done(ad, wt, command, cap, timeout):
    """Run mutate.py; again once after leftover backups (5) or an interruption
    (6, or no exit file); after another live run (9), wait for it and run
    again. The last exit code."""
    again = set()
    while True:
        Stop.check()
        code = run_mutate(ad, wt, command, cap, timeout)
        if code == 9:
            left = restore_left(ad, wt)  # waits while that run is alive
            if left:
                raise left
            continue
        if code in (5, 6, None) and code not in again:
            again.add(code)
            left = restore_left(ad, wt)
            if left:
                raise left
            continue
        return code


def run_pass(ad, wt, state, opts):
    """Steps 1-4; returns (notes, mutate.py's exit) or raises Outcome."""
    cut = cmd_work.cut_commit(str(wt), state["repo"]["base"])
    discard(ad)
    if opts["new_set"] or opts["extended"]:
        ev(ad, "base").write_bytes(git(wt, "diff", "--no-color", "--no-ext-diff", cut))
    command = opts["command"]
    ev(ad, "cmd").write_text(command + "\n", encoding="utf-8")
    try:
        mutants = json.loads(ev(ad, "mutants").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Outcome("MALFORMED", f"{FILES['mutants']} can't be read: {exc}") from None
    if not isinstance(mutants, list):
        raise Outcome("MALFORMED", f"{FILES['mutants']} is not a JSON list")
    if not mutants:
        return ["no mutant to run: every result is carried forward"], None
    cap = int(state["settings"].get("mutation_max", 20))
    notes = []
    value = None if opts["new_set"] else saved_cold(ad)
    measured = value is None
    if measured:
        value, kind, why, tail = cold_run(ad, wt, command, mutants)
        if value is None:
            raise Outcome(kind, why, tail)
        write_cold(ad, value)
        notes.append(f"cold run: {value}s, measured")
    else:
        notes.append(f"cold run: {value:g}s, saved by an earlier pass")
    timeout = 3 * math.ceil(value)
    before = snapshot(wt, cut)
    code = mutate_until_done(ad, wt, command, cap, timeout)
    while code in (0, 1, 3) and not pass_state(ad).get("retimed"):
        why = retime_reason(ad, results(ad), measured, code)
        if not why:
            break
        note_pass(ad, retimed=why)
        discard(ad)
        Stop.check()
        new, kind, fail, tail = cold_run(ad, wt, command, mutants)
        if new is None:
            raise Outcome(kind, f"re-timing ({why}): {fail}", tail)
        timeout = max(3 * new, 2 * timeout)
        write_cold(ad, timeout / 3)
        notes.append(f"re-timed once ({why}): timeout now {timeout}s")
        code = mutate_until_done(ad, wt, command, cap, timeout)
    if code == 3:
        if baseline_timed_out(ad) and pass_state(ad).get("retimed"):
            raise Outcome("NOT_RUN", "the unmutated scoped command ran past the timeout "
                          "after this pass's re-time", log_tail(ad))
        raise Outcome("FAILING", "the scoped tests fail on the unmutated code", log_tail(ad))
    if code == 2:
        raise Outcome("MALFORMED", "mutate.py refused mutants.json", log_tail(ad))
    if code in (6, None):
        raise Outcome("NOT_RUN", "the mutation run was interrupted twice", log_tail(ad))
    if code == 7:
        raise Outcome("NOT_RUN", "an I/O error stopped the mutation run (every file was "
                      "restored); fix the cause", log_tail(ad))
    if code not in (0, 1, 8):
        left = restore_left(ad, wt)
        if left:
            raise left
        raise Outcome("NOT_RUN", f"mutate.py exited {code}; every file is restored",
                      log_tail(ad))
    after = snapshot(wt, cut)
    if after != before:
        changed = sorted(p for p in set(after) | set(before) if after.get(p) != before.get(p))
        raise Outcome("LEFT_CHANGES", "the tree changed during the mutation run (the test "
                      "command may have written files)", changed)
    return notes, code


def record_pass(ad, tree):
    done = subprocess.run([sys.executable, str(SCRIPTS / "autodev.py"), "mutants", "record",
                           "--dir", str(ad), "--tree", tree], capture_output=True,
                          text=True, check=False)
    return done.returncode, (done.stdout + done.stderr).strip().splitlines()


def finish(ad, tree, notes, code):
    """Record the pass; the result dict."""
    if code == 8 and not pass_state(ad).get("all_invalid"):
        note_pass(ad, all_invalid=True)
        return {"token": "ALL_INVALID", "message": "every mutant was invalid (lines moved "
                "or `find` text wrong); nothing is recorded yet", "lines": log_tail(ad)}
    rc, lines = record_pass(ad, tree)
    if rc == 0:
        token = "ALL_INVALID" if code == 8 else "DONE"
        message = ("every mutant was invalid again; the pass is recorded" if code == 8
                   else "the mutation pass is recorded")
    elif rc == 1:
        token, message = "INCOMPLETE", "some mutants named to run have no result"
    elif rc == 3:
        token, message = "KEPT", "nothing was recorded"
    else:
        token, message = "KEPT", f"`mutants record` could not run (exit {rc})"
    return {"token": token, "message": message, "lines": notes + lines}


def runner(ad):
    """The detached runner: run the pass, record it, write the result file."""
    ad = Path(ad)
    for name in ("SIGINT", "SIGHUP"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), signal.SIG_IGN)
    signal.signal(signal.SIGTERM, Stop.handler)
    ev(ad, "lock").write_text(f"{os.getpid()}\n", encoding="utf-8")
    result = {"token": "NOT_RUN", "message": "the runner stopped unexpectedly", "lines": []}
    opts, wt = {}, None
    try:
        state = st.load(ad)
        wt = Path(state["worktree"])
        opts = json.loads(ev(ad, "args").read_text(encoding="utf-8"))
        tree = (ad / EV / "tree-start.txt").read_text(encoding="utf-8").strip()
        try:
            notes, code = run_pass(ad, wt, state, opts)
            result = finish(ad, tree, notes, code)
        except Outcome as out:
            result = {"token": out.token, "message": out.message, "lines": out.lines}
            if out.token in ("FAILING", "NOT_RUN"):
                discard(ad)
                _rc, lines = record_pass(ad, tree)  # prints KEPT: nothing recorded
                result["lines"] += lines
    except Fail as exc:
        result = {"token": "NOT_RUN", "message": str(exc), "lines": []}
    except Exception as exc:  # record it, whatever it is
        result = {"token": "NOT_RUN", "message": f"{type(exc).__name__}: {exc}", "lines": []}
    finally:
        if wt is not None and result.get("token") != "LEFT_CHANGES":
            left = restore_left(ad, wt)  # never end with a mutant in the tree
            if left:
                result = {"token": left.token, "message": left.message,
                          "lines": left.lines}
        result["id"] = opts.get("id")
        tmp = ev(ad, "result").with_suffix(".tmp")
        tmp.write_text(json.dumps(result), encoding="utf-8")
        os.replace(tmp, ev(ad, "result"))
        try:  # only its own: a lock taken over since is another runner's
            if ev(ad, "lock").read_text().strip() == str(os.getpid()):
                ev(ad, "lock").unlink()
        except OSError:
            pass


# ---------------------------------------------------------------- run and wait

def start(ad, opts):
    """Start the detached runner on `opts`; False while another runner holds
    the lock."""
    if not take_lock(ad):
        return False
    opts = {**opts, "id": f"{time.time_ns()}-{os.getpid()}"}
    ev(ad, "result").unlink(missing_ok=True)
    ev(ad, "args").write_text(json.dumps(opts), encoding="utf-8")
    try:
        with open(ev(ad, "runner"), "w", encoding="utf-8") as log:
            subprocess.Popen([sys.executable, str(SCRIPTS / "autodev.py"), "_mutants-runner",
                              str(ad)], stdout=log, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        ev(ad, "lock").unlink(missing_ok=True)
        raise
    return True


def current_id(ad):
    try:
        return json.loads(ev(ad, "args").read_text(encoding="utf-8")).get("id")
    except (OSError, ValueError, AttributeError):
        return None


def read_result(ad):
    """This run's result (its id matches the run started last), else None."""
    try:
        data = json.loads(ev(ad, "result").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("id") == current_id(ad) else None


def wait_for(ad, seconds):
    """The runner's result, or None while it still runs after `seconds`."""
    deadline = time.monotonic() + seconds
    while True:
        result = read_result(ad)
        if result:
            return result
        if not runner_alive(ad):
            time.sleep(0.2)  # it may have written the file as it ended
            result = read_result(ad)
            if result:
                return result
            if current_id(ad) is None:
                return {"token": "NOT_STARTED", "message": "no mutation run was started this "
                        "pass; run `mutants run`", "lines": []}
            return ended_without_result(ad, deadline)
        if time.monotonic() >= deadline:
            return None
        time.sleep(POLL)


def ended_without_result(ad, deadline):
    """The runner died without a result: put back what its mutate.py left."""
    try:
        wt = Path(st.load(ad)["worktree"])
    except st.StateError as exc:
        raise Fail(str(exc), CANNOT_RUN, "ERROR") from None
    left = restore_left(ad, wt, deadline)
    if left and left.token == "RUNNING":
        return None
    if left:
        return {"token": left.token, "message": left.message, "lines": left.lines}
    return {"token": "NOT_RUN", "message": "the mutation runner ended without a result "
            f"(its log: {ev(ad, 'runner')}); no mutant is left in the tree", "lines": []}
