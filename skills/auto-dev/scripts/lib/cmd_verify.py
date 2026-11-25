"""autodev.py verify prep|tree — the verifier's routine steps, as one command each.

Usage:
    autodev.py verify prep --dir <artifact-dir>
                           [--wait <seconds>] [--json]
    autodev.py verify tree --dir <artifact-dir> [--json]

The verifier (agents/verifier.md; Phase 6, on the draft PR) runs `prep` first
on every pass and `tree` once its runs are done. Both write only under <artifact-dir>/ and to the
worktree's index (intent-to-add, as the verifier's own diff would).

prep
    In order, stopping at the first that fails:
    1. An earlier pass's mutation run still going (`mutants run`'s runner, or
       mutate.py) is waited for, up to --wait seconds (default 170); then a
       backup or lock it left (evidence/mutants.json.backup, .lock) is put
       back with `mutate.py --restore`. The earlier pass's mutation-run.json,
       mutation-run-args.json and mutation-pass.json are deleted.
    2. The audit of the build's test changes (`check-tests.py --base <cut>
       --tests-commit <sha> …`, every tests commit in state.json, so a changed
       or removed line of the committed acceptance checks is a finding), saved
       to evidence/integrity.txt with its exit code on the first line. The
       checks are in the worktree already: nothing is installed.
    3. The code's tree hash (`check-fresh.py --print-tree`), saved to
       evidence/tree-start.txt.
    4. The change set: untracked files are marked intent-to-add, and `git diff
       <cut>` is saved to evidence/changes.diff.
    5. The acceptance run: the profile's test check (the first `kind: test`
       check with a `files` form, else the first; `autodev.py run test`),
       scoped to the files that hold the checks when it has a `files` form,
       saved to evidence/acceptance.txt. It runs in the background (a
       detached runner, `autodev.py _verify-runner`, which saves its result
       to evidence/acceptance-run.json) and is stopped at `run`'s default
       timeout: twice the check's newest measured whole run, at least 600 s.
       Prep waits for it until 170 s after prep started, all its waits
       counted; a run still going then is RUN_AGAIN. The next prep call
       picks up that same run instead of starting another, when the code's
       tree is the one it started on (or, in the same verifier spawn, the one
       the run itself left, as a run that writes files does); else it waits
       for that run to end and starts a fresh one. A run is used once, and
       never before it ended.
       A whole run that finished saves its time to tmp/run/timings.json, for
       `autodev.py run`'s default timeout.
    6. For each PLAN.md condition with acceptance checks, evidence/C<n>.txt:
       Expected, Command and Result lines and the lines of the run's output
       that name the condition's checks (its last 30 lines when none does). A
       line that names several checks goes to the longest name it holds.
       The verifier adds a group for each run of its own after it.
    Prints one token, then `key: value` lines:
      PREPARED: <what ran> — then `tree:`, `integrity:`, `changes:`,
                 `acceptance:`, a `warning:` line when the run finished and no
                 line of its output names any check MANIFEST.md lists,
                 `evidence:` and one `unnamed:` line per check MANIFEST.md
                 lists that no line of the run's output names
      MUTATION_LEFT_CHANGES: `mutate.py --restore` could not put a file back
                 — its output follows
      STILL_RUNNING: an earlier mutation run is still alive after --wait
                 seconds; run prep again
      RUN_AGAIN: the acceptance run is still going, in the background, 170 s
                 after prep started; run prep again, which waits on that run
Every prep call returns within about 170 s, under the 180 s after which the
Bash tool moves a call to the background.
tree
    Compares the tree hash now with evidence/tree-start.txt.
      TREE: <hash> — the code is as it was when prep ran: write this hash on
                 the Tree line
      TREE_CHANGED: <first> → <now> — the code changed during the pass: write
                 `Tree: changed during the run`; `changed:` lines name the files

Exit codes:
    0  PREPARED, or TREE
    1  TREE_CHANGED
    2  could not run (no state, no MANIFEST.md, git or a script failing) —
       `ERROR: …`, never a pass
    3  STILL_RUNNING or RUN_AGAIN
    4  MUTATION_LEFT_CHANGES
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from . import artifacts as art
from . import cmd_init, cmd_run, cmd_work, mutation_run
from . import state as st
from .output import CANNOT_RUN, FAILED, OK, Fail, emit

STILL_RUNNING, LEFT_CHANGES = 3, 4
SCRIPTS = Path(__file__).resolve().parent.parent
# The Bash tool moves a call still running after 180 s to the background, and
# the verifier must never poll one: one prep call waits at most BUDGET seconds
# in all, the wait for a mutation run (at most WAIT) included.
WAIT = BUDGET = 170
POLL = 5
RUN_POLL = 0.5  # the acceptance run: most end in a second or two
YOUNG = 30  # seconds a run whose pid isn't saved yet counts as starting
TAIL = 30
PREP_FILES = ("integrity.txt", "tree-start.txt", "changes.diff", "acceptance.txt")
# The background acceptance run: what it runs (and its pid), its result, its log.
RUN_FILES = {"args": "acceptance-run-args.json", "result": "acceptance-run.json",
             "log": "acceptance-run.log"}
EXPECTED = "the tests written before the code to pass"


def add_arguments(parser):
    parser.add_argument("action", choices=("prep", "tree"))
    parser.add_argument("--dir", required=True, help="the run's .auto-dev/")
    parser.add_argument("--budget", type=int, default=BUDGET, help=argparse.SUPPRESS)
    parser.add_argument("--timeout", type=int, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--wait", type=int, default=WAIT,
                        help="prep: seconds to wait for a live mutation run")


def main(args):
    return prep(args) if args.action == "prep" else tree(args)


def script(name, *args, cwd=None):
    done = subprocess.run([sys.executable, str(SCRIPTS / name), *map(str, args)],
                          capture_output=True, text=True, cwd=cwd, check=False)
    return done.returncode, done.stdout, done.stderr


def git(wt, *args, check=True):
    done = subprocess.run(["git", "-C", str(wt), *args], capture_output=True,
                          env={**os.environ, "GIT_LITERAL_PATHSPECS": "1"},
                          check=False)
    if check and done.returncode != 0:
        raise Fail(f"git {' '.join(args)} exited {done.returncode}: "
                   f"{done.stderr.decode('utf-8', 'replace').strip()}", CANNOT_RUN, "ERROR")
    return done.stdout


def restore(ad, wt, wait):
    """None when nothing is left over, else (token, exit code, message, lines)."""
    evidence = ad / "evidence"
    mutants = evidence / "mutants.json"
    backup, lock = Path(f"{mutants}.backup"), Path(f"{mutants}.lock")
    deadline = time.monotonic() + wait
    # An earlier pass's mutation runner (`mutants run`) may still be going.
    while mutation_run.runner_alive(ad):
        if time.monotonic() >= deadline:
            return ("STILL_RUNNING", STILL_RUNNING,
                    (f"an earlier mutation run is still alive after {wait}s; run "
                     "`verify prep` again"), [])
        time.sleep(POLL)
    for key in ("result", "args", "pass"):  # an earlier pass's, never this one's
        mutation_run.ev(ad, key).unlink(missing_ok=True)
    if not backup.exists() and not lock.exists():
        return None
    while True:
        code, out, err = script("mutate.py", wt, "--restore", "--mutants", mutants)
        if code == 0:
            return None
        if code == 4:
            return ("MUTATION_LEFT_CHANGES", LEFT_CHANGES,
                    "mutate.py --restore could not put a file back",
                    (out + err).strip().splitlines())
        if code != 9:
            raise Fail(f"mutate.py --restore exited {code}: {(err or out).strip()}",
                       CANNOT_RUN, "ERROR")
        if time.monotonic() >= deadline:
            return ("STILL_RUNNING", STILL_RUNNING,
                    (f"an earlier mutation run is still alive after {wait}s; run "
                     "`verify prep` again"), [])
        while lock.exists() and time.monotonic() < deadline:
            time.sleep(POLL)


def audit(ad, wt, cut, state):
    shas = [c["sha"] for c in state.get("tests_commits") or []]
    args = [a for sha in shas for a in ("--tests-commit", sha)]
    code, out, err = script("check-tests.py", wt, "--base", cut, *args)
    (ad / "evidence" / "integrity.txt").write_text(
        f"check-tests.py exit {code}\n{out}{err}", encoding="utf-8")
    return code


def change_set(ad, wt, cut):
    """Mark untracked files intent-to-add, save `git diff <cut>`; (lines, files)."""
    untracked = [p for p in git(wt, "ls-files", "-z", "--others",
                                "--exclude-standard").split(b"\0") if p]
    for i in range(0, len(untracked), 200):
        git(wt, "add", "-N", "--", *[os.fsdecode(p) for p in untracked[i:i + 200]])
    diff = git(wt, "diff", "--no-color", "--no-ext-diff", cut)
    (ad / "evidence" / "changes.diff").write_bytes(diff)
    names = [n for n in git(wt, "diff", "--no-ext-diff", "--name-only", "-z", cut)
             .split(b"\0") if n]
    return diff.count(b"\n"), len(names)


def check_names(rows):
    """{condition id: [test name]} from MANIFEST.md's check rows."""
    names = {}
    for row in rows:
        cell = row["Check (path :: test name)"]
        name = cell.split("::", 1)[-1].strip().strip('"').strip("`").strip()
        names.setdefault(row["#"].strip(), []).append(name)
    return names


