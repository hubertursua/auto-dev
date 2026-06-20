---
name: auto-dev
description: >-
  Use this when the user wants you to take an entire coding task off their plate
  — implement a whole feature or fix and deliver it as a finished pull request,
  working autonomously without check-ins. It's the right call whenever someone
  asks you to BUILD something AND ship the PR yourself in one pass: "do it
  autonomously", "by yourself", "you do it", "raise/open the PR", "take it all
  the way", "from idea/spec to PR", "run the whole dev cycle", "knock it out",
  "make the calls on anything ambiguous", "don't make me babysit each step", or
  an explicit "auto-dev …". Prefer this over ordinary guided feature-development
  help whenever the user wants the full plan → build → test → ship pipeline run
  hands-off, not one supervised step. Do NOT use it for a single slice of that
  work: running or fixing one test/lint/type error, critiquing a plan,
  explaining how code works, or answering a question. Choose it only when they
  clearly want the whole task carried autonomously to a PR on their behalf.
---

# auto-dev

Drive a single task through the entire development lifecycle autonomously, using
purpose-built subagents for each stage and handing structured artifacts between
them. The orchestrator (you, the main agent) owns the pipeline; each stage runs
in its own subagent so the main context stays clean and each worker stays
focused on one job.

This skill is **project-agnostic**. It does not assume any particular language,
framework, or toolchain. Instead, Stage 0 discovers the repo's own conventions —
how it builds, tests, and lints; its branching and PR norms; its security and
contribution rules — and every later stage is told to obey what was discovered.

### Tool permissions per agent

Each agent in this pipeline needs specific tools to do its job. When spawning a
subagent, pick an agent type that grants the tools listed below. The simplest
safe choice for every worker is a full-tool type (`claude` / `general-purpose`,
whose tool set is `*`). The narrow specialized types are the trap: read-only
blueprint/reviewer types (for example `feature-dev:code-architect` and
`feature-dev:code-reviewer`) have **no Write, Edit, or Bash**, so they cannot
create artifacts, implement code, or run the gate. **Never spawn the coding or
polish worker with a read-only blueprint/reviewer type** — they will silently
fail to do their job.

- **Main agent (orchestrator — you):** **TodoWrite** (track the pipeline stages
  so progress stays visible), **Bash** (Stage 0 `git worktree` + toolchain
  setup; Stage 6 `git diff`; Stage 7 `git`/`gh`), **Read** (read the artifacts
  and the diff), **Edit** (Stage 3 — you revise the two artifacts to apply
  critique), and the **Agent/Task** tool (spawn the worker for every stage).
- **Spec agent (Stage 1):** **Write** (creates `.auto-dev/specification.md`) plus
  read-only discovery — **Read, Grep, Glob**.
- **Implementation plan agent (Stage 2):** **Write** (creates
  `.auto-dev/implementation-plan.md`) plus **Read, Grep, Glob** to read the spec
  and explore the codebase.
- **Reviewer (Stage 3):** **Read, Grep, Glob** only — it returns findings and is
  explicitly told *not* to rewrite the files, so it needs no Write/Edit.
- **Coding agent (Stage 4):** **Read, Write, Edit, Bash, Grep, Glob** — Edit to
  implement and Bash to run tests as it goes are both essential.
- **Polish agent (Stage 5):** **Read, Edit, Write, Bash** — the quality gate is
  all shell (the commands discovered in Stage 0) — plus a way to run
  code-simplifier: either the **Skill** tool, or the **Agent/Task** tool to spawn
  the `code-simplifier:code-simplifier` agent (whose tool set is `*`).

This skill is **fully autonomous**: it does not pause for user approval between
stages. It stops early only when it is genuinely blocked (e.g. the task is
self-contradictory, the worktree can't be created, or the quality gate cannot be
made green after the bounded retries) — and then it reports clearly what it tried
and why it stopped.

The project's own rules are binding on every change this pipeline makes.
Whatever conventions, security constraints, and Definition-of-Done you discover
in Stage 0 (from `CLAUDE.md`, `CONTRIBUTING`, coding-guideline docs, linter
configs, etc.) must be passed into every worker's brief and obeyed. Never weaken
a security control or hardcode a secret to make the task finish.

