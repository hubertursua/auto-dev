"""autodev.py check-manifest / eval-status / apply-fix / spec-overlap /
security-reviewer / install-checks.

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
    (repair)`); every check has its sealed copy under files/, a sealed copy
    of a file that exists (it has a files/<path>.base) only adds lines to it,
    and, before the build is installed, no check is left in the worktree. A
    check's Result is the base-run line for its exact test name, else the one
    line whose name contains it.
    Prints `OK: <n> condition(s) covered`, or `GAPS: <n> condition(s) with
    gaps` with a `gap: <condition>: <why>` line for each gap and `respawn:
    <conditions>` naming what to re-spawn the tester for (Scope "ONLY
    conditions <...>").
    Exit: 0 no gaps; 1 gaps.

eval-status [--install-conflict] [--mutation-left-changes]
    Turns SPEC_EVAL.md into one decision, printed as one token (pass the
    verifier's INSTALL CONFLICT or MUTATION LEFT CHANGES report as a flag):
      STOP                    mutation left changes: stop and report the paths
      CORRECT                 correct the coder (spend a round, consumer 3):
                              each open condition and Unjustified finding is a
                              `correct:` line. An install conflict is CORRECT
                              with that one item, without reading SPEC_EVAL.md
                              (the verifier stopped before writing it)
      REPAIR                  only defective acceptance checks are open: repair
                              mode for the `repair:` conditions
      ALL_MET                 nothing open; manual conditions go to the PR gate
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
    before it are applied), every `FIX` line must start a well-formed block,
    and no new text may hold a marker line; otherwise nothing is written.
    When <file> is SPEC.md and the run's size check said FITS, a Security/
    Compliance criterion (`S<n>.`) in the result turns the run high-risk and the
    post-plan gate on (printed as `high_risk: yes`); a fix never turns it off.
    Exit: 0 applied; 1 no FIX block, or a block is malformed or didn't match
    (`NO-MATCH`): spawn the file's author in revise mode with the fix file
    instead.

spec-overlap <file> [--spec SPEC.md] [--words N]
    Refuses a correction brief or plan that copies a condition's wording from
    SPEC.md: any run of N consecutive words (default 6, or the whole condition
    when shorter) of a condition's text found in <file>. In a required-changes
    file (`*corrections.md`, `triage/*.md`) text in backticks or double quotes
    is left out: it quotes a test name, an assertion or output, not the spec.
    `record` runs the same check on the planner's IMPLEMENTATION.md and on each
    required-changes file the coder gets unedited.
    Exit: 0 no overlap; 1 overlap (the copied words are printed): rewrite it as
    concrete behavior.

security-reviewer
    Prints the security reviewer to spawn: `auto-dev:security-reviewer-sensitive`
    when SPEC.md's Security/Compliance criteria section lists any criterion (the
    Define agent writes it only for a sensitive path), else
    `auto-dev:security-reviewer`.
    Exit: 0 printed; 1 SPEC.md is malformed (no `## Conditions` section or no
    numbered condition); 2 SPEC.md is missing or unreadable.

install-checks [--recheck]
    Installs each sealed acceptance check, acceptance/files/<path>.sealed, at
    <worktree>/<path>, so the verifier needs no shell loop to do it. A check in
    a new file is copied in. A check that adds tests to an existing file (it has
    a files/<path>.base, the file it added to) has its added lines put in among
    the lines now there, each next to the line it followed, so the coder's
    edits to that file stay. A check already in is left alone. Without
    --recheck (a first pass), a path where a check can't go in (the coder made
    a file there, deleted the file, or rewrote the lines around an added test)
    is printed as a `conflict:` line and nothing is installed. With --recheck,
    a check that was edited is put back: a new file is copied over, and in a
    shared file the edits that touched the check are undone and the rest kept
    (run the audit first, so it records the edit); a check that can't be put
    back is a `conflict:` line, and the others are still installed.
    Prints `INSTALLED: <n> check(s)` (or `CONFLICT: <n> path(s) …`) and the
    paths it wrote as `installed:` lines.
    Exit: 0 installed; 1 a conflict; 2 no sealed checks dir, or git can't diff.

All exit 2 when they could not run (a file missing, unreadable) — never a pass.
"""

