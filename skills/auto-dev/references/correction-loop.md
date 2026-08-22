# The correction loop and the iteration budget

Three things send work backwards: an unmet spec condition, a PR-review blocker
(from `PR_REVIEW.md` or from a human reviewer on the PR), and a red CI check. They are **one loop entered at three points**, and this file
is its single statement — `SKILL.md`, `references/subagent-prompts.md`, and
`references/gates-and-jira.md` point here instead of restating it.

## The loop

1. **Re-dispatch the coding agent** with a targeted correction brief (template in
   `references/subagent-prompts.md`, under Phase 5). Describe the required
   behavior concretely; never quote the spec verbatim. One correction, one brief.
2. **Spend a round** from the shared budget (below) *before* dispatching. At zero,
   do not dispatch — stop and report.
3. **Re-run the affected `gate` commands yourself.** You have Bash. The cleanup
   agent is spawned exactly **once** per task and a correction never brings it
   back.
4. **Refresh whatever the correction invalidated — of what already exists.** See
   the table.
5. **Re-check the thing that failed:** re-evaluate the condition, re-read the
   blocker, re-watch the check.

Step 4 is the only step that looks different at each entry point, and it differs
only because the entry points happen at different *times*. The rule is single: a
correction invalidates the evidence written before it, so rewrite that evidence.
Earlier in the pipeline there is less of it to rewrite.

| Entered at | Written by then | Refresh | `/simplify` |
|---|---|---|---|
| **Phase 5 — acceptance** (unmet condition) | nothing; the cleanup agent has not run | `SPEC_EVAL.md` only | not yet run — it runs once after this loop settles, so corrective code gets simplified with everything else |
| **Phase 6a — PR review** (blocker, adversarial or human) | `lint/`, the commit, the PR body | the affected `lint/<CHECK>.md`, and the PR body's gate results | **no** — see below |
| **Phase 6a — CI red** (pre-merge) | `lint/`, the commit, the push, the PR body | the affected `lint/<CHECK>.md` and the PR body's gate results, then commit and re-push | **no** |

**Why `/simplify` never re-runs in Phase 6.** A blocker fix is small and targeted;
re-simplifying already-reviewed code churns a diff a human has read and costs more
than it returns. The consequence is explicit and accepted: **Phase 6 corrective
code is gate-verified but not simplified.**

## Where the loop does not apply

- **Post-merge CI failures (Phases 6b–6c).** No gate is left to hold, and
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

**One budget of revise rounds shared by every corrective loop** — not a cap per
loop. Default **4**; override with `iteration_budget:` in `.auto-dev.yml`
(`references/profiles.md`), resolved in Phase 1 and recorded in `profile.md`.

**The budget is per task, and on a multi-PR run that means per sub-task.** Each
sub-task starts with a fresh `iteration_budget` and tracks what it has left in the
ledger's `budget` column (`references/artifacts.md`). A single run-wide budget would
let the first sub-task spend every round and leave the rest with no corrections at
all — four rounds shared across six sub-tasks bounds nothing useful.

Six things spend it, one round each:

| # | Consumer | Phase |
|---|---|---|
| 1 | Define review — re-review after fixes | 2 |
| 2 | Plan review — re-review after fixes | 3 |
| 3 | Acceptance feedback into the coder | 5 |
| 4 | Quality-gate fixes — a *re-spawn* of the cleanup agent after its first pass | 5 |
| 5 | PR-review blocker corrections — adversarial or human | 6a |
| 6 | CI-red corrections, pre-merge | 6a |

The cleanup agent's own loop to green (Phase 5, step 3) is that phase's first pass
and spends nothing, however many times it re-runs a gate command internally — it has
no view of the budget and is never told one. Row 4 is the orchestrator **re-spawning**
it, or running gate commands itself, after a correction.

**Accounting.** A round is spent by each **re-spawn or re-run for correction**;
the first pass through a phase is not a round. Decrement **before** dispatching,
and write the new remaining count to `WORK_LOG.md` in the same update that records
what the round bought. Read the remaining count before every dispatch — at zero,
the loop does not run.

**On exhaustion, stop and report.** Never loop past it and never merge over it.
Say which loop ran it out, what is still unfixed, and what was tried — naming each
unmet condition, not summarizing them. Where exhaustion coincides with a gate — blockers still
open, CI still red — surface it **at that gate** and let the user decide, rather
than holding silently.
