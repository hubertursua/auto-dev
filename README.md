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
never shared memory. Phase 1 and the correction briefs are its own work; judging
the build is not — it holds the plan and the story of every round, which is the
context a judge must not have.

```
Orchestrator (main agent) ── owns the pipeline, holds the spec, runs the human gates
│
├─ Phase 1  Setup ......... detect repo + stack, resolve ticket, worktree, .auto-dev/
├─ Phase 2  Define agent .. SPEC.md — the testable contract + SCOPE CALL  (→ reviewer)
├─ Phase 3  Planner ....... IMPLEMENTATION.md — the technical how  (→ reviewer)
│           Acceptance tester  held-out checks from the spec, proven to fail, sealed [optional gate]
├─ Phase 4  Coder ......... code + tests (given only the plan)
├─ Phase 5  Verifier + cleanup  RUN the checks vs. the withheld spec → /simplify → quality gate → re-check
└─ Phase 6  orch + reviewers  code review panel → security review → [GATE] PR + CI → [GATE] staging → [GATE] main
```

Two documents describe the work, and they answer different questions: `SPEC.md`
asks *did we build the right thing*, `IMPLEMENTATION.md` asks *did we build it the
way we decided*. They fail independently — a plan executed faithfully can still
miss the outcome — so the pipeline checks both.

The coder builds from the plan, never the contract. The plan is *required* to
cover every condition, so this isn't information-hiding — it's **language**-hiding:
the coder can't satisfy the check by echoing the contract's own wording back in a
test name.

## How the build is verified

Tests the coder wrote are evidence the coder produced, so they can't be the main
proof that the work is right. Agents are known to mark work done too early and to
make tests pass by weakening them. Verification is built around that:

- **A spec written to be tested.** Every condition in `SPEC.md` carries a
  concrete example (Given / When / Then), its tricky edge case, and how it should
  be verified (unit, integration, end-to-end or manual). The Define reviewer runs
  an ambiguity probe: if two different implementations both fit a condition's
  words, the condition is rewritten before anything is built.
- **Held-out acceptance checks.** After planning, an acceptance tester turns each
  spec condition into a black-box test from the spec alone. Every check for new
  behavior must **fail on the untouched code for the right reason**, since a test
  that passes before the change exists proves nothing. The checks are then sealed
  out of the worktree (stored where no test runner collects them), and the
  coder's brief never names them.
- **An independent verifier that runs things.** After the build, a fresh verifier
  installs the checks and **runs** them. It never sees the plan or the coder's
  report. Each condition gets a verdict and an evidence tier: **Strong** (the
  held-out checks passed), **Adequate** (it ran something itself and saw what it
  predicted beforehand) or **Weak** (a code citation, which can never count as
  met). A condition no agent can observe is marked `manual` and handed to you at
  the PR gate as a check to make.
- **A test-integrity audit.** `scripts/check-tests.py` flags deleted or skipped
  tests, removed assertions, new tests that assert nothing, and any edit to a
  sealed check. Each finding must be justified by the spec or it goes back to the
  coder. The coder and cleanup agent are told never to game tests, and the coder
  has a `BLOCKED` exit for when a step can't be done honestly.
- **Targeted mutation testing.** Passing tests show the code works; they don't
  show the tests would notice if it broke. The verifier plants a few small bugs
  in the changed lines (a flipped comparison, a boundary moved by one) with
  `scripts/mutate.py`, which restores every file afterwards. A bug no test
  catches on a line a condition depends on is a test gap and goes back to the
  coder. Capped at 20 mutants per pass by default; set `mutation.max` in
  `.auto-dev.yml` (0 turns it off).
- **Re-checked after every change.** The verifier runs again after `/simplify`
  and after every later fix, so the PR checklist always reflects the final code.

## What it does

Invoke it when you want a whole task taken off your plate and delivered as a
finished PR, hands-off — e.g. *"auto-dev this…"*, *"take it all the way to a
PR"*, *"pick up JIRA-1234 and ship it"*. The orchestrator runs:

| Phase | Worker | Output |
|-------|--------|--------|
| 1 Setup | orchestrator | detect repo/stack, load profile, resolve ticket, isolated worktree + branch, `.auto-dev/` |
| 2 Define | Define agent + reviewer | `SPEC.md` — context, testable conditions, assumptions, security criteria; plus the **scope call** |
| 3 Plan | planner + plan reviewer, acceptance tester | `IMPLEMENTATION.md` — the technical how; `acceptance/` — held-out checks sealed from the coder (optional approval gate) |
| 4 Build | coder | code + tests given **only** the plan |
| 5 Verify | verifier, then cleanup agent | the verifier runs the held-out checks and audits the tests vs. the withheld spec → `SPEC_EVAL.md` (correction loop to Phase 4), then `/simplify` + the profile's quality gate to green, then a verifier re-check |
| 6 Ship | orchestrator, 3 code reviewers + judge, security reviewer | code review panel and security review on the uncommitted change (correction loop to Phase 4 for must-fix findings), then commit + draft PR + CI, then staging, then main + Jira Done — pausing at each gate |

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
  migration or config change, and an existing test file covers it. The Define
  review, planner and plan reviewer are skipped; the orchestrator writes a short
  plan itself. **8 worker roles.**
- **STANDARD** — the full path. **11 worker roles.** (Roles, not spawns —
  the code review panel alone spawns three reviewers and a judge, and a
  correction round re-spawns workers.)
- **OVERSIZED** — too big for one PR: you get a proposed breakdown into ordered
  sub-tasks, tracked in `.auto-dev/WORK_LOG.md`, and on approval the pipeline runs
  per sub-task as separate PRs. Each sub-task gets its *own* scope call, so the
  cost is **1 role for the parent Define, then 8 or 11 per sub-task** depending on
  how each one sizes up — a number the approval prompt shows you before you agree to
  it, alongside how many times it will stop for your approval. A sub-task can be
  TRIVIAL but never OVERSIZED: decomposing inside a decomposition means the
  breakdown was wrong, so the pipeline stops and offers to re-cut it.

**The scope call thins the planning head, never the verification tail.** Phase 5
and Phase 6 run identically at every scope — skipping planning on a small change
is cheap, skipping verification is how a small change ships broken.

`WORK_LOG.md` is also the resume point if a run is interrupted.

## Review before the PR

Nothing is committed or pushed until the change has been reviewed twice, on the
uncommitted working tree, and you have seen the results:

1. **Code review panel.** Three reviewers run `/code-review xhigh` on the change
   independently. A judge merges their findings and checks each trigger path in
   the code. A correctness or test finding that only one reviewer raised goes to
   the other two for a re-vote.
2. **Security review.** One security reviewer runs `/security-review` over the
   whole change, and the judge double-checks every finding rated High or Medium.

A **rubric** decides what must be fixed and what is noise:

- **Code findings.** Only correctness bugs and missing or weak tests can be
  must-fix. Each one needs a concrete trigger path, a real input or sequence that
  leads to the failure, and at least 2 of the 3 reviewers' votes. Scope,
  performance and design findings are advisory. Problems the change didn't
  introduce are dropped.
- **Security findings.** One this change introduced, with a traced path, is
  must-fix. One that was already there is shown to you at the PR gate to triage:
  fix it in this PR, note it as a follow-up for a separate PR, or ignore it.
  It is never fixed without asking, because fixing it widens the PR's scope.
- **Confidence.** Every finding carries a confidence level (High, Medium or
  Low), and so does each report as a whole. A report whose confidence is Low
  (say, a reviewer failed) is flagged at the gate as a warning, never shown as a
  clean pass.

Must-fix findings go back to the coder through the same correction loop as an
unmet spec condition, and the fix is reviewed again before anything moves on.
Fixes made after the PR is open, for red CI or a human reviewer's comment, are
reviewed the same way before they are pushed. The procedure and the full rubric
are in `skills/auto-dev/references/review.md`.

## Stack profiles

The pipeline is language/framework-agnostic. A **profile** (`skills/auto-dev/profiles/`)
declares how a stack installs and what its quality gate is; Phase 1 detects the
stack, loads the profile, merges in runtime discovery, and honors a repo-local
`.auto-dev.yml` override. Shipped: **Elixir** (`mix compile`/`format`/`credo`/
`dialyzer`/`test`) plus a generic `default` fallback that discovers commands at
runtime. Add a stack by dropping in `profiles/<stack>.md` — no skill change.

