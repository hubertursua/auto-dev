# Artifacts — the `.auto-dev/` scratch directory

Every run of the pipeline hands state between phases through files under
`.auto-dev/` in the **control worktree** — the one Phase 1 creates. This directory
is **scratch, not shippable code**: Phase 1 makes it self-excluding and it must
never appear in a commit, a staged diff, or a PR (see the guardrails in
`SKILL.md`).

The pipeline keeps **two** descriptions of the work — `SPEC.md` (what) and
`IMPLEMENTATION.md` (how) — and nothing in between. Every other file here is
either setup state, a ledger, or a verification report.

## Where artifacts live: `<worktree>` vs. `<artifact-dir>`

Phase 1 creates one worktree; that is the **control worktree**, and its
`.auto-dev/` is the run's root. `WORK_LOG.md` and `profile.md` live there for the
whole run, however many PRs it takes.

Every brief is filled with **two** absolute paths, because they are not always
the same tree:

- **`<worktree>`** — where the code lives and the worker does its work.
- **`<artifact-dir>`** — where that task's artifacts are read and written.

On a **single-PR run** they coincide: the control worktree is also the build
tree, so `<artifact-dir>` is `<worktree>/.auto-dev`.

On a **multi-PR run** they diverge. Each sub-task builds in its own worktree, but
its artifacts stay in the control worktree at
`<control-worktree>/.auto-dev/tasks/<id>` — an absolute path into a *different*
tree than the `<worktree>` that sub-task builds in. Two reasons: the ledger and
every sub-task's evidence stay in one place for the final report and for
resuming, and they survive the Phase 6c offer to remove a merged sub-task's
worktree. The control worktree is never built in on a multi-PR run — it holds the
parent `SPEC.md` and the ledger, nothing more.

Create each sub-task's directory (including its `lint/`) before spawning that
sub-task's first agent. **Never write `.auto-dev/…` literally into a brief** —
always substitute `<artifact-dir>`.

## Layout

Single-PR run (the task fits one PR):

```
.auto-dev/
  profile.md              # resolved project profile (Phase 1) — stack, commands, branches, Jira map
  WORK_LOG.md             # normalized ticket + progress ledger + resume point (Phase 1 onward)
  HANDOFF.md              # brief for the NEXT session; overwritten at each session boundary
  SPEC.md                 # the testable contract: context, conditions, assumptions, security (Phase 2)
  IMPLEMENTATION.md       # the technical plan — how (Phase 3)
  SPEC_EVAL.md            # code vs. spec; drives the acceptance feedback loop (Phase 5)
  lint/                   # one report per quality-gate check (Phase 5)
    COMPILE.md            # one file per check in the profile's `gate` list —
    FORMAT.md             # Elixir's five shown; the filenames come from the
    CREDO.md              # profile, so another stack has another set
    DIALYZER.md
    TEST.md
  PR_REVIEW.md            # adversarial self-review of the diff (Phase 6)
```

Multi-PR run (an oversized ticket decomposed into sub-tasks — see the
task-orchestration layer in `SKILL.md`). Everything below sits in the **control
worktree**; the sub-task worktrees hold code only and contain no `.auto-dev/` at
all, so each sub-task's artifacts and branch never collide:

```
<control-worktree>/.auto-dev/
  profile.md              # resolved once in Phase 1, shared by every sub-task
  WORK_LOG.md             # ledger of all sub-tasks + their status/branch/PR
  HANDOFF.md              # brief for the next session, naming the active sub-task
  SPEC.md                 # the parent spec — informs the decomposition only
  tasks/
    01-<slug>/            # <artifact-dir> for sub-task 01, whose code is in its
      SPEC.md  IMPLEMENTATION.md  SPEC_EVAL.md  lint/  PR_REVIEW.md
    02-<slug>/            # own worktree: same file set as a single-PR run
      ...
```

On the **TRIVIAL** fast path the file set is unchanged — `IMPLEMENTATION.md` is
just written by the orchestrator rather than by a plan agent, and no Define review
runs. The verification artifacts (`SPEC_EVAL.md`, `lint/`, `PR_REVIEW.md`) are
produced exactly as on the standard path.

## Never commit `.auto-dev/`

In Phase 1, immediately after creating the worktree:

```bash
mkdir -p .auto-dev/lint
printf '*\n' > .auto-dev/.gitignore
```

A `.gitignore` containing `*` ignores everything in the directory, itself
included, so the exclusion is mechanical and survives even a stray `git add -A`.
It is also self-contained: it travels with the worktree and disappears when the
worktree is removed.

