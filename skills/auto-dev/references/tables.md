# Shared tables

The facts all three runbooks rely on, stated once. `autodev.py next` applies
every rule here by itself; this file is for explaining a stop or a question to
the user, and for the few steps `next` hands to you.

## Contents

- [The iteration budget](#the-iteration-budget)
- [Stop conditions](#stop-conditions)
- [Hold and Stop](#hold-and-stop)
- [Overriding a stop](#overriding-a-stop)
- [What each gate option does](#what-each-gate-option-does)
- [Freshness: when a report no longer matches the code](#freshness-when-a-report-no-longer-matches-the-code)
- [Lookups](#lookups)

## The iteration budget

One budget of revise rounds per task: `iteration_budget` in `.auto-dev.yml`,
default 4. `next` spends a round before the action that needs it and prints a
`BUDGET:` line when it does. You never spend one yourself.

Each of these spends one round: a re-review after a reviewer's FIX blocks
applied (Define or plan), re-spawning the acceptance tester for gaps or for the
other reading of an ambiguous condition, a re-dispatched `BLOCKED` step, a
quality-gate repair of a check, and each correction: after verification (a
repair of the checks the verifier calls defective rides on the same round), for
a review pass's findings, for people's comments on the PR, or for red CI.

When none is left, `next` stops and its `REPORT` names what is still open, one
item at a time, and `autodev.py budget raise --by <n>`. One exception: a review
pass's correction with no round left before the commit goes on to the PR gate,
whose summary names every open must-fix finding. Run `budget raise` only when
the user asks for more rounds and gives the number (1 to 10; it is refused
unless `next` just stopped on the budget). Then `next` takes the step that
stopped, spending the new rounds as usual.

Free (no round): the first review of anything, every verifier re-check, every
cleanup run, a user's "Revise plan" at the post-plan gate, a re-spawn after a
worker failed once, the entry-point repair a plan revision calls for, a stop
and whatever the user's answer to it runs (a fix, a retry, a sign-off), and
the re-check after a sign-off. Open items a re-check finds are a new
correction, paid as usual.

## Stop conditions

Each one ends with `next` exiting 4 (or the command named exiting 1). Tell the
user the `REPORT` lines. The worktree and `.auto-dev/` stay. Every stop `next`
reports, except #12, #20 and a merge whose outcome is unknown, comes with a
`QUESTION`: the user can override it (_Overriding a stop_, below).

| # | Condition | Detected by |
|---|---|---|
| 1 | `gh` missing or signed out, `origin` not on GitHub, python3 < 3.9 or no PyYAML | `init` exit 1 |
| 2 | invalid `.auto-dev.yml` or saved profile, no test command in the quality gate | `init` exit 1 |
| 3 | worktree path taken, a seeded file not gitignored, a setup command missing or failing; in a worktree the user made, uncommitted changes, another task's run or a stray `.auto-dev/` there, or no `origin/<base>` it shares history with | `init` exit 1 |
| 4 | the run was started on auto-dev 3.x | `resume` prints `OLD-VERSION` |
| 5 | the task is too big for one PR | Define returns `OVERSIZED` |
| 6 | a worker did not return ok twice running: it stopped on purpose, failed, or one of each (lifted by `auto-dev continue`) | `next` records a second result that is not ok |
| 7 | a worker was spawned three times and never left a result `next` accepts (lifted by `auto-dev continue`) | `next` |
| 8 | a reviewer found blockers but wrote no FIX block | `next` |
| 9 | the planner judged the spec impossible to meet | planner returns `SPEC_IMPOSSIBLE` |
| 10 | the quality gate can't be made green | cleanup returns `RED` |
| 11 | the mutation step may have left a planted change in the source | verifier returns `MUTATION_LEFT_CHANGES` |
| 12 | the budget ran out (a review pass's correction before the commit goes to the PR gate instead). Lifted when the user adds rounds (`budget raise`, above) | `next` |
| 13 | a report is stale again right after its own re-run (lifted by `auto-dev continue`) | `check-fresh`, inside `next` |
| 14 | no code reviewer wrote a usable report, twice | `next` |
| 15 | the commit failed, or does not carry the checked code | `commit` exit 1 or 3, then `next` |
| 16 | CI is red for a reason the code can't fix: a secret or credential (`SECRET`), infrastructure (`INFRA`), a flaky test (`FLAKY`) or no clear cause (`UNKNOWN`). Reported before Jira moves to In Review. Lifted by `auto-dev continue` once the cause is fixed and CI re-run: CI is watched again | triager's CI mode |
| 17 | someone pushed commits to the PR branch the pipeline didn't check. Lifted once the user fast-forwards the worktree to `origin/<branch>` (`git merge --ff-only`, which the report names) and says `auto-dev continue`: the commits are re-checked, then the main gate is asked again | `check-fresh --ref`, inside `next` |
| 18 | CI is red at the main gate | `next` |
| 19 | GitHub refused or only queued the merge | `merge-pr` exit 3 or 4, then `next` |
| 20 | the user chose Stop at a gate or pause | `gate … stop` |
| 21 | a later worker found a SPEC.md criterion wrong or missing (the verifier, the review judge, a security reviewer, or the triager from a PR comment): the report names each item from `spec-problems/<worker>-<n>.md`. Workers never change the spec; the user decides, and a sign-off keeps it as written | `next`, on a result with `spec_problems` |
| 22 | the acceptance tester ruled a check right as written (STANDS) that the verifier, a review finding or a PR comment called wrong: the report names both sides. A sign-off keeps the check as written | `next` |

## Hold and Stop

They are different states.

- **Hold** pauses the run at one gate: the PR gate or the main gate. The phase is `held`. Starting a new session and saying
  `auto-dev continue` asks **that gate** again, starting with its checks, since
  the code may have changed meanwhile.
- **Stop** ends the run. The phase is `stopped`. Nothing resumes it: `resume`
  reports it as `FINISHED`. This is a gate's `Stop` answer. (An `OVERSIZED`
  task (#5) marks Phase 2 stopped too, but `resume` picks it up, since the user
  can still override it.)

Every other stop (exit 4) leaves the phase open, and `next` decides again in
the next session:

- A stop on a **worker** (#6, #7), a refused `pr publish`, and a red CI run the
  code can't fix (#16) are lifted when the user fixes the cause and says
  `auto-dev continue`: the worker is spawned again, the PR published again, or
  CI watched again. A session that ended at a checkpoint (`handoff
  --checkpoint`) lifts nothing: it ended at a clean point, with no stop to
  lift, so a worker that failed once before it and once after still stops.
- A stop on a **result** (a red quality gate #10, an impossible spec #9, a
  mutation that may have left changes #11, a wrong criterion #21, a disputed
  check #22, …) comes back in a resumed run,
  since the result is still there. The user overrides it, in the same session
  or a new one (below). The budget stop (#12) is lifted only when the user
  adds rounds: `budget raise`, then `next` takes the step that stopped.

## Overriding a stop

`next` saves the stop it reports in `state.json` and asks the user how to go
on. Each answer's `AFTER` line runs `autodev.py override`, which records it,
then `next` acts on it. Running the stopped step again spends no round; a
correction its new result calls for is paid as usual.

| Answer | Records | Then |
|---|---|---|
| a typed instruction | `override fix --text "<the user's words>"` | the **fixer** is spawned with the words, its consent. It does what they say and nothing more: in the code, the tests, or the run's SPEC.md, plan or acceptance checks when they name them. `FIXED`: the step that stopped runs again, and so does what depends on what changed (the quality gate and the verifier on changed code; the verifier's first pass on a changed SPEC.md or plan; in Phase 6, a review of the changed files). `record` refuses a report that leaves out a path the fixer changed. An installed check the fixer edits in the worktree is sealed again from its edit (`.sealed` and `.base`), so the fixer never keeps the seal by hand; for every other change to the checks (a sealed copy before the install, a new check file, MANIFEST.md rows) it runs `autodev.py amend-checks`, which works only while its fix is open. `record` refuses a dropped test still in its file, a condition left with no check and no Not automatable row, and `FIXED` with a status other than ok. A change to the run's settings in `state.json` (a gate check's command) counts as a changed path: kept with `FIXED`, put back otherwise. Auto mode can refuse an agent's own edit of those files as test removal. `NEEDS_CONSENT` (the fix needs more than the words allow) or `CANNOT_FIX`: whatever it changed is put back, and the question comes again, with its proposal or its reason |
| Approve the fixer's proposal | `override approve` | the fixer runs again, told to do what it proposed |
| I fixed it myself | `override retry` | the result that stopped is set aside and its step runs again; a worker that failed twice, a refused `pr publish` or red CI (#6, #7, #13, #16, #18) get what `auto-dev continue` gives them |
| Sign off and go on | `override signoff --text "<why>"` | the result is accepted as if it had passed: a red gate as green (for the rest of the run, while only the checks signed off fail), a disputed check as standing and a wrong criterion as written (each later worker that judges it is told the user kept it, `checks_kept` or `spec_kept` in its brief), a review with blockers and no FIX as clean, open findings as known (the PR gate names them), an `OVERSIZED` task as fitting. Named in `WORK_LOG.md`, the PR gate's summary and the PR body. Never offered on red CI, a confirmed security finding, a mutation that may have left changes, a stale report, an impossible spec or commits the pipeline didn't check |
| Let's talk it through | `override talk` (records nothing) | talk it over with the user, sending a `lookup` for any fact about the code; then `next` asks again |
| Leave it stopped | `override leave` | the stop is reported without the question for the rest of the session; `auto-dev continue` asks again |

`override` is refused (exit 1) when `next` did not just stop on a step that
can be overridden, for a sign-off the stop doesn't offer, and for a fix with no
instruction.

## What each gate option does

`next` prints the gate's question and one `AFTER` line per option. Run the line
for the option the user picked, filling in `<the user's words>` or `<why>` with
what they said, then run `next`.

| Gate (when) | Option | Records | Then |
|---|---|---|---|
| Jira (Phase 2, with a ticket, once the size check says FITS) | Move it | `gate jira proceed` | you move the ticket; Jira moves at each later milestone too |
| | Already In Progress (also run without asking when the ticket's status shows it) | `gate jira already` | no move now; Jira moves at each later milestone |
| | Leave Jira alone | `gate jira leave` | no Jira move for the rest of the run |
| | Stop | `gate jira stop` | the run stops |
| Post-plan (Phase 3; on when `HIGH_RISK` or `gates.post_plan: true` in `.auto-dev.yml`) | Approve & build | `gate post-plan proceed` | Phase 3 ends; the session hands off |
| | Revise plan (tell me what to change) | `gate post-plan revise --reason "<the user's words>"` | the planner revises (no round); if its entry points changed the tester repairs the checks; the gate is asked again |
| | Stop | `gate post-plan stop` | the run stops |
| PR (Phase 6, once the reviews settle) | Open PR | `gate pr proceed` | commit, push, open the PR |
| | Hold (don't push yet) | `gate pr hold --reason "<why>"` | the run is held at the PR gate |
| | Stop | `gate pr stop --reason "<why>"` | the run stops; nothing is pushed |
| Main (Phase 6, once CI and human comments are settled) | Merge PR to main | `gate main proceed` | `merge-pr`, then Jira Done and the final report |
| | Hold | `gate main hold --reason "<why>"` | the run is held at the main gate |
| | Stop | `gate main stop --reason "<why>"` | the run stops; the PR stays open |
| Worktree (after the final report) | Remove it / Keep it | `gate cleanup proceed` / `keep` | the worktree (and `.auto-dev/`) is removed or kept |

The PR gate may add a question per pre-existing security finding (the two most
severe on their own, the rest grouped as `Others`, once there are more than
three; three or fewer get a question each): `Separate PR (note it as a
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
| Before the main gate (`--ref origin/<branch>`) | someone pushed to the PR branch | stop (#17); once the user brings the commits into the worktree, the quality gate and the verifier run again, a review pass covers what they changed, `commit` verifies the new head, or commits the re-check's edits on top, and the main gate is asked again |
| The same check, stale twice running | the re-run didn't settle it | stop (#13) |

## Lookups

When you need a fact from source, a diff or a long artifact, ask `lookup`
instead of reading it. It answers only these kinds of question:

- where a symbol is defined or used;
- whether a file or diff contains something;
- what a section of a long artifact says;
- which files a change touches, and what each change does;
- what a piece of code does in a case you name.

Ask for a fact, never a verdict, and only to route the run or to answer
the user. Whether code is correct, safe or done, or what should change, is not
yours to settle (hard rule 2): run `next`, and the verifier and the reviewers
give that verdict from evidence. A lookup returns `OUT_OF_SCOPE` for a verdict
question. If you still need a fact, ask the question it suggests after `ask
instead:`, and pass the answer on as a fact, never as a ruling. To ask one:

1. `autodev.py brief lookup --set question='<the question>' --dir <artifact-dir>`
2. Spawn the agent it names with the prompt it prints.
3. Nothing to record: the next `next` you run records it.
