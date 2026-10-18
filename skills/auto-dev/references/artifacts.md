# Artifacts — the `.auto-dev/` scratch directory

Every run of the pipeline hands state between phases through files under
`.auto-dev/` in the **control worktree** — the one Phase 1 creates. This directory
is **scratch, not shippable code**: Phase 1 makes it self-excluding and it must
never appear in a commit, a staged diff, or a PR (see the guardrails in
`SKILL.md`).

The pipeline keeps **two** descriptions of the work — `SPEC.md` (what) and
`IMPLEMENTATION.md` (how) — and nothing in between. Every other file here is
either setup state, a ledger, or verification: the held-out acceptance checks
and the reports that judge the build.

## Contents

- **Why two documents** — why `SPEC.md` and `IMPLEMENTATION.md` stay separate, and
  why the coder never sees the spec.
- **Where artifacts live: `<worktree>` vs. `<artifact-dir>`** — the two paths every
  brief carries, and how they diverge on a multi-PR run.
- **Layout** — the directory tree for single-PR and multi-PR runs.
- **Never commit `.auto-dev/`** — the Phase 1 self-excluding `.gitignore` (written
  and verified by `scripts/exclude-artifacts.py`), why not `.git/info/exclude`,
  and the pre-commit staged check (`scripts/check-staged.py`).
- **`WORK_LOG.md` — the progress ledger** — status rules and:
  - **Single-PR run template**
  - **Multi-PR run template** — sub-task table and per-sub-task phase tables.
  - **Resuming an interrupted run** — read this on any re-entry, planned or not;
    `scripts/resume-point.py` reads the ledger and names the resume point.
  - **Session checklists** — the S1 / S2 / S3 progress checklists to copy into
    TodoWrite, mirroring the ledger.
- **Artifact contracts (what each file must contain)** — what each file *is*, plus
  what deliberately is not an artifact.
- **Artifact templates** — skeletons to paste into briefs, and how strict each
  output is (strict vs. flexible, and what reads it back):
  - **`HANDOFF.md` (end of S1 and S2, or a context checkpoint; orchestrator)**
  - **`profile.md` (Phase 1, orchestrator)**
  - **`SPEC.md` (Phase 2, Define agent)**
  - **`IMPLEMENTATION.md` (Phase 3, planner)**
  - **`acceptance/MANIFEST.md` (Phase 3, acceptance tester)**
  - **`SPEC_EVAL.md` (Phase 5, verifier)**
  - **`review/pass-<n>/R<k>.md` (Phase 6a, code reviewer)**
  - **`review/pass-<n>/VOTES-R<k>.md` (Phase 6a, code reviewer re-voting)**
  - **`CODE_REVIEW.md` (Phase 6a, review judge)**
  - **`SECURITY_REVIEW.md` (Phase 6a, security reviewer + review judge)**
  - **`lint/<CHECK>.md` (Phase 5, cleanup agent) — one per `gate` entry**
- **The PR body** — who writes it in Phase 6a, and the sections it must keep.
- **The final report** — a flexible default shape for the run's last message.

## Why two documents

The pipeline keeps exactly two descriptions of the work, and they answer different
questions:

- **`SPEC.md` — did we build the right thing?** The testable contract: observable
  conditions, no design.
- **`IMPLEMENTATION.md` — did we build it the way we decided?** The technical how.

They fail **independently**. A plan executed faithfully can still miss the
outcome; an outcome can be delivered by a route the plan never described. Merging
them into one document collapses both into a single, weaker check.

**The coder builds from the plan, never the spec.** The plan is _required_ to
cover every condition (Phase 3), so this is not information-hiding — it is
**language**-hiding: the coder cannot satisfy the Phase 5 check by echoing the
spec's own wording back in a test name.

**A third description sits beside them: the held-out acceptance checks**
(`acceptance/`), executable tests written from `SPEC.md` alone before any code
exists, each new-behavior check proven to fail on the untouched tree. The coder
never sees them during the build. The Phase 5 verifier installs and runs them,
and it never sees the plan or the coder's account of the build: it judges the
code against the contract, with neither the builder's story nor the
orchestrator's correction history in its context.

## Where artifacts live: `<worktree>` vs. `<artifact-dir>`

Phase 1 creates one worktree; that is the **control worktree**, and its
`.auto-dev/` is the run's root. `WORK_LOG.md` and `profile.md` live there for the
whole run, however many PRs it takes.

Every brief is filled with **two** absolute paths, because they are not always
the same tree:

- **`<worktree>`** — where the code lives and the worker does its work.
- **`<artifact-dir>`** — where that task's artifacts are read and written.

