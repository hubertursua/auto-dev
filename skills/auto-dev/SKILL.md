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
merged pull request — using purpose-built subagents for each phase and handing
structured artifacts between them through `.auto-dev/`. You (the main agent) are
the **orchestrator**: you own the pipeline, hold the spec, run the human gates,
and never write implementation code yourself. Each phase runs in its own fresh
subagent so your context stays clean and each worker stays focused on one job.

This skill is **stack-agnostic**. A **stack profile** (see
`references/profiles.md`) supplies the concrete setup and quality-gate commands;
Phase 1 detects the stack, loads the matching `profiles/*.md`, merges in runtime
discovery, and honors a repo-local `.auto-dev.yml` override. The shipped profile
is **Elixir**; unknown stacks fall back to `default.md` + runtime discovery. Add a
stack by dropping in a new profile — no change to this file.

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

## Pipeline at a glance

```
Phase 1  Workspace Setup   → detect repo + stack, resolve ticket, worktree + branch, prep .auto-dev/
Phase 2  Ticket Evaluation → research + acceptance criteria + testability; SCOPING (decompose if oversized)
Phase 3  Spec Definition   → spec agent writes SPEC.md; spec reviewer critiques
Phase 4  Impl Planning     → plan agent writes IMPLEMENTATION.md; plan reviewer critiques   [optional gate]
Phase 5  Implementation    → coder (plan only) + impl-eval (code vs. plan)
Phase 6  Evaluation        → spec-eval (code vs. withheld spec); feedback loop → Phase 5
Phase 7  Clean Up          → simplify + run the profile's quality gate to green
Phase 8  PR Management      → [GATE] commit + push + open PR + adversarial review + CI monitor
Phase 9  Staging Review    → [GATE] direct merge to staging + CI monitor   (skip if no staging)
Phase 10 Close Ticket      → [GATE] merge the PR to main + CI monitor + Jira Done
```

Run phases in order; each depends on the previous. Track them in
`.auto-dev/WORK_LOG.md` (which is also the resume point) and mirror the status in
TodoWrite so progress stays visible.

## Task-orchestration layer (decompose & track)

Before committing to a single-PR run, Phase 2 decides whether the ticket fits one
PR:

- **Fits → single-PR run.** Run Phases 3–10 once. `WORK_LOG.md` records phase
  progress.
- **Too big → alert + decompose.** Propose an ordered set of sub-tasks (with
  dependencies), write them to `WORK_LOG.md`, and **alert the user** with the
  proposed breakdown. On approval, run Phases 3–10 **per sub-task** — each in its
  own branch/worktree with its own `.auto-dev/tasks/<id>/` subtree — respecting
  dependency order and updating the ledger after each. Each sub-task produces its
  own PR.

`WORK_LOG.md` is the single source of truth across a multi-PR run and the resume
point if interrupted — read it first when resuming (`references/artifacts.md`).

## Human gates

This skill runs the planning and build unattended, and **pauses for explicit
approval** (via `AskUserQuestion`) only at these points:

- **Post-plan gate (Phase 4) — OFF by default, enable per run.** If the user asks
  to review before building (or the task is high-risk), pause after
  `IMPLEMENTATION.md` to approve SPEC + plan before any code is written.
- **PR gate (Phase 8).** Pause before opening the PR.
- **Staging gate (Phase 9).** Pause before the direct merge to staging.
- **Main gate (Phase 10).** Pause before merging the PR to main.

Everything else runs without check-ins. Jira status transitions ride along with
these gates (`references/gates-and-jira.md`). Gate scripts and the exact prompts
live in `references/gates-and-jira.md`.

## Global iteration budget

Instead of separate per-loop caps, the pipeline shares **one budget of revise
rounds** (default **4**) across all corrective loops — spec review, plan review,
the Phase 6 → Phase 5 spec-eval feedback loop, and Phase 7 gate fixes. Each
re-spawn or re-run for correction consumes one round. When the budget is
exhausted, **stop and report** what remains rather than looping forever. Record
the remaining budget in `WORK_LOG.md`.

## Tool permissions per agent

Pick an agent type that grants the tools listed. The safe default for any worker
is a full-tool type (`claude` / `general-purpose`, tool set `*`). The trap is a
read-only blueprint/reviewer type (`feature-dev:code-architect`,
`feature-dev:code-reviewer`): **no Write/Edit/Bash**, so it cannot create
artifacts, implement, or run the gate. **Never spawn the coder or cleanup worker
with a read-only type** — it will silently fail.

