---
name: auto-dev
description: >-
  Autonomously carries one coding task from ticket, idea or spec to a finished,
  reviewed pull request, running a plan → build → verify → ship pipeline with
  subagents and human gates. Use when the user wants a whole feature or fix built
  AND shipped hands-off in one pass: "do it autonomously", "by yourself",
  "raise/open the PR", "take it all the way", "from ticket/idea/spec to PR", "run
  the whole dev cycle", "make the calls on anything ambiguous", "don't make me
  babysit each step", "pick up JIRA-1234 and ship it", or an explicit "auto-dev
  …". Prefer it over guided feature-development help when the user wants the work
  run hands-off. Do NOT use for a single slice of that work: fixing one
  test/lint/type error, critiquing a plan, explaining code, or answering a
  question. Also use to RESUME a run in flight — "auto-dev continue", "pick up
  where the plan session left off" — since the pipeline stops between its plan,
  build and ship sessions.
---

# auto-dev

Drive a single task through the entire development lifecycle — from a ticket to a
merged pull request — using purpose-built **workers** (subagents, one per
delegated job) and handing structured artifacts between them through
`.auto-dev/`. You (the main agent) are
the **orchestrator**: you own the pipeline, hold the spec, run the human gates,
and never write implementation code yourself. Not every phase delegates: Phase 1
and the Phase 5 acceptance check are yours.

This skill is **stack-agnostic**. A **stack profile** (`profiles/*.md`, schema in
`references/profiles.md`) supplies the setup and quality-gate commands. Phase 1
detects the stack, loads the matching profile (else `profiles/default.md`), merges in
runtime discovery, and honors a repo-local `.auto-dev.yml` override.

External integrations are **optional and auto-detected**: Jira (status
transitions only), a CI provider (GitHub Actions / CircleCI / GitLab), and a
staging branch. Each is used when present and skipped cleanly when not. Details in
`references/gates-and-jira.md`.

## Reference files (read on demand)