On a **single-PR run** they coincide: the control worktree is also the build
worktree, so `<artifact-dir>` is `<worktree>/.auto-dev`. Removing that worktree
deletes the ledger with it, so the Phase 6c cleanup offer waits until after the
final report.

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
  acceptance/             # held-out checks from SPEC.md alone (Phase 3, acceptance tester)
    MANIFEST.md           # condition → check, kind, base-run result; what is not automatable
    files/<repo-path>     # the sealed copy of each check, at the path the verifier installs it
  SPEC_EVAL.md            # code vs. spec, with an evidence tier per condition (Phase 5, verifier)
  evidence/               # what the verifier ran and saw: integrity.txt, acceptance.txt, C<n>.txt
  lint/                   # one report per quality-gate check (Phase 5)
    COMPILE.md            # one file per check in the profile's `gate` list —
    FORMAT.md             # Elixir's five shown; the filenames come from the
    CREDO.md              # profile, so another stack has another set
    DIALYZER.md
    TEST.md
  review/                 # raw code-review reports, one directory per pass (Phase 6a)
    pass-1/
      R1.md  R2.md  R3.md   # the three panelists' own findings
      VOTES-R2.md           # re-votes on lone findings, when any
  CODE_REVIEW.md          # the judge's consolidated code review: verdicts, votes, confidence (Phase 6a)
  SECURITY_REVIEW.md      # the security review: origin, confidence, verification (Phase 6a)
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
      SPEC.md  IMPLEMENTATION.md  acceptance/  SPEC_EVAL.md  evidence/  lint/  review/
      CODE_REVIEW.md  SECURITY_REVIEW.md
    02-<slug>/            # own worktree: same file set as a single-PR run
      ...