**Do not use `.git/info/exclude`.** Inside a linked worktree `.git` is a *file*
(`gitdir: …`), not a directory, so `echo … >> .git/info/exclude` fails with "not
a directory" and the exclusion silently never happens. Nor is the path
`git rev-parse --git-path info/exclude` resolves to a fix: that is the **main
repository's shared** exclude file, so writing there affects every other worktree
and outlives this run.

On a multi-PR run only the control worktree holds `.auto-dev/`, so it is the only
tree that needs this; the sub-task worktrees contain code alone.

Phase 6 also stages source paths **explicitly**
(`git add <path> …`) and never uses `git add -A`/`.`, and confirms `git status`
shows nothing under `.auto-dev/` before committing.

Note: `.auto-dev.yml` (the optional repo-local **override**, see
`references/profiles.md`) is a *different* file — it lives at the repo root, is
meant to be committed by the project, and is **not** excluded.

---

## `WORK_LOG.md` — the progress ledger

The single source of truth for progress within a run, and the **resume point** if a
run is interrupted. The orchestrator writes it in Phase 1, then marks each phase
`in-progress` **before** starting it and `done` once it finishes. Read it first when
resuming.

Write the row on entry, not only on completion: a phase updated only at the end would
still read `pending` after being cut off mid-flight, and step 3 below would trust its
half-written artifact as finished.

Its header also carries the **normalized ticket** — the restated task and its
link — so the ledger is self-describing without a separate ticket file.

### Single-PR run template

```markdown
# Work Log

- **Task:** <one-line description>
- **Ticket:** <JIRA-KEY + link, or "none"> — <restated ask, 1–2 sentences>
- **Repo:** <repo-name>   **Base:** <base-branch>   **Stack:** <profile>
- **Control worktree:** <abs-path>   **Branch:** <prefix/slug>
- **Mode:** single-PR   **Scope call:** <TRIVIAL | STANDARD>   (`OVERSIZED` runs multi-PR)
- **Iteration budget:** <n> total revise rounds (<n> remaining)

## Phase status
| # | Phase | Status | Notes |
|---|-------|--------|-------|
| 1 | Setup | done | |
| 2 | Define | in-progress | |
| 3 | Plan | skipped | scope call TRIVIAL — plan written by the orchestrator |
| 4 | Build | pending | |
| 5 | Verify | pending | |
| 6 | Ship | pending | staging gate: n/a (no staging branch) |

## Decisions & assumptions
- <recorded as they happen>
```

### Multi-PR run template

Same header, with `Mode: multi-PR`. A sub-task summary table replaces the single
phase table, and each sub-task that has **started** carries its own phase table
below it — the same six-row shape a single-PR run uses.

```markdown
## Sub-tasks
| id | slug | depends on | scope | budget | status | branch | worktree | PR |
|----|------|-----------|-------|--------|--------|--------|----------|----|
| 01 | <slug> | — | STANDARD | 1/4 | done | prefix/slug-01 | <abs-path> | <url> |
| 02 | <slug> | 01 | TRIVIAL | 4/4 | in-progress | prefix/slug-02 | <abs-path> | |
| 03 | <slug> | 01 | — | 4/4 | pending | | | |

### 02-<slug>
| # | Phase | Status | Notes |
|---|-------|--------|-------|
| 2 | Define | done | scope call TRIVIAL |
| 3 | Plan | skipped | plan written by the orchestrator |
| 4 | Build | in-progress | |
| 5 | Verify | pending | |
| 6 | Ship | pending | staging gate: n/a (no staging branch) |
```

Three rules govern it:

- **Write a sub-task's phase table when that sub-task starts**, not up front. A
  `pending` sub-task adds nothing, so the ledger grows only with work actually in
  flight. Phase 1 gets no row: it ran once, for the whole run.
- **The phase table is authoritative.** The summary `status` is a rollup for
  scanning; where the two disagree, the phase table is what resume reads.
- **`budget` is `<remaining>/<total>` for that sub-task alone**, because the
  iteration budget on a multi-PR run is per sub-task
  (`references/correction-loop.md`).

The `worktree` column is the sub-task's **build** tree — the `<worktree>` its
briefs are filled with. Its `<artifact-dir>` is always
`<control-worktree>/.auto-dev/tasks/<id>`, so only the build tree varies. Both are
created when the sub-task starts, not when the decomposition is approved
(`references/subagent-prompts.md`).