def line_owners(lines, names):
    """{line index: {(check name, condition id)}}: each output line goes to the
    checks whose name it holds, less a name that is only part of a longer one
    it holds, so `keeps the date` never takes the line of `keeps the date when
    edited`, while a line naming two unrelated checks goes to both."""
    pairs = [(name, cid) for cid, ns in names.items() for name in ns if name]
    owners = {}
    for i, line in enumerate(lines):
        found = [(name, cid) for name, cid in pairs if name in line]
        kept = {(n, c) for n, c in found
                if not any(n != m and n in m for m, _ in found)}
        if kept:
            owners[i] = kept
    return owners


def acceptance_command(ad, wt, state):
    """(the acceptance run's command, the test check, whether it has a scoped
    form, whether the run is scoped: it has one and MANIFEST.md names files)."""
    gate = state["settings"].get("gate", [])
    n, check = cmd_run.pick(gate, "test", None)
    files = cmd_work.check_files(ad)
    form = cmd_run.PLACEHOLDER in str(check.get("files") or "")
    scoped = form and bool(files)
    command = cmd_run.command_for(n, check, wt, files if scoped else None)
    return command, check, form, scoped


def run_file(ad, key):
    return ad / "evidence" / RUN_FILES[key]


def read_json(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write_json(path, data):
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, path)


