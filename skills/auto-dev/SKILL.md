---
name: auto-dev
description: >-
  Use this when the user wants you to take an entire coding task off their plate
  — implement a whole feature or fix and deliver it as a finished, reviewed pull
  request, working autonomously through a full plan → build → verify → ship
  pipeline. It's the right call whenever someone asks you to BUILD something AND
  ship it yourself in one pass: "do it autonomously", "by yourself", "you do it",
  "raise/open the PR", "take it all the way", "from ticket/idea/spec to PR", "run
  the whole dev cycle", "knock it out", "make the calls on anything ambiguous",
  "don't make me babysit each step", "pick up JIRA-1234 and ship it", or an
  explicit "auto-dev …". Prefer this over ordinary guided feature-development help
  whenever the user wants the full pipeline run hands-off, not one supervised
  step. Do NOT use it for a single slice of that work: running or fixing one
  test/lint/type error, critiquing a plan, explaining how code works, or answering
  a question. Choose it only when they clearly want the whole task carried
  autonomously to a PR on their behalf.
---

# auto-dev

Drive a single task through the entire development lifecycle — from a ticket to a
merged pull request — using purpose-built subagents for each delegated job and handing
structured artifacts between them through `.auto-dev/`. You (the main agent) are
the **orchestrator**: you own the pipeline, hold the spec, run the human gates,
and never write implementation code yourself. Every delegated job runs in its own
fresh subagent so your context stays clean and each worker stays focused on one
job. Not every phase delegates: Phase 1 and the Phase 5 acceptance check are
yours.

This skill is **stack-agnostic**. A **stack profile** (see
`references/profiles.md`) supplies the concrete setup and quality-gate commands;
Phase 1 detects the stack, loads the matching `profiles/*.md`, merges in runtime
discovery, and honors a repo-local `.auto-dev.yml` override. Shipped profiles live
in `profiles/`; an unknown stack falls back to `default.md` + runtime discovery.
Add a stack by dropping in a new profile — no change to this file.

External integrations are **optional and auto-detected**: Jira (status
transitions only), a CI provider (GitHub Actions / CircleCI / GitLab), and a
staging branch. Each is used when present and skipped cleanly when not. Details in
`references/gates-and-jira.md`.

## Reference files (read on demand)

Keep this spine in context; open a reference only when you reach the phase that
needs it.

- `references/profiles.md` — profile schema, detection precedence, monorepo rules, `.auto-dev.yml` override.
- `references/artifacts.md` — the `.auto-dev/` layout, the `WORK_LOG.md` ledger, and every artifact's contract.
- `references/subagent-prompts.md` — the exact brief template + tool requirements for each delegated Task Agent.
- `references/gates-and-jira.md` — human-gate scripts, Jira transition mapping, CI monitoring policy (timeouts, on-red).
- `references/correction-loop.md` — the one corrective loop (unmet condition / PR blocker / CI red), what each correction invalidates, and the iteration budget.

## Pipeline at a glance

```
Phase 1  Setup   → detect repo + stack, resolve ticket, worktree + branch, prep .auto-dev/
Phase 2  Define  → research + the testable contract (SPEC.md); SCOPE CALL (trivial / standard / oversized)
Phase 3  Plan    → plan agent writes IMPLEMENTATION.md; plan reviewer critiques      [optional gate]
Phase 4  Build   → coding agent implements + tests, given only the plan
Phase 5  Verify  → acceptance vs. the withheld spec → simplify → quality gate to green
Phase 6  Ship    → [GATE] commit + PR + adversarial review + CI → [GATE] staging → [GATE] main + Jira
```

Run phases in order; each depends on the previous. Track them in
`.auto-dev/WORK_LOG.md` (which is also the resume point) and mirror the status in
TodoWrite so progress stays visible.

## Why two documents

The pipeline keeps exactly two descriptions of the work, and they answer different
questions:

- **`SPEC.md` — did we build the right thing?** The testable contract: observable
  conditions, no design.
- **`IMPLEMENTATION.md` — did we build it the way we decided?** The technical how.

They fail **independently**. A plan executed faithfully can still miss the
outcome; an outcome can be delivered by a route the plan never described. One
merged document collapses both into a single check, and it is the weaker one —
design detail crowds out the outcome statement.

