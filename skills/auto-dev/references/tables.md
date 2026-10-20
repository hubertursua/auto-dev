# Shared tables

The facts all three runbooks rely on, stated once. `autodev.py next` applies
every rule here by itself; this file is for explaining a stop or a question to
the user, and for the few steps `next` hands to you.

## Contents

- [The iteration budget](#the-iteration-budget)
- [Stop conditions](#stop-conditions)
- [Hold and Stop](#hold-and-stop)
- [What each gate option does](#what-each-gate-option-does)
- [Freshness: when a report no longer matches the code](#freshness-when-a-report-no-longer-matches-the-code)
- [Lookups](#lookups)

## The iteration budget

One budget of revise rounds per task: `iteration_budget` in `.auto-dev.yml`,
default 4. `next` spends a round before the action that needs it and prints a
`BUDGET:` line when it does. You never spend one yourself.

| Consumer | Spends a round on | When none is left |
|---|---|---|
| 1 | a Define re-review after its FIX blocks applied | stop; report the Define review's open blockers one by one |
| 2 | a plan re-review, or re-spawning the acceptance tester for gaps | stop; report the plan review's open blockers or the gaps one by one |
| 3 | a correction after verification, a re-dispatched `BLOCKED` step, an acceptance-check repair | stop; report each unmet condition by name and what was tried; no cleanup, no Phase 6 |
| 4 | a correction for a review finding or a human reviewer's blocker | before the commit: `next` goes on to the PR gate, whose summary names every open must-fix finding. After it: stop; report every open must-fix finding by name |
| 5 | a correction for red CI caused by the code | stop; report each red check. Never merge over it |

Free (no round): the first review of anything, every verifier re-check, every
cleanup run, a user's "Revise plan" at the post-plan gate, and a re-spawn after
a worker failed once.

## Stop conditions

Each one ends with `next` exiting 4 (or the command named exiting 1). Tell the
user the `REPORT` lines and do nothing more. The worktree and `.auto-dev/` stay.

| # | Condition | Detected by |
|---|---|---|
| 1 | `gh` missing or signed out, `origin` not on GitHub, python3 < 3.9 or no PyYAML | `init` exit 1 |
| 2 | invalid `.auto-dev.yml` or saved profile, no test command in the quality gate | `init` exit 1 |
| 3 | worktree path taken, a seeded file not gitignored, a setup command missing or failing | `init` exit 1 |
| 4 | the run was started on auto-dev 3.x | `resume` prints `OLD-VERSION` |
| 5 | the task is too big for one PR | Define returns `OVERSIZED` |
| 6 | a worker stopped on purpose, or failed twice running (lifted by `auto-dev continue`) | `record` logs `blocked` or a second `failed` |
| 7 | a worker was spawned three times and never left a result `record` accepts (lifted by `auto-dev continue`) | `next` |
| 8 | a reviewer found blockers but wrote no FIX block | `next` |
| 9 | the planner judged the spec impossible to meet | planner returns `SPEC_IMPOSSIBLE` |
| 10 | the quality gate can't be made green | cleanup returns `RED` |
| 11 | the mutation step may have left a planted change in the source | verifier returns `MUTATION_LEFT_CHANGES` |
| 12 | the budget ran out (consumers 1–3; 4 and 5 after the commit) | `next`, per the table above |
| 13 | a report is stale again right after its own re-run | `check-fresh`, inside `next` |
| 14 | no code reviewer wrote a usable report, twice | `next` |
| 15 | the commit failed, or does not carry the checked code | `commit` exit 1 or 3, then `next` |
| 16 | CI is red for a reason the code can't fix: a secret or credential (`SECRET`), infrastructure (`INFRA`), a flaky test (`FLAKY`) or no clear cause (`UNKNOWN`). Reported before Jira moves to In Review or staging is asked. Lifted by `auto-dev continue` once the cause is fixed and CI re-run: CI is watched again | triager's CI mode |
| 17 | the staging merge conflicted or its push was rejected | `merge-staging` exit 1 or 3, then `next` |
| 18 | someone pushed commits to the PR branch the pipeline didn't check. Lifted once the user fast-forwards the worktree to `origin/<branch>` (`git merge --ff-only`, which the report names) and says `auto-dev continue`: the commits are re-checked, then the main gate is asked again | `check-fresh --ref`, inside `next` |
| 19 | CI is red at the main gate | `next` |
| 20 | GitHub refused or only queued the merge | `merge-pr` exit 3 or 4, then `next` |
| 21 | the user chose Stop at a gate or pause | `gate … stop` |

## Hold and Stop

They are different states.

- **Hold** pauses the run at one gate: the PR gate or the main gate. The phase is `held`. Starting a new session and saying
  `auto-dev continue` asks **that gate** again, starting with its checks, since
  the code may have changed meanwhile.
- **Stop** ends the run. The phase is `stopped`. Nothing resumes it: `resume`
  reports it as `FINISHED`. This is a gate's `Stop` answer.

Every other stop (exit 4) leaves the phase open, and `next` decides again in
the next session:

- A stop on a **worker** (#6, #7), a refused `pr publish`, and a red CI run the
  code can't fix (#16) are lifted when the user fixes the cause and says
  `auto-dev continue`: the worker is spawned again, the PR published again, or
  CI watched again. A session that ended at a checkpoint (`handoff
  --checkpoint`) lifts nothing: it ended at a clean point, with no stop to
  lift, so a worker that failed once before it and once after still stops.
- A stop on a **result** stays: a red quality gate (#10), an impossible spec
  (#9), a mutation that may have left changes (#11), the budget used up (#12).
  A resumed run stops at the same place.

## What each gate option does

`next` prints the gate's question and one `AFTER` line per option. Run the line
for the option the user picked, filling in `<the user's words>` or `<why>` with
what they said, then run `next`.

| Gate (when) | Option | Records | Then |
|---|---|---|---|
| Jira (Phase 2, with a ticket, once the size check says FITS) | Move it | `gate jira proceed` | you move the ticket; Jira moves at each later milestone too |
| | Leave Jira alone | `gate jira leave` | no Jira move for the rest of the run |
| | Stop | `gate jira stop` | the run stops |
| Post-plan (Phase 3; on when `HIGH_RISK` or `gates.post_plan: true` in `.auto-dev.yml`) | Approve & build | `gate post-plan proceed` | Phase 3 ends; the session hands off |
| | Revise plan (tell me what to change) | `gate post-plan revise --reason "<the user's words>"` | the planner revises (no round); if its entry points changed the tester repairs the checks; the gate is asked again |
| | Stop | `gate post-plan stop` | the run stops |
| PR (Phase 6, once the reviews settle) | Open PR | `gate pr proceed` | commit, push, open the PR |
| | Hold (don't push yet) | `gate pr hold --reason "<why>"` | the run is held at the PR gate |
| | Stop | `gate pr stop --reason "<why>"` | the run stops; nothing is pushed |
| Staging (Phase 6, only with a staging branch) | Merge to staging | `gate staging proceed` | direct merge into staging, then its CI is watched |
| | Skip staging | `gate staging skip` | straight on to the main gate |
| | Stop | `gate staging stop --reason "<why>"` | the run stops |
| Main (Phase 6, once CI and human comments are settled) | Merge PR to main | `gate main proceed` | `merge-pr`, then Jira Done and the final report |
| | Hold | `gate main hold --reason "<why>"` | the run is held at the main gate |
| | Stop | `gate main stop --reason "<why>"` | the run stops; the PR stays open |
| Worktree (after the final report) | Remove it / Keep it | `gate cleanup proceed` / `keep` | the worktree (and `.auto-dev/`) is removed or kept |

The PR gate may add a question per pre-existing security finding (the two most
severe on their own, the rest grouped as `Others`): `Separate PR (note it as a
follow-up)` · `Ignore it`. This PR never fixes a pre-existing finding. Each
answer's `AFTER` line is `autodev.py mark triage-<ID> --value separate|ignore`:
run the one for each answer the user gave. A `separate` finding is listed in
the PR body and the final report as a follow-up for its own PR; the pipeline
doesn't open that PR.

The profile confirmation (Phase 1) has its own options: `S1-plan.md`, step 4.

## Freshness: when a report no longer matches the code

Every report stamps the code it checked (`Tree:` lines, from `check-fresh.py
--print-tree`). `next` and the Phase 6 commands run `check-fresh.py` at these
points; you never run it yourself.

| When | A stale report means | What happens |
|---|---|---|
| End of Phase 5 | something rewrites the code on every run | stop (#13) |
| Start of Phase 6, nothing committed yet | the code changed outside the pipeline since S2 | the quality gate and the verifier run again, then the full review |
| The PR gate | the code changed while the gate waited | re-checked as above, then the gate is asked again |
| `commit` | the code changed after the gate | re-checked as above, then the gate is asked again |
| Before the main gate (`--ref origin/<branch>`) | someone pushed to the PR branch | stop (#18); once the user brings the commits into the worktree, the quality gate and the verifier run again, a review pass covers what they changed, `commit` verifies the new head without committing, and the main gate is asked again |
| The same check, stale twice running | the re-run didn't settle it | stop (#13) |

## Lookups

When you need a fact from source, a diff or a long artifact, ask `lookup`
instead of reading it. It answers only these kinds of question:

- where a symbol is defined or used;
- whether a file or diff contains something;
- what a section of a long artifact says;
- which files a change touches, and what each change does.

It never judges whether anything is right. To ask one:

1. `autodev.py brief lookup --set question="<the question>" --dir <artifact-dir>`
2. Spawn the agent it names with the prompt it prints.
3. `autodev.py record lookup <n> --dir <artifact-dir>`. Always record it: an
   unrecorded brief makes `next` re-issue it.
