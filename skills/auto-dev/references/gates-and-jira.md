# Human gates, Jira transitions, and CI monitoring

How the orchestrator pauses for approval, moves the Jira ticket, and watches CI.

## Human gates

Four gates exist. Three of them — PR, staging, main — are the checkpoints **inside
Phase 6**; the fourth (post-plan) sits at the end of Phase 3 and is off by default.
**Three further pauses are conditional** — they are not gates, and they fire only
when their situation arises: the **decomposition approval** (Phase 2, OVERSIZED
only), the **Jira In Progress confirmation** (Phase 1, only with a ticket), and
the **worktree cleanup offer** (Phase 6c). All three are specified below.

Gates use `AskUserQuestion`. Each presents a **concise summary** of what is about
to happen and the state so far, then a decision. Always give the user enough to
decide without digging: what will happen, what's been verified, and any risks.
Never proceed past a declined gate.

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
- **Summary:** branch + base, files changed (count + notable paths), quality-gate
  results (each check pass), acceptance status from `SPEC_EVAL.md`, and any
  unresolved assumptions.
- **Options:** `Open PR` · `Hold (don't push yet)` · `Stop`.

### Staging gate — Phase 6b (skip entirely if no staging branch)
- **Summary:** PR link, PR CI status, target `staging` branch, that this is a
  **direct merge** (no PR).
- **Options:** `Merge to staging` · `Skip staging` · `Stop`.

### Main gate — Phase 6c
Collect the human review state before asking (`gh pr view --json
reviewDecision,reviews,comments,mergeable,mergeStateStatus`) — this gate is the only
place a teammate's feedback enters the pipeline.
- **Summary:** PR link, CI status (must be green), **`reviewDecision` and any
  unresolved review comments**, `PR_REVIEW.md` blocker count, `mergeable` /
  `mergeStateStatus`, and that the merge is via `gh pr merge` respecting branch
  protection.
- **Options:** `Merge PR to main` · `Hold` · `Stop`.

Unresolved human blockers go through the correction loop before this gate is worth
asking. If `gh pr merge` then refuses, the PR is **unmergeable**: report the specific
requirement blocking it and stop — never merge locally to get around it.

## Conditional pauses

These are not gates: each fires only when its situation arises, and none of them
is a checkpoint on the change itself.

### Decomposition approval — Phase 2 (OVERSIZED only)
Never start a multi-PR run unapproved.
- **Summary:** why the ticket exceeds one PR, the proposed ordered sub-tasks with
  their dependencies, that each becomes its own branch and PR, and **what it will
  cost**: roughly 4 or 7 subagents per sub-task depending on how each is likely to
  size up, plus the approvals it will ask for — a PR gate and a main gate per
  sub-task, and a staging gate too where the repo has one. Six sub-tasks is on the
  order of forty subagents and fifteen gates. Say the numbers before asking; they
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
The work is already merged; declining costs nothing but disk.
- **Summary:** the worktree path and branch, and that the PR is merged and CI green.
- **Options:** `Remove the worktree` · `Leave it in place`.

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

Full names: `mcp__atlassian-gateway__getAccessibleAtlassianResources`,
`mcp__atlassian-gateway__getJiraIssue`,
`mcp__atlassian-gateway__getTransitionsForJiraIssue`,
`mcp__atlassian-gateway__transitionJiraIssue`.

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
- **Done — Phase 6c.** Rides along with the main gate, after `gh pr merge`.

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
  `gh pr checks <pr> --watch --interval 30` (blocks until all checks settle), or
  poll `gh pr checks <pr>` in a bounded loop and parse pass/fail/pending.
- **CircleCI (not surfaced to GitHub):** CircleCI API/CLI for the pipeline tied to
  the branch SHA; fall back to `gh pr checks` if it appears as a status.
- **GitLab:** `glab ci status` / `glab ci view` for the branch's pipeline.

### Policy
- Wrap watching in a **bounded timeout** — default **30 min**, overridable with
  `ci_timeout_minutes:` in `.auto-dev.yml` and recorded in `profile.md`. Poll every
  ~30s; never block indefinitely.
- **On red, pre-merge (Phase 6a):** surface the failing checks (name + link),
  then enter the corrective loop — the steps, the reports to refresh, and the
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
