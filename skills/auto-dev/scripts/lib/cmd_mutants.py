"""autodev.py mutants select / record — which mutants a verifier re-check runs
again, and the record of each finished mutation pass.

Usage:
    autodev.py mutants select [--dir <artifact-dir>] [--json]
    autodev.py mutants record --tree <hash> [--dir <artifact-dir>] [--json]

The verifier keeps one fixed set of mutants across its passes
(`<artifact-dir>/evidence/mutation-set.json`). `record` saves, after each
finished pass, the tree that pass tested and every mutant's result there
(`evidence/mutation-record.json`). On a re-check, `select` compares the code
now with that tree and names the mutants to run again; every other one keeps
its earlier result ("carried forward"). Neither ever changes the worktree, its
index or its branch; `record` writes only under `evidence/`.

select
    Re-runs a mutant when it has no recorded result (new since the last pass),
    its recorded status was `survived` or `invalid`, its recorded file, find or
    replace differs from the set's, its file's content changed since the
    recorded tree, or its file is not in the tree now. A caught mutant
    (`killed` or `timeout`) in an unchanged file is carried forward; its line
    is never compared. Every mutant runs again when there is no usable record,
    the recorded tree is not a tree object in this repository, or a test
    changed in a way that can weaken what the tests catch: an existing line of
    a test file edited or removed (comments, blank lines and fixture data
    included), a test file deleted, renamed or replaced, a skip or focus marker
    added, or a test-runner config changed. A test file is one the audit
    (`check-tests.py`) recognizes, anything under a test directory, or an
    installed acceptance check. Lines only added to test files never force it.
    Prints one token:
      RERUN_ALL: <n> mutant(s); every one runs again
                 then `reason: <why>` and a `rerun:` line per mutant
      RERUN: <r> to re-run, <c> carried forward
                 then `rerun: <id> <file>:<line> — <why>` and
                 `carried: <id> <file>:<line> <status>` lines
      CARRY_ALL: nothing to re-run, <c> carried forward
                 then the `carried:` lines; run no mutant
    and ends with `base: <recorded tree>` (when there is one) and
    `tree: <tree now>`. With --json, `rerun` and `carried` are lists of
    objects and `reason` and `base` are null when unset.

record --tree <hash>
    <hash> is the tree noted at the start of the pass (`check-fresh.py
    --print-tree`). Repeats `select`'s choice, takes this run's results
    (`evidence/mutants.json.results.json`, from `mutate.py`) for the mutants it
    names and the earlier record's for the carried ones, and writes them with
    the tree now as the new record. A carried mutant that this run also ran,
    with the same file, find and replace, takes this run's result and counts as
    run. When nothing is named, no run file is read. A run that exited 8 (every
    mutant it ran was invalid) finished: its results are recorded.
    Prints one token:
      RECORDED: <n> result(s) at tree <hash>
                 then `summary: <N> mutants: <k> killed · <t> timeout ·
                 <s> survived · <i> invalid · <c> carried forward` (every
                 mutant in the set, once) and a `survived: <id> <file>:<line>`
                 line per survivor of this pass
      INCOMPLETE: <m> mutant(s) named to run have no result from this run;
                 nothing recorded — then a `missing: <id>` line each
      KEPT: nothing recorded; the earlier record stays (…) — <why>: the code
                 changed during the pass, the mutation run did not finish
                 (`evidence/mutate.exit` missing or not 0, 1 or 8), or this run's
                 results can't be read

Exit codes:
    0  select: a selection is printed; record: RECORDED
    1  record: INCOMPLETE — run the named mutants again in one run, then record
    2  could not run (no or unreadable mutation-set.json, not a git worktree,
       record without --tree) — `ERROR: …`; carry nothing forward
    3  record: KEPT — nothing recorded
"""

import json
import os
import posixpath
import re
import tempfile
from pathlib import Path

from . import proc, sealed, testfiles
from .cmd_checks import worktree_of
from .cmd_work import print_tree
from .output import CANNOT_RUN, Fail, emit

STATUSES = ("killed", "timeout", "survived", "invalid")
CAUGHT = {"killed", "timeout"}
HASH = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
HUNK = sealed.HUNK
FIELDS = ("id", "file", "line", "find", "replace", "condition", "status")

SET = "evidence/mutation-set.json"
RECORD = "evidence/mutation-record.json"
RESULTS = "evidence/mutants.json.results.json"
EXIT = "evidence/mutate.exit"

INCOMPLETE, KEPT = 1, 3
EVERY = "every mutant runs again"


def add_arguments(parser):
    parser.add_argument("action", choices=("select", "record"))
    parser.add_argument("--dir", default=".auto-dev", help="the run's .auto-dev/")
    parser.add_argument("--tree", help="record: the tree hash noted at the start of the pass")