The keys most runs touch in `.auto-dev.yml`: `iteration_budget` (revise rounds,
default 4), `mutation.max` (mutants per verifier pass, default 20, `0` = off),
`gates.post_plan` (turn the post-plan gate on), `branches` (`base`, `staging`,
`prefix`), `ci` and `ci_timeout_minutes`, `worktree_files`, `security_docs`, and
`jira.states`. Phase 1 validates the file with `scripts/validate-config.py`, so a
mistyped key is reported rather than silently ignored. See
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

Three more pauses are **conditional** and fire only when their situation
arises: the **decomposition approval** (OVERSIZED only — a multi-PR run never
starts unapproved), the **Jira In Progress confirmation** (Phase 1, only with a
ticket) and the **worktree cleanup offer** (after the main merge). Everything
else runs without check-ins.

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
(the Phase 5 cleanup agent runs `/simplify` with it, the code reviewers
`/code-review`, and the security reviewer `/security-review`). `gh` must be on your `PATH`
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
The other helpers in `skills/auto-dev/scripts/` need only Python's standard
library. Three are run by the orchestrator: `resume-point.py` (finds where an
interrupted run resumes, from `WORK_LOG.md`), `exclude-artifacts.py` (makes
`.auto-dev/` self-excluding in Phase 1 and verifies it with git) and
`check-staged.py` (the read-only check before each Phase 6a commit that nothing
under `.auto-dev/` is staged); without `python3` the orchestrator runs the same
steps by hand. Two are run by the Phase 5 verifier: `check-tests.py` (the
test-integrity audit) and `mutate.py` (applies mutants one at a time and restores
every file afterwards).
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
| Acceptance tester                        | `auto-dev:acceptance-tester`     | `opus` · high     |
| Coder (STANDARD build, all corrections)  | `auto-dev:coder`                 | `opus` · high     |
| Coder (TRIVIAL first build)              | `auto-dev:coder-trivial`         | `sonnet` · medium |
| Verifier                                 | `auto-dev:verifier`              | `opus` · high     |
| Cleanup agent                            | `auto-dev:cleanup`               | `sonnet` · medium |
| Code reviewer (×3 panel, and re-votes)   | `auto-dev:code-reviewer`         | `opus` · xhigh    |
| Review judge                             | `auto-dev:review-judge`          | `opus` · xhigh    |
| Security reviewer                        | `auto-dev:security-reviewer`     | `opus` · xhigh    |
| Security reviewer (sensitive paths)      | `auto-dev:security-reviewer-sensitive` | `fable` · high |
| Orchestrator lookups                     | `auto-dev:lookup`                | `sonnet` · low    |

The orchestrator runs on the session's model, which you pick when starting each
session: `opus` at high effort for Plan and Build, `sonnet` at medium for Ship.
Each session's stop message names the model for the next one. To retune a worker,
edit the `model:` / `effort:` frontmatter in `agents/<name>.md` and the table in
`SKILL.md`.

## The `.auto-dev/` scratch directory

Each run creates `.auto-dev/` holding the artifacts phases hand off:

| Path | Written by | Holds |
| ---- | ---------- | ----- |
| `profile.md` | Phase 1 | the resolved stack, commands, branches, CI and Jira settings |
| `WORK_LOG.md` | Phase 1 onward | the ledger: phase status, scope call, gate decisions, budget; the resume point |
| `HANDOFF.md` | each session's end | the brief for the next session |
| `SPEC.md` | Phase 2 | the testable contract |
| `IMPLEMENTATION.md` | Phase 3 | the technical plan |
| `acceptance/` | Phase 3 | the sealed held-out checks and their `MANIFEST.md` |
| `SPEC_EVAL.md`, `evidence/` | Phase 5 | the verifier's verdicts and evidence tiers, and what it ran |
| `lint/` | Phase 5 | one report per quality-gate check |
| `review/`, `CODE_REVIEW.md`, `SECURITY_REVIEW.md` | Phase 6a | the panel's raw reports, the judge's code review, the security review |

On a multi-PR run these live in the control worktree, with a
`tasks/<nn>-<slug>/` folder per sub-task. The full layout and every artifact's contract are in
`skills/auto-dev/references/artifacts.md`. This is scratch, not part of your
project — the pipeline never commits it and makes the directory self-ignoring (a
`.gitignore` containing `*`, written into `.auto-dev/` itself) automatically, so
it cannot be staged even by a stray `git add -A`. (Note: a committed
`.auto-dev.yml` override file is separate and is *not* excluded.)

