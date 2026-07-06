# auto-dev

An orchestration skill for autonomous development.

It drives a single coding task from a ticket to a merged pull request hands-off,
delegating each phase to a purpose-built subagent and handing structured
artifacts between them through a `.auto-dev/` scratch directory. It is
**stack-agnostic** via editable profiles (Elixir ships today), and integrates
optionally with Jira, CI, and a staging branch — each auto-detected and skipped
when absent.

## Agent hierarchy

The main agent stays the orchestrator and never writes code itself — it spawns a
fresh subagent per phase and hands off through files in `.auto-dev/`, never shared
memory. The specification is deliberately withheld from the coding agent so the
acceptance check is made by a context that never saw the code being written.

```
Orchestrator (main agent) ── owns the pipeline, holds the spec, runs the gates
│
├─ Phase 1  Workspace Setup ....... detect repo + stack, resolve ticket, worktree, .auto-dev/
├─ Phase 2  Ticket-analysis agent . TICKET.md + ACCEPTANCE_CRITERIA.md; scoping/decompose
├─ Phase 3  Spec agent → reviewer .. SPEC.md (testable contract)
├─ Phase 4  Plan agent → reviewer .. IMPLEMENTATION.md            [optional gate]
├─ Phase 5  Coding agent (TDD) ..... code + tests (given only the plan) → impl-eval
├─ Phase 6  (orchestrator) ......... acceptance review vs. withheld spec → feedback loop
├─ Phase 7  Cleanup agent .......... simplify + quality gate to green (lint/*.md)
├─ Phase 8  (orchestrator) ......... [GATE] commit + PR + adversarial review + CI monitor
├─ Phase 9  (orchestrator) ......... [GATE] direct merge to staging + CI   (optional)
└─ Phase 10 (orchestrator) ......... [GATE] merge PR to main + CI + Jira Done
```

## What it does

Invoke it when you want a whole task taken off your plate and delivered as a
finished PR, hands-off — e.g. *"auto-dev this…"*, *"take it all the way to a
PR"*, *"pick up JIRA-1234 and ship it"*. The orchestrator runs:

| Phase | Worker | Output |
|-------|--------|--------|
| 1 Workspace Setup | orchestrator | detect repo/stack, load profile, resolve ticket, isolated worktree + branch, `.auto-dev/` |
| 2 Ticket Evaluation | ticket-analysis agent | `TICKET.md`, `ACCEPTANCE_CRITERIA.md`; scoping (decompose oversized tickets) |
| 3 Spec Definition | spec agent + reviewer | `SPEC.md` — the testable contract |
| 4 Impl Planning | plan agent + reviewer | `IMPLEMENTATION.md` — the technical how (optional approval gate) |
| 5 Implementation | coding agent | code + tests given **only** the plan; plan-adherence eval |
| 6 Evaluation | orchestrator | acceptance review vs. the withheld spec; feedback loop to Phase 5 |
| 7 Clean Up | cleanup agent | code-simplifier, then the profile's quality gate to green |
| 8 PR Management | orchestrator | commit + PR + adversarial review + CI monitor (pauses first) |
| 9 Staging Review | orchestrator | direct merge to staging + CI (pauses first; skipped if none) |
| 10 Close Ticket | orchestrator | merge the PR to main + CI + Jira Done (pauses first) |

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
monitored on the PR before merge. See `skills/auto-dev/references/gates-and-jira.md`.

## Decompose & track

If a ticket is too big for one PR, the pipeline alerts you with a proposed
breakdown into ordered sub-tasks, tracks them in `.auto-dev/WORK_LOG.md`, and
(on approval) runs the pipeline per sub-task as separate PRs. `WORK_LOG.md` is
also the resume point if a run is interrupted.

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

Built-in tools: `TodoWrite`, `Task`/`Agent`, `Bash`, `Read`, `Edit`, `Write`,
`Grep`, `Glob`, `AskUserQuestion`, plus `gh` on your `PATH` for PR/merge steps.
Optional integrations: the Atlassian MCP (Jira transitions) and a CI provider CLI.
Beyond those:

| Plugin / skill | Used in | Required? |
|----------------|---------|-----------|
| `code-simplifier` plugin (`code-simplifier:code-simplifier`) | Phase 7 runs it over the diff before the gate | **Recommended.** Without it the simplify step is skipped; the rest still runs. |
| `feature-dev` plugin (`code-reviewer` etc.) | Phases 3–4 prefer its reviewer types | **Optional.** Falls back to full-tool agent types when absent. |

## The `.auto-dev/` scratch directory

Each run creates `.auto-dev/` holding the artifacts phases hand off (see
`skills/auto-dev/references/artifacts.md`). This is scratch, not part of your
project — the pipeline never commits it and adds `.auto-dev/` to the worktree's
`.git/info/exclude` automatically. (Note: a committed `.auto-dev.yml` override
file is separate and is *not* excluded.)

## Safety

Autonomous but bounded: all corrective loops share one iteration budget, and the
pipeline stops and reports rather than committing a red build or weakening any
security control. It merges to main only through a PR and only after your
approval.
