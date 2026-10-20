#!/usr/bin/env python3
"""Run targeted mutants against a worktree: plant one small bug at a time in a
changed source line, run the tests, record whether they caught it, and put the
file back exactly as it was.

Run by the Phase 5 verifier (agents/verifier.md, the mutation step). The
verifier chooses the mutants; this script only applies,
runs and restores them, so the source is never left changed. A mutant the tests
do not catch ("survived") is a behavior no test pins down.

Usage:
    python3 <skill-dir>/scripts/mutate.py <worktree> --mutants <file.json> --cmd "<test command>"
                                          [--max <n>] [--timeout <sec>] [--out <results.json>]
    python3 <skill-dir>/scripts/mutate.py <worktree> --restore --mutants <file.json>
    python3 <skill-dir>/scripts/mutate.py --help

<skill-dir> is the auto-dev skill's own directory, not the target repo.
--mutants is a JSON list; each entry:
    {"id": "M1", "file": "lib/app/todos.ex", "line": 42,
     "find": "user_id == owner_id", "replace": "user_id != owner_id",
     "condition": "3", "cmd": "<optional per-mutant test command>"}
`file` is relative to <worktree> and must stay inside it. `line` is 1-based and
counts `\\n` only, as `grep -n` does. `find` must occur exactly once on that line;
only that occurrence is replaced, byte for byte — the rest of the file is never
re-encoded. --cmd runs through the shell in <worktree>, in its own process
group; a non-zero exit means the mutant was caught. It must pass on the
unmutated tree first (the baseline), and so must every per-mutant `cmd`, or
nothing is mutated. File permission bits are preserved. --max (default 50)
is the most mutants accepted; pass the run's mutation cap.

Each write (mutant and restore) moves the file's mtime forward, so mtime-based
build caches recompile it; a restored file has its original bytes and a newer
mtime.

Safety: before a file is mutated, its original is copied atomically to a backup
directory next to the mutants file (`<mutants file>.backup/`), with its SHA-256
recorded. It is restored byte-for-byte afterwards, on errors and SIGTERM/SIGINT
too, and the restore is checked against that hash. If a run is killed hard, the
next run refuses to start (exit 5) until `--restore` puts every backed-up file
back.

Output:
    stdout  one line per mutant: id, status, file:line, condition; then a summary
    stderr  `ERROR: …`
    --out   (default `<mutants file>.results.json`) the mutants with `status`
            and the tail of the test output for each

Statuses:
    killed    the test command failed with the mutant in place
    timeout   the test command ran past --timeout (its process group is
              killed); usually the mutant made the code hang — counted as caught
    survived  the test command passed with the mutant in place
    invalid   `find` is not exactly once on `line` — the mutant was not applied

Exit codes:
    0  no mutant survived (and at least one was applied)
    1  at least one mutant survived
    2  usage error or a malformed mutants file — fix the input
    3  baseline red: the test command fails on the unmutated tree
    4  a file could not be restored — the worktree is changed: stop and report
    5  leftover backups from a killed run — run `--restore` first
    6  interrupted by a signal; every file was restored
    7  an I/O error (e.g. disk full, unwritable backup dir); every file was
       restored — fix the cause, do not just retry
    8  every mutant was invalid, so nothing was tested — fix the mutants
    9  another run on the same mutants file is still alive (a lock file,
       `<mutants file>.lock`, holds its pid) — wait for it; never restore
       or start a second run over it
"""

import argparse
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time


class Interrupted(Exception):
    pass


def on_signal(signum, frame):
    raise Interrupted(f"signal {signum}")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def run(cmd, cwd, timeout):
    p = subprocess.Popen(cmd, shell=True, cwd=cwd, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, start_new_session=True)
    try:
        out, _ = p.communicate(timeout=timeout)
        return p.returncode, out.decode("utf-8", "replace")[-1500:]
    except subprocess.TimeoutExpired:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except OSError:
            pass
        p.communicate()
        return None, f"timed out after {timeout}s"
    except BaseException:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except OSError:
            pass
        raise


def mtime(path):
    try:
        return os.stat(path).st_mtime
    except OSError:
        return 0.0


def touch_forward(path, before):
    """Give the file an mtime past both now and `before` (its mtime before the
    write, taken by the caller: write_atomic resets it to now), so mtime-based
    build caches (bytecode, mix, make) see every write, even several within
    one second."""
    t = max(time.time(), before) + 1
    os.utime(path, (t, t))


def write_atomic(path, data, mode=None):
    """Write via a temp file and rename. Keeps the existing file's permission
    bits (mkstemp creates 0600), or applies `mode` when given."""
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    if mode is None:
        try:
            mode = os.stat(path).st_mode & 0o7777
        except OSError:
            mode = 0o644
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def inside(wt, rel):
    """The absolute path for `rel`, or None if it escapes the worktree."""
    if not isinstance(rel, str) or not rel or os.path.isabs(rel):
        return None
    path = os.path.realpath(os.path.join(wt, rel))
    return path if path.startswith(wt + os.sep) else None


