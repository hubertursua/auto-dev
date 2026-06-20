# auto-dev

A minimal orchestration skill for autonomous development.

It drives a single coding task from spec to pull request hands-off, delegating
each stage to a purpose-built subagent. Project-agnostic: Stage 0 discovers the
repo's own toolchain, quality gate, and conventions at runtime, and every later
stage obeys what was discovered.

## Agent hierarchy

The main agent stays the orchestrator and never writes code itself — it spawns a
fresh subagent per stage and hands off through files in `.auto-dev/`, never
shared memory.

```
Orchestrator (main agent) ── owns the pipeline, holds the spec
│
├─ Stage 1  Spec agent ............ writes specification.md
├─ Stage 2  Plan agent ............ writes implementation-plan.md
├─ Stage 3  Reviewer agent ........ critiques both artifacts  (≤2 rounds)
├─ Stage 4  Coding agent .......... implements + tests (given only the plan)
├─ Stage 5  Cleanup agent ......... runs the quality gate to green
│            └─ code-simplifier agent ... simplifies the diff first
├─ Stage 6  (orchestrator) ........ acceptance review vs. spec
│            └─ Coding agent (re-spawned) ... fixes unmet criteria (≤2 rounds)
└─ Stage 7  (orchestrator) ........ commit + open PR
```

Stages 0, 3, 6, and 7 run in the orchestrator; 1, 2, 4, and 5 are delegated. The
specification is deliberately withheld from the coding agent so Stage 6 is an
independent check by a context that never saw the code being written.

## What it does

Invoke it when you want a whole task taken off your plate and delivered as a
finished PR, hands-off — e.g. *"auto-dev this…"*, *"take it all the way to a
PR"*, *"run the whole dev cycle by yourself"*. The orchestrator runs:

| Stage | Worker | Output |
|-------|--------|--------|
| 0 Setup | orchestrator | discovers repo conventions; creates an isolated git worktree + branch |
| 1 Spec | spec agent | `specification.md` — observable acceptance criteria |
| 2 Plan | plan agent | `implementation-plan.md` — the technical how |
| 3 Critique | reviewer agent | structured findings; orchestrator revises (≤2 rounds) |
| 4 Code | coding agent | implementation + tests, given **only** the plan |
| 5 Polish + Gate | cleanup agent | runs code-simplifier, then the discovered quality gate to green |
| 6 Accept | orchestrator | verifies the build against the spec it withheld (≤2 fix rounds) |
| 7 Ship | orchestrator | commit on the branch + open a PR |

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

Then, in any project, ask Claude to "auto-dev" a task and the skill triggers.

## Dependencies

This plugin orchestrates other agents and skills. It uses the built-in
`TodoWrite`, `Task`/`Agent`, `Bash`, `Read`, `Edit`, `Write`, `Grep`, and `Glob`
tools, plus `gh` on your `PATH` for the PR step. Beyond those it relies on the
following plugins/skills:

| Plugin / skill | Used in | Required? |
|----------------|---------|-----------|
| `code-simplifier` plugin — provides the `code-simplifier:code-simplifier` agent (and skill) | Stage 5 runs it over the diff before the quality gate | **Recommended.** Without it the simplify step is skipped; the rest of the pipeline still runs. |
| `feature-dev` plugin — provides the `feature-dev:feature-dev` skill and the `feature-dev:code-architect` / `feature-dev:code-reviewer` / `feature-dev:code-explorer` agents | Stages 1–2 follow the feature-dev methodology; Stage 3 prefers the `code-reviewer` agent | **Optional.** Stages fall back to full-tool agent types (`claude` / `general-purpose`) when these specialized types aren't installed. |

Both are available in the official Claude Code plugin marketplace
(`claude-plugins-official`). Nothing else is required — the pipeline degrades
gracefully to general-purpose agents when a specialized type is missing.

## Safety

The pipeline is fully autonomous but bounded: critique and acceptance-fix loops
are capped, and it stops and reports rather than committing a red build or
weakening any security control. It never merges or removes the worktree — it
leaves the finished branch in place for you to review.
