"""autodev.py check-manifest / eval-status / apply-fix / spec-overlap.

Mechanical reads of the workers' artifacts, so the orchestrator acts on a
printed decision instead of judging the files itself. Each takes `--dir
<artifact-dir>` (default `./.auto-dev`) and `--json`.

check-manifest
    Checks the acceptance tester's MANIFEST.md against SPEC.md: every condition
    has a check or a Not automatable row; every condition with a real Edge has
    a check covering it or an `<n> (Edge)` row; no check's Level is below its
    condition's Verify by (unless the Level cell says why); every condition with
    checks has base-run/C<n>.txt with a Result for each check that fits its
    kind (pass-to-pass passed, fail-to-pass failed, a repair `not re-run
    (repair)`); every check has its sealed copy under files/ and none is left in
    the worktree.
    Exit: 0 no gaps; 1 gaps: `RESPAWN: <conditions>` names what to re-spawn the
    tester for (Scope "ONLY conditions <...>").

eval-status [--install-conflict] [--mutation-left-changes]
    Turns SPEC_EVAL.md into one decision (pass the verifier's INSTALL CONFLICT
    or MUTATION LEFT CHANGES report as a flag):
      STOP                    mutation left changes: stop and report the paths
      CORRECT                 correct the coder (spend a round, consumer 3):
                              the conditions and findings are listed; an install
                              conflict is a correction too
      REPAIR                  only defective acceptance checks: repair mode
      ALL_MET                 nothing open; manual conditions go to the PR gate
    CORRECT and REPAIR can both be printed; repair first, then correct. The
    Mutation rows to pass to the next verifier spawn are printed as SURVIVOR
    lines. Exit: 0 a decision; 1 SPEC_EVAL.md is malformed or misses a
    condition (re-spawn the verifier).

apply-fix <file> <fix-file>
    Applies a reviewer's FIX blocks to <file> (SPEC.md or IMPLEMENTATION.md).
    A FIX block is:
        FIX <id>
        <<<<<<< OLD
        <exact old text>
        =======
        <new text>
        >>>>>>> NEW
    All or nothing: each old text must occur exactly once (after the blocks
    before it are applied), or nothing is written.
    Exit: 0 applied; 1 a block didn't match: spawn the file's author in revise
    mode with the fix file instead.

spec-overlap <file> [--spec SPEC.md] [--words N]
    Refuses a correction brief or plan that copies a condition's wording from
    SPEC.md: any run of N consecutive words (default 6, or the whole condition
    when shorter) of a condition's text found in <file>.
    Exit: 0 no overlap; 1 overlap (the copied words are printed): rewrite it as
    concrete behavior.

security-reviewer
    Prints the security reviewer to spawn: `auto-dev:security-reviewer-sensitive`
    when SPEC.md's Security/Compliance criteria section lists any criterion (the
    Define agent writes it only for a sensitive path), else
    `auto-dev:security-reviewer`. Exit: 0.

All exit 2 when they could not run (a file missing, unreadable) — never a pass.
"""

import re
import subprocess
import tempfile
from pathlib import Path

from . import artifacts as art
from . import state as st
from .output import CANNOT_RUN, FAILED, Fail, emit

FIX_RE = re.compile(r"^FIX[ \t]+(\S+)[ \t]*\n<<<<<<< OLD\n(.*?)\n=======\n(.*?)\n?>>>>>>> NEW",
                    re.DOTALL | re.MULTILINE)
WORD_RE = re.compile(r"[a-z0-9]+")


def add_arguments(parser, name):
    parser.add_argument("--dir", default=".auto-dev", help="the run's .auto-dev/")
    if name == "eval-status":
        parser.add_argument("--install-conflict", action="store_true")
        parser.add_argument("--mutation-left-changes", action="store_true")
    elif name == "apply-fix":
        parser.add_argument("file")
        parser.add_argument("fix_file")
    elif name == "spec-overlap":
        parser.add_argument("file")
        parser.add_argument("--spec", help="default: <dir>/SPEC.md")
        parser.add_argument("--words", type=int, default=6)


def worktree_of(args):
    """The worktree from state.json, or the artifact dir's parent."""
    try:
        return Path(st.load(args.dir)["worktree"])
    except st.StateError:
        return Path(args.dir).resolve().parent


def wrap(fn):
    def run(args):
        try:
            return fn(args)
        except art.ArtifactError as exc:
            missing = "does not exist" in str(exc) or "cannot read" in str(exc)
            raise Fail(str(exc), CANNOT_RUN if missing else FAILED,
                       "ERROR" if missing else "MALFORMED") from None
    return run


def edge_is_real(edge):
    return bool(edge) and not edge.lower().startswith("none")