def pending_run(ad):
    """The background acceptance run not yet used (its args), or None."""
    opts = read_json(run_file(ad, "args"))
    return opts if opts and opts.get("id") else None


def run_result(ad, opts):
    """The result of the run `opts` started, or None while it has none."""
    result = read_json(run_file(ad, "result"))
    return result if result and result.get("id") == opts["id"] else None


def run_alive(opts, proc=None):
    if proc is not None or opts.get("pid"):
        return cmd_init.runner_alive(opts.get("pid"), proc)
    return time.time() - float(opts.get("started") or 0) < YOUNG


def spawn_id(ad):
    """The current verifier spawn: its brief's name and mtime (a brief is
    written for each spawn), or None when there is none."""
    try:
        found = [(b.stat().st_mtime_ns, b.name) for b in (ad / "briefs").glob("verifier-*.md")]
    except OSError:
        return None
    return "{1}@{0}".format(*max(found)) if found else None


def discard(ad):
    for key in ("args", "result"):
        run_file(ad, key).unlink(missing_ok=True)


def start_run(ad, wt, command, tree, timeout, scoped):
    """Start the detached acceptance runner; (its args, its process)."""
    discard(ad)
    (ad / "evidence" / "acceptance.txt").unlink(missing_ok=True)
    opts = {"id": f"{time.time_ns()}-{os.getpid()}", "command": command,
            "worktree": str(wt), "tree": tree, "timeout": timeout, "scoped": scoped,
            "spawn": spawn_id(ad), "started": time.time()}
    write_json(run_file(ad, "args"), opts)
    try:
        with open(run_file(ad, "log"), "w", encoding="utf-8") as log:
            proc = subprocess.Popen([sys.executable, str(SCRIPTS / "autodev.py"),
                                     "_verify-runner", str(ad)], stdout=log,
                                    stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                    start_new_session=True)
    except OSError as exc:
        discard(ad)
        raise Fail(f"could not start the acceptance run: {exc}", CANNOT_RUN,
                   "ERROR") from None
    opts["pid"] = proc.pid
    write_json(run_file(ad, "args"), opts)
    return opts, proc


