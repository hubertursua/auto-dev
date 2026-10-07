# Phase 6 — Ship procedure

The orchestrator's git/gh work in S3, step by step, with the exact command
sequences. `SKILL.md` keeps the step list and the safety rules; this file holds
each step's full procedure. The gate scripts (summary, options, what each option
does), the Jira transitions and the CI polling policy are in
`references/gates-and-jira.md`; the PR body's shape is in `references/artifacts.md`,
_The PR body_.

## Contents

- 6a — PR **[gate]** — the commit sequence and its staged check
  (`scripts/check-staged.py`), push, PR requirements, adversarial review, CI and
  Jira.
- 6b — Staging **[gate]** (skip if no staging branch) — the direct-merge sequence
  and its failure handling.
- 6c — Main **[gate]** — reading human reviews, the draft flag, `gh pr merge`,
  confirming it merged, and a refused merge.

## 6a — PR **[gate]**

1. **Gate:** pause for approval to open the PR (`references/gates-and-jira.md`).
2. **Commit** — stage source paths **explicitly**, confirm nothing under
   `.auto-dev/` is staged, then commit with a conventional message. Run exactly
   this sequence; only the paths and the message vary:
   ```bash
   git add -- <path> …                             # named paths that exist on disk — never -A or .
   git rm -q --cached --ignore-unmatch -- <deleted-path> …   # named deleted paths; skip if none
   python3 <skill-dir>/scripts/check-staged.py <worktree> --expect <path> …   # every path, both kinds
   git commit -m "<type>(<scope>): <summary>" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
   ```
   The paths to stage, and to pass to `--expect`, are the changed files the PR gate
   summary listed, which is the working tree Phase 5 verified. That list comes from
   `git status --porcelain --untracked-files=all --no-renames --ignore-submodules=dirty`,
   which names each new file instead of collapsing a new directory to `dir/`,
   lists a rename as its old path (deleted) and its new path rather than
   `old -> new`, and leaves out a submodule whose only change is uncommitted
   content inside it (nothing can stage that). The PR gate summary has already
   checked the submodules with `git submodule foreach 'git status --porcelain'`
   and stopped the run if the build edited source inside one
   (`references/gates-and-jira.md`). Git
   quotes a name with spaces or unusual characters (`"a b.txt"`); pass it
   unquoted, as the bare path. A file
   the gate never showed should not ride into the commit. A **deleted** path,
   including a rename's old path, goes to the `git rm --cached` line, never to
   `git add`: if the deletion is already staged (a worker used `git mv` or
   `git rm`, or this sequence is re-run on resume), `git add -- <path>` fails with
   "pathspec did not match", while `git rm --cached --ignore-unmatch` stages the
   deletion whether or not it was staged already, and exits `0`. One deleted path
   has nothing to stage: a file Phase 5 marked intent-to-add that a later step
   removed was never committed, so `git rm --cached` only clears its marker and
   the script reports it as `IGNORED`, not `MISSING`. That is safe because the
   script also fails on any change outside `.auto-dev/` still left unstaged, so a
   mistyped path cannot pass while the real one sits unstaged. The script is
   read-only (it reads `git diff --cached --name-only --no-renames`, so a staged
   rename shows both paths, as the summary does) and its exit code decides the
   next move:
   - `0` — nothing under `.auto-dev/` is staged, the staged set is exactly the
     summary's paths, and nothing else is left unstaged: commit.
   - `1` — it prints what is wrong. Staged `.auto-dev/` paths: unstage them with
     the `git restore --staged` command it prints. `MISSING`: stage those paths.
     `EXTRA`: unstage them. `UNSTAGED`: the `--expect` list was wrong (a typo, or
     a quoted name); stage the real paths and correct the list. If an UNSTAGED
     path should never be committed (a secret, a local config file, anything the
     PR gate summary didn't show), don't stage it: stop and report it. Then
     re-run it; commit only on `0`.
   - `2` — it couldn't run (git missing, `<worktree>` not a git work tree, an
     `--expect` path outside it). Not a pass: fix the cause it names and re-run it.
   - `127` — `python3` isn't installed. Check by hand instead:
     `git diff --cached --name-only -- .auto-dev/` must print nothing (if it
     prints a path, `git restore --staged <path>` and re-check), and
     `git diff --cached --name-only --no-renames` must match the summary's file
     count and paths, leaving out any path that is neither on disk nor in HEAD
     (`git cat-file -e HEAD:<path>` fails), and
     `git status --porcelain --untracked-files=all --no-renames --ignore-submodules=dirty`
     must show no line with a second-column change or `??` outside `.auto-dev/`. Commit only
     once all three hold.
