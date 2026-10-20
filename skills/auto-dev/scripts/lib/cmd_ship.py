"""autodev.py commit / ci-watch / merge-staging / merge-pr / pr-body --check / cleanup-worktree.

Phase 6's git and gh steps. Each takes `--dir <artifact-dir>` (default
`./.auto-dev`) and `--json`, re-reads git and gh rather than trusting the stored
state, and records what it did in state.json.

commit --message "<type>(<scope>): <summary>" [--body TEXT]
    Re-checks that every report checked the code as it is now (check-fresh.py),
    stages every changed path outside .auto-dev/ by name (deleted paths with
    `git rm --cached`), runs check-staged.py on exactly that list, commits, then
    checks the commit carries the checked code (check-fresh.py --ref HEAD) and
    records it as the verified commit. Unstages everything it staged if any
    step before the commit fails.
    Exit: 0 committed and verified (push it); 1 refused: stale results (re-run
    them and ask the PR gate again), nothing to commit, staged-set check or the
    commit failed; 3 committed but NOT verified: do not push, stop and report.

ci-watch [--pr N] [--max-wait SECONDS] [--interval SECONDS] [--grace SECONDS]
    Polls the PR's checks with `gh pr checks` (GitHub Actions, and CircleCI or
    other CI that reports to GitHub). Gives up after --max-wait (default 540,
    under the Bash tool's limit) and says to call again; the overall bound is
    the profile's CI timeout, counted from the first watch of this commit. "No
    checks reported" is pending for --grace seconds (default 300), then the
    watcher is unavailable. CI provider `none` skips the watch.
    Exit: 0 green, or skipped (CI: none); 1 red: the failing checks are printed
    with their links; 3 pending (call again) or timed out (TIMEOUT: hold at the
    gate); 4 the watcher is unavailable (no checks after the grace period, or a
    provider gh cannot see): hold at the gate, never assume green.

merge-staging
    Merges the branch into the staging branch directly (fetch, detach at
    origin/<staging>, merge, push without --force) and always switches back to
    the branch. Exit: 0 merged and pushed; 1 conflict (merge aborted) or no
    staging branch; 3 push rejected.

merge-pr --pr N --sha <checked commit>
    `gh pr merge` with the repo's allowed method (squash first), locked with
    --match-head-commit, never --admin; then confirms the PR state is MERGED.
    Exit: 0 merged; 1 the head moved (re-check the code and ask the main gate
    again); 3 queued or auto-merge enabled, not merged (report and stop; don't
    move Jira); 4 refused (report the requirement blocking it and stop).

pr-body
    Generates the PR description for the verified commit from the run's
    artifacts and templates/pr-body.md, into <artifact-dir>/pr-body.md, leaving
    a `<!-- WRITE: ... -->` line for the Summary and one for the Assumptions.
    Links point at the commit; worktree and home paths are hidden and lines that
    look like secrets dropped; output blocks are cut, then moved to
    pr-output-comment.md, to keep it under 60,000 characters. `next` runs it.
    Exit: 0 written; 1 no verified commit yet.

pr-body --check <file>
    Lints a PR description before it is published: the strict sections and the
    attribution line are present, `Checked at commit <sha>` names the verified
    commit, it is under 60,000 characters, and it holds no `.auto-dev/` path, no
    condition or finding IDs, no pipeline terms, no absolute worktree or home
    path and nothing that looks like a secret.
    Exit: 0 clean; 1 problems (each printed).

cleanup-worktree
    Removes the run's worktree from the main checkout with `git worktree
    remove` (never --force). Only after the final report: it deletes
    .auto-dev/. Exit: 0 removed; 1 git refused (files are listed; leave it).

All of them exit 2 when they could not run (no state, git or gh missing) —
never a pass.
"""

import json
import os
import re
import sys
import time
from pathlib import Path

from . import state as st
from .output import CANNOT_RUN, FAILED, Fail, emit
from .proc import git, run

SCRIPTS = Path(__file__).resolve().parent.parent
ARTIFACTS = ".auto-dev/"
TRAILER = "Co-Authored-By: Claude Code <noreply@anthropic.com>"
EXIT_NOT_VERIFIED = EXIT_PENDING = EXIT_QUEUED = EXIT_PUSH_REJECTED = 3
EXIT_UNAVAILABLE = EXIT_REFUSED = 4
BODY_LIMIT = 60000
STRICT_HEADINGS = ("## Acceptance conditions", "### Checks for a person",
                   "### Changes to tests", "### Test strength", "## Quality gate",
                   "## Review")