## Pipeline at a glance

```
Stage 0  Setup        → discover repo conventions; create worktree + branch; prep .auto-dev/
Stage 1  Spec         → spec agent (with Write) writes specification.md
Stage 2  Plan         → plan agent (with Write) writes implementation-plan.md from the spec
Stage 3  Critique     → reviewer agent critiques both; orchestrator revises (≤2 rounds)
Stage 4  Code         → coding agent implements + tests, given ONLY the plan
Stage 5  Polish+Gate  → simplifier agent runs code-simplifier, then the quality gate green
Stage 6  Accept       → orchestrator checks build against specification.md (≤2 fix rounds)
Stage 7  Ship         → commit on the branch, open a PR
```

Run the stages in order; each depends on the previous. Track them with TodoWrite
so progress is visible.

---

## Stage 0 — Discover conventions, then set up the isolated worktree

**First, discover how this repo works.** You will pass these findings into every
later worker, so the pipeline adapts to the project instead of assuming a
toolchain. Read what the repo tells you and record a short "project profile":

- **Conventions & rules:** read `CLAUDE.md`/`AGENTS.md` if present, plus
  `README`, `CONTRIBUTING`, and any coding-guideline / architecture / security
  docs you find. These define the binding constraints, the Definition-of-Done,
  and the branch/PR norms.
- **Toolchain & dependency setup:** detect the ecosystem from manifest and
  version files (e.g. `package.json`, `pyproject.toml`/`requirements.txt`,
  `go.mod`, `Cargo.toml`, `Gemfile`, `pom.xml`/`build.gradle`, `mix.exs`,
  `composer.json`) and any version pin (`.tool-versions`, `.nvmrc`, `mise.toml`,
  `.python-version`). Note the install command (e.g. `npm ci`, `pnpm install`,
  `uv sync`, `poetry install`, `go mod download`, `bundle install`, `mix
  deps.get`) and any toolchain activation step (`mise install`, `nvm use`, etc.).
- **Quality gate:** find the commands that constitute "done" — test, lint,
  format-check, type-check, build. Look in CI configs (`.github/workflows`,
  `.gitlab-ci.yml`), `Makefile`/`Justfile`/`Taskfile`, `package.json` scripts,
  `pre-commit` config, or a documented precommit/check command. Prefer an
  aggregate command the repo already defines (e.g. `make check`, `npm run
  verify`, `mix precommit`) and add the separately-run checks it omits.
- **Test scope hints:** note anything that affects how tests run — a required
  database/service, a monorepo with per-package suites, fast vs. slow tiers — so
  the coding and polish workers run the right scope.

If a check genuinely can't be determined, prefer the conventional default for
the detected ecosystem and record the assumption rather than skipping verification.

**Then create an isolated worktree.** Every task gets its own git worktree on its
own branch — never work on the repo's default branch.