**The coder builds from the plan, never the contract.** The plan is *required* to
cover every condition (Phase 3), so this is not information-hiding — it is
**language**-hiding: the coder cannot satisfy the acceptance check by echoing the
contract's own wording back in a test name. The Phase 5 acceptance check is
independent because the context that runs it did not write the code.

## Task-orchestration layer (scope call, decompose & track)

Phase 2 returns a three-way **scope call**, and the pipeline adapts to it:

- **TRIVIAL** — one subsystem, one behavior, no new abstraction or interface, no
  migration or config change, and an existing test file covers it. Skip the Define
  review and the Phase 3 agents; you write a short `IMPLEMENTATION.md` yourself
  (files to touch + the test that proves it). Phases 4–6 run normally.
- **STANDARD** — the full path: Phase 3 onward runs in full. Record `Mode: single-PR`.
- **OVERSIZED** — multiple independent deliverables, several subsystems, or a large
  file count. Do **not** cram it onto one branch: propose an ordered set of
  sub-tasks (with dependencies), write them to `WORK_LOG.md`, and **alert the
  user**. On approval, run Phases 2–6 **per sub-task** — each *building* in its
  own branch/worktree, while its *artifacts* stay in the **control worktree** (the
  one Phase 1 created) under `.auto-dev/tasks/<id>/` — respecting dependency order
  and updating the ledger after each. Each sub-task gets its
  **own** scope call, so a sub-task can itself be TRIVIAL. Each produces its own PR.

> **The scope call thins the planning head, never the verification tail.**
> Phase 5 (acceptance + simplify + gate) and Phase 6 (adversarial review + CI +
> gates) run identically at every scope.

`WORK_LOG.md` is the single source of truth across a multi-PR run and the resume
point if interrupted — read it first when resuming (`references/artifacts.md`).

## Human gates

This skill runs the planning and build unattended. Four gates pause it for
explicit approval (via `AskUserQuestion`):

- **Post-plan gate (Phase 3) — OFF by default.** Turn it on for the run when any
  of these holds: the user asked to see the plan before building; `.auto-dev.yml`
  sets `gates.post_plan: true`; or the task is **high-risk**, meaning `SPEC.md`
  carries Security/Compliance criteria, or the change touches auth, payments,
  access control, or a data migration. Then pause after `IMPLEMENTATION.md` to
  approve SPEC + plan before any code is written. Record the decision, and the
  reason, in `WORK_LOG.md`.
- **PR gate (Phase 6).** Pause before opening the PR.
- **Staging gate (Phase 6).** Pause before the direct merge to staging.
- **Main gate (Phase 6).** Pause before merging the PR to main.

Three further pauses are **conditional**, and are not gates in the sense above —
they fire only when their situation arises: the **decomposition approval**
(Phase 2, OVERSIZED only — never start a multi-PR run unapproved), the **Jira
In Progress confirmation** (Phase 1, only with a ticket), and the **worktree
cleanup offer** (Phase 6c). Everything else runs without check-ins.

Jira status transitions ride along with these gates. Every gate and conditional
pause — its summary, its option set, and the Jira transition it carries — is
specified in `references/gates-and-jira.md`.

## Corrections and the iteration budget

An unmet spec condition, a PR-review blocker, and a red CI check are **one
corrective loop entered at three points**. All of them draw on **a single budget
of revise rounds** (default **4**, overridable via `.auto-dev.yml`) rather than a
cap per loop. Each re-spawn or re-run for correction spends a round, decremented
before dispatch and tracked in `WORK_LOG.md`; at zero, **stop and report** instead
of looping.

The loop's steps, what each correction invalidates and must refresh, and the full
budget accounting are in `references/correction-loop.md` — the single statement of
both. Do not restate its rules elsewhere.

## Tool permissions & models

Pick an agent type that grants the tools listed. The safe default for any worker
is a full-tool type (`claude` / `general-purpose`, tool set `*`). The trap is a
read-only blueprint/reviewer type (`feature-dev:code-architect`,
`feature-dev:code-reviewer`): **no Write/Edit/Bash**, so it cannot create
artifacts, implement, or run the gate — and both also pin `model: sonnet`, so
they quietly downgrade the phase on top of failing it. **Never spawn an artifact
writer with a read-only type** — it will silently fail. Only the two reviewers
(Define review, plan review) are genuinely read-only; every other worker writes at
least one file. The per-worker list below is authoritative.