ATTRIBUTION = "Generated with [Claude Code](https://claude.com/claude-code)"
ID_RE = re.compile(r"\b(?:C|CS|M|S)\d+\b")
TERMS_RE = re.compile(r"\b(held-out|fail-to-pass|pass-to-pass|verifier|mutants?)\b",
                      re.IGNORECASE)
TIER_RE = re.compile(r"\b(Strong|Adequate|Weak)\b")
SECRET_RE = re.compile(r"(gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*"
                       r"PRIVATE KEY|xox[baprs]-[A-Za-z0-9-]{10,}|"
                       r"(?:password|passwd|secret|token)\s*[=:]\s*\S{6,})",
                       re.IGNORECASE)
CHECKED_RE = re.compile(r"Checked at commit\s+([0-9a-f]{7,64})")


def add_arguments(parser, name):
    parser.add_argument("--dir", default=".auto-dev", help="the run's .auto-dev/")
    if name == "commit":
        parser.add_argument("--message", required=True, help="the commit subject")
        parser.add_argument("--body", default="")
    elif name == "ci-watch":
        parser.add_argument("--pr", help="the PR number (default: from state)")
        parser.add_argument("--max-wait", type=int, default=540)
        parser.add_argument("--interval", type=int, default=30)
        parser.add_argument("--grace", type=int, default=300)
    elif name == "merge-pr":
        parser.add_argument("--pr", required=True)
        parser.add_argument("--sha", required=True, help="the checked commit")
    elif name == "pr-body":
        parser.add_argument("--check", metavar="FILE",
                            help="the PR description to lint")


def load(args):
    try:
        return st.load(args.dir)
    except st.StateError as exc:
        raise Fail(str(exc), CANNOT_RUN, "ERROR") from None


def check_fresh(worktree, artifact_dir, *extra):
    code, out, err = run([sys.executable, str(SCRIPTS / "check-fresh.py"),
                          worktree, artifact_dir, *extra], check=False)
    if code == 2:
        raise Fail(f"check-fresh.py could not run: {err.strip()}", CANNOT_RUN, "ERROR")
    return code, (err or out).strip()


def changed_paths(worktree):
    """(paths to add, paths to remove from the index) outside .auto-dev/."""
    out = git(worktree, "status", "--porcelain=v1", "-z", "--untracked-files=all",
              "--no-renames", "--ignore-submodules=dirty")
    add, remove = [], []
    for entry in out.split("\0"):
        if len(entry) < 4:
            continue
        code, path = entry[:2], entry[3:]
        if path.startswith(ARTIFACTS):
            continue
        if "D" in code and not Path(worktree, path).exists():
            remove.append(path)
        else:
            add.append(path)
    return add, remove


def unstage(worktree, paths):
    if paths:
        git(worktree, "reset", "-q", "--", *paths, check=False)


def commit(args):
    state = load(args)
    try:
        return make_commit(args, state)
    except Fail as exc:
        if exc.code != CANNOT_RUN:
            state.setdefault("phase6", {})["commit_attempt"] = {
                "result": exc.token.lower(), "seq": st.seq(state)}
            st.save(args.dir, state)
        raise


