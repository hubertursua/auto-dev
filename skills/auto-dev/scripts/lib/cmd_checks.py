"""autodev.py check-manifest / eval-status / security-reviewer.

Mechanical reads of the workers' artifacts, so the orchestrator acts on a
printed decision instead of judging the files itself. Each takes `--dir
<artifact-dir>` (default `./.auto-dev`) and `--json`.

check-manifest
    Checks the acceptance tester's MANIFEST.md against PLAN.md: every condition
    has a check or a Not automatable row; every condition with a real Edge has
    a check covering it or an `<n> (Edge)` row; no check's Level is below its
    condition's Verify by (unless the Level cell says why); every condition with
    checks has base-run/C<n>.txt with a Result for each check that fits its
    kind (pass-to-pass passed, fail-to-pass failed, a repair `not re-run
    (repair)`); and every check's file is in the worktree (the tester leaves
    its checks there, and `next` commits them). A check's Result is the
    base-run line for its exact test name, else the one line whose name
    contains it.
    Prints `OK: <n> condition(s) covered`, or `GAPS: <n> condition(s) with
    gaps` with a `gap: <condition>: <why>` line for each gap and `respawn:
    <conditions>` naming what to re-spawn the tester for (Scope "ONLY
    conditions <...>").
    Exit: 0 no gaps; 1 gaps.

eval-status [--mutation-left-changes]
    Turns SPEC_EVAL.md into one decision, printed as one token (pass the
    verifier's MUTATION LEFT CHANGES report as a flag):
      STOP                    mutation left changes: stop and report the paths
      CORRECT                 correct the coder (spend a round):
                              each open condition and Unjustified finding is a
                              `correct:` line
      REPAIR                  only defective acceptance checks are open: repair
                              mode for the `repair:` conditions
      ALL_MET                 nothing open; manual conditions go to the ready gate
    A condition with a check listed under `## Defective acceptance checks` (as
    MANIFEST.md names it, `path` :: "test name", matched exactly; or by path
    alone when only that condition has checks in that file) goes to `repair:`.
    A `partial` one is settled by the repair alone; an `unmet` one (a check
    failed, maybe on a real bug) is also corrected. A listed check whose
    condition is met changes nothing. CORRECT with a `repair:` line means
    repair those first, then correct. Also printed:
    `manual:` (the manual conditions) and a `survivor:` line per Mutation row,
    to pass to the next verifier spawn.
    Exit: 0 a decision; 1 SPEC_EVAL.md is malformed or misses a condition
    (re-spawn the verifier).

security-reviewer
    Prints the security reviewer to spawn: `auto-dev:security-reviewer-sensitive`
    when PLAN.md's Security/Compliance criteria section lists any criterion (the
    planner writes it only for a sensitive path), else
    `auto-dev:security-reviewer`.
    Exit: 0 printed; 1 PLAN.md is malformed (no `## Conditions` section or no
    numbered condition); 2 PLAN.md is missing or unreadable.

All exit 2 when they could not run (a file missing, unreadable) — never a pass.
"""

import re
import subprocess
import tempfile
from pathlib import Path

from . import artifacts as art
from . import state as st
from .output import CANNOT_RUN, FAILED, Fail, emit


def add_arguments(parser, name):
    parser.add_argument("--dir", default=".auto-dev", help="the run's .auto-dev/")
    if name == "eval-status":
        parser.add_argument("--mutation-left-changes", action="store_true")


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
    conditions = art.spec_conditions(ad / "PLAN.md")
    rows, na_rows = art.manifest(ad / "acceptance" / "MANIFEST.md")
    worktree = worktree_of(args)
    gaps = {}

    def gap(cid, why):
        if why not in gaps.setdefault(cid, []):
            gaps[cid].append(why)

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
            if not (worktree / path).is_file():
                gap(cid, f"{path} is not in the worktree: write the check there")
    if gaps:
        ids = sorted(gaps, key=sort_key)
        emit(args.json, "GAPS", f"{len(ids)} condition(s) with gaps",
             gap=[f"{cid}: {why}" for cid in ids for why in gaps[cid]],
             respawn=", ".join(ids))
        return FAILED
    emit(args.json, "OK", f"{len(conditions)} condition(s) covered")
    return 0


def gap_base_run(ad, cid, checks, gap):
    path = ad / "acceptance" / "base-run" / f"C{cid}.txt"
    if not path.exists():
        gap(cid, f"no base-run/C{cid}.txt")
        return
    results = art.base_run_results(path)
    for row in checks:
        cell = row["Check (path :: test name)"]
        name = cell.split("::", 1)[-1].strip().strip('"').strip()
        result = result_for(results, name)
        kind = row.get("Kind", "").strip().lower()
        if result is None:
            gap(cid, f"base-run/C{cid}.txt has no Result for `{name}`")
        elif result.startswith("not re-run (repair)"):
            continue
        elif kind == "pass-to-pass" and not result.startswith("passed"):
            gap(cid, f"`{name}` is pass-to-pass but did not pass on the old code")
        elif kind == "fail-to-pass" and not result.startswith("failed"):
            gap(cid, f"`{name}` is fail-to-pass but did not fail on the old code")


