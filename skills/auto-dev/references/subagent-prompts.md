# Spawning workers

How the orchestrator spawns each worker (the subagent for each delegated job)
and acts on what it returns. The workers' own instructions are not here: each
one's brief is its agent file, `agents/<name>.md`, which is its system prompt,
with a `## Mode: <name>` section for each mode.

**Every spawn is three commands.**

1. `python3 <skill-dir>/scripts/autodev.py brief <worker> [--mode <mode>] [--set
   name=value …]` writes `briefs/<worker>-<n>.md`, filling every slot it can
   from `state.json` and the artifacts (paths, base, task, the profile's
   commands, acceptance check paths, survivors, the review pass). It refuses
   when a slot only you can give is missing, and names it.
2. Spawn the agent type it prints, with the one-line prompt it prints ("Your
   brief is at <path>. Read it first."). Never paste instructions into the
   prompt, and never pass the Agent tool's `model` parameter: the type fixes the
   worker's model and effort (`agents/<name>.md`; the model table in
   `SKILL.md`).
3. When it returns, `autodev.py record <worker> <n>` checks the result block it
   wrote to `returns/<worker>-<n>.json` against the artifact it wrote. `RECORDED`
   prints the `next` token to act on, as each section below says. `MISMATCH`
   means the return and the artifact disagree: re-spawn the worker with the
   issues it printed, never guess which is right.

Workers read the templates (`templates/`) and the rubric (`templates/rubric.md`)
by path, and run `autodev.py check-artifact` on what they write before they
return.

## Contents

- **Models** — why judgment stays on `opus` and what moves to `sonnet`.
- **Tools per worker** — the tool list each worker type gets.
- **What every brief says** — the rules each agent file carries.
- **Phase 1 — Profile research**
  - **Profiler** — returns a draft stack profile for the user to confirm.
- **Phase 2 — Define**
  - **Define agent** — writes `SPEC.md`; revise mode.
  - **Define reviewer** — FIX blocks, applied by `autodev.py apply-fix`.
  - **Size check (orchestrator)** — FITS goes on; OVERSIZED stops the run.
- **Phase 3 — Plan**
  - **Planner** — writes `IMPLEMENTATION.md`; revise and blocked modes.
  - **Plan reviewer** — FIX blocks, like the Define reviewer.
  - **Acceptance tester** — writes and seals the held-out checks under
    `acceptance/`.
  - **Optional post-plan gate (orchestrator)**