def make_commit(args, state):
    wt, ad = state["worktree"], state["artifact_dir"]
    code, detail = check_fresh(wt, ad)
    if code != 0:
        raise Fail(f"results are stale; re-run them and ask the PR gate again:\n{detail}",
                   FAILED, "STALE")
    add, remove = changed_paths(wt)
    if not add and not remove:
        raise Fail("nothing to commit", FAILED, "NOTHING")
    staged = add + remove
    try:
        if add:
            git(wt, "add", "--", *add)
        if remove:
            git(wt, "rm", "-q", "--cached", "--ignore-unmatch", "--", *remove)
        code, out, err = run([sys.executable, str(SCRIPTS / "check-staged.py"), wt,
                              "--expect", *staged], check=False)
        if code != 0:
            raise Fail(f"check-staged.py exited {code}:\n{(err or out).strip()}",
                       CANNOT_RUN if code == 2 else FAILED, "NOT-CLEAN")
        message = ["-m", args.message] + (["-m", args.body] if args.body else [])
        code, out, err = git(wt, "commit", "-q", *message, "-m", TRAILER, check=False)
        if code != 0:
            raise Fail(f"git commit failed: {(err or out).strip()}", FAILED, "COMMIT-FAILED")
    except Fail:
        unstage(wt, staged)
        raise
    sha = git(wt, "rev-parse", "HEAD").strip()
    code, detail = check_fresh(wt, ad, "--ref", "HEAD")
    phase6 = state.setdefault("phase6", {})
    if code != 0:
        phase6["unverified_commit"] = sha
        phase6["commit_attempt"] = {"result": "not-verified", "seq": st.seq(state)}
        st.add_note(state, f"commit {sha} holds code no result checked; not pushed")
        st.save(args.dir, state)
        emit(args.json, "NOT-VERIFIED", f"commit {sha} holds code no result checked: "
             "do not push; stop and report", detail=detail)
        return EXIT_NOT_VERIFIED
    phase6["verified_sha"] = sha
    phase6["commit_seq"] = st.seq(state)
    st.add_note(state, f"verified commit {sha}")
    st.save(args.dir, state)
    emit(args.json, "COMMITTED", sha, paths=len(staged),
         next="push with `git push -u origin HEAD` (never --force)")
    return 0


def gh_json(cwd, *args):
    code, out, err = run(["gh", *args], cwd=cwd, check=False)
    return code, out, err


def ci_watch(args):
    state = load(args)
    wt = state["worktree"]
    provider = state["settings"].get("ci", "none")
    if provider == "none":
        emit(args.json, "SKIPPED", "CI: none — no CI to watch; say so at the gate")
        return 0
    if provider == "gitlab":
        state.setdefault("phase6", {})["ci"] = {
            "sha": git(wt, "rev-parse", "HEAD").strip(), "status": "unavailable",
            "failing": [], "seq": st.seq(state)}
        st.save(args.dir, state)
        emit(args.json, "UNAVAILABLE", "ci-watch reads GitHub checks only; GitLab CI "
             "can't be watched here: hold at the gate and say CI was not monitored")
        return EXIT_UNAVAILABLE
    pr = args.pr or state.get("phase6", {}).get("pr")
    if not pr:
        raise Fail("no PR number: pass --pr", CANNOT_RUN, "ERROR")
    sha = git(wt, "rev-parse", "HEAD").strip()
    phase6 = state.setdefault("phase6", {})
    ci = phase6.get("ci") or {}
    if ci.get("sha") != sha:
        ci = {"sha": sha, "started": time.time()}
    timeout = state["settings"].get("ci_timeout", 30) * 60
    deadline = time.monotonic() + max(args.max_wait, 0)
    while True:
        status, failing, detail = poll_checks(wt, pr)
        elapsed = time.time() - ci["started"]
        if status == "none" and elapsed > args.grace:
            status = "unavailable"
        if status in ("green", "red", "unavailable") or elapsed > timeout \
                or time.monotonic() >= deadline:
            break
        time.sleep(max(args.interval, 1))
    if status not in ("green", "red", "unavailable") and elapsed > timeout:
        status = "timeout"
    ci["status"], ci["failing"], ci["seq"] = status, failing, st.seq(state)
    phase6["ci"] = ci
    st.save(args.dir, state)
    if status == "green":
        emit(args.json, "GREEN", f"all checks passed on {sha[:12]}")
        return 0
    if status == "red":
        emit(args.json, "RED", f"checks failed on {sha[:12]}", failing=failing)
        return FAILED
    if status == "unavailable":
        emit(args.json, "UNAVAILABLE", "no checks reported after the grace period: CI "
             "can't be watched; hold at the gate and say CI was not monitored",
             detail=detail)
        return EXIT_UNAVAILABLE
    if status == "timeout":
        emit(args.json, "TIMEOUT", f"CI still running after {timeout // 60} min: hold "
             "at the gate with what is still running", pending=failing)
        return EXIT_PENDING
    emit(args.json, "PENDING", "CI still running: run ci-watch again", pending=failing)
    return EXIT_PENDING


