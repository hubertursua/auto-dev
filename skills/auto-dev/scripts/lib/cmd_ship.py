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
    step before the commit fails. The commit is recorded before it is checked:
    if that check cannot run (exit 2, which names the commit), run `commit`
    again on the clean tree and it checks that commit instead of committing.
    Exit: 0 committed and verified (push it); 1 refused: stale results (re-run
    them and ask the PR gate again), nothing to commit, staged-set check or the
    commit failed; 3 committed but NOT verified: do not push, stop and report.
    A refusal is recorded for `next` as `commit_attempt`, except "nothing to
    commit" (`next` never asks for a commit with nothing changed) and exit 2.

ci-watch [--pr N] [--max-wait SECONDS] [--interval SECONDS] [--grace SECONDS]
    Polls the PR's checks with `gh pr checks` (GitHub Actions, and CircleCI or
    other CI that reports to GitHub). Gives up after --max-wait (default 540,
    under the Bash tool's limit) and says to call again; the overall bound is
    the profile's CI timeout, counted from the first watch of this commit (a
    watch after a final result — green, red, timeout, unavailable — starts the
    clock again). Checks count only once the PR's head on GitHub is the local
    HEAD; until then the watch is pending. "No checks reported", or a PR head
    that is still another commit, is pending for --grace seconds (default 300),
    then the watcher is unavailable. Once the PR is marked ready (`mark
    pr-ready`), green counts only when a check started after the mark, or
    --grace seconds after it: workflows that skip drafts take a moment to
    register, and until then the draft's old checks still read green.
    CI provider `none` skips the watch.
    Exit: 0 green, or skipped (CI: none); 1 red: the failing checks are printed
    with their links; 3 pending (PENDING: call again) or timed out (TIMEOUT:
    CI still running at the profile's CI timeout); 4 the watcher is unavailable
    (no checks after the grace period, or a provider gh cannot see). Whatever
    it exits, run `next`: it asks for `ci-watch` again only while CI is
    PENDING, and after TIMEOUT or UNAVAILABLE the main gate shows CI as not
    monitored. Never assume green.

merge-staging
    Merges the branch into the staging branch directly (fetch, detach at
    origin/<staging>, merge, push without --force) and always switches back to
    the branch. Exit: 0 merged and pushed; 1 conflict (merge aborted) or no
    staging branch; 3 push rejected; 2 git could not run (not recorded as an
    attempt).

merge-pr --pr N --sha <checked commit>
    `gh pr merge` with the repo's allowed method (squash first), locked with
    --match-head-commit, never --admin; then confirms the PR state is MERGED.
    Exit: 0 merged; 1 the head moved (re-check the code and ask the main gate
    again); 2 could not run: gh missing, signed out, offline or too old, the
    repo's merge methods unreadable, or the merge succeeded but the PR's state
    could not be read (it says so, and records the merge as `unknown`, so
    `next` never offers it again); 3 queued or auto-merge
    enabled, not merged (report and stop; don't move Jira); 4 refused (report
    the requirement blocking it and stop).

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
    commit, it is under 60,000 characters, and it holds no `.auto-dev/` path,
    none of the run's own condition, finding or mutant IDs (those its artifacts
    define), no "held-out" / "fail-to-pass" / "pass-to-pass", no evidence tier
    used as one, no absolute worktree or home path and nothing that looks like
    a secret.
    Exit: 0 clean; 1 problems (each printed).

