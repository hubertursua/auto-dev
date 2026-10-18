#!/usr/bin/env python3
"""Run targeted mutants against a worktree: plant one small bug at a time in a
changed source line, run the tests, record whether they caught it, and put the
file back exactly as it was.

Run by the Phase 5 verifier (references/subagent-prompts.md, _Verifier_, the
mutation step). The verifier chooses the mutants; this script only applies,
runs and restores them, so the source is never left changed. A mutant the tests
do not catch ("survived") is a behavior no test pins down.

Usage:
    python3 <skill-dir>/scripts/mutate.py <worktree> --mutants <file.json> --cmd "<test command>"
                                          [--timeout <sec>] [--max <n>] [--out <results.json>]
    python3 <skill-dir>/scripts/mutate.py <worktree> --restore --mutants <file.json>
    python3 <skill-dir>/scripts/mutate.py --help

<skill-dir> is the auto-dev skill's own directory, not the target repo.
--mutants is a JSON list; each entry:
    {"id": "M1", "file": "lib/app/todos.ex", "line": 42,
     "find": "user_id == owner_id", "replace": "user_id != owner_id",
     "condition": "3", "cmd": "<optional per-mutant test command>"}
`file` is relative to <worktree>; `find` must occur exactly once on `line`
(1-based), and only that occurrence is replaced. --cmd runs through the shell in
<worktree>; a non-zero exit means the mutant was caught. It must pass on the
unmutated tree first (the baseline), or nothing is mutated.

Each write (mutant and restore) moves the file's mtime forward a second, so
mtime-based build caches recompile it; a restored file has its original bytes
and a newer mtime.

Safety: before each mutant the original file is copied to a backup directory
next to the mutants file (`<mutants file>.backup/`), and restored byte-for-byte
afterwards, on errors and SIGTERM/SIGINT too. If a run is killed hard, the next
run refuses to start until `--restore` puts every backed-up file back.

Output:
    stdout  one line per mutant: id, status, file:line, condition; then a summary
    stderr  `ERROR: …`
    --out   (default `<mutants file>.results.json`) the mutants with `status`
            and the tail of the test output for each

Statuses:
    killed    the test command failed with the mutant in place
    survived  the test command passed with the mutant in place
    timeout   the test command ran past --timeout (counted as neither)
    invalid   `find` is not exactly once on `line` — the mutant was not applied

Exit codes:
    0  no mutant survived
    1  at least one mutant survived (or timed out)
    2  usage error, bad mutants file, baseline red, or leftover backups found
    4  a file could not be restored — the worktree is changed: stop and report
"""

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time


class Interrupted(Exception):
    pass


def on_signal(signum, frame):
    raise Interrupted(f"signal {signum}")


def run(cmd, cwd, timeout):
    try:
        r = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, timeout=timeout)
        out = (r.stdout + r.stderr).decode("utf-8", "replace")
        return r.returncode, out[-1500:]
    except subprocess.TimeoutExpired:
        return None, f"timed out after {timeout}s"


def touch_forward(path, after):
    """Give the file an mtime past `after`, so mtime-based build caches
    (compiled bytecode, mix, make) see the write even within one second."""
    t = max(time.time(), after) + 1
    os.utime(path, (t, t))
    return t