def poll_checks(cwd, pr):
    """('green'|'red'|'pending'|'none', [lines], detail)."""
    code, out, err = gh_json(cwd, "pr", "checks", str(pr), "--json",
                             "name,state,bucket,link")
    if "no checks reported" in (out + err).lower():
        return "none", [], (out + err).strip()
    try:
        checks = json.loads(out)
    except ValueError:
        if code == 127:
            raise Fail("gh is not installed", CANNOT_RUN, "ERROR") from None
        raise Fail(f"gh pr checks failed (exit {code}): {(err or out).strip()}",
                   CANNOT_RUN, "ERROR") from None
    if not checks:
        return "none", [], "no checks"
    buckets = {c.get("bucket", "") for c in checks}
    failed = [f"{c['name']} — {c.get('link', '')}"
              + (" (cancelled: likely infrastructure)" if c.get("bucket") == "cancel"
                 else "")
              for c in checks if c.get("bucket") in ("fail", "cancel")]
    if failed:
        return "red", failed, ""
    pending = [c["name"] for c in checks if c.get("bucket") == "pending"]
    if pending:
        return "pending", pending, ""
    if buckets <= {"pass", "skipping"}:
        return "green", [], ""
    return "pending", [c["name"] for c in checks], ""


def merge_staging(args):
    state = load(args)
    wt, branch, staging = state["worktree"], state["branch"], state["repo"].get("staging")
    if not staging:
        raise Fail("no staging branch: the staging gate is n/a", FAILED, "NO-STAGING")
    git(wt, "fetch", "origin", staging)
    try:
        merged = staging_merge(wt, branch, staging)
    except Fail as exc:
        state.setdefault("phase6", {})["staging_attempt"] = {
            "result": exc.token.lower(), "seq": st.seq(state)}
        st.save(args.dir, state)
        raise
    state.setdefault("phase6", {})["staging_merge"] = merged
    st.add_note(state, f"merged into {staging} at {merged}")
    st.save(args.dir, state)
    emit(args.json, "MERGED", f"{branch} into {staging} at {merged}",
         next="watch CI on staging; report a failure, don't gate on it")
    return 0


def staging_merge(wt, branch, staging):
    try:
        git(wt, "switch", "-q", "--detach", f"origin/{staging}")
        code, out, err = git(wt, "merge", "--no-edit", branch, check=False)
        if code != 0:
            git(wt, "merge", "--abort", check=False)
            raise Fail(f"merging {branch} into {staging} conflicts; aborted. Never "
                       f"resolve conflicts on staging unasked: report it.\n"
                       f"{(out + err).strip()[-800:]}", FAILED, "CONFLICT")
        merged = git(wt, "rev-parse", "HEAD").strip()
        code, out, err = git(wt, "push", "origin", f"HEAD:{staging}", check=False)
        if code != 0:
            raise Fail(f"push to {staging} rejected; never force it unasked:\n"
                       f"{(out + err).strip()[-800:]}", EXIT_PUSH_REJECTED, "REJECTED")
    finally:
        git(wt, "switch", "-q", branch, check=False)
    return merged


def merge_method(cwd):
    code, out, _ = gh_json(cwd, "repo", "view", "--json",
                           "squashMergeAllowed,mergeCommitAllowed,rebaseMergeAllowed")
    try:
        allowed = json.loads(out) if code == 0 else {}
    except ValueError:
        allowed = {}
    for key, flag in (("squashMergeAllowed", "--squash"),
                      ("mergeCommitAllowed", "--merge"),
                      ("rebaseMergeAllowed", "--rebase")):
        if allowed.get(key):
            return flag
    return "--squash"


def merge_pr(args):
    state = load(args)
    wt = state["worktree"]
    method = merge_method(wt)
    code, out, err = gh_json(wt, "pr", "merge", str(args.pr), method,
                             "--match-head-commit", args.sha)
    text = (out + err).strip()
    if code != 0:
        moved = re.search(r"head (branch )?(was modified|has moved)|not the expected head|"
                          r"match-head-commit|head commit", text, re.IGNORECASE)
        note_merge(args, state, "head-moved" if moved else "refused")
        if moved:
            raise Fail(f"the PR's head is no longer {args.sha}: re-check the code "
                       f"(check-fresh --ref origin/<branch>) and ask the main gate "
                       f"again.\n{text[-500:]}", FAILED, "HEAD-MOVED")
        raise Fail(f"GitHub refused the merge; report the requirement blocking it "
                   f"and stop, leaving the PR open. Never use --admin.\n{text[-800:]}",
                   EXIT_REFUSED, "REFUSED")
    code, out, err = gh_json(wt, "pr", "view", str(args.pr), "--json", "state")
    try:
        pr_state = json.loads(out).get("state", "")
    except ValueError:
        pr_state = ""
    phase6 = state.setdefault("phase6", {})
    if pr_state != "MERGED":
        st.add_note(state, f"PR #{args.pr} queued or set to auto-merge, not merged")
        note_merge(args, state, "queued")
        emit(args.json, "QUEUED", f"PR #{args.pr} is {pr_state or 'not merged'}: "
             "report it and stop; don't move Jira")
        return EXIT_QUEUED
    phase6["merged"] = args.sha
    st.add_note(state, f"PR #{args.pr} merged ({method}) at {args.sha}")
    st.save(args.dir, state)
    emit(args.json, "MERGED", f"PR #{args.pr} ({method.lstrip('-')})")
    return 0