- **Orchestrator (you):** TodoWrite, Bash (git/gh/CI, worktree, setup), Read,
  Edit (revise artifacts after critique), Write (`WORK_LOG.md`, `profile.md`), the
  Agent/Task tool (spawn every worker), AskUserQuestion (gates), and the Atlassian
  MCP Jira tools when a ticket is present.
- **Ticket-analysis agent (Phase 2):** Write + Read, Grep, Glob (research is
  read-only; it writes `TICKET.md` / `ACCEPTANCE_CRITERIA.md`).
- **Spec agent (Phase 3):** Write + Read, Grep, Glob.
- **Spec reviewer (Phase 3):** Read, Grep, Glob only.
- **Plan agent (Phase 4):** Write + Read, Grep, Glob.
- **Plan reviewer (Phase 4):** Read, Grep, Glob only.
- **Coding agent (Phase 5):** Read, Write, Edit, Bash, Grep, Glob.
- **Cleanup agent (Phase 7):** Read, Edit, Write, Bash, plus a way to run
  code-simplifier (Skill tool, or spawn `code-simplifier:code-simplifier`).
- **PR reviewer (Phase 8):** Read, Grep, Glob, Bash (`git diff`, `gh`) — read-only
  w.r.t. source; writes `PR_REVIEW.md`.

Per-phase isolation: hand each worker the worktree path, `profile.md`, and only
the inputs its phase needs. The coder gets the **plan only, never the spec** — the
independence is what makes Phase 6 a real check.

---

## Phase 1 — Workspace Setup

Deterministic, run by the orchestrator.

1. **Detect the repo & branches.** Canonical repo name from the git remote
   (`basename -s .git "$(git remote get-url origin)"`); default branch via
   `gh repo view --json defaultBranchRef`. Resolve `base`, `staging` (optional),
   and branch `prefix` — from `.auto-dev.yml` if present, else conventional
   defaults. If there is no `staging` branch, mark Phase 9 as N/A.
2. **Detect the stack & load the profile.** Match `detect` signals
   (`references/profiles.md`) → load `profiles/<stack>.md`, else `default.md` +
   runtime discovery. Merge in repo-doc/CI discovery, apply `.auto-dev.yml`.
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
   Then run the profile's `setup` commands. Derive `<slug>` from the ticket/task.
6. **Prep `.auto-dev/`** and exclude it from git (see `references/artifacts.md`):
   ```bash
   mkdir -p .auto-dev
   echo ".auto-dev/" >> .git/info/exclude
   ```
7. **Write `.auto-dev/profile.md`** (fully-resolved profile) and initialize
   `.auto-dev/WORK_LOG.md`.
8. **Jira → In Progress** (if a ticket exists), confirmed with the user as part of
   starting work (`references/gates-and-jira.md`).

All later phases run **inside the worktree directory**.

## Phase 2 — Ticket Evaluation + Scoping

Spawn **one** ticket-analysis agent (brief in `references/subagent-prompts.md`)
that, in a single pass: researches the ticket against the codebase, drafts the
**acceptance criteria** (what the ticket asks, stakeholder view), and assesses
**testability** (can each criterion be observed/tested; flag gaps). It writes
`TICKET.md` and `ACCEPTANCE_CRITERIA.md`.

Then run the **scoping check**: does this fit one PR? Estimate by subsystems
touched, independent deliverables, and rough file count. If it's oversized,
enter the **decompose & track** path (above) — alert the user and populate
`WORK_LOG.md` — before proceeding to Phase 3.

## Phase 3 — Spec Definition

From `ACCEPTANCE_CRITERIA.md`, produce the **testable contract**:

1. **Problem Breakdown** (orchestrator) — frame the problem for the spec agent.
2. **Spec Writing agent** → `.auto-dev/SPEC.md` — observable, testable conditions;
   an `Assumptions` section; a `Security/Compliance criteria` section for
   sensitive paths.
3. **Spec Review agent** (read-only) → critique. Apply fixes yourself (you have
   the context); re-review only if blockers remain. Consumes the shared iteration
   budget.

Hold `SPEC.md` — you withhold it from the coder and use it for Phase 6.

## Phase 4 — Implementation Planning

1. **Impl Writing agent** → `.auto-dev/IMPLEMENTATION.md` — the self-contained
   technical plan; every acceptance criterion maps to a step and a test. Reads
   `SPEC.md`.
2. **Impl Review agent** (read-only) → critique; apply fixes; re-review if
   blockers. Consumes the shared budget.
3. **Optional post-plan gate** — if enabled for this run, pause here for the user
   to approve `SPEC.md` + `IMPLEMENTATION.md` before any code is written.

## Phase 5 — Implementation

