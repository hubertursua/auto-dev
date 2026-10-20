"""autodev.py brief / record / check-artifact — briefing workers and checking what they return.

brief <worker> [--mode M] [--set name=value ...] [--dir <artifact-dir>]
brief profiler --out <dir> --set repo=<path> --set base=<branch> --set draft_path=<path>
    Writes briefs/<worker>-<n>.md: one `name: value` line for every slot the
    worker's agent file (agents/<worker>.md) uses in that mode. It fills what it
    can from state.json and the artifacts (paths, base, task, the profile's test
    command and gate, the acceptance check paths, the last survivors, the next
    review pass, the result file) and takes the rest from --set. It refuses when
    a slot the worker needs has no value. Prints the agent type to spawn and
    the one-line prompt to give it.
    Exit: 0 written; 1 refused (the missing slots are listed).

record <worker> <n>
    Reads returns/<worker>-<n>.json, checks it has the keys the worker's Result
    section lists and an allowed `next`, then re-derives the same decision from
    the artifact the worker wrote (for example: the verifier's `next` against
    `eval-status`, the judge's open must-fix count against CODE_REVIEW.md, the
    cleanup agent's GREEN against the lint reports). Every file the result says
    the worker wrote must exist and pass check-artifact (a fix file, SPEC_EVAL.md
    and corrections.md, the lint reports, a reviewer's report or votes,
    CODE_REVIEW.md and its corrections, SECURITY_REVIEW.md, the triager's file),
    and the two files the coder is briefed with that a SPEC.md reader writes,
    IMPLEMENTATION.md and evidence/corrections.md, must not copy a condition's
    wording (spec-overlap). On a match it updates
    state.json (the Define agent's size check, and the result in the log
    `autodev.py next` reads) and
    prints `RECORDED` with the `next` token.
    Exit: 0 recorded; 1 the return and the artifact disagree, or the return is
    malformed (both sides are printed: re-spawn the worker, don't guess).

check-artifact <file>
    Checks one artifact against its template before a worker returns it:
    SPEC.md, IMPLEMENTATION.md, acceptance/MANIFEST.md, SPEC_EVAL.md,
    CODE_REVIEW.md, SECURITY_REVIEW.md, review/pass-<n>/R<k>.md and
    VOTES-R<k>.md, lint/<CHECK>.md, a required-changes file (corrections.md,
    triage/*.md), a FIX file (fixes/*.md), or a returns/*.json file.
    Exit: 0 it follows the template; 1 problems (each printed).

All exit 2 when they could not run — never a pass.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

from . import artifacts as art
from . import briefs
from . import state as st
from .cmd_checks import FIX_RE, overlaps
from .output import CANNOT_RUN, FAILED, Fail, emit

SCRIPTS = Path(__file__).resolve().parent.parent
SKILL_DIR = SCRIPTS.parent
BINDING_RULES = ("the repo's CLAUDE.md or AGENTS.md, CONTRIBUTING and coding-guideline "
                 "docs, and the security directives named in {artifact_dir}/profile.md; "
                 "they override finishing the task")
IMPLEMENTATION_HEADINGS = ("## Files", "## Design", "## Data flow", "## Build sequence",
                           "## Test plan", "## Migrations / config")
VERDICTS = {"met", "partial", "unmet", "manual"}
FIX_PREFIX = {"define-reviewer": "define", "plan-reviewer": "plan"}


def add_arguments(parser, name):
    parser.add_argument("--dir", default=".auto-dev", help="the run's .auto-dev/")
    if name == "brief":
        parser.add_argument("worker")
        parser.add_argument("--mode")
        parser.add_argument("--set", action="append", default=[], metavar="NAME=VALUE")
        parser.add_argument("--out", help="where to write a profiler brief (no run yet)")
    elif name == "record":
        parser.add_argument("worker")
        parser.add_argument("n", type=int)
    elif name == "check-artifact":
        parser.add_argument("file")


# ---------------------------------------------------------------- brief

def parse_sets(pairs):
    values = {}
    for pair in pairs:
        name, sep, value = pair.partition("=")
        if not sep or not name:
            raise Fail(f"--set {pair!r} is not name=value", CANNOT_RUN, "ERROR")
        values[name.strip()] = value
    return values


def next_number(directory, worker):
    taken = [int(m.group(1)) for p in directory.glob(f"{worker}-*.md")
             if (m := re.match(rf"{re.escape(worker)}-(\d+)\.md$", p.name))]
    return max(taken, default=0) + 1


def acceptance_paths(ad):
    try:
        rows, _ = art.manifest(ad / "acceptance" / "MANIFEST.md")
    except art.ArtifactError:
        return "none"
    paths = sorted({p for r in rows if (p := art.check_path(r["Check (path :: test name)"]))})
    return ", ".join(paths) or "none"


def survivors(ad):
    try:
        rows = art.spec_eval(ad / "SPEC_EVAL.md")["survivors"]
    except art.ArtifactError:
        return "none"
    keys = ("Mutant", "Location", "Change", "Condition", "Judgment")
    lines = ["| " + " | ".join(keys) + " |"] + [
        "| " + " | ".join(r.get(k, "") for k in keys) + " |" for r in rows]
    return "\n".join(lines) if rows else "none"


def symbol_lookup(ad):
    profile = ad / "profile.md"
    if profile.exists():
        for line in profile.read_text(encoding="utf-8").splitlines():
            if line.startswith("- **Symbol lookup:**"):
                return line.split(":**", 1)[1].strip()
    return "`grep -n`"


def print_tree(worktree):
    out = subprocess.run([sys.executable, str(SCRIPTS / "check-fresh.py"), "--print-tree",
                          worktree], capture_output=True, text=True, check=False)
    return out.stdout.strip() or "unknown"


def auto_values(worker, n, state, ad, mode):
    """Every AUTO slot's value for this run (some depend on the worker)."""
    s = state["settings"]
    test = next((c["command"] for c in s.get("gate", []) if c.get("kind") == "test"), "")
    gate = "\n".join(f"{i}. `{c['command']}` → {ad}/lint/{c.get('report', '')}"
                     for i, c in enumerate(s.get("gate", []), 1))
    phase6 = state.get("phase6", {})
    values = {
        "worktree": state["worktree"], "artifact_dir": str(ad), "skill_dir": str(SKILL_DIR),
        "base": state["repo"]["base"], "branch": state["branch"],
        "task": state["task"].get("ask") or state["task"].get("text", ""),
        "ticket": st.ticket_line(state["task"]).split(" — ")[0],
        "binding_rules": BINDING_RULES.format(artifact_dir=ad),
        "test_command": test or "none", "test_notes": s.get("test_notes") or "none",
        "mutation_cap": str(s.get("mutation_max", 20)) if s.get("mutation_max", 20) else "0 (off)",
        "gate_commands": gate or "none",
        "result_file": str(ad / "returns" / f"{worker}-{n}.json"),
        "pr": str(phase6.get("pr") or "none"),
        "pass": str(phase6.get("review_pass") or 1),
        "run": str(phase6.get("security_run", 0) + 1),
        "triage_file": str(ad / "triage" / f"{mode or 'triage'}-{n}.md"),
        "answer_file": str(ad / "lookups" / f"{n}.md"),
        "blocked_file": str(ad / "blocked" / f"coder-{n}.md"),
        "fix_file": str(ad / "fixes" / f"{FIX_PREFIX.get(worker, 'plan')}-{n}.md"),
    }
    return values


