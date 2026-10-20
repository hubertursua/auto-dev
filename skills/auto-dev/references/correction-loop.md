# The correction loop and the iteration budget

Three things send work backwards: an unmet spec condition (or an unjustified
test-integrity finding, which the verifier reports alongside it), a must-fix
review finding, and a red CI check. A review finding comes from the code review panel
(`CODE_REVIEW.md`), the security review (`SECURITY_REVIEW.md`), a pre-existing
security finding the user chose to fix at the PR gate, or a human reviewer's
blocker on the PR. They are **one loop entered at three points**, and this file
is its single statement — `SKILL.md`, `references/subagent-prompts.md`, and
`references/gates-and-jira.md` point here instead of restating it.

## Contents

- **The loop** — the correction steps, and what each correction invalidates.
- **Stale results** — what to re-run when `scripts/check-fresh.py` finds a report
  that checked other code than the tree now holds.
- **Where the loop does not apply** — post-merge CI, plan deviations, review
  phases, and post-plan-gate revisions.
- **The iteration budget** — what spends a round, the accounting, and what to do
  on exhaustion.

## The loop

1. **Re-dispatch the coder** with the correction brief
   (`references/subagent-prompts.md`, _Acting on SPEC_EVAL.md_), pointed at the
   required-changes file the worker who found the problem wrote: the verifier's
   `evidence/corrections.md` (Phase 5), the review judge's
   `review/pass-<n>/corrections.md` or `review/security-corrections.md`
   (review findings), or the triager's `triage/ci-<n>.md` (red CI) or
   `triage/human-<n>.md` (a human blocker). Pass it unedited; you never write
   the changes yourself. One correction, one brief. The one exception: a
   finding about an **acceptance check itself** — the verifier's defective
   check, the judge's `acceptance-check` category, the triager's
   `ACCEPTANCE_CHECK` — is never the coder's to fix: the acceptance tester
   repairs it (`references/subagent-prompts.md`, _Acceptance tester_, repair
   mode), and may answer that it stands. It spends the same round.
2. **Spend a round** from the shared budget (below) *before* dispatching. At zero,
   do not dispatch — stop and report.
3. **Re-spawn the cleanup agent on the changed code** (`auto-dev:cleanup`,
   brief in `references/subagent-prompts.md`). It runs `/simplify` and then the
   quality gate to green, exactly as on its first pass, and rewrites `lint/`. In
   Phase 6 its `/simplify` is scoped to the files the correction changed (below;
   before the commit, that is the snapshot diff in `references/review.md`, not
   `git diff HEAD`). In
   Phase 5 the acceptance loop's corrections wait for the single cleanup pass
   that follows once the loop settles (Phase 5 steps 2–3), so do not spawn it per
   correction there. A Phase 5 correction made **after** that pass — a condition
   the verifier's re-check finds no longer met (`references/subagent-prompts.md`,
   _Re-verify after cleanup_) — does re-spawn it, with its Phase 5
   scope, before Phase 6; then re-verify again. **A cleanup re-spawn never spends the budget.** Do not
   re-run `gate` commands yourself as the correction's check; the cleanup agent
   does it. If it returns a check still at fail, the quality gate is red: stop and
   report, never ship red.
4. **Refresh whatever the correction invalidated — of what already exists.** See
   the table.
5. **Re-check the thing that failed:** re-spawn the verifier in re-check mode
   (`references/subagent-prompts.md`, _Verifier_), re-review the change
   (`references/review.md`), re-watch the check. A verifier re-spawn, like a
   review pass, never spends the budget.
6. **Repeat or exit.** If the re-check still fails, that is another correction:
   back to step 1. Exit only when the re-check passes; then resume the pipeline
   where the loop was entered.
   The budget is the bound — at zero, step 2 stops the loop.

