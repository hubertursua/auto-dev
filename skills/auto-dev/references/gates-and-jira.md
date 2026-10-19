# Human gates, Jira transitions, and CI monitoring

How the orchestrator pauses for approval, moves the Jira ticket, and watches CI.

## Contents

- **Human gates** — the four gates and four conditional pauses at a glance.
- **What each option does** — Proceed, `Hold`, and the other labels every gate shares.
- **Gates (in pipeline order)** — summary and options for each:
  - **Post-plan gate — Phase 3 (off by default)**
  - **PR gate — Phase 6a**
  - **Staging gate — Phase 6b (skip entirely if no staging branch)**
  - **Main gate — Phase 6c**
- **Conditional pauses** — situational stops that are not gates:
  - **Profile confirmation — Phase 1 (only when the profile was researched)**
  - **Decomposition approval — Phase 2 (OVERSIZED only)**
  - **Jira In Progress confirmation — Phase 1 (only with a ticket)**
  - **Worktree cleanup offer — Phase 6c (after the main merge)**
- **Jira — status transitions only** — how to move the ticket, never edit it:
  - **MCP tools (deferred — fetch schemas via ToolSearch before calling)**
  - **Procedure (applies to every transition)**
  - **Milestones** — which phase moves the ticket to which state.
- **CI monitoring** — watching checks on the PR and after merges:
  - **Where it runs**
  - **Poll commands (by provider)**
  - **Policy** — timeout, and what to do on green, on red before and after a merge, and on timeout.

## Human gates

Four gates exist. Three of them — PR, staging, main — sit **inside
Phase 6**; the fourth (post-plan) sits at the end of Phase 3 and is off by default.
**Four further pauses are conditional** — they are not gates, and they fire only
when their situation arises: the **profile confirmation** (Phase 1, only when no
saved profile exists and the profile was researched), the **decomposition
approval** (Phase 2, OVERSIZED only), the **Jira In Progress confirmation**
(Phase 1, only with a ticket), and the **worktree cleanup offer** (Phase 6c).
All four are specified below.

