#!/usr/bin/env python3
"""Run the test suite with its test classes spread over several processes.

Usage: python3 tools/run-tests.py [-j N] [-v] [NAME ...]

Finds the tests the way `python3 -m unittest discover -s tests` does, then runs
each test class as its own `python3 -m unittest <module>.<Class>` process, N at
a time (default: the number of CPUs). The tests build their own temp repos and
set their own environment, so classes don't share state. Run from anywhere.

  -j N     run N classes at once (1 runs them one after another)
  -v       print every class's unittest output, not only a failing one's
  NAME     run only these modules or classes (`test_next`, `test_next.ShipTest`)

Each class prints one line when it finishes; a failing class's output follows
its line. The last line sums the tests run and the failures.

Exit codes: 0 every test passed (skips allowed), 1 a test failed or errored,
2 the tests could not be found or run.
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


def classes(names):
    """Each `module.Class` the discovery finds, limited to `names` when given,
    the ones with the most tests first, so the slow ones don't start last."""
    sys.path.insert(0, str(TESTS))
    suite = unittest.defaultTestLoader.discover(str(TESTS), top_level_dir=str(TESTS))
    found, count = [], {}

    def walk(s):
        for t in s:
            if isinstance(t, unittest.TestSuite):
                walk(t)
            elif type(t).__name__ == "_FailedTest":
                raise NotFound(f"a test module failed to import: {t.id()}")
            else:
                name = f"{type(t).__module__}.{type(t).__name__}"
                if name not in count:
                    found.append(name)
                count[name] = count.get(name, 0) + 1

    walk(suite)
    if names:
        found = [c for c in found
                 if any(c == n or c.startswith(n + ".") for n in names)]
    return sorted(found, key=lambda c: -count[c])


def run_class(name):
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(p for p in (str(TESTS), env.get("PYTHONPATH")) if p)
    start = time.monotonic()
    proc = subprocess.run([sys.executable, "-m", "unittest", name], cwd=ROOT, env=env,
                          capture_output=True, text=True, check=False)
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
        todo = classes(args.names)
    except NotFound as e:
        print(f"run-tests: {e}", file=sys.stderr)
        return 2
    if not todo:
        print("run-tests: no test classes found" +
              (f" for {', '.join(args.names)}" if args.names else ""), file=sys.stderr)
        return 2
    start, total, failed = time.monotonic(), 0, []
    with ThreadPoolExecutor(max_workers=max(1, args.j)) as pool:
        jobs = [pool.submit(run_class, c) for c in todo]
        for job in as_completed(jobs):
            name, code, ran, secs, out = job.result()
            total += ran
            ok = code == 0 and ran > 0
            print(f"{'ok  ' if ok else 'FAIL'} {name} ({ran} tests, {secs:.0f}s)", flush=True)
            if not ok:
                failed.append(name)
            if not ok or args.v:
                print(out.rstrip() + "\n", flush=True)
    secs = time.monotonic() - start
    if failed:
        print(f"FAILED: {len(failed)} of {len(todo)} classes ({total} tests, {secs:.0f}s): "
              + ", ".join(failed))
        return 1
    print(f"OK: {total} tests in {len(todo)} classes, {secs:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