**Models.** **Every worker inherits your model** — no brief pins one. There is no
"mechanical" worker to economize on: Define's contract is what every later phase
derives from, and a weak reviewer returns "no findings," which is indistinguishable
from a clean pass. The only model risk is the *accidental* pin in the read-only
agent types above.

- **Orchestrator (you):** TodoWrite, Bash (git/gh/CI, worktree, setup), Read,
  Edit (revise artifacts after critique), Write (`WORK_LOG.md`, `profile.md`,
  `SPEC_EVAL.md`, and `IMPLEMENTATION.md` on the TRIVIAL fast path), the
  Agent/Task tool (spawn every worker), AskUserQuestion
  (gates), and the Atlassian MCP Jira tools when a ticket is present.
- **Define agent (Phase 2):** Write + Read, Grep, Glob (research is read-only; it
  writes `SPEC.md`).
- **Define reviewer (Phase 2):** Read, Grep, Glob only.
- **Plan agent (Phase 3):** Write + Read, Grep, Glob.
- **Plan reviewer (Phase 3):** Read, Grep, Glob only.
- **Coding agent (Phase 4):** Read, Write, Edit, Bash, Grep, Glob.
- **Cleanup agent (Phase 5):** Read, Edit, Write, Bash, plus the **Skill** tool to
  run `/simplify`.
- **PR reviewer (Phase 6):** Read, Grep, Glob, Bash (`git diff`, `gh`), Write —
  read-only **w.r.t. source**, but it must be able to write its one artifact,
  `.auto-dev/PR_REVIEW.md`.

Per-phase isolation: hand each worker **two** absolute paths — the worktree it
works in, and the `<artifact-dir>` it reads and writes (the two are the same tree
on a single-PR run and different trees on a multi-PR one; see
`references/artifacts.md`) — plus `profile.md` and only the inputs its phase
needs. The coder gets the **plan only, never the spec** (see *Why two documents*).

---

## Phase 1 — Setup

Deterministic, run by the orchestrator.

**First: is this a resumed run?** If a `.auto-dev/WORK_LOG.md` for this task
already exists, do not re-run Phase 1 — read the ledger and continue from it
(`references/artifacts.md`, *Resuming an interrupted run*).

1. **Detect the repo & branches.** Canonical repo name from the git remote
   (`basename -s .git "$(git remote get-url origin)"`); default branch via
   `gh repo view --json defaultBranchRef`. Resolve `base`, `staging` (optional),
   and branch `prefix` — from `.auto-dev.yml` if present, else conventional
   defaults. If there is no `staging` branch, mark the Phase 6 staging gate as N/A.
   **Check `gh` before anything else in this step** — `gh auth status`, and an
   `origin` that is GitHub. Phase 6 cannot open or merge a PR without it, so a
   missing, unauthenticated, or non-GitHub setup is a **stop-and-report now**, not
   a surprise after the build.
2. **Detect the stack & load the profile.** Match `detect` signals
   (`references/profiles.md`) → load `profiles/<stack>.md`, else `default.md` +
   runtime discovery. Merge in repo-doc/CI discovery, apply `.auto-dev.yml`. While
   reading CI config, **record the CI provider** (GitHub Actions / CircleCI /
   GitLab / none) — `profile.md` carries it and Phase 6 monitors with it.
3. **Resolve the ticket.** If the user gave a Jira key/URL, read it via the
   Atlassian MCP (`getJiraIssue`); detect Jira availability and cache the issue.
   Otherwise treat the free-form task text as the ticket.
4. **Read the repo's binding rules** — `CLAUDE.md`/`AGENTS.md`, `CONTRIBUTING`,
   security/coding-guideline docs, plus the org security directives — and carry
   them into every worker's brief.
5. **Create the isolated worktree** on its own branch (never the default branch):
   ```bash
   git worktree add ../<repo-name>-<slug> -b <prefix>/<slug> origin/<base>
   ```
   Then run the profile's `setup` commands. Derive `<slug>` from the ticket/task:
   the slug is **yours alone**, since the branch and worktree exist before Phase 2
   runs. No later phase returns or renames one.
