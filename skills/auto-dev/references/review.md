# Phase 6a review: code review panel, then security review

Phase 6a starts with two reviews. Both run on the uncommitted working tree,
before the PR gate. Nothing is committed or pushed until both are finished and
the user approves at the PR gate. The order never changes:

1. **Code review panel:** three independent reviewers, a judge, and re-votes on
   findings only one reviewer raised.
2. **Security review:** one reviewer, plus a judge check on every finding that
   would block.

This file is the single statement of both steps and of **the rubric** that
decides which findings must be fixed and which are noise. `SKILL.md`,
`references/phase-6-ship.md`, `references/correction-loop.md` and
`references/subagent-prompts.md` point here. The briefs are in
`references/subagent-prompts.md`, under _Phase 6 — Ship_. The report templates
are in `references/artifacts.md`.

## Contents

- **Why the reviews run before the commit**
- **What each review pass covers**
- **Step 1: the code review panel**: reviewers, judge, re-votes, applying the
  votes.
- **Step 2: the security review**: reviewer, verification.
- **The review loop**: how fixes cycle back through both steps, and when it exits.
- **The rubric**: code findings, security findings, confidence levels.
- **Later corrections**: CI red and human blockers get the same review.

## Why the reviews run before the commit

- **The user approves with the findings in hand.** The PR gate summary carries
  both reports, so the user is never asked to open a PR that has not been
  reviewed.
- **Fixes stay local.** Every finding is fixed before the first push, so the PR
  does not collect review-fix commits and CI does not re-run for each fix.
- **`/code-review` reviews the current uncommitted diff by default.** Nothing is
  committed before the PR gate, so on the first pass that diff is the whole
  change.

## What each review pass covers

First mark untracked files intent-to-add, or new files are invisible to every
diff (the same line Phase 5 uses):

```bash
git ls-files -z --others --exclude-standard | xargs -0 git add -N --
```

| Pass | Code review panel covers | Security review covers |
|---|---|---|
| **First pass** | the whole change: the uncommitted working tree against `HEAD` (nothing on the branch is committed yet) | the whole change |
| **After a review-stage fix** (before the commit) | **only the files the fix changed**, from the snapshot diff below — never from the coder's return alone, and not from `git status`, which before the commit lists the whole change | the whole change |
| **After a CI-red or human-blocker fix** (after the commit) | the fix: the uncommitted working tree against `HEAD` | the whole change |
| **Stale results** (the code changed outside the pipeline, `references/correction-loop.md`, _Stale results_) | the files changed since `CODE_REVIEW.md`'s stamp that are part of the change: tell the reviewers to read `git diff <stamp>` for them. The whole change if the report had no usable stamp | the whole change |

**The snapshot diff (review-stage fixes only).** Before the commit, nothing in
git separates the fix from the rest of the change, so take a snapshot of the
working tree just before dispatching each review-stage correction, and diff
against it afterwards. The snapshot is the working tree's tree hash, the same
one every report is stamped with (`references/artifacts.md`, _Stamps: which code
each result checked_, which also gives the by-hand command without `python3`).
Taking it leaves the real index, the working tree and the branch untouched, and
`.auto-dev/` stays out.

```bash
snap() { python3 <skill-dir>/scripts/check-fresh.py --print-tree <worktree>; }
before=$(snap)     # just before dispatching the correction; record it in the Notes
# … the coder applies the fix …
git diff --name-only "$before" "$(snap)"     # the files the fix changed
```

That list is the scope of the cleanup re-spawn and the next panel pass. If it
misses a file the coder's return names, add that file too.

**One snapshot per pending correction, not per dispatch.** When a further round
joins a correction that has not been reviewed yet (the verifier re-check finds
a condition no longer met, `references/correction-loop.md`, _The Phase 6a
refresh_, step 2), do **not** take a new snapshot: keep the one taken before the
first of them, so the diff covers every chained correction's files. Take a new
snapshot only after a panel pass has reviewed the previous one.

"The whole change" for the security review is everything since the branch left
its base, committed or not: `git diff $(git merge-base origin/<base> HEAD)`.
The security review always covers the whole change. A fix in one file can open a
hole that only shows up through another file.

## Step 1: the code review panel

1. **Make the pass directory:** `mkdir -p <artifact-dir>/review/pass-<n>`, with
   `<n>` counting up from 1 for each code-review pass in this task. Record the pass
   number and its scope in the Phase 6 row's Notes in `WORK_LOG.md`.
2. **Note the tree** the panel will review
   (`scripts/check-fresh.py --print-tree <worktree>`) for the judge's brief
   (`references/artifacts.md`, _Stamps_). Then **spawn three code reviewers in parallel**, all in one message:
   `auto-dev:code-reviewer`, review mode. The briefs are identical except for the
   slot (`R1`, `R2`, `R3`). Each reviewer runs `/code-review xhigh` on the pass's
   scope and writes `review/pass-<n>/R<k>.md`. The reviewers never see each
   other's reports. Independent agreement only counts when it is independent.
3. **A reviewer that fails** (it errors, times out, or writes no usable report)
   gets one re-spawn. If it fails again, carry on with the reports you have and
   record the gap. The judge lowers the overall confidence (_The rubric_). With
   fewer than two usable reports, the panel has nothing to cross-check: no
   finding can reach two votes, so none is must-fix; the judge still confirms or
   refutes each one, the overall confidence is Low, and the PR gate shows that as
   a warning.
4. **Spawn the judge** (`auto-dev:review-judge`, consolidate brief). It reads
   every `R<k>.md`, merges duplicates, checks each trigger path itself, applies
   the rubric, and writes `CODE_REVIEW.md`. On pass 2 or later it also re-checks
   every must-fix finding from earlier passes against the current code and marks
   each one `fixed` or `open`.