def result_for(results, name):
    """The Result for test `name`: its exact name, else the one name containing it."""
    if name in results:
        return results[name]
    near = [v for k, v in results.items() if name in k]
    return near[0] if len(near) == 1 else None


def sort_key(cid):
    return (cid.startswith("S"), int(re.sub(r"\D", "", cid) or 0))


@wrap
def eval_status(args):
    token, fields = eval_decision(Path(args.dir), args.mutation_left_changes)
    message = {
        "STOP": "the mutation step may have left changes in the source: stop and "
                "report the paths the verifier gave; build nothing more on this tree",
        "CORRECT": f"{len(fields.get('correct', []))} open item(s): spend a round, "
                   "then brief the coder" + (
                       "; repair the listed checks first" if fields.get("repair") else ""),
        "REPAIR": "only defective acceptance checks are open: repair mode for these "
                  "conditions, then a verifier re-check",
        "ALL_MET": "nothing open" + ("; the manual conditions go to the ready-for-review gate"
                                     if fields.get("manual") else ""),
    }[token]
    emit(args.json, token, message, **fields)
    return 0


def eval_decision(ad, mutation_left_changes=False):
    """SPEC_EVAL.md as one decision: (STOP|CORRECT|REPAIR|ALL_MET, fields)."""
    if mutation_left_changes:
        return "STOP", {}
    conditions = art.spec_conditions(ad / "PLAN.md")
    ev = art.spec_eval(ad / "SPEC_EVAL.md")
    verdicts = {r["#"].strip(): r for r in ev["rows"]}
    missing = [c["id"] for c in conditions if c["id"] not in verdicts]
    if missing:
        raise art.ArtifactError(f"SPEC_EVAL.md has no row for condition(s) "
                                f"{', '.join(missing)}: re-spawn the verifier")
    correct, repair, manual, open_ = [], [], [], []
    for cond in conditions:
        row = verdicts[cond["id"]]
        verdict = row["Verdict"].strip().lower()
        if verdict == "manual":
            manual.append(cond["id"])
        elif verdict in ("unmet", "partial"):
            open_.append((cond["id"], verdict, row.get("Evidence", "")))
        elif verdict != "met":
            raise art.ArtifactError(f"SPEC_EVAL.md: condition {cond['id']} has verdict "
                                    f"`{row['Verdict']}`, not met/partial/unmet/manual")
    defective = defective_conditions(ad, ev["defective"]) if open_ else set()
    for cid, verdict, evidence in open_:
        if cid in defective:
            repair.append(cid)
        # `partial` with a defective check is settled by the repair alone; `unmet`
        # means a check failed, which may be a real bug, so the coder hears of it too.
        if cid not in defective or verdict == "unmet":
            correct.append(f"condition {cid} {verdict}: {evidence}")
    for finding in ev["integrity"]:
        if finding.get("Judgment", "").strip().lower() == "unjustified":
            correct.append(f"integrity {finding.get('Finding', '')} at "
                           f"{finding.get('Location', '')}: {finding.get('Reason', '')}")
    survivors = [" | ".join(r.get(k, "") for k in ("Mutant", "Location", "Change",
                                                    "Condition", "Judgment"))
                 for r in ev["survivors"]]
    fields = {"correct": correct, "repair": ", ".join(repair), "manual": ", ".join(manual),
              "survivor": survivors}
    if correct:
        return "CORRECT", fields
    if repair:
        return "REPAIR", fields
    return "ALL_MET", fields


CHECK_REF_RE = re.compile(r'`([^`]+)`\s*::\s*"([^"]+)"')
PATH_REF_RE = re.compile(r"`([^`]+)`(?!\s*::)")


def defective_conditions(ad, section):
    """The conditions with a check listed under `## Defective acceptance checks`.

    A check is listed when the section names it as MANIFEST.md does
    (`path` :: "test name", matched exactly), or names its path alone when only
    that condition has checks in that file."""
    if not section:
        return set()
    rows, _ = art.manifest(ad / "acceptance" / "MANIFEST.md")
    named = {(p.strip(), n.strip()) for p, n in CHECK_REF_RE.findall(section)}
    paths = {p.strip() for p in PATH_REF_RE.findall(section)}
    checks, owners = [], {}
    for row in rows:
        cid, cell = row["#"].strip(), row["Check (path :: test name)"]
        match = CHECK_REF_RE.search(cell)
        if match:
            path, name = match.group(1).strip(), match.group(2).strip()
            checks.append((cid, path, name))
            owners.setdefault(path, set()).add(cid)
    return {cid for cid, path, name in checks
            if (path, name) in named or (path in paths and owners[path] == {cid})}


def security_criteria(ad):
    """PLAN.md's Security/Compliance criteria (`S<n>.` conditions)."""
    return [c for c in art.spec_conditions(Path(ad) / "PLAN.md") if c["id"].startswith("S")]


def security_agent(ad):
    """The security reviewer to spawn: the sensitive one when PLAN.md lists any
    Security/Compliance criterion. `next` and `security-reviewer` both use it."""
    return ("auto-dev:security-reviewer-sensitive" if security_criteria(ad)
            else "auto-dev:security-reviewer")


@wrap
def security_reviewer(args):
    emit(args.json, "AGENT", security_agent(args.dir),
         criteria=len(security_criteria(args.dir)))
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