@wrap
def check_manifest(args):
    ad = Path(args.dir)
    conditions = art.spec_conditions(ad / "SPEC.md")
    rows, na_rows = art.manifest(ad / "acceptance" / "MANIFEST.md")
    worktree = worktree_of(args)
    gaps = {}

    def gap(cid, why):
        gaps.setdefault(cid, []).append(why)

    na_ids = {r.get("#", "").strip() for r in na_rows}
    by_id = {}
    for row in rows:
        by_id.setdefault(row["#"].strip(), []).append(row)
    for cond in conditions:
        cid = cond["id"]
        checks = by_id.get(cid, [])
        if not checks and cid not in na_ids:
            gap(cid, "no check and no Not automatable row")
            continue
        if edge_is_real(cond["edge"]) and cid not in na_ids \
                and f"{cid} (Edge)" not in na_ids \
                and not any("edge" in r.get("Covers", "").lower() for r in checks):
            gap(cid, "its Edge has no check and no `(Edge)` Not automatable row")
        want = art.level_of(cond["verify"])
        for row in checks:
            level_cell = row.get("Level", "")
            have = art.level_of(level_cell)
            explained = len(level_cell.split()) > 1
            if want and have and art.LEVELS.index(have) < art.LEVELS.index(want) \
                    and not explained:
                gap(cid, f"a check is {have}, below Verify by {want}, with no reason")
        if checks:
            gap_base_run(ad, cid, checks, gap)
        for row in checks:
            path = art.check_path(row["Check (path :: test name)"])
            if not path:
                gap(cid, f"cannot read a check path from `{row['Check (path :: test name)']}`")
                continue
            if not (ad / "acceptance" / "files" / f"{path}.sealed").exists():
                gap(cid, f"no sealed copy files/{path}.sealed")
            if (worktree / path).exists() and not installed(ad):
                gap(cid, f"{path} is still in the worktree; seal it")
    if gaps:
        ids = sorted(gaps, key=sort_key)
        emit(args.json, "GAPS", f"{len(ids)} condition(s) with gaps",
             gap=[f"{cid}: {why}" for cid in ids for why in gaps[cid]],
             respawn=", ".join(ids))
        return FAILED
    emit(args.json, "OK", f"{len(conditions)} condition(s) covered")
    return 0


def installed(ad):
    """From Phase 5 on, the checks are installed in the worktree on purpose."""
    try:
        state = st.load(ad)
    except st.StateError:
        return False
    return st.phase(state, 4)["status"] == "done"


def gap_base_run(ad, cid, checks, gap):
    path = ad / "acceptance" / "base-run" / f"C{cid}.txt"
    if not path.exists():
        gap(cid, f"no base-run/C{cid}.txt")
        return
    results = art.base_run_results(path)
    for row in checks:
        cell = row["Check (path :: test name)"]
        name = cell.split("::", 1)[-1].strip().strip('"').strip()
        result = next((v for k, v in results.items() if k == name or name in k), None)
        kind = row.get("Kind", "").strip().lower()
        if result is None:
            gap(cid, f"base-run/C{cid}.txt has no Result for `{name}`")
        elif result.startswith("not re-run (repair)"):
            continue
        elif kind == "pass-to-pass" and not result.startswith("passed"):
            gap(cid, f"`{name}` is pass-to-pass but did not pass on the old code")
        elif kind == "fail-to-pass" and not result.startswith("failed"):
            gap(cid, f"`{name}` is fail-to-pass but did not fail on the old code")


def sort_key(cid):
    return (cid.startswith("S"), int(re.sub(r"\D", "", cid) or 0))