Keep this spine in context; open a reference only when you reach the phase that
needs it. Bundled paths (`references/`, `profiles/`, `scripts/`) are relative to
`<skill-dir>` (this skill's base directory, named when it loads), never to the repo
or worktree you are in — open or run each by its absolute path.

| File | Read when | Holds |
| ---- | --------- | ----- |
| `references/phase-1-setup.md` | S1, before Phase 1 | the step-by-step setup procedure and its exact commands |
| `references/profiles.md` | S1, Phase 1 step 2 | profile schema, detection precedence, monorepo rules, `.auto-dev.yml` override |
| `profiles/<stack>.md` / `profiles/default.md` | S1, Phase 1 step 2 | the matched stack profile (e.g. `profiles/elixir.md`), or the fallback's discovery checklist |
| `scripts/validate-config.py` | S1, Phase 1 step 2, when `.auto-dev.yml` exists | run (not read) to validate the override: `python3 <skill-dir>/scripts/validate-config.py <repo>/.auto-dev.yml` — `<skill-dir>` is this skill's directory, not the target repo; needs Python 3.9+ and PyYAML (without PyYAML it exits `2`, not a pass); exit codes in `references/profiles.md` |
| `scripts/resume-point.py` | Phase 1's resume check; any re-entry | run (not read) to find the resume point: `python3 <skill-dir>/scripts/resume-point.py <tree>/.auto-dev --task "<ticket or task>"` prints the first phase not done, its session and the budget; exit `0` found, `3` nothing to resume, `1` missing/malformed/mismatch, `2` couldn't run, `127` no python3 (by hand); handling in `references/artifacts.md`, _Resuming an interrupted run_ |
| `scripts/exclude-artifacts.py` | S1, Phase 1 step 6 | run (not read) to make `.auto-dev/` self-excluding and verify it: `python3 <skill-dir>/scripts/exclude-artifacts.py <worktree>`; exit `0` verified, `1` git still sees paths, `2` couldn't run, `127` no python3 (by hand); handling in `references/phase-1-setup.md`, step 6 |
| `scripts/check-staged.py` | S3, before every Phase 6a commit | run (not read), read-only, to check the staged set: `python3 <skill-dir>/scripts/check-staged.py <worktree> --expect <path> …`; exit `0` clean, `1` `.auto-dev/` staged, set mismatch or changes left unstaged, `2` couldn't run, `127` no python3 (by hand); handling in `references/phase-6-ship.md`, step 2 |
| `references/artifacts.md` | each session's start (its checklist); writing or resuming from any `.auto-dev/` file | layout, `WORK_LOG.md` ledger, resume procedure, session checklists, `HANDOFF.md`, every artifact's contract, template and strictness, the PR body, the final report |
| `references/subagent-prompts.md` | before spawning any worker (Phases 2–6) | each worker's brief and tools, the scope decision, the acceptance check |
| `references/gates-and-jira.md` | before any gate or pause, Jira transition, or CI watch | gate scripts, Jira transition mapping, CI monitoring policy (timeouts, on-red) |
| `references/correction-loop.md` | on an unmet condition, a PR blocker, or red CI | the one correction loop, what each correction invalidates, the iteration budget |
| `references/phase-6-ship.md` | S3, before Phase 6 | the exact commit, push, staging-merge and main-merge sequences and their failure handling |

## Pipeline at a glance

```
Phase 1  Setup   → detect repo + stack, resolve ticket, worktree + branch, prep .auto-dev/
Phase 2  Define  → research + the testable contract (SPEC.md); SCOPE CALL (trivial / standard / oversized)
Phase 3  Plan    → planner writes IMPLEMENTATION.md; plan reviewer critiques         [optional gate]
Phase 4  Build   → coder implements + tests, given only the plan
Phase 5  Verify  → acceptance vs. the withheld spec → simplify → quality gate to green
Phase 6  Ship    → [GATE] commit + PR + adversarial review + CI → [GATE] staging → [GATE] main + Jira
```

Run phases in order; each depends on the previous. Track them in
`.auto-dev/WORK_LOG.md` — the single source of truth, across a multi-PR run too,
and the resume point — and mirror it in TodoWrite so progress stays visible: at
each session's start, copy that session's checklist (`references/artifacts.md`,
_Session checklists_) and tick items off as you go.

## Session boundaries — the pipeline spans THREE sessions, not one

This pipeline **must not** run end-to-end in one context. It is cut into three
sessions with a written handoff between each. Nothing carries across a boundary
except `.auto-dev/` on disk and the git tree.

| Session        | Phases                   | Orchestrator model | Ends by                                                   |
| -------------- | ------------------------ | ------------------ | --------------------------------------------------------- |
| **S1 — Plan**  | 1–3 (2–3 for a sub-task) | `opus` · high      | Writing `.auto-dev/HANDOFF.md` (Build brief) and STOPPING |
| **S2 — Build** | 4–5                      | `opus` · high      | Writing `.auto-dev/HANDOFF.md` (Ship brief) and STOPPING  |
| **S3 — Ship**  | 6                        | `sonnet` · medium  | Final report                                              |

The user picks the orchestrator's model when starting each session. S1 (the scope
call) and S2 (the acceptance check) are no place to economize; S3 is scripted
git/gh/CI work between human gates, so `sonnet` is enough.

**Which session is this?** A fresh run is S1. A resumed run is whichever session
holds the first phase not `done` (_Phase 1 — Setup_ says how to tell).

At the end of S1 and S2, do exactly this and then stop:

1. Update `WORK_LOG.md` (phase statuses, remaining iteration budget, the scope
   call, every gate decision).
2. Overwrite `.auto-dev/HANDOFF.md` with the next session's brief — **under 60
   lines**: what is done, the exact next phase, the 3–8 file paths that matter,
   open assumptions, and the one command to re-enter (`cd <worktree>`). Contract
   in `references/artifacts.md`.
3. Tell the user: _"Plan session complete. Artifacts in `.auto-dev/`. Start a
   fresh session on `opus` at high effort and say `auto-dev continue` to run the
   build."_ At the end of S2, name `sonnet` at medium effort for the ship session
   instead. Then **stop — do not begin the next phase.**

On entry to S2 or S3, read `WORK_LOG.md`, `HANDOFF.md` and `profile.md` — and
nothing else by default. `profile.md` is always in that set: it holds the resolved
`gate` commands S2 needs and the CI provider and Jira mapping S3 needs, and
re-deriving any of it is the mistake (`references/artifacts.md`, _Resuming an
interrupted run_, step 2).

Beyond those three, read an artifact when a phase **of yours** needs it, and not
otherwise:

