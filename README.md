# auto-dev

An orchestration skill for autonomous development.

It drives a single coding task from a ticket to a merged pull request hands-off,
delegating each job to a purpose-built subagent and handing structured
artifacts between them through a `.auto-dev/` scratch directory. It is
**stack-agnostic** via editable profiles (Elixir ships today), and integrates
optionally with Jira, CI, and a staging branch — each auto-detected and skipped
when absent.

## Agent hierarchy

The main agent stays the orchestrator and never writes code itself — it spawns a
fresh subagent per delegated job and hands off through files in `.auto-dev/`,
never shared memory. Phase 1 and the Phase 5 acceptance check are its own work.

```
Orchestrator (main agent) ── owns the pipeline, holds the spec, runs the human gates
│
├─ Phase 1  Setup ......... detect repo + stack, resolve ticket, worktree, .auto-dev/
├─ Phase 2  Define agent .. SPEC.md — the testable contract + SCOPE CALL  (→ reviewer)
├─ Phase 3  Plan → reviewer IMPLEMENTATION.md — the technical how         [optional gate]
├─ Phase 4  Coding agent .. code + tests (given only the plan)
├─ Phase 5  orch + cleanup  acceptance vs. the withheld spec → /simplify → quality gate
└─ Phase 6  orch + reviewer  [GATE] PR + adversarial review + CI → [GATE] staging → [GATE] main
```

Two documents describe the work, and they answer different questions: `SPEC.md`
asks *did we build the right thing*, `IMPLEMENTATION.md` asks *did we build it the
way we decided*. They fail independently — a plan executed faithfully can still
miss the outcome — so the pipeline checks both.

The coder builds from the plan, never the contract. The plan is *required* to
cover every condition, so this isn't information-hiding — it's **language**-hiding:
the coder can't satisfy the acceptance check by echoing the contract's own wording
back in a test name. The check is independent because the context that runs it
didn't write the code.

## What it does

Invoke it when you want a whole task taken off your plate and delivered as a
finished PR, hands-off — e.g. *"auto-dev this…"*, *"take it all the way to a
PR"*, *"pick up JIRA-1234 and ship it"*. The orchestrator runs:

| Phase | Worker | Output |
|-------|--------|--------|
| 1 Setup | orchestrator | detect repo/stack, load profile, resolve ticket, isolated worktree + branch, `.auto-dev/` |
| 2 Define | Define agent + reviewer | `SPEC.md` — context, testable conditions, assumptions, security criteria; plus the **scope call** |
| 3 Plan | plan agent + reviewer | `IMPLEMENTATION.md` — the technical how (optional approval gate) |
| 4 Build | coding agent | code + tests given **only** the plan |
| 5 Verify | orchestrator, then cleanup agent | acceptance review vs. the withheld spec (feedback loop to Phase 4), then `/simplify` + the profile's quality gate to green |
| 6 Ship | orchestrator + PR review agent | commit + PR + adversarial review + CI, then staging, then main + Jira Done — pausing at each |

## Scope call: the pipeline sizes itself to the task

Phase 2 returns one of three calls, and the pipeline adapts:

- **TRIVIAL** — one subsystem, one behavior, no new abstraction or interface, no
  migration or config change, and an existing test file covers it. The Define review and the Phase 3 agents are skipped; the
  orchestrator writes a short plan itself. **4 subagent roles.**
- **STANDARD** — the full path. **7 subagent roles.** (Roles, not spawns —
  a correction round re-spawns a worker.)
- **OVERSIZED** — too big for one PR: you get a proposed breakdown into ordered
  sub-tasks, tracked in `.auto-dev/WORK_LOG.md`, and on approval the pipeline runs
  per sub-task as separate PRs. Each sub-task gets its *own* scope call, so the
  cost is **1 role for the parent Define, then 4 or 7 per sub-task** depending on
  how each one sizes up.

**The scope call thins the planning head, never the verification tail.** Phase 5
and Phase 6 run identically at every scope — skipping planning on a small change
is cheap, skipping verification is how a small change ships broken.