- **Phase 4 — Build**
  - **Coder (TDD)** — the build brief, the correction brief, and what to do
    with a `BLOCKED` report (the planner's blocked mode).
- **Phase 5 — Verify**
  - **Verifier** — runs the checks, writes `SPEC_EVAL.md` and
    `evidence/corrections.md`.
  - **Acting on SPEC_EVAL.md (orchestrator)** — `autodev.py eval-status`, the
    correction, and repairing a defective acceptance check.
  - **Cleanup agent (simplify + quality gate)** — writes `lint/<CHECK>.md`.
  - **Re-verify after cleanup (verifier re-spawn)**
- **Phase 6 — Ship** (the procedure and the rubric are in `references/review.md`)
  - **Code reviewer: review mode** — one of three; writes `review/pass-<n>/R<k>.md`.
  - **Code reviewer: re-vote mode** — writes `review/pass-<n>/VOTES-R<k>.md`.
  - **Review judge: consolidate** — writes `CODE_REVIEW.md`.
  - **Security reviewer** — writes `SECURITY_REVIEW.md`.
  - **Review judge: security-verify** — fills `SECURITY_REVIEW.md`'s `Verified`
    cells.
  - **Triager: CI mode** — classifies a red CI run.
  - **Triager: human mode** — sorts the PR's review comments.
- **Any phase**
  - **Lookup** — the questions it answers.

## Models

Judgment stays on `opus`: a weak reviewer returns "no findings," which
is indistinguishable from a clean pass, and a weak plan spends revise rounds
downstream. Only work that a later check verifies moves down to `sonnet`: the
cleanup agent (the
quality gate and the re-verify catch it), the profiler (the user confirms its
profile, and `setup` and the quality gate run it), lookups (they only report),
and the triager (its CI class and its sorting of comments decide only which
loop runs; the fix it asks for is reviewed like any other). The
acceptance tester, the verifier, the review panel, the judge and the security
reviewer are all judgment, so all stay on `opus` (or
`fable` for the sensitive-path security reviewer). The routing rule
(`auto-dev:security-reviewer-sensitive` for sensitive paths) is in
`SKILL.md` and on each brief's `_Agent type:_` line below.

The types name model **families** (`opus`, `sonnet`, `fable`), never a version, so
each resolves to the current release without editing this skill.

## Tools per worker

Each type's `tools:` frontmatter, this list, and the `_Tools:_` line on each brief
below state the same thing; change them together:

- **Orchestrator (you):** TodoWrite, Bash (`autodev.py`, git/gh), Read, the
  Agent/Task tool (spawn every worker), AskUserQuestion
  (gates), Skill (only if a fitting skill opens the PR in 6a), and — when a
  ticket is present — ToolSearch to locate the Atlassian MCP Jira tools, then those
  tools.
- **Profiler (Phase 1):** Read, Grep, Glob, Bash, Write — writes only the draft
  profile, to the path its brief names.
- **Define agent (Phase 2):** Write + Read, Grep, Glob (research is read-only; it
  writes `SPEC.md`).
- **Define reviewer (Phase 2):** Read, Grep, Glob, Write — writes only its FIX
  file; never edits `SPEC.md`.
- **Planner (Phase 3):** Write + Read, Grep, Glob.
- **Plan reviewer (Phase 3):** Read, Grep, Glob, Write — writes only its FIX
  file; never edits `IMPLEMENTATION.md`.
- **Acceptance tester (Phase 3):** Read, Write, Edit, Bash, Grep, Glob — writes
  only its own checks (removed from the worktree before it returns) and
  `acceptance/`; never source.
- **Coder (Phase 4):** Read, Write, Edit, Bash, Grep, Glob.
- **Verifier (Phase 5, re-spawned after every later change):** Read, Grep, Glob,
  Bash, Write — read-only w.r.t. source and tests (its mutants are applied and
  restored by `scripts/mutate.py`, never by hand); it installs the sealed
  acceptance checks and writes `SPEC_EVAL.md` and `evidence/` (with
  `evidence/corrections.md`).
- **Cleanup agent (Phase 5, re-spawned after later corrections):** Read, Edit, Write, Bash, Grep,
  Glob, plus the **Skill** tool to run `/simplify`.
- **Code reviewer (Phase 6a):** Read, Grep, Glob, Bash (`git diff`, `git blame`),
  Write, plus the **Skill** tool to run `/code-review` — read-only **w.r.t.
  source**; it writes only its own report under `review/pass-<n>/`.
- **Review judge (Phase 6a):** Read, Grep, Glob, Bash (`git diff`, `git blame`),
  Write — read-only w.r.t. source; it writes `CODE_REVIEW.md`, or edits
  `SECURITY_REVIEW.md` in security-verify mode.
- **Security reviewer (Phase 6a), both types:** Read, Grep, Glob, Bash, Write, plus
  the **Skill** tool to run `/security-review` — read-only w.r.t. source; it writes
  `SECURITY_REVIEW.md`.
- **Triager (Phase 6):** Read, Grep, Glob, Bash, Write — reads CI logs or PR
  comments with `gh`; writes only its triage file; never touches source.
- **Lookup (any phase):** Read, Grep, Glob, Bash, Write — answers a question,
  and writes only its answer file when the prompt names one.

## What every brief says

Every agent file carries these, so you never add them:

- **Non-interactive:** the worker never asks the user; it resolves ambiguity with
  a recorded assumption.
- It works inside `<worktree>`; `<artifact-dir>` is the one other path it may
  write to.
- It writes its artifact to the template in `templates/`, checks it with
  `autodev.py check-artifact`, and ends with an `auto-dev-result` block that it
  also writes to `returns/<worker>-<n>.json`.
- The binding rules and the security directives named in `profile.md` override
  "finish".
- **Spill large output to `$TMPDIR`; return a digest, never a corpus.**
- **Keep any single command under 5 minutes.** A worker's prompt cache is
  short-lived, so a worker idling on a long blocking command has its whole
  context re-billed. **The cleanup agent's quality gate is the one exception**:
  it is the Definition of Done and runs in full, in the background.

---

## Phase 1 — Profile research

### Profiler
_Agent type: `auto-dev:profiler`._
_Tools: Read, Grep, Glob, Bash, Write (it writes only the draft profile)._

Spawned at Phase 1 step 2 only when no usable saved profile exists and
`.auto-dev.yml` doesn't set both `setup` and `gate` (`references/profiles.md`,
_How Phase 1 resolves the profile_). There is no worktree or `<artifact-dir>`
yet: it reads the main checkout. Its reply is what you show the user at the
profile confirmation, so it must stand on its own.

The return's commands are an example in TypeScript; leave them out of the brief.

The brief is `agents/profiler.md`. Write its slots and spawn it:

```bash
python3 <skill-dir>/scripts/autodev.py brief profiler --out $TMPDIR --set repo=<repo> --set base=<base> --set draft_path=$TMPDIR/auto-dev-profile.yml
```

Spawn `auto-dev:profiler` with the one-line prompt it prints. When the worker returns, run `autodev.py record profiler <n>` and act on its `next`.

A return shaped like this, example in TypeScript:


---

## Phase 2 — Define

### Define agent
_Agent type: `auto-dev:define`._
_Tools: Write + Read, Grep, Glob (research is read-only; it must not modify source)._

