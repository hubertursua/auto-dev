#!/usr/bin/env python3
"""Run the test suite with its test classes spread over several processes.

Usage: python3 tools/run-tests.py [-j N] [-v] [NAME ...]

Finds the tests the way `python3 -m unittest discover -s tests` does, then runs
each test class as its own `python3 -m unittest <module>.<Class>` process, N at
a time (default: the number of CPUs). The tests build their own temp repos and
set their own environment, so classes don't share state. Run from anywhere.

  -j N     run N classes at once (1 runs them one after another)
  -v       print every class's unittest output, not only a failing one's
  NAME     run only these modules, classes or tests (`test_next`,
           `test_next.ShipTest`, `tests.test_next.ShipTest.test_x`)

Each class prints one line when it finishes; a failing class's output follows
its line. The last line sums the tests run and the failures.

Exit codes: 0 every test passed (skips allowed), 1 a test failed or errored,
2 the tests could not be found or run, or the run was interrupted.
"""

import argparse
import os
import re
import subprocess
import sys
import time
import unittest
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"
RAN_RE = re.compile(r"^Ran (\d+) tests? in", re.MULTILINE)


class NotFound(Exception):
    pass


def targets(names):
    """What to run, one process each: every `module.Class` the discovery finds,
    the ones with the most tests first, so the slow ones don't start last.
    With `names`, only the modules, classes or single tests they name."""
    sys.path.insert(0, str(TESTS))
    suite = unittest.defaultTestLoader.discover(str(TESTS), top_level_dir=str(TESTS))
    found, count = [], {}

    def walk(s):
        for t in s:
            if isinstance(t, unittest.TestSuite):
                walk(t)
            elif type(t).__name__ == "_FailedTest":
                why = getattr(t, "_exception", None)
                raise NotFound(f"a test module failed to import: {t.id()}"
                               + (f": {why}" if why else ""))
            else:
                name = f"{type(t).__module__}.{type(t).__name__}"
                if name not in count:
                    found.append(name)
                count[name] = count.get(name, 0) + 1

    walk(suite)
    found.sort(key=lambda c: -count[c])
    if not names:
        return found
    names = [n[len("tests."):] if n.startswith("tests.") else n for n in names]
    picked = []
    for c in found:
        single = [n for n in names if n.startswith(c + ".")]
        if single:
            picked += single
        elif any(c == n or c.startswith(n + ".") for n in names):
            picked.append(c)
    return picked


def run_one(name):
    """(name, exit code or None when it could not start, tests run, seconds, output)."""
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(p for p in (str(TESTS), env.get("PYTHONPATH")) if p)
    start = time.monotonic()
    try:
        proc = subprocess.run([sys.executable, "-m", "unittest", name], cwd=ROOT, env=env,
                              capture_output=True, text=True, errors="replace", check=False)
    except OSError as e:
        return name, None, 0, time.monotonic() - start, f"could not start: {e}"
    ran = RAN_RE.search(proc.stderr)
    return name, proc.returncode, int(ran.group(1)) if ran else 0, \
        time.monotonic() - start, proc.stderr + proc.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("-j", type=int, default=os.cpu_count() or 1)
    parser.add_argument("-v", action="store_true")
    parser.add_argument("names", nargs="*")
    args = parser.parse_args()
    try:
        todo = targets(args.names)
    except NotFound as e:
        print(f"run-tests: {e}", file=sys.stderr)
        return 2
    if not todo:
        print("run-tests: no test classes found" +
              (f" for {', '.join(args.names)}" if args.names else ""), file=sys.stderr)
        return 2
    start, total, failed, unrun = time.monotonic(), 0, [], []
    pool = ThreadPoolExecutor(max_workers=max(1, args.j))
    try:
        jobs = [pool.submit(run_one, c) for c in todo]
        for job in as_completed(jobs):
            name, code, ran, secs, out = job.result()
            total += ran
            ok = code == 0  # a class that skips itself whole runs 0 tests
            print(f"{'ok  ' if ok else 'FAIL'} {name} ({ran} tests, {secs:.0f}s)", flush=True)
            if not ok:
                (unrun if code is None else failed).append(name)
            if not ok or args.v:
                print(out.rstrip() + "\n", flush=True)
    except KeyboardInterrupt:
        # The running tests got the same interrupt; start no more.
        pool.shutdown(wait=False, cancel_futures=True)
        print("run-tests: interrupted", file=sys.stderr)
        return 2
    pool.shutdown()
    secs = time.monotonic() - start
    if failed or unrun:
        print(f"FAILED: {len(failed) + len(unrun)} of {len(todo)} classes ({total} tests, "
              f"{secs:.0f}s): " + ", ".join(failed + unrun))
        return 1 if failed else 2
    print(f"OK: {total} tests in {len(todo)} classes, {secs:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