LAZY = {"acceptance_paths": acceptance_paths, "survivors": survivors,
        "symbol_lookup": symbol_lookup}


def brief(args):
    worker = args.worker
    given = parse_sets(args.set)
    if worker == "profiler":
        if not args.out:
            raise Fail("a profiler brief needs --out <dir> (there is no run yet)",
                       CANNOT_RUN, "ERROR")
        path, values = write_brief(None, Path(args.out).resolve(), worker, args.mode, given)
    else:
        try:
            state = st.load(args.dir)
        except st.StateError as exc:
            raise Fail(str(exc), CANNOT_RUN, "ERROR") from None
        path, values = write_brief(state, Path(state["artifact_dir"]), worker,
                                   args.mode, given)
        st.save(args.dir, state)
    n = int(path.stem.rsplit("-", 1)[1])
    emit(args.json, "BRIEF", str(path), agent=f"auto-dev:{worker}", n=n,
         prompt=prompt_for(path), result_file=values.get("result_file", ""))
    return 0


def prompt_for(path):
    return f"Your brief is at {path}. Read it first."


def write_brief(state, where, worker, mode, given):
    """Write briefs/<worker>-<n>.md and log it in `state` (the caller saves).

    `where` is the artifact dir, or for the profiler (state None) the folder
    to write into. Returns (path, the slot values)."""
    if worker not in briefs.RESULTS:
        raise Fail(f"unknown worker {worker!r}; one of {', '.join(sorted(briefs.RESULTS))}",
                   CANNOT_RUN, "ERROR")
    worker_modes = briefs.modes(worker)
    if worker_modes and mode not in worker_modes:
        raise Fail(f"{worker} needs --mode, one of {', '.join(worker_modes)}",
                   FAILED, "REFUSED")
    if not worker_modes and mode:
        raise Fail(f"{worker} has no modes", FAILED, "REFUSED")
    if state is None:
        ad, directory = None, where
        n = next_number(directory, worker)
        auto = {"skill_dir": str(SKILL_DIR),
                "result_file": str(where / f"profiler-{n}.json")}
    else:
        ad = where
        directory = ad / "briefs"
        n = next_number(directory, worker)
        auto = auto_values(worker, n, state, ad, mode)
    needed = briefs.slots(worker, mode)
    values, missing = {}, []
    for slot in sorted(needed):
        kind = briefs.kind(worker, slot)
        if slot in given:
            values[slot] = given[slot]
        elif kind == "auto" and slot in auto:
            values[slot] = auto[slot]
        elif kind == "auto" and slot == "tree" and ad is not None:
            values[slot] = print_tree(auto["worktree"])
        elif kind == "auto" and slot in LAZY and ad is not None:
            values[slot] = LAZY[slot](ad)
        elif kind == "optional":
            values[slot] = "none"
        else:
            missing.append(slot)
    unknown = sorted(set(given) - needed)
    if missing:
        raise Fail(f"{worker} needs " + ", ".join(f"--set {m}=..." for m in missing),
                   FAILED, "REFUSED")
    if unknown:
        raise Fail(f"{worker} ({mode or 'no mode'}) uses no slot named "
                   f"{', '.join(unknown)}", FAILED, "REFUSED")
    directory.mkdir(parents=True, exist_ok=True)
    if ad is not None:
        for sub in ("returns", "fixes", "triage", "lookups", "blocked"):
            (ad / sub).mkdir(exist_ok=True)
    path = directory / f"{worker}-{n}.md"
    path.write_text(briefs.render(worker, n, mode, values), encoding="utf-8")
    if state is not None:
        state.setdefault("briefs", []).append(
            {"worker": worker, "n": n, "mode": mode, "sets": given, "at": st.now(),
             "seq": st.seq(state)})
    return path, values