def main(args):
    return select(args) if args.action == "select" else record(args)


def git(wt, *args, check=True):
    """(exit code, stdout, stderr) of git in `wt`. Pathspecs are literal, so a
    file named `*.ts` or `:(exclude)x` is never a pattern."""
    return proc.run(["git", "-C", str(wt), *args],
                    env={**os.environ, "GIT_LITERAL_PATHSPECS": "1"},
                    errors="surrogateescape", check=check)


def load_set(ad):
    path = Path(ad) / SET
    if not path.exists():
        raise Fail(f"{SET} does not exist; a first pass makes it", CANNOT_RUN, "ERROR")
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Fail(f"{SET} can't be read: {exc}", CANNOT_RUN, "ERROR") from None
    if not isinstance(entries, list):
        raise Fail(f"{SET} is not a JSON list", CANNOT_RUN, "ERROR")
    seen = set()
    for i, entry in enumerate(entries, 1):
        problem = None
        if not isinstance(entry, dict):
            problem = f"entry {i} is not an object"
        elif not isinstance(entry.get("id"), str) or not entry["id"]:
            problem = f"entry {i} has no id"
        else:
            for key in ("file", "find"):
                if not isinstance(entry.get(key), str) or not entry[key]:
                    problem = problem or f"entry {i} ({entry['id']}) has no {key}"
            if not isinstance(entry.get("replace"), str):
                problem = problem or f"entry {i} ({entry['id']}) has no string replace"
            if entry["id"] in seen:
                problem = problem or f"two entries for {entry['id']}"
            seen.add(entry["id"])
        if problem:
            raise Fail(f"{SET}: {problem}", CANNOT_RUN, "ERROR")
    return entries


def load_record(ad):
    """(record, problem): `problem` says why the record can't be used, else None."""
    path = Path(ad) / RECORD
    if not path.exists():
        return None, f"no previous results were recorded ({RECORD} does not exist)"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, one_line(f"{RECORD} can't be read: {exc}")
    what = None
    if not isinstance(data, dict):
        what = "it is not an object"
    elif not isinstance(data.get("results"), list):
        what = '"results" is not a list'
    else:
        seen = set()
        for i, r in enumerate(data["results"], 1):
            if not isinstance(r, dict):
                what = f"result {i} is not an object"
            elif not isinstance(r.get("id"), str) or not r["id"]:
                what = f"result {i} has no id"
            elif "status" not in r:
                what = f"result {i} ({r['id']}) has no status"
            elif r["status"] not in STATUSES:
                what = f"result {i} ({r['id']}) has status {r['status']!r}"
            elif r["id"] in seen:
                what = f"two results for {r['id']}"
            if what:
                break
            seen.add(r["id"])
    if what:
        return None, one_line(f"{RECORD} is unusable: {what}")
    return data, None


def one_line(text):
    return " ".join(str(text).split())


def is_tree(wt, value):
    """True when `value` is a hash naming a tree object in this repository. The
    pattern is checked first, so no other value ever reaches git."""
    if not isinstance(value, str) or not HASH.fullmatch(value):
        return False
    code, out, _ = git(wt, "cat-file", "-t", value, check=False)
    return code == 0 and out.strip() == "tree"


def changes(wt, old, new):
    """[(status letter, path)] of every file whose content differs between the
    two trees. A rename is a deletion and an addition."""
    _, out, _ = git(wt, "diff-tree", "-r", "--no-renames", "-z", "--name-status", old, new)
    parts = out.split("\0")
    return [(parts[i][:1], parts[i + 1]) for i in range(0, len(parts) - 1, 2)]


def patch(wt, old, new, path):
    """(first old line removed or changed, or None; [(new line, text)] added;
    whether git printed any hunk) for `path` between the two trees.

    A hunk whose only removed line is the old file's last line, which had no
    final newline, and whose first added line has the same text, is an
    insertion: lines were appended after that line, which only gained its
    newline."""
    _, out, _ = git(wt, "diff-tree", "-r", "-p", "-U0", "--no-renames", "--no-ext-diff",
                    "--no-textconv", "--no-color", old, new, "--", path)
    hunks = []
    for line in out.split("\n"):
        m = HUNK.match(line)
        if m:
            hunks.append({"start": int(m.group(1)),
                          "count": 1 if m.group(2) is None else int(m.group(2)),
                          "new": int(m.group(3)), "removed": [], "added": [], "eof": False})
            continue
        if not hunks:  # the file header comes before the first hunk
            continue
        hunk = hunks[-1]
        if line.startswith("-"):
            hunk["removed"].append(line[1:])
        elif line.startswith("+"):
            hunk["added"].append(line[1:])
        elif line.startswith("\\") and hunk["removed"] and not hunk["added"]:
            hunk["eof"] = True  # `\ No newline at end of file` after the old side
    removed, added = None, []
    for hunk in hunks:
        lines = list(enumerate(hunk["added"], hunk["new"]))
        if hunk["count"] == 1 and hunk["eof"] and lines \
                and lines[0][1] == hunk["removed"][0]:
            lines = lines[1:]  # the old last line, unchanged but for its newline
        elif hunk["count"] > 0 and removed is None:
            removed = hunk["start"]
        added.extend(lines)
    return removed, added, bool(hunks)