## Safety

Autonomous but bounded: the correction loop and the Define/plan re-reviews share
one iteration budget per task (default 4 revise rounds; each sub-task of a
multi-PR run gets its own), and the pipeline stops and reports
rather than committing a red build or weakening any security control. It also
stops if the mutation step may have left a planted bug in the tree, or if the
build edited source inside a submodule. It refuses a
resolved quality gate with no test command in it, since that would pass Phase 5 by
having nothing to check. It merges to main only through a PR, only after your
approval, and if `gh pr merge` is refused it tells you why instead of working around
branch protection.

## Repository layout

```
.claude-plugin/         plugin.json (name, version) and marketplace.json
agents/                 one agent type per worker: tools, model, effort, role
skills/auto-dev/
  SKILL.md              the orchestrator's spine: phases, sessions, gates, rules
  references/           detail read on demand, one file per phase or topic
  profiles/             stack profiles (elixir.md, default.md)
  scripts/              the Python helpers listed under Dependencies
  evals/                evals.json (pipeline evals, with fixtures in files/)
                        and trigger-eval.json (should / shouldn't trigger)
tests/                  unit tests for the helper scripts
tools/check-repo.py     checks that the repo's files agree with each other
tools/check-pr.py       checks a branch name and PR title against the conventions
ruff.toml               lint config
.github/                CI workflow and PR template
CLAUDE.md               conventions for agents (and people) changing this repo
```

## Contributing

Before pushing, run the same checks CI runs:

```
ruff check .
python3 tools/check-repo.py
python3 -m unittest discover -s tests
```

Every change that alters how the pipeline behaves updates this README in the same
PR: the phase table, the worker and model table, the dependencies, the
`.auto-dev/` layout, and an *Upgrading* note for a version bump.

Branches are named `<type>/<short-kebab-description>` (`fix/mutate-mtime`), PR
titles `<type>: <summary>`, with types `feat`, `fix`, `docs`, `refactor`, `test`,
`chore` and `ci`. Every PR is squash-merged. PR conventions,
the full README checklist and the rules for changing a script are in
`CLAUDE.md`.

## Upgrading from 3.3

3.4 adds Example, Edge and Verify by lines under every `SPEC.md` condition, an
ambiguity probe in the Define review, and a mutation step in the verifier
(`scripts/mutate.py`, the `mutation.max` key in `.auto-dev.yml`). A run with a
3.3 `SPEC.md` still works: the acceptance tester falls back to the condition's
own words, and the mutation step needs nothing from the spec.

## Upgrading from 3.2

3.3 moves the Phase 5 acceptance check from the orchestrator to two new workers:
the `acceptance-tester`, which runs at the end of Phase 3, and the `verifier`.
It adds `acceptance/` and `evidence/` to `.auto-dev/`, an evidence tier and a
test-integrity section to `SPEC_EVAL.md`, and `scripts/check-tests.py`. A run
whose Phase 3 is already done has no sealed checks: finish it on 3.2, or re-run
its Phase 3 on 3.3 before the build.

## Upgrading from 3.1

3.2 replaces the single PR reviewer, which ran after the PR was opened, with a
code review panel and a separate security review that run before the PR gate.
`PR_REVIEW.md` is replaced by `CODE_REVIEW.md` and `SECURITY_REVIEW.md`, and the
`pr-reviewer` agents by `code-reviewer`, `review-judge`, `security-reviewer` and
`security-reviewer-sensitive`. A run that has not reached Phase 6 resumes
normally. A run already in Phase 6 should be finished on 3.1.

## Upgrading from 2.x

3.0 restructures the pipeline from ten phases to six and changes the artifact set:
`TICKET.md` and `ACCEPTANCE_CRITERIA.md` are merged into `SPEC.md`,
`CODING_TODO.md` is dropped (the plan's build sequence is the coder's worklist),
and `IMPLEMENTATION_EVAL.md` is dropped along with the plan-adherence check. A run
started on 2.x cannot be resumed on 3.0 — its `.auto-dev/` and its `WORK_LOG.md`
phase table won't match. Finish in-flight runs before upgrading.