# ---------------------------------------------------------------- record

def load_return(ad, worker, n):
    path = ad / "returns" / f"{worker}-{n}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise Fail(f"no {path}: the worker wrote no result file; re-spawn it",
                   FAILED, "MISSING") from None
    except ValueError as exc:
        raise Fail(f"{path} is not JSON: {exc}", FAILED, "MALFORMED") from None
    problems = return_problems(worker, data)
    if problems:
        raise Fail(f"{path}: " + "; ".join(problems), FAILED, "MALFORMED")
    return data


def return_problems(worker, data):
    problems = []
    if not isinstance(data, dict):
        return ["not a JSON object"]
    if data.get("worker") != worker:
        problems.append(f"worker is {data.get('worker')!r}, expected {worker!r}")
    if data.get("status") not in briefs.STATUSES:
        problems.append(f"status {data.get('status')!r} is not ok/blocked/failed")
    if data.get("status") == "ok" and data.get("next") not in briefs.RESULTS.get(worker, ()):
        problems.append(f"next {data.get('next')!r} is not one of "
                        f"{', '.join(sorted(briefs.RESULTS.get(worker, ())))}")
    return problems


def as_int(data, key):
    try:
        return int(str(data.get(key, "")).strip())
    except ValueError:
        raise Fail(f"`{key}` is {data.get(key)!r}, not a number", FAILED, "MALFORMED") from None