def test_cause(wt, ad, old, new, changed):
    """Why a test change forces every mutant to run, or None."""
    installed = set(sealed.sealed_files(ad))
    for status, path in changed:
        if testfiles.TEST_CONFIG.search(path):
            return f"{path} — a test-runner config file changed"
        if not (testfiles.is_test_file(path) or testfiles.under_test_dir(path)
                or path in installed):
            continue
        if status == "D":
            return f"{path} — a test file was deleted or renamed"
        if status == "T":
            return f"{path} — a test file was replaced by another kind of file"
        removed, added, has_hunk = patch(wt, old, new, path)
        if status != "A":
            if removed is not None:
                return f"{path}:{removed} — an existing test line was changed or removed"
            if not has_hunk:
                return f"{path} — an existing test file changed"
        for n, text in added:
            if testfiles.SKIP.search(testfiles.code(text)):
                return f"{path}:{n} — a skip or focus marker was added"
    return None


def every(sel, entries, reason, by_id):
    sel["reason"] = reason
    sel["rerun"] = [(e, EVERY, by_id.get(e["id"])) for e in entries]
    return sel


def compute(ad, wt, entries, now):
    """Which of `entries` run again (with why) and which are carried forward."""
    sel = {"tree": now, "base": None, "reason": None, "rerun": [], "carried": []}
    if not entries:
        return sel
    data, problem = load_record(ad)
    if problem:
        return every(sel, entries, problem, {})
    by_id = {r["id"]: r for r in data["results"]}
    old = data.get("tree")
    if not is_tree(wt, old):
        return every(sel, entries, f"the recorded tree {repr(old)[:80]} is not a tree "
                                   "in this repository", by_id)
    sel["base"] = old
    try:
        changed = changes(wt, old, now)
        cause = test_cause(wt, ad, old, now, changed)
        if not cause:
            _, listed, _ = git(wt, "ls-tree", "-r", "-z", "--name-only", now)
    except proc.CommandError as exc:
        err = [ln for ln in (exc.output or str(exc)).splitlines() if ln.strip()]
        return every(sel, entries, "could not compare the recorded tree with the tree now: "
                     + (err[-1].strip() if err else f"git exited {exc.code}"), by_id)
    if cause:
        return every(sel, entries, cause, by_id)
    present = {p for p in listed.split("\0") if p}
    touched = {path for _, path in changed}
    for entry in entries:
        f = posixpath.normpath(entry["file"])
        result = by_id.get(entry["id"])
        if result is None:
            why = "new since the last pass"
        elif result["status"] not in CAUGHT:
            why = f"{result['status']} last pass"
        elif tuple(result.get(k) for k in ("file", "find", "replace")) != \
                tuple(entry[k] for k in ("file", "find", "replace")):
            why = "its recorded file, find or replace differs from the set"
        elif f in touched:
            why = f"{entry['file']} changed since the last pass"
        elif f not in present:
            why = f"{entry['file']} is not in the tree now"
        else:
            sel["carried"].append((entry, result))
            continue
        sel["rerun"].append((entry, why, result))
    return sel


def where(entry, result):
    """The mutant's file and its latest known line: the recorded result's line
    when it is for the same file, else the set's."""
    line = entry.get("line")
    if result is not None and result.get("file") == entry["file"] and "line" in result:
        line = result["line"]
    return entry["file"], line


def shown(file, line):
    return f"{file}:{'?' if line is None else line}"


