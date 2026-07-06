# Human gates, Jira transitions, and CI monitoring

How the orchestrator pauses for approval, moves the Jira ticket, and watches CI.

## Human gates

Gates use `AskUserQuestion`. Each presents a **concise summary** of what is about
to happen and the state so far, then a proceed / hold decision. Always give the
user enough to decide without digging: what will happen, what's been verified, and
any risks. A `Stop` / `Hold` choice ends the run gracefully (work left in place,
reported) — never proceed past a declined gate.

### Post-plan gate — Phase 4 (off by default; enable per run)
Enable when the user asks to review before building, or for high-risk tasks.
- **Summary:** task, `SPEC.md` + `IMPLEMENTATION.md` paths, key assumptions, main
  risks, files the plan will touch.
- **Options:** `Approve & build` · `Revise plan (tell me what to change)` · `Stop`.

### PR gate — Phase 8
- **Summary:** branch + base, files changed (count + notable paths), quality-gate
  results (each check pass), acceptance status from `SPEC_EVAL.md`, and any
  unresolved assumptions.
- **Options:** `Open PR` · `Hold (don't push yet)` · `Stop`.

### Staging gate — Phase 9 (skip entirely if no staging branch)
- **Summary:** PR link, PR CI status, target `staging` branch, that this is a
  **direct merge** (no PR).
- **Options:** `Merge to staging` · `Skip staging` · `Stop`.

### Main gate — Phase 10
- **Summary:** PR link, CI status (must be green), review/approval state,
  `PR_REVIEW.md` blocker count, that the merge is via `gh pr merge` respecting
  branch protection.
- **Options:** `Merge PR to main` · `Hold` · `Stop`.

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

Detect the provider in Phase 1 (recorded in `profile.md`): GitHub Actions,
CircleCI, GitLab, or none. When checks are integrated as GitHub commit statuses
(CircleCI usually is), `gh pr checks` aggregates them, so it is the default watcher
regardless of provider on a GitHub repo.

### Where it runs
- **Phase 8 — on the PR, pre-merge** (the important one): the change must be green
  before it can be promoted.
- **Phases 9–10 — after the staging/main merges:** confirm the merge didn't break
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
- **On red:** surface the failing checks (name + link) and **stop at the gate** —
  do not silently loop, retry, or auto-merge over a failure. A pre-merge CI
  failure feeds back to the coder (Phase 5 correction brief) under the shared
  budget, then re-push; if the budget is exhausted, report and hold.
- **On timeout/pending:** report what's still running and hold at the gate rather
  than assuming success.
- Never rely on post-merge monitoring to catch what pre-merge CI should have.