def run_autodev(*args):
    out = subprocess.run([sys.executable, str(SCRIPTS / "autodev.py"), *args],
                         capture_output=True, text=True, check=False)
    return out.returncode, out.stdout, out.stderr


def entries(path):
    text = Path(path).read_text(encoding="utf-8") if Path(path).exists() else ""
    return len(re.findall(r"^\d+\.\s", text, re.MULTILINE))


def derive(worker, n, data, ad, state):
    """Return a list of disagreements between the return and the artifacts."""
    if data.get("status") != "ok":
        return []
    return result_issues(worker, n, data, ad, state) + artifact_issues(
        worker, n, data, ad, state)


def written_files(worker, n, data, ad, state):
    """[(path, required)]: the files this result says the worker wrote."""
    nxt = data.get("next")
    issued = next((b for b in state.get("briefs", [])
                   if b["worker"] == worker and b["n"] == n), {})
    mode, sets = issued.get("mode"), issued.get("sets", {})
    review = ad / "review" / f"pass-{state.get('phase6', {}).get('review_pass', 0)}"
    files = []
    if worker in ("define-reviewer", "plan-reviewer"):
        fix = data.get("fix_file", "none")
        if fix not in ("none", ""):
            files.append((Path(fix), True))
    elif worker == "verifier" and nxt not in ("INSTALL_CONFLICT", "MUTATION_LEFT_CHANGES"):
        files.append((ad / "SPEC_EVAL.md", True))
        if nxt == "CORRECT":
            files.append((ad / "evidence" / "corrections.md", True))
    elif worker == "cleanup":
        files += [(ad / "lint" / c["report"], False)
                  for c in state["settings"].get("gate", []) if c.get("report")]
    elif worker == "code-reviewer" and sets.get("reviewer"):
        name = "VOTES-" if mode == "re-vote" else ""
        files.append((review / f"{name}{sets['reviewer']}.md", True))
    elif worker == "review-judge":
        if mode == "security-verify":
            files.append((ad / "SECURITY_REVIEW.md", True))
            files.append((ad / "review" / "security-corrections.md", False))
        else:
            files.append((ad / "CODE_REVIEW.md", True))
            files.append((review / "corrections.md", nxt == "MUST_FIX"))
    elif worker in ("security-reviewer", "security-reviewer-sensitive"):
        files.append((ad / "SECURITY_REVIEW.md", True))
    elif worker == "triager":
        files.append((ad / "triage" / f"{mode or 'triage'}-{n}.md", nxt == "CODE"))
    return files


