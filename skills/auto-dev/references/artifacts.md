# Artifacts — the `.auto-dev/` scratch directory

Every run of the pipeline hands state between phases through files under
`.auto-dev/` at the root of the task's worktree. This directory is **scratch, not
shippable code**: it is excluded from git in Phase 1 and must never appear in a
commit, a staged diff, or a PR (see the guardrails in `SKILL.md`).

## Layout

Single-PR run (the task fits one PR):

```
.auto-dev/
  profile.md              # resolved project profile (Phase 1) — stack, commands, branches, Jira map
  WORK_LOG.md             # progress ledger + resume point (Phase 1 onward)
  TICKET.md               # normalized ticket + research — the stakeholder view (Phase 2)
  ACCEPTANCE_CRITERIA.md  # what the ticket asks: stakeholder acceptance (Phase 2)
  SPEC.md                 # the testable contract derived from acceptance criteria (Phase 3)
  IMPLEMENTATION.md       # the technical plan — how (Phase 4)
  CODING_TODO.md          # ordered implementation steps (Phase 5)
  IMPLEMENTATION_EVAL.md  # code vs. plan (Phase 5)
  SPEC_EVAL.md            # code vs. spec; drives the feedback loop (Phase 6)
  lint/                   # one report per quality-gate check (Phase 7)
    COMPILE.md
    CREDO.md
    DIALYZER.md
    ...                   # filename per profile check; Elixir shown
  PR_REVIEW.md            # adversarial self-review of the diff (Phase 8)
```

Multi-PR run (an oversized ticket decomposed into sub-tasks — see the
task-orchestration layer in `SKILL.md`): the top-level `WORK_LOG.md` and
`profile.md` stay at the root, and each sub-task gets its own subtree so its
artifacts and branch never collide:

```
.auto-dev/
  profile.md
  WORK_LOG.md             # ledger of all sub-tasks + their status/branch/PR
  tasks/
    01-<slug>/            # per sub-task: same file set as a single-PR run
      TICKET.md  ACCEPTANCE_CRITERIA.md  SPEC.md  IMPLEMENTATION.md
      CODING_TODO.md  IMPLEMENTATION_EVAL.md  SPEC_EVAL.md  lint/  PR_REVIEW.md
    02-<slug>/
      ...
```

## Never commit `.auto-dev/`

In Phase 1, immediately after creating the worktree:

```bash
mkdir -p .auto-dev
echo ".auto-dev/" >> .git/info/exclude
```

`.git/info/exclude` enforces it mechanically (survives even a stray `git add
-A`). Belt-and-suspenders: Phase 8 still stages source paths **explicitly**
(`git add <path> …`) and never uses `git add -A`/`.`, and confirms `git status`
shows nothing under `.auto-dev/` before committing.

Note: `.auto-dev.yml` (the optional repo-local **override**, see
`references/profiles.md`) is a *different* file — it lives at the repo root, is
meant to be committed by the project, and is **not** excluded.

---

## `WORK_LOG.md` — the progress ledger

The single source of truth for progress within a run, and the **resume point** if
a run is interrupted. The orchestrator writes it in Phase 1 and updates it as
each phase/sub-task completes. Read it first when resuming.

### Single-PR run template

```markdown
# Work Log

- **Task:** <one-line description>
- **Ticket:** <JIRA-KEY or "none">
- **Repo:** <repo-name>   **Base:** <base-branch>   **Stack:** <profile>
- **Worktree:** <abs-path>   **Branch:** <prefix/slug>
- **Mode:** single-PR
- **Iteration budget:** <n> total revise rounds (<n> remaining)

## Phase status
| # | Phase | Status | Notes |
|---|-------|--------|-------|
| 1 | Workspace Setup | done | |
| 2 | Ticket Evaluation | in-progress | |
| 3 | Spec Definition | pending | |
| 4 | Implementation Planning | pending | |
| 5 | Implementation | pending | |
| 6 | Evaluation | pending | |
| 7 | Clean Up | pending | |
| 8 | PR Management | pending | |
| 9 | Staging Review | pending / n-a | |
| 10 | Close Ticket | pending | |

## Decisions & assumptions
- <recorded as they happen>
```

### Multi-PR run template

Same header (`Mode: multi-PR`), plus a sub-task table instead of a single phase
table. Each sub-task row tracks its own phase progress in its subtree.

```markdown
## Sub-tasks
| id | slug | depends on | status | branch | PR |
|----|------|-----------|--------|--------|----|
| 01 | <slug> | — | done | prefix/slug-01 | <url> |
| 02 | <slug> | 01 | in-progress | prefix/slug-02 | |
| 03 | <slug> | 01 | pending | | |
```

`status` values: `pending` → `in-progress` → `done` (or `blocked` with a note).

---

## Artifact contracts (what each file must contain)

Detailed authoring briefs for the agents that produce these live in
`references/subagent-prompts.md`. The contracts below define what each file *is*,
so downstream phases can rely on them.

- **`profile.md`** — the resolved project profile from Phase 1: detected stack and
  which `profiles/*.md` was loaded, the exact setup/gate commands (post-override),
  base/staging/prefix, CI provider, and Jira availability + state mapping. Every
  later phase reads this instead of re-detecting.
- **`TICKET.md`** — the normalized ticket (title, description, links) plus the
  research findings needed to act on it. Stakeholder-facing; no technical design.
- **`ACCEPTANCE_CRITERIA.md`** — *what the ticket asks*: the observable outcomes a
  stakeholder would sign off on, in their language. Not necessarily test-shaped.
- **`SPEC.md`** — *the testable contract* derived from the acceptance criteria:
  observable, testable conditions defining "this works," an `Assumptions` section
  for every resolved ambiguity, and a `Security/Compliance criteria` section when
  the task touches a sensitive path (pull the controls from the repo's own docs
  and the org security directives). No technical design / file names.
- **`IMPLEMENTATION.md`** — the technical *how*, self-contained: files to
  create/modify, design, data flow, ordered build sequence, test plan (which test
  proves which behavior, and where), migrations/config. Buildable without the
  spec; every acceptance criterion maps to a step and a test.
- **`CODING_TODO.md`** — the ordered, checkable task list the coder works through,
  derived from `IMPLEMENTATION.md`.
- **`IMPLEMENTATION_EVAL.md`** — the plan-adherence check: does the code match
  `IMPLEMENTATION.md`? Findings grouped blocker / should-fix / nit.
- **`SPEC_EVAL.md`** — the acceptance check against `SPEC.md` (which the coder
  never saw): per-criterion met / partially-met / unmet, with evidence
  (file\:line, test). Drives the Phase 6 → Phase 5 feedback loop.
- **`lint/<CHECK>.md`** — one report per quality-gate command, named per the
  loaded profile (Elixir: `COMPILE.md`, `CREDO.md`, `DIALYZER.md`): the command
  run, final status, and the tail of any output that had to be fixed.
- **`PR_REVIEW.md`** — the adversarial review of the branch diff: issues the
  reviewer tried to find (correctness, security, scope), grouped by severity, with
  file\:line. Written to disk; posting inline PR comments is opt-in.
