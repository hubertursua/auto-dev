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
and never write implementation code yourself. Phase 1 is yours; so is turning the
Phase 5 verifier's verdicts into correction briefs. You never judge the build
yourself: you hold the plan and every round's story, which is exactly the
context a judge must not have.

This skill is **stack-agnostic** and ships no stack profile. A **stack profile**
(schema in `references/profiles.md`) supplies the setup and quality-gate
commands. Phase 1 loads the repo's **saved profile** from the user's machine,
or has a worker research one and the user confirm it (and optionally save it,
for every later clone or worktree), then honors a repo-local `.auto-dev.yml`
override.

External integrations are **optional and auto-detected**: Jira (status
transitions only), a CI provider (GitHub Actions / CircleCI / GitLab), and a
staging branch. Each is used when present and skipped cleanly when not. Details in
`references/gates-and-jira.md`.

## Reference files (read on demand)

Keep this spine in context; open a reference only when you reach the phase that
needs it. Bundled paths (`references/`, `scripts/`) are relative to
`<skill-dir>` (this skill's base directory, named when it loads), never to the repo
or worktree you are in — open or run each by its absolute path.

| File | Read when | Holds |
| ---- | --------- | ----- |
| `references/phase-1-setup.md` | S1, before Phase 1 | the step-by-step setup procedure and its exact commands |
| `references/profiles.md` | S1, Phase 1 step 2 | resolving the profile (saved, or researched and confirmed), its schema, where saved profiles live, the permissions guidance for the user, monorepo rules, `.auto-dev.yml` override |
| `scripts/profile-path.py` | S1, Phase 1 step 2 | run (not read): `python3 <skill-dir>/scripts/profile-path.py <repo>` names this repo's saved-profile path and whether it exists; exit codes in `references/profiles.md` |
| `scripts/validate-config.py` | S1, Phase 1 step 2, when `.auto-dev.yml` exists or a saved profile is loaded or written | run (not read): `python3 <skill-dir>/scripts/validate-config.py <repo>/.auto-dev.yml`, or `--profile <saved-profile>`; needs PyYAML (without it, exit `2` — not a pass); exit codes in `references/profiles.md` |
| `scripts/resume-point.py` | Phase 1's resume check; any re-entry | run (not read): `python3 <skill-dir>/scripts/resume-point.py <tree>/.auto-dev [--task "<ticket or task>"]` names the resume point (`--task` only when the user named a ticket or task: the task word for word, a few words may be left out; a `NEAR-MISS` means ask); exit codes in `references/artifacts.md`, _Resuming an interrupted run_ |
| `scripts/exclude-artifacts.py` | S1, Phase 1 step 6 | run (not read): `python3 <skill-dir>/scripts/exclude-artifacts.py <worktree>`; exit codes in `references/phase-1-setup.md`, step 6 |
| `scripts/check-tests.py` | run by the verifier (Phase 5), never by you | audits test changes against the base: deleted, skipped or weakened tests, assertion-free new ones, tampered acceptance checks; exit codes in its `--help` |
| `scripts/mutate.py` | run by the verifier (Phase 5), never by you | applies the verifier's mutants one at a time, runs the scoped tests, restores each file byte-for-byte; exit codes in its `--help` |
| `scripts/check-staged.py` | S3, before every Phase 6a commit | run (not read): `python3 <skill-dir>/scripts/check-staged.py <worktree> --expect <path> …`; exit codes in `references/phase-6-ship.md`, step 4 |
| `references/artifacts.md` | each session's start (its checklist); writing or resuming from any `.auto-dev/` file | layout, `WORK_LOG.md` ledger, resume procedure, session checklists, `HANDOFF.md`, every artifact's contract, template and strictness, the PR body, the final report |
| `references/subagent-prompts.md` | before spawning any worker (the profiler in Phase 1, then Phases 2–6) | each worker's brief and tools, the scope decision, acting on the verifier's verdicts |
| `references/gates-and-jira.md` | before any gate or pause, Jira transition, or CI watch | gate scripts, Jira transition mapping, CI monitoring policy (timeouts, on-red) |
| `references/correction-loop.md` | on an unmet condition, a must-fix review finding, a human blocker, or red CI | the one correction loop, what each correction invalidates, the iteration budget |
| `references/phase-6-ship.md` | S3, before Phase 6 | the exact commit, push, staging-merge and main-merge sequences and their failure handling |
| `references/review.md` | S3, before Phase 6a's reviews | the code review panel, the security review, the review loop, and **the rubric** that sorts must-fix findings from noise, with confidence levels |

## Pipeline at a glance

```
Phase 1  Setup   → detect repo, resolve the profile (saved, or researched + confirmed), ticket, worktree + branch, .auto-dev/
Phase 2  Define  → research + the testable contract (SPEC.md); SCOPE CALL (trivial / standard / oversized)
Phase 3  Plan    → planner writes IMPLEMENTATION.md; plan reviewer critiques;
                   acceptance tester writes + seals held-out checks from the spec  [optional gate]
Phase 4  Build   → coder implements + tests, given only the plan
Phase 5  Verify  → verifier RUNS the held-out checks vs. the withheld spec → simplify
                   → quality gate to green → verifier re-checks
Phase 6  Ship    → code review panel → security review → [GATE] commit + PR + CI → [GATE] staging → [GATE] main + Jira
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

The user picks the orchestrator's model per session: S1 (the scope call) and S2
(settling `BLOCKED` steps and translating verdicts into correction briefs) need
`opus`; S3 is scripted git/gh/CI work, so `sonnet`
is enough. **Which session is this?** A fresh run is S1; a resumed run is the
session holding the first phase not `done` (_Phase 1 — Setup_ says how to tell).

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

On entry to S2 or S3, read `WORK_LOG.md`, `HANDOFF.md` and `profile.md` (the
resolved `gate` commands, CI provider and Jira mapping — never re-derive them).
Beyond those, read an artifact only when a phase **of yours** needs it: in S2,
`SPEC.md` and `SPEC_EVAL.md` for the correction briefs; in S3, `SPEC.md`, `SPEC_EVAL.md`,
`lint/*.md`, `CODE_REVIEW.md` and `SECURITY_REVIEW.md` for the PR body and the PR
gate summary, and `review/pass-<n>/VOTES-R<k>.md` to apply the re-votes. `IMPLEMENTATION.md` is the
coder's, never yours. For anything else — including a question _about_ one of
those files outside the phase that needs it — spawn a worker that reads it and
returns an answer.

On a multi-PR run, each sub-task gets its **own** set of three sessions — S1
covering phases 2–3, since Phase 1 ran once for the whole run and never repeats.
Never carry two sub-tasks in one context.

## Why two documents

**`SPEC.md`** answers _did we build the right thing?_ (the testable contract, no
design); **`IMPLEMENTATION.md`** answers _did we build it the way we decided?_ (the
technical how). They fail independently, so they stay separate. **The coder builds
from the plan, never the spec.** Beside them sit the **held-out acceptance
checks**, written from the spec alone before any code exists and sealed out of
the worktree, never named in the coder's brief; the Phase 5 verifier runs them, never seeing the plan or the coder's
report. The full rationale is in `references/artifacts.md`, _Why two
documents_.

## Task-orchestration layer (scope call, decompose & track)

Phase 2 returns a three-way **scope call**, and the pipeline adapts to it:

- **TRIVIAL** — one subsystem, one behavior, no new abstraction or interface, no
  migration or config change, and an existing test file covers it. Skip the Define
  review, the planner and the plan reviewer; you write a short `IMPLEMENTATION.md`
  yourself (files to touch + the test that proves it). The acceptance tester still
  runs, and Phases 4–6 run normally.
- **STANDARD** — fits one PR but is neither TRIVIAL nor OVERSIZED: the full path,
  Phase 3 onward runs in full. Record `Mode: single-PR`.
- **OVERSIZED** — multiple independent deliverables, several subsystems, or a large
  file count. Do **not** cram it onto one branch: propose ordered sub-tasks, write
  them to `WORK_LOG.md`, and **alert the user**. On approval, run Phases 2–6 **per
  sub-task**, each with its own branch, worktree, PR, scope call and **iteration
  budget**. A sub-task may **not** be OVERSIZED.

What to record for each call, and the full multi-PR procedure (sub-task
worktrees, `<artifact-dir>` per sub-task, an OVERSIZED sub-task), are in
`references/subagent-prompts.md`, _Scope decision_ — read it before acting on an
OVERSIZED call.

> **The scope call thins the planning head, never the verification tail.**
> The acceptance tester (Phase 3), Phase 5 (verifier + simplify + quality gate +
> re-check) and Phase 6 (code review panel + security review + CI + human gates)
> run identically at every scope.

## Human gates

Planning and build run unattended. Four gates pause for explicit approval (via
`AskUserQuestion`): the **post-plan gate** (Phase 3, **OFF by default**), the
**PR gate** (6a), the **staging gate** (6b) and the **main gate** (6c). A bare
"gate" always means one of these four; the Phase 5 checks are the **quality
gate**, run from the profile's `gate` commands.

Four **conditional** pauses fire only when their situation arises: the
**profile confirmation** (Phase 1, only when the profile was researched), the
**decomposition approval** (OVERSIZED only — never start a multi-PR run
unapproved), the **Jira In Progress confirmation** (only with a ticket), and the
**worktree cleanup offer** (6c). Everything else runs without check-ins.

Each gate's summary, options, **what each option does**, its Jira transition, and
when to enable the post-plan gate are in `references/gates-and-jira.md`. Record
every gate decision, and its reason, in `WORK_LOG.md`.

## Corrections and the iteration budget

An unmet spec condition (or an unjustified test-integrity finding, or a
`BLOCKED` build step), a must-fix review finding (from the code review panel,
the security review, or a human reviewer on the PR), and a red CI check are **one
correction loop entered at three points**, drawing on **a single budget of
revise rounds per task** (default **4**, overridable via `.auto-dev.yml`; per
sub-task on a multi-PR run), shared with the Phase 2/3 re-reviews. Each re-review
or correction spends a round, **decremented before dispatch** and tracked in
`WORK_LOG.md`; cleanup-agent and verifier spawns never do. At zero, **stop and report** instead
of looping. **When any of the three fires, read `references/correction-loop.md`**
— the loop's steps, what each correction invalidates, and the budget accounting.
Do not restate its rules elsewhere.

## Context budget (separate from the iteration budget)

This one counts _context_, the harder limit. On top of this skill's baseline,
context grows roughly **1k tokens per assistant turn**, so turn 75 lands around
120k, and every turn makes each later call more expensive (past
runs that didn't stop averaged ~87k tokens per call over turns 1–50 and ~304k
over turns 201–400).

- **Ceiling: 150k tokens per session.** On a large-context model, auto-compaction
  won't fire anywhere near this ceiling to rescue you — it is on you to stop.
- **Always checkpoint at ~120k, roughly assistant turn 75**, even near a session
  boundary. Finish the current tool call, write `WORK_LOG.md` + `HANDOFF.md` per
  _Session boundaries_ above, and tell the user to restart. A mid-phase
  checkpoint is always cheaper than finishing the phase in a bloated context.
- **Never hold an artifact you can delegate.** If you are about to `Read` a file
  in `.auto-dev/` longer than ~200 lines, stop and spawn a worker that reads it
  and returns a verdict. The artifacts exist so that you _don't_ have to hold
  them. `SPEC.md` and `SPEC_EVAL.md` are exempt at any length — the correction
  briefs are yours by design, and they must be written from the contract and the
  verdicts, not from a worker's summary of them.

## Tool permissions & models

Every worker has its own agent type in this plugin's `agents/` directory, which
fixes its tools, model and effort. Spawn **exactly the type named**: a generic
type (`claude` / `general-purpose`) silently undoes the table below, and
`feature-dev:code-architect` / `feature-dev:code-reviewer` have **no
Write/Edit/Bash**, so an artifact writer spawned with one silently fails.

| Worker                                         | Agent type                       | Model · effort    |
| ---------------------------------------------- | -------------------------------- | ----------------- |
| Profiler (Phase 1, only with no saved profile) | `auto-dev:profiler`              | `sonnet` · medium |
| Define agent (Phase 2)                         | `auto-dev:define`                | `opus` · high     |
| Define reviewer (Phase 2)                      | `auto-dev:define-reviewer`       | `opus` · high     |
| Planner (Phase 3)                              | `auto-dev:planner`               | `opus` · xhigh    |
| Plan reviewer (Phase 3)                        | `auto-dev:plan-reviewer`         | `opus` · high     |
| Acceptance tester (Phase 3, every scope)       | `auto-dev:acceptance-tester`     | `opus` · high     |
| Coder: STANDARD build, every correction        | `auto-dev:coder`                 | `opus` · high     |
| Coder: TRIVIAL first build                     | `auto-dev:coder-trivial`         | `sonnet` · medium |
| Verifier (Phase 5, re-spawned on every change) | `auto-dev:verifier`              | `opus` · high     |
| Cleanup agent (Phase 5, re-spawned on fixes)   | `auto-dev:cleanup`               | `sonnet` · medium |
| Code reviewer, ×3 panel + re-votes (Phase 6a)  | `auto-dev:code-reviewer`         | `opus` · xhigh    |
| Review judge (Phase 6a)                        | `auto-dev:review-judge`          | `opus` · xhigh    |
| Security reviewer (Phase 6a)                   | `auto-dev:security-reviewer`     | `opus` · xhigh    |
| Security reviewer, sensitive paths (Phase 6a)  | `auto-dev:security-reviewer-sensitive` | `fable` · high |
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
- **Use `auto-dev:security-reviewer-sensitive`** when `SPEC.md`'s
  `Security/Compliance criteria` section lists controls for a sensitive path, and
  `auto-dev:security-reviewer` otherwise. The code review panel is always three
  `auto-dev:code-reviewer`s.

**Never pass the Agent tool's `model` parameter** when spawning a worker: it
overrides the type's model. To change a worker's model or effort, edit its
`agents/<name>.md` frontmatter and this table together. Its tools are likewise
fixed by the frontmatter's `tools:` and listed in `references/subagent-prompts.md`,
_Tools per worker_. Reviewers are read-only w.r.t. source.

Hand each worker **two** absolute paths — its worktree and its `<artifact-dir>`
(different trees on a multi-PR run; `references/artifacts.md`) — plus
`profile.md` and only the inputs its phase needs. The coder gets the **plan only,
never the spec or the sealed acceptance checks**; the verifier gets the **spec and
the checks, never the plan or the coder's report**. **Avoid giving a worker a >5-minute blocking command** (the
cleanup agent's quality gate is the deliberate exception), and every brief says:
**spill large output to `$TMPDIR` and return a digest, never a corpus**
(`references/subagent-prompts.md`, _Conventions for every brief_).

## Reading discipline (orchestrator)

Your average `Read` costs ~5.5k tokens and stays in context for the rest of the
session. Before every one, ask whether a worker should read it instead.

- **Never `Read` a source file to understand it.** Spawn `auto-dev:lookup` and ask
  for the conclusion. You are the orchestrator; you do not need the code.
- **Never `Read` a whole file when you need one fact.** `grep -n` for it, then
  read the surrounding lines — or better, have the worker answer.
- **Full `git diff` is for workers.** Freely run `git diff --stat` and
  `git diff --name-only`. Everywhere else (scoping, sanity checks, "what changed
  again?") delegate to a worker that returns a verdict — Phase 5's verifier reads
  the whole diff so that you don't.
- **Each reference file, at most once per session** — `subagent-prompts.md` alone
  is ~5k tokens, and S1/S2/S3 each need only their own phases' references.
- **Find symbols with `profile.md`'s _Symbol lookup_ commands.** They name the
  stack's code-index tool when the profile has one and it's on PATH, and
  `grep -n` otherwise (also when `profile.md` has no such line).

---

## Phase 1 — Setup

Run by the orchestrator; only the profile research goes to a worker.

**First: is this a resumed run?** The control worktree is a sibling of the repo
you start in. Run
`python3 <skill-dir>/scripts/resume-point.py <tree>/.auto-dev --task "<ticket or task>"`
on each tree in `git worktree list` — omit `--task` on a bare `auto-dev
continue` or a loose name for the run ("the multi-currency run"), where the user
named no ticket or task; then only an exit `0` counts, several is a
stop-and-ask, and none means there is nothing to continue (ask, don't start fresh).
If one matches, do not re-run Phase 1 — continue from its ledger
(`references/artifacts.md`, _Resuming an interrupted run_). A `NEAR-MISS` may be
the run: show the user each near-miss's task and ask which (if any) is theirs,
as that section says — never a fresh Phase 1 unasked.

**Fresh run: before step 1, read `references/phase-1-setup.md`** — each step's
procedure and exact commands. The steps, in order:

1. **Detect the repo & branches.** **Check `gh` first** — missing,
   unauthenticated, or a non-GitHub `origin` is a **stop-and-report now**.
2. **Resolve the profile** — the saved one (`scripts/profile-path.py`), else
   `auto-dev:profiler` researches one, the user confirms it and may save it;
   apply `.auto-dev.yml` (validated); record the CI provider.
3. **Resolve the ticket** (Jira via the Atlassian MCP, else the free-form task).
4. **Read the repo's binding rules**; resolve the security directives.
5. **Create the isolated worktree** on its own branch — **never the default
   branch** — from a freshly fetched `origin/<base>`; seed `worktree_files`; run
   `setup`.
6. **Prep `.auto-dev/` self-excluding** (`scripts/exclude-artifacts.py`) — never
   `.git/info/exclude`.
7. **Write `.auto-dev/profile.md`** and initialize `.auto-dev/WORK_LOG.md`.
8. **Jira → In Progress** (if a ticket exists), confirmed with the user.

All later phases run **inside the worktree directory**.

## Phase 2 — Define (the testable contract + scope call)

Each worker's brief, and the full procedure for Phases 2–5, is in
`references/subagent-prompts.md`, under the same phase heading.

Spawn **one** Define agent → `.auto-dev/SPEC.md`: research, the acceptance
conditions **as a testable contract** — each with a concrete **Example**, an
**Edge** case and a **Verify by** level — and a **scope call**.

1. **Read the scope call first** — it decides whether step 2 runs and which path
   Phase 3 takes.
2. **Define reviewer** (read-only) → critique, including an **ambiguity probe**
   (two implementations that fit a condition's words but differ); apply fixes
   yourself; re-review while it finds blockers (each re-review spends a round).
   STANDARD only — on TRIVIAL the acceptance tester's AMBIGUOUS report is the
   only probe —
   **skipped on TRIVIAL and OVERSIZED**.

Hold `SPEC.md` — you withhold it from the coder and use it for Phase 5.

## Phase 3 — Plan

On **TRIVIAL**, skip steps 1–2 and write a short `IMPLEMENTATION.md` yourself
(files to touch + the test that proves it).

1. **Planner** → `.auto-dev/IMPLEMENTATION.md`, the self-contained technical plan;
   every spec condition maps to a step and a test.
2. **Plan reviewer** (read-only) → critique; apply fixes; re-review while it finds
   blockers (each re-review spends a round).
3. **Acceptance tester** → `.auto-dev/acceptance/`, at **every** scope: from
   `SPEC.md` alone (the plan only for entry points), one or more black-box checks
   per condition; each new-behavior check must **fail on the untouched tree for
   the right reason**. It then **seals** them — removes them from the worktree and
   keeps the only copy under `acceptance/files/` as `<path>.sealed` — and writes
   `MANIFEST.md`.
4. **Optional post-plan gate**, if enabled for this run — **independent of the
   scope call**, so it fires on TRIVIAL too.

## Phase 4 — Build

Spawn the **coder (TDD)** with **only `IMPLEMENTATION.md`, never the spec**. Its
brief forbids deleting, skipping or weakening tests and gaming them, and gives it
a **`BLOCKED`** exit instead of forcing a step green. Settle every `BLOCKED` step
before Phase 5 (a plan fix and re-dispatch spends a round; a spec that cannot be
met is a stop-and-report). Read its **plan deviations** as information, not as
defects — the verifier never sees them.

## Phase 5 — Verify (verifier → simplify → quality gate → re-check)

Four steps, never reordered. **Before step 1, consult
`references/subagent-prompts.md`, _Phase 5 — Verify_** (already read for Phase 4;
don't re-read the whole file) — the verifier's brief, acting on its verdicts, the
correction brief, and the cleanup agent's brief.

1. **Verifier** (`auto-dev:verifier`, no plan, no coder report) installs the
   sealed checks, audits every test change (`scripts/check-tests.py`), **runs**
   the evidence for each `SPEC.md` condition and writes `.auto-dev/SPEC_EVAL.md`:
   a verdict (`met` / `partial` / `unmet` / `manual`) and an **evidence tier**
   per condition — **Strong** (held-out checks passed), **Adequate** (it ran
   something itself and saw what it predicted), **Weak** (a citation; caps the
   verdict at `partial`). It also plants **targeted mutants** in the changed
   lines (`scripts/mutate.py`, capped by `mutation.max`): one the tests don't
   catch on a condition's lines is a **test gap** and caps that condition at
   `partial`. You read `SPEC_EVAL.md`, not the diff. An unmet or
   partial condition, or an unjustified integrity finding → a **specific**
   correction brief to the coder (concrete behavior, never the spec verbatim),
   then a verifier re-check; each correction spends budget
   (`references/correction-loop.md`). A `manual` condition goes to the PR gate
   for a human, never to the coder.
2. **Simplify.** Once the loop settles, spawn the cleanup agent to run
   **`/simplify`** over the branch diff. Behavior-preserving only.
3. **Quality gate.** The same agent runs the profile's `gate` commands to green,
   writing `.auto-dev/lint/<CHECK>.md` per check, spending **no** budget, and
   never by weakening a test. If it can't get green, **stop and report** — never
   ship a red build.
4. **Re-check.** Re-spawn the verifier (no budget): it re-runs the checks and the
   audit over the final code and rewrites `SPEC_EVAL.md`. A condition no longer
   met is a Phase 5 correction, followed by a free cleanup re-spawn and another
   re-check.

## Phase 6 — Ship **[three human gates]**

**Before starting Phase 6, read `references/phase-6-ship.md`** — the exact commit,
push, staging-merge and main-merge sequences and what to do when each fails —
`references/review.md` for the two reviews and their rubric, and
`references/gates-and-jira.md` for the gate scripts, Jira transitions and CI policy.

### 6a — Review, then PR **[gate]**

Both reviews run on the **uncommitted** working tree: nothing is committed or
pushed until they settle and the user approves.

1. **Code review panel** → `.auto-dev/CODE_REVIEW.md`. Three
   `auto-dev:code-reviewer`s run `/code-review xhigh` independently; the
   `auto-dev:review-judge` merges them, confirms each trigger path and applies the
   rubric; a correctness or test finding only one reviewer raised goes to the other
   two for a re-vote. Must-fix → the correction loop, then the panel again on the
   fix's files.
2. **Security review** → `.auto-dev/SECURITY_REVIEW.md`. One security reviewer runs
   `/security-review` over the whole change; the judge verifies every High/Medium
   finding. An introduced, confirmed finding is must-fix → the correction loop,
   then Step 1 on the fix's files, then this step again. A pre-existing one goes to
   the user at the PR gate.
3. **Gate:** pause for approval to open the PR. The summary carries the
   acceptance verdicts with their evidence tiers, every `manual` check a human
   must make, the justified test changes, both reports' confidence and counts,
   any open must-fix, and the pre-existing security findings for the user to
   triage.
4. **Commit** — stage source paths **explicitly** (never `git add -A`/`.`); commit
   only once `scripts/check-staged.py --expect <paths>` passes.
5. **Push** — **never `--force`** — and open **exactly one** PR, a draft by
   default, carrying the **acceptance checklist**, the **quality-gate results** and
   the **review summary**.
6. **CI monitoring**, bounded. Red pre-merge → the correction loop, whose fix is
   reviewed (both steps) before the Phase 6a refresh commits and re-pushes it.
7. **Jira → In Review.**

### 6b — Staging **[gate]** (skip if no staging branch)

Pause for approval, **directly merge** into `staging`, and monitor CI there. Never
resolve conflicts on staging or force the push unasked.

### 6c — Main **[gate]**

1. **Read what humans said**; mark the PR ready. A human blocker goes through the
   correction loop (its fix reviewed like any other), never merged over.
2. **Gate:** pause for approval.
3. **Merge to main** only via `gh pr merge` with an explicit method — **never
   `--admin`**. Refused → report the PR unmergeable and stop. Then confirm it is
   `MERGED`; queued or auto-merge → report and stop, without moving Jira.
4. Monitor CI on main, **Jira → Done**, and offer to remove the worktree —
   confirmed, and never the control worktree before the final report (multi-PR:
   each sub-task's build worktree; single-PR: this worktree *is* the control
   worktree, so offer it after the report).

---

## Final report

Summarize: branch/worktree path, PR link(s), what was built, the scope call,
acceptance verdicts with evidence tiers (and every `manual` check left for a
human), assumptions made, final quality-gate status, Jira transitions performed, remaining
iteration budget, and anything left unresolved. In a multi-PR run, report per
sub-task from `WORK_LOG.md`. Be honest about skipped steps and unmet conditions —
never report success you didn't verify. Default shape: `references/artifacts.md`.

## Bounds and guardrails

- **Stop-and-report conditions** — leave the work in place and explain: `gh` is
  missing, unauthenticated, or `origin` isn't GitHub; the worktree can't be
  created, or a seeded `worktree_files` file isn't gitignored; the resolved
  quality gate has **no test command** (an empty gate passes by checking nothing);
  a `setup` command is missing (exit `127`); the task is self-contradictory or
  impossible as specified; the quality gate can't be made green; the verifier
  returns `MUTATION LEFT CHANGES` (the source may not be the code that was built); the build edited
  source inside a submodule; spec conditions remain unmet after the iteration
  budget; `gh pr merge` refuses (or only queues) the merge; a sub-task's scope
  call comes back OVERSIZED; the user declines a gate or merge.
- **Never weaken security to finish** — no disabled TLS/cert/signature checks, no
  exposed or hardcoded secrets, no real/sensitive data or PII in tests/fixtures.
  The repo's rules and the security directives in `profile.md` override "finish
  the task".
- **Never commit `.auto-dev/`.** Self-excluding from Phase 1; stage explicitly in
  Phase 6, never `git add -A`/`.` (`references/artifacts.md`).
- **Promotion safety:** main only via `gh pr merge`; staging via direct merge only
  where the project uses that convention.
- **Per-job isolation:** a fresh worker per delegated job; hand off via
  `.auto-dev/` and the git tree; give each worker only the inputs its phase needs.