3. **Push** the branch (`git push -u origin HEAD` — never `--force`), then
   **open exactly one PR** for it. These are the pipeline's requirements, whatever
   route opens it:
   - **Body** to the PR-body contract (`references/artifacts.md`, _The PR body_):
     summary, unresolved assumptions, and — as required content — the **acceptance
     checklist** (the spec's conditions, ticked from `SPEC_EVAL.md`, unticked ones
     left unticked) and the **quality-gate results**. Brevity rules may trim the
     _prose_; they never drop those two sections.
   - **Repo PR template:** detect it (`.github/pull_request_template.md`,
     `.github/PULL_REQUEST_TEMPLATE/`, `docs/` or the repo root) and fill it,
     carrying the contract's sections inside it. No template → the contract's shape.
   - **Jira link** to the ticket, when the run has one.
   - **Base:** target `<base>`, the resolved `branches.base` from `profile.md` —
     it may be `develop`, not the default branch.
   - **Draft flag:** open the PR as a **draft** (`--draft`) unless the
     user asked for it ready for review; 6c marks it ready before the main gate.
   - **Attribution line** last: `Generated with [Claude Code](https://claude.com/claude-code)`.

   Pick the route yourself. If a skill in your available-skills list clearly fits
   PR creation and can meet every requirement above, you may invoke it through the
   Skill tool and pass these requirements as its input — it must still target
   `<base>`, so say so in that input. Otherwise do it directly:
   ```bash
   gh pr create --base <base> --title "<title>" --body-file <artifact-dir>/PR_BODY.md --draft
   ```
   Drop `--draft` only if the user asked for the PR ready for review. `--title` is
   required: `gh` cannot prompt here. Write the body file in `<artifact-dir>`
   (self-excluded from git) or `$TMPDIR`, never anywhere `git status` would list
   it for staging. Either way, first check
   `gh pr list --head <branch>` — if a PR already exists, update it
   (`gh pr edit <pr> --base <base> --title "<title>" --body-file <file>`) and never
   open a second — and afterwards read the result back
   (`gh pr view <pr> --json url,isDraft,baseRefName,title,body`) and fix any
   requirement it misses, including a `baseRefName` that isn't `<base>`.
4. **PR reviewer** (adversarial) → `.auto-dev/PR_REVIEW.md` — briefed to _find_
   problems (correctness, security, scope), not rubber-stamp. This is the only
   check briefed to find what no checklist names. Findings stay on disk: post them
   as inline PR comments **only** if the user asks during the run, or
   `.auto-dev.yml` sets `pr_review.inline_comments: true`.
5. **CI monitoring** — poll the PR's checks (detected provider) with a bounded
   timeout (`references/gates-and-jira.md`). On red pre-merge the response is a
   correction loop, not an immediate halt: `references/correction-loop.md`.
   "No checks reported" is not red, and a CI provider of `none` skips the watch
   (`references/gates-and-jira.md`, _Poll commands_).
6. **Jira → In Review.**

## 6b — Staging **[gate]** (skip if no staging branch)

Pause for approval, then **directly merge** the branch into `staging` (no PR — per
project convention) and monitor CI on staging. Skip entirely if the repo has no
staging branch. Run the merge from the worktree with exactly this sequence
(`<branch>` is the PR's branch):

```bash
git fetch origin <staging>
git switch --detach origin/<staging>
git merge --no-edit <branch>
git push origin HEAD:<staging>     # never --force
git switch <branch>
```

If the merge conflicts (`git merge --abort`) or the push is rejected, switch back
to `<branch>` and report to the user. Never resolve conflicts on staging or force
the push unasked.

## 6c — Main **[gate]**

1. **Read what humans said,** and check whether the PR is still a draft. A
   teammate may have reviewed since the PR gate, and nothing else in this pipeline
   reads their words:
   ```bash
   gh pr view <pr> --json isDraft,reviewDecision,reviews,comments,mergeable,mergeStateStatus
   ```
   **`isDraft: true` blocks the merge, and on some setups suppressed CI too** —
   6a opens the PR as a draft by default, so this is the expected state, not an error.
   Mark it ready (`gh pr ready <pr>`) _before_ the gate, then confirm the checks
   Phase 6a polled actually ran; if they only started once the draft flag came off,
   monitor them now rather than merging on a stale green.
   Put unresolved review comments and any `CHANGES_REQUESTED` in the gate summary. A
   human blocker is handled exactly like a `PR_REVIEW.md` blocker — through the
   correction loop (`references/correction-loop.md`), never merged over.
2. **Gate:** pause for approval.
3. **Merge to main** via `gh pr merge` (respects branch protection and required
   reviews — never a local push to main):
   ```bash
   gh pr merge <pr> --squash
   ```
   Pass the method explicitly — `gh` cannot prompt here. Use `--squash`; if the
   repo disallows squash merges (`gh repo view --json squashMergeAllowed,mergeCommitAllowed,rebaseMergeAllowed`),
   use `--merge`, and `--rebase` only when it is the one method allowed.
   **Never add `--admin`**: it bypasses branch protection. If the merge is
   **refused** — missing approvals, a failing required check, an out-of-date
   branch, an unresolved conversation — do not work around it. **Report that the PR is unmergeable**, name
   the specific requirement blocking it, and stop with the PR left open. Merging
   locally to get past branch protection is never the answer.

   Then confirm it actually merged, before Jira or anything else:
   ```bash
   gh pr view <pr> --json state       # must be MERGED
   ```
   On a repo with auto-merge or a merge queue, `gh pr merge` can exit `0` having
   only enabled auto-merge or queued the PR. If `state` is not `MERGED`, report
   that (queued, or auto-merge pending) and stop: don't poll for it, and don't
   move Jira.
4. Monitor CI on main, transition **Jira → Done**, and offer to remove the worktree
   (confirmed, not automatic). On a single-PR run the worktree is the control
   worktree, so make the offer only **after the final report** is delivered:
   removing it deletes the gitignored `.auto-dev/` ledger. On a multi-PR run this runs **per sub-task**, and the offer covers
   that sub-task's build worktree only — the control worktree holds the ledger and
   stays until the final report.