def wait_run(ad, opts, deadline, proc=None):
    """The run's result; None while it is still going at `deadline`."""
    while True:
        result = run_result(ad, opts)
        if result:
            return result
        if not run_alive(opts, proc):
            time.sleep(0.2)  # it may have written its result as it ended
            return run_result(ad, opts) or {
                "id": opts["id"], "error": "the acceptance run ended without a result "
                f"(its log: {run_file(ad, 'log')})"}
        left = deadline - time.monotonic()
        if left <= 0:
            return None
        time.sleep(min(RUN_POLL, left))


def runner(ad):
    """The detached acceptance runner: run the command, save its result."""
    ad = Path(ad)
    for name in ("SIGINT", "SIGHUP"):  # ignored, so `execute` leaves them ignored
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), signal.SIG_IGN)
    opts, result = {}, {"error": "the acceptance runner stopped unexpectedly"}
    try:
        opts = read_json(run_file(ad, "args")) or {}
        wt = opts["worktree"]
        code, seconds = cmd_run.execute(opts["command"], wt, ad / "evidence" /
                                        "acceptance.txt", opts["timeout"])
        result = {"code": code, "seconds": seconds}
        try:  # the tree it left: a run that writes files is still used
            result["tree_end"] = cmd_work.print_tree(wt)
        except Fail:
            pass
    except Exception as exc:  # record it, whatever it is
        result = {"error": str(exc) or type(exc).__name__}
    finally:
        result["id"] = opts.get("id")
        write_json(run_file(ad, "result"), result)


def usable(ad, wt, opts, result, command, tree):
    """Whether a pending run's result holds for the code now: it ran the same
    command and finished, on this tree, or, in this same verifier spawn (which
    never edits the code), it left this tree, as a run that writes files does."""
    if "error" in result or opts.get("command") != command:
        return False
    if tree == opts.get("tree"):
        return True
    spawn = opts.get("spawn")
    if not spawn or spawn != spawn_id(ad) or not result.get("tree_end"):
        return False
    return result["tree_end"] in (tree, cmd_work.print_tree(str(wt)))


def acceptance_run(ad, wt, state, tree, deadline, timeout):
    """The acceptance run: the pending one when it ran on this code, else a
    new one. (command, exit code or None on a timeout, seconds, output lines,
    whether the check has a scoped form, the tree it ran on, its timeout), or
    None while it still runs."""
    command, check, form, scoped = acceptance_command(ad, wt, state)
    if timeout is None:
        timeout = cmd_run.default_timeout(ad, check)[0]
    opts, result = pending_run(ad), None
    if opts:
        result = wait_run(ad, opts, deadline)
        if result is None:
            return None
        if not usable(ad, wt, opts, result, command, tree):
            opts = result = None
    if not opts:
        opts, proc = start_run(ad, wt, command, tree, timeout, scoped)
        result = wait_run(ad, opts, deadline, proc)
        if result is None:
            return None
        if "error" in result:
            discard(ad)
            raise Fail(result["error"], CANNOT_RUN, "ERROR")
    discard(ad)  # a run is used once
    code, seconds = result.get("code"), result.get("seconds") or 0
    if code is not None and not opts.get("scoped"):  # a whole run that finished
        cmd_run.save_timing(ad, opts["command"], seconds, "verify prep")
    path = ad / "evidence" / "acceptance.txt"
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return (opts["command"], code, seconds, lines, form, opts.get("tree") or tree,
            opts.get("timeout") or timeout)


def ran(code, budget):
    if code is None:
        return f"ran past {budget}s and was stopped"
    return "passed" if code == 0 else f"exited {code}"


def write_evidence(ad, conditions, names, command, code, lines, owners, budget):
    """evidence/C<n>.txt for each condition with acceptance checks; the ids."""
    written = []
    for cond in conditions:
        cid = cond["id"]
        if cid not in names:
            continue
        hits = [lines[i] for i, who in sorted(owners.items())
                if any(c == cid for _, c in who)]
        output = hits[-TAIL:] if hits else lines[-TAIL:]
        failed = " (any failing check fails it)" if code not in (0, None) else ""
        result = f"the run {ran(code, budget)}{failed}" + (
            "; the lines naming this condition's checks are below" if hits else
            "; no line of its output names this condition's checks, so its last "
            "lines are below")
        text = "\n".join([f"Expected: {EXPECTED}", f"Command: {command}",
                          f"Result: {result}", "Output (last lines):", *output])
        (ad / "evidence" / f"C{cid}.txt").write_text(text + "\n", encoding="utf-8")
        written.append(f"C{cid}.txt")
    return written