def load_index(backup_dir):
    try:
        with open(os.path.join(backup_dir, "index.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_index(backup_dir, index):
    write_atomic(os.path.join(backup_dir, "index.json"),
                 json.dumps(index, indent=2).encode("utf-8"))


def restore_all(wt, backup_dir):
    """Put every backed-up file back, checked against its recorded hash.
    A file is overwritten only while it still holds the mutant (or is missing);
    if it already holds the original, the backup is just dropped; if it holds
    anything else, someone edited it after the run died, and it is left alone
    and reported. Returns the paths that could not be restored."""
    if not os.path.isdir(backup_dir):
        return []
    index = load_index(backup_dir)
    failed = []
    for rel, entry in list(index.items()):
        digest, mode = entry["sha256"], entry["mode"]
        src = os.path.join(backup_dir, "files", rel)
        dst = inside(wt, rel)
        try:
            with open(src, "rb") as f:
                data = f.read()
            if dst is None or sha(data) != digest:
                failed.append(rel)
                continue
            try:
                with open(dst, "rb") as f:
                    current = sha(f.read())
            except OSError:
                current = None
            if current == digest:
                del index[rel]
                save_index(backup_dir, index)
                continue
            if current is not None and current != entry.get("mutant_sha256"):
                print(f"ERROR: {rel} changed after the mutation run stopped — "
                      f"not overwriting it; the original is at {src}", file=sys.stderr)
                failed.append(rel)
                continue
            before = mtime(dst)
            write_atomic(dst, data, mode)
            touch_forward(dst, before)
            with open(dst, "rb") as f:
                if sha(f.read()) != digest:
                    failed.append(rel)
                    continue
            del index[rel]
            save_index(backup_dir, index)
        except OSError:
            failed.append(rel)
    if not failed:
        shutil.rmtree(backup_dir, ignore_errors=True)
    return failed


def pid_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def take_lock(lock_path):
    """Claim the run. Returns None on success, or the live owner's pid.
    A lock left by a dead process is stale and is taken over."""
    for _ in range(2):
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            with os.fdopen(fd, "w") as f:
                f.write(str(os.getpid()))
            return None
        except FileExistsError:
            try:
                with open(lock_path) as f:
                    owner = int(f.read().strip() or 0)
            except (OSError, ValueError):
                owner = 0
            if owner and owner != os.getpid() and pid_alive(owner):
                return owner
            try:
                os.remove(lock_path)
            except OSError:
                pass
    return -1


def validate(mutants):
    if not isinstance(mutants, list):
        return "not a JSON list"
    seen = set()
    for i, m in enumerate(mutants):
        if not isinstance(m, dict):
            return f"entry {i} is not an object"
        for k in ("id", "file", "find", "replace"):
            if not isinstance(m.get(k), str) or (k != "replace" and not m[k]):
                return f"entry {i}: `{k}` must be a non-empty string"
        if not isinstance(m.get("line"), int) or isinstance(m["line"], bool) or m["line"] < 1:
            return f"entry {i}: `line` must be a positive integer"
        if m["find"] == m["replace"]:
            return f"entry {i}: `replace` equals `find`"
        if m["id"] in seen:
            return f"entry {i}: duplicate id {m['id']}"
        seen.add(m["id"])
        if "cmd" in m and not isinstance(m["cmd"], str):
            return f"entry {i}: `cmd` must be a string"
    return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("worktree")
    parser.add_argument("--mutants", required=True)
    parser.add_argument("--cmd")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--max", type=int, default=50)
    parser.add_argument("--out")
    parser.add_argument("--restore", action="store_true")
    args = parser.parse_args()  # bad arguments exit 2 via argparse

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)

    wt = os.path.realpath(args.worktree)
    mutants_path = os.path.abspath(args.mutants)
    backup_dir = mutants_path + ".backup"
    out_path = args.out or mutants_path + ".results.json"

    lock_path = mutants_path + ".lock"
    owner = take_lock(lock_path)
    if owner:
        print(f"ERROR: another mutate.py run (pid {owner}) is using {mutants_path} — "
              f"wait for it to finish; do not restore or start another", file=sys.stderr)
        return 9
    try:
        return run_locked(args, wt, mutants_path, backup_dir, out_path)
    finally:
        try:
            os.remove(lock_path)
        except OSError:
            pass


def run_locked(args, wt, mutants_path, backup_dir, out_path):
    if args.restore:
        failed = restore_all(wt, backup_dir)
        if failed:
            print(f"ERROR: could not restore: {', '.join(failed)}", file=sys.stderr)
            return 4
        print("RESTORED: no backups left")
        return 0

    if os.path.isdir(backup_dir):
        print(f"ERROR: leftover backups in {backup_dir} — a run was killed mid-mutant. "
              f"Run with --restore first.", file=sys.stderr)
        return 5
    if not args.cmd:
        print("ERROR: --cmd is required", file=sys.stderr)
        return 2
    try:
        with open(mutants_path, encoding="utf-8") as f:
            mutants = json.load(f)
    except (OSError, ValueError) as e:
        print(f"ERROR: cannot read {mutants_path}: {e}", file=sys.stderr)
        return 2
    problem = validate(mutants)
    if problem:
        print(f"ERROR: {mutants_path}: {problem}", file=sys.stderr)
        return 2
    if len(mutants) > args.max:
        print(f"ERROR: {len(mutants)} mutants exceeds --max {args.max}", file=sys.stderr)
        return 2
    for m in mutants:
        if inside(wt, m["file"]) is None:
            print(f"ERROR: {m['id']}: `{m['file']}` is not inside the worktree", file=sys.stderr)
            return 2

    # Every command a mutant will run must pass on the unmutated tree, or a
    # failure would be read as the mutant being caught.
    cmds = [args.cmd] + sorted({m["cmd"] for m in mutants if m.get("cmd")} - {args.cmd})
    for cmd in cmds:
        try:
            code, tail = run(cmd, wt, args.timeout)
        except Interrupted:
            return 6
        if code != 0:
            print(f"ERROR: baseline is not green (each test command must pass unmutated): "
                  f"{cmd}\n{tail}", file=sys.stderr)
            return 3

    results = []
    index = {}
    try:
        for m in mutants:
            rec = dict(m)
            results.append(rec)
            path = inside(wt, m["file"])
            try:
                with open(path, "rb") as f:
                    original = f.read()
            except OSError as e:
                rec.update(status="invalid", output=f"cannot read: {e}")
                continue
            lines = original.split(b"\n")
            n = m["line"] - 1
            find, repl = m["find"].encode("utf-8"), m["replace"].encode("utf-8")
            if not (0 <= n < len(lines)) or lines[n].count(find) != 1:
                rec.update(status="invalid", output="`find` is not exactly once on that line")
                continue
            if not os.access(path, os.W_OK):
                rec.update(status="invalid", output="file is not writable")
                continue
            lines[n] = lines[n].replace(find, repl, 1)
            mutated = b"\n".join(lines)
            # Back up atomically and record the hash BEFORE touching the file.
            write_atomic(os.path.join(backup_dir, "files", m["file"]), original)
            mode = os.stat(path).st_mode & 0o7777
            index[m["file"]] = {"sha256": sha(original), "mode": mode,
                                "mutant_sha256": sha(mutated)}
            save_index(backup_dir, index)
            try:
                before = mtime(path)
                write_atomic(path, mutated)
                touch_forward(path, before)
                code, tail = run(m.get("cmd") or args.cmd, wt, args.timeout)
            finally:
                before = mtime(path)
                write_atomic(path, original, mode)
                touch_forward(path, before)
            with open(path, "rb") as f:
                if sha(f.read()) != index[m["file"]]["sha256"] or \
                        os.stat(path).st_mode & 0o7777 != mode:
                    raise OSError(f"restore mismatch: {m['file']}")
            del index[m["file"]]
            save_index(backup_dir, index)
            rec["status"] = "timeout" if code is None else ("survived" if code == 0 else "killed")
            rec["output"] = tail
    except (Interrupted, OSError) as e:
        failed = restore_all(wt, backup_dir)
        if failed:
            print(f"ERROR: stopped ({e}); could not restore: {', '.join(failed)}", file=sys.stderr)
            return 4
        print(f"ERROR: stopped ({e}); every file restored", file=sys.stderr)
        return 6 if isinstance(e, Interrupted) else 7
    shutil.rmtree(backup_dir, ignore_errors=True)

    write_atomic(out_path, json.dumps(results, indent=2).encode("utf-8"))
    counts = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
        print(f"{r['id']}\t{r['status']}\t{r['file']}:{r['line']}\t"
              f"condition {r.get('condition', '-')}")
    print("SUMMARY: " + ", ".join(f"{v} {k}" for k, v in sorted(counts.items()))
          + f" (results: {out_path})")
    if counts.get("survived"):
        return 1
    if not any(counts.get(k) for k in ("killed", "timeout")):
        print("ERROR: no mutant was applied (all invalid) — nothing was tested", file=sys.stderr)
        return 8
    return 0


if __name__ == "__main__":
    sys.exit(main())