def select(args):
    ad, wt = Path(args.dir), worktree_of(args)
    entries = load_set(ad)
    now = print_tree(str(wt))
    sel = compute(ad, wt, entries, now)
    rerun, carried = [], []
    for entry, why, result in sel["rerun"]:
        file, line = where(entry, result)
        rerun.append({"id": entry["id"], "file": file, "line": line, "why": why})
    for entry, result in sel["carried"]:
        file, line = where(entry, result)
        carried.append({"id": entry["id"], "file": file, "line": line,
                        "status": result["status"]})
    if sel["reason"]:
        token, message = "RERUN_ALL", f"{len(rerun)} mutant(s); every one runs again"
    elif rerun:
        token, message = "RERUN", f"{len(rerun)} to re-run, {len(carried)} carried forward"
    else:
        token, message = "CARRY_ALL", f"nothing to re-run, {len(carried)} carried forward"
    if args.json:
        emit(True, token, message, reason=sel["reason"], rerun=rerun, carried=carried,
             base=sel["base"], tree=now)
    else:
        emit(False, token, message, reason=sel["reason"],
             rerun=[f"{m['id']} {shown(m['file'], m['line'])} — {m['why']}" for m in rerun],
             carried=[f"{m['id']} {shown(m['file'], m['line'])} {m['status']}"
                      for m in carried],
             base=sel["base"], tree=now)
    return 0


def kept(args, ad, why):
    data, _ = load_record(ad)
    if data is not None and isinstance(data.get("tree"), str):
        stays = f"tree {data['tree']}"
    elif (Path(ad) / RECORD).exists():
        stays = "it is unusable"
    else:
        stays = "there is none"
    emit(args.json, "KEPT", f"nothing recorded; the earlier record stays ({stays}) — {why}")
    return KEPT


def run_results(ad):
    """This run's results by id, or (None, why) when the run did not finish or
    its results can't be read."""
    try:
        code = (Path(ad) / EXIT).read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None, f"the mutation run did not finish ({EXIT} does not exist)"
    except (OSError, ValueError) as exc:
        return None, one_line(f"the mutation run did not finish ({EXIT} can't be read: {exc})")
    if code not in ("0", "1", "8"):  # 8: it finished, but every mutant was invalid
        return None, f"the mutation run did not finish ({EXIT} holds {one_line(code)[:40]!r})"
    try:
        results = json.loads((Path(ad) / RESULTS).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, one_line(f"this run's results can't be read: {exc}")
    if not isinstance(results, list):
        return None, f"this run's results can't be read: {RESULTS} is not a JSON list"
    return {r["id"]: r for r in results
            if isinstance(r, dict) and isinstance(r.get("id"), str)
            and r.get("status") in STATUSES}, None


def write_record(ad, body):
    evidence = Path(ad) / "evidence"
    fd, tmp = tempfile.mkstemp(dir=str(evidence), prefix=".mutation-record.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(body, f, indent=2)
            f.write("\n")
        os.replace(tmp, str(Path(ad) / RECORD))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def record(args):
    if not args.tree:
        raise Fail("mutants record needs --tree <the tree hash noted at the start of the pass>",
                   CANNOT_RUN, "ERROR")
    ad, wt = Path(args.dir), worktree_of(args)
    entries = load_set(ad)
    now = print_tree(str(wt))
    if args.tree != now:
        return kept(args, ad, f"the code changed during the pass (noted {args.tree}, "
                              f"now {now})")
    sel = compute(ad, wt, entries, now)
    need = [entry for entry, _, _ in sel["rerun"]]
    fresh = {}
    if need:
        fresh, why = run_results(ad)
        if fresh is None:
            return kept(args, ad, why)
        missing = [e["id"] for e in need if e["id"] not in fresh]
        if missing:
            emit(args.json, "INCOMPLETE", f"{len(missing)} mutant(s) named to run have no "
                 "result from this run; nothing recorded", missing=missing)
            return INCOMPLETE
    ran = [(entry, fresh[entry["id"]]) for entry in need]
    carried = []
    for entry, r in sel["carried"]:
        # A carried mutant this run ran too, at the same code, takes this run's result.
        mine = fresh.get(entry["id"])
        if mine is not None and all(mine.get(k) == entry[k] for k in ("file", "find", "replace")):
            ran.append((entry, mine))
        else:
            carried.append((entry, r))
    order = {e["id"]: i for i, e in enumerate(entries)}
    merged = sorted(ran + carried, key=lambda pair: order[pair[0]["id"]])
    results = [{k: r[k] for k in FIELDS if k in r} for _, r in merged]
    write_record(ad, {"tree": now, "results": results})
    counts = {s: sum(1 for r in results if r["status"] == s) for s in STATUSES}
    summary = (f"{len(results)} mutants: {counts['killed']} killed · {counts['timeout']} "
               f"timeout · {counts['survived']} survived · {counts['invalid']} invalid · "
               f"{len(carried)} carried forward")
    survived = [f"{entry['id']} {shown(r.get('file', entry['file']), r.get('line'))}"
                for entry, r in sorted(ran, key=lambda pair: order[pair[0]["id"]])
                if r["status"] == "survived"]
    emit(args.json, "RECORDED", f"{len(results)} result(s) at tree {now}", summary=summary,
         survived=survived)
    return 0