@wrap
def eval_status(args):
    ad = Path(args.dir)
    if args.mutation_left_changes:
        emit(args.json, "STOP", "the mutation step may have left changes in the "
             "source: stop and report the paths the verifier gave; build nothing "
             "more on this tree")
        return 0
    conditions = art.spec_conditions(ad / "SPEC.md")
    ev = art.spec_eval(ad / "SPEC_EVAL.md")
    verdicts = {r["#"].strip(): r for r in ev["rows"]}
    missing = [c["id"] for c in conditions if c["id"] not in verdicts]
    if missing:
        raise art.ArtifactError(f"SPEC_EVAL.md has no row for condition(s) "
                                f"{', '.join(missing)}: re-spawn the verifier")
    correct, repair, manual = [], [], []
    for cond in conditions:
        row = verdicts[cond["id"]]
        verdict = row["Verdict"].strip().lower()
        evidence = row.get("Evidence", "").lower()
        if verdict == "manual":
            manual.append(cond["id"])
        elif verdict in ("unmet", "partial"):
            if "defective" in evidence:
                repair.append(cond["id"])
            else:
                correct.append(f"condition {cond['id']} {verdict}: {row.get('Evidence', '')}")
        elif verdict != "met":
            raise art.ArtifactError(f"SPEC_EVAL.md: condition {cond['id']} has verdict "
                                    f"`{row['Verdict']}`, not met/partial/unmet/manual")
    for finding in ev["integrity"]:
        if finding.get("Judgment", "").strip().lower() == "unjustified":
            correct.append(f"integrity {finding.get('Finding', '')} at "
                           f"{finding.get('Location', '')}: {finding.get('Reason', '')}")
    if args.install_conflict:
        correct.insert(0, "install conflict: the coder wrote a file at an acceptance "
                       "check's path; move it, then re-run the verifier's first pass")
    if ev["defective"] and not repair:
        repair.append("see Defective acceptance checks")
    survivors = [" | ".join(r.get(k, "") for k in ("Mutant", "Location", "Change",
                                                    "Condition", "Judgment"))
                 for r in ev["survivors"]]
    fields = {"correct": correct, "repair": ", ".join(repair), "manual": ", ".join(manual),
              "survivor": survivors}
    if correct:
        emit(args.json, "CORRECT", f"{len(correct)} open item(s): spend a round "
             "(consumer 3), then brief the coder" + ("; repair the listed checks "
                                                     "first" if repair else ""), **fields)
    elif repair:
        emit(args.json, "REPAIR", "only defective acceptance checks are open: repair "
             "mode for these conditions, then a verifier re-check", **fields)
    else:
        emit(args.json, "ALL_MET", "nothing open" + (
            "; the manual conditions go to the PR gate" if manual else ""), **fields)
    return 0


@wrap
def apply_fix(args):
    target, fixes = Path(args.file), art.read(args.fix_file)
    text = art.read(target)
    blocks = FIX_RE.findall(fixes)
    if not blocks:
        raise Fail(f"{args.fix_file} holds no FIX block", FAILED, "NO-MATCH")
    failed = []
    for fix_id, old, new in blocks:
        count = text.count(old)
        if count != 1:
            failed.append(f"FIX {fix_id}: old text found {count} times")
            continue
        text = text.replace(old, new, 1)
    if failed:
        note_fix(args, "no-match")
        emit(args.json, "NO-MATCH", f"nothing written to {target}: spawn its author in "
             f"revise mode with {args.fix_file}", block=failed)
        return FAILED
    tmp = target.with_name(f".{target.name}.fix")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(target)
    note_fix(args, "applied")
    emit(args.json, "APPLIED", f"{len(blocks)} FIX block(s) to {target}")
    return 0


def note_fix(args, outcome):
    """Record the outcome in state.json, when there is a run, for `next`."""
    try:
        state = st.load(args.dir)
    except st.StateError:
        return
    state.setdefault("fixes", {})[str(Path(args.fix_file).resolve())] = outcome
    st.save(args.dir, state)


def words(text):
    return WORD_RE.findall(text.lower().replace("'", "").replace("’", ""))


@wrap
def spec_overlap(args):
    spec = Path(args.spec) if args.spec else Path(args.dir) / "SPEC.md"
    target = words(art.read(args.file))
    joined = " " + " ".join(target) + " "
    hits = []
    for cond in art.spec_conditions(spec):
        cw = words(cond["text"])
        size = min(args.words, len(cw))
        if size < 4:
            continue
        for i in range(len(cw) - size + 1):
            phrase = " ".join(cw[i:i + size])
            if f" {phrase} " in joined:
                hits.append(f"condition {cond['id']}: \"{phrase}\"")
                break
    if hits:
        emit(args.json, "OVERLAP", f"{args.file} copies SPEC.md's wording: say what the "
             "code must do and where, in your own words", copied=hits)
        return FAILED
    emit(args.json, "CLEAN", f"{args.file} copies no condition's wording")
    return 0


@wrap
def security_reviewer(args):
    criteria = [c for c in art.spec_conditions(Path(args.dir) / "SPEC.md")
                if c["id"].startswith("S")]
    agent = ("auto-dev:security-reviewer-sensitive" if criteria
             else "auto-dev:security-reviewer")
    emit(args.json, "AGENT", agent, criteria=len(criteria))
    return 0


def git_add_intent(worktree):
    """Mark untracked files intent-to-add so every diff sees them."""
    out = subprocess.run(["git", "ls-files", "-z", "--others", "--exclude-standard"],
                         cwd=worktree, capture_output=True, text=True, check=False).stdout
    paths = [p for p in out.split("\0") if p]
    if paths:
        with tempfile.TemporaryFile("w+") as fh:
            fh.write("\0".join(paths))
            fh.seek(0)
            subprocess.run(["git", "add", "-N", "--pathspec-from-file=-",
                            "--pathspec-file-nul"], cwd=worktree, stdin=fh,
                           capture_output=True, check=False)