import re
import subprocess
import tempfile
from pathlib import Path

from . import artifacts as art
from . import sealed
from . import state as st
from .output import CANNOT_RUN, FAILED, Fail, emit

FIX_RE = re.compile(r"^FIX[ \t]+(\S+)[ \t]*\n<<<<<<< OLD\n(.*?)\n=======\n(.*?)\n?>>>>>>> NEW",
                    re.DOTALL | re.MULTILINE)
FIX_HEADER_RE = re.compile(r"^FIX\s", re.MULTILINE)
# A marker line left in a block's new text: the block was cut or run together.
CONFLICT_RE = re.compile(r"^(<{7}(?:[ \t].*)?|={7}|>{7}(?:[ \t].*)?)[ \t]*$", re.MULTILINE)
WORD_RE = re.compile(r"[a-z0-9]+")


def add_arguments(parser, name):
    parser.add_argument("--dir", default=".auto-dev", help="the run's .auto-dev/")
    if name == "eval-status":
        parser.add_argument("--install-conflict", action="store_true")
        parser.add_argument("--mutation-left-changes", action="store_true")
    elif name == "apply-fix":
        parser.add_argument("file")
        parser.add_argument("fix_file")
    elif name == "install-checks":
        parser.add_argument("--recheck", action="store_true")
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


def sealed_pairs(ad, wt):
    """[(sealed copy, install path)] for every sealed acceptance check."""
    files = Path(ad) / "acceptance" / "files"
    if not files.is_dir():
        raise Fail(f"{files} does not exist: no sealed checks to install", CANNOT_RUN,
                   "ERROR")
    return [(s, Path(wt) / rel) for rel, s in sealed.sealed_files(ad).items()]


def install_sealed(ad, wt, recheck=False, dry=False):
    """Install the sealed checks; returns (installed paths, conflict paths).

    A new file is copied in. A check that adds to a file goes in among the lines
    already there (lib/sealed.py). On a first pass, any conflict installs
    nothing; with `recheck`, every check that can go back in does. `dry` only
    reports the conflicts."""
    sealed_pairs(ad, wt)  # fails when there is no files/ directory
    plans, conflicts = [], []
    for rel in sealed.sealed_files(ad):
        target = Path(wt) / rel
        current = sealed.read(target)
        try:
            body, conflict = sealed.installed_text(ad, rel, current, recheck)
        except sealed.SealError as exc:
            raise Fail(f"cannot diff {rel}: {exc}", CANNOT_RUN, "ERROR") from None
        if conflict:
            conflicts.append(rel)
        else:
            plans.append((rel, target, current, body))
    if dry or (conflicts and not recheck):
        return [], conflicts
    written = []
    for rel, target, current, body in plans:
        if body is not None:
            if sealed.base_of(ad, rel) is None:  # a new file: copied as sealed
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(sealed.sealed_files(ad)[rel].read_bytes())
            else:
                sealed.write(target, body, current)
            written.append(rel)
        if sealed.base_of(ad, rel):  # a shared file: remember it whole
            sealed.snapshot(ad, rel, sealed.read(target))
    return written, conflicts


def install_checks(args):
    wt = worktree_of(args)
    written, conflicts = install_sealed(args.dir, wt, args.recheck)
    if conflicts:
        emit(args.json, "CONFLICT", f"{len(conflicts)} path(s) where a check can't go "
             "in" + ("" if args.recheck else "; nothing installed"),
             conflict=conflicts, installed=written)
        return FAILED
    emit(args.json, "INSTALLED", f"{len(sealed_pairs(args.dir, wt))} check(s)",
         installed=written)
    return 0


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
            if not (ad / "acceptance" / "files" / f"{path}.sealed").exists():
                gap(cid, f"no sealed copy files/{path}.sealed")
                continue
            why = sealed.adds_only(ad, path)
            if why:
                gap(cid, why)
            if not installed(ad):
                left = left_in(ad, worktree, path)
                if left:
                    gap(cid, left)
    if gaps:
        ids = sorted(gaps, key=sort_key)
        emit(args.json, "GAPS", f"{len(ids)} condition(s) with gaps",
             gap=[f"{cid}: {why}" for cid in ids for why in gaps[cid]],
             respawn=", ".join(ids))
        return FAILED
    emit(args.json, "OK", f"{len(conditions)} condition(s) covered")
    return 0


