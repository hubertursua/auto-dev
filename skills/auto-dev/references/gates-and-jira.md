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

Never comment or edit fields — transitions only. Availability is detected in
Phase 1. Milestone → state mapping comes from `.auto-dev.yml`
(`jira.states`) or defaults (In Progress / In Review / Done).

- Read the issue: Atlassian MCP `getJiraIssue`.
- List valid transitions: `getTransitionsForJiraIssue` (state names vary per
  board — resolve the target name to its transition id).
- Apply: `transitionJiraIssue`.
- Milestones: **In Progress** at start (Phase 1, confirmed), **In Review** when
  the PR opens (Phase 8), **Done** when the PR merges to main (Phase 10). Writes
  ride along with the corresponding gate.

_(MCP tools are deferred; fetch schemas via ToolSearch when implementing: M1/M3.)_

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
