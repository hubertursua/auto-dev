# Release 5.0 — a lean pipeline

This file lives on the release branch only. It is the brief for every
workstream that merges into `feat/release-5-0`: read it whole before you start
one. It is deleted in the release PR that takes the branch to `main`.

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

## Target

A default-lane happy path takes **at most 5 worker spawns to the first push**
(planner, plan critic, planner's revision, acceptance tester, coder) and **at
most 7 to ready-for-review** (plus the verifier and the reviewer), in one
session. Wave 5 turns these numbers into a test. Timing benchmarks come after
the release; until then, spawn counts are the measure.

## The 5.0 pipeline

One session, four steps:

1. **Plan.** One planner writes `PLAN.md`: the ask, the acceptance criteria
   (Given / When / Then, with the edge case), assumptions, the size check, the
   risk tier it proposes, and the steps. A **separate plan critic** reviews it
   (instructions below), since the author reads its own plan the way it meant
   to write it. The planner revises once. Blockers still open after that
   revision fire the post-plan gate and the user decides; the run never builds
   on a plan with a known blocker. Otherwise the post-plan gate stays optional
   (on for high-risk tasks).
2. **Tests first, in the open.** The acceptance tester writes a test per
   criterion, shows each failing on the untouched code, and commits them as
   their own commit. Nothing is sealed: `check-tests.py` refuses a later change
   to those lines, compared against that commit.
3. **Build and push.** The coder sees `PLAN.md` and the tests whole, builds,
   and runs the quality gate to green. `check-staged.py` still guards the
   commit. Then the run commits, pushes and opens a **draft PR** whose
   description says it is not yet reviewed. CI starts here.
4. **Verify alongside CI.** One verifier (runs the tests, audits the test
   changes) and one reviewer covering code and security, in parallel with CI.
   One fix loop takes review findings and red CI together. Then the
   ready-for-review gate, the PR is marked ready, CI is watched once more, the
   merge gate asks, and it merges.

### Rules that replace what is removed

- **Instead of proposals.** The coder may deviate from a plan step when the
  step is wrong; it records each deviation and why in its report, and the
  ready-for-review gate lists them. The acceptance criteria are fixed: a
  criterion that turns out wrong or impossible is a stop that asks the user
  (the stop-and-fixer flow from 4.26), never a negotiation between workers.
- **Instead of sealing.** The coder can see the tests, so it could special-case
  them. The verifier and the reviewer are both told to look for code that
  passes a test without implementing the criterion. On a high-risk task the
  verifier also runs its own probe for each criterion, with inputs the
  committed test doesn't use.
- **The risk tier is not the author's alone.** The planner proposes it, the
  plan critic confirms or raises it, and after the build a script re-checks it
  from the diff (sensitive paths, size). It can only go up.
- **High-risk tasks add** the 3-reviewer panel with the judge, the separate
  security reviewer, mutation, the verifier's probes and the post-plan gate.
- **Draft CI.** Some workflows skip drafts. If no check appears on the draft
  within a grace period, the run goes on without waiting, and CI is watched
  after the PR is marked ready, as today. CI that never ran is shown as not
  monitored, never as green.
- **The old open-the-PR gate is an opt-in key** in `.auto-dev.yml`, off by
  default, for repos that must not push unreviewed code.
- **One round counter** replaces the five budget consumers. A plan revision, a
  fix loop and a red-CI fix each spend one round; the user can still add
  rounds at a budget stop.
- **One session.** The run goes straight through. The event checkpoint stays
  as the only session break; a happy 5.0 run is far below it.

### Workers

| Kept | High-risk only | Removed |
|---|---|---|
| profiler, planner, plan critic (new), acceptance tester, coder, verifier, reviewer (code and security), triager, lookup, fixer | panel code reviewers, review judge, security reviewer (the sensitive-path one when the plan has security criteria) | `define`, `define-reviewer`, `plan-reviewer`, `cleanup` |

Without `cleanup`, the coder runs the quality gate, and `next` confirms it by
running the profile's gate commands itself before the push. Whoever does
wave 5 checks that 4.18's command runner can do that; if it can't, say so in
the PR and keep a gate-only worker.

## The plan critic

Becomes `agents/plan-critic.md` in wave 3. It is a fresh agent: it gets the
ticket text, `PLAN.md` and read access to the repo, never the planner's notes
or reasoning. It writes a findings file and edits nothing else.

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
   touched and the plan doesn't say how it is handled, flag it. Say whether
   the plan's risk tier is right; raise it when it is too low.
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
changed parts and whether each blocker was fixed. A blocker still open goes to
the user at the post-plan gate; the workers don't loop.

The same principle (a fresh reader with a checklist, evidence required, a cap,
one round) applies to the reviewer in wave 5.

## Workstreams

Each workstream is one branch off `feat/release-5-0`, worked in its own
worktree, and lands by a squash-merged PR into `feat/release-5-0`, never
`main`. Each PR:

- passes the three checks in `CLAUDE.md`;
- updates `README.md` and the references for what it changes;
- deletes the evals, fixtures and tests of behavior it removes, and adds the
  ones for what it adds (not left for wave 6);
- gets a fresh-agent review before it opens;
- does **not** bump the version (wave 6 does that once; this is the one
  exception to the versioning rule in `CLAUDE.md`);
- leaves the release branch with a pipeline that works end to end.

`cmd_next.py`, `briefs.py` and the references are shared by nearly every
workstream, so they run in waves. A wave's branches are cut from the release
branch only after the wave before it has merged. While the release is open,
`main` takes critical fixes only, and is merged into the release branch after
each wave.

| Wave | Branch | Scope | Done when |
|---|---|---|---|
| 1 | `feat/strip-proposals` | Remove spec / plan / check proposals and rulings, the redo cascade, the deviation gate and the per-consumer budget; add the replacement rules (the coder's recorded deviations, a wrong criterion is a stop, one round counter). The largest wave: about a third of `cmd_next.py` and of `tests/test_next.py`. | smoke run passes |
| 2 | `feat/one-session` | Run straight through; keep the event checkpoint; simplify `HANDOFF.md` and `resume`. | smoke run passes in one session |
| 2 | `feat/early-draft-pr` | Commit, push and open the draft PR after the build's quality gate; the ready-for-review gate; the draft-CI grace rule; the opt-in open-the-PR gate key. | the first push comes before any review spawn |
| 3 | `feat/plan-critic` | Merge `define` into the planner (`PLAN.md`); add the plan critic; remove `define-reviewer` and `plan-reviewer`; open blockers fire the post-plan gate; the risk tier proposed, confirmed and re-checked by script. | smoke run passes |
| 4 | `feat/tests-first-open` | Commit the acceptance tests first; remove sealing and fold mode; `check-tests.py` guards those lines against the tests' commit; the coder sees `PLAN.md` and the tests whole. | smoke run passes |
| 5 | `feat/lean-review` | One verifier and one reviewer by default, alongside CI; panel, judge, security reviewer, mutation and probes for high-risk only; remove `cleanup`; one fix loop for findings and red CI; lower the xhigh efforts; the spawn-budget test. | 5 and 7 spawns hold in the test and the smoke run |
| 6 | `docs/release-5-0` | `UPGRADING.md` *Upgrading from 4.x*; `resume` refuses a 4.x run as it does a 3.x one; a final README and evals pass; version 5.0.0; the spawn-budget rule added to `CLAUDE.md`; delete this file. | release PR opens |

Wave 2's two branches run in parallel; their files barely overlap (`handoff`,
`resume` and the runbooks versus the ship steps).

**The smoke run.** After each wave, run three pipeline evals end to end on the
fixture repo (`tools/eval-run.py`): a small fix, a feature, and a high-risk
change. Record the worker spawns to first push and to ready-for-review in the
wave's PR. These numbers are the release's acceptance test.

**Rewrite checkpoint.** After wave 1 merges, look at what is left of
`cmd_next.py`. If the remaining flow is still tangled, write `next`'s decision
logic fresh for the 5.0 pipeline in the wave that would otherwise cut it up
again, instead of four more rounds of surgery. Decide it once, with the user,
before wave 2 starts.

**The spawn budget.** Wave 5 adds a test that walks `next` through a
default-lane happy path and fails when it takes more than 5 spawns to the
first push or 7 to ready-for-review. A later PR that adds a step has to raise
the number on purpose, in the open.

The release PR from `feat/release-5-0` to `main` is titled
`feat!: run a lean plan, build, ship pipeline (5.0.0)`.

## Decided

- A 4.x run in flight can't resume on 5.0 (breaking).
- The draft PR opens without asking; the gate moves to ready-for-review. The
  old gate is an opt-in key.
- Tests are not sealed. The loss is accepted; the verifier's probes cover
  high-risk tasks.
- No benchmark wave before the work starts. Timing benchmarks come later.
- Rewrite checkpoint (after wave 1): Phase 6 of `cmd_next.py` is written
  fresh in the 5.0 order in `feat/early-draft-pr` (draft PR, then review
  alongside CI, then the ready-for-review gate); phases 2–5 and the shared
  code stay and are changed in place by later waves.
- Wave 2's two branches run one after the other, early draft PR first, each
  cut from the release branch once the one before it merged.