def left_in(ad, worktree, path):
    """Why the worktree still holds a sealed check, or None."""
    current = sealed.read(worktree / path)
    base = sealed.base_of(ad, path)
    if base is None:
        return f"{path} is still in the worktree; seal it" if current is not None else None
    if sealed.lines(current) != base:
        return (f"{path} still differs from HEAD; seal your tests and restore the file "
                "(`git -C <worktree> checkout -- <path>`)")
    return None


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
    token, fields = eval_decision(Path(args.dir), args.install_conflict,
                                  args.mutation_left_changes)
    message = {
        "STOP": "the mutation step may have left changes in the source: stop and "
                "report the paths the verifier gave; build nothing more on this tree",
        "CORRECT": f"{len(fields.get('correct', []))} open item(s): spend a round "
                   "(consumer 3), then brief the coder" + (
                       "; repair the listed checks first" if fields.get("repair") else ""),
        "REPAIR": "only defective acceptance checks are open: repair mode for these "
                  "conditions, then a verifier re-check",
        "ALL_MET": "nothing open" + ("; the manual conditions go to the PR gate"
                                     if fields.get("manual") else ""),
    }[token]
    emit(args.json, token, message, **fields)
    return 0


INSTALL_CONFLICT = ("install conflict: an acceptance check can't go into the paths "
                    "evidence/corrections.md names (the coder made, deleted or rewrote "
                    "them); make the change it asks for, then re-run the verifier")


def eval_decision(ad, install_conflict=False, mutation_left_changes=False):
    """SPEC_EVAL.md as one decision: (STOP|CORRECT|REPAIR|ALL_MET, fields)."""
    if mutation_left_changes:
        return "STOP", {}
    if install_conflict:
        # The verifier stopped before judging: SPEC_EVAL.md is absent or stale.
        return "CORRECT", {"correct": [INSTALL_CONFLICT], "repair": "", "manual": "",
                           "survivor": []}
    conditions = art.spec_conditions(ad / "SPEC.md")
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


@wrap
def apply_fix(args):
    target = Path(args.file)
    blocks, failed = apply_fix_file(target, args.fix_file)
    if not blocks and not failed:
        raise Fail(f"{args.fix_file} holds no FIX block", FAILED, "NO-MATCH")
    if failed:
        note_fix(args, "no-match")
        emit(args.json, "NO-MATCH", f"nothing written to {target}: spawn its author in "
             f"revise mode with {args.fix_file}", block=failed)
        return FAILED
    extra = {}
    if target.name == "SPEC.md":
        try:
            state = st.load(args.dir)
        except st.StateError:
            state = None  # apply-fix outside a run: there is no gate to turn on
        try:
            changed = state is not None and rederive_risk(state, target)
        except art.ArtifactError:
            changed = False  # SPEC.md is written; it is checked when it is used
        if changed:
            st.add_note(state, "SPEC.md gained a Security/Compliance criterion: "
                        "high risk, post-plan gate on")
            st.save(args.dir, state)
        if state is not None and state.get("high_risk"):
            extra["high_risk"] = "yes"
    note_fix(args, "applied")
    emit(args.json, "APPLIED", f"{len(blocks)} FIX block(s) to {target}", **extra)
    return 0


def rederive_risk(state, spec):
    """Turn high_risk and the post-plan gate on when a run that FITS has a
    Security/Compliance criterion in SPEC.md. Never turns either off.
    Returns whether anything changed."""
    if state.get("size") != "FITS":
        return False
    if not any(c["id"].startswith("S") for c in art.spec_conditions(spec)):
        return False
    settings = state.setdefault("settings", {})
    changed = not state.get("high_risk") or not settings.get("post_plan_gate")
    state["high_risk"] = True
    settings["post_plan_gate"] = True
    return changed