6. **Prep `.auto-dev/`** and make it self-excluding (see `references/artifacts.md`):
   ```bash
   mkdir -p .auto-dev/lint
   printf '*\n' > .auto-dev/.gitignore
   ```
   A `.gitignore` containing `*` ignores the whole directory, itself included.
   Do **not** use `.git/info/exclude` here: inside a linked worktree `.git` is a
   *file*, not a directory, so that command fails outright — and the shared file
   it resolves to would leak into every other worktree. Confirm with `git status`
   that nothing under `.auto-dev/` appears.
7. **Write `.auto-dev/profile.md`** (fully-resolved profile) and initialize
   `.auto-dev/WORK_LOG.md` — whose header carries the normalized ticket.
8. **Jira → In Progress** (if a ticket exists), confirmed with the user as part of
   starting work (`references/gates-and-jira.md`).

All later phases run **inside the worktree directory**.

## Phase 2 — Define (the testable contract + scope call)

Spawn **one** Define agent (brief in `references/subagent-prompts.md`) that, in a
single pass: researches the ticket against the codebase, states the acceptance
conditions **as a testable contract**, and returns a **scope call**. It writes one
file, `.auto-dev/SPEC.md`, containing a `Context` section (restated ticket +
research findings), the testable conditions in plain language, an `Assumptions`
section, and a `Security/Compliance criteria` section for sensitive paths.

One agent does research *and* contract because the agent holding the codebase
research is the one best positioned to know what is actually observable.

Then:

1. **Read the scope call first** — it decides whether step 2 runs at all, and
   which path Phase 3 takes (TRIVIAL / STANDARD / OVERSIZED, per the
   task-orchestration layer above).