5. **Re-vote on lone findings.** The judge marks `re-vote` on a correctness or
   test finding that only one reviewer raised and whose trigger path the judge
   confirmed. For each reviewer slot **that wrote a usable report this pass**,
   collect the re-vote findings that slot did **not** raise, and spawn one
   `auto-dev:code-reviewer` in re-vote mode per such slot that has any, all in
   parallel. A slot whose reviewer failed never re-votes: a fresh agent in its
   place would add a voter the panel never had. With only one usable report
   there is no one to re-vote, and every lone finding stays advisory. Each one writes `review/pass-<n>/VOTES-R<k>.md`
   with `agree` or `disagree` and a reason for each finding. A re-voter is told
   the finding, not who raised it or how anyone else voted.
6. **Apply the votes** with `autodev.py votes --apply` (`votes --plan` names
   the re-voters to spawn in step 5). For each re-vote finding it counts the
   reviewer who raised it plus every `agree`. With 2 or more, it is
   **must-fix, Medium**. With fewer, it is **advisory, Low**. It writes the
   verdict, the vote count and the confidence into `CODE_REVIEW.md`, updates
   the header, and adds each new must-fix finding's required change to
   `review/pass-<n>/corrections.md`.
7. **Security leads.** The panel is told not to review security. Any security
   finding a reviewer raises anyway is listed by the judge under
   `Security leads`. Pass each one to Step 2's brief to check. The panel never
   decides them.
8. **Open must-fix findings** go to the correction loop
   (`references/correction-loop.md`, entry _Phase 6a — review_): one correction
   brief per pass, covering every open must-fix finding, pointed at the judge's
   `review/pass-<n>/corrections.md`. Take the snapshot
   (_What each review pass covers_) just before dispatching it. Then run Step 1
   again, scoped to the files the snapshot diff names. Exit Step 1 only when a pass leaves no
   open must-fix finding, or the budget runs out.

## Step 2: the security review

1. **Spawn the security reviewer,** with the tree you note just before it
   (`scripts/check-fresh.py --print-tree <worktree>`) in its brief. Use `auto-dev:security-reviewer-sensitive`
   when `SPEC.md`'s `Security/Compliance criteria` section lists controls for a
   sensitive path, and `auto-dev:security-reviewer` otherwise. It runs
   `/security-review` over the whole change, checks the panel's security leads,
   classifies each finding with the rubric, and writes `SECURITY_REVIEW.md`. On a
   repeat run it marks each earlier must-fix finding `fixed` or `open`.
2. **Verify every finding rated High or Medium**, introduced or pre-existing.
   Only one agent reviews security, so nothing votes on it. Instead, spawn
   `auto-dev:review-judge` (security-verify brief) once for all of them. It traces
   each path in the code and writes `confirmed` or `refuted`, with a reason, into
   the finding's `Verified` cell. A refuted finding becomes advisory.
3. **Confirmed must-fix findings** (introduced by this change, High or Medium)
   go to the correction loop, entry _Phase 6a — review_. After the fix, go back to
   **Step 1**, scoped to the files the fix changed, because a security fix can
   introduce a bug. Then run Step 2 again on the whole change.
4. **Pre-existing findings** (High or Medium, confirmed) never block and are
   never fixed in this PR. They go to the PR gate, where the user sends each to a
   separate PR or ignores it (`references/gates-and-jira.md`, _PR gate_).

## The review loop

```
Step 1 (panel → judge → re-votes) ──must-fix──► fix ──► Step 1 on the fix's files
   │ none open
   ▼
Step 2 (security → verify) ──must-fix──► fix ──► Step 1 on the fix's files ──► Step 2
   │ none open
   ▼
PR gate
```

- Each correction spends one round of the shared iteration budget, before it is
  dispatched. **Review passes never spend a round.** They are checks, like the
  cleanup agent, and only a correction triggers another pass. That is what keeps
  the loop bounded.
- **On exhaustion,** stop correcting and go to the PR gate with the open must-fix
  findings listed (`references/correction-loop.md`, _On exhaustion_). Never
  commit over them silently.
- **Record each step's outcome** in the Phase 6 row's Notes, for example
  `code review pass 2: done, 0 open` or `security review: done, 1 pre-existing`,
  and each correction when it is dispatched, for example
  `correction for pass 2 (C1, C3): dispatched, round spent, snapshot <tree>`.
  A resumed run re-runs any review step whose completion the Notes do not record.
  A half-written report cannot be told apart from a finished one.
- **Resuming mid-correction.** If the Notes show a correction dispatched and no
  review pass after it, the fix may be half-applied in the working tree.
  Re-dispatch the same correction to the coder against the tree as it stands,
  **without spending another round** (the Notes show it was spent), then carry on
  with the cleanup re-spawn, the verifier re-check (the Phase 6a refresh, steps
  1–2, `references/correction-loop.md`) and the re-review. Scope them by diffing against the
  snapshot the Notes recorded, not a new one, so the files the interrupted
  attempt changed are covered too.

## The rubric

The rubric that sorts must-fix findings from noise, with its confidence levels,
is in `templates/rubric.md`. The code reviewers, the judge and the security
reviewer read it there; it is stated nowhere else.

## Later corrections

Every correction made after the PR gate (a red CI check before the merge, or a
human reviewer's blocker at 6c) is reviewed the same way before it is committed
and pushed. Step 1 runs on the uncommitted fix, then Step 2 runs on the whole
change. Must-fix findings from those passes are another round of the same
correction. The order is in `references/correction-loop.md`, _The Phase 6a
refresh_.
