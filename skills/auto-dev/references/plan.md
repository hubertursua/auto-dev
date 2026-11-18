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
move into the worktree. What you will see:

1. A saved profile: one `lookup` to spawn (whether each quality-gate check's
   tool is adopted). When it finds one or more not adopted, the gate-check
   question comes before the run exists (exit 5): show the `SUMMARY` (each
   flagged check, the lookup's reason, the saved file), ask the `QUESTION`
   and run the `AFTER` line for the answer. `Keep them` keeps every check (one
   that fails stops the run at the quality gate, where the user can sign it
   off); `Leave them out of this run` creates the run without them; `Stop`
   ends setup with nothing created. When leaving them out would leave no
   test check, only `Keep them` and `Stop` are offered. `autodev.py` makes
   the run's profile from the answer and never changes the saved file: never
   edit a profile yourself. A saved file changed since its lookup is looked
   up again, and the question asked anew.
2. No usable profile (none saved, an invalid one, or a `.auto-dev.yml` that
   doesn't set both `setup` and `gate`): the `profiler` to spawn, then the
   profile question (exit 5). Show the `SUMMARY` (the profiler's questions
   first, then what isn't installed, the evidence, the draft YAML, the keys
   `.auto-dev.yml` overrides and the save path) and the permissions guidance
   from `references/profiles.md`, _Permissions_, with the `SUMMARY`'s paths and
   the draft's commands filled in, then ask the `QUESTION`. Run the `AFTER`
   line for the answer: `Change something` takes the user's words as its
   `<…>` (the profiler redoes the draft and you ask again); `Stop` ends
   setup with nothing created. A `.auto-dev.yml` that sets both `setup` and
   `gate` needs neither.
3. The run is created: the action says to tell the user its `SUMMARY` lines
   (the profile in use, a check left out or kept at the gate-check question,
   a profile that could not be saved,
   commits already on a worktree you made), then `cd <worktree>` (the path it
   names; the one you are in when the run uses yours). Every later step runs
   there, with the `next --dir` command its `AFTER` names.

An `ACTION` that starts with `wait` means a worker it spawned is still out, as
in the loop. Exit 4 is a stop (`references/tables.md`, stop conditions 1–3):
tell the user the `REPORT`; it says how to go on. A setup command that failed
keeps the run: once the user fixed the file the `REPORT` names, they say
`auto-dev continue`, and `next` runs setup again.

When `<repo>` is a worktree the user made (a linked worktree on a branch other
than the base and the default branch), the run uses it instead of making a new
one; setup stops if it has uncommitted changes. The run finds the security
directives itself (`security_docs` in `.auto-dev.yml`, else `SECURITY.md`,
`.github/SECURITY.md` and `docs/security/`).

## Phases 2–3 — Plan and Tests, the loop

### 3. Run the loop

Follow **The loop** in `SKILL.md` until `next` exits 3, 4 or 6. What you will
see in the Plan stage, in order:

1. `planner` writes `PLAN.md`: the ask, the testable conditions, the
   assumptions, the size check, the risk tier it proposes and the build steps,
   from the ticket text the run stored (else your `--ask`). `OVERSIZED` → exit 4:
   tell the user the planner's reasons, the subsystems it found and its
   suggested split lines, all in the `REPORT` (copied from PLAN.md's Size
   check), then ask its `QUESTION` (`SKILL.md`, _A stop_): the user may sign it
   off, or tell the fixer how to narrow it. Nothing else.
2. With a ticket: the Jira question (exit 5). Read the ticket's status first
   (`references/gates-and-jira.md`, _Asking first_): if it is in progress
   already, don't ask, and run the `Already …` line. On `Move it`, a later exit 0
   says to move the ticket: do it as `references/gates-and-jira.md`,
   _Moving a ticket_ says, then run its `AFTER` line.
3. `plan-critic`, a fresh reader with the ticket, PLAN.md and the repo. With
   blockers, the `planner` revises once (a round), and the critic re-checks
   only the revision. A blocker still open after that goes to the user at
   the post-plan gate; the workers don't loop. The critic can raise the risk tier,
   never lower it. You do nothing but spawn.
4. The post-plan gate (exit 5) when the task is high-risk, the critic left
   blockers open (the gate lists them), or the repo turns it on: before any
   check is written, so a revision the user asks for never leaves one stale.
5. `acceptance-tester`. It writes a check per condition as ordinary test files
   in the worktree and shows each new-behavior check failing on the untouched
   code. It may be spawned once more for gaps in what it wrote (a second set
   of gaps stops), or send the `planner` a question about a condition that
   reads two ways. Then `next` commits the
   checks as their own commit (`test: acceptance checks for <task>`), before
   any code, by itself: there is nothing to run. From then on `check-tests.py`
   guards every line that commit added.
   A worker whose result `next` refuses (a `RECORDED: … refused` line) is
   briefed again by that `next`, with the refused issues.
6. Once the tests are written, `next` says the run goes on to the Build stage in
   this session: read `references/build.md`, as its `ACTION` says, then run `next`.
   Don't stop or hand off.
7. Exit 6, a checkpoint: run its `AFTER` command exactly as printed (`handoff
   --checkpoint`), give the user its message, stop. A fresh session picks the
   run up where it is.

### Stops in the Plan stage

Every stop is exit 4 with its reason in `REPORT`, and most ask how to go on
(`SKILL.md`, _A stop_). The full list is
`references/tables.md`, _Stop conditions_. The usual ones here: OVERSIZED,
no round left for the plan's revision (the user can add rounds: `SKILL.md`,
_The loop_), a worker that didn't return ok twice, and the acceptance checks
still having gaps after the tester's one more go, or a condition still reading
two ways after the planner's decision (#22).
