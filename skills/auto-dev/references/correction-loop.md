# The correction loop and the iteration budget

Three things send work backwards: an unmet spec condition, a PR-review blocker
(from `PR_REVIEW.md` or from a human reviewer on the PR), and a red CI check. They are **one loop entered at three points**, and this file
is its single statement — `SKILL.md`, `references/subagent-prompts.md`, and
`references/gates-and-jira.md` point here instead of restating it.

## Contents

- **The loop** — the correction steps, and what each correction invalidates.
- **Where the loop does not apply** — post-merge CI, plan deviations, review
  phases, and post-plan-gate revisions.
- **The iteration budget** — what spends a round, the accounting, and what to do
  on exhaustion.

## The loop

1. **Re-dispatch the coder** with a targeted correction brief (template in
   `references/subagent-prompts.md`, under Phase 5). Describe the required
   behavior concretely; never quote the spec verbatim. One correction, one brief.
2. **Spend a round** from the shared budget (below) *before* dispatching. At zero,
   do not dispatch — stop and report.
3. **Re-spawn the cleanup agent on the changed code** (`auto-dev:cleanup`,
   brief in `references/subagent-prompts.md`). It runs `/simplify` and then the
   quality gate to green, exactly as on its first pass, and rewrites `lint/`. In
   Phase 6a its `/simplify` is scoped to the correction's own diff (below). In
   Phase 5 the acceptance loop's corrections wait for the single cleanup pass
   that follows once the loop settles (Phase 5 steps 2–3), so do not spawn it per
   correction there. A Phase 5 correction made **after** that pass — a condition
   the evidence re-resolve finds no longer met (`references/subagent-prompts.md`,
   _Re-resolve the acceptance evidence_) — does re-spawn it, with its Phase 5
   scope, before Phase 6; then re-resolve again. **A cleanup re-spawn never spends the budget.** Do not
   re-run `gate` commands yourself as the correction's check; the cleanup agent
   does it. If it returns a check still at fail, the quality gate is red: stop and
   report, never ship red.
4. **Refresh whatever the correction invalidated — of what already exists.** See
   the table.
5. **Re-check the thing that failed:** re-evaluate the condition, re-read the
   blocker, re-watch the check.
6. **Repeat or exit.** If the re-check still fails, that is another correction:
   back to step 1. Exit only when the re-check passes; then resume the pipeline
   where the loop was entered.
   The budget is the bound — at zero, step 2 stops the loop.

Every Phase 6a "commit and re-push" in the table below uses the same
explicit-staging sequence and `.auto-dev/` check as the first commit
(`references/phase-6-ship.md`, step 2), and runs only after step 3's re-spawned
cleanup agent returns every `gate` check green. The paths it stages are the files
`git status --porcelain --untracked-files=all --no-renames --ignore-submodules=dirty` shows the correction
changed (a deleted or renamed-away path included), and
those same paths are its `--expect` list:
`python3 <skill-dir>/scripts/check-staged.py <worktree> --expect <path> …`.
Commit only on exit `0`; handle `1`, `2` and `127` (no `python3`: the manual
check) exactly as step 2 says. A correction's commit gets no lighter check.

Step 4 is the only step that looks different at each entry point, and it differs
only because the entry points happen at different *times*. The rule is single: a
correction invalidates the evidence written before it, so rewrite that evidence.
Earlier in the pipeline there is less of it to rewrite.

| Entered at | Written by then | Refresh | `/simplify` |
|---|---|---|---|
| **Phase 5 — acceptance** (unmet condition) | nothing; the cleanup agent has not run | `SPEC_EVAL.md` only | not yet run — the single cleanup pass after this loop settles simplifies corrective code with everything else |
| **Phase 5 — after the quality gate** (re-resolving the evidence finds a condition no longer met) | `SPEC_EVAL.md`, `lint/` | `SPEC_EVAL.md`, then `lint/` (rewritten by the re-spawned cleanup agent), then re-resolve the evidence again | **yes, Phase 5 scope** (the branch diff) — no human has read it yet |
| **Phase 6a — PR review** (blocker, adversarial or human) | `lint/`, the commit, the PR body | `lint/` (rewritten by the re-spawned cleanup agent) and the PR body's quality-gate results, then commit and re-push (CI re-runs — re-watch it) | **yes, scoped to the correction's own diff** — see below |
| **Phase 6a — CI red** (pre-merge) | `lint/`, the commit, the push, the PR body | `lint/` (rewritten by the re-spawned cleanup agent) and the PR body's quality-gate results, then commit and re-push | **yes, scoped to the correction's own diff** |

**Why `/simplify` is scoped to the correction in Phase 6.** Corrective code needs
simplifying as much as any other code, so the cleanup agent re-runs after every
Phase 6a correction. But by then a human may have read the branch's diff, and
re-simplifying the whole branch would churn code they already reviewed and cost
more than it returns. So the re-spawned agent's `/simplify` covers **only the files
the correction changed**, the correction's own uncommitted diff, and leaves the
rest of the branch alone. The quality gate after it still runs in full.

## Where the loop does not apply

- **Post-merge CI failures (Phases 6b–6c).** No human gate is left to hold, and
  re-pushing the branch cannot fix merged code. Report and stop; recovery is the
  user's call (`references/gates-and-jira.md`).
- **Plan deviations reported by the coder (Phase 4).** Information for the
  acceptance check, not defects. Do not spend budget reconciling code with a plan
  it improved on.
- **The two review phases (Define, plan).** You apply their findings by editing
  the artifact; no agent is re-dispatched. They still spend a round.
- **A plan revision the user asks for at the post-plan gate.** You edit
  `IMPLEMENTATION.md` from their direction and re-fire the gate. Nothing is being
  corrected and no round is spent (`references/gates-and-jira.md`).

## The iteration budget

**One budget of revise rounds shared by the two review loops and the correction
loop** — not a cap per loop. Default **4**; override with `iteration_budget:` in
`.auto-dev.yml` (`references/profiles.md`), resolved in Phase 1 and recorded in `profile.md`.

**The budget is per task, and on a multi-PR run that means per sub-task.** Each
sub-task starts with a fresh `iteration_budget` and tracks what it has left in the
ledger's `budget` column (`references/artifacts.md`). A single run-wide budget would
let the first sub-task spend every round and leave the rest with no corrections at
all — four rounds shared across six sub-tasks bounds nothing useful.

Five things spend it, one round each:

| # | Consumer | Phase |
|---|---|---|
| 1 | Define review — re-review after fixes | 2 |
| 2 | Plan review — re-review after fixes | 3 |
| 3 | Acceptance corrections to the coder | 5 |
| 4 | PR-review blocker corrections — adversarial or human | 6a |
| 5 | CI-red corrections, pre-merge | 6a |

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
unmet condition, not summarizing them. Where exhaustion coincides with a gate — blockers still
open, CI still red — surface it **at that gate** and let the user decide, rather
than holding silently.