1. **Steps Breakdown** → `.auto-dev/CODING_TODO.md` — the ordered, checkable task
   list from the plan.
2. **Coding agent (TDD)** — spawn with **only the plan + CODING_TODO, never the
   spec**. Implements code and tests, runs the relevant tests as it goes.
3. **Impl-Eval agent** → `.auto-dev/IMPLEMENTATION_EVAL.md` — checks the code
   against `IMPLEMENTATION.md` (plan adherence). Blockers feed back to the coder
   under the shared budget.

## Phase 6 — Evaluation (acceptance)

**You (the orchestrator)**, holding `SPEC.md` (which the coder never saw), verify
the build against every acceptance criterion — read the diff
(`git diff <base>...HEAD`) and the tests. Write `.auto-dev/SPEC_EVAL.md`
(per-criterion met / partial / unmet, with evidence). For unmet criteria, send the
coder back with a **specific** correction brief (translate the criterion into
concrete required behavior; don't quote the spec verbatim), then re-check. This
**feedback loop into Phase 5** consumes the shared budget; past it, stop-and-report
the unmet criteria.

## Phase 7 — Clean Up (quality gate)

Spawn the cleanup agent: first run **code-simplifier** over the branch diff
(behavior-preserving), then run the profile's `gate` commands (from `profile.md`)
in order, fixing what they surface, until every command is green. Each check
writes `.auto-dev/lint/<CHECK>.md` (Elixir: `COMPILE.md`, `FORMAT.md`, `CREDO.md`,
`DIALYZER.md`, `TEST.md`). If the gate cannot be made green, **stop and report** —
never ship a red build. Gate fixes consume the shared budget.

## Phase 8 — PR Management  **[human gate]**

1. **Gate:** pause for approval to open the PR (`references/gates-and-jira.md`).
2. **Commit** — stage source paths **explicitly** (`git add <paths>`, never
   `-A`/`.`); confirm nothing under `.auto-dev/` is staged. Conventional message
   ending with `Co-Authored-By: Claude Code <noreply@anthropic.com>`.
3. **Push** the branch; **open the PR** with `gh pr create` — body includes the
   acceptance criteria as a checklist, a summary, gate results, and unresolved
   assumptions; ends with `Generated with [Claude Code](https://claude.com/claude-code)`.
4. **Adversarial PR Review agent** → `.auto-dev/PR_REVIEW.md` — briefed to *find*
   problems (correctness, security, scope), not rubber-stamp. Posting inline
   comments is opt-in.
5. **CI Monitoring** — poll the PR's checks (detected provider) with a timeout and
   an on-red policy (surface + stop); see `references/gates-and-jira.md`.
6. **Jira → In Review.**

## Phase 9 — Staging Review  **[human gate]**  (skip if no staging branch)

Pause for approval, then **directly merge** the branch into `staging` (no PR — per
project convention) and monitor CI on staging. Skip entirely if the repo has no
staging branch.

## Phase 10 — Close Ticket  **[human gate]**

Pause for approval, then **merge the PR to main** via `gh pr merge` (respects
branch protection and required reviews — never a local push to main). Monitor CI
on main, transition **Jira → Done**, and offer to remove the worktree (confirmed,
not automatic).

---

## Final report

Summarize: branch/worktree path, PR link(s), what was built, assumptions made,
final gate status, Jira transitions performed, remaining iteration budget, and
anything left unresolved. In a multi-PR run, report per sub-task from
`WORK_LOG.md`. Be honest about skipped steps and unmet criteria — never report
success you didn't verify.

## Bounds and guardrails

- **One global iteration budget** (default 4 revise rounds) across all corrective
  loops. Past it, report rather than loop.
- **Stop-and-report conditions:** worktree can't be created; task is
  self-contradictory or impossible as specified; the quality gate can't be made
  green; acceptance criteria remain unmet after the budget; a gate/merge is
  declined by the user. Leave the work in place and explain.
- **Never weaken security to finish** — no disabled TLS/cert/signature checks, no
  exposed or hardcoded secrets, no real/sensitive data or PII in tests/fixtures.
  Obey the repo's rules and the org security directives. These override "finish
  the task."
- **Never commit `.auto-dev/`.** Exclude it in Phase 1; stage explicitly in
  Phase 8; never `git add -A`/`.` (`references/artifacts.md`).
- **Promotion safety:** main only via `gh pr merge`; staging via direct merge only
  where the project uses that convention.
- **Per-phase isolation:** fresh subagent per phase; hand off via `.auto-dev/`
  files + the git tree; give each worker only the inputs its phase needs; the
  coder never sees the spec.