Gates use `AskUserQuestion`. Each presents a **concise summary**, enough to decide
without digging (what will happen, what's been verified, any risks), then a
decision. Never proceed past a declined gate.

## What each option does

The labels recur across gates and mean the same thing everywhere. Record the
decision, the option chosen, and its reason in `WORK_LOG.md`.

- **Proceed** (`Approve & build`, `Open PR`, `Merge to staging`, `Merge PR to main`)
  — take the action and continue.
- **`Hold`** — pause without ending the run. Leave the worktree, the branch, and
  every artifact in place; mark the phase `blocked` in the ledger with the reason.
  The run stays **resumable** from `WORK_LOG.md` (`references/artifacts.md`), and
  resuming re-fires this gate, starting with the checks it runs before asking
  (the freshness check among them): the code may have changed during the hold.
- **`Stop`** — end the run. The same state is left on disk, but nothing resumes on
  its own: write the final report, mark the phase `blocked`, and say what remains.
- **`Skip staging`** (6b only) — mark Phase 6b `n/a` in the ledger and continue to
  the main gate. This is not a decline; 6c still fires.
- **`Revise plan (tell me what to change)`** (post-plan gate only) — you edit
  `IMPLEMENTATION.md` yourself from the user's direction, then re-fire this gate on
  the revised plan. User-directed, not a correction: it spends **no** iteration-budget
  round (`references/correction-loop.md`).
- **`Adjust the breakdown`** (decomposition only) — rewrite the sub-task table in
  `WORK_LOG.md` from the user's direction, then re-ask.
- **`Do it as one PR anyway`** (decomposition only) — downgrade the scope call to
  STANDARD, record the downgrade and who asked for it, and **run the Define reviewer
  that OVERSIZED skipped** before Phase 3. Without that, the whole PR gets built from
  a spec nothing ever reviewed.

## Gates (in pipeline order)

### Post-plan gate — Phase 3 (off by default)
Enable for the run when **any** of these holds, and record which one in
`WORK_LOG.md`:
- the user asked to see the plan before building;
- `.auto-dev.yml` sets `gates.post_plan: true` (`references/profiles.md`);
- the task is **high-risk** — `SPEC.md` carries Security/Compliance criteria, or
  the change touches auth, payments, access control, or a data migration.

- **Summary:** task, `SPEC.md` + `IMPLEMENTATION.md` paths, key assumptions, main
  risks, files the plan will touch, and the acceptance coverage from
  `acceptance/MANIFEST.md` (checks per condition; each not-automatable condition
  by name). A revision that changes an entry point the checks call re-runs the
  acceptance tester for those checks before the gate re-fires (nothing is
  installed yet, so with their base run); like the revision, it spends no
  round.
- **Options:** `Approve & build` · `Revise plan (tell me what to change)` · `Stop`.

Once enabled it fires on the TRIVIAL path too, on the short plan the orchestrator
wrote itself.

### PR gate — Phase 6a
- **Summary:** branch + base, files changed (count + notable paths, from
  `git status --porcelain --untracked-files=all --no-renames --ignore-submodules=dirty`,
  so a new directory's files are each listed, a rename is its old and new path,
  and a submodule with only uncommitted content inside it is left out, since
  nothing can stage that; this is the list the commit stages), any submodule the
  check below names as not committed, quality-gate results (each check pass),
  acceptance status from `SPEC_EVAL.md` (**the acceptance block**, below),
  **the two reviews** (below), and any unresolved assumptions. Read
  the quality-gate results from `lint/*.md`: there must be one report per `gate`
  command in `profile.md`, each `pass`. A missing or failing report means Phase 5
  never reached green. Do not ask this gate on it; that is Phase 5's
  stop-and-report.
- **Freshness check (before asking):** every result this summary shows must
  have been produced on the code the commit will carry:
  `python3 <skill-dir>/scripts/check-fresh.py <worktree> <artifact-dir>` exits
  `0` (`references/artifacts.md`, _Stamps: which code each result checked_). On
  `1`, re-run the stale results first (`references/correction-loop.md`, _Stale
  results_); never ask this gate on results for other code.
- **Submodule check (before asking):** run
  `git submodule foreach 'git status --porcelain'`. It visits only checked-out
  submodules (a fresh worktree leaves them uninitialized, and then it prints
  nothing). Each line under an `Entering '<sub>'` header is an uncommitted edit
  inside `<sub>`, with its path relative to `<sub>`, that this PR will not carry,
  whether or not the submodule's commit also moved. Never probe with
  `git -C <sub> status`: in an uninitialized submodule it falls through to the
  parent repo. Everything it shows was made during this run. If a path printed
  under a header, or a coder-reported path under `<sub>/`, is a source file,
  **stop and report** — the pipeline never commits inside a submodule. If it is
  only generated output (from `setup` or a build), name the submodule in the
  summary as not committed.
- **The acceptance block (before asking):** from `SPEC_EVAL.md`. Give the count
  of conditions per verdict and per evidence tier, then name one by one: every
  condition not `met`, every `met` condition resting on Adequate evidence (what
  was run instead of a held-out check), every `manual` condition with exactly
  what the human must check, and every test-integrity finding judged Justified,
  with its reason, so the user can disagree. An Unjustified finding still open
  means Phase 5 did not settle: say so, never present it as a pass.
  Then the mutation line: killed of total, and each surviving mutant judged
  equivalent, with its reason, so the user can disagree. Example in TypeScript:
  ```
  Acceptance — 5 met (4 Strong, 1 Adequate) · 0 partial · 0 unmet · 1 manual
    Mutation: 14 of 15 killed · 1 equivalent (M7: sort of a one-element list)
    C2 Adequate: no held-out check (repaired); verifier observed GET /todos
    C6 manual: open /settings on a phone and check the toggle is visible
    Test changes: 1 justified — todos.test.ts:-42 assertion changed (C3 makes it 404)
  ```
  The IDs (`C2`, `M7`) are for you, since you can open the run's files. The PR
  body says the same things in plain words for reviewers who can't
  (`references/artifacts.md`, _The PR body_).
- **The two reviews (before asking):** from `CODE_REVIEW.md` and
  `SECURITY_REVIEW.md`. For each, give the overall confidence with its reason,
  the must-fix findings fixed, and any still open, named one by one with their
  confidence. Then list the pre-existing security findings for the user, each
  with its confidence and location. Leave advisory findings and noise out; say
  only how many there are and where they are. A **Low** overall confidence is a
  warning, never a clean pass: say what failed. Example in TypeScript:
  ```
  Code review — confidence: High (3/3 reviewers, full diff)
    Must-fix: 0 open · 2 fixed (C1 High, C2 Medium)
    Advisory: 4 (in CODE_REVIEW.md)
  Security review — confidence: High
    Must-fix: 0 open · 1 fixed (S1 High)
    Pre-existing, for you: 1 — S2 (Medium) src/auth.ts:88, session token not rotated on login
  ```
  A must-fix finding is open here only when the iteration budget ran out
  (`references/correction-loop.md`, _On exhaustion_). Say so, and that `Open PR`
  ships it listed in the PR body's `Review` section.
- **Options:** `Open PR` · `Hold (don't push yet)` · `Stop`.
- **Triage, only when there are pre-existing security findings for the user:**
  these are never fixed without asking, whatever their confidence. Fixing one
  widens the PR beyond its task, so whether it belongs in this PR or a separate
  one is the user's call. Add one question per finding to the same `AskUserQuestion` call. The call
  holds at most four questions and the gate's own options take one, so three are
  left: with three findings or fewer, ask about each; with more, ask about the two
  most severe and group the rest into the third question:
  `Separate PR (note it as a follow-up)` · `Fix it in this PR` · `Ignore it`.
  `Fix it in this PR` is a correction (`references/correction-loop.md`, entry
  _Phase 6a — review_): it spends a round, the fix is reviewed like any other
  (`references/review.md`), and the gate fires again on the result. It **wins
  over `Open PR`**: when both are picked, commit nothing, run the correction, and
  ask the gate again. At zero budget, leave `Fix it in this PR` out of the options
  and say why. `Separate PR` adds the finding to the PR body's `Review` section
  and the final report as a follow-up for its own PR; the pipeline does not open
  that PR. `Ignore it` records the
  decision in `WORK_LOG.md` and nothing else. Record every triage decision, and
  its reason, in `WORK_LOG.md`.

### Staging gate — Phase 6b (skip entirely if no staging branch)
- **Summary:** PR link, PR CI status, target `staging` branch, that this is a
  **direct merge** (no PR).
- **Options:** `Merge to staging` · `Skip staging` · `Stop`.

### Main gate — Phase 6c
Collect the human review state before asking (`gh pr view --json
isDraft,reviewDecision,reviews,comments,mergeable,mergeStateStatus`) — this gate is the only
place a teammate's feedback enters the pipeline.
- **Summary:** PR link, CI status (must be green, or `CI: none`), **`reviewDecision` and any
  unresolved review comments**, the open must-fix counts from `CODE_REVIEW.md` and
  `SECURITY_REVIEW.md` (with their overall confidence), `mergeable` /
  `mergeStateStatus`, the PR's head commit and that every result was checked on
  it (`references/phase-6-ship.md`, 6c step 2; name any commits pushed from
  outside the pipeline and what their re-check found), and that the merge is via
  `gh pr merge` respecting branch protection, locked to that commit.
- **Options:** `Merge PR to main` · `Hold` · `Stop`.

Unresolved human blockers go through the correction loop before this gate is worth
asking. If `gh pr merge` then refuses because the PR's head is no longer the
checked commit (`--match-head-commit`), go back to the freshness check and ask
this gate again (`references/phase-6-ship.md`, 6c step 4). Any other refusal
means the PR is **unmergeable**: report the specific requirement blocking it and
stop — never merge locally to get around it.

## Conditional pauses

These are not gates: each fires only when its situation arises, and none of them
signs off on the change itself.

### Profile confirmation — Phase 1 (only when the profile was researched)
Fires on a repo's first run, after the profiler returns
(`references/profiles.md`, _How Phase 1 resolves the profile_). A saved
profile, or a `.auto-dev.yml` that sets both `setup` and `gate`, skips it.
- **Summary:** the draft profile as YAML (also in the save option's preview),
  the profiler's evidence line for each command, everything under its NOT
  INSTALLED and QUESTIONS (questions first: they are what the user is confirming),
  which keys `.auto-dev.yml` will override, the path a save writes to, and the
  permissions guidance (`references/profiles.md`, _Permissions_) filled in with
  this run's directory, skill directory and commands.
- **Options:** `Looks right — save it for this repo` · `Looks right — use it for
  this run only` · `Change something (tell me what)` · `Stop`. Leave the save
  option out when `scripts/profile-path.py` could not name a path (exit `2` or
  `127`). `Change something` means you apply the user's corrections and ask
  again; it spends no iteration-budget round. `Stop` ends the run before any
  worktree exists.
- `WORK_LOG.md` doesn't exist yet: record the decision when Phase 1 step 7
  initializes it, and in `profile.md`'s _Profile_ line.

### Decomposition approval — Phase 2 (OVERSIZED only)
Never start a multi-PR run unapproved.
- **Summary:** why the ticket exceeds one PR, the proposed ordered sub-tasks with
  their dependencies, that each becomes its own branch and PR, and **what it will
  cost**: roughly 11–12 or 14–15 worker spawns per sub-task depending on how each
  is likely to size up (the Phase 6a reviews alone are at least 5: three code
  reviewers, the judge and the security reviewer, plus re-votes, a verification,
  and a re-review after every fix; verification adds at least 3 more: the
  acceptance tester and two verifier passes, plus a re-check after every fix),
  plus the approvals it will ask for — a PR gate and a main gate per sub-task, and
  a staging gate too where the repo has one. Six sub-tasks is on the order of
  eighty to ninety workers and fifteen gates. Say the numbers before asking; they
  are what the decision actually turns on.
- **Options:** `Run them in order` · `Adjust the breakdown` · `Do it as one PR
  anyway` · `Stop`.

### Jira In Progress confirmation — Phase 1 (only with a ticket)
Part of "start work".
- **Summary:** the resolved issue (key, title, current status) and the target
  transition.
- **Options:** `Start work (move to In Progress)` · `Start work, leave Jira alone`
  · `Stop`.

### Worktree cleanup offer — Phase 6c (after the main merge)
The work is already merged; declining costs nothing but disk. On a single-PR run
the worktree is the control worktree and holds the gitignored `.auto-dev/` ledger,
which `git worktree remove` deletes, so make this offer only **after the final
report** is delivered.
- **Summary:** the worktree path and branch, and that the PR is merged and CI green.
- **Options:** `Remove the worktree` · `Leave it in place`.

On `Remove the worktree`, run from the main checkout, not from inside the tree being
removed:

```bash
git worktree remove <worktree-path>     # never --force
```

If git refuses because the tree has modified or untracked files, leave it in place
and report what is there. Those files are not in the merged PR, so deleting them
would lose work.

On a multi-PR run this fires **per sub-task**, and offers that sub-task's build
worktree only. The control worktree holds the ledger and every sub-task's evidence —
leave it until the final report.

## Jira — status transitions only

Never comment or edit fields — **transitions only**. Availability is detected in
Phase 1 (a ticket key/URL was supplied and the Atlassian MCP is reachable). If
either is missing, skip all Jira steps and note it in `WORK_LOG.md`. Milestone →
state mapping comes from `.auto-dev.yml` (`jira.states`) or the defaults
In Progress / In Review / Done.

### MCP tools (deferred — fetch schemas via ToolSearch before calling)

Four tools from the Atlassian MCP server, by base name:
`getAccessibleAtlassianResources`, `getJiraIssue`, `getTransitionsForJiraIssue`,
`transitionJiraIssue`.

Claude Code exposes MCP tools as `mcp__<server>__<tool>`, and `<server>` is
whatever the user named the Atlassian server, so it differs between setups (for
example `mcp__atlassian__getJiraIssue`, `mcp__atlassian-gateway__getJiraIssue`, or
`mcp__claude_ai_Atlassian__getJiraIssue`). Don't assume a prefix. Find the real
names once in Phase 1: search the deferred tools with ToolSearch for
`getJiraIssue`, take the server segment from the match, and call all four by that
fully qualified name (loading their schemas first). The bare names below are
shorthand for those full names. If no match turns up, the Atlassian MCP is
unreachable: Jira is unavailable for the run.

### Procedure (applies to every transition)

1. **Resolve `cloudId` once** (Phase 1): call `getAccessibleAtlassianResources`
   and cache the site's cloud id. Every Jira call needs it.
2. **Read the issue** (Phase 1): `getJiraIssue { cloudId, issueIdOrKey,
   responseContentFormat: "markdown" }` — feeds the `WORK_LOG.md` header and
   `SPEC.md`'s Context section, and confirms the current status.
3. **Transition is by id, resolved from the name.** State names vary per board, so
   never hardcode an id:
   - `getTransitionsForJiraIssue { cloudId, issueIdOrKey }` → the list of
     currently-available transitions, each with an `id` and a target status
     `name`.
   - Match the target state name (from `jira.states`, case-insensitive) to a
     transition; take its `id`.
   - `transitionJiraIssue { cloudId, issueIdOrKey, transition: { id } }`.
   - If no available transition matches (e.g. the board has no direct path from
     the current status), **do not force it** — report the mismatch and continue;
     the transition is best-effort, not a blocker.

### Milestones

- **In Progress — Phase 1.** After the worktree is created and the issue read,
  confirm with the user (part of "start work") and transition to the
  `in_progress` state. Skip the transition if the issue already sits at or past
  `in_progress` in the `jira.states` map (In Progress, In Review, or Done).
- **In Review — Phase 6a.** Rides along with the PR gate, after the PR opens.
- **Done — Phase 6c.** Rides along with the main gate, after `gh pr merge` and only
  once `gh pr view <pr> --json state` shows `MERGED` (a queued or auto-merge PR
  is not merged yet).

## CI monitoring

Detect the provider in Phase 1 (recorded in `profile.md`): GitHub Actions,
CircleCI, GitLab, or none. When checks are integrated as GitHub commit statuses
(CircleCI usually is), `gh pr checks` aggregates them, so it is the default watcher
regardless of provider on a GitHub repo.

### Where it runs
- **Phase 6a — on the PR, pre-merge** (the important one): the change must be green
  before it can be promoted.
- **Phases 6b–6c — after the staging/main merges:** confirm the merge did not break
  the branch; report, don't gate (the merge already happened).

### Poll commands (by provider)
- **GitHub Actions / GitHub-integrated checks (incl. CircleCI):**
  poll `gh pr checks <pr>` every ~30s in a loop bounded by the timeout below, and
  read its exit code:
  - `0` — all passed; `8` — still pending.
  - `1` with `no checks reported` in the output — nothing has registered yet
    (right after a push, on a draft PR with CI held back, or a repo with no CI).
    Treat it as pending for a short grace period, roughly the first ~5 minutes
    after the push (a rough guide). After that, treat it as **watcher
    unavailable** (below): not red, and no budget spent.
  - any other non-zero — a failure (or an error to report).

  Don't use `--watch`: it blocks with no timeout of its own.
- **CircleCI (not surfaced to GitHub):** the CircleCI API, for the pipeline tied to
  the branch SHA; fall back to `gh pr checks` if it appears as a status.
- **GitLab:** `glab ci status` for the branch's pipeline (not `glab ci view`,
  which is interactive).
- **`none`** (the resolved CI provider) — skip the watch entirely and record
  `CI: none` in the gate summary.
- **Watcher unavailable** — `glab` not installed or not authenticated, or no
  CircleCI API access (no token), and the checks don't show in `gh pr checks`
  either; or `gh pr checks` still says `no checks reported` after the grace
  period: CI can't be watched. Treat it like timeout/pending below — log
  `CI not monitored: <missing tool, or no checks reported>` in `WORK_LOG.md`, say so at the gate, and
  hold rather than assume success. Don't install or authenticate the CLI yourself.

### Policy
- Wrap watching in a **bounded timeout** — default **30 min**, overridable with
  `ci_timeout_minutes:` in `.auto-dev.yml` and recorded in `profile.md`. Poll every
  ~30s; never block indefinitely.
- **On green:** continue to the step after the watch — Phase 6a step 7 (Jira →
  In Review) pre-merge, or the next step of 6b/6c post-merge.
- **On red, pre-merge (Phase 6a):** surface the failing checks (name + link),
  then enter the correction loop — the steps, the reports to refresh, the review
  of the fix, and the commit-and-re-push are specified once in
  `references/correction-loop.md`.
  Two things stop the loop before the budget does: a failure the coder cannot fix
  (infrastructure, a flaky external service, a missing secret), and a budget that
  has run out. In both cases **hold at the gate** and say which it was. Never
  retry blindly; never auto-merge over a failure.
- **On red, post-merge (Phases 6b–6c):** there is no gate left to hold and
  re-pushing the branch cannot fix already-merged code, so the pre-merge loop does
  **not** apply. Report the failure to the user immediately with the failing
  checks and the merge commit, state plainly that the merge is already in, and
  stop. Recovery (revert, forward-fix, or a new run) is the user's call — never
  start it unasked.
- **On timeout/pending:** report what's still running and hold at the gate rather
  than assuming success.
- Never rely on post-merge monitoring to catch what pre-merge CI should have.
