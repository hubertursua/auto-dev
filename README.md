# auto-dev

An orchestration skill for autonomous development.

It drives a single coding task from a ticket to a merged pull request hands-off,
delegating each job to a purpose-built **worker** (a subagent) and handing
structured artifacts between them through a `.auto-dev/` scratch directory. It is
**stack-agnostic** via editable profiles (Elixir ships today), and integrates
optionally with Jira, CI, and a staging branch — each auto-detected and skipped
when absent.

## Agent hierarchy

The main agent stays the orchestrator and never writes code itself — it spawns a
fresh worker per delegated job and hands off through files in `.auto-dev/`,
never shared memory. Phase 1 and the Phase 5 acceptance check are its own work.

```
Orchestrator (main agent) ── owns the pipeline, holds the spec, runs the human gates
│
├─ Phase 1  Setup ......... detect repo + stack, resolve ticket, worktree, .auto-dev/
├─ Phase 2  Define agent .. SPEC.md — the testable contract + SCOPE CALL  (→ reviewer)
├─ Phase 3  Planner ....... IMPLEMENTATION.md — the technical how  (→ reviewer) [optional gate]
├─ Phase 4  Coder ......... code + tests (given only the plan)
├─ Phase 5  orch + cleanup  acceptance vs. the withheld spec → /simplify → quality gate
└─ Phase 6  orch + PR reviewer  [GATE] PR + adversarial review + CI → [GATE] staging → [GATE] main
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
| 3 Plan | planner + plan reviewer | `IMPLEMENTATION.md` — the technical how (optional approval gate) |
| 4 Build | coder | code + tests given **only** the plan |
| 5 Verify | orchestrator, then cleanup agent | acceptance review vs. the withheld spec (correction loop to Phase 4), then `/simplify` + the profile's quality gate to green |
| 6 Ship | orchestrator + PR reviewer | commit + draft PR + adversarial review + CI, then staging, then main + Jira Done — pausing at each |

## Three sessions, not one

The pipeline deliberately does **not** run end-to-end in a single context. It is
cut into three sessions — **Plan** (phases 1–3), **Build** (4–5) and **Ship** (6)
— and stops at each boundary after writing `.auto-dev/HANDOFF.md`, a short brief
for the next one. Start a fresh session and say `auto-dev continue` to pick up.

Orchestrator context is the real cost driver: it grows about 1k tokens per turn
and every added turn makes every later turn more expensive. So the orchestrator
holds the pipeline, not the code — it delegates reads, keeps large artifacts in
workers, and checkpoints at ~120k tokens rather than running until a 1M window
fills. Nothing crosses a boundary except `.auto-dev/` on disk and the git tree,
which is also what makes an interrupted run resumable.

## Scope call: the pipeline sizes itself to the task

Phase 2 returns one of three calls, and the pipeline adapts:

- **TRIVIAL** — one subsystem, one behavior, no new abstraction or interface, no
  migration or config change, and an existing test file covers it. The Define review
  and the Phase 3 agents are skipped; the orchestrator writes a short plan itself.
  **4 worker roles.**
- **STANDARD** — the full path. **7 worker roles.** (Roles, not spawns —
  a correction round re-spawns a worker.)
- **OVERSIZED** — too big for one PR: you get a proposed breakdown into ordered
  sub-tasks, tracked in `.auto-dev/WORK_LOG.md`, and on approval the pipeline runs
  per sub-task as separate PRs. Each sub-task gets its *own* scope call, so the
  cost is **1 role for the parent Define, then 4 or 7 per sub-task** depending on
  how each one sizes up — a number the approval prompt shows you before you agree to
  it, alongside how many times it will stop for your approval. A sub-task can be
  TRIVIAL but never OVERSIZED: decomposing inside a decomposition means the
  breakdown was wrong, so the pipeline stops and offers to re-cut it.

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
`skills/auto-dev/references/profiles.md`, and
`skills/auto-dev/references/phase-1-setup.md` for the full Phase 1 procedure.

## Human gates & integrations

Planning and build run unattended; the pipeline pauses for approval before
**opening the PR**, before the **staging merge**, and before the **main merge**
(plus an optional post-plan gate you can enable per run). The PR opens as a
**draft** unless you ask for it ready for review, and is marked ready before the
main gate. Main is merged only via `gh pr merge` (respecting branch protection,
never `--admin`), with `--squash` by default — `--merge` if the repo disallows
squash, `--rebase` only when it is the one method allowed. Staging is a direct
merge where the project uses that convention. **Jira** integration is
status-transitions-only (In Progress → In Review → Done) and is skipped if no
ticket is given. **CI** is monitored, with a bounded timeout, on the PR before
merge, and again after the staging and main merges to confirm the merge itself
didn't break the branch.

Declining is safe at every gate: `Stop` ends the run, `Hold` (where a gate offers
it) pauses a run you can resume later, and both leave the branch, the worktree,
and every artifact on disk. See `skills/auto-dev/references/gates-and-jira.md`
for the gates, and `skills/auto-dev/references/phase-6-ship.md` for the exact
commit, PR and merge sequences.

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

### Install without the plugin

If policy blocks plugins, link the agents into your user folder instead:

```
ln -s ~/Dev/auto-dev/agents ~/.claude/agents
```

This works only when `~/.claude/agents` does not exist yet. If it exists, link
each file into it:

```
ln -s ~/Dev/auto-dev/agents/*.md ~/.claude/agents/
```

The agents load as `auto-dev-<name>`, and the orchestrator falls back to that form.
Link `skills/auto-dev` into `~/.claude/skills/` too.

## Dependencies

Built-in tools only — no plugins required: `TodoWrite`, `Task`/`Agent`, `Bash`,
`Read`, `Edit`, `Write`, `Grep`, `Glob`, `AskUserQuestion`, and the `Skill` tool
(the Phase 5 cleanup agent runs `/simplify` with it). `gh` must be on your `PATH`
and authenticated: Phase 1 checks, and stops before doing any work if it isn't.
Optional integrations: the Atlassian MCP (Jira transitions) and a CI provider CLI.
The Jira tools are found by base name (`getJiraIssue`, …) with `ToolSearch`, so
the MCP server can be registered under any name; no match means Jira is skipped.
Phase 6a opens the PR with `gh pr create`, or through any PR skill Claude already
has that meets the pipeline's PR requirements — none is required.
Optional tooling: **Python 3.9+** with **PyYAML** (`pip install pyyaml`), used by
`skills/auto-dev/scripts/validate-config.py` to check a repo's `.auto-dev.yml` in
Phase 1 — a mistyped key is silently ignored otherwise. Without it the pipeline
still runs; it checks the file by hand and reports that it went unvalidated.
Three more helpers in `skills/auto-dev/scripts/` need only Python's standard
library: `resume-point.py` (finds where an interrupted run resumes, from
`WORK_LOG.md`), `exclude-artifacts.py` (makes `.auto-dev/` self-excluding in
Phase 1 and verifies it with git) and `check-staged.py` (the read-only check
before each Phase 6a commit that nothing under `.auto-dev/` is staged). Without
`python3` the pipeline runs the same steps by hand.
Also optional: `dexter`, which the orchestrator uses for symbol lookups in Elixir
repos; without it on your `PATH` it falls back to `grep`.

## Models and effort

Each worker ships as its own agent type in `agents/`, which fixes its tools, model
and effort. The types name model families (`opus`, `sonnet`, `fable`), not
versions, so a new release is picked up without editing the plugin.

| Worker                                   | Agent type                       | Model · effort    |
| ---------------------------------------- | -------------------------------- | ----------------- |
| Define agent                             | `auto-dev:define`                | `opus` · high     |
| Define reviewer                          | `auto-dev:define-reviewer`       | `opus` · high     |
| Planner                                  | `auto-dev:planner`               | `opus` · xhigh    |
| Plan reviewer                            | `auto-dev:plan-reviewer`         | `opus` · high     |
| Coder (STANDARD build, all corrections)  | `auto-dev:coder`                 | `opus` · high     |
| Coder (TRIVIAL first build)              | `auto-dev:coder-trivial`         | `sonnet` · medium |
| Cleanup agent                            | `auto-dev:cleanup`               | `sonnet` · medium |
| PR reviewer                              | `auto-dev:pr-reviewer`           | `opus` · xhigh    |
| PR reviewer (sensitive paths)            | `auto-dev:pr-reviewer-sensitive` | `fable` · high    |
| Orchestrator lookups                     | `auto-dev:lookup`                | `sonnet` · low    |

The orchestrator runs on the session's model, which you pick when starting each
session: `opus` at high effort for Plan and Build, `sonnet` at medium for Ship.
Each session's stop message names the model for the next one. To retune a worker,
edit the `model:` / `effort:` frontmatter in `agents/<name>.md` and the table in
`SKILL.md`.

## The `.auto-dev/` scratch directory

Each run creates `.auto-dev/` holding the artifacts phases hand off, plus
`WORK_LOG.md` (the ledger and resume point) and `HANDOFF.md` (the brief for the
next session) — see `skills/auto-dev/references/artifacts.md`. This is scratch, not part of your
project — the pipeline never commits it and makes the directory self-ignoring (a
`.gitignore` containing `*`, written into `.auto-dev/` itself) automatically, so
it cannot be staged even by a stray `git add -A`. (Note: a committed
`.auto-dev.yml` override file is separate and is *not* excluded.)

## Safety

Autonomous but bounded: the correction loop and the Define/plan re-reviews share
one iteration budget per task (default 4 revise rounds; each sub-task of a
multi-PR run gets its own), and the pipeline stops and reports
rather than committing a red build or weakening any security control. It refuses a
resolved quality gate with no test command in it, since that would pass Phase 5 by
having nothing to check. It merges to main only through a PR, only after your
approval, and if `gh pr merge` is refused it tells you why instead of working around
branch protection.

## Upgrading from 2.x

3.0 restructures the pipeline from ten phases to six and changes the artifact set:
`TICKET.md` and `ACCEPTANCE_CRITERIA.md` are merged into `SPEC.md`,
`CODING_TODO.md` is dropped (the plan's build sequence is the coder's worklist),
and `IMPLEMENTATION_EVAL.md` is dropped along with the plan-adherence check. A run
started on 2.x cannot be resumed on 3.0 — its `.auto-dev/` and its `WORK_LOG.md`
phase table won't match. Finish in-flight runs before upgrading.