Every Phase 6a "commit and re-push" in the table below uses the same
explicit-staging sequence, `.auto-dev/` check and `check-fresh.py --ref HEAD`
check before the push as the first commit (`references/phase-6-ship.md`, step 4), and runs only after step 3's re-spawned
cleanup agent returns every `gate` check green. The paths it stages are the files
`git status --porcelain --untracked-files=all --no-renames --ignore-submodules=dirty` shows the correction
changed (a deleted or renamed-away path included), and
those same paths are its `--expect` list:
`python3 <skill-dir>/scripts/check-staged.py <worktree> --expect <path> …`.
Commit only on exit `0`; handle `1`, `2` and `127` (no `python3`: the manual
check) exactly as that step says. A correction's commit gets no lighter check.

Step 4 is the only step that looks different at each entry point, and it differs
only because the entry points happen at different *times*. The rule is single: a
correction invalidates the evidence written before it, so rewrite that evidence.
Earlier in the pipeline there is less of it to rewrite.

| Entered at | Written by then | Refresh | `/simplify` |
|---|---|---|---|
| **Phase 5 — acceptance** (unmet or partial condition, unjustified integrity finding) | `SPEC_EVAL.md`, `evidence/`; the cleanup agent has not run | `SPEC_EVAL.md` and `evidence/` (the verifier's re-check rewrites both) | not yet run — the single cleanup pass after this loop settles simplifies corrective code with everything else |
| **Phase 5 — after the quality gate** (the verifier's re-check finds a condition no longer met) | `SPEC_EVAL.md`, `evidence/`, `lint/` | `lint/` (rewritten by the re-spawned cleanup agent), then the verifier's re-check again | **yes, Phase 5 scope** (the branch diff) — no human has read it yet |
| **Phase 6a — review** (a must-fix finding from the code review panel or the security review, or a pre-existing finding the user chose to fix at the PR gate; **before the commit**) | `SPEC_EVAL.md`, `lint/`, `CODE_REVIEW.md`, `SECURITY_REVIEW.md` | `lint/` (rewritten by the re-spawned cleanup agent), then steps 1–2 of _The Phase 6a refresh_ below (the verifier's re-check of every row), then **review again**: the code review panel on the files the fix changed, then the security review on the whole change (`references/review.md`). Nothing is committed, pushed or published yet, so the refresh stops there | **yes, scoped to the files the correction changed** — see below |
| **Phase 6a — CI red** (pre-merge), or **Phase 6c — a human reviewer's blocker** | `SPEC_EVAL.md`, `lint/`, the review reports, the commit, the push, the PR body | `lint/` (rewritten by the re-spawned cleanup agent), then _The Phase 6a refresh_ below: the verifier's re-check, a review of the correction, commit and re-push (CI re-runs — re-watch it), then the PR body | **yes, scoped to the correction's own diff** — see below |

**The Phase 6a refresh.** Every correction in Phase 6 runs it once the
re-spawned cleanup agent returns every `gate` check green, in this order. A
review-stage correction (before the commit) runs steps 1–2 only, then goes back
to the reviews, which are its re-check:

1. **Re-spawn the verifier in re-check mode** ("after a Phase 6 correction"). It
   re-runs the acceptance checks and the test audit and rewrites every row of
   `SPEC_EVAL.md`: a correction changes behavior on purpose, and a `met` condition
   can depend on a file its evidence never names. The `partial` and `unmet` rows
   are re-judged too — the correction may have supplied what they lacked.
2. **A condition no longer met, or a new unjustified integrity finding, joins the
   pending correction**, before anything is
   committed: back to step 1 of the loop, as another round of the same entry point
   (logged against the same consumer, #4 or #5 below). The cleanup re-spawn's scope
   (the files the corrections changed) then covers both corrections, and this
   refresh runs again. At zero budget, step 2 stops the loop: commit, push and edit
   nothing — after the commit, the open PR keeps describing the commit it carries —
   and report the condition, by number, as unmet at the gate (_On exhaustion_,
   below).
3. **Review the correction** before anything is committed
   (`references/review.md`, _Later corrections_): the code review panel on the
   uncommitted correction, then the security review on the whole change. A
   must-fix finding joins the pending correction, exactly as step 2 says, and
   exhaustion is handled the same way. Rewrite `CODE_REVIEW.md` and
   `SECURITY_REVIEW.md` with the new pass.
4. **Commit and re-push**, with the sequence above.
5. **Then refresh the PR body** — every section the pipeline writes, from the
   rewritten reports and their sources (`references/artifacts.md`, _The PR
   body_, _Where each part comes from_, and its _Links_ and _Size_ rules), with
   every link at the old commit pointing at the new one — starting from the live
   body (`gh pr view <pr> --json body`) so edits made on GitHub survive, and
   publish it with `gh pr edit <pr> --body-file <file>`, the file in
   `<artifact-dir>` or `$TMPDIR` (`references/phase-6-ship.md`, step 5). Only
   after the push, so the PR never shows results for a commit it does not carry,
   and only once `scripts/check-fresh.py <worktree> <artifact-dir> --ref HEAD`
   exits `0` (`references/artifacts.md`, _The PR body_).

**Why `/simplify` is scoped to the correction in Phase 6.** Corrective code needs
simplifying as much as any other code, so the cleanup agent re-runs after every
Phase 6 correction. But by then the reviewers, and maybe a human, have read the
branch's diff, and re-simplifying the whole branch would churn code they already
reviewed and cost more than it returns. So the re-spawned agent's `/simplify`
covers **only the files the correction changed**, and leaves the rest of the
branch alone. After the commit, that is the correction's own uncommitted diff.
Before the commit (a review-stage correction), `git diff HEAD` still shows the
whole change, so the scope comes from a snapshot of the working tree taken just
before the correction was dispatched (`references/review.md`, _What each review
pass covers_). The
quality gate after it still runs in full.

## Stale results

`scripts/check-fresh.py` exits `1` when a report checked other code than the
code now holds (`references/artifacts.md`, _Stamps: which code each result
checked_). The loop above never leaves one behind on its own, because every
correction re-runs its checks before the next step. So a stale report means the
code moved outside the pipeline: a person edited the worktree, a teammate pushed
to the PR branch, or GitHub merged the base into it. Its results describe code
that no longer exists. Produce them again before anything relies on them.

A run cut off between one of its own fixes and the fix's re-check also leaves
stale reports, but that code is the pipeline's: if the Notes record a correction
dispatched and not yet re-checked, resume that correction instead
(`references/review.md`, _The review loop_). Its refresh re-runs and restamps
every report.

1. **Bring in commits the PR has and the worktree lacks** (when the check ran
   with `--ref origin/<branch>`, after fetching both the branch and `<base>`):
   `git merge --ff-only origin/<branch>` in the worktree. Never rebase or reset.
   If it can't fast-forward, the worktree holds commits the PR doesn't: stop and
   report.
2. **Re-run the writer of each stale report, and of every report after it**, in
   this order, over the code as it stands. None of these spends a round; they are
   checks:
   - `lint/*.md` → the cleanup agent with the _Outside changes_ scope
     (`references/subagent-prompts.md`, _Cleanup agent_): it skips `/simplify`,
     since a person wrote this code and it isn't the pipeline's to rewrite, and
     runs the quality gate in full.
   - `SPEC_EVAL.md` → the verifier in re-check mode ("after changes made outside
     the pipeline").
   - `CODE_REVIEW.md` → a code review panel pass (`references/review.md`, _What
     each review pass covers_, the stale-results row). Work out its files only
     now, after the two re-runs above, so it also covers any fix the cleanup
     agent made: `git diff --name-only <the report's old stamp> <the tree now>`,
     leaving out files that are not part of the change (`git diff --name-only
     $(git merge-base origin/<base> HEAD)`), such as files a merge of the base
     brought in. Use the whole change when the report had no stamp or git no
     longer holds its tree.
   - `SECURITY_REVIEW.md` → the security review on the whole change.

   After a `--phase 5` check, re-run only the first two now; the check before
   the PR gate covers the reviews.
3. **What they find is handled as usual.** An unmet condition or a must-fix
   finding is a correction: it enters the loop above at its usual point and
   spends a round there. A quality gate the cleanup agent can't get green is a
   stop-and-report, as always.
4. **After the commit, publish the result.** If the re-runs changed code (a
   quality-gate fix, a correction), commit and push it as _The Phase 6a refresh_,
   step 4, does. Whenever the PR's head moved, by your push or someone else's,
   watch CI on the new head (`references/gates-and-jira.md`). Either way, refresh
   the PR body (step 5): it described the old code.
5. **Run the check again.** On `0`, carry on from where the check fired. A
   report stale again straight after its own re-run means something rewrites the
   code on every run (a test writing files outside `.gitignore`, say): stop and
   report, naming the files the check lists.

## Where the loop does not apply

- **Post-merge CI failures (Phases 6b–6c).** No human gate is left to hold, and
  re-pushing the branch cannot fix merged code. Report and stop; recovery is the
  user's call (`references/gates-and-jira.md`).
- **Plan deviations reported by the coder (Phase 4).** Information, not defects;
  the verifier judges the code against the spec and never sees them. Do not spend
  budget reconciling code with a plan it improved on. (A `BLOCKED` step is
  different: it is a correction, consumer #3.)
- **A `manual` verdict, or an Edge left for a person.** Nothing the coder
  writes makes it observable here: a `manual` condition, or the Edge of a met
  condition that `SPEC_EVAL.md`'s _Unresolved_ leaves for a person, goes to the
  PR gate as a check for a human, and to the PR body's _Checks for a person_.
- **The two review phases (Define, plan).** You apply their findings by editing
  the artifact; no agent is re-dispatched. They still spend a round.
- **A plan revision the user asks for at the post-plan gate.** The planner
  revises `IMPLEMENTATION.md` from their direction and the gate re-fires. Nothing is being
  corrected and no round is spent (`references/gates-and-jira.md`).

## The iteration budget

**One budget of revise rounds shared by the two review loops and the correction
loop** — not a cap per loop. Default **4**; override with `iteration_budget:` in
`.auto-dev.yml` (`references/profiles.md`), resolved in Phase 1 and recorded in `profile.md`.

Five things spend it, one round each:

| # | Consumer | Phase |
|---|---|---|
| 1 | Define review — re-review after fixes | 2 |
| 2 | Plan review — re-review after fixes, and an acceptance-tester re-spawn to fill a gap in its return (coverage, a level, or a base run that failed for the wrong reason; a re-spawn after a post-plan-gate revision spends none, like the revision) | 3 |
| 3 | Build and acceptance corrections to the coder — an unmet or partial condition (a surviving mutant's test gap included), an unjustified integrity finding, an install conflict, a `BLOCKED` step (with its plan revision) — and an acceptance-check repair in Phase 4–5 | 4–5 |
| 4 | Review-finding corrections — code review panel, security review, a pre-existing security finding the user chose to fix, or a human reviewer's blocker | 6a, 6c |
| 5 | CI-red corrections, pre-merge | 6a |

**Review and verifier passes never spend it** — not the first code review,
security review or verifier pass, and not the re-review or re-check after a
correction. A review is a check, like the quality
gate; the correction that triggered the re-review already spent its round, and
that is what bounds the loop. One correction brief covers every open must-fix
finding from one review pass, so a pass with three must-fix findings spends one
round, not three.

**The cleanup agent never spends it** — not its Phase 5 pass, not its own loop to
green however many times it re-runs a `gate` command internally (it has no view of
the budget and is never told one), and not a re-spawn after a later Phase 5
correction or a Phase 6a correction.
It has to run whenever code changes, so it is not rationed; the coder correction
that changed the code is what spends the round. Its own retries are capped instead,
at 3 fix attempts per failing check per spawn (`references/subagent-prompts.md`).

**Accounting.** A round is spent by each **re-spawn or re-run for correction**,
except a cleanup-agent re-spawn; the first pass through a phase is not a round.
Decrement **before** dispatching, and write the new remaining count to `WORK_LOG.md` in the same update that records
what the round bought. Read the remaining count before every dispatch — at zero,
the loop does not run.

**On exhaustion, stop and report.** Never loop past it and never merge over it.
Say which loop ran it out, what is still unfixed, and what was tried — naming each
unmet condition, not summarizing them. Where exhaustion coincides with a gate — must-fix findings still open, CI still
red — surface it **at that gate** and let the user decide, rather than holding
silently. Must-fix findings still open when the review loop runs out of budget go
to the PR gate, named one by one, and into the PR body if the user opens it
anyway.
