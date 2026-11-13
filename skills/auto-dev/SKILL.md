---
name: auto-dev
description: >-
  Autonomously carries one coding task from ticket, idea or spec to a finished,
  reviewed pull request, running a plan → build → verify → ship pipeline with
  subagents and human gates. Use when the user wants a whole feature or fix
  built AND shipped hands-off in one pass: "do it autonomously", "by yourself",
  "raise/open the PR", "take it all the way", "from ticket/idea/spec to PR",
  "run the whole dev cycle", "don't make me babysit each step", "pick up
  JIRA-1234 and ship it". ALWAYS use it when the user asks to auto-dev a task
  ("auto-dev: …", "auto-dev this"), however small. Prefer it over guided
  feature-development help for hands-off work. Unless asked to auto-dev it, do
  NOT use for one slice of the work: fixing one test/lint/type error, critiquing
  a plan, explaining code, or answering a question (about auto-dev too). Also
  use to RESUME a run in flight — "auto-dev continue", "pick up where the plan
  session left off" — since the pipeline stops between its plan, build and ship
  sessions.
---

# auto-dev

auto-dev carries one task from a ticket to a merged pull request. Workers
(subagents, one per job) do the work and write files in `.auto-dev/`. You are
the **orchestrator**: you run one command, do the one thing it prints, and
repeat. You never write code, never judge the build, and never decide what
comes next yourself.

The pipeline:

```
Phase 1  Setup   → find or research the repo's profile, create (or adopt) the worktree   (S1 Plan)
Phase 2  Define  → SPEC.md, the testable contract, and the size check          (S1 Plan)
Phase 3  Plan    → IMPLEMENTATION.md, then sealed acceptance checks             (S1 Plan)
Phase 4  Build   → the coder builds from the plan                               (S2 Build)
Phase 5  Verify  → cleanup and the quality gate, then the verifier runs checks (S2 Build)
Phase 6  Ship    → reviews, PR gate, commit, PR, CI, main gate, merge  (S3 Ship)
```

It runs in three sessions: **S1 Plan**, **S2 Build**, **S3 Ship**. Each ends
by writing `.auto-dev/HANDOFF.md` and stopping; the user starts a fresh session
and says `auto-dev continue`. Every session runs on whatever model the user
picked. Never ask them to switch.

## Paths

`<skill-dir>` is this skill's base directory (named when the skill loads).
Run every bundled script by its absolute path under it, never relative to the
repo. Below, `autodev.py` means `python3 <skill-dir>/scripts/autodev.py`.
`<artifact-dir>` is `<worktree>/.auto-dev`.

## Hard rules

1. **Never read source code, diffs, CI logs or PR comments.** Ask `lookup`
   (`references/tables.md`, _Lookups_). Workers read; you route.
2. **Never judge the build or edit an artifact.** Workers write the reports and
   the required changes; scripts check them. You pass files on unedited.
3. **Spawn exactly the agent type `next` names**, with exactly its `PROMPT`.
   Never pass the Agent tool's `model` parameter. Pass its `effort`
   parameter only when `next` prints an `EFFORT` line for that agent, set to
   that value; never otherwise. Never substitute
   `general-purpose` or another type.
4. **Only `autodev.py` writes `state.json`.** Never edit it or `WORK_LOG.md`.
5. **Never commit `.auto-dev/`, never push with `--force`, never merge with
   `--admin`.** The scripts already enforce this; don't work around a refusal.
6. **Never weaken security to finish**: no disabled checks, no secrets in code
   or tests. The repo's rules override "finish the task".

## Start here

1. Run `autodev.py resume --repo <the directory you are in>`, adding
   `--task "<the ticket key or task, word for word>"` when the user stated one.
   Leave `--task` out on a bare `auto-dev continue`: inside a run's worktree,
   `resume` picks that run.
2. Act on the first word it prints:

