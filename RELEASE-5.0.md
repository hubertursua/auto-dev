# Release 5.0 — a lean pipeline

This file lives on the release branch only. It is the brief for every
workstream that merges into `feat/release-5-0`, and it is deleted in the
release PR that takes the branch to `main`.

## Why

A run is too slow to reach its first push. On a happy path, 14 or more Opus
spawns (20–30 in practice) and two manual session restarts happen before
anything reaches GitHub, and CI runs last, so a red CI starts the most
expensive loop of the run. The causes:

- **Nothing is pushed until the end.** The draft PR opens in S3, after the full
  review panel.
- **The same question is checked six or seven times**: a spec reviewer, a plan
  reviewer, fail-first checks, a verifier with a test audit and mutation, a
  3-reviewer panel with a judge, and a security reviewer. None is skipped for a
  small task.
- **Hiding information costs whole roles.** Sealed checks need reinsertion,
  fold mode and check proposals; a coder that never sees the spec needs plan
  proposals and a blocked mode.
- **The proposal and ruling system** (artifact owners, rulings, redo cascades,
  the deviation gate, five budget consumers) is where most PRs since 4.10 went.
- **Three sessions** guard an orchestrator context that `next` already keeps
  small.

## The 5.0 pipeline

One session, four steps:

1. **Plan.** One planner writes `PLAN.md`: the ask, the acceptance criteria
   (Given / When / Then, with the edge case), assumptions, and the steps. A
   **separate plan critic** reviews it (instructions below), since the author
   reads its own plan the way it meant to write it. The planner revises once.
   The post-plan gate stays optional (on for high-risk tasks).
2. **Tests first, in the open.** The acceptance tester writes a test per
   criterion, shows each failing on the untouched code, and commits them as
   their own commit. Nothing is sealed: `check-tests.py` refuses a later change
   to those lines, compared against that commit.
3. **Build and push.** The coder sees `PLAN.md` whole, builds, runs the quality
   gate to green, commits, pushes and opens a **draft PR**. CI starts here.
4. **Verify alongside CI.** One verifier (runs the tests, audits the test
   changes) and one reviewer covering code and security, in parallel with CI.
   High-risk tasks add the 3-reviewer panel, the judge and mutation. One fix
   loop takes review findings and red CI together. Then the PR is marked ready,
   the merge gate asks, and it merges.

Gates: the post-plan gate (optional), the ready-for-review gate (replaces the
open-the-PR gate: the draft PR opens without asking), the merge gate, and the
stops. Jira and CI handling stay as they are.

Removed: `define`, `define-reviewer`, `plan-reviewer` (folded into the planner
and the plan critic), sealing and fold mode, spec / plan / check proposals and
rulings, the deviation gate, the per-consumer budget (one round counter
remains), and the forced session boundaries (the event checkpoint stays).

## The plan critic

Becomes `agents/plan-critic.md` in workstream 2. It is a fresh agent: it gets
the ticket text, `PLAN.md` and read access to the repo, never the planner's
notes or reasoning. It writes a findings file and edits nothing else.

### What it looks for, in this order

1. **The ask, whole and no more.** Map every requirement in the ticket text to
   a criterion. Flag a requirement with no criterion, a criterion the ticket
   doesn't ask for (scope creep), and an assumption a human would plausibly
   answer the other way. Quote the ticket line for each.
2. **Criteria a test can decide.** Each criterion has a concrete example with
   real inputs and the exact expected outcome, and an edge case. Flag any
   criterion two implementations could both pass while one of them is wrong,
   and any outcome no test can observe ("is clean", "is fast" with no number).
3. **Grounded in the code.** Open every file, function and entry point the plan
   names and confirm it exists and does what the plan says. Flag a plan that
   builds a parallel version of something the repo already has, a changed
   interface whose callers aren't listed, and a test file or test pattern that
   doesn't match how the repo tests that code.
4. **Covered both ways.** Every criterion has a step that delivers it, and
   every step serves a criterion. Each step names the tests that prove it.
   Check the parts plans forget: error paths, config and migrations,
   permissions, docs the repo keeps for this kind of change.
5. **Risk.** Input from users or the network, auth and access control,
   secrets, data migrations, backward compatibility, concurrency. If any is
   touched and the plan doesn't say how it is handled, flag it, and say
   whether the task should be marked high-risk.
6. **Size and order.** The change fits one PR, and the steps run in an order
   where each can be built and tested before the next.

### How it reports

- **Blockers only when the plan, built as written, would ship the wrong thing
  or fail.** Each blocker states what goes wrong, cites its evidence (a quoted
  ticket line or a `path:line` it opened), and gives the concrete change to the
  plan. A blocker without evidence is a note.
- **Notes** are everything else worth saying, kept short. No style, wording or
  preference findings at all.
- **At most 7 blockers**, most severe first. More than that means the plan
  should be redone: say so as one blocker.
- **Verdict:** `APPROVE` (no blockers) or `REVISE`. "No blockers" is a claim:
  make it only after working through all six checks.
- It never rewrites the plan or proposes another design when the plan's design
  works.

### One round

The planner revises once for the blockers. The critic then checks only the
changed parts and whether each blocker was fixed. Anything still open goes on
the PR's ready-for-review gate summary; the run doesn't loop.

The same principle (a fresh reader with a checklist, evidence required, a cap,
one round) applies to the combined reviewer in workstream 5.

## Workstreams

Each workstream is one branch off `feat/release-5-0`, worked in its own
worktree, and lands by a squash-merged PR into `feat/release-5-0`, never
`main`. Each PR passes the three checks in `CLAUDE.md`, updates `README.md` for
what it changes, gets a fresh-agent review before it opens, and does **not**
bump the version (workstream 6 does that once). PR titles follow the usual
convention.

`cmd_next.py`, `briefs.py` and the references are shared by nearly every
workstream, so they run in waves. A wave's branches are cut from the release
branch only after the wave before it has merged.

| Wave | Branch | Scope |
|---|---|---|
| 1 | `refactor/strip-proposals` | Remove spec / plan / check proposals and rulings, the deviation gate and the per-consumer budget rules (one round counter). Pure deletion: no new behavior. |
| 2 | `feat/plan-critic` | Merge `define` into the planner (`PLAN.md`), add the plan critic, remove `define-reviewer` and `plan-reviewer`. |
| 2 | `feat/one-session` | Run straight through in one session; keep the event checkpoint; simplify `HANDOFF.md` and `resume`. |
| 3 | `feat/tests-first-open` | Commit the acceptance tests first; remove sealing and fold mode; `check-tests.py` guards those lines against the tests' commit; the coder sees `PLAN.md` whole. |
| 4 | `feat/early-draft-pr` | Commit, push and open the draft PR after the build's quality gate; the ready-for-review gate replaces the open-the-PR gate. |
| 5 | `feat/lean-review` | One verifier and one code-and-security reviewer by default, alongside CI; panel, judge and mutation for high-risk only; one fix loop for findings and red CI; lower the xhigh efforts. |
| 6 | `docs/release-5-0` | `UPGRADING.md` *Upgrading from 4.x* (a 4.x run can't resume on 5.0), evals and fixtures, a final README pass, version 5.0.0, delete this file. |

Wave 2's two branches run in parallel; their files barely overlap
(`define` / planner / critic versus `handoff` / `resume` / the runbooks).

The release PR from `feat/release-5-0` to `main` is titled
`feat!: run a lean plan, build, ship pipeline (5.0.0)`.
