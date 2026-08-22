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
to happen and the state so far, then a proceed / hold decision. Always give the
user enough to decide without digging: what will happen, what's been verified, and
any risks. A `Stop` / `Hold` choice ends the run gracefully (work left in place,
reported) — never proceed past a declined gate.

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
- **Summary:** PR link, CI status (must be green), review/approval state,
  `PR_REVIEW.md` blocker count, that the merge is via `gh pr merge` respecting
  branch protection.
- **Options:** `Merge PR to main` · `Hold` · `Stop`.

## Conditional pauses

These are not gates: each fires only when its situation arises, and none of them
is a checkpoint on the change itself.

### Decomposition approval — Phase 2 (OVERSIZED only)
Not optional when it applies: never start a multi-PR run unapproved.
- **Summary:** why the ticket exceeds one PR, the proposed ordered sub-tasks with
  their dependencies, and that each becomes its own branch and PR.
- **Options:** `Run them in order` · `Adjust the breakdown` · `Do it as one PR
  anyway` · `Stop`.

### Jira In Progress confirmation — Phase 1 (only with a ticket)
Part of "start work".
- **Summary:** the resolved issue (key, title, current status) and the target
  transition.
- **Options:** `Start work (move to In Progress)` · `Start work, leave Jira alone`
  · `Stop`.

### Worktree cleanup offer — Phase 6c (after the main merge)
The run is already complete; declining costs nothing but disk.
- **Summary:** the worktree path and branch, and that the PR is merged and CI green.
- **Options:** `Remove the worktree` · `Leave it in place`.

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
  `in_progress` state. Skip if already in a started state.
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
- Wrap watching in a **bounded timeout** (default **30 min**; poll every ~30s);
  never block indefinitely.
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