def artifact_issues(worker, n, data, ad, state):
    """Each file the worker wrote must follow its template; the files the coder
    is briefed with must not copy SPEC.md's wording."""
    issues = []
    for path, required in written_files(worker, n, data, ad, state):
        if not path.exists():
            if required:
                issues.append(f"{path} does not exist")
            continue
        issues += [f"{path.name}: {p}" for p in check_file(path)]
    spec = ad / "SPEC.md"
    coder_bound = {"planner": ad / "IMPLEMENTATION.md",
                   "verifier": ad / "evidence" / "corrections.md"}.get(worker)
    if coder_bound and coder_bound.exists() and spec.exists() and data.get("next") in (
            "WRITTEN", "REVISED", "PLAN_REVISED", "UPDATE_OLD_TEST", "CORRECT"):
        issues += [f"{coder_bound.name} copies SPEC.md's wording ({hit}): the coder never "
                   "sees SPEC.md, so say what the code must do in your own words"
                   for hit in overlaps(coder_bound, spec)]
    return issues


def result_issues(worker, n, data, ad, state):
    nxt = data.get("next")
    issues = []
    if worker == "define":
        if nxt in ("FITS", "OVERSIZED"):
            conds = art.spec_conditions(ad / "SPEC.md")
            has_security = any(c["id"].startswith("S") for c in conds)
            if has_security and data.get("high_risk") != "yes":
                issues.append("SPEC.md has Security/Compliance criteria but high_risk is not yes")
    elif worker in ("define-reviewer", "plan-reviewer"):
        blockers = as_int(data, "blockers")
        if (nxt == "CLEAN") != (blockers == 0):
            issues.append(f"next is {nxt} but blockers is {blockers}")
        fix = data.get("fix_file", "none")
        if fix not in ("none", "") and not Path(fix).exists():
            issues.append(f"fix_file {fix} does not exist")
    elif worker == "planner" and nxt in ("WRITTEN", "REVISED", "PLAN_REVISED", "UPDATE_OLD_TEST"):
        issues += [f"IMPLEMENTATION.md: {p}" for p in check_file(ad / "IMPLEMENTATION.md")]
    elif worker == "acceptance-tester" and nxt in ("SEALED", "REPAIRED"):
        # Gaps are not a disagreement: `next` re-spawns the tester for them.
        art.manifest(ad / "acceptance" / "MANIFEST.md")
    elif worker == "coder":
        if (nxt == "BLOCKED") != (as_int(data, "blocked") > 0):
            issues.append(f"next is {nxt} but blocked is {data.get('blocked')}")
        listed = ad / "blocked" / f"coder-{n}.md"
        if nxt == "BLOCKED" and not listed.exists():
            issues.append(f"next is BLOCKED but {listed} does not exist")
    elif worker == "verifier":
        flags = {"INSTALL_CONFLICT": "--install-conflict",
                 "MUTATION_LEFT_CHANGES": "--mutation-left-changes"}
        if nxt not in flags:
            code, out, err = run_autodev("eval-status", "--dir", str(ad))
            decision = out.split(":", 1)[0].strip() if code == 0 else f"error: {err.strip()}"
            if decision != nxt:
                issues.append(f"next is {nxt} but eval-status says {decision}")
            if nxt == "CORRECT" and entries(ad / "evidence" / "corrections.md") == 0:
                issues.append("next is CORRECT but evidence/corrections.md has no entries")
    elif worker == "cleanup":
        failing = [c.get("report", "") for c in state["settings"].get("gate", [])
                   if not lint_passes(ad / "lint" / c.get("report", ""))]
        if (nxt == "GREEN") != (not failing):
            issues.append(f"next is {nxt} but these lint reports don't pass: "
                          f"{', '.join(failing) or 'none'}")
    elif worker == "review-judge" and nxt in ("CLEAN", "MUST_FIX", "REVOTE"):
        text = art.read(ad / "CODE_REVIEW.md")
        open_rows = count_open(text)
        if as_int(data, "must_fix_open") != open_rows:
            issues.append(f"must_fix_open is {data.get('must_fix_open')} but CODE_REVIEW.md "
                          f"has {open_rows} open must-fix rows")
    elif worker == "triager":
        issued = next((b for b in state.get("briefs", [])
                       if b["worker"] == worker and b["n"] == n), {})
        mine = ad / "triage" / f"{issued.get('mode') or 'triage'}-{n}.md"
        if nxt == "CODE" and not entries(mine):
            issues.append(f"next is CODE but {mine.name} holds no required change")
        blockers = as_int(data, "blockers") + as_int(data, "acceptance_checks")
        if blockers and not entries(mine):
            issues.append(f"{blockers} blocker(s) or check comment(s) but {mine.name} "
                          "holds no required change")
    elif worker == "lookup" and nxt == "ANSWERED":
        if not Path(data.get("answer_file", "")).exists():
            issues.append("answer_file does not exist")
    return issues


