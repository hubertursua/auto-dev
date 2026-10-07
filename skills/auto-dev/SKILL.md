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
| `scripts/validate-config.py` | S1, Phase 1 step 2, when `.auto-dev.yml` exists | run (not read): `python3 <skill-dir>/scripts/validate-config.py <repo>/.auto-dev.yml`; needs PyYAML (without it, exit `2` — not a pass); exit codes in `references/profiles.md` |
| `scripts/resume-point.py` | Phase 1's resume check; any re-entry | run (not read): `python3 <skill-dir>/scripts/resume-point.py <tree>/.auto-dev --task "<ticket or task>"` names the resume point; exit codes in `references/artifacts.md`, _Resuming an interrupted run_ |
| `scripts/exclude-artifacts.py` | S1, Phase 1 step 6 | run (not read): `python3 <skill-dir>/scripts/exclude-artifacts.py <worktree>`; exit codes in `references/phase-1-setup.md`, step 6 |
| `scripts/check-staged.py` | S3, before every Phase 6a commit | run (not read): `python3 <skill-dir>/scripts/check-staged.py <worktree> --expect <path> …`; exit codes in `references/phase-6-ship.md`, step 2 |
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

The user picks the orchestrator's model per session: S1 (the scope call) and S2
(the acceptance check) need `opus`; S3 is scripted git/gh/CI work, so `sonnet`
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
`SPEC.md` for the acceptance check; in S3, `SPEC.md`, `SPEC_EVAL.md` and
`lint/*.md` for the PR body and the PR gate summary. `IMPLEMENTATION.md` is the
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
  sub-task**, each with its own branch, worktree, PR, scope call and **iteration
  budget**. A sub-task may **not** be OVERSIZED.

What to record for each call, and the full multi-PR procedure (sub-task
worktrees, `<artifact-dir>` per sub-task, an OVERSIZED sub-task), are in
`references/subagent-prompts.md`, _Scope decision_ — read it before acting on an
OVERSIZED call.

> **The scope call thins the planning head, never the verification tail.**
> Phase 5 (acceptance + simplify + quality gate) and Phase 6 (adversarial review +
> CI + human gates) run identically at every scope.

## Human gates

Planning and build run unattended. Four gates pause for explicit approval (via
`AskUserQuestion`): the **post-plan gate** (Phase 3, **OFF by default**), the
**PR gate** (6a), the **staging gate** (6b) and the **main gate** (6c). A bare
"gate" always means one of these four; the Phase 5 checks are the **quality
gate**, run from the profile's `gate` commands.

Three **conditional** pauses fire only when their situation arises: the
**decomposition approval** (OVERSIZED only — never start a multi-PR run
unapproved), the **Jira In Progress confirmation** (only with a ticket), and the
**worktree cleanup offer** (6c). Everything else runs without check-ins.

Each gate's summary, options, **what each option does**, its Jira transition, and
when to enable the post-plan gate are in `references/gates-and-jira.md`. Record
every gate decision, and its reason, in `WORK_LOG.md`.

## Corrections and the iteration budget

An unmet spec condition, a PR-review blocker, and a red CI check are **one
correction loop entered at three points**, drawing on **a single budget of
revise rounds per task** (default **4**, overridable via `.auto-dev.yml`; per
sub-task on a multi-PR run), shared with the Phase 2/3 re-reviews. Each re-review
or correction spends a round, **decremented before dispatch** and tracked in
`WORK_LOG.md`; cleanup-agent spawns never do. At zero, **stop and report** instead
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
  them. `SPEC.md` and `SPEC_EVAL.md` are exempt at any length — the acceptance
  check is yours by design, and delegating it would delegate away the one check
  no worker can run.

## Tool permissions & models

Every worker has its own agent type in this plugin's `agents/` directory, which
fixes its tools, model and effort. Spawn **exactly the type named**: a generic
type (`claude` / `general-purpose`) silently undoes the table below, and
`feature-dev:code-architect` / `feature-dev:code-reviewer` have **no
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
overrides the type's model. To change a worker's model or effort, edit its
`agents/<name>.md` frontmatter and this table together. Its tools are likewise
fixed by the frontmatter's `tools:` and listed in `references/subagent-prompts.md`,
_Tools per worker_. Reviewers are read-only w.r.t. source.

