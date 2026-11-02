"""autodev.py verify prep|tree — the verifier's routine steps, as one command each.

Usage:
    autodev.py verify prep --dir <artifact-dir> [--pass <first pass | re-check>]
                           [--wait <seconds>] [--json]
    autodev.py verify tree --dir <artifact-dir> [--json]

The Phase 5 verifier (agents/verifier.md) runs `prep` first on every pass and
`tree` once its runs are done. Both write only under <artifact-dir>/ and to the
worktree's index (intent-to-add, as the verifier's own diff would).

prep
    In order, stopping at the first that fails:
    1. An earlier pass's mutation run that left a backup or a lock
       (evidence/mutants.json.backup, .lock) is put back with `mutate.py
       --restore`. A run still alive is waited for, up to --wait seconds
       (default 270), then restored.
    2. The sealed acceptance checks: on a re-check (`--pass re-check`), or a
       first pass whose checks went in before cleanup (acceptance/INSTALLED),
       the audit runs first and then `install-checks --recheck` puts back any
       check edited since; otherwise the checks are installed and then
       audited. A path
       where a check can't go in writes evidence/corrections.md, one entry per
       path. The audit (`check-tests.py --base <cut> --acceptance …`) is saved
       to evidence/integrity.txt with its exit code on the first line.
    3. The code's tree hash (`check-fresh.py --print-tree`), saved to
       evidence/tree-start.txt.
    4. The change set: untracked files are marked intent-to-add, and `git diff
       <cut>` is saved to evidence/changes.diff.
    5. The acceptance run: the profile's test command, scoped to the files that
       hold the checks when the test check has a `files` form (`autodev.py run
       test`), saved to evidence/acceptance.txt with the command on its first
       line.
    6. For each SPEC.md condition with acceptance checks, evidence/C<n>.txt:
       Expected, Command and Result lines and the lines of the run's output
       that name the condition's checks (its last 30 lines when none does).
       The verifier adds a group for each run of its own after it.
    Prints one token, then `key: value` lines:
      PREPARED: <what ran> — then `tree:`, `integrity:`, `changes:`,
                 `acceptance:`, `evidence:` and one `unnamed:` line per check
                 MANIFEST.md lists that no line of the run's output names
      INSTALL_CONFLICT: <n> path(s) where a check can't go in — `conflict:`
                 lines; evidence/corrections.md names them
      MUTATION_LEFT_CHANGES: `mutate.py --restore` could not put a file back
                 — its output follows
      STILL_RUNNING: an earlier mutation run is still alive after --wait
                 seconds; run prep again
tree
    Compares the tree hash now with evidence/tree-start.txt.
      TREE: <hash> — the code is as it was when prep ran: write this hash on
                 the Tree line
      TREE_CHANGED: <first> → <now> — the code changed during the pass: write
                 `Tree: changed during the run`; `changed:` lines name the files

Exit codes:
    0  PREPARED, or TREE
    1  INSTALL_CONFLICT, or TREE_CHANGED
    2  could not run (no state, no sealed checks, git or a script failing) —
       `ERROR: …`, never a pass
    3  STILL_RUNNING
    4  MUTATION_LEFT_CHANGES
"""

import os
import subprocess
import sys
import time
from pathlib import Path

from . import artifacts as art
from . import cmd_checks, cmd_run, sealed
from . import state as st
from .output import CANNOT_RUN, FAILED, OK, Fail, emit

STILL_RUNNING, LEFT_CHANGES = 3, 4
SCRIPTS = Path(__file__).resolve().parent.parent
WAIT = 270
POLL = 5
TAIL = 30
CONFLICT_ENTRY = ("`{path}`: a held-out acceptance check goes into this file and can't "
                  "be merged with the change to it; if the change deleted, moved or "
                  "recreated the file, put it back, and undo any rewrite of its "
                  "existing lines the task doesn't need")
PREP_FILES = ("integrity.txt", "tree-start.txt", "changes.diff", "acceptance.txt")
EXPECTED = "the tests written before the code, for this condition, pass"


def add_arguments(parser):
    parser.add_argument("action", choices=("prep", "tree"))
    parser.add_argument("--dir", required=True, help="the run's .auto-dev/")
    parser.add_argument("--pass", dest="pass_", default="first pass",
                        help="prep: the brief's mode (`first pass` or `re-check`)")
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
    if not backup.exists() and not lock.exists():
        return None
    deadline = time.monotonic() + wait
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


def write_conflicts(ad, paths):
    lines = ["# Required changes"]
    for i, path in enumerate(paths, 1):
        lines += [f"{i}. {CONFLICT_ENTRY.format(path=path)}",
                  f"   Where: `{path}` — the file the check goes into",
                  "   Now: the held-out check can't be put into the file as it is now",
                  "   Test: none to add — the held-out check is the test"]
    path = ad / "evidence" / "corrections.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def audit(ad, wt, cut):
    code, out, err = script("check-tests.py", wt, "--base", cut, "--acceptance",
                            ad / "acceptance")
    (ad / "evidence" / "integrity.txt").write_text(
        f"check-tests.py exit {code}\n{out}{err}", encoding="utf-8")
    return code