def note_merge(args, state, result):
    """Record a merge attempt that did not merge, for `next`."""
    state.setdefault("phase6", {})["merge_attempt"] = {
        "result": result, "sha": args.sha, "seq": st.seq(state)}
    st.save(args.dir, state)


def pr_body(args):
    state = load(args)
    if not args.check:
        from .cmd_pr import generate
        sha = state.get("phase6", {}).get("verified_sha")
        if not sha:
            raise Fail("no verified commit yet: commit first", FAILED, "NO-COMMIT")
        path = generate(state, Path(state["artifact_dir"]), sha)
        state["phase6"]["body"] = {"sha": sha, "path": str(path), "seq": st.seq(state)}
        st.save(args.dir, state)
        emit(args.json, "WRITTEN", str(path), commit=sha,
             then="write its Summary and Assumptions, then `autodev.py pr publish`")
        return 0
    try:
        text = Path(args.check).read_text(encoding="utf-8")
    except OSError as exc:
        raise Fail(f"cannot read {args.check}: {exc}", CANNOT_RUN, "ERROR") from None
    problems = lint_body(text, state)
    if problems:
        emit(args.json, "PROBLEMS", f"{len(problems)} problem(s) in {args.check}",
             problem=problems)
        return FAILED
    emit(args.json, "CLEAN", f"{args.check}: {len(text)} characters")
    return 0


def lint_body(text, state):
    problems = []
    if len(text) > BODY_LIMIT:
        problems.append(f"{len(text)} characters, over {BODY_LIMIT}: cut output blocks "
                        "to their last 10 lines, then move them to one comment")
    for heading in STRICT_HEADINGS:
        if not re.search(rf"^{re.escape(heading)}\s*$", text, re.MULTILINE):
            problems.append(f"missing the strict heading `{heading}`")
    if ATTRIBUTION not in text:
        problems.append("missing the attribution line")
    checked = CHECKED_RE.search(text)
    verified = state.get("phase6", {}).get("verified_sha")
    if not checked:
        problems.append("missing `Checked at commit <sha>`")
    elif verified and not verified.startswith(checked.group(1)):
        problems.append(f"`Checked at commit {checked.group(1)}` is not the verified "
                        f"commit {verified}")
    if ARTIFACTS in text:
        problems.append("names a .auto-dev/ path, which nobody else can open")
    for pattern, what in ((ID_RE, "a condition or finding ID"),
                          (TERMS_RE, "a pipeline term"),
                          (TIER_RE, "an evidence tier")):
        found = sorted({m.group(0) for m in pattern.finditer(text)})
        if found:
            problems.append(f"uses {what}: {', '.join(found[:5])}")
    for path, what in ((state["worktree"], "the worktree's absolute path"),
                       (os.path.expanduser("~"), "a home directory")):
        if path and path != "/" and path in text:
            problems.append(f"shows {what}; replace it with `.` or `~`")
    secrets = SECRET_RE.findall(text)
    if secrets:
        problems.append(f"{len(secrets)} line(s) look like a secret; drop them")
    return problems


def cleanup_worktree(args):
    state = load(args)
    main_checkout, wt = state["repo"]["main_checkout"], state["worktree"]
    code, out, err = git(main_checkout, "worktree", "remove", wt, check=False)
    if code != 0:
        raise Fail(f"git refused to remove {wt}; leave it in place and report what is "
                   f"there:\n{(err or out).strip()}", FAILED, "REFUSED")
    emit(args.json, "REMOVED", wt)
    return 0