cleanup-worktree
    Removes the run's worktree from the main checkout with `git worktree
    remove` (never --force). Only after the final report: it deletes
    .auto-dev/. Exit: 0 removed; 1 git refused (files are listed; leave it).

All of them exit 2 when they could not run (no state, git or gh missing, an
unexpected error) — never a pass.
"""

import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from . import state as st
from .output import CANNOT_RUN, FAILED, Fail, emit
from .proc import CommandError, git, run

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
# The ID forms the run's artifacts use: condition (C1, CS1), finding (C1, S1)
# and mutant (M1) numbers. Only the IDs this run's artifacts define are flagged,
# so "S3" or "M1" in ordinary prose passes unless the run has such an item.
ID_FORM = r"(?:CS|C|M|S)\d+"
ID_DEF_RE = re.compile(rf"^\s*\|\s*({ID_FORM})\s*\||^#+\s*({ID_FORM})\b|"
                       rf"^\s*({ID_FORM})\.\s", re.MULTILINE)
ID_SOURCES = ("SPEC.md", "acceptance/MANIFEST.md", "SPEC_EVAL.md", "CODE_REVIEW.md",
              "SECURITY_REVIEW.md")
ID_USE_RE = re.compile(rf"(?<![\w/.-])({ID_FORM})(?![\w-])")
# Terms only the pipeline uses; words like "verifier" are ordinary English.
TERMS_RE = re.compile(r"\b(held-out|fail-to-pass|pass-to-pass)\b", re.IGNORECASE)
# An evidence tier only where it reads as one: a table cell, bold, or next to
# "tier" or "evidence". "Strong passwords" is prose.
TIERS = r"(?:Strong|Adequate|Weak)"
TIER_RE = re.compile(rf"\|\s*{TIERS}\s*\||\*\*{TIERS}\*\*|"
                     rf"\b{TIERS}\s+(?i:tier|evidence)\b|"
                     rf"\b(?i:tier)\s*[:=(]?\s*{TIERS}\b")
# A secret's value: quoted, or 6+ non-space characters, except what reads as a
# type annotation: a common type name (`token: string`), or an identifier
# followed by `;` `,` `}` or `)` (`{ token: Token }`, `f(password: Secret)`).
TYPE_NAMES = (r"(?:string|number|boolean|bool|str|int|float|bytes|any|unknown|object|"
              r"null|undefined|none|optional|secretstr)")
SECRET_VALUE = (r"(?:[\"'][^\"'\s]{6,}[\"']|"
                r"(?!" + TYPE_NAMES + r"(?!\w))(?![A-Za-z_][\w.]*\s*[;,})])\S{6,})")
SECRET_RE = re.compile(r"(gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*"
                       r"PRIVATE KEY|xox[baprs]-[A-Za-z0-9-]{10,}|"
                       r"(?:password|passwd|secret|token|api[_-]?key)\s*[=:]\s*"
                       + SECRET_VALUE + ")", re.IGNORECASE)
CHECKED_RE = re.compile(r"Checked at commit\s+([0-9a-f]{7,64})")
# gh failing before GitHub answered: misused, signed out, or offline. Checked
# before HEAD_MOVED_RE, since gh's usage text names --match-head-commit.
GH_BROKEN_RE = re.compile(
    r"unknown (flag|command|shorthand flag)|^usage:|\bUsage:|accepts \d+ arg|"
    r"not logged in|gh auth login|authentication (failed|required)|bad credentials|"
    r"HTTP 401|could not resolve host|no such host|connection (refused|reset|timed out)|"
    r"network is unreachable|i/o timeout|TLS handshake timeout|dial tcp|"
    r"error connecting to|check your internet connection|githubstatus\.com|"
    r"HTTP 5\d\d|context deadline exceeded",
    re.IGNORECASE | re.MULTILINE)
HEAD_MOVED_RE = re.compile(r"head (branch )?(was modified|has moved)|not the expected head|"
                           r"expected head (sha|oid)", re.IGNORECASE)
# A stored CI status that ends a watch: watching the same commit again starts anew.
FINAL_CI = ("green", "red", "unavailable", "timeout")
GH_MIN_WAIT, GH_MAX_WAIT = 10, 60  # seconds one gh call may take during a watch


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
    # surrogateescape: a file name that isn't UTF-8 is read without crashing and
    # passed back to git as the same bytes.
    out = git(worktree, "status", "--porcelain=v1", "-z", "--untracked-files=all",
              "--no-renames", "--ignore-submodules=dirty", errors="surrogateescape")
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
        if exc.code != CANNOT_RUN and exc.token != "NOTHING":
            state.setdefault("phase6", {})["commit_attempt"] = {
                "result": exc.token.lower(), "seq": st.seq(state)}
            st.save(args.dir, state)
        raise


def make_commit(args, state):
    wt, ad = state["worktree"], state["artifact_dir"]
    add, remove = changed_paths(wt)
    phase6 = state.setdefault("phase6", {})
    unverified = phase6.get("unverified_commit")
    if not add and not remove and unverified \
            and git(wt, "rev-parse", "HEAD").strip() == unverified:
        # An earlier run committed but could not finish checking the commit.
        return verify_commit(args, state, unverified, 0)
    code, detail = check_fresh(wt, ad)
    if code != 0:
        raise Fail(f"results are stale; re-run them and ask the PR gate again:\n{detail}",
                   FAILED, "STALE")
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
    except BaseException:  # any failure before the commit leaves nothing staged
        unstage(wt, staged)
        raise
    sha = git(wt, "rev-parse", "HEAD").strip()
    # Record the commit before checking it, so a check that cannot run (or a
    # killed process) leaves state describing the commit; a re-run verifies it.
    phase6["unverified_commit"] = sha
    st.add_note(state, f"committed {sha}; checking it carries the checked code")
    st.save(args.dir, state)
    return verify_commit(args, state, sha, len(staged))


def verify_commit(args, state, sha, paths):
    """Check the commit carries the checked code; record it as verified or not."""
    wt, ad = state["worktree"], state["artifact_dir"]
    phase6 = state.setdefault("phase6", {})
    code, out, err = run([sys.executable, str(SCRIPTS / "check-fresh.py"), wt, ad,
                          "--ref", sha], check=False)
    detail = (err or out).strip()
    if code not in (0, 1):
        raise Fail(f"commit {sha} was made, but check-fresh.py could not check it "
                   f"(exit {code}): {detail}\nDo not push. Fix that, then run "
                   "`autodev.py commit` again: it checks this commit without "
                   "committing again.", CANNOT_RUN, "ERROR")
    if code != 0:
        phase6["commit_attempt"] = {"result": "not-verified", "seq": st.seq(state)}
        st.add_note(state, f"commit {sha} holds code no result checked; not pushed")
        st.save(args.dir, state)
        emit(args.json, "NOT-VERIFIED", f"commit {sha} holds code no result checked: "
             "do not push; stop and report", detail=detail)
        return EXIT_NOT_VERIFIED
    phase6.pop("unverified_commit", None)
    phase6["verified_sha"] = sha
    phase6["commit_seq"] = st.seq(state)
    st.add_note(state, f"verified commit {sha}")
    st.save(args.dir, state)
    emit(args.json, "COMMITTED", sha, paths=paths,
         next="push with `git push -u origin HEAD` (never --force)")
    return 0


def gh_json(cwd, *args, timeout=None):
    code, out, err = run(["gh", *args], cwd=cwd, check=False, timeout=timeout)
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
             "can't be watched here: run `next`; the main gate shows CI as not "
             "monitored — never assume green")
        return EXIT_UNAVAILABLE
    pr = args.pr or state.get("phase6", {}).get("pr")
    if not pr:
        raise Fail("no PR number: pass --pr", CANNOT_RUN, "ERROR")
    sha = git(wt, "rev-parse", "HEAD").strip()
    phase6 = state.setdefault("phase6", {})
    ci = phase6.get("ci") or {}
    if ci.get("sha") != sha or ci.get("status") in FINAL_CI:
        ci = {"sha": sha, "started": time.time()}  # a new watch: a fresh clock
    # Saved before polling, so a watch killed mid-way still counts its time.
    ci["status"] = "pending"
    phase6["ci"] = ci
    st.save(args.dir, state)
    timeout = state["settings"].get("ci_timeout", 30) * 60
    deadline = time.monotonic() + max(args.max_wait, 0)
    ready = epoch((state.get("marks") or {}).get("pr-ready", {}).get("at"))
    while True:
        status, failing, detail = poll_checks(wt, pr, sha, deadline, ready)
        if status == "stale-green":  # only the draft's checks so far
            status = "green" if time.time() - ready > args.grace else "pending"
            detail = ("no check has started since the PR was marked ready; the draft's "
                      "checks are green" if status == "pending" else "")
        elapsed = time.time() - ci["started"]
        if status in ("none", "elsewhere") and elapsed > args.grace:
            status = "unavailable"
        if status in ("green", "red", "unavailable") or elapsed > timeout:
            break
        left = deadline - time.monotonic()
        if left <= 0:
            break
        time.sleep(min(max(args.interval, 1), left))
    if status not in ("green", "red", "unavailable") and elapsed > timeout:
        status = "timeout"
    ci["status"] = "pending" if status in ("none", "elsewhere") else status
    ci["failing"], ci["seq"] = failing, st.seq(state)
    phase6["ci"] = ci
    st.save(args.dir, state)
    if status == "green":
        emit(args.json, "GREEN", f"all checks passed on {sha[:12]}")
        return 0
    if status == "red":
        emit(args.json, "RED", f"checks failed on {sha[:12]}", failing=failing)
        return FAILED
    if status == "unavailable":
        what = (detail if detail.startswith("the PR's head") else
                "no checks reported after the grace period")
        emit(args.json, "UNAVAILABLE", f"{what}: CI can't be watched for {sha[:12]}: "
             "run `next`; the main gate shows CI as not monitored — never assume green",
             detail=detail)
        return EXIT_UNAVAILABLE
    if status == "timeout":
        emit(args.json, "TIMEOUT", f"CI still running for {sha[:12]} after "
             f"{timeout // 60} min: run `next`; the main gate shows CI as not monitored "
             "— never assume green", pending=failing, detail=detail)
        return EXIT_PENDING
    emit(args.json, "PENDING", "CI still running: run ci-watch again", pending=failing,
         detail=detail)
    return EXIT_PENDING


def gh_poll(cwd, deadline, *args):
    """One bounded gh call for a poll: (code, out, err); a timeout is code 124."""
    left = deadline - time.monotonic()
    code, out, err = gh_json(cwd, *args, timeout=min(max(left, GH_MIN_WAIT), GH_MAX_WAIT))
    if code == 127:
        raise Fail("gh is not installed", CANNOT_RUN, "ERROR")
    return code, out, err


def epoch(stamp):
    """An ISO 8601 time (`...Z` or `+00:00`) as seconds since the epoch, or None."""
    if not stamp:
        return None
    try:
        return datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def poll_checks(cwd, pr, sha, deadline, ready=None):
    """('green'|'red'|'pending'|'none'|'elsewhere'|'stale-green', [lines], detail).

    `gh pr checks` reports the PR's head on GitHub, so it counts only once that
    head is `sha`; until then the poll is 'elsewhere' (pending), never another
    commit's result. With `ready` (when the PR was marked ready, in epoch
    seconds), all-green checks none of which started after it are 'stale-green'.
    """
    code, out, err = gh_poll(cwd, deadline, "pr", "view", str(pr), "--json", "headRefOid")
    if code == 124:
        return "pending", [], "gh timed out; still waiting"
    try:
        head = json.loads(out).get("headRefOid", "")
    except (ValueError, AttributeError):
        raise Fail(f"gh pr view {pr} failed (exit {code}): {(err or out).strip()}",
                   CANNOT_RUN, "ERROR") from None
    if head != sha:
        return "elsewhere", [], (f"the PR's head is {head[:12] or 'unknown'}, not the "
                                 f"local HEAD {sha[:12]} (not pushed yet?)")
    code, out, err = gh_poll(cwd, deadline, "pr", "checks", str(pr), "--json",
                             "name,state,bucket,link,startedAt")
    if code == 124:
        return "pending", [], "gh timed out; still waiting"
    if "no checks reported" in (out + err).lower():
        return "none", [], (out + err).strip()
    try:
        checks = json.loads(out)
    except ValueError:
        raise Fail(f"gh pr checks failed (exit {code}): {(err or out).strip()}",
                   CANNOT_RUN, "ERROR") from None
    if not checks:
        return "none", [], "no checks"
    buckets = {c.get("bucket", "") for c in checks}
    failed = [f"{c['name']} — {c.get('link', '')}"
              + (" (cancelled)" if c.get("bucket") == "cancel" else "")
              for c in checks if c.get("bucket") in ("fail", "cancel")]
    if failed:
        return "red", failed, ""
    pending = [c["name"] for c in checks if c.get("bucket") == "pending"]
    if pending:
        return "pending", pending, ""
    if buckets <= {"pass", "skipping"}:
        if ready and not any((epoch(c.get("startedAt")) or 0) > ready for c in checks):
            return "stale-green", [], ""
        return "green", [], ""
    return "pending", [c["name"] for c in checks], ""


def merge_staging(args):
    state = load(args)
    wt, branch, staging = state["worktree"], state["branch"], state["repo"].get("staging")
    if not staging:
        raise Fail("no staging branch: the staging gate is n/a", FAILED, "NO-STAGING")
    try:
        try:
            git(wt, "fetch", "origin", staging)
            merged = staging_merge(wt, branch, staging)
        except CommandError as exc:
            raise Fail(f"git could not run: {exc}", CANNOT_RUN, "ERROR") from None
    except Fail as exc:
        if exc.code != CANNOT_RUN:  # could not run is not an attempt
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


def gh_cannot_run(code, text, what):
    """Raise CANNOT_RUN when gh itself failed (missing, misused, signed out, offline)."""
    if code == 127:
        raise Fail("gh is not installed", CANNOT_RUN, "ERROR")
    if GH_BROKEN_RE.search(text):
        raise Fail(f"{what} could not run (exit {code}): fix gh (signed in, online, a "
                   f"version with this flag), and read the PR's state before running "
                   f"it again:\n{text[-800:]}", CANNOT_RUN, "ERROR")


def merge_method(cwd):
    code, out, err = gh_json(cwd, "repo", "view", "--json",
                             "squashMergeAllowed,mergeCommitAllowed,rebaseMergeAllowed")
    if code == 127:
        raise Fail("gh is not installed", CANNOT_RUN, "ERROR")
    try:
        allowed = json.loads(out) if code == 0 else None
    except ValueError:
        allowed = None
    if not isinstance(allowed, dict):
        raise Fail(f"could not read the repo's allowed merge methods with `gh repo view` "
                   f"(exit {code}): {(err or out).strip()[-500:]}", CANNOT_RUN, "ERROR")
    for key, flag in (("squashMergeAllowed", "--squash"),
                      ("mergeCommitAllowed", "--merge"),
                      ("rebaseMergeAllowed", "--rebase")):
        if allowed.get(key):
            return flag
    raise Fail("`gh repo view` says the repo allows no merge method: check gh's access "
               "to the repo", CANNOT_RUN, "ERROR")


def merge_pr(args):
    state = load(args)
    wt = state["worktree"]
    method = merge_method(wt)
    code, out, err = gh_json(wt, "pr", "merge", str(args.pr), method,
                             "--match-head-commit", args.sha)
    text = (out + err).strip()
    if code != 0:
        gh_cannot_run(code, text, "gh pr merge")  # could not run: not an attempt
        moved = HEAD_MOVED_RE.search(text)
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
        pr_state = json.loads(out).get("state", "") if code == 0 else ""
    except (ValueError, AttributeError):
        pr_state = ""
    phase6 = state.setdefault("phase6", {})
    if not pr_state:
        st.add_note(state, f"gh pr merge succeeded for PR #{args.pr} at {args.sha}, "
                    "but its state could not be read")
        note_merge(args, state, "unknown")  # `next` never offers this merge again
        raise Fail(f"`gh pr merge` succeeded, but `gh pr view {args.pr}` could not read "
                   f"the PR's state (exit {code}): {(err or out).strip()[-500:]}\n"
                   f"Do not merge again: check `gh pr view {args.pr} --json state` and "
                   "report what it says.", CANNOT_RUN, "ERROR")
    if pr_state != "MERGED":
        st.add_note(state, f"PR #{args.pr} queued or set to auto-merge, not merged")
        note_merge(args, state, "queued")
        emit(args.json, "QUEUED", f"PR #{args.pr} is {pr_state}: "
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
    own = run_ids(state.get("artifact_dir"))
    found = sorted({m.group(1) for m in ID_USE_RE.finditer(text)} & own)
    if found:
        problems.append(f"uses a condition or finding ID: {', '.join(found[:5])}")
    for pattern, what in ((TERMS_RE, "a pipeline term"),
                          (TIER_RE, "an evidence tier")):
        found = sorted({m.group(0) for m in pattern.finditer(text)})
        if found:
            problems.append(f"uses {what}: {', '.join(found[:5])}")
    for path, what, whole in ((state["worktree"], "the worktree's absolute path", True),
                              (os.path.expanduser("~"), "a home directory", False)):
        if path_shown(text, path, whole):
            problems.append(f"shows {what}; replace it with `.` or `~`")
    secrets = SECRET_RE.findall(text)
    if secrets:
        problems.append(f"{len(secrets)} line(s) look like a secret; drop them")
    return problems


def run_ids(artifact_dir):
    """The condition, finding and mutant IDs this run's artifacts define."""
    ids = set()
    if not artifact_dir or not Path(artifact_dir).is_dir():
        return ids
    root = Path(artifact_dir)
    for name in ID_SOURCES:
        try:
            text = (root / name).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        ids.update(next(g for g in m.groups() if g) for m in ID_DEF_RE.finditer(text))
    for folder in ("acceptance/base-run", "evidence"):  # C1.txt, CS1.txt
        if (root / folder).is_dir():
            ids.update(f.stem for f in (root / folder).iterdir()
                       if f.suffix == ".txt" and re.fullmatch(ID_FORM, f.stem))
    return ids


def path_shown(text, path, whole=False):
    """Whether `text` holds `path` as a path prefix: at a boundary and followed
    by `/`, or (`whole`) also ending there, as the worktree's own path can."""
    path = (path or "").rstrip("/")
    if not path:
        return False
    end = r"(?:/|(?![\w.-])|\.(?!\w))" if whole else "/"
    return re.search(rf"(?<![\w.~/-]){re.escape(path)}{end}", text) is not None


def cleanup_worktree(args):
    state = load(args)
    main_checkout, wt = state["repo"]["main_checkout"], state["worktree"]
    code, out, err = git(main_checkout, "worktree", "remove", wt, check=False)
    if code != 0:
        raise Fail(f"git refused to remove {wt}; leave it in place and report what is "
                   f"there:\n{(err or out).strip()}", FAILED, "REFUSED")
    emit(args.json, "REMOVED", wt)
    return 0