Hand each worker **two** absolute paths — its worktree and its `<artifact-dir>`
(different trees on a multi-PR run; `references/artifacts.md`) — plus
`profile.md` and only the inputs its phase needs. The coder gets the **plan only,
never the spec**. **Avoid giving a worker a >5-minute blocking command** (the
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

**First: is this a resumed run?** The control worktree is a sibling of the repo
you start in. Run `scripts/resume-point.py <tree>/.auto-dev --task "<ticket or
task>"` on each tree in `git worktree list`; if one matches, do not re-run Phase 1 —
continue from its ledger (`references/artifacts.md`, _Resuming an interrupted run_).

**Fresh run: before step 1, read `references/phase-1-setup.md`** — each step's
procedure and exact commands. The steps, in order:

1. **Detect the repo & branches.** **Check `gh` first** — missing,
   unauthenticated, or a non-GitHub `origin` is a **stop-and-report now**.
2. **Detect the stack & load the profile**; apply `.auto-dev.yml` (validated);
   record the CI provider.
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
conditions **as a testable contract**, and a **scope call**.

1. **Read the scope call first** — it decides whether step 2 runs and which path
   Phase 3 takes.
2. **Define reviewer** (read-only) → critique; apply fixes yourself; re-review
   while it finds blockers (each re-review spends a round). STANDARD only —
   **skipped on TRIVIAL and OVERSIZED**.

Hold `SPEC.md` — you withhold it from the coder and use it for Phase 5.

## Phase 3 — Plan

On **TRIVIAL**, skip steps 1–2 and write a short `IMPLEMENTATION.md` yourself
(files to touch + the test that proves it).

1. **Planner** → `.auto-dev/IMPLEMENTATION.md`, the self-contained technical plan;
   every spec condition maps to a step and a test.
2. **Plan reviewer** (read-only) → critique; apply fixes; re-review while it finds
   blockers (each re-review spends a round).
3. **Optional post-plan gate**, if enabled for this run — **independent of the
   scope call**, so it fires on TRIVIAL too.

## Phase 4 — Build

Spawn the **coder (TDD)** with **only `IMPLEMENTATION.md`, never the spec**. Read
its **plan deviations** as information going into Phase 5, not as defects.

## Phase 5 — Verify (acceptance → simplify → quality gate)

Three steps, never reordered. **Before step 1, consult
`references/subagent-prompts.md`, _Phase 5 — Verify_** (already read for Phase 4;
don't re-read the whole file) — the working-tree diff
commands (the coder doesn't commit), the correction brief, the cleanup agent's
brief and the evidence re-check.

1. **Acceptance (you).** Verify the build against every `SPEC.md` condition and
   write `.auto-dev/SPEC_EVAL.md`. Unmet or partial → a **specific** correction
   brief to the coder (concrete behavior, never the spec verbatim), then re-check;
   each round spends budget (`references/correction-loop.md`).
2. **Simplify.** Once the acceptance loop settles, spawn the cleanup agent to run
   **`/simplify`** over the branch diff. Behavior-preserving only.
3. **Quality gate.** The same agent runs the profile's `gate` commands to green,
   writing `.auto-dev/lint/<CHECK>.md` per check, spending **no** budget. If it
   can't get green, **stop and report** — never ship a red build. Then
   **re-resolve `SPEC_EVAL.md`'s evidence** for the files simplify touched; a
   condition no longer met is a Phase 5 correction, followed by a free cleanup
   re-spawn.

## Phase 6 — Ship **[three human gates]**

**Before starting Phase 6, read `references/phase-6-ship.md`** — the exact commit,
push, staging-merge and main-merge sequences and what to do when each fails — and
`references/gates-and-jira.md` for the gate scripts, Jira transitions and CI policy.

### 6a — PR **[gate]**

1. **Gate:** pause for approval to open the PR.
2. **Commit** — stage source paths **explicitly** (never `git add -A`/`.`); commit
   only once `scripts/check-staged.py --expect <paths>` passes.
3. **Push** — **never `--force`** — and open **exactly one** PR, a draft by
   default, carrying the **acceptance checklist** and the **quality-gate results**.
4. **PR reviewer** (adversarial) → `.auto-dev/PR_REVIEW.md`.
5. **CI monitoring**, bounded. Red pre-merge → the correction loop.
6. **Jira → In Review.**

### 6b — Staging **[gate]** (skip if no staging branch)

Pause for approval, **directly merge** into `staging`, and monitor CI there. Never
resolve conflicts on staging or force the push unasked.

### 6c — Main **[gate]**

1. **Read what humans said**; mark the PR ready. A human blocker goes through the
   correction loop, never merged over.
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
assumptions made, final quality-gate status, Jira transitions performed, remaining
iteration budget, and anything left unresolved. In a multi-PR run, report per
sub-task from `WORK_LOG.md`. Be honest about skipped steps and unmet conditions —
never report success you didn't verify. Default shape: `references/artifacts.md`.

## Bounds and guardrails

- **Stop-and-report conditions** — leave the work in place and explain: `gh` is
  missing, unauthenticated, or `origin` isn't GitHub; the worktree can't be
  created, or a seeded `worktree_files` file isn't gitignored; the resolved
  quality gate has **no test command** (an empty gate passes by checking nothing);
  a `setup` command is missing (exit `127`); the task is self-contradictory or
  impossible as specified; the quality gate can't be made green; the build edited
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
