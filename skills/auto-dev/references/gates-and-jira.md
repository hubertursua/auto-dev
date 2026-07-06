# Human gates, Jira transitions, and CI monitoring

How the orchestrator pauses for approval, moves the Jira ticket, and watches CI.

> **Status:** scaffold. Fully authored in **M3** (with the Jira-at-start
> transition wired in **M1**). Section headers below are the contract.

## Human gates

Gates use `AskUserQuestion`. Each gate presents a concise summary of what is about
to happen and the state so far, then a proceed / hold decision. Gate points:

- **Post-plan (Phase 4)** — off by default; enabled per run. Approve SPEC + plan
  before building.
- **PR (Phase 8)** — approve opening the PR.
- **Staging (Phase 9)** — approve the direct merge to staging.
- **Main (Phase 10)** — approve merging the PR to main.

_(Exact prompts and summaries: M3.)_

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
   responseContentFormat: "markdown" }` — feeds `TICKET.md` and confirms the
   current status.
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

- **In Progress — Phase 1 (wired in M1).** After the worktree is created and the
  issue read, confirm with the user (part of "start work") and transition to the
  `in_progress` state. Skip if already in a started state.
- **In Review — Phase 8 (M3).** Rides along with the PR gate, after the PR opens.
- **Done — Phase 10 (M3).** Rides along with the main gate, after `gh pr merge`.

## CI monitoring

Detect the provider in Phase 1: GitHub Actions (via `gh`), CircleCI, GitLab, or
none. Monitor **on the PR pre-merge** (Phase 8) and after the staging/main merges.

Policy:

- Poll with a bounded **timeout**; do not block indefinitely.
- **On red:** surface the failing checks and **stop** at that gate — do not
  silently loop or auto-merge over a failure.
- Never rely on post-merge monitoring to catch problems that pre-merge CI should
  have caught.

_(Provider-specific poll commands and timeout defaults: M3.)_