def apply_fix_file(target, fix_file):
    """Apply every FIX block, or none: (blocks, [why each failed])."""
    fixes, text = art.read(fix_file), art.read(target)
    blocks = FIX_RE.findall(fixes)
    headers = len(FIX_HEADER_RE.findall(fixes))
    failed = []
    if headers != len(blocks):
        failed.append(f"{headers} FIX header(s) but {len(blocks)} well-formed block(s): "
                      "each needs `<<<<<<< OLD`, `=======` and `>>>>>>> NEW` lines")
    for fix_id, old, new in blocks:
        if CONFLICT_RE.search(new):
            failed.append(f"FIX {fix_id}: its new text holds a conflict marker line")
            continue
        count = text.count(old)
        if count != 1:
            failed.append(f"FIX {fix_id}: old text found {count} times")
            continue
        text = text.replace(old, new, 1)
    if blocks and not failed:
        tmp = Path(target).with_name(f".{Path(target).name}.fix")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(target)
    return blocks, failed


def note_fix(args, outcome):
    """Record the outcome in state.json, when there is a run, for `next`."""
    try:
        state = st.load(args.dir)
    except st.StateError:
        return
    state.setdefault("fixes", {})[str(Path(args.fix_file).resolve())] = {
        "outcome": outcome, "seq": st.seq(state)}
    st.save(args.dir, state)


def words(text):
    return WORD_RE.findall(text.lower().replace("'", "").replace("’", ""))


QUOTED_RE = re.compile(r"`[^`\n]*`|\"[^\"\n]*\"|“[^”\n]*”")


def is_corrections(path):
    path = Path(path)
    return path.name.endswith("corrections.md") or path.parent.name == "triage"


def overlaps(path, spec, n=6, quoted=None, text=None):
    """Each condition whose wording `path` copies: `condition <id>: "<words>"`.
    Quoted spans (test names, assertions, output) count only when `quoted` is
    true; by default, everywhere but in a required-changes file. `text`, when
    given, is checked in place of the file's text (part of it)."""
    text = art.read(path) if text is None else text
    if quoted is None:
        quoted = not is_corrections(path)
    sources = [(f"condition {c['id']}", c["text"]) for c in art.spec_conditions(spec)]
    return [f"{label}: \"{phrase}\"" for label, phrase in
            phrase_hits(text, sources, n, quoted)]


def phrase_hits(text, sources, n=6, quoted=False):
    """[(label, phrase)]: for each (label, wording) in `sources`, the first run
    of `n` of its words (fewer for a short one, never under 4) that `text`
    repeats. Quoted spans in `text` count only when `quoted` is true."""
    # A phrase may not run across a left-out span: each piece is matched alone.
    pieces = QUOTED_RE.split(text) if not quoted else [text]
    joined = " " + " | ".join(" ".join(words(p)) for p in pieces) + " "
    hits = []
    for label, wording in sources:
        cw = words(wording)
        size = min(n, len(cw))
        if size < 4:
            continue
        for i in range(len(cw) - size + 1):
            phrase = " ".join(cw[i:i + size])
            if f" {phrase} " in joined:
                hits.append((label, phrase))
                break
    return hits


@wrap
def spec_overlap(args):
    spec = Path(args.spec) if args.spec else Path(args.dir) / "SPEC.md"
    hits = overlaps(args.file, spec, args.words)
    if hits:
        emit(args.json, "OVERLAP", f"{args.file} copies SPEC.md's wording: say what the "
             "code must do and where, in your own words", copied=hits)
        return FAILED
    emit(args.json, "CLEAN", f"{args.file} copies no condition's wording")
    return 0


def security_criteria(ad):
    """SPEC.md's Security/Compliance criteria (`S<n>.` conditions)."""
    return [c for c in art.spec_conditions(Path(ad) / "SPEC.md") if c["id"].startswith("S")]


def security_agent(ad):
    """The security reviewer to spawn: the sensitive one when SPEC.md lists any
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