2. **Define reviewer** (read-only) → critique. Apply fixes yourself (you have the
   context); re-review only if blockers remain. Consumes the shared iteration
   budget. **Skipped on TRIVIAL** (nothing to review that the plan won't restate)
   **and on OVERSIZED** (the parent spec only informs the decomposition — each
   sub-task gets its own reviewed spec). It runs on STANDARD.

Hold `SPEC.md` — you withhold it from the coder and use it for Phase 5.

## Phase 3 — Plan

**Skipped as an agent phase when the scope call is TRIVIAL** — you write a short
`IMPLEMENTATION.md` yourself instead (files to touch + the test that proves it).

1. **Plan agent** → `.auto-dev/IMPLEMENTATION.md` — the self-contained technical
   plan; every spec condition maps to a step and a test. Reads `SPEC.md`.
2. **Plan reviewer** (read-only) → critique; apply fixes; re-review if blockers.
   Consumes the shared budget. A spec condition with no plan step is cheapest to
   catch here, before any code exists.
3. **Optional post-plan gate** — if enabled for this run (see *Human gates* for
   when to enable it), pause here to approve `SPEC.md` + `IMPLEMENTATION.md`
   before any code is written. It is **independent of the scope call**: it fires
   on the TRIVIAL path too, on the plan you wrote yourself.

## Phase 4 — Build

Spawn the **coding agent (TDD)** with **only `IMPLEMENTATION.md`, never the spec**.
It implements code and tests, working through the plan's build sequence in order
and running the relevant tests as it goes.

Its structured return reports **plan deviations** — anything it could not do, or
did differently, and why. Read that as **information going into Phase 5**, not as
a defect to correct: the plan is a route, and the acceptance check in Phase 5 is
what decides whether the destination was reached.

## Phase 5 — Verify (acceptance → simplify → gate)

Three steps, in this order. Simplify is behavior-preserving so it cannot affect
acceptance, and running it after the acceptance loop means corrective code gets
simplified too.

1. **Acceptance (you, the orchestrator).** Holding `SPEC.md` (which the coder never
   saw), verify the build against every condition — read the diff and the tests.
   The coder does not commit, so read the **working tree**, not a commit range:
   ```bash
   git add -N .          # intent-to-add, so newly created files show in the diff
   git diff <base>
   ```
   `git diff <base>...HEAD` is **wrong here**: nothing is committed yet, so it
   reports an empty diff. (Phase 6's PR reviewer does use the three-dot form, and
   is correct to — by then the branch is committed.) Write `.auto-dev/SPEC_EVAL.md`
   (per-condition met / partial / unmet, with evidence). For unmet conditions, send
   the coder back with a **specific** correction brief (translate the condition into
   concrete required behavior; don't quote the spec verbatim), then re-check. This
   **feedback loop into Phase 4** consumes the shared budget; past it,
   stop-and-report the unmet conditions.
   **You** re-run the affected profile `gate` commands yourself (you have Bash) to
   confirm the correction broke nothing. The cleanup agent is spawned **once**,
   after this loop settles, and no correction brings it back. Full protocol:
   `references/correction-loop.md`.
2. **Simplify + 3. Quality gate.** Spawn the cleanup agent: run **`/simplify`** over
   the branch diff (behavior-preserving), then run the profile's `gate` commands
   (from `profile.md`) in order, fixing what they surface, until every command is
   green. Each check writes `.auto-dev/lint/<CHECK>.md` (Elixir: `COMPILE.md`,
   `FORMAT.md`, `CREDO.md`, `DIALYZER.md`, `TEST.md`). If the gate cannot be made
   green, **stop and report** — never ship a red build. Gate fixes consume the
   shared budget.

## Phase 6 — Ship  **[three human gates]**

### 6a — PR  **[gate]**
1. **Gate:** pause for approval to open the PR (`references/gates-and-jira.md`).
2. **Commit** — stage source paths **explicitly** (`git add <paths>`, never
   `-A`/`.`); confirm nothing under `.auto-dev/` is staged. Conventional message
   ending with `Co-Authored-By: Claude Code <noreply@anthropic.com>`.
3. **Push** the branch; **open the PR** with `gh pr create` — body includes the
   spec's conditions as a checklist, a summary, gate results, and unresolved
   assumptions; ends with `Generated with [Claude Code](https://claude.com/claude-code)`.
4. **Adversarial PR Review agent** → `.auto-dev/PR_REVIEW.md` — briefed to *find*
   problems (correctness, security, scope), not rubber-stamp. This is the only
   check briefed to find what no checklist names. Posting inline comments is opt-in.
5. **CI Monitoring** — poll the PR's checks (detected provider) with a bounded
   timeout (`references/gates-and-jira.md`). On red pre-merge the response is a
   corrective loop, not an immediate halt: `references/correction-loop.md`.
6. **Jira → In Review.**

### 6b — Staging  **[gate]**  (skip if no staging branch)
Pause for approval, then **directly merge** the branch into `staging` (no PR — per
project convention) and monitor CI on staging. Skip entirely if the repo has no
staging branch.

### 6c — Main  **[gate]**
Pause for approval, then **merge the PR to main** via `gh pr merge` (respects
branch protection and required reviews — never a local push to main). Monitor CI
on main, transition **Jira → Done**, and offer to remove the worktree (confirmed,
not automatic).

---

## Final report

Summarize: branch/worktree path, PR link(s), what was built, the scope call,
assumptions made, final gate status, Jira transitions performed, remaining
iteration budget, and anything left unresolved. In a multi-PR run, report per
sub-task from `WORK_LOG.md`. Be honest about skipped steps and unmet conditions —
never report success you didn't verify.

## Bounds and guardrails

- **One global iteration budget** (default 4 revise rounds) across all corrective
  loops. Past it, report rather than loop (`references/correction-loop.md`).
- **Stop-and-report conditions:** `gh` is missing, unauthenticated, or `origin`
  isn't GitHub (caught in Phase 1, before any work); the worktree can't be
  created; the task is self-contradictory or impossible as specified; the quality
  gate can't be made green; spec conditions remain unmet after the budget; a
  gate/merge is declined by the user. Leave the work in place and explain.
- **Never weaken security to finish** — no disabled TLS/cert/signature checks, no
  exposed or hardcoded secrets, no real/sensitive data or PII in tests/fixtures.
  Obey the repo's rules and the org security directives. These override "finish
  the task."
- **Never commit `.auto-dev/`.** Make it self-excluding in Phase 1; stage
  explicitly in Phase 6; never `git add -A`/`.` (`references/artifacts.md`).
- **Promotion safety:** main only via `gh pr merge`; staging via direct merge only
  where the project uses that convention.
- **Per-job isolation:** a fresh subagent per delegated job; hand off via
  `.auto-dev/` files + the git tree; give each worker only the inputs its phase
  needs; the coder never sees the spec.
