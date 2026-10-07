# Human gates, Jira transitions, and CI monitoring

How the orchestrator pauses for approval, moves the Jira ticket, and watches CI.

## Contents

- **Human gates** — the four gates and three conditional pauses at a glance.
- **What each option does** — Proceed, `Hold`, and the other labels every gate shares.
- **Gates (in pipeline order)** — summary and options for each:
  - **Post-plan gate — Phase 3 (off by default)**
  - **PR gate — Phase 6a**
  - **Staging gate — Phase 6b (skip entirely if no staging branch)**
  - **Main gate — Phase 6c**
- **Conditional pauses** — situational stops that are not gates:
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
**Three further pauses are conditional** — they are not gates, and they fire only
when their situation arises: the **decomposition approval** (Phase 2, OVERSIZED
only), the **Jira In Progress confirmation** (Phase 1, only with a ticket), and
the **worktree cleanup offer** (Phase 6c). All three are specified below.

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
  resuming re-fires this gate.
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
  risks, files the plan will touch.
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
  acceptance status from `SPEC_EVAL.md`, and any unresolved assumptions. Read
  the quality-gate results from `lint/*.md`: there must be one report per `gate`
  command in `profile.md`, each `pass`. A missing or failing report means Phase 5
  never reached green. Do not ask this gate on it; that is Phase 5's
  stop-and-report.
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
- **Options:** `Open PR` · `Hold (don't push yet)` · `Stop`.

### Staging gate — Phase 6b (skip entirely if no staging branch)
- **Summary:** PR link, PR CI status, target `staging` branch, that this is a
  **direct merge** (no PR).
- **Options:** `Merge to staging` · `Skip staging` · `Stop`.

### Main gate — Phase 6c
Collect the human review state before asking (`gh pr view --json
isDraft,reviewDecision,reviews,comments,mergeable,mergeStateStatus`) — this gate is the only
place a teammate's feedback enters the pipeline.
- **Summary:** PR link, CI status (must be green, or `CI: none`), **`reviewDecision` and any
  unresolved review comments**, `PR_REVIEW.md` blocker count, `mergeable` /
  `mergeStateStatus`, and that the merge is via `gh pr merge` respecting branch
  protection.
- **Options:** `Merge PR to main` · `Hold` · `Stop`.

Unresolved human blockers go through the correction loop before this gate is worth
asking. If `gh pr merge` then refuses, the PR is **unmergeable**: report the specific
requirement blocking it and stop — never merge locally to get around it.

## Conditional pauses

These are not gates: each fires only when its situation arises, and none of them
signs off on the change itself.

### Decomposition approval — Phase 2 (OVERSIZED only)
Never start a multi-PR run unapproved.
- **Summary:** why the ticket exceeds one PR, the proposed ordered sub-tasks with
  their dependencies, that each becomes its own branch and PR, and **what it will
  cost**: roughly 4 or 7 workers per sub-task depending on how each is likely to
  size up, plus the approvals it will ask for — a PR gate and a main gate per
  sub-task, and a staging gate too where the repo has one. Six sub-tasks is on the
  order of forty workers and fifteen gates. Say the numbers before asking; they
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
- **On green:** continue to the step after the watch — Phase 6a step 6 (Jira →
  In Review) pre-merge, or the next step of 6b/6c post-merge.
- **On red, pre-merge (Phase 6a):** surface the failing checks (name + link),
  then enter the correction loop — the steps, the reports to refresh, and the
  commit-and-re-push are specified once in `references/correction-loop.md`.
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
