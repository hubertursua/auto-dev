# Jira

auto-dev only moves a ticket between states. It never comments on a ticket or
edits its fields. `next` decides when (after the size check, after the PR opens,
after the merge) and asks the user first; this file says how. What each gate
option does is in `references/tables.md`.

## MCP tools

Jira goes through the Atlassian MCP server's tools, which are deferred: load
each schema with ToolSearch before calling it. Four tools, by base name:
`getAccessibleAtlassianResources`, `getJiraIssue`, `getTransitionsForJiraIssue`,
`transitionJiraIssue`.

Their full names are `mcp__<server>__<tool>`, and `<server>` is whatever the
user named the server (`mcp__atlassian__getJiraIssue`,
`mcp__claude_ai_Atlassian__getJiraIssue`, …). Don't guess it: ToolSearch for
`getJiraIssue`, take the server part of the match, and call all four with it.
No match means Jira is unavailable: tell the user, and run the step's `AFTER`
line with `--value skipped`.

## Moving a ticket

`next` names the ticket and the target state (from `jira.states` in
`.auto-dev.yml`, else `In Progress`, `In Review`, `Done`).

1. `getAccessibleAtlassianResources` → the site's `cloudId` (once per session).
2. `getJiraIssue { cloudId, issueIdOrKey }` → its current status. IF it is
   already at the target state or past it (In Review or Done for In Progress;
   Done for In Review), don't move it: run the `AFTER` line with `--value
   already`.
3. `getTransitionsForJiraIssue { cloudId, issueIdOrKey }` → the transitions
   open now, each with an `id` and a target status `name`.
4. Pick the one whose `name` matches the target state, ignoring case. IF none
   matches, don't force it: tell the user the board has no direct move to that
   state, and run the `AFTER` line with `--value skipped`.
5. `transitionJiraIssue { cloudId, issueIdOrKey, transition: { id } }`, then
   run the `AFTER` line.

A Jira move is best effort: a ticket that can't be moved never stops the run.