`status` values: `pending` → `in-progress` → `done`. Also valid: `skipped` (the
phase was deliberately bypassed — e.g. Phase 3 on the TRIVIAL path), `n/a` (the
step cannot apply — e.g. the staging gate with no staging branch, recorded in the
Phase 6 row's Notes since Phase 6 is one row), and `blocked`
(with a note). Never leave a phase that will never run sitting at `pending`.

### Resuming an interrupted run

The worktree, the branch, and every artifact produced so far are still on disk.

This covers both kinds of re-entry. A **planned** one — the session boundary at
the end of S1 or S2 (`SKILL.md`, *Session boundaries*) — left a `HANDOFF.md`,
which names the next phase outright; read it with `WORK_LOG.md` and skip to step
3. An **unplanned** one — a crash, a `/clear`, a machine restart — has no handoff
or a stale one, so run the detection below and trust the ledger over the handoff
wherever the two disagree.

1. **Detect.** Before Phase 1 does anything else, look for an existing control
   worktree. You are standing in the main repo, which never holds `.auto-dev/` — the
   control worktree is a sibling directory:
   ```bash
   git worktree list     # control worktrees are siblings: ../<repo-name>-<slug>
   ```
   Check each tree it lists for a `.auto-dev/WORK_LOG.md` and read the header. If one
   names this ticket (or restates this task), that is the run to resume, and its
   **Control worktree** line confirms the path. Two matches — the same ticket started
   twice — is a stop-and-ask, not a guess.
2. **Re-read, don't re-derive.** `profile.md` already holds the resolved stack,
   commands, branches, CI provider, and Jira mapping — do not re-detect any of it.
   The ledger header holds the ticket, worktree, branch, and remaining budget.
3. **Restart at the first phase that is not `done`,** reading its status:
   - `pending` — run it normally.
   - `in-progress` — the phase was cut off mid-flight, so its artifact may be
     partial. **Re-run the whole phase and overwrite the artifact.** Never resume
     *inside* a phase: a half-written artifact is indistinguishable from a
     finished one.
   - `skipped` / `n/a` — move on; the decision behind it still holds.
   - `blocked` — do not quietly retry. Report the recorded reason and ask.
4. **Phase 6 is the exception to blind re-running.** Check the world before
   acting: `git log`, `git status`, whether the branch is on the remote,
   `gh pr view`. A PR may already be open, or already merged. Reconcile the ledger
   to what git and `gh` actually report, then continue from there.
5. **Multi-PR runs** restart at the first sub-task that is not `done`, and within it
   at the first phase that is not `done` in **that sub-task's own phase table**. A
   sub-task with no phase table never started; begin it at Phase 2. Completed
   sub-tasks keep their merged PRs — never re-run them, and never re-run Phase 1.
6. **Re-confirm nothing already confirmed.** A gate approved before the
   interruption stays approved (the ledger records it); a gate not yet reached
   still fires. Do not repeat a Jira transition — read the issue's current status
   instead of assuming it.

The budget carries over: a resumed run continues from the remaining count recorded
in the ledger — the header on a single-PR run, the sub-task's `budget` cell on a
multi-PR one — never a fresh 4 (`references/correction-loop.md`).

---

## Artifact contracts (what each file must contain)

Detailed authoring briefs for the agents that produce these live in
`references/subagent-prompts.md`. The contracts below define what each file *is*, so
downstream phases can rely on them; the templates that follow fix the shape.

- **`profile.md`** — the resolved project profile from Phase 1: detected stack and
  which `profiles/*.md` was loaded, the exact setup/gate commands (post-override)
  and any check dropped for a missing tool, base/staging/prefix, CI provider and
  timeout, the iteration budget, the resolved security-directive sources, and Jira
  availability + state mapping. Every later phase reads this instead of re-detecting.
- **`HANDOFF.md`** — the brief the *next* session reads. It, `WORK_LOG.md` and
  `profile.md` are what a session opens on entry; everything else in here is read
  only by the phase that needs it (`SKILL.md`, *Session boundaries*).
  **Under 60 lines**, overwritten — not appended — at the end
  of S1 and S2: what is done, the exact next phase, the 3–8 file paths that matter,
  open assumptions, and the one command to re-enter. It is a pointer sheet, not a
  summary: never restate `SPEC.md` or `IMPLEMENTATION.md` in it. A session that
  needs their content either opens them where its own phase requires it (the
  Phase 5 acceptance check, the Phase 6a checklist) or spawns a worker that reads
  them — copying them into the handoff just pays for them twice.
- **`SPEC.md`** — *the testable contract*, and the only statement of what the task
  asks. Four sections: **Context** (the ticket restated, links, and the research
  findings needed to act on it — stakeholder-readable, no technical design);
  **Conditions** (observable, testable conditions defining "this works," in plain
  language, no file names or signatures); **Assumptions** (every resolved
  ambiguity); and **Security/Compliance criteria** when the task touches a
  sensitive path (controls pulled from the security-directive sources `profile.md`
  names). Written in Phase 2; **withheld from the coder**; the basis of the
  Phase 5 acceptance check and of the PR body's checklist.
- **`IMPLEMENTATION.md`** — the technical *how*, self-contained: files to
  create/modify, design, data flow, the ordered build sequence (which is the
  coder's worklist), test plan (which test proves which behavior, and where),
  migrations/config. Buildable without the spec; every spec condition maps to a
  build step and a test. Written by the plan agent in Phase 3 — or, on the TRIVIAL
  fast path, by the orchestrator as a short files-plus-test note.
- **`SPEC_EVAL.md`** — the acceptance check against `SPEC.md` (which the coder
  never saw): per-condition **met / partial / unmet**, with evidence
  (file\:line, test) — including the security/compliance conditions. Drives the
  Phase 5 → Phase 4 feedback loop. Nothing is committed at this point, so the
  evidence comes from the working tree rather than a commit range — `SKILL.md`
  Phase 5 gives the exact invocation and why each half of it matters.
- **`lint/<CHECK>.md`** — one report per quality-gate command, named per the
  loaded profile — **one per `gate` entry, all of them** (Elixir: `COMPILE.md`,
  `FORMAT.md`, `CREDO.md`, `DIALYZER.md`, `TEST.md`): the command run, final
  status, and the tail of any output that had to be fixed.
- **`PR_REVIEW.md`** — the adversarial review of the branch diff: issues the
  reviewer tried to find (correctness, security, scope), grouped by severity, with
  file\:line. Written to disk; posted as inline PR comments only when the user asks
  during the run or `.auto-dev.yml` sets `pr_review.inline_comments: true`
  (`references/profiles.md`).

**Not artifacts.** Three things deliberately live outside this directory: the
coder's **plan-deviation report**, which is part of its structured return and is
read as context for the acceptance check rather than filed; the reviewers'
findings (Define review, plan review), which are returned to the orchestrator and
applied as edits to `SPEC.md` / `IMPLEMENTATION.md` rather than written to disk;
and the **PR body**, contracted below.

## Artifact templates

Skeletons for the six artifacts a worker or the orchestrator writes. They fix the
*shape* — the contracts above fix the content. Keep the headings; a later phase reads
them back (Phase 6a builds the PR checklist straight out of `SPEC_EVAL.md`).

**Paste the relevant template into the worker's brief.** A subagent has no path to
this file and cannot follow a reference to it.

### `HANDOFF.md` (end of S1 and S2, orchestrator)

```markdown
# Handoff — <ticket or task> → <S2 Build | S3 Ship>

Re-enter with: `cd <absolute worktree path>`
Branch: <prefix>/<slug>   Base: origin/<base>   Sub-task: <id or n/a>
Iteration budget remaining: <n>/<total>

## Done
- <phase>: <one line, outcome only>

## Next
Phase <n> — <name>. <One or two sentences on the first action.>

## Files that matter
- <path> — <why>            # 3–8 entries, no more

## Open assumptions
- <assumption the next session must not silently re-decide>

## Do not
- <anything already settled that a fresh context might redo — e.g. re-run Phase 1,
  re-review the spec, re-detect the stack>
```

Paths absolute; a fresh session does not know where it is. Do not include a
narrative of how the last session went — the ledger has that, and the next
session does not need it.

### `profile.md` (Phase 1, orchestrator)

```markdown
# Project profile

- **Stack:** <stack>   **Profile:** `profiles/<stack>.md` | `default.md` + discovery
- **Repo:** <repo-name>   **CI:** <github-actions|circleci|gitlab|none>   **CI timeout:** <n> min
- **Base:** <branch>   **Staging:** <branch | n/a — no staging branch>   **Prefix:** <prefix>
- **Iteration budget:** <n> per task
- **Worktree files seeded:** <paths copied from the main checkout | none>
- **Post-plan gate:** <on | off> — <which condition enabled it>
- **Security directives:** <resolved paths> | none found — repo coding rules only
- **Jira:** <available, cloudId cached | unavailable — no ticket / MCP unreachable>
  in_progress `<name>` · in_review `<name>` · done `<name>`

## Setup — run in order, verbatim
1. `<command>`

## Quality gate — run in order, verbatim (the Definition of Done)
| # | kind | command | report |
|---|------|---------|--------|
| 1 | compile | `<command>` | `COMPILE.md` |

**Dropped checks:** `<check>` — <tool absent: no dependency declared / no config file>

## Test notes
<required services, monorepo/umbrella scope, slow tiers>

## Assumptions
<anything inferred rather than found — required when the default profile was used>
```

### `SPEC.md` (Phase 2, Define agent)

```markdown
# Spec — <task>

## Context
<the ticket restated, links, and the research findings needed to act on it: where
this lives in the code, the modules and flows involved, similar precedents,
constraints. Stakeholder-readable; no technical design.>

## Conditions
1. <observable, testable condition in plain language — no file names, no signatures>
2. <…>

<where a condition is hard to observe, say so and give the closest observable proxy>

## Assumptions
- <each ambiguity resolved, and how it was resolved>

## Security/Compliance criteria
<the specific controls, pulled from the sources profile.md names. Omit this section
entirely when the task touches no sensitive path.>
```

### `SPEC_EVAL.md` (Phase 5, orchestrator)

```markdown
# Acceptance evaluation — <task>

Read from the working tree against `origin/<base>`; nothing is committed yet.

| # | Condition | Verdict | Evidence |
|---|-----------|---------|----------|
| 1 | <condition, in the spec's own words> | met | `lib/foo.ex:42`, `test/foo_test.exs:18` |
| 2 | <condition> | partial | <what holds; what does not> |
| 3 | <condition> | unmet | <what is missing> |

Security/compliance conditions are rows in this table — never a separate pass.

## Corrections dispatched
| Round | Condition | Brief | Outcome |
|-------|-----------|-------|---------|
| 1 | 3 | <one line> | met |

## Unresolved
<every condition still partial or unmet when the loop settled, and what was tried.
This is what the PR body's unticked boxes are drawn from.>
```

### `PR_REVIEW.md` (Phase 6a, adversarial reviewer)

```markdown
# Adversarial PR review — <branch>

Diff: `git diff origin/<base>...HEAD`   ·   **Blockers: <n>**

## Blockers
1. **<title>** — `path/to/file.ex:120`
   <why it is wrong, and a concrete input or sequence that triggers it>

## Should-fix
1. **<title>** — `path:line` — <why>

## Nits
- `path:line` — <why>

## Lenses
| Lens | Result |
|------|--------|
| Correctness | <finding numbers, or "nothing found"> |
| Security | |
| Scope | |
| Tests | |
| Conventions | |
```

A lens that turns up nothing says so; an empty row is an unread lens, not a clean one.

### `lint/<CHECK>.md` (Phase 5, cleanup agent) — one per `gate` entry

```markdown
# <CHECK> — <pass | fail>

- **Command:** `<the exact command from profile.md, run verbatim>`
- **Final status:** pass
- **Runs:** <n>

## Fixed to get here
- `path:line` — <what the check flagged, and the change that cleared it>

## Output tail (final run)
<the last lines of output, fenced>

**Suppressions:** <none | the narrowest suppression applied, and why it was needed>
```

## The PR body

`.auto-dev/` is never committed, so the PR body is the one place this pipeline's
reasoning reaches a human reviewer. The orchestrator assembles these sections in
Phase 6a from artifacts that are about to become invisible to everyone but itself.

**Who writes it.** Where the `open-pr` skill is available, Phase 6a hands the PR
over to it — that skill owns the repo's PR template, the Jira link, the draft flag
and the attribution line, and its prose brevity rules govern the Summary. What it
does **not** get to drop are the two sections below that this pipeline reads back:
**Acceptance conditions** and **Quality gate**. Pass them as required content.
Without `open-pr`, the orchestrator writes the whole thing to this shape,
attribution line included:

```markdown
## Summary
<what changed and why, 2–4 sentences — drawn from SPEC.md's Context>

## Acceptance conditions
<one checkbox per SPEC.md condition; ticked only where SPEC_EVAL.md says `met`>
- [x] <condition, in the spec's own words>
- [ ] <partial or unmet — say which it is, and why it is being shipped anyway>

## Quality gate
<one line per gate command: the command and its final status, from lint/*.md>

## Assumptions
<the unresolved assumptions from SPEC.md a reviewer should sanity-check>

Generated with [Claude Code](https://claude.com/claude-code)
```

**Ship the unticked box rather than a tidy list.** A condition surfaced as unmet
is a decision the reviewer gets to make; a condition quietly dropped from the
checklist is the one failure of this pipeline nobody can catch downstream. If a
Phase 6 correction lands, the checklist and the gate lines are part of what it
invalidates (`references/correction-loop.md`) — refresh them on the open PR with
`gh pr edit <pr> --body-file <file>`, since the PR already exists by then and
re-running `open-pr` would try to create a second one.