One pass that researches the ticket against the codebase, states the acceptance
conditions **as a testable contract**, and returns the **size check** the
orchestrator branches on. Research and spec are the same worker's job on
purpose: the worker holding the codebase research is the one best positioned to
know what is actually observable.

The brief is `agents/define.md`, mode `write`. Write its slots and spawn it:

```bash
python3 <skill-dir>/scripts/autodev.py brief define --mode write
```

Spawn `auto-dev:define` with the one-line prompt it prints. When the worker returns, run `autodev.py record define <n>` and act on its `next`.

After it returns, act on its SIZE line (_Size check_, below). `SPEC.md` is
withheld from the coder (Phase 4); the verifier checks the build against it in
Phase 5.

**Revise mode** (`autodev.py brief define --mode revise`), when a Define
reviewer's FIX file didn't apply (`autodev.py apply-fix` printed `NO-MATCH`:
`--set fix_file=<that file>`), or when the acceptance tester reports a condition
AMBIGUOUS (`--set ambiguous="condition <n>: <the reading it tested> / <the
other reading>"`).

A revise spawn spends no round of its own: the review it serves already spent
one, and an AMBIGUOUS reading is settled before any check is re-written. On
`reading: other`, re-spawn the acceptance tester with Scope "ONLY condition
<n>" (a round, consumer #2).

No brief returns a slug: Phase 1 derived it and cut the branch and worktree before
this phase ran, so a slug proposed here could only conflict with paths already on
disk.

### Define reviewer
_Agent type: `auto-dev:define-reviewer`._
_Tools: Read, Grep, Glob only (must not rewrite the file)._
Runs only after the size check returns FITS.

The brief is `agents/define-reviewer.md`. Write its slots and spawn it:

```bash
python3 <skill-dir>/scripts/autodev.py brief define-reviewer
```

Spawn `auto-dev:define-reviewer` with the one-line prompt it prints. When the worker returns, run `autodev.py record define-reviewer <n>` and act on its `next`.

Apply its FIX file with `autodev.py apply-fix <artifact-dir>/SPEC.md
<artifact-dir>/fixes/define-<n>.md`. `APPLIED` → go on. `NO-MATCH` (nothing was
written) → spawn the Define agent in revise mode with that file. Re-review only
if `BLOCKERS` was above 0, and repeat until a review returns `BLOCKERS: 0`.
Each re-review consumes a round of the shared iteration budget
(`autodev.py budget spend --consumer 1`); at zero, stop and report the open
blockers (`references/correction-loop.md`).

### Size check (orchestrator)

Read the **SIZE** line of the Define agent's return, before the Define reviewer
runs.

- **FITS** — record `Size: FITS` and `High risk: <yes|no>` in `WORK_LOG.md`'s
  header. If there is a ticket, move it to In Progress now
  (`references/gates-and-jira.md`, _Jira In Progress confirmation_). Then run the
  Define reviewer.
- **OVERSIZED** — the task goes back to the user; auto-dev builds nothing.
  1. Record `Size: OVERSIZED` in `WORK_LOG.md`'s header, mark Phase 2 `blocked`
     with the Notes `OVERSIZED`, and Phases 3–6 `n/a`. Skip the Define reviewer.
  2. Leave Jira alone: it was never moved to In Progress.
  3. Keep the worktree and branch. Delete nothing.
  4. Report to the user, then stop: the task is too big for one PR; Define's
     reasons, the subsystems it found and its suggested split lines (a hint for
     whoever splits the task; auto-dev does not act on them); `SPEC.md`'s path, for
     reference; and the commands that remove the worktree and branch if the user
     doesn't want them: `git worktree remove <worktree>` and
     `git branch -D <branch>`.

---

## Phase 3 — Plan

The planner writes every plan, then the plan reviewer and the acceptance tester
run. Every task takes all three steps.

### Planner
_Agent type: `auto-dev:planner`._
_Tools: Write + Read, Grep, Glob._

The brief is `agents/planner.md`, mode `write`. Write its slots and spawn it:

```bash
python3 <skill-dir>/scripts/autodev.py brief planner --mode write
```

Spawn `auto-dev:planner` with the one-line prompt it prints. When the worker returns, run `autodev.py record planner <n>` and act on its `next`.

**Revise mode** (`autodev.py brief planner --mode revise`), when a plan
reviewer's FIX file didn't apply (`--set fix_file=<that file>`), or when the
user picks `Revise plan` at the post-plan gate (`--set direction="<the user's
words, verbatim>"`). Its result says `entry_points_changed`.

**Blocked mode** (`autodev.py brief planner --mode blocked --set
blocked="the steps listed in <artifact-dir>/blocked/coder-<n>.md"`, the file
the coder wrote; `autodev.py next` fills it in), when the coder returns
`next: BLOCKED` (_Coder (TDD)_, below). Its `next` is the decision.

### Plan reviewer
_Agent type: `auto-dev:plan-reviewer`._
_Tools: Read, Grep, Glob only._

The brief is `agents/plan-reviewer.md`. Write its slots and spawn it:

```bash
python3 <skill-dir>/scripts/autodev.py brief plan-reviewer
```

Spawn `auto-dev:plan-reviewer` with the one-line prompt it prints. When the worker returns, run `autodev.py record plan-reviewer <n>` and act on its `next`.

Apply its FIX file with `autodev.py apply-fix <artifact-dir>/IMPLEMENTATION.md
<artifact-dir>/fixes/plan-<n>.md`; on `NO-MATCH`, spawn the planner in revise
mode with that file. Re-review only if `BLOCKERS` was above 0, and repeat until
a review returns `BLOCKERS: 0`. Each re-review consumes a round of the shared
budget (`autodev.py budget spend --consumer 2`); at zero, stop and report the
open blockers (`references/correction-loop.md`).
A spec condition with no plan step is cheapest to catch here, before code exists.

### Acceptance tester
_Agent type: `auto-dev:acceptance-tester`._
_Tools: Read, Write, Edit, Bash, Grep, Glob._ Runs once the plan is final (after
the plan review settles), before the
post-plan gate and before any code exists.

The coder's own tests are written by the agent whose work they judge, so they
cannot be the main evidence that the work is right. This agent writes a second,
**held-out** set from `SPEC.md` alone, proves each new-behavior check fails on
the untouched tree (a check that passes before the change exists proves nothing
about it), and then **seals** them: removes them from the worktree and keeps the
only copy under `<artifact-dir>/acceptance/`. The coder never sees them during
the build; the verifier installs them afterwards (Phase 5).

The brief is `agents/acceptance-tester.md`, mode `write`. Write its slots and spawn it:

```bash
python3 <skill-dir>/scripts/autodev.py brief acceptance-tester --mode write --set scope="ALL CONDITIONS"
```

Spawn `auto-dev:acceptance-tester` with the one-line prompt it prints. When the worker returns, run `autodev.py record acceptance-tester <n>` and act on its `next`.

Check the return, and MANIFEST.md against SPEC.md, before moving on:
- every condition is covered by a check or listed under Not automatable;
- every condition with an Edge line that doesn't start with `none`, and that
  isn't wholly under Not automatable, has a check covering its Edge, or a
  `<n> (Edge)` row under Not automatable with a reason;
- no check's Level is below its condition's Verify by, unless the Level says
  why;
- every check has its base-run/C<n>.txt, with a Result line that matches its
  kind: a pass-to-pass check passed, and a fail-to-pass check failed for the
  right reason (step 3). Read the Output to judge the reason, not just the word
  `failed`. A repaired check reads `not re-run (repair)`;