def install(ad, wt, cut, recheck):
    """(audit exit, conflicts). A re-check, or a first pass whose checks went in
    before cleanup (acceptance/INSTALLED), audits first, so the audit records an
    edit before `--recheck` undoes it."""
    if recheck or (ad / "acceptance" / "INSTALLED").exists():
        code = audit(ad, wt, cut)
        _written, conflicts = cmd_checks.install_sealed(ad, wt, recheck=True)
        return code, conflicts
    _written, conflicts = cmd_checks.install_sealed(ad, wt)
    if conflicts:
        return None, conflicts
    return audit(ad, wt, cut), []


def change_set(ad, wt, cut):
    """Mark untracked files intent-to-add, save `git diff <cut>`; (lines, files)."""
    untracked = [p for p in git(wt, "ls-files", "-z", "--others",
                                "--exclude-standard").split(b"\0") if p]
    for i in range(0, len(untracked), 200):
        git(wt, "add", "-N", "--", *[os.fsdecode(p) for p in untracked[i:i + 200]])
    diff = git(wt, "diff", cut)
    (ad / "evidence" / "changes.diff").write_bytes(diff)
    names = [n for n in git(wt, "diff", "--name-only", "-z", cut).split(b"\0") if n]
    return diff.count(b"\n"), len(names)


def check_names(rows):
    """{condition id: [test name]} from MANIFEST.md's check rows."""
    names = {}
    for row in rows:
        cell = row["Check (path :: test name)"]
        name = cell.split("::", 1)[-1].strip().strip('"').strip("`").strip()
        names.setdefault(row["#"].strip(), []).append(name)
    return names


def acceptance_run(ad, wt, state):
    """Run the checks; (command, exit code, seconds, output lines)."""
    gate = state["settings"].get("gate", [])
    n, check = cmd_run.pick(gate, "test", None)
    files = sorted(sealed.sealed_files(ad))
    scoped = cmd_run.PLACEHOLDER in str(check.get("files") or "")
    command = cmd_run.command_for(n, check, wt, files if scoped and files else None)
    path = ad / "evidence" / "acceptance.txt"
    code, seconds = cmd_run.execute(command, wt, path, None)
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return command, code, seconds, lines, scoped


def write_evidence(ad, conditions, names, command, code, lines):
    """evidence/C<n>.txt for each condition with acceptance checks; the ids."""
    written = []
    for cond in conditions:
        cid = cond["id"]
        if cid not in names:
            continue
        hits = [ln for ln in lines if any(name and name in ln for name in names[cid])]
        output = hits[-TAIL:] if hits else lines[-TAIL:]
        result = ("the run passed" if code == 0 else f"the run exited {code}") + (
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
    for name in PREP_FILES:  # an earlier pass's, never read as this one's
        (evidence / name).unlink(missing_ok=True)
    left = restore(ad, wt, args.wait)
    if left:
        token, code, message, lines = left
        emit(args.json, token, message, output=lines)
        return code
    cut = git(wt, "merge-base", f"origin/{state['repo']['base']}", "HEAD").decode().strip()
    recheck = not str(args.pass_ or "first").startswith("first")
    audit_code, conflicts = install(ad, wt, cut, recheck)
    if conflicts:
        write_conflicts(ad, conflicts)
        emit(args.json, "INSTALL_CONFLICT",
             f"{len(conflicts)} path(s) where a check can't go in; "
             "evidence/corrections.md names them", conflict=conflicts)
        return FAILED
    tree_hash = print_tree(wt)
    (evidence / "tree-start.txt").write_text(tree_hash + "\n", encoding="utf-8")
    diff_lines, diff_files = change_set(ad, wt, cut)
    rows, _na = art.manifest(ad / "acceptance" / "MANIFEST.md")
    names = check_names(rows)
    command, code, seconds, lines, scoped = acceptance_run(ad, wt, state)
    conditions = art.spec_conditions(ad / "SPEC.md")
    written = write_evidence(ad, conditions, names, command, code, lines)
    unnamed = [f"{cid}: {name}" for cid, ns in names.items() for name in ns
               if name and not any(name in ln for ln in lines)]
    ran = "exited 0" if code == 0 else f"exited {code}"
    emit(args.json, "PREPARED",
         f"checks installed, audit exit {audit_code}, acceptance run {ran}",
         tree=tree_hash, cut=cut,
         integrity=f"{evidence / 'integrity.txt'} (check-tests.py exit {audit_code})",
         changes=f"{evidence / 'changes.diff'} ({diff_lines} lines, {diff_files} files)",
         acceptance=(f"{evidence / 'acceptance.txt'} — `{command}` {ran} in {seconds:g}s"
                     + ("" if scoped else " (the whole suite: the test check has no "
                                          "scoped form)")),
         evidence=", ".join(written) or "none", unnamed=unnamed)
    return OK


def print_tree(wt):
    code, out, err = script("check-fresh.py", "--print-tree", wt)
    if code != 0 or not out.strip():
        raise Fail(f"check-fresh.py --print-tree exited {code}: {(err or out).strip()}",
                   CANNOT_RUN, "ERROR")
    return out.strip()


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
    now = print_tree(wt)
    if now == first:
        emit(args.json, "TREE", now)
        return OK
    changed = [os.fsdecode(n) for n in
               git(wt, "diff", "--name-only", "-z", first, now).split(b"\0") if n]
    emit(args.json, "TREE_CHANGED", f"{first} → {now}", changed=changed)
    return FAILED