def lint_passes(path):
    if not path.exists():
        return False
    first = path.read_text(encoding="utf-8").splitlines()[:1]
    return bool(first) and first[0].rstrip().endswith("pass")


def count_open(text):
    body = art.find_section(text, "Must-fix") or ""
    for header, rows in art.tables(body):
        if "Status" in header:
            return sum(1 for r in rows if r.get("Status", "").strip().startswith("open"))
    return 0


def record(args):
    try:
        state = st.load(args.dir)
    except st.StateError as exc:
        raise Fail(str(exc), CANNOT_RUN, "ERROR") from None
    ad = Path(state["artifact_dir"])
    data = load_return(ad, args.worker, args.n)
    try:
        issues = derive(args.worker, args.n, data, ad, state)
    except art.ArtifactError as exc:
        issues = [str(exc)]
    if issues:
        emit(args.json, "MISMATCH", f"{args.worker}-{args.n}: the return and the artifacts "
             "disagree; re-spawn the worker with these issues, don't guess",
             returned=json.dumps(data), issue=issues)
        return FAILED
    if args.worker == "define" and data.get("next") in ("FITS", "OVERSIZED"):
        state["size"] = data["next"]
        state["high_risk"] = data.get("high_risk") == "yes"
        if data["next"] == "OVERSIZED":
            st.set_phase(state, 2, "stopped", "OVERSIZED")
            for number in (3, 4, 5, 6):
                st.set_phase(state, number, "n/a", "")
        elif state["high_risk"]:
            state["settings"]["post_plan_gate"] = True
    issued = next((b for b in state.get("briefs", [])
                   if b["worker"] == args.worker and b["n"] == args.n), {})
    log = state.setdefault("log", [])
    log[:] = [e for e in log if not (e["worker"] == args.worker and e["n"] == args.n)]
    log.append({"worker": args.worker, "n": args.n, "mode": issued.get("mode"),
                "sets": issued.get("sets", {}), "status": data.get("status"),
                "next": data.get("next", ""), "data": data,
                "seq": st.seq(state)})
    st.add_note(state, f"{args.worker} #{args.n} returned {data.get('status')} "
                f"{data.get('next', '')}".rstrip())
    st.save(args.dir, state)
    emit(args.json, "RECORDED", f"{args.worker}-{args.n}", status=data.get("status"),
         next=data.get("next", ""))
    return 0


# ---------------------------------------------------------------- check-artifact