- **S2** — `SPEC.md`, for the Phase 5 acceptance check.
- **S3** — `SPEC.md` and `SPEC_EVAL.md` for the PR body's condition checklist
  (Phase 6a quotes the spec's wording and takes each tick from the eval), and
  `lint/*.md` for the quality-gate results the PR gate summary reports.

`IMPLEMENTATION.md` is the coder's and never yours. For anything else — including
any question _about_ one of the files above that isn't the phase that needs it —
spawn a worker that reads it and returns an answer.

On a multi-PR run, each sub-task gets its **own** set of three sessions — S1
covering phases 2–3, since Phase 1 ran once for the whole run and never repeats.
Never carry two sub-tasks in one context.

## Why two documents

**`SPEC.md`** answers _did we build the right thing?_ (the testable contract, no
design); **`IMPLEMENTATION.md`** answers _did we build it the way we decided?_ (the
technical how). They fail independently, so they stay separate. **The coder builds
from the plan, never the spec**, which keeps the Phase 5 acceptance check
independent. The full rationale is in `references/artifacts.md`, _Why two
documents_.

## Task-orchestration layer (scope call, decompose & track)

Phase 2 returns a three-way **scope call**, and the pipeline adapts to it:

- **TRIVIAL** — one subsystem, one behavior, no new abstraction or interface, no
  migration or config change, and an existing test file covers it. Skip the Define
  review and the Phase 3 agents; you write a short `IMPLEMENTATION.md` yourself
  (files to touch + the test that proves it). Phases 4–6 run normally.
- **STANDARD** — fits one PR but is neither TRIVIAL nor OVERSIZED: the full path,
  Phase 3 onward runs in full. Record `Mode: single-PR`.
- **OVERSIZED** — multiple independent deliverables, several subsystems, or a large
  file count. Do **not** cram it onto one branch: propose ordered sub-tasks, write
  them to `WORK_LOG.md`, and **alert the user**. On approval, run Phases 2–6 **per
  sub-task** in dependency order, each with its own branch, worktree (created when
  it starts), PR, scope call and **iteration budget**, its artifacts kept in the
  control worktree under `.auto-dev/tasks/<id>/`. A sub-task may **not** be
  OVERSIZED: stop and offer to re-cut the parent breakdown. Before acting on this
  call, read `references/subagent-prompts.md`, _Scope decision_.

> **The scope call thins the planning head, never the verification tail.**
> Phase 5 (acceptance + simplify + quality gate) and Phase 6 (adversarial review +
> CI + human gates) run identically at every scope.

## Human gates

This skill runs the planning and build unattended. Four gates pause it for
explicit approval (via `AskUserQuestion`):

- **Post-plan gate (Phase 3)** — after `IMPLEMENTATION.md`, before any code is
  written. **OFF by default**; `references/gates-and-jira.md` states when to enable
  it for a run.
- **PR gate (Phase 6a)** — before opening the PR.
- **Staging gate (Phase 6b)** — before the direct merge to staging.
- **Main gate (Phase 6c)** — before merging the PR to main.

A bare "gate" in this skill always means one of these four. The Phase 5 checks
are the **quality gate**, run from the profile's `gate` commands.

Three further pauses are **conditional** — not gates, and they fire only when
their situation arises: the **decomposition approval** (Phase 2, OVERSIZED only —
never start a multi-PR run unapproved), the **Jira In Progress confirmation**
(Phase 1, only with a ticket), and the **worktree cleanup offer** (Phase 6c).
Everything else runs without check-ins.

Each gate's summary, option set, **what each option does**, and the Jira transition
it carries are in `references/gates-and-jira.md`. Record every gate decision, and
its reason, in `WORK_LOG.md`.

## Corrections and the iteration budget

An unmet spec condition, a PR-review blocker, and a red CI check are **one
correction loop entered at three points**. All of them draw on **a single budget
of revise rounds per task** (default **4**, overridable via `.auto-dev.yml`) rather
than a cap per loop; on a multi-PR run each sub-task gets its own. Each re-spawn or
re-run for correction spends a round, decremented before dispatch and tracked in
`WORK_LOG.md`, except the cleanup agent, which never spends one: it runs once
after the Phase 5 acceptance loop settles, again after any later Phase 5
correction, and after every Phase 6a correction; at zero, **stop and report** instead of
looping. **When any of the three fires, read `references/correction-loop.md`** —
the loop's steps, what each correction invalidates, and the full budget
accounting. Do not restate its rules elsewhere.

## Context budget (separate from the iteration budget)

This one counts _context_, the harder limit. On top of this skill's baseline,
context grows roughly **1k tokens per assistant turn**, so turn 75 lands around
120k. As a rough guide from past runs that _didn't_ stop, cost per call climbed
from **~87k tokens over turns 1–50 to ~212k over 101–200 and ~304k over 201–400.**

- **Ceiling: 150k tokens per session.** On a large-context model, auto-compaction
  won't fire anywhere near this ceiling to rescue you — it is on you to stop.
- **Always checkpoint at ~120k, which is roughly assistant turn 75** — turn 75
  is the line, not turn 400, and being near a session boundary is no exception.
  Stop whatever phase you are in, finish the current tool call, write
  `WORK_LOG.md` + `HANDOFF.md` per _Session boundaries_ above, and tell the user
  to restart. A mid-phase checkpoint is always cheaper than finishing the phase
  in a bloated context.
- **Never hold an artifact you can delegate.** If you are about to `Read` a file
  in `.auto-dev/` longer than ~200 lines, stop and spawn a worker that reads it
  and returns a verdict. The artifacts exist so that you _don't_ have to hold
  them. `SPEC.md` and `SPEC_EVAL.md` are exempt at any length — the acceptance
  check is yours by design, and delegating it would delegate away the one check
  no worker can run.

## Tool permissions & models

Every worker has its own agent type, shipped in this plugin's `agents/` directory.
Each type fixes the worker's tools, model and effort, so spawn **exactly the type
named** and nothing else. A generic type (`claude` / `general-purpose`) runs on
your model and effort, which silently undoes the table below.
`feature-dev:code-architect` and `feature-dev:code-reviewer` are worse: **no
Write/Edit/Bash**, so an artifact writer spawned with one silently fails.

| Worker                                         | Agent type                       | Model · effort    |
| ---------------------------------------------- | -------------------------------- | ----------------- |
| Define agent (Phase 2)                         | `auto-dev:define`                | `opus` · high     |
| Define reviewer (Phase 2)                      | `auto-dev:define-reviewer`       | `opus` · high     |
| Planner (Phase 3)                              | `auto-dev:planner`               | `opus` · xhigh    |
| Plan reviewer (Phase 3)                        | `auto-dev:plan-reviewer`         | `opus` · high     |
| Coder: STANDARD build, every correction        | `auto-dev:coder`                 | `opus` · high     |
| Coder: TRIVIAL first build                     | `auto-dev:coder-trivial`         | `sonnet` · medium |
| Cleanup agent (Phase 5, re-spawned on fixes)   | `auto-dev:cleanup`               | `sonnet` · medium |
| PR reviewer (Phase 6)                          | `auto-dev:pr-reviewer`           | `opus` · xhigh    |
| PR reviewer, sensitive paths (Phase 6)         | `auto-dev:pr-reviewer-sensitive` | `fable` · high    |
| Your read-and-answer lookups                   | `auto-dev:lookup`                | `sonnet` · low    |

**Resolving a type.** The table and the rules below write each type as
`auto-dev:<x>`. To spawn worker `<x>`, use the first of these that is in the
available agents list: `auto-dev:auto-dev-<x>` (plugin install), `auto-dev:<x>`,
or `auto-dev-<x>` (user-level install, `agents/` symlinked into `~/.claude/agents/`).
If none exists, stop and tell the user to install the plugin or symlink `agents/`
into `~/.claude/agents/`. Never fall back to `general-purpose`.

**Models.** Judgment stays on `opus`; only work a later check verifies moves down
to `sonnet` (why: `references/subagent-prompts.md`, _Models_). Two routing rules:

- **Corrections always go to `auto-dev:coder`**, TRIVIAL runs included. A TRIVIAL
  build that failed acceptance was not as trivial as the scope call said.
- **Use `auto-dev:pr-reviewer-sensitive`** when `SPEC.md`'s
  `Security/Compliance criteria` section lists controls for a sensitive path, and
  `auto-dev:pr-reviewer` otherwise.

**Never pass the Agent tool's `model` parameter** when spawning a worker: it
overrides the type's model. Change a worker's model or effort in its
`agents/<name>.md` frontmatter, and change the table above with it.

**Tools.** Each type's `tools:` frontmatter fixes its tools. The full per-worker
list, yours included, is in `references/subagent-prompts.md`, _Tools per worker_;
the frontmatter, that list, and each brief's `_Tools:_` line state the same thing,
so change them together. Reviewers are read-only w.r.t. source.

Per-phase isolation: hand each worker **two** absolute paths — the worktree it
works in, and the `<artifact-dir>` it reads and writes (the two are the same tree
on a single-PR run and different trees on a multi-PR one; see
`references/artifacts.md`) — plus `profile.md` and only the inputs its phase
needs. The coder gets the **plan only, never the spec** (see _Why two documents_).

**Avoid giving a worker a >5-minute blocking command** — a full suite, a poll
loop, a long build; keep such commands in your own context where you can. The
**cleanup agent's quality gate is the deliberate exception**. Every brief
says: **spill large output to `$TMPDIR` and return a digest, never a corpus.** Why
and how: `references/subagent-prompts.md`, _Conventions for every brief_.

## Reading discipline (orchestrator)

Your average `Read` costs ~5.5k tokens and stays in context for the rest of the
session. Before every one, ask whether a worker should read it instead.

- **Never `Read` a source file to understand it.** Spawn `auto-dev:lookup` and ask
  for the conclusion. You are the orchestrator; you do not need the code.
- **Never `Read` a whole file when you need one fact.** `grep -n` for it, then
  read the surrounding lines — or better, have the worker answer.
- **Full `git diff` is for workers, with one exception.** Freely run
  `git diff --stat` and `git diff --name-only`. The Phase 5 acceptance check _is_
  yours and does require reading the whole working-tree diff — that read is the
  point of the phase. Everywhere else (scoping, sanity checks, "what changed
  again?") delegate to a worker that returns a verdict.
- **Each reference file, at most once per session** — `subagent-prompts.md` alone
  is ~5k tokens, and S1/S2/S3 each need only their own phases' references.
- **In Elixir repos use `dexter lookup` / `dexter references`, not grep**, for any
  module or function symbol. No `dexter` on PATH → `grep -n`, noted in `WORK_LOG.md`.

---

## Phase 1 — Setup

Deterministic, run by the orchestrator.

**First: is this a resumed run?** You are standing in the main repo, which has no
`.auto-dev/` — the control worktree is a sibling directory. Scan `git worktree list`
for one holding a `.auto-dev/WORK_LOG.md` whose header matches this task — run
`scripts/resume-point.py <tree>/.auto-dev --task "<ticket or task>"` on each. If one
exists, do not re-run Phase 1: read the ledger and continue from it. Full detection
procedure and exit handling: `references/artifacts.md`, _Resuming an interrupted run_.

**Fresh run: before starting step 1, read `references/phase-1-setup.md`** — each
step's full procedure and exact commands. The steps, in order:

1. **Detect the repo & branches** (`base`, optional `staging`, `prefix`). **Check
   `gh` first** — missing, unauthenticated, or a non-GitHub `origin` is a
   **stop-and-report now**. No staging branch → mark the 6b gate `n/a`.
2. **Detect the stack & load the profile** (`references/profiles.md`), merge in
   discovery, apply `.auto-dev.yml` (validated by running `scripts/validate-config.py`),
   and record the CI provider.
3. **Resolve the ticket** (Jira via the Atlassian MCP, else the free-form task).
4. **Read the repo's binding rules** and resolve the security directives into
   `profile.md`.
5. **Create the isolated worktree** on its own branch — **never the default
   branch** — from a freshly fetched `origin/<base>`; seed `worktree_files`; run
   `setup`. The slug is yours alone.
6. **Prep `.auto-dev/` self-excluding** with a `.auto-dev/.gitignore` of `*` —
   never `.git/info/exclude` — and confirm git sees nothing under it: run
   `scripts/exclude-artifacts.py <worktree>`, which does both.
7. **Write `.auto-dev/profile.md`** and initialize `.auto-dev/WORK_LOG.md`.
8. **Jira → In Progress** (if a ticket exists), confirmed with the user.

All later phases run **inside the worktree directory**.

## Phase 2 — Define (the testable contract + scope call)

Spawn **one** Define agent (brief in `references/subagent-prompts.md`) that, in a
single pass: researches the ticket against the codebase, states the acceptance
conditions **as a testable contract**, and returns a **scope call**. It writes one
file, `.auto-dev/SPEC.md` — `Context`, the testable conditions, `Assumptions`, and
`Security/Compliance criteria` for sensitive paths (`references/artifacts.md`).

1. **Read the scope call first** — it decides whether step 2 runs at all, and
   which path Phase 3 takes (per the task-orchestration layer above).
2. **Define reviewer** (read-only) → critique. Apply fixes yourself; re-review only
   if it found blockers, until a review returns none. Each re-review spends a round
   of the shared iteration budget. Runs on STANDARD;
   **skipped on TRIVIAL** (nothing the plan won't restate) **and OVERSIZED** (each
   sub-task gets its own reviewed spec).

Hold `SPEC.md` — you withhold it from the coder and use it for Phase 5.

## Phase 3 — Plan

**Skipped as an agent phase when the scope call is TRIVIAL** — you write a short
`IMPLEMENTATION.md` yourself instead (files to touch + the test that proves it).

1. **Planner** → `.auto-dev/IMPLEMENTATION.md` — the self-contained technical
   plan; every spec condition maps to a step and a test. Reads `SPEC.md`.
2. **Plan reviewer** (read-only) → critique; apply fixes; re-review if it found
   blockers, until a review returns none. Each re-review spends a round of the
   shared budget. A spec condition with no plan step is cheapest to
   catch here, before any code exists.
3. **Optional post-plan gate** — if enabled for this run (see _Human gates_), pause
   to approve `SPEC.md` + `IMPLEMENTATION.md` before any code is written. It is
   **independent of the scope call**: it fires on TRIVIAL too, on your own plan.

## Phase 4 — Build

Spawn the **coder (TDD)** with **only `IMPLEMENTATION.md`, never the spec**.
It implements code and tests, working through the plan's build sequence in order
and running the relevant tests as it goes.

Its return reports **plan deviations**. Read them as **information going into
Phase 5**, not defects: the plan is a route, and the acceptance check decides
whether the destination was reached.

## Phase 5 — Verify (acceptance → simplify → quality gate)

Three steps, in this order, never reordered. Simplify follows the Phase 5 correction
loop so corrective code gets simplified too. It only _intends_ to preserve
behavior; step 3's quality gate is what checks it.

1. **Acceptance (you, the orchestrator).** Holding `SPEC.md` (which the coder never
   saw), verify the build against every condition — read the diff and the tests.
   The coder does not commit, so read the **working tree**, not a commit range:
   `git ls-files -z --others --exclude-standard | xargs -0 git add -N --` (new
   files only; never `git add -N .`, which also stages deletions), then
   `git diff origin/<base>` (never `...HEAD`, which is empty before the commit).
   **Before this step, read `references/subagent-prompts.md`, _Acceptance
   check_** — why each half matters, and the correction brief.

   Write `.auto-dev/SPEC_EVAL.md` (met / partial / unmet per condition, with
   evidence; template in `references/artifacts.md`). For unmet or partial
   conditions, send the coder back with a **specific** correction brief (concrete
   required behavior, never the spec verbatim), and re-check, until every condition
   is met. This loop spends the shared budget; past it, stop-and-report the unmet
   conditions. The cleanup agent is spawned after this loop settles, not per
   acceptance correction. Full protocol: `references/correction-loop.md`.

2. **Simplify.** Spawn the cleanup agent to run **`/simplify`** over the branch diff.
   Behavior-preserving only.
3. **Quality gate.** The same agent then runs the profile's `gate` commands (from
   `profile.md`) in order, fixing what they surface, until every command is green.
   Each check writes `.auto-dev/lint/<CHECK>.md`. The cleanup agent spends **no**
   budget, here or when re-spawned after a later correction, and makes at most 3
   fix attempts per failing check per spawn. If the quality gate cannot be made
   green, **stop and report** — never ship a red build.

   Once it is green, **re-resolve `SPEC_EVAL.md`'s `file:line` evidence** for the
   conditions whose cited files simplify touched (`references/subagent-prompts.md`,
   _Re-resolve the acceptance evidence_). A condition it finds no longer met is a
   Phase 5 correction (one round); re-spawn the cleanup agent after it, free, and
   re-resolve again before Phase 6.

## Phase 6 — Ship **[three human gates]**

**Before starting Phase 6, read `references/phase-6-ship.md`** — the exact commit,
push, staging-merge and main-merge sequences and what to do when each fails — and
`references/gates-and-jira.md` for the gate scripts, Jira transitions and CI policy.

### 6a — PR **[gate]**

1. **Gate:** pause for approval to open the PR.
2. **Commit** — stage source paths **explicitly** (never `git add -A`/`.`), confirm
   nothing under `.auto-dev/` is staged (`scripts/check-staged.py --expect` those
   paths), then commit with a conventional message.
3. **Push** the branch — **never `--force`** — and open **one** PR (never a
   duplicate). Pick the route: a skill from your available-skills list that clearly
   fits and meets the requirements, else `gh pr create`; then verify the result. The
   body carries the **acceptance checklist** (ticked from `SPEC_EVAL.md`) and the
   **quality-gate results**, and the PR meets the base-branch, template, Jira-link,
   draft-flag and attribution requirements (`references/phase-6-ship.md`; `references/artifacts.md`).
4. **PR reviewer** (adversarial) → `.auto-dev/PR_REVIEW.md`, briefed to _find_
   problems, not rubber-stamp.
5. **CI monitoring** with a bounded timeout. Red pre-merge → the correction loop
   (`references/correction-loop.md`). "No checks reported" is not red, and CI
   `none` skips the watch (`references/gates-and-jira.md`).
6. **Jira → In Review.**

### 6b — Staging **[gate]** (skip if no staging branch)

Pause for approval, then **directly merge** the branch into `staging` (no PR — per
project convention) and monitor CI on staging. Never resolve conflicts on staging
or force the push unasked.

### 6c — Main **[gate]**

1. **Read what humans said** and whether the PR is still a draft (mark it ready
   before the gate). A human blocker goes through the correction loop, never
   merged over.
2. **Gate:** pause for approval.
3. **Merge to main** via `gh pr merge` with an explicit method — never a local
   push to main, **never `--admin`**. If the merge is refused, **report that the PR
   is unmergeable**, name the blocking requirement, and stop with the PR open. Then
   confirm `gh pr view <pr> --json state` is `MERGED`; if it is only queued or set
   to auto-merge, report that and stop, without moving Jira.
4. Monitor CI on main, transition **Jira → Done**, and offer to remove the worktree
   (confirmed, not automatic; per sub-task on a multi-PR run, and never the control
   worktree before the final report — on a single-PR run that is this worktree, so
   offer it after the report).

---

## Final report

Summarize: branch/worktree path, PR link(s), what was built, the scope call,
assumptions made, final quality-gate status, Jira transitions performed, remaining
iteration budget, and anything left unresolved. In a multi-PR run, report per
sub-task from `WORK_LOG.md`. Be honest about skipped steps and unmet conditions —
never report success you didn't verify. Default shape: `references/artifacts.md`.

## Bounds and guardrails

- **One iteration budget per task** (default 4 revise rounds), shared by the
  review re-reviews and the correction loop — and per _sub-task_ on a multi-PR run. Past it, report rather than loop
  (`references/correction-loop.md`).
- **Stop-and-report conditions:** `gh` is missing, unauthenticated, or `origin`
  isn't GitHub (caught in Phase 1, before any work); the worktree can't be created,
  or a seeded `worktree_files` file isn't gitignored;
  the resolved quality gate has **no test command** (Phase 1 — an empty quality gate
  passes Phase 5 by having nothing to check); a `setup` command is missing (exit
  `127` — the toolchain isn't installed); the task is self-contradictory or impossible
  as specified; the quality gate can't be made green; the build edited source
  inside a submodule (PR gate); spec conditions remain unmet
  after the budget; `gh pr merge` refuses (or only queues) the merge; a sub-task's scope call comes
  back OVERSIZED; a human gate or merge is declined by the user. Leave the work in place and
  explain.
- **Never weaken security to finish** — no disabled TLS/cert/signature checks, no
  exposed or hardcoded secrets, no real/sensitive data or PII in tests/fixtures.
  Obey the repo's rules and the security directives resolved in Phase 1 (recorded in
  `profile.md`). These override "finish the task".
- **Never commit `.auto-dev/`.** Make it self-excluding in Phase 1; stage
  explicitly in Phase 6; never `git add -A`/`.` (`references/artifacts.md`).
- **Promotion safety:** main only via `gh pr merge`; staging via direct merge only
  where the project uses that convention.
- **Per-job isolation:** a fresh worker per delegated job; hand off via
  `.auto-dev/` files + the git tree; give each worker only the inputs its phase
  needs; the coder never sees the spec.
