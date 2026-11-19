# Plan stage (Phases 1–3)

Phase 1 is the ticket (step 1) and a loop on `next --repo` (step 2), which
finds or researches the repo's profile, creates the run and sets it up. From
step 3 on, `next --dir` drives in the run's worktree. `autodev.py` means `python3
<skill-dir>/scripts/autodev.py`; `<repo>` is the absolute path of the checkout
you started in: the main checkout, or a worktree the user made for this task.

On a run resumed in the Plan stage (`resume` printed `RESUME <tree>`), `cd
<tree>` and skip to step 3. IF `resume` also printed an `action:` line (setup
is not done), the first `next` waits for setup, or runs it again now that the
user fixed the cause.

## Phase 1 — Setup

### 1. The ticket

- IF the user gave a Jira key or URL:
  1. Find the Atlassian tools: ToolSearch for `getJiraIssue`. Take the server
     part of the match (`mcp__<server>__getJiraIssue`) and use it for every
     Jira tool (`references/gates-and-jira.md`, _MCP tools_). No match → Jira is
     unavailable: note it and treat the key as the task text.
  2. `getAccessibleAtlassianResources` → keep the `cloudId`.
  3. `getJiraIssue { cloudId, issueIdOrKey, responseContentFormat: "markdown" }`
     → keep the key, title, link and current status.
  4. Write the issue's summary and description, exactly as `getJiraIssue`
     returned them, to a new file under `$TMPDIR` (`<ticket-text>`): the
     summary on the first line, a blank line, then the description. Don't
     shorten, reword or translate them. The planner and the plan critic have
     no Jira access; the run stores this file's text and gives it to them
     verbatim as the task.
- ELSE the task is the user's words.

Write a one- or two-sentence restatement of the ask in the user's words
(`--ask` below).

### 2. Set the run up with `next --repo`

Run, from `<repo>`:

```
autodev.py next --repo <repo> --task "<the ticket key, or the task in one line>" \
  --ask "<restated ask>" \
  [--ticket <KEY> --ticket-url <link> --ticket-text-file <ticket-text>] \
  --jira "<available, cloudId <id> | unavailable: <why> | no ticket>"
```

The ticket flags, `--ask` and `--jira` are needed on the first call only.
Pass `--ticket-text-file` whenever step 1 wrote one: without it, the planner
and the plan critic work from your restated ask. The run keeps the ask, so a
later `resume` or `next --repo` given the user's own wording finds the run by
it. Then follow **The loop** in `SKILL.md` with this same command (the `next
--repo` line its `AFTER` lines name) in place of `next --dir`, until it says to
move into the worktree. The steps that are yours:

- **A question before the run exists (exit 5)**, about a saved profile's gate
  checks or a profile the `profiler` drafted: show the `SUMMARY`, ask the
  `QUESTION` and run the `AFTER` line for the answer. For the profiler's
  draft, also show the permissions guidance from `references/profiles.md`,
  _Permissions_, with the `SUMMARY`'s paths and the draft's commands filled in.
  `autodev.py` makes the run's profile from the answer and never changes a
  saved file: never edit a profile yourself.
- **The run is created:** tell the user its `SUMMARY` lines, then `cd
  <worktree>` (the path it names; the one you are in when the run uses yours).
  Every later step runs there, with the `next --dir` command its `AFTER` names.

Exit 4 is a stop (`references/tables.md`, stop conditions 1–3): tell the user
the `REPORT`; it says how to go on. A setup command that failed keeps the run:
once the user fixed the file the `REPORT` names, they say `auto-dev continue`,
and `next` runs setup again.

Setup adopts a worktree you made (and stops if it has uncommitted changes) and
finds the security directives by itself: do neither by hand.

## Phases 2–3 — Plan and Tests, the loop

### 3. Run the loop

Follow **The loop** in `SKILL.md` until `next` exits 3, 4 or 6. `next` names
each worker to spawn and each question to ask. The steps that are yours:

- **With a ticket, the Jira question (exit 5).** Read the ticket's status
  first (`references/gates-and-jira.md`, _Asking first_): if it is in progress
  already, don't ask, and run the `Already …` line. On `Move it`, a later exit 0
  says to move the ticket: do it as `references/gates-and-jira.md`, _Moving a
  ticket_ says, then run its `AFTER` line.
- **Into the Build stage.** Once the acceptance checks are committed, `next`
  says the run goes on to the Build stage in this session: read
  `references/build.md`, as its `ACTION` says, then run `next`. Don't stop or
  hand off.

### Stops in the Plan stage

Every stop is exit 4 with its reason in `REPORT`, and most ask how to go on
(`SKILL.md`, _A stop_). The full list is `references/tables.md`, _Stop
conditions_. The ones that need care:

- **OVERSIZED (#5):** tell the user the planner's reasons, the subsystems it
  found and its suggested split lines, all in the `REPORT` (copied from
  PLAN.md's Size check), then ask its `QUESTION`: the user may sign it off, or
  tell the fixer how to narrow it. Nothing else.
- **No round left for the plan's revision (#11):** the user can add rounds
  (`SKILL.md`, _The loop_).