`WORK_LOG.md` is also the resume point if a run is interrupted.

## Stack profiles

The pipeline is language/framework-agnostic. A **profile** (`skills/auto-dev/profiles/`)
declares how a stack installs and what its quality gate is; Phase 1 detects the
stack, loads the profile, merges in runtime discovery, and honors a repo-local
`.auto-dev.yml` override. Shipped: **Elixir** (`mix compile`/`format`/`credo`/
`dialyzer`/`test`) plus a generic `default` fallback that discovers commands at
runtime. Add a stack by dropping in `profiles/<stack>.md` — no skill change. See
`skills/auto-dev/references/profiles.md`.

## Human gates & integrations

Planning and build run unattended; the pipeline pauses for approval before
**opening the PR**, before the **staging merge**, and before the **main merge**
(plus an optional post-plan gate you can enable per run). Main is merged only via
`gh pr merge` (respecting branch protection); staging is a direct merge where the
project uses that convention. **Jira** integration is status-transitions-only
(In Progress → In Review → Done) and is skipped if no ticket is given. **CI** is
monitored on the PR before merge, and again after the staging and main merges to
confirm the merge itself didn't break the branch. See `skills/auto-dev/references/gates-and-jira.md`.

## Install

Add this repo as a marketplace, then install the plugin. From GitHub:

```
/plugin marketplace add hubertursua/auto-dev
/plugin install auto-dev@auto-dev-marketplace
```

Or from a local clone, point at the directory that contains `.claude-plugin/`:

```
/plugin marketplace add ./auto-dev
/plugin install auto-dev@auto-dev-marketplace
```

As a safeguard, add the scratch directory to each project's `.gitignore` so its
planning artifacts can never be committed:

```
echo ".auto-dev/" >> .gitignore
```

Now ask Claude to "auto-dev" a task and the skill triggers.

## Dependencies

Built-in tools only — no plugins required: `TodoWrite`, `Task`/`Agent`, `Bash`,
`Read`, `Edit`, `Write`, `Grep`, `Glob`, `AskUserQuestion`, and the `Skill` tool
(the Phase 5 cleanup agent runs `/simplify` with it). `gh` must be on your `PATH`
and authenticated: Phase 1 checks, and stops before doing any work if it isn't.
Optional integrations: the Atlassian MCP (Jira transitions) and a CI provider
CLI.

A note on agent types: `feature-dev`'s `code-reviewer` / `code-architect` types
look like a natural fit for the two read-only reviewers, but they pin
`model: sonnet`, which breaks the skill's invariant that **every worker inherits
your model**. Use a full-tool type (`claude` / `general-purpose`) everywhere and
constrain the reviewers by their brief instead — which is what the briefs already
do ("Do NOT rewrite the file. Return findings only.").

## The `.auto-dev/` scratch directory

Each run creates `.auto-dev/` holding the artifacts phases hand off (see
`skills/auto-dev/references/artifacts.md`). This is scratch, not part of your
project — the pipeline never commits it and makes the directory self-ignoring (a
`.gitignore` containing `*`, written into `.auto-dev/` itself) automatically, so
it cannot be staged even by a stray `git add -A`. (Note: a committed
`.auto-dev.yml` override file is separate and is *not* excluded.)

## Safety

Autonomous but bounded: all corrective loops share one iteration budget, and the
pipeline stops and reports rather than committing a red build or weakening any
security control. It merges to main only through a PR and only after your
approval.

## Upgrading from 2.x

3.0 restructures the pipeline from ten phases to six and changes the artifact set:
`TICKET.md` and `ACCEPTANCE_CRITERIA.md` are merged into `SPEC.md`,
`CODING_TODO.md` is dropped (the plan's build sequence is the coder's worklist),
and `IMPLEMENTATION_EVAL.md` is dropped along with the plan-adherence check. A run
started on 2.x cannot be resumed on 3.0 — its `.auto-dev/` and its `WORK_LOG.md`
phase table won't match. Finish in-flight runs before upgrading.