| Prints | Do |
|---|---|
| `FRESH` | a new run: follow `references/S1-plan.md` from step 1 |
| `RESUME <tree>` | read the runbook for the session it names (`S1-plan.md`, `S2-build.md` or `S3-ship.md`). IF it also printed an `action:` line (setup is not done), run that `init --continue` command first, as `S1-plan.md` says. Then go to **The loop** |
| `ASK` | show the user the `candidates` lines and ask which run is theirs, or whether to start fresh. Then run `resume` again with `--task` set to the chosen run's task, or follow `S1-plan.md` for a fresh one |
| `FINISHED <tree>` | tell the user that run already finished or was stopped; ask whether to start a fresh one |
| `OLD-VERSION <tree>` | tell the user: "This run was started on auto-dev 3.x. Finish it on auto-dev 3.9, or remove its worktree (`git worktree remove <tree>`) and start again." Then stop |

Being given a task always means that task: `resume` never continues a run
that doesn't match it. No task and nothing to continue means `ASK`: ask the
user what to work on; never start a run unasked.

## The loop

From inside the worktree, repeat:

1. Run `autodev.py next --dir <artifact-dir>`.
2. Do what its `ACTION` line says, using the lines below it.
3. Run each `AFTER` command, in order (for a question, only the one for the
   user's answer).
4. Go back to 1.

Its exit code says what kind of step it is:

| Exit | Meaning | Do |
|---|---|---|
| 0 | an action | Do it. Spawn each `AGENT` with its `PROMPT` (and its `EFFORT`, rule 3); several `AGENT` lines go in **one message**, in parallel, and you run `next` again only once every one has returned (not on the first agent's notification). A command in backticks: run it. Then the `AFTER` lines |
| 2 | could not run | Tell the user the `ERROR` line and stop. Don't work around it |
| 3 | the run is complete | Do the `ACTION` if it names a command, then stop |
| 4 | stop and report | Tell the user every `REPORT` line, in your own words if needed. With a `QUESTION`, the user decides how to go on (_A stop_, below); without one, stop. Do nothing more (one exception: more rounds after a budget stop, below) |
| 5 | ask the user | Show the `SUMMARY` lines, then call AskUserQuestion with the `QUESTION` JSON as given, unless `ACTION` says to read the ticket first: then follow it, and ask only when it says to. Run the `AFTER` line whose label matches the answer, filling in any `<…>` with what the user said |
| 6 | end of session, or a checkpoint | Run the `AFTER` command, give the user the message it prints, and stop. Do not start the next phase |

`next` never exits 1: a step it can't take is a stop (4) that says why.

Every path and value in a printed command is already shell-quoted. A `<…>`
placeholder (a reason, a commit subject) sits inside single quotes: replace it
there with text that holds no single quote (rephrase, or use the typographic
apostrophe ’), and change nothing else on the line.

`next --explain` only looks: it prints the action `next` would take and a
`RULE:` line naming why, but writes no brief and saves nothing. Use it when the
user asks why; run `next` without it to act.

**After a worker returns**, just run `next`: it records each result first
(its `RECORDED` lines say what it found). A result it can't accept is refused,
and the same `next` briefs that job again with the issues in its
`previous_issues` slot. Never write the retry brief yourself (`brief --retry`)
and never fix the worker's file yourself.

**A stop** is not final. When it prints a `QUESTION`, show the `SUMMARY`
lines and ask it with AskUserQuestion. A typed answer (Other) is the user's
instruction for the fixer: run the `"<a typed answer>"` `AFTER` line with
their words, then `next`, which spawns the fixer to do exactly that; when all
it asks is that a quality-gate check run differently, run the `"<a typed
change to a gate check>"` line instead, then _I fixed it myself_'s. For a
pick, run its `AFTER` line, then `next`: _I fixed it myself_ runs the step
that stopped again; _Sign off and go on_ (offered only where it is safe)
accepts the result; _Approve the fixer's proposal_ lets the fixer do what it
proposed. _Let's talk it through_: discuss the stop with the user (a `lookup`
for any fact about the code, never the code itself), then run `next`, which
asks again; when they give an instruction or a pick in the talk, run its
`AFTER` line. After _Leave it stopped_, stop. Never edit `.auto-dev/` files or
fix the cause yourself to get past a stop: the override is the way past it
(`references/tables.md`, _Overriding a stop_). The budget stop has no
question; when the user asks for more rounds and says how many (right after
the stop, or as `auto-dev continue with <n> more rounds`), run the `budget
raise` command its `REPORT` names with their number, then `next`. Never add
rounds they didn't ask for.

**Never skip a step or run one `next` didn't print**, except the ones in your
session's runbook.

## Spawning a worker

`next` names each agent as `auto-dev:<worker>`. Use the first of these in your
available agents list: `auto-dev:auto-dev-<worker>` (plugin install),
`auto-dev:<worker>`, or `auto-dev-<worker>` (agents symlinked into
`~/.claude/agents/`). If none exists, stop and tell the user to install the
plugin. Each worker's model and tools are fixed by its agent file:

| Worker | Agent type | Model · effort |
| ------ | ---------- | -------------- |
| Profiler (Phase 1, only with no saved profile) | `auto-dev:profiler` | `sonnet` · high |
| Define agent (Phase 2; rules on spec proposals in Phases 5–6) | `auto-dev:define` | `opus` · high |
| Define reviewer (Phase 2) | `auto-dev:define-reviewer` | `opus` · high |
| Planner (Phase 3; rules on the coder's plan proposals in Phases 4–6) | `auto-dev:planner` | `opus` · xhigh |
| Plan reviewer (Phase 3) | `auto-dev:plan-reviewer` | `opus` · high |
| Acceptance tester (Phase 3; rules on check proposals in Phases 4–6) | `auto-dev:acceptance-tester` | `opus` · high |
| Coder: the build and every correction | `auto-dev:coder` | `opus` · high |
| Verifier (Phase 5, re-spawned on every change) | `auto-dev:verifier` | `opus` · high |
| Cleanup agent (Phase 5, re-spawned on fixes) | `auto-dev:cleanup` | `sonnet` · high |
| Code reviewer, ×3 panel + re-votes (Phase 6) | `auto-dev:code-reviewer` | `opus` · high |
| Review judge (Phase 6) | `auto-dev:review-judge` | `opus` · xhigh |
| Security reviewer (Phase 6) | `auto-dev:security-reviewer` | `opus` · xhigh |
| Security reviewer, sensitive paths (Phase 6) | `auto-dev:security-reviewer-sensitive` | `opus` · xhigh |
| Triager: red CI, human PR comments (Phase 6) | `auto-dev:triager` | `sonnet` · high |
| Your read-and-answer lookups | `auto-dev:lookup` | `haiku` · medium |
| Fixer: the user's instruction at a stop | `auto-dev:fixer` | `opus` · high |

To change a worker's model, edit its `agents/<name>.md` frontmatter, this
table and README.md's _Models and effort_ table together. The one per-run
override is the code reviewers' effort, which the plan sets (the `EFFORT`
line of rule 3).

## Reading discipline

You hold the pipeline, not the code. Each file you read stays in your context
for the rest of the session.

- Read only what your runbook names. Everything else: `lookup`.
- `git status`, `git diff --stat` and `git log --oneline` are fine. A full diff
  is never yours.
- Don't re-read a reference file in the same session.

## Reference files

| File | Read when |
|---|---|
| `references/S1-plan.md` | a fresh run, or a resumed run in S1 |
| `references/S2-build.md` | a run resumed in S2 |
| `references/S3-ship.md` | a run resumed in S3 |
| `references/tables.md` | to explain a stop or how to override one, a gate option, the budget or a stale report; to ask a lookup |
| `references/gates-and-jira.md` | when `next` says to move a Jira ticket |
| `references/profiles.md` | Phase 1, when resolving the profile |