1. Derive a short, descriptive slug from the task (e.g. `link-expiry-validation`).
   Pick the branch prefix by intent: `feature/`, `fix/`, `chore/`, `refactor/`
   (or match the repo's own convention if it differs).
2. From the repo root, create a sibling worktree named for the repo and slug,
   then run the discovered setup:
   ```bash
   git worktree add ../<repo-name>-<slug> -b <prefix>/<slug>
   cd ../<repo-name>-<slug>
   # run the toolchain-activation + dependency-install commands discovered above
   ```
3. Create an artifacts directory the pipeline uses to hand off between stages:
   ```bash
   mkdir -p .auto-dev
   ```
   **Never commit anything under `.auto-dev/`** — it holds planning scratch
   (the spec and plan handed between stages), not shippable code, and must never
   appear in a commit, a diff you stage, or a PR. Add it to the worktree's
   `.git/info/exclude` immediately so it can't be staged even by `git add -A`:
   ```bash
   echo ".auto-dev/" >> .git/info/exclude
   ```
   This is belt-and-suspenders: the exclude entry enforces it mechanically, and
   the Stage 7 staging step must still add files explicitly rather than blanket
   `git add`.

All remaining stages run **inside the worktree directory.** Subagents you spawn
should be told the worktree path explicitly so they operate in the right tree,
and should be handed the project profile from this stage.

---

## Stage 1 — Specification (spec agent)

Spawn one subagent to write the acceptance criteria. It follows the
**feature-dev skill's methodology** — explore the codebase enough to write
accurate, testable criteria — and operates autonomously: never wait for user
input, resolve every ambiguity with an explicit, recorded assumption instead of
asking.

**Tools:** spawn it with an agent type that grants the **Write** tool (e.g.
`claude` / `general-purpose`), because it creates `.auto-dev/specification.md`.
Do not use an agent type that lacks Write — a read-only blueprint agent (e.g.
`feature-dev:code-architect`, which has no Write tool) cannot produce the
artifact and the stage will silently fail.

```
You are the SPECIFICATION stage of an autonomous dev pipeline. Work entirely
inside the worktree at <abs-path>. Do NOT modify any source code. Do NOT ask the
user anything — this is non-interactive; resolve every ambiguity yourself and
record the assumption.

Task: <the user's task, verbatim>

Project profile (from Stage 0): <conventions docs, security/contribution rules,
relevant constraints>. Read those convention docs first — their constraints are
binding. Explore the relevant code (find similar features, map the architecture)
enough to write accurate, testable criteria.

Write exactly one file:

.auto-dev/specification.md — the ACCEPTANCE CRITERIA only. Observable, testable
conditions that define "this works," in plain language. NO technical design, no
file names, no function signatures. Include an "Assumptions" section for every
ambiguity you resolved. If the task touches a sensitive path (auth, data
handling, payments, access control, anything the repo's guidelines flag), add a
"Security/Compliance criteria" section pulling the relevant controls from the
repo's own security/compliance docs.

Return a short summary: the slug, the assumptions you made, and the key risks.
```

After it returns, read `specification.md` yourself — you hold it as the
independent check for Stage 6, and you pass it to the Stage 2 plan agent.

---

## Stage 2 — Implementation plan (plan agent)

Spawn a second subagent to turn the specification into the technical plan. This
stage **depends on Stage 1**: the plan agent reads `.auto-dev/specification.md`
and designs to it, so every acceptance criterion maps to concrete plan steps and
tests. It follows the **feature-dev skill's discovery approach** and operates
autonomously, recording assumptions instead of asking.

**Tools:** spawn it with an agent type that grants the **Write** tool (e.g.
`claude` / `general-purpose`), because it creates
`.auto-dev/implementation-plan.md`. The same read-only caveat as Stage 1 applies.

```
You are the IMPLEMENTATION-PLAN stage of an autonomous dev pipeline. Work
entirely inside the worktree at <abs-path>. Do NOT modify any source code. Do NOT
ask the user anything — this is non-interactive; resolve every ambiguity yourself
and record the assumption.

Task: <the user's task, verbatim>

Read .auto-dev/specification.md — your plan must satisfy every acceptance
criterion in it. Then read the project's convention docs (<from Stage 0>) — the
security constraints and the Definition-of-Done gate (<the discovered quality-gate
commands>) are binding. Explore the relevant code (use the feature-dev skill's
discovery approach: find similar features, map the architecture, identify the
files you'll touch) before designing.

Write exactly one file:

.auto-dev/implementation-plan.md — the technical HOW, sufficient to implement
from on its own. Include: files to create/modify (paths), the design
(modules/functions/data structures), data flow, the build sequence in order, the
test plan (which tests prove which behavior, and where they live), and any
migration/config. It must be self-contained: a competent engineer who has NOT
seen the acceptance criteria should be able to build the right thing from this
plan alone. Ensure every acceptance criterion in the spec maps to a plan step and
a test.

Return a short summary: the slug, the assumptions you made, and the key risks.
```

After it returns, read `implementation-plan.md` yourself as well.

---

## Stage 3 — Critique the plans (reviewer agent)

Spawn a reviewer subagent to critique **both** artifacts and return structured
feedback. **Tools:** read-only is correct here (it must not rewrite the files) —
spawn it as `feature-dev:code-reviewer` if available, else `claude`; **Read,
Grep, Glob** are all it needs. Brief:

```
You are the PLAN-REVIEW stage. Read these two files in the worktree at <abs-path>:
.auto-dev/specification.md and .auto-dev/implementation-plan.md. Also read the
project's convention docs (<from Stage 0>) for the binding constraints.

Critique against these criteria and return findings grouped by severity
(blocker / should-fix / nit):
- Specification: Are the acceptance criteria observable and testable? Is it free
  of technical leakage (no design detail masquerading as a requirement)? Are the
  assumptions reasonable and the security/compliance criteria complete for what
  the task touches?
- Implementation plan: Is it complete and self-contained (buildable without the
  spec)? Does every acceptance criterion in the spec map to something in the
  plan AND to a test? Does it follow repo conventions and the project's security
  constraints? Are there correctness, security, or scope risks? Is anything
  over-engineered for the task?
- Coverage gap: list any acceptance criterion with no corresponding plan step or
  test, and any plan step that doesn't trace back to a criterion.

Do not rewrite the files. Return the findings only.
```

Apply the feedback yourself by editing the two artifacts (you have the context;
this is faster than re-spawning the planner). Re-run the reviewer if a round
surfaced blockers. **Cap at 2 critique rounds.** If blockers remain after 2
rounds, record the unresolved items in the plan and proceed — note them in the
final report rather than looping forever.

---

## Stage 4 — Implementation (coding agent)

Spawn the coding subagent with **only the implementation plan plus minimal
operating instructions — never the specification.** The plan is the contract;
withholding the spec keeps this worker focused on building exactly what was
designed, and ensures the Stage 6 acceptance check is made by a context that
didn't write the code — that independence is the whole point of splitting spec
from plan.

**Tools:** this worker must implement code and run tests, so it needs a full-tool
type (`claude` / `general-purpose`): **Read, Write, Edit, Bash, Grep, Glob**.
Never use a read-only blueprint/reviewer type (`feature-dev:code-architect` /
`code-reviewer` have no Edit or Bash) — it cannot write code or run the tests.

```
You are the IMPLEMENTATION stage. Work inside the worktree at <abs-path>.

Implement the change described in .auto-dev/implementation-plan.md. Read that
file and follow it. Read the project's convention docs (<from Stage 0>) and obey
them — follow the repo's security and coding guidelines, never log or expose
sensitive data, never hardcode secrets, and use synthetic/test data only.

Build the code AND the tests called for in the plan's test plan. Follow existing
codebase conventions and abstractions closely. Run the relevant tests as you go
and get them passing (test command: <from Stage 0>; test-scope hints: <from
Stage 0>). Do not open a PR or commit — just leave the working tree with the
change implemented.

Return a summary: files created/modified, tests added, anything in the plan you
could not do and why.
```

Pass the Stage 0 test-scope hints into the brief so the worker runs the right
scope (e.g. a required database/service, or a single package's suite in a
monorepo) instead of guessing.

---

## Stage 5 — Simplify + quality gate (cleanup agent)

Spawn one subagent to do the cleanup-and-verify pass. It first simplifies, then
drives the Definition-of-Done gate to green.

**Tools:** the whole quality gate is shell, so this worker needs a full-tool type
(`claude` / `general-purpose`): **Read, Edit, Write, Bash**, plus a way to run
code-simplifier — the **Skill** tool, or the **Agent/Task** tool to spawn the
`code-simplifier:code-simplifier` agent. Never a read-only type — it cannot run
the gate commands.

```
You are the POLISH + QUALITY-GATE stage. Work inside the worktree at <abs-path>.

Step 1 — Simplify: Run the code-simplifier skill (the code-simplifier agent) over
the code changed on this branch (diff against the base branch). Apply
simplifications that preserve behavior — clarity, DRY, removing dead/over-built
code. Do not change what the code does.

Step 2 — Quality gate (the project's Definition of Done, from Stage 0). Run each
of these and make them clean, fixing issues you introduced or surfaced:
  <the discovered quality-gate commands, e.g. test / lint / format-check /
  type-check / build — list them explicitly here>
Re-run until every gate command is green. If a warning must be suppressed,
suppress it as narrowly as possible and explain why.

Heads-up on tests (from Stage 0): <test-scope hints — required services, monorepo
scope, slow tiers>. Make sure any prerequisite is available before running the
suite.

Return: what you simplified, and the final status of each gate command (with the
tail of any output you had to fix).
```

If the gate cannot be made green (e.g. a type/lint error that traces to a genuine
design problem in the plan), stop the pipeline and report — do not commit a red
build.

---

## Stage 6 — Acceptance review against the specification

Now the specification earns its keep. **You (the orchestrator)** — holding
`specification.md`, which the coding agent never saw — verify the implemented
change against every acceptance criterion. Read the diff (`git diff
<base-branch>...HEAD`) and the tests, and check each criterion is actually
satisfied, including the security/compliance criteria.

For any criterion that is unmet or only partially met, send the coding agent back
with a **specific** correction brief — name the failing criterion in implementation
terms (not by quoting the spec verbatim; translate it into concrete required
behavior), point at the relevant files, and have it fix and re-test. After it
returns, re-run the relevant part of the Stage 5 gate, then re-check.

**Cap at 2 fix rounds.** If criteria remain unmet after 2 rounds, stop and report
exactly which acceptance criteria are unsatisfied and what was tried.

---

## Stage 7 — Ship (commit + PR)

When the gate is green and the acceptance review passes:

1. Stage **only the source changes** the pipeline produced — name the paths
   explicitly (`git add <paths>`); never blanket-stage with `git add -A`/`.`,
   which would sweep in `.auto-dev/`. Before committing, confirm nothing under
   `.auto-dev/` is staged (`git status` should show none). Then commit on the
   feature branch with a clear, conventional message (match the repo's
   commit-message style). End the commit body with:
   ```
   Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
   ```
2. Push the branch and open a pull request with `gh`. The PR body should include
   the **acceptance criteria as a checklist** (from `specification.md`), a short
   summary of the approach, the gate results, and any unresolved assumptions or
   risks. Follow the repo's PR template if it has one. End the PR body with:
   ```
   🤖 Generated with [Claude Code](https://claude.com/claude-code)
   ```
   If there is no remote or `gh` isn't configured, commit locally and report that
   the PR step was skipped and why.

Leave the worktree in place for the user to review — don't merge, and don't remove
the worktree.

---

## Final report

Summarize for the user: the branch/worktree path, the PR link (or why it was
skipped), what was built, the assumptions made during planning, the final gate
status, and anything left unresolved. Be honest about skipped steps or unmet
criteria — never report success you didn't verify.

## Bounds and guardrails

- **Bounded loops.** Critique ≤2 rounds, acceptance-fix ≤2 rounds. Past the cap,
  report rather than loop.
- **Stop-and-report conditions:** worktree can't be created; the task is
  self-contradictory or impossible as specified; the quality gate can't be made
  green; acceptance criteria remain unmet after the fix cap. In each case, leave
  the work in place and explain.
- **Never** weaken security to make it pass — no disabled TLS/cert/signature
  checks, no exposed secrets or credentials, no real/sensitive data or PII in
  tests or fixtures, no hardcoded secrets. These override "finish the task."
- **Per-stage isolation:** spawn a fresh subagent per stage, hand off through
  `.auto-dev/` files and the git tree, and give each worker the worktree path,
  the Stage 0 project profile, and only the inputs its stage needs.
- **Never commit `.auto-dev/`.** It is pipeline scratch, not shippable code. It
  must never land in a commit, a staged diff, or a PR — in this repo or any repo
  the pipeline runs against. Exclude it in Stage 0 and stage paths explicitly in
  Stage 7 (never `git add -A`/`.`).