```

On the **TRIVIAL** fast path the file set is unchanged — `IMPLEMENTATION.md` is
just written by the orchestrator rather than by the planner, and no Define review
runs. The verification artifacts (`acceptance/`, `SPEC_EVAL.md`, `evidence/`,
`lint/`, `review/`, `CODE_REVIEW.md`, `SECURITY_REVIEW.md`) are produced exactly as
on the standard path.

## Never commit `.auto-dev/`

In Phase 1, immediately after creating the worktree, run
`python3 <skill-dir>/scripts/exclude-artifacts.py <worktree>`. It does exactly
this, then proves it with `git status --porcelain --untracked-files=all --
.auto-dev/` (must print nothing) and `git check-ignore -q .auto-dev/WORK_LOG.md`
(must succeed):

```bash
mkdir -p .auto-dev/lint
printf '*\n' > .auto-dev/.gitignore
```

Without `python3` (exit `127`), run those two commands by hand and confirm with
`git status` that nothing under `.auto-dev/` appears. The script's exit handling
is in `references/phase-1-setup.md`, step 6.

The exclusion is mechanical, so it survives even a stray `git add -A`, and it is
removed along with the worktree.

**Do not use `.git/info/exclude`.** Inside a linked worktree `.git` is a *file*
(`gitdir: …`), not a directory, so `echo … >> .git/info/exclude` fails with "not
a directory" and the exclusion silently never happens. Nor is the path
`git rev-parse --git-path info/exclude` resolves to a fix: that is the **main
repository's shared** exclude file, so writing there affects every other worktree
and outlives this run.

On a multi-PR run only the control worktree holds `.auto-dev/`, so it is the only
tree that needs this; the sub-task worktrees contain code alone.

Phase 6 also stages source paths **explicitly**
(`git add -- <path> …`, and `git rm --cached` for deleted paths) and never uses
`git add -A`/`.`, and before committing
confirms nothing under `.auto-dev/` is staged, with `scripts/check-staged.py`
or its manual equivalent (`references/phase-6-ship.md`, step 4).

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

**Strict: ALWAYS use the exact structure below** — the same header fields, table
columns and `status` values. Resume finds the run by its header lines and restarts
from the phase tables' `Status` column, so a renamed field or column breaks it.

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
  flight. Phase 1 gets no row: it ran once, for the whole run. "Starts" means its
  worktree is cut and prepared; a prep that stops writes the table with Phase 2
  `blocked` (`references/subagent-prompts.md`).
- **The phase table is authoritative.** The summary `status` is a rollup for
  scanning; where the two disagree, the phase table is what resume reads.
- **`budget` is `<remaining>/<total>` for that sub-task alone**, because the
  iteration budget on a multi-PR run is per sub-task
  (`references/correction-loop.md`).

The `worktree` column is the sub-task's **build** worktree — the `<worktree>` its
briefs are filled with. Its `<artifact-dir>` is always
`<control-worktree>/.auto-dev/tasks/<id>`, so only the build worktree varies. Both are
created when the sub-task starts, not when the decomposition is approved
(`references/subagent-prompts.md`).

`status` values: `pending` → `in-progress` → `done`. Also valid: `skipped` (the
phase was deliberately bypassed; never Phase 3 on the TRIVIAL path, which still
runs the acceptance tester), `n/a` (the
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
   names this ticket (or states this task, by the rule below), that is the run to
   resume, and its **Control worktree** line confirms the path. Two matches — the
   same ticket started twice — is a stop-and-ask, not a guess.

   The script does this check and steps 3 and 5's lookup in one read-only call per
   tree; pass the Jira key, or the task text when there is no ticket (or no
   `--task` when the user names no task at all — see below):
   ```bash
   python3 <skill-dir>/scripts/resume-point.py <tree>/.auto-dev --task "<ticket or task>"
   ```
   A Jira key must appear as a whole token in the key/link part of the header's
   Ticket line (before the first spaced em dash ` — `; a key the restated ask
   mentions doesn't count, unless that part is a bare "none"), so
   `PROJ-12` never matches a `PROJ-123` ledger, and a Jira URL is matched by its
   key; any other text is compared word by word, ignoring case, punctuation and
   markdown, with the Task line and the ask the Ticket line restates. It matches
   when it has that line's words, or the line with a few words left out (at least
   80% kept, in order, no negation like `not` dropped). When one side's words all
   appear in the other but that is not a match — a fragment like
   `multi-currency`, or the user's longer original request containing the Task
   line — the script reports `NEAR-MISS`: possibly this run, worded differently.
   Whenever the user states a task, pass it as `--task`, even a short one.
   Run without `--task` only when they state none — a bare "continue" or
   "resume", or a loose name like "the multi-currency run"; an empty `--task`
   counts as omitted, and never pass a stand-in like "continue", which is
   matched as task text. Without `--task` the exit code says only what a tree
   holds: a `3` is a finished run left in place, not a candidate. List every tree
   that exits `0` with its printed task and ticket. One plainly the run the user
   means is the run; two or more, or any doubt, is a stop-and-ask, not a guess;
   none (and no `MALFORMED` ledger that may be the run) means there is nothing to
   continue — tell the user and ask what to work on rather than starting a fresh
   Phase 1.
   It prints the task, ticket, the first phase not complete (`done`, `skipped` or
   `n/a`) with its status, that phase's session, and the remaining budget.
   - `0` — this tree is the run; resume where it says, handling the status as
     step 3 does (and step 4 for Phase 6). A `Blocked:` line (a blocked phase,
     or a blocked sub-task with no phase table) means ask the user, as step 3
     says.
   - `3` — this tree is the run, but every phase is complete: nothing to resume.
     Tell the user the run already finished; re-run no phase.
   - `1` — read the message. `MISSING` or `MISMATCH`: this tree is not the run;
     check the next one. `NEAR-MISS`: it may be the run — after checking every
     tree, show the user each near-miss's task and ask which (if any) is theirs;
     never start a fresh run over one unasked. `MALFORMED` (it names the line or
     field): this may be the run with a broken ledger — read it by hand, and if
     steps 3–5 can't place the resume point, ask.
   - `2` — it couldn't run. Not a result: read that tree's header and phase table
     by hand, as above.
   - `127` — `python3` isn't installed: do the whole detection by hand, as above.
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
   to what git and `gh` actually report, then continue from there. With no commit
   on the branch and no PR-gate approval recorded in the Notes, the PR gate has
   not passed: the run was in the reviews, which come before it. Resume them as
   `references/review.md`, _The review loop_, says: re-run every review step the
   Notes do not record as done, and never trust a review report the Notes do not
   vouch for. A correction the Notes record as dispatched but not re-reviewed
   is re-dispatched without spending another round.
5. **Multi-PR runs** restart at the first sub-task that is not `done`, and within it
   at the first phase that is not `done` in **that sub-task's own phase table**. A
   sub-task with no phase table goes by its summary `status`: `done` is complete
   (skip it), `blocked` is step 3's report-and-ask, and `pending` never started —
   begin it at Phase 2, by cutting and preparing its worktree. If that worktree
   already exists, prep was cut off: reuse it and redo the prep
   (`references/subagent-prompts.md`). Completed sub-tasks keep their merged
   PRs — never re-run them, and never re-run Phase 1.
6. **Re-confirm nothing already confirmed.** A gate approved before the
   interruption stays approved (the ledger records it); a gate not yet reached
   still fires. Do not repeat a Jira transition — read the issue's current status
   instead of assuming it.

The budget carries over: a resumed run continues from the remaining count recorded
in the ledger — the header on a single-PR run, the sub-task's `budget` cell on a
multi-PR one — never a fresh 4 (`references/correction-loop.md`).

### Session checklists

At the start of each session, copy that session's checklist into TodoWrite and
tick items off as you go. The checklist **mirrors the ledger and never replaces
it**: `WORK_LOG.md` stays the source of truth and the resume point, so update its
phase row as well as ticking the item. On a resume, tick whatever the ledger
already marks `done`, `skipped` or `n/a`, and start at the first open item as
steps 3–5 above decide. Each item restates a step from `SKILL.md`, in the same
order. The checklist adds no step, and the detail lives where `SKILL.md` puts it.

```
S1 Plan progress (on a sub-task, cut and prepare its worktree as 1.5 does, then start at Phase 2; Phase 1 never repeats):
- [ ] 1.1 Detect repo & branches; check gh first (missing/unauthenticated/non-GitHub → stop-and-report)
- [ ] 1.2 Detect stack, load profile, apply .auto-dev.yml (validated); record CI provider
- [ ] 1.3 Resolve the ticket
- [ ] 1.4 Read binding rules; resolve security directives
- [ ] 1.5 Worktree + branch from fresh origin/<base>; seed worktree_files (each must be gitignored); run setup
- [ ] 1.6 Prep .auto-dev/ self-excluding: exclude-artifacts.py exits 0 (127: by hand; git status shows nothing under it)
- [ ] 1.7 Write profile.md; initialize WORK_LOG.md
- [ ] 1.8 Jira → In Progress (ticket only, confirmed)
- [ ] 2   Define agent → SPEC.md
- [ ] 2.1 Read the scope call (OVERSIZED: propose sub-tasks, get decomposition approval)
- [ ] 2.2 Define review (STANDARD only)
- [ ] 3.1 Planner → IMPLEMENTATION.md (TRIVIAL: write it yourself)
- [ ] 3.2 Plan review (not on TRIVIAL)
- [ ] 3.3 Acceptance tester → acceptance/ (every scope; checks sealed, worktree unchanged)
- [ ] 3.4 Post-plan gate (only if enabled for this run)
- [ ] Boundary: update WORK_LOG.md → overwrite HANDOFF.md → tell the user → STOP
```

```
S2 Build progress:
- [ ] 4   Coder builds from IMPLEMENTATION.md only; settle any BLOCKED step; note plan deviations
- [ ] 5.1 Verifier (first pass) → SPEC_EVAL.md (unmet / partial / unjustified integrity → correction + verifier re-check)
- [ ] 5.2 Simplify (cleanup agent, after the acceptance loop settles — not per correction; no budget)
- [ ] 5.3 Quality gate to green → lint/*.md; verifier re-check (unmet → correction + cleanup re-spawn + re-check)
- [ ] Boundary: update WORK_LOG.md → overwrite HANDOFF.md → tell the user → STOP
```

```
S3 Ship progress:
- [ ] 6a.1 Code review panel: 3 × code-reviewer (/code-review xhigh) → judge → re-votes → CODE_REVIEW.md (must-fix → correction loop + cleanup re-spawn + re-review on the fix's files)
- [ ] 6a.2 Security review: security reviewer (/security-review) → judge verifies High/Medium → SECURITY_REVIEW.md (must-fix → correction loop, then 6a.1 on the fix's files, then 6a.2 again)
- [ ] 6a.3 PR gate (both reviews' confidence + counts; open must-fix; pre-existing security for the user to triage)
- [ ] 6a.4 Commit: explicit paths; check-staged.py --expect <paths> exits 0 (127: by hand) — nothing under .auto-dev/ staged
- [ ] 6a.5 Push (never --force); open PR with acceptance checklist + quality-gate results + review summary; inline review comments only if asked or configured
- [ ] 6a.6 CI monitoring (red pre-merge → correction loop + cleanup re-spawn + Phase 6a refresh, its fix reviewed before re-push)
- [ ] 6a.7 Jira → In Review
- [ ] 6b   Staging gate → direct merge → CI on staging (n/a without staging)
- [ ] 6c.1 Read human reviews; mark the PR ready
- [ ] 6c.2 Main gate
- [ ] 6c.3 gh pr merge, explicit method, never --admin (refused → report, stop);
           confirm state MERGED (queued/auto-merge → report, stop)
- [ ] 6c.4 CI on main; Jira → Done; multi-PR: offer the sub-task's build-worktree cleanup
- [ ] Final report
- [ ] Single-PR: offer worktree cleanup, only now (removing it deletes .auto-dev/)
```

---

## Artifact contracts (what each file must contain)

Briefs for the agents that produce these are in `references/subagent-prompts.md`.
The contracts below define what each file *is*; the templates that follow fix the
shape.

- **`profile.md`** — the resolved project profile from Phase 1: detected stack and
  which `profiles/*.md` was loaded, the exact `setup`/`gate` commands (post-override)
  and any check dropped for a missing tool, base/staging/prefix, CI provider and
  timeout, the iteration budget, the resolved security-directive sources, and Jira
  availability + state mapping. Every later phase reads this instead of re-detecting.
- **`HANDOFF.md`** — the brief the *next* session reads. It, `WORK_LOG.md` and
  `profile.md` are what a session opens on entry; everything else in here is read
  only by the phase that needs it (`SKILL.md`, *Session boundaries*).
  **Under 60 lines**, overwritten — not appended — at the end
  of S1 and S2 and at any context checkpoint: what is done, the exact next phase, the 3–8 file paths that matter,
  open assumptions, and the one command to re-enter. It is a pointer sheet, not a
  summary: never restate `SPEC.md` or `IMPLEMENTATION.md` in it. A session that
  needs their content either opens them where its own phase requires it (the
  Phase 5 correction briefs, the Phase 6a checklist) or spawns a worker that reads
  them — copying them into the handoff just pays for them twice.
- **`SPEC.md`** — *the testable contract*, and the only statement of what the task
  asks. Four sections: **Context** (the ticket restated, links, and the research
  findings needed to act on it — stakeholder-readable, no technical design);
  **Conditions** (observable, testable conditions defining "this works," in plain
  language, no file names or signatures); **Assumptions** (every resolved
  ambiguity); and **Security/Compliance criteria** when the task touches a
  sensitive path (controls pulled from the security-directive sources `profile.md`
  names). Written in Phase 2; **withheld from the coder**; the basis of the
  acceptance checks, the Phase 5 verifier's verdicts and the PR body's checklist.
- **`IMPLEMENTATION.md`** — the technical *how*, self-contained: files to
  create/modify, design, data flow, the ordered build sequence (which is the
  coder's worklist), test plan (which test proves which behavior, and where),
  migrations/config. Buildable without the spec; every spec condition maps to a
  build step and a test. Written by the planner in Phase 3 — or, on the TRIVIAL
  fast path, by the orchestrator as a short files-plus-test note.
- **`acceptance/`** — the held-out checks (Phase 3, acceptance tester).
  `MANIFEST.md` maps each `SPEC.md` condition to its checks, each check's kind
  (`fail-to-pass` or `pass-to-pass`) and its run on the untouched tree, and lists
  the conditions no check can drive, with an observable proxy where one exists.
  `files/` holds the **sealed** copy of each check at its repo-relative path; the
  worktree holds no copy until the verifier installs them in Phase 5. Once
  installed they ship in the PR like any other test, and
  `scripts/check-tests.py` fails any run where an installed copy differs from its
  sealed one.
- **`SPEC_EVAL.md`** — the verifier's judgment of the build against `SPEC.md`
  (which the coder never saw): per condition, security/compliance criteria
  included, a verdict (**met / partial / unmet / manual**), an **evidence tier**
  (**Strong** — the held-out checks passed; **Adequate** — something the verifier
  ran itself matched its stated expectation; **Weak** — a citation nobody ran,
  which caps the verdict at partial), and the evidence; plus the test-integrity
  audit, each finding judged justified or not. Drives the Phase 5 correction loop
  back into the coder. Rewritten in full by every verifier re-spawn. Nothing is
  committed at this point, so the evidence comes from the working tree rather than
  a commit range — `references/subagent-prompts.md`, _Verifier_, gives the exact
  invocation and why each half of it matters.
- **`evidence/`** — what the verifier ran and saw: the audit output
  (`integrity.txt`), the acceptance run (`acceptance.txt`), and per condition its
  stated expectation, the command and the result (`C<n>.txt`). `SPEC_EVAL.md`
  cites these; the correction brief quotes them.
- **`lint/<CHECK>.md`** — one report per quality-gate command, named per the
  loaded profile — **one per `gate` entry, all of them** (Elixir: `COMPILE.md`,
  `FORMAT.md`, `CREDO.md`, `DIALYZER.md`, `TEST.md`): the command run, final
  status, and the tail of any output that had to be fixed.
- **`review/pass-<n>/R<k>.md`** — one code reviewer's own findings for one pass,
  each with a trigger path, plus security leads it noticed. Raw input to the
  judge; nothing else reads it.
- **`review/pass-<n>/VOTES-R<k>.md`** — one reviewer's `agree` / `disagree` on
  the lone findings it did not raise. The orchestrator counts them into
  `CODE_REVIEW.md`.
- **`CODE_REVIEW.md`** — the consolidated code review, across every pass: each
  finding's verdict (must-fix, advisory, noise), votes, confidence, the judge's
  reason, and whether a must-fix finding is `open` or `fixed`; plus the report's
  overall confidence. Drives the review-stage correction loop and the PR gate
  summary.
- **`SECURITY_REVIEW.md`** — the security review of the whole change: each
  finding's origin (introduced or pre-existing), confidence, the judge's
  verification, and verdict (must-fix, for the user, advisory); plus the overall
  confidence. Drives the security corrections and the PR gate's triage of
  pre-existing findings.

  Both review reports stay on disk. Their findings are posted as inline PR
  comments only when the user asks during the run or `.auto-dev.yml` sets
  `pr_review.inline_comments: true` (`references/profiles.md`).

**Not artifacts.** Three things deliberately live outside this directory: the
coder's **report** (deviations, test changes, `BLOCKED` steps), which is part of
its structured return, read by the orchestrator and never by the verifier; the reviewers'
findings (Define review, plan review), which are returned to the orchestrator and
applied as edits to `SPEC.md` / `IMPLEMENTATION.md` rather than written to disk;
and the **PR body**, contracted below.

## Artifact templates

Skeletons for the artifacts a worker or the orchestrator writes. They fix the
*shape* — the contracts above fix the content. Keep the headings; a later phase reads
them back (Phase 6a builds the PR checklist straight out of `SPEC_EVAL.md`).

**Paste the relevant template into the worker's brief, with its strictness line.**
A worker has no path to this file and cannot follow a reference to it.

**How strict each template is.** Match the output to its consumer:

- **Strict** — ALWAYS use the exact template structure: the same headings in the
  same order, the same header fields, the same table columns. Fill the `<…>`
  placeholders; never rename, merge or drop a heading (beyond an omission the
  template itself allows). A later step reads these back by section or field name.
- **Flexible** — a sensible default. Adapt the sections to the task, using your
  best judgment; only the parts named as fixed must stay.

| Output | Strictness | Read back by |
|--------|------------|--------------|
| `WORK_LOG.md` | strict | the resume procedure and `scripts/resume-point.py` (header lines, phase-table `Status`); every session's entry |
| `HANDOFF.md` | strict | the next session's entry |
| `profile.md` | strict | every phase and worker (`setup`/`gate` commands run verbatim) |
| `SPEC.md` | strict | Define reviewer, acceptance tester, verifier, code reviewers, security-reviewer type choice (`Security/Compliance criteria`), PR body |
| `IMPLEMENTATION.md` | headings strict, content flexible | coder (`Build sequence`), plan reviewer, acceptance tester (entry points only), code reviewers |
| `acceptance/MANIFEST.md` | strict | verifier (tiers, install), post-plan gate summary, correction briefs (the paths not to touch) |
| `SPEC_EVAL.md` | strict | the orchestrator's correction briefs, the next verifier re-check, PR body checklist, PR gate summary |
| `review/pass-<n>/R<k>.md` | strict | the review judge |
| `review/pass-<n>/VOTES-R<k>.md` | strict | the orchestrator, applying the votes |
| `CODE_REVIEW.md` | strict | open must-fix → correction loop; PR gate and main gate summaries; PR body `Review` |
| `SECURITY_REVIEW.md` | strict | the security-verify judge; open must-fix → correction loop; PR gate triage; PR body `Review` |
| `lint/<CHECK>.md` | strict | PR body `Quality gate`, PR gate summary |
| PR body | required sections strict, prose flexible | the human reviewer; refreshed after a Phase 6 correction |
| Final report | flexible | the user |

### `HANDOFF.md` (end of S1 and S2, or a context checkpoint; orchestrator)

```markdown
# Handoff — <ticket or task> → <S1 Plan | S2 Build | S3 Ship> (<next session | resume>)

Re-enter with: `cd <absolute worktree path>`
Branch: <prefix>/<slug>   Base: origin/<base>   Sub-task: <id or n/a>
Iteration budget remaining: <n>/<total>

## Done
- <phase>: <one line, outcome only>

## Next
Phase <n> — <name>. <One or two sentences on the first action.>
Pick up at: <start of Phase <n> | Phase 6, after <last gate passed> — reconcile first>

## Files that matter
- <path> — <why>            # 3–8 entries, no more

## Open assumptions
- <assumption the next session must not silently re-decide>

## Do not
- <anything already settled that a fresh context might redo — e.g. re-run Phase 1,
  re-review the spec, re-detect the stack>
```

`(next session)` is the planned boundary at the end of S1 or S2. `(resume)` is a
context checkpoint (`SKILL.md`, _Context budget_): the target is the session the
checkpoint fired in, resumed in a fresh context. `Pick up at` tells that session
where in the phase to start. For a phase the ledger marks `in-progress` that is
its start, because an `in-progress` phase re-runs whole (_Resuming an
interrupted run_, step 3). Only Phase 6 resumes inside the phase: name the last
gate passed, and reconcile with git and `gh` before acting (step 4).

Paths absolute; a fresh session does not know where it is. Do not include a
narrative of how the last session went — the ledger has that, and the next
session does not need it.

### `profile.md` (Phase 1, orchestrator)

```markdown
# Project profile

- **Stack:** <stack>   **Profile:** `profiles/<stack>.md` | `profiles/default.md` + discovery
- **Repo:** <repo-name>   **CI:** <github-actions|circleci|gitlab|none>   **CI timeout:** <n> min
- **Base:** <branch>   **Staging:** <branch | n/a — no staging branch>   **Prefix:** <prefix>
- **Iteration budget:** <n> per task
- **Worktree files seeded:** <paths copied from the main checkout | none>
- **`.auto-dev.yml`:** <validated | not machine-validated: <reason> — checked by hand | none>
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

### `IMPLEMENTATION.md` (Phase 3, planner)

**Headings strict, content flexible.** Keep every heading below, in this order —
the coder works `Build sequence` top to bottom, and the plan reviewer checks
`Build sequence` and `Test plan` against the spec. What goes under `Design` and
`Data flow` adapts to the task. On the TRIVIAL fast path the orchestrator's short
note keeps `Files` and `Test plan` and may drop the rest.

```markdown
# Implementation plan — <task>

## Files
- `<path>` — <create | modify>: <what changes there>

## Design
<modules, functions, data structures — and why this shape, where it is not obvious>

## Data flow
<how a request, event or record moves through the change, end to end>

## Build sequence
1. <small, independently verifiable unit> — test: `<test file>`
2. <…>

## Test plan
| Test | Location | Proves | Spec condition |
|------|----------|--------|----------------|
| <test name> | `<path>` | <the behavior, in the plan's own words> | <#> |

## Migrations / config
<schema migrations, config or env changes — or "none">
```

Cite spec conditions **by number only**, never by their wording: the coder reads
this file, and the spec's language stays out of it (*Why two documents*).

### `acceptance/MANIFEST.md` (Phase 3, acceptance tester)

```markdown
# Acceptance checks — <task>

Written from SPEC.md alone, run on the untouched tree at `origin/<base>` (<short sha>).
Sealed copies are under `files/`; the verifier installs them after the build.

| # | Condition | Check (path :: test name) | Kind | Base run |
|---|-----------|---------------------------|------|----------|
| 1 | <condition, in the spec's own words> | `test/app/acceptance/todo_delete_acceptance_test.exs` :: "owner deleting a todo removes it from the list" | fail-to-pass | failed: `UndefinedFunctionError Todos.delete/2` |
| 2 | <condition> | <path :: name> | pass-to-pass | passed |
| S1 | <security/compliance criterion> | <path :: name> | fail-to-pass | failed: expected 404, got 200 |

A fail-to-pass check whose Base run is not a right-reason failure does not belong
here. A repaired check reads `not re-run (repair)`.

## Not automatable
| # | Condition | Why no check can drive it | Proxy a verifier can run |
|---|-----------|---------------------------|--------------------------|
| <n> | <condition> | <reason> | <command, request or log line — or "none"> |

<"None." when every condition has a check>

## Assumptions
- <each choice made about entry points or expected values, and why>
```

### `SPEC_EVAL.md` (Phase 5, verifier)

```markdown
# Acceptance evaluation — <task>

Read from the working tree against `origin/<base>`; nothing is committed yet.
Pass: <first | re-check after <what changed>> · acceptance run: <n passed / n total> (`evidence/acceptance.txt`)

| # | Condition | Verdict | Tier | Evidence |
|---|-----------|---------|------|----------|
| 1 | <condition, in the spec's own words> | met | Strong | acceptance `todo_delete_acceptance_test.exs` :: "owner deleting…" passed (`evidence/C1.txt`) |
| 2 | <condition> | met | Adequate | expected `GET /todos` without the deleted id; saw it (`evidence/C2.txt`) |
| 3 | <condition> | partial | Weak | <what holds, what was not run, and why> |
| 4 | <condition> | unmet | Strong | acceptance check failed: <the failing assertion, one line> |
| 5 | <condition> | manual | — | a human must check: <exactly what, and how> |
| S1 | <security/compliance criterion> | met | Strong | <check passed> |

Verdicts: `met` needs every acceptance check for the condition passing AND Strong
or Adequate evidence; Weak evidence caps a condition at `partial`; a failing
acceptance check is `unmet`; `manual` only for a condition MANIFEST.md lists as not
automatable that could not be observed here either. Security/compliance criteria
are rows in this table — never a separate pass.

## Test integrity
`check-tests.py` exit <0 | 1 | 3> (`evidence/integrity.txt`)

| Finding | Location | Judgment | Reason |
|---------|----------|----------|--------|
| REMOVED_ASSERTION | `test/app/todos_test.exs:-42` | Justified | condition 3 changes the response to 404 |
| ADDED_SKIP | `test/app/list_test.exs:10` | Unjustified | no condition removes this behavior |

<"None." when the audit is clean and the diff shows no gaming>

## Defective acceptance checks
<each check that asserts something SPEC.md does not say, and why — or "None.">

## Corrections dispatched
| Round | Item | Brief | Outcome |
|-------|------|-------|---------|
| 1 | 4 | <one line> | met |

## Unresolved
<every condition still partial or unmet, and every Unjustified finding, when the
loop settled, and what was tried. Then every `manual` condition. This is what the
PR body's unticked boxes are drawn from.>
```

The verifier rewrites the whole file on every pass. Carry the `Corrections
dispatched` rows over from the previous version (the orchestrator tells it what
was dispatched) so the history survives.

### `review/pass-<n>/R<k>.md` (Phase 6a, code reviewer)

```markdown
# Code review R<k> — pass <n>

Scope: <the scope as briefed>
/code-review xhigh: <ran | failed: <reason>>   ·   Coverage: <full | partial: <files not covered, and why>>

## Findings
1. **<title>** — `path:line` — <correctness | tests | scope | performance | design | conventions>
   Trigger path: <entry point `file:line` → … → the failure, with the input>
   Why it is wrong: <one or two sentences>

## Security leads
- `path:line` — <one line, unchased>

## Pre-existing
<n> problems seen in code this change did not introduce (count only).
```

An empty `Findings` section says `none — <what you tried>`. An empty
`Security leads` section says `none`.

### `review/pass-<n>/VOTES-R<k>.md` (Phase 6a, code reviewer re-voting)

```markdown
# Re-votes R<k> — pass <n>

| Finding | Vote | Reason |
|---------|------|--------|
| C4 | agree | `lib/todos/list.ex:42` — `hd/1` on the empty list; nothing upstream guards it |
| C6 | disagree | `lib/todos/save.ex:18` — the changeset already rejects a blank title |
```

### `CODE_REVIEW.md` (Phase 6a, review judge)

The judge writes it, and the orchestrator updates it after the re-votes (moving
each `Pending re-vote` row to `Must-fix` or `Advisory`, and finalizing the
overall line). It holds every pass, so earlier must-fix findings stay visible as
`fixed`.

```markdown
# Code review — <branch>

**Overall confidence: <High | Medium | Low | provisional (re-votes pending)>** — <reviewers finished: n/3; coverage: full | partial; must-fix decided 2–1: <IDs | none>>
Latest pass: <n> — scope: <scope>
Must-fix: <open> open · <fixed> fixed   ·   Advisory: <n>   ·   Noise: <n>   ·   Dropped (pre-existing): <n>

## Must-fix
| ID | Finding | Location | Category | Votes | Confidence | Status |
|----|---------|----------|----------|-------|------------|--------|
| C1 | <title> | `path:line` | correctness | 3/3 | High | open |
| C2 | <title> | `path:line` | tests | 2/3 (re-vote) | Medium | fixed (pass 2) |

### C1 — <title>
Trigger path: <entry point `file:line` → … → failure, as the judge confirmed it>
Judge: <why it holds>

## Pending re-vote
| ID | Finding | Location | Category | Raised by | Re-voters | Votes |
|----|---------|----------|----------|-----------|-----------|-------|

## Advisory
| ID | Finding | Location | Category | Votes | Confidence | Why advisory |
|----|---------|----------|----------|-------|------------|--------------|

## Noise
| ID | Finding | Raised by | Why dismissed |
|----|---------|-----------|---------------|

## Security leads
- `path:line` — <lead> (raised by R<k>) → passed to the security review

## Passes
| Pass | Scope | Reviewers finished | Must-fix found | Re-votes |
|------|-------|--------------------|----------------|----------|
| 1 | whole change | 3/3 | 2 | 1 |
```

An empty section says `none`; an empty table is a section nobody filled, not a
clean one. `Pending re-vote` is empty once the orchestrator has applied the votes.

### `SECURITY_REVIEW.md` (Phase 6a, security reviewer + review judge)

The security reviewer writes it with every `Verified` cell `pending`; the
security-verify judge fills those cells, corrects any origin, and recomputes the
header.

```markdown
# Security review — <branch>

**Overall confidence: <High | Medium | Low>** — <finished: yes | no; coverage: full | partial; High/Medium verified: <n>/<n>>
Run <n> — reviewer: <security-reviewer | security-reviewer-sensitive> — scope: the whole change since `<merge-base>`
Must-fix: <open> open · <fixed> fixed   ·   For the user (pre-existing): <n>   ·   Advisory: <n>

## Findings
| ID | Finding | Location | Origin | Confidence | Verified | Verdict | Status |
|----|---------|----------|--------|------------|----------|---------|--------|
| S1 | <title> | `path:line` | introduced | High | confirmed | must-fix | open |
| S2 | <title> | `path:line` | pre-existing | Medium | confirmed | for the user | — |
| S3 | <title> | `path:line` | introduced | Low | — | advisory | — |

### S1 — <title>
Path: <untrusted input → `file:line` → … → the exploit>
Depends on: <the configuration or assumption — Medium only>
Verified: <the judge's reason>

## Panel leads checked
| Lead | Result |
|------|--------|
| `path:line` — <lead> | <finding ID, or "not a vulnerability: <why>"> |

## Coverage
<what was covered; any file not covered, and why>
```

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

**Who writes it.** The orchestrator, in Phase 6a, whatever route opens the PR —
directly with `gh pr create`, or through a fitting skill from its available-skills
list (`references/phase-6-ship.md`, step 5, has the full requirements). Where the
repo has a PR template, fill it and carry these sections inside it; otherwise use
this shape as-is, attribution line included. Brevity rules may trim the Summary,
but nothing drops the three sections this pipeline reads back: **Acceptance
conditions**, **Quality gate** and **Review**. So: those three sections and the
attribution line are **strict**; the Summary and Assumptions prose is
**flexible**.

```markdown
## Summary
<what changed and why, 2–4 sentences — drawn from SPEC.md's Context>

## Acceptance conditions
<one checkbox per SPEC.md condition; ticked only where SPEC_EVAL.md says `met`,
each with its evidence tier>
- [x] <condition, in the spec's own words> — <Strong | Adequate>: <the check or what was run>
- [ ] <partial or unmet — say which it is, and why it is being shipped anyway>
- [ ] Needs a human check: <condition> — <exactly what to check, from SPEC_EVAL.md>
<then one line per Unjustified test-integrity finding still open, if any>

## Quality gate
<one line per `gate` command: the command and its final status, from lint/*.md>

## Review
<two lines, from CODE_REVIEW.md and SECURITY_REVIEW.md: each review's overall
confidence, and its must-fix findings fixed and still open>
- Code review — confidence <High | Medium | Low>: <n> must-fix fixed, <n> open
- Security review — confidence <High | Medium | Low>: <n> must-fix fixed, <n> open
<then one line per must-fix finding still open: what it is, where, and why it is
being shipped anyway. Advisory and noise findings stay in .auto-dev/. A
pre-existing security finding appears here only if the user chose `Separate PR`
(listed as a follow-up) or `Fix it in this PR` (listed as fixed) at the PR gate.>

## Assumptions
<the unresolved assumptions from SPEC.md a reviewer should sanity-check>

Generated with [Claude Code](https://claude.com/claude-code)
```

**Ship the unticked box rather than a tidy list.** A condition surfaced as unmet
is a decision the reviewer gets to make; a condition quietly dropped from the
checklist is the one failure of this pipeline nobody can catch downstream. If a
Phase 6 correction lands, the checklist, the quality-gate lines and the review
summary are part of what it invalidates (`references/correction-loop.md`) — refresh them on the open PR with
`gh pr edit <pr> --body-file <file>`, since the PR already exists by then and
re-running PR creation would open a second one.

## The final report

**Flexible — a sensible default; adapt it as needed.** It is for the user, and
nothing reads it back. Every item `SKILL.md`, _Final report_, lists must appear;
the order, wording and grouping are yours. On a multi-PR run, repeat the per-PR
lines for each sub-task from `WORK_LOG.md`. A run ended early (a `Stop` at a gate,
a stop-and-report condition) uses the same shape and says where it stopped.

```markdown
## auto-dev — <task or ticket> — <shipped | stopped at <phase>: <reason>>

- **PR:** <url> (<merged | open | draft>)   **Branch:** <prefix/slug>   **Worktree:** <abs-path>
- **Built:** <what changed, 1–3 sentences>
- **Scope call:** <TRIVIAL | STANDARD | OVERSIZED → n sub-tasks>
- **Quality gate:** <each check and its final status>
- **Review:** code <confidence>, <n> must-fix fixed, <n> open · security <confidence>, <n> must-fix fixed, <n> open, <n> pre-existing for the user
- **Jira:** <transitions performed | none — no ticket>
- **Iteration budget:** <remaining>/<total>

**Assumptions:** <the ones a reviewer should know about>

**Unresolved / skipped:** <unmet conditions, open must-fix findings, skipped steps — or "none">

**Follow-ups:** <pre-existing security findings the user sent to a separate PR — or "none">
```