def restore_all(wt, backup_dir):
    """Put every backed-up file back. Returns the paths that failed."""
    failed = []
    if not os.path.isdir(backup_dir):
        return failed
    for dirpath, _, names in os.walk(backup_dir):
        for n in names:
            src = os.path.join(dirpath, n)
            rel = os.path.relpath(src, backup_dir)
            try:
                shutil.copyfile(src, os.path.join(wt, rel))
                os.remove(src)
            except OSError:
                failed.append(rel)
    if not failed:
        shutil.rmtree(backup_dir, ignore_errors=True)
    return failed


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("worktree")
    parser.add_argument("--mutants", required=True)
    parser.add_argument("--cmd")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--max", type=int, default=25)
    parser.add_argument("--out")
    parser.add_argument("--restore", action="store_true")
    args = parser.parse_args()  # bad arguments exit 2 via argparse

    wt = os.path.abspath(args.worktree)
    mutants_path = os.path.abspath(args.mutants)
    backup_dir = mutants_path + ".backup"
    out_path = args.out or mutants_path + ".results.json"

    if args.restore:
        failed = restore_all(wt, backup_dir)
        if failed:
            print(f"ERROR: could not restore: {', '.join(failed)}", file=sys.stderr)
            return 4
        print("RESTORED: no backups left")
        return 0

    if os.path.isdir(backup_dir) and any(files for _, _, files in os.walk(backup_dir)):
        print(f"ERROR: leftover backups in {backup_dir} — a run was killed mid-mutant. "
              f"Run with --restore first.", file=sys.stderr)
        return 2
    if not args.cmd:
        print("ERROR: --cmd is required", file=sys.stderr)
        return 2
    try:
        with open(mutants_path, encoding="utf-8") as f:
            mutants = json.load(f)
        assert isinstance(mutants, list)
        for m in mutants:
            assert {"id", "file", "line", "find", "replace"} <= set(m)
    except (OSError, ValueError, AssertionError):
        print(f"ERROR: {mutants_path} is not a JSON list of mutants with "
              f"id, file, line, find, replace", file=sys.stderr)
        return 2
    if len(mutants) > args.max:
        print(f"ERROR: {len(mutants)} mutants exceeds --max {args.max}", file=sys.stderr)
        return 2

    code, tail = run(args.cmd, wt, args.timeout)
    if code != 0:
        print(f"ERROR: baseline is not green (the test command must pass unmutated):\n{tail}",
              file=sys.stderr)
        return 2

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    results = []
    try:
        for m in mutants:
            rec = dict(m)
            path = os.path.join(wt, m["file"])
            try:
                with open(path, "rb") as f:
                    original = f.read()
            except OSError:
                rec.update(status="invalid", output="file not found")
                results.append(rec)
                continue
            lines = original.decode("utf-8", "replace").splitlines(keepends=True)
            n = int(m["line"]) - 1
            if not (0 <= n < len(lines)) or lines[n].count(m["find"]) != 1:
                rec.update(status="invalid", output="`find` is not exactly once on that line")
                results.append(rec)
                continue
            lines[n] = lines[n].replace(m["find"], m["replace"], 1)
            backup = os.path.join(backup_dir, m["file"])
            os.makedirs(os.path.dirname(backup), exist_ok=True)
            shutil.copyfile(path, backup)
            stamp = os.stat(path).st_mtime
            try:
                with open(path, "wb") as f:
                    f.write("".join(lines).encode("utf-8"))
                stamp = touch_forward(path, stamp)
                code, tail = run(m.get("cmd") or args.cmd, wt, args.timeout)
            finally:
                shutil.copyfile(backup, path)
                touch_forward(path, stamp)
                with open(path, "rb") as f:
                    if f.read() != original:
                        raise OSError(f"restore mismatch: {m['file']}")
                os.remove(backup)
            rec["status"] = "timeout" if code is None else ("survived" if code == 0 else "killed")
            rec["output"] = tail
            results.append(rec)
    except (Interrupted, OSError) as e:
        failed = restore_all(wt, backup_dir)
        print(f"ERROR: stopped ({e}); "
              + (f"could not restore: {', '.join(failed)}" if failed else "every file restored"),
              file=sys.stderr)
        return 4 if failed or isinstance(e, OSError) else 2
    shutil.rmtree(backup_dir, ignore_errors=True)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    counts = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
        print(f"{r['id']}\t{r['status']}\t{r['file']}:{r['line']}\tcondition {r.get('condition', '-')}")
    print("SUMMARY: " + ", ".join(f"{v} {k}" for k, v in sorted(counts.items()))
          + f" (results: {out_path})")
    return 1 if counts.get("survived") or counts.get("timeout") else 0


if __name__ == "__main__":
    sys.exit(main())