- `git status` in the worktree is unchanged.
Anything short of this is a gap. A MANIFEST.md written before 3.9 has no Covers
or Level column and no base-run/ beside it. On a resumed run, keep it as it is
and don't re-spawn the tester for that; the verifier works from what it has.
For each **AMBIGUOUS** condition, spawn the Define agent in revise mode with
both readings (the tester writes them to `acceptance/AMBIGUOUS.md`); it records the meant one in `SPEC.md`'s Assumptions and returns
`READING: tester` (done, no round) or `READING: other` (re-spawn the tester with
Scope "ONLY condition <n>", a round, consumer #2).
Fix a gap by re-spawning this agent with Scope "ONLY conditions <the gap>" (a
first pass is not a round; a re-spawn spends one, consumer #2 in
`references/correction-loop.md`). Only the first spawn of a run uses ALL
CONDITIONS; every re-spawn names its conditions, or it would wipe the rest.

**Repair mode.** A check is repaired by this agent, never edited by the coder,
when someone reports it wrong or too weak. You don't judge the report: the
tester does, and may answer that the check stands. Four things lead here: the
verifier reports it defective (_Acting on SPEC_EVAL.md_, below); a `BLOCKED` plan revision or a
post-plan-gate revision changes an entry point it calls; or, in Phase 6, a
must-fix review finding or a human reviewer's blocker is about the check itself;
or the cleanup agent returns `GATE: ACCEPTANCE_CHECK_FAILS_GATE` — then the repair is
to make the check pass the gate without changing what it asserts, and the
cleanup agent is re-spawned after it (free).
A check reported too weak whose condition is still met (the verifier observed
the missing case itself, so it is Adequate) is not repaired: a repair would
spend a round and could reach Adequate at most. Record that with `autodev.py
note`. To repair, re-spawn this agent with the same brief, Scope "ONLY conditions <the
checks' conditions>", plus: "The tree now holds the built change and
these checks are installed at their paths. Fix each one IN PLACE at its
installed path, then copy it over its sealed copy so the two stay
byte-identical; do not remove it from the worktree. Skip the base run and
record its Base run as `not re-run (repair)`. Update its MANIFEST row; in its
base-run/C<n>.txt, if there is one, change its Result line to `<test name>:
not re-run (repair)` and leave the Output, which shows the check before the
repair; never create one. Leave every other check alone. The report: <the
verifier's defective-check reason, the judge's or triager's required change,
or the cleanup agent's error>. If, read against SPEC.md, the check is right as
it is, change nothing and return `STANDS: <why>`." On `STANDS`, the check
stays: a failure is the coder's to fix. Record the reason with `autodev.py
note` so a later pass's same report isn't decided again. Checks are
installed only from Phase 5 on. Before that, nothing is installed, so the repair re-runs the brief with Scope "ONLY
conditions <those checks' conditions>" and seals as on a first run (removing
the checks from the worktree again): after a post-plan-gate revision, with
the base run; after a Phase 4 `BLOCKED` revision, the tree already holds
partial code, so record the Base run as `not re-run (repair)`, and in its
base-run/C<n>.txt write `Commit: none`, `Command: none — not re-run (repair)`
and one Result line per check of the condition, `<test name>: not re-run
(repair)`. Then re-spawn the verifier in re-check mode. A repaired
check no longer proves the change was needed, so the verifier counts it as
Adequate evidence at most, never Strong. A repair spends a round from the entry
point that led to it (consumer #3 in Phase 4–5, #4 or #5 in Phase 6); a
post-plan-gate revision's spends none, like the revision itself.

### Optional post-plan gate (orchestrator)
If enabled for this run, pause here (`AskUserQuestion`) for the user to approve
`SPEC.md` + `IMPLEMENTATION.md` before any code is written, with
`acceptance/MANIFEST.md`'s coverage (checks per condition, and each condition
or Edge that is not automatable) in the summary. Off by default; see
`references/gates-and-jira.md`.

---

## Phase 4 — Build

### Coder (TDD)
_Agent type: `auto-dev:coder`._
_Tools: Read, Write, Edit, Bash, Grep, Glob._ Spawn with the **plan only — never
SPEC.md** (see *Why two documents* in `references/artifacts.md`).

The brief is `agents/coder.md`, mode `build`. Write its slots and spawn it:

```bash
python3 <skill-dir>/scripts/autodev.py brief coder --mode build
```

Spawn `auto-dev:coder` with the one-line prompt it prints. When the worker returns, run `autodev.py record coder <n>` and act on its `next`.

**Read the DEVIATIONS report as information, not a defect list.** The plan is a
route; the Phase 5 verifier decides whether the destination was reached. Do not
spend budget reconciling code with a plan it improved on. The verifier never sees
this report: it judges the code, not the coder's account of it.

**A `BLOCKED` report** means a step stopped rather than going green dishonestly.
Settle it before Phase 5 by spawning the planner in blocked mode (_Planner_,
above) with the coder's BLOCKED section, verbatim, and act on its `DECISION`:

- **`PLAN_REVISED` or `UPDATE_OLD_TEST`** — spend one round (consumer #3,
  `references/correction-loop.md`). With `ENTRY_POINTS_CHANGED: yes`, repair the
  checks for those entry points too (_Acceptance tester_, repair mode). Then
  re-dispatch `auto-dev:coder` for the stopped steps; after `UPDATE_OLD_TEST`,
  tell it the named test is in scope and goes under TEST CHANGES.
- **`SPEC_IMPOSSIBLE`** — the _self-contradictory or impossible_
  stop-and-report in `SKILL.md`. Report the conditions the planner named, and
  why.

---

## Phase 5 — Verify

### Verifier
_Agent type: `auto-dev:verifier`._
_Tools: Read, Grep, Glob, Bash, Write._ It never edits source; the one time source
changes under it is inside `scripts/mutate.py`, which restores every file it
mutates. Spawn it **without** `IMPLEMENTATION.md`,
the coder's return, or your correction history: it gets the contract and the
code, nothing that explains the code.

The verifier replaces reading the diff and judging it. Two things make its
verdicts worth more than a read: it **runs** the evidence instead of citing it,
and it holds none of the context that wants the build to have worked — the plan,
the coder's account, the rounds already spent. Anthropic's harness work found
agents "reliably skew positive" when grading work whose story they already hold,
and that an evaluator that clicks through the running system catches what one
that reads the code does not.

**Its first pass** runs once the build returns with nothing `BLOCKED`. **It is
re-spawned** — in re-check mode, never spending a round — after every
acceptance correction, after the cleanup agent (_Re-verify after cleanup_,
below), after every Phase 6 correction (`references/correction-loop.md`,
_The Phase 6a refresh_), and when its results go stale because the code changed
outside the pipeline (`references/correction-loop.md`, _Stale results_).

The coder is told not to commit, so **the change set is the working tree**, and
the brief's diff step has two halves that both fail silently. Without
intent-to-add, every file the coder _created_ is invisible to `git diff` —
usually most of the change. Mark the untracked files only, never `git add -N .`:
that also stages every deletion — real staged changes, not intent-to-add markers,
made before the PR gate approved any commit. And `git diff origin/<base>...HEAD`
reports an **empty** diff, because nothing is committed yet. Diff against the
commit Phase 1 cut the worktree from, `$(git merge-base origin/<base> HEAD)` —
not `origin/<base>` itself, which moves whenever anything fetches (worktrees
share refs) and would make upstream commits look like this branch reverting
them, and not the local branch, which may be stale. (Phase 6a's reviews run before the commit too, so they also
read the working tree; `references/review.md`, _What each review pass covers_.)

The brief is `agents/verifier.md`. Write its slots and spawn it:

```bash
python3 <skill-dir>/scripts/autodev.py brief verifier --set mode=first
```

Spawn `auto-dev:verifier` with the one-line prompt it prints. When the worker returns, run `autodev.py record verifier <n>` and act on its `next`.

The verifier's run spends no round, on its first pass or any re-spawn: like the
quality gate and the reviews, it is a check, and what bounds the loop is the
correction that sent it back (`references/correction-loop.md`).

### Acting on SPEC_EVAL.md (orchestrator)

Don't read `SPEC_EVAL.md` or the diff. Run `autodev.py eval-status` (pass
`--install-conflict` or `--mutation-left-changes` when the verifier returned
either) and act on the decision it prints:

- **`STOP`** — the source may no longer be the code that was built (a mutant
  could not be restored, or the test command wrote files). **Stop and report**,
  naming the paths the verifier gave: never let a worker build on that tree,
  and never guess which bytes are right. The user decides (`git diff`, the
  backups under `evidence/mutants.json.backup/`).
- **`REPAIR`** — a defective acceptance check is all that keeps the listed
  conditions from `met`. Repair them (_Acceptance tester_, repair mode), then
  re-spawn the verifier in re-check mode. One weak check spends one round, not
  two: those conditions are left out of the coder's correction.
- **`CORRECT`** — a Phase 5 correction, the correction loop's Phase 5 entry
  (consumer #3): an unmet or partial condition (a Test gap included), an
  Unjustified integrity finding, or an install conflict. Run `autodev.py
  spec-overlap <artifact-dir>/evidence/corrections.md`; on `OVERLAP`, re-spawn
  the verifier in re-check mode with "evidence/corrections.md copied SPEC.md's
  wording: <the phrases>; rewrite it in your own words" (no round). Then
  `autodev.py budget spend --consumer 3 --id <id>` and spawn `auto-dev:coder`
  with the correction brief below. When `REPAIR` is printed too, repair first.
- **`ALL_MET`** — nothing open. A `manual` condition, or an Edge
  `SPEC_EVAL.md`'s _Unresolved_ leaves for a person, is not a correction:
  nothing the coder writes can make it observable here. Both go to the PR gate,
  and to the PR body's _Checks for a person_.

An install conflict means the coder wrote a file at an acceptance check's path:
the correction moves it, then the verifier's first pass runs again.

**The previous survivors.** Each verifier re-spawn's brief carries the
Mutation rows from the `SPEC_EVAL.md` it replaces (`brief` fills them): the
verifier's own earlier output, so it can re-test each Test gap and keep its
Equivalent judgments stable.

**The correction brief.** It is the same for every correction, wherever the
required changes came from: the verifier's `evidence/corrections.md`, the review
judge's `review/pass-<n>/corrections.md` or `review/security-corrections.md`, or
the triager's `triage/<ci|human>-<n>.md`. Pass the file unedited; never write
the changes yourself.

The brief is `agents/coder.md`, mode `correction`. Write its slots and spawn it:

```bash
python3 <skill-dir>/scripts/autodev.py brief coder --mode correction --set corrections_file=<file>
```

Spawn `auto-dev:coder` with the one-line prompt it prints. When the worker returns, run `autodev.py record coder <n>` and act on its `next`.

After it returns, re-spawn the verifier in re-check mode and run `eval-status`
again. Repeat until it prints `ALL_MET`. Do not run the `gate` commands
yourself, and do not spawn the cleanup agent per correction: it runs after this
loop settles, so `/simplify` and the quality gate see the final code. If
anything is still open when `budget spend` exits 3 (exhausted), **stop and
report** exactly which conditions and findings remain and what was tried.

This is one entry point into the pipeline's single correction loop — its steps,
what a correction invalidates at each point, and the budget accounting are in
`references/correction-loop.md`.

### Cleanup agent (simplify + quality gate)
_Agent type: `auto-dev:cleanup`._
_Tools: Read, Edit, Write, Bash, Grep, Glob, plus the **Skill** tool to run `/simplify`._

Runs after the Phase 5 correction loop settles, so corrective code gets simplified too,
is re-spawned after any Phase 5 correction made after that pass (_Re-verify after
cleanup_, below), is **re-spawned after every Phase 6 correction**
(a must-fix review finding, a human blocker or red CI) on the code that correction
changed, and is re-spawned with no simplify step when its reports go stale
because the code changed outside the pipeline (the _Outside changes_ scope). No spawn of it spends the iteration budget.
`/simplify` is *meant* to preserve behavior; Step 2's quality gate is what checks that it
did.

The brief is `agents/cleanup.md`. Write its slots and spawn it:

```bash
python3 <skill-dir>/scripts/autodev.py brief cleanup --set scope=phase5
```

Spawn `auto-dev:cleanup` with the one-line prompt it prints. When the worker returns, run `autodev.py record cleanup <n>` and act on its `next`.

`--set scope=` names one of the scopes in its agent file:

- **`phase5`** — the first pass, or a re-spawn after a later Phase 5 correction.
- **`review-fix`** (with `--set files="<the paths review-scope --files
  printed>"`) — after a correction to a review finding, before the commit.
- **`after-commit`** — after a CI-red or human-blocker correction. Why the
  scope is narrower: `references/correction-loop.md`.
- **`outside`** — a stale-results re-run (`references/correction-loop.md`,
  _Stale results_): Step 1 is skipped, since the code changed outside this
  pipeline.

Step 1 is **unconditional** except for the _Outside changes_ scope, which skips
it by design — `/simplify` is a built-in skill, so there is nothing to detect and
no other skip path. If the return says the simplify step was skipped on any other
scope, that is a bug in the run, not an expected outcome.

If the agent returns any check at fail (the 3-attempt cap reached, or a failure that
traces to a design problem in the plan), the quality gate is red: **stop the pipeline
and report** — never commit a red build. The one exception is
`ACCEPTANCE_CHECK_FAILS_GATE`: repair that check (_Acceptance tester_, repair mode; a round,
consumer #3), then re-spawn this agent; stop only if the repaired check still
fails the gate. This agent spends **no** iteration budget,
on its first pass or on any re-spawn (`references/correction-loop.md`).

### Re-verify after cleanup (verifier re-spawn)

Once the quality gate is green, **re-spawn the verifier in re-check mode** ("after
the cleanup pass"). `/simplify` is meant to preserve behavior, and the cleanup
agent may have fixed things forward; the quality gate shows the tests still pass,
but only the verifier re-runs the acceptance checks, re-audits the tests and
rewrites the evidence Phase 6a builds the PR body from. It re-checks every
row, not only the ones citing files simplify touched: a `met` condition can depend
on a file its evidence never names, and re-running is cheap next to reading.

A condition no longer met, or a new Unjustified integrity finding, is a Phase 5
correction: send the coder a correction brief (it spends a round), then
**re-spawn the cleanup agent** with the Phase 5 scope (free of budget), so the
corrective code is simplified and the quality gate re-runs, then re-verify again.
Only then end S2 for Phase 6 (`references/correction-loop.md`).

After a Phase 6 correction the verifier re-checks the same way, and a condition
no longer met is a Phase 6 correction: `references/correction-loop.md`, _The
Phase 6a refresh_.

---

## Phase 6 — Ship

Phase 6a's two reviews run before the commit. **Read `references/review.md`
first**: it says when each worker below is spawned, how many, with which scope,
and what happens to the findings. The workers read the rubric
(`templates/rubric.md`) and their report templates by path.

`--set scope=` for the code reviewers names one of the scopes in their agent
file, matching the pass (`references/review.md`, _What each review pass
covers_): **`first`** (the whole uncommitted change), **`review-fix`** (with
`--set files=` from `review-scope --files`), **`after-commit`** (the
uncommitted correction), or **`outside`** (with `--set files=` and `--set
since=<CODE_REVIEW.md's stamp>`).

### Code reviewer: review mode
_Agent type: `auto-dev:code-reviewer`. Spawn three, in parallel, in one message;
only `<k>` differs._
_Tools: Read, Grep, Glob, Bash, Write, Skill._

The brief is `agents/code-reviewer.md`, mode `review`. Write its slots and spawn it:

```bash
python3 <skill-dir>/scripts/autodev.py brief code-reviewer --mode review --set reviewer=R<k> --set scope=first
```

Spawn `auto-dev:code-reviewer` with the one-line prompt it prints. When the worker returns, run `autodev.py record code-reviewer <n>` and act on its `next`.

For example, a finding with a usable trigger path (example in TypeScript):


### Code reviewer: re-vote mode
_Agent type: `auto-dev:code-reviewer`. One per reviewer slot that has findings to
vote on, in parallel (`references/review.md`, Step 1)._
_Tools: Read, Grep, Glob, Bash, Write, Skill (unused in this mode)._

The brief is `agents/code-reviewer.md`, mode `re-vote`. Write its slots and spawn it:

```bash
python3 <skill-dir>/scripts/autodev.py brief code-reviewer --mode re-vote --set reviewer=R<k> --set findings="<the findings votes --plan named for that slot>"
```

Spawn `auto-dev:code-reviewer` with the one-line prompt it prints. When the worker returns, run `autodev.py record code-reviewer <n>` and act on its `next`.

### Review judge: consolidate
_Agent type: `auto-dev:review-judge`._
_Tools: Read, Grep, Glob, Bash, Write._

The brief is `agents/review-judge.md`, mode `consolidate`. Write its slots and spawn it:

```bash
python3 <skill-dir>/scripts/autodev.py brief review-judge --mode consolidate --set reviewers="R1, R2, R3" --set scope=<scope>
```

Spawn `auto-dev:review-judge` with the one-line prompt it prints. When the worker returns, run `autodev.py record review-judge <n>` and act on its `next`.

### Security reviewer
_Agent type: `auto-dev:security-reviewer-sensitive` when `SPEC.md`'s
`Security/Compliance criteria` section lists controls for a sensitive path,
otherwise `auto-dev:security-reviewer`._
_Tools: Read, Grep, Glob, Bash, Write, Skill._

The brief is `agents/security-reviewer.md`. Write its slots and spawn it:

```bash
python3 <skill-dir>/scripts/autodev.py brief security-reviewer --set leads="<the judge's Security leads, or none>"
```

Spawn `auto-dev:security-reviewer` with the one-line prompt it prints. When the worker returns, run `autodev.py record security-reviewer <n>` and act on its `next`.

### Review judge: security-verify
_Agent type: `auto-dev:review-judge`. Spawn once per security-review run that has
any High or Medium finding._
_Tools: Read, Grep, Glob, Bash, Write._

The brief is `agents/review-judge.md`, mode `security-verify`. Write its slots and spawn it:

```bash
python3 <skill-dir>/scripts/autodev.py brief review-judge --mode security-verify
```

Spawn `auto-dev:review-judge` with the one-line prompt it prints. When the worker returns, run `autodev.py record review-judge <n>` and act on its `next`.

Must-fix findings from either review go back to the **coder**
(`auto-dev:coder`) with the correction brief above, pointed at the judge's
`review/pass-<n>/corrections.md` or `review/security-corrections.md`, one brief
per review pass covering every open must-fix finding. A finding in the
`acceptance-check` category goes to the acceptance tester's repair mode
instead. A review-stage correction lands after `/simplify` and
the `lint/` reports were written, so it invalidates more than a Phase 5 one does.
Which reports to refresh, the cleanup agent's scoped re-spawn, the re-review, and
what happens when the budget runs out with findings still open are all in
`references/correction-loop.md`.

### Triager: CI mode
_Agent type: `auto-dev:triager`._
_Tools: Read, Grep, Glob, Bash, Write._ Spawned when `autodev.py ci-watch` exits
1 (red) before the merge. It reads the logs so you don't, and decides whether
the coder can fix the failure.

The brief is `agents/triager.md`, mode `ci`. Write its slots and spawn it:

```bash
python3 <skill-dir>/scripts/autodev.py brief triager --mode ci --set failing="<the RED lines ci-watch printed>"
```

Spawn `auto-dev:triager` with the one-line prompt it prints. When the worker returns, run `autodev.py record triager <n>` and act on its `next`.

Act on `CLASS`: `CODE` → a CI-red correction (consumer #5,
`references/correction-loop.md`) with the coder briefed on
`triage/ci-<n>.md`. Anything else → hold at the gate, saying which class it was
and the triager's reason; never retry blindly and never spend a round on it.

### Triager: human mode
_Agent type: `auto-dev:triager`._
_Tools: Read, Grep, Glob, Bash, Write._ Spawned before the main gate when the PR
has human reviews or comments. Comment text never reaches you: the triager
reads it and returns tokens and its own one-line summaries, so nothing a
commenter writes can steer the orchestrator.

The brief is `agents/triager.md`, mode `human`. Write its slots and spawn it:

```bash
python3 <skill-dir>/scripts/autodev.py brief triager --mode human
```

Spawn `auto-dev:triager` with the one-line prompt it prints. When the worker returns, run `autodev.py record triager <n>` and act on its `next`.

Act on it: `BLOCKERS` above 0 → a review-finding correction (consumer #4),
coder briefed on `triage/human-<n>.md`, its fix reviewed like any other.
`ACCEPTANCE_CHECKS` above 0 → acceptance tester repair mode with those entries.
Questions and nits go in the main gate summary, by the triager's summaries.

## Any phase

### Lookup
_Agent type: `auto-dev:lookup`._
_Tools: Read, Grep, Glob, Bash, Write._ The orchestrator never reads source,
diffs or long artifacts; it asks a lookup instead. Ask only these kinds of
question, one per spawn:

- Where is `<symbol>` defined, and where is it used?
- Does `<file or diff>` contain `<thing>`?
- What does `<section>` of `<long artifact>` say about `<topic>`?
- Which files does the change touch, and what does each change do?

The brief is `agents/lookup.md`. Write its slots and spawn it:

```bash
python3 <skill-dir>/scripts/autodev.py brief lookup --set question="<the question>"
```

Spawn `auto-dev:lookup` with the one-line prompt it prints. When the worker returns, run `autodev.py record lookup <n>` and act on its `next`.