def check_file(path):
    """Problems with one artifact, by its name; [] when it follows its template."""
    path = Path(path)
    name, parent = path.name, path.parent.name
    try:
        text = art.read(path)
    except art.ArtifactError as exc:
        return [str(exc)]
    try:
        if name == "SPEC.md":
            return check_spec(path)
        if name == "IMPLEMENTATION.md":
            heads = [ln.strip() for ln in text.splitlines() if ln.startswith("## ")]
            want = list(IMPLEMENTATION_HEADINGS)
            return [] if [h for h in heads if h in want] == want else [
                f"headings must be, in order: {', '.join(want)} (found: {', '.join(heads)})"]
        if name == "MANIFEST.md":
            rows, _ = art.manifest(path)
            return [f"row {r['#']}: Kind `{r['Kind']}` is not fail-to-pass/pass-to-pass"
                    for r in rows if r["Kind"].strip() not in ("fail-to-pass", "pass-to-pass")]
        if name == "SPEC_EVAL.md":
            ev = art.spec_eval(path)
            problems = [f"row {r['#']}: verdict `{r['Verdict']}` is not one of "
                        f"{', '.join(sorted(VERDICTS))}" for r in ev["rows"]
                        if r["Verdict"].strip().lower() not in VERDICTS]
            if not art.header_line(text, "Tree:"):
                problems.append("no `Tree:` line")
            return problems
        if name == "CODE_REVIEW.md":
            return need_lines(text, ("**Overall confidence", "Latest pass:", "Tree:",
                                     "Must-fix:")) + need_sections(
                text, ("Must-fix", "Pending re-vote", "Advisory", "Noise", "Passes"))
        if name == "SECURITY_REVIEW.md":
            return need_lines(text, ("**Overall confidence", "Tree:", "Must-fix:")) + \
                need_sections(text, ("Findings", "Coverage"))
        if parent == "lint":
            first = text.splitlines()[:1]
            problems = [] if first and re.match(r"^# .+ — (pass|fail)\s*$", first[0]) else [
                "first line must be `# <CHECK> — pass` or `— fail`"]
            return problems + ([] if "Tree:" in text else ["no `Tree:` line"])
        if re.match(r"R\d\.md$", name):
            return need_sections(text, ("Findings", "Security leads", "Pre-existing"))
        if re.match(r"VOTES-R\d\.md$", name):
            art.first_table(text, ("Finding", "Vote", "Reason"), str(path))
            return []
        if name.endswith("corrections.md") or parent == "triage":
            return check_corrections(text)
        if parent == "fixes":
            blocks = FIX_RE.findall(text)
            declared = len(re.findall(r"^FIX\s+\S+", text, re.MULTILINE))
            if not blocks:
                return ["no FIX block"]
            return [] if declared == len(blocks) else [
                f"{declared} FIX headers but only {len(blocks)} well-formed blocks"]
        if parent == "returns" and name.endswith(".json"):
            data = json.loads(text)
            return return_problems(data.get("worker", ""), data)
    except art.ArtifactError as exc:
        return [str(exc)]
    except ValueError as exc:
        return [f"not valid JSON: {exc}"]
    return [f"no template is known for {name}"]


def check_spec(path):
    problems = []
    for c in art.spec_conditions(path):
        needed = ("example", "verify") if c["id"].startswith("S") else ("example", "edge", "verify")
        for key in needed:
            if not c[key]:
                label = {"verify": "Verify by"}.get(key, key.title())
                problems.append(f"condition {c['id']} has no `{label}:` line")
    return problems


def check_corrections(text):
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines or lines[0].strip() != "# Required changes":
        return ["the first line must be `# Required changes`"]
    body = "\n".join(lines[1:]).strip()
    if body == "None.":
        return []
    if not re.search(r"^\d+\.\s", body, re.MULTILINE):
        return ["no numbered entry, and not `None.`"]
    return []


def need_lines(text, prefixes):
    return [f"no `{p}` line" for p in prefixes if not art.header_line(text, p)]


def need_sections(text, names):
    found = art.sections(text)
    return [f"no `## {n}` section" for n in names
            if not any(h.startswith(n) for h in found)]


def check_artifact(args):
    if not Path(args.file).exists():
        raise Fail(f"{args.file} does not exist", CANNOT_RUN, "ERROR")
    problems = check_file(args.file)
    if problems:
        emit(args.json, "PROBLEMS", f"{args.file} does not follow its template",
             problem=problems)
        return FAILED
    emit(args.json, "OK", f"{args.file} follows its template")
    return 0