def prep(args):
    ad = Path(args.dir)
    state = st.load(ad)
    wt = Path(state["worktree"])
    evidence = ad / "evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    deadline = started + args.budget
    opts = pending_run(ad)
    going = opts is not None and run_result(ad, opts) is None and run_alive(opts)
    for name in PREP_FILES:  # an earlier pass's, never read as this one's
        if not (going and name == "acceptance.txt"):  # a live run writes it
            (evidence / name).unlink(missing_ok=True)
    left = restore(ad, wt, max(0, min(args.wait, args.budget)))
    if left:
        token, code, message, lines = left
        emit(args.json, token, message, output=lines)
        return code
    cut = cmd_work.cut_commit(str(wt), state["repo"]["base"])
    audit_code = audit(ad, wt, cut, state)
    tree_hash = cmd_work.print_tree(str(wt))
    (evidence / "tree-start.txt").write_text(tree_hash + "\n", encoding="utf-8")
    diff_lines, diff_files = change_set(ad, wt, cut)
    rows, _na = art.manifest(ad / "acceptance" / "MANIFEST.md")
    names = check_names(rows)
    run = acceptance_run(ad, wt, state, tree_hash, deadline, args.timeout)
    if run is None:
        opts = pending_run(ad) or {}
        took = time.time() - float(opts.get("started") or time.time())
        emit(args.json, "RUN_AGAIN", f"the acceptance run `{opts.get('command')}` is "
             f"still going after {took:.0f}s, in the background; run `verify prep` "
             "again, which waits on that same run",
             output=str(evidence / "acceptance.txt"))
        return STILL_RUNNING
    command, code, seconds, lines, form, tree_hash, timeout = run
    # The tree the run checked, which `verify tree` compares with.
    (evidence / "tree-start.txt").write_text(tree_hash + "\n", encoding="utf-8")
    conditions = art.spec_conditions(ad / "PLAN.md")
    owners = line_owners(lines, names)
    written = write_evidence(ad, conditions, names, command, code, lines, owners, timeout)
    named = {pair for who in owners.values() for pair in who}
    unnamed = [f"{cid}: {name}" for cid, ns in names.items() for name in ns
               if name and (name, cid) not in named]
    listed = sum(1 for ns in names.values() for name in ns if name)
    warning = (f"the acceptance run's output names none of the {listed} checks "
               f"MANIFEST.md lists, so `{command}` may not run them: run them yourself"
               if code is not None and listed and len(unnamed) == listed else None)
    how = ran(code, timeout)
    emit(args.json, "PREPARED",
         f"audit exit {audit_code}, acceptance run {how}",
         tree=tree_hash, cut=cut,
         integrity=f"{evidence / 'integrity.txt'} (check-tests.py exit {audit_code})",
         changes=f"{evidence / 'changes.diff'} ({diff_lines} lines, {diff_files} files)",
         acceptance=(f"{evidence / 'acceptance.txt'} — `{command}` {how}"
                     + (f" in {seconds:g}s" if code is not None else "")
                     + ("" if form else " (the whole suite: the test check has no "
                                          "scoped form)")),
         warning=warning, evidence=", ".join(written) or "none", unnamed=unnamed)
    return OK


def tree(args):
    ad = Path(args.dir)
    state = st.load(ad)
    wt = Path(state["worktree"])
    start = ad / "evidence" / "tree-start.txt"
    try:
        first = start.read_text(encoding="utf-8").strip()
    except OSError:
        raise Fail(f"{start} does not exist: run `verify prep` first", CANNOT_RUN,
                   "ERROR") from None
    now = cmd_work.print_tree(str(wt))
    if now == first:
        emit(args.json, "TREE", now)
        return OK
    changed = [os.fsdecode(n) for n in
               git(wt, "diff", "--name-only", "-z", first, now).split(b"\0") if n]
    emit(args.json, "TREE_CHANGED", f"{first} → {now}", changed=changed)
    return FAILED
