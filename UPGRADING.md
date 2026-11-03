# Upgrading auto-dev

What changed in each release, and whether a run started on the previous version
can resume on the new one. Newest first. The current version is in
`.claude-plugin/plugin.json`.

## Upgrading from 4.24

- **`record` holds the workers that never change the repo to that.** The
  planner, Define, the Define and plan reviewers, the review judge and the
  triager each get a snapshot of the worktree with their brief. When one of
  them changed a file outside `.auto-dev/`, `record` refuses its result,
  names the files, keeps the worker's versions in `.auto-dev/tree/<worker>-<n>/`
  and puts the files back. Before, only their instructions kept them out of the
  code. A change someone else could have made is left alone: a file written
  after the worker returned, a commit, or anything while a worker that writes
  code was out.
- **Resume:** a run in flight resumes. A brief written before the upgrade holds
  no snapshot, so its result is recorded as before.

## Upgrading from 4.23

- **The Jira In Progress question has an `Already In Progress` answer.**
  Before asking, the orchestrator reads the ticket's status. When the ticket
  is already In Progress or past it, it doesn't ask: it records `gate jira
  already`, makes no move then, and still moves the ticket to In Review and
  Done at the later milestones. You can give the same answer yourself, for
  example when Jira can't be read. Before, the only answers were `Move it`,
  `Leave Jira alone` (no moves for the whole run) and `Stop`.
- **Resume:** a run in flight resumes. A run waiting at the Jira question is
  asked the new question when it resumes; a run past it keeps the answer it
  gave.

## Upgrading from 4.22

Several workers change model or effort. The first three changes below were
checked in small scenarios with planted bugs, where each new setting found as
much as the one it replaces:

- **The code reviewers run at `high`, not `xhigh`.** The planner now writes
  `Review effort: high` by default, and `xhigh` only for a large change (many
  files, or logic across several modules). A plan with no `Review effort:`
  line also means `high` now.
- **The sensitive-path security reviewer runs on `opus` · `xhigh`, not
  `fable` · `high`.** It keeps its own instructions, which weight the
  sensitive paths hardest.
- **Lookups run on `haiku` · `medium`, not `sonnet` · `medium`.**
- **The profiler and the cleanup agent run at `high`, not `medium`.** On the
  Claude 5.5 models, `high` is Sonnet's default, and at `medium` Sonnet 5.5
  scores 7 to 15 points lower on Anthropic's published coding benchmarks.
- **Resume:** a run in flight resumes. Workers spawned after the upgrade use
  the new settings, except that the code reviewers follow the plan's
  `Review effort:` line, so a plan written before the upgrade (often
  `xhigh`) keeps its effort for the rest of the run. A review pass that has
  started keeps the effort it started at.

## Upgrading from 4.21

- **You can add rounds after the budget runs out.** The stop for a used-up
  iteration budget now says you can go on with more rounds. Say how many,
  right after the stop or as `auto-dev continue with <n> more rounds`. The
  orchestrator then runs the new `autodev.py budget raise --by <n>` (1 to 10)
  and `next`, which takes the step that stopped and spends the new rounds as
  usual. The spec, plan and check proposals that step had no round for are
  sent with it. Proposals an earlier step left unsent stay unsent, since the
  run went past them, and the reports keep naming them. `budget raise` is
  refused unless `next` has just stopped on the budget.
  state.json's `budget` gains `stopped` (set by that stop) and `raises`.
- **A review pass after the commit no longer ships past its must-fix
  findings.** When a review correction found no round left before the
  commit, the open findings went to the PR gate, and every later review pass
  was skipped the same way, even one after the commit. Now only the passes
  from before the commit are. A must-fix finding in a pass after the commit
  gets a correction, or, with no round left, stops the run and is named in
  the report, as _The iteration budget_ in `references/tables.md` says.
- **Resume:** a run in flight resumes. A run already stopped on the budget
  under 4.21 gets the new report, and can be raised, on its next `next`. The
  proposals its stopped step had no round for stay unsent after the raise,
  since that stop came before 4.22 could tell them apart.

## Upgrading from 4.20

- **The review judge makes the calls; a script writes the report.** When it
  briefs the judge, `next` merges the reviewers' reports into
  `review/pass-<n>/findings.md`. Each finding becomes `F<k>`, with who raised
  it, its location, category, trigger path and reason, plus a `Near:` hint
  for findings close together in one file. The security leads and spec
  problems are gathered there too. The judge writes
  `review/pass-<n>/JUDGMENT.md` (`templates/JUDGMENT.md`). Each block merges
  F findings and says whether the path holds, gives the category and the
  detail lines a must-fix finding needs, and covers the earlier must-fix
  findings and each lead. It then runs `autodev.py review-build`, which:
  - applies the rubric's vote table (3 votes must-fix High, 2 Medium, 1 a
    re-vote; an advisory category advisory; a path that fails noise);
  - carries the earlier passes' rows, details, leads and Passes rows
    forward, and writes the Tree line, counts and overall confidence;
  - writes `CODE_REVIEW.md` and the pass's `corrections.md`;
  - prints the `next`, `must_fix_open` and `revote` values for the judge's
    result.

  The judge used to rewrite the whole `CODE_REVIEW.md` each pass (3–12k
  characters) and work out the counts and tables by hand. `CODE_REVIEW.md`
  keeps its format, so `votes`, the gates and the PR description read it as
  before.
- **A reviewer's report is checked against its template.** `check-artifact`
  (and so `record`) now refuses an `R<k>.md` finding that isn't
  `<n>. **<title>** — `path:line` — <category>` with a `Trigger path:`
  line. The reviewer runs that check itself before it returns. A line that
  still doesn't parse (a report recorded on 4.20) is never dropped: it
  becomes a finding of category `unknown` in `findings.md`, and the judge
  reads the report for it.
- **`record` refuses a judge's result with no `JUDGMENT.md`** for a pass
  whose `findings.md` `next` wrote, so the report always comes from
  `review-build`. `review-build` refuses (exit 2) when `CODE_REVIEW.md`
  already holds the pass and no snapshot from before it exists, rather than
  build without the earlier passes.
- **Resume:** a run in flight resumes. A judge briefed from now on writes
  `JUDGMENT.md`. One already spawned on 4.20 writes `CODE_REVIEW.md` itself,
  which `next` reads as before. A later pass of the same run builds on that
  report.

## Upgrading from 4.19

- **A script runs the verifier's mutation run.** The verifier still chooses
  the mutants (writing `evidence/mutation-set.json` and the ones to run in
  `evidence/mutants.json`) and judges the survivors. Everything between is
  now `autodev.py mutants run --dir <artifact dir> --files <tests>
  [--new-set | --extended]`, which starts a runner in the background, and
  `autodev.py mutants wait` while it prints `RUNNING`. The runner:
  - saves the base diff;
  - takes the scoped test command from the profile;
  - times the cold run, or reuses the saved time;
  - runs `mutate.py`, and runs it again after leftover backups, a live run
    or an interruption;
  - re-times once by the same rules as before, and checks that the tree is
    as it was;
  - runs `mutants record`.

  It prints one token: `DONE`, `INCOMPLETE`, `ALL_INVALID`, `MALFORMED`,
  `FAILING`, `NOT_RUN`, `KEPT`, `LEFT_CHANGES` or `BUSY` (`wait` with no
  run started prints `NOT_STARTED`). It never ends
  while a mutant may be in the tree: it waits for a live `mutate.py` run and
  puts back what one left. It re-times at most once a pass, and records an
  all-invalid run only when it is the pass's second. Step 7 of
  `agents/verifier.md` shrinks from 17k to 6k characters, and the verifier's
  file from 37k to 25k. The hand-written timing, `sha256sum` pipes, redirects
  and wait loops are gone. In the 4.0.6 benchmark they were 18 of the
  verifier's refused commands and several turns a pass.
- **No `mutate.py` permission rule is needed.** `autodev.py` runs it, so the
  `autodev.py` rule covers mutation testing. The `mutate.py` rule can be
  dropped from your settings.
- **`verify prep` waits for a mutation runner still going** from an earlier
  pass, as it already did for `mutate.py`.
- **Resume:** a run in flight resumes. A verifier briefed from now on uses
  `mutants run`. One already spawned on 4.19 finishes its pass the old way;
  its files are the ones the runner reads.

## Upgrading from 4.18

- **The verifier's routine steps are one script call.** A verifier pass now
  starts with `autodev.py verify prep --dir <artifact dir> --pass <mode>`.
  It does these steps in order:
  - puts back what an earlier pass's mutation run left, waiting up to 270
    seconds for one still alive;
  - installs the sealed checks, or on a re-check puts back any check edited
    since, after the audit has recorded the edit;
  - runs the audit into `evidence/integrity.txt`, its exit code on the first
    line;
  - notes the tree hash in `evidence/tree-start.txt`;
  - marks untracked files intent-to-add and saves `git diff <cut>` to
    `evidence/changes.diff`;
  - runs the acceptance checks through `autodev.py run test` into
    `evidence/acceptance.txt`;
  - writes `evidence/C<n>.txt` for each condition with checks: the
    Expected, Command and Result lines and the output lines that name its
    checks.

  The verifier used to do this by hand, one tool call per step, and typed
  each evidence file's output itself. In the 4.0.6 benchmark that was about
  half of a pass's calls, and evidence writes alone took 30–55 seconds. A
  path where a check can't go in is printed as `INSTALL_CONFLICT`, with
  `evidence/corrections.md` written. `autodev.py verify tree` compares the
  tree at the end of the pass with the one prep noted, and prints the Tree
  line to write or the files that changed. The judging (tiers, verdicts,
  integrity, defective checks, mutants) is unchanged.
- **Resume:** a run in flight resumes. A verifier briefed from now on uses
  `verify prep`; one already spawned on 4.18 finishes its pass as it began.

## Upgrading from 4.17

- **Workers run the profile's commands through `autodev.py run`.** `autodev.py
  run gate <n | REPORT>` and `autodev.py run test` run a quality-gate check's
  command exactly as the profile lists it, with the run's worktree as its
  directory, save the whole output under `.auto-dev/tmp/run/` (or `--out`, a
  file under `.auto-dev/`), and print `PASSED`, `FAILED` or `TIMED_OUT` with
  the time taken and the output's tail. A worker's shell doesn't start in the
  worktree, so workers used to rewrite the commands as `cd <worktree> && …` or
  with the worktree's path, which a permission check refuses: 44 of the cleanup
  agent's 45 refused commands in the 4.0.6 benchmark were that one pattern, and
  a twice-refused command makes the worker return `blocked` and be spawned
  again. Cleanup's brief now gives a `run:` command under each gate check, and
  the coder, acceptance tester and verifier run tests through `run test`. It
  runs only the profile's commands, so the existing `autodev.py *` permission
  rule covers it.
- **A gate check can give a scoped form.** The optional `files` field of a
  `gate` check is the same check run on only some files, with `<files>` where
  the paths go (for example `npx vitest run --reporter=verbose <files>`, in
  TypeScript). `autodev.py run … --files <path> …` runs it with the paths
  quoted and relative to the worktree, and refuses a path outside it. The
  test check's form must name every test it runs and its result. The profiler
  now researches it, and profile.md's Quality gate table shows it.
  `validate-config.py` accepts `files` and requires `<files>` in it. A saved
  profile without it still works: a worker that wanted a check scoped runs
  it whole through `run` instead, which is slower on a large suite. To scope
  them, add `files` to the checks in your saved profile, or delete the
  profile to have the next run research it again. `run` needs `--dir`, and
  `--out` writes only under `.auto-dev/`'s `evidence/`,
  `acceptance/base-run/` or `tmp/`.
- **Resume:** a run in flight resumes. Its briefs written from now on use
  `autodev.py run`; its gate has no `files` forms unless its profile had them.

## Upgrading from 4.16

- **The orchestrator writes the PR description's prose in a small file.**
  Alongside `pr-body.md`, `next` now writes `pr-write.md`: the text the WRITE
  lines draw on, quoted (`SPEC.md`'s Context and Assumptions, the task, and the
  description's checked requirements, Quality gate and Review), then a mark
  line and only the sections of the description that hold a `<!-- WRITE: ...
  -->` line (the Summary, the Assumptions, a section or checklist the repo's PR
  template adds). The orchestrator edits that file, never reading the
  30–50k-character `pr-body.md`, and `pr publish` puts each of its sections in
  place of the section of the same heading that still holds a WRITE line, then
  lints the result as before. A section already written in `pr-body.md` stands.
  `pr publish` refuses (`unwritten`, so the orchestrator fixes the file once)
  when the mark line is gone, or a heading below it was renamed, removed or
  added.
- **Resume:** a run in flight resumes. A description generated before 4.17
  has no `pr-write.md`, and `next` names `pr-body.md` as before.

## Upgrading from 4.15

- **`next` records the workers' results itself.** Before it decides, `next`
  records each issued brief whose result file exists and isn't recorded yet,
  as `autodev.py record` would, and prints a `RECORDED: <worker>-<n>: <status>
  <next>` line for each (or `refused (<token>)`, after which the same `next`
  briefs the job again with the issues). Each recorded result is still its own
  event, so results and later briefs keep their order and the checkpoint
  counts as before. A spawn action no longer prints `AFTER: autodev.py record
  …` lines: the orchestrator spawns, waits for every agent to return, and runs
  `next`. That saves one orchestrator turn per worker, a fifth of a run's turns.
  A brief with no result file is still issued again as it is, so a worker
  that wrote none is no longer told so in its brief (`record` used to refuse
  it as `MISSING`). `next --explain` records nothing: with a result waiting, it
  says `next` would record it first. `autodev.py record` stays, to record one
  result by hand.
- **Resume:** a run in flight resumes. A session that already ran `record` for
  a result is fine: `next` sees it recorded. A result written before a session
  was cut off is now recorded on resume rather than its worker spawned again.

## Upgrading from 4.14

- **A refused return is fixed up, not redone.** When `record` refuses a
  worker's return, `next` re-spawns the worker with the issues in its
  `previous_issues` slot, as before. That slot now opens with a line saying
  the refused return's files are still in place: when they are complete and
  current, start from them, fix each issue and redo nothing else, even where the agent file says to start clean
  (the acceptance tester's write mode) or judge from scratch (the verifier's
  re-check). It still redoes what its fix makes stale, and does the job afresh
  when its files are missing, partial or from an earlier pass, or when it wrote
  no result file at all. Before, a retry often redid the whole job: in one
  benchmark run a verifier refused over a token that disagreed with its report
  spent 271 s on a full redo.
- **Resume:** a run in flight resumes. A retry briefed before 4.15 keeps its
  old `previous_issues` text and may redo the job, as before.

## Upgrading from 4.13

- **The acceptance tester runs `check-manifest` before it returns.** In write
  mode it runs `autodev.py check-manifest --dir <artifact dir>`, the check
  `next` runs on its return, and fixes each gap it lists in the conditions its
  scope names (a missing base-run Result for a check's exact test name, an Edge
  with no check, …) by redoing the step that produced it, never by editing a
  record to fit. Before, `next` found these gaps after the tester had
  returned, and re-spawned it at the cost of a round: 4 of 18 benchmark runs
  did, for 1.5–2.5 min each. `next` still runs the same check, so a gap the
  tester leaves is handled as before.
- **Resume:** a run in flight resumes. No state, result key or artifact changed.

## Upgrading from 4.12

- **Workers reply with their result block alone.** The agent files no longer
  ask for a prose summary ("Return: …"). Nothing read it: most of it repeated
  the worker's artifacts, and the rest (risks, the coder's deviations from the
  plan, cleanup's reverted simplifications) reached no step. A worker writes a
  few lines above the block only for why it is `blocked` or `failed`, a
  reviewer's blocker with no FIX block, the planner's reasons for
  `SPEC_IMPOSSIBLE`, the tester's reason for `STANDS`, and the paths a
  mutation run may have left changed (`MUTATION_LEFT_CHANGES`). The coder's TEST CHANGES go in the result's
  `test_changes` and its BLOCKED steps in the blocked file, as before; the
  tester records which rule chose a new test file's path in `MANIFEST.md`'s
  Assumptions. This cuts the time workers spend writing and the text that
  lands in the orchestrator's context.
- **Resume:** a run in flight resumes. No state, result key or artifact changed.

## Upgrading from 4.11

- **The coder proposes against the plan and the checks.** When a step of
  `IMPLEMENTATION.md`'s build sequence can't be right as written, or a held-out
  check its correction brief listed asserts the wrong thing, the coder writes
  `proposals/coder-<n>.md` (the new `templates/CODER_PROPOSAL.md`) and returns
  `proposals: <k>`. A plan proposal names steps or adds one after the last; a
  check proposal names one check as `MANIFEST.md` writes it. `record` refuses
  a coder proposal on a `SPEC.md` condition or criterion, a step the plan
  lacks, a check its brief didn't list, or a test `MANIFEST.md` doesn't name.
- **The planner and the acceptance tester rule.** The planner answers plan
  proposals in revise mode (a new `STANDS` token when it applies none) or, when
  the coder also returned `BLOCKED`, in the same blocked-mode answer, writing
  `proposals/plan-<k>-rulings.md`. The tester answers check proposals per
  condition, `repaired` or `stands`, in `proposals/checks-<k>-rulings.md`.
  `record` holds the build sequence and the sealed copies to the rulings,
  against copies taken at brief time (`proposals/snapshots/`), and refuses an
  answer that writes a `stands` reason into the plan or a check file.
- **The three existing check routes become check proposals.** The verifier's
  `REPAIR`, the review judge's `acceptance-check` findings and the triager's
  `ACCEPTANCE_CHECK` comments are written as before, but now reach the tester
  as a batch with one item per condition. They stay those workers' only way to
  question a check: a proposal file whose Target is a check is refused.
- **Order, settled items and rounds.** Proposals on one result settle spec,
  then plan, then checks; after a plan revision that changes the checks' entry
  points, the entry-point repair runs before the check proposals. A step or
  condition ruled to stand is not sent again for the rest of the run (before
  4.12 a stood check counted only within one build–verify loop), until
  something changes it; a review or PR comment that re-raises a stood check
  with nothing else open stops the run (stop #22). A coder result's proposals
  cost one round, `BLOCKED` included; the coder then runs again in its mode,
  told only `P<k>: repaired` or `P<k>: stands` (new optional `{{answers}}`
  slot) and, when the plan changed, its revised lines (`{{plan_change}}`). A
  plan or check proposal no round was left for is named in the stop report or
  the PR gate summary.
- **A run in flight resumes.** No `.auto-dev.yml` key changes and the state
  needs no migration: `state.json`'s `proposals` gains `plan_batches`,
  `check_batches` and `filings`, briefs gain `plan` and `sealed` keys, and log
  entries `steps_changed` and `checks_changed`, on first use. A coder return
  without `proposals` (briefed on 4.11) reads as filing none; a planner or
  tester briefed on 4.11 has no batch, so `record` asks no rulings of it; a
  correction or spec redo started on 4.11 sends its checks as before; and a
  4.11 tester STANDS on an `ONLY conditions …` scope now counts as settled for
  the rest of the run, until a later 4.11 REPAIRED on such a scope names the
  condition again.
- **Every verifier pass is told which checks stand.** Its brief's `rulings:`
  line names each condition whose checks the tester ruled stand, from a mixed
  batch or an earlier loop too.

## Upgrading from 4.10

- **The deviation gate.** When a verifier proposes a change to a condition the
  Define agent ruled stands (on that result's own proposal, or an earlier
  one), and judges that condition partial or unmet, the code does what the
  proposal described. This changes what follows a verifier STANDS: before
  4.11 the correction went straight to the coder. Before the correction
  would undo it, `next` exits 5 and asks you, one condition at a time:
  `Accept the deviation`, `Keep the spec (correct the code)` or `Stop`. This
  applies whoever first proposed the change: a stood review or PR-comment
  proposal reaches the gate once the code deviates. The answer is recorded
  with the new `gate deviation <accept|keep|stop> --condition <n>`; it holds
  for the rest of the run.
- **Accepting costs no round.** The verifier re-checks, told the deviation is
  accepted (a new line in `{{rulings}}`): it judges the condition met when the
  deviation is its only gap, writing `accepted deviation:` in the Evidence, and
  writes no correction to undo it. Any other open item is corrected on the
  round the first result already paid. Later code reviewers and the review
  judge get the accepted deviations (a new optional `{{deviations}}` slot),
  so a review never asks to undo one.
- **What can't be accepted.** An unmet condition (its acceptance check may
  fail, which fails the quality gate) is offered only Keep and Stop. A
  security criterion is never deviated from: proposals can't name an existing
  S row, and `gate deviation accept` refuses an `S<n>`.
- **Where accepted deviations show.** The PR and main gate summaries, and a new
  *Accepted deviations* line in the final report. The PR body is unchanged.
- **The verifier is told to propose again.** After a STANDS, a verifier that
  finds the code still doing what the proposal described proposes it again;
  that proposal goes to the gate, never to the Define agent. A proposal's
  `Why:` says what the code does, since the gate shows it to the user.
- **A run in flight resumes.** No `.auto-dev.yml` key changes and the state
  needs no migration: `state.json`'s `proposals` gains a `deviations` key, and
  a verifier brief a `paid_by` key, on first use. A run that is in the middle of
  a correction after a STANDS goes on as before; the gate is asked at the next
  verifier result that shows a deviation.

## Upgrading from 4.9

- **A later step can propose a change to `SPEC.md`.** The verifier, the review
  judge (consolidating the panel, whose reviewers raise a spec problem in a new
  `## Spec problems` section of their reports), the security reviewer and the
  triager (human mode only, in its own words, naming the comment's id) may
  write `proposals/<worker>-<n>.md` (`templates/PROPOSAL.md`) when SPEC.md
  itself is wrong, and return `proposals: <k>`. No other worker or mode may.
  A proposal changes named conditions or adds one condition or one security
  criterion; it never removes or renumbers a condition or touches an existing
  S row. `record` refuses a malformed proposal, a correction file that copies
  a proposal's new text, and a filer that edited SPEC.md itself.
- **The Define agent rules on them.** `next` sends a result's proposals (or a
  settled review pass's, together) to the Define agent in revise mode, as
  `proposals/batch-<k>.md`, before the result is acted on. Define answers each
  `applied` or `stands` with a reason in `proposals/batch-<k>-rulings.md`
  (`templates/RULINGS.md`) and returns `REVISED` or the new token `STANDS`;
  `record` holds SPEC.md to the rulings. A STANDS holds for the run: the
  result is acted on as if it carried no proposal, a later proposal on that
  condition is not sent again, and every later verifier brief carries the
  ruling (`{{rulings}}`).
- **An applied change is redone.** The planner revises the plan for the
  changed conditions (`{{spec_change}}`), the acceptance tester rewrites only
  their checks in place (write mode after the build; sealed files of other
  conditions are held), one free repair covers changed entry points and any
  carried check finding, the coder gets the plan's change
  (`redo/plan-change-<k>.md`) with any review or PR-comment fix the result
  carried, then cleanup and a verifier first pass. In Phase 6, the change is
  reviewed again and the next gate asked again. A redo that can't settle its
  checks (gaps after one re-spawn, or a second ambiguity) is stop #21.
- **The budget.** Sending the proposals spends the round the result's own
  correction would; the redo spends nothing more. With no round left nothing
  is sent, and the stop report or gate summary names the proposal.
- **Gate summaries** list every spec change made during the run and who
  proposed it, the proposals ruled to stand, and the ones never sent.
- **New files:** `.auto-dev/proposals/` (proposals, batches, rulings, SPEC.md
  copies) and `.auto-dev/redo/`.
- **A run in flight resumes.** No `.auto-dev.yml` key changes and the state
  needs no migration: `state.json` gains a `proposals` key on first use. A
  return without the new `proposals` key is read as none, so a worker briefed
  on 4.9 is still recorded.

## Upgrading from 4.8

- **A mutation run that fits now runs as one blocking call.** The verifier
  used to start every `mutate.py` run in the background and look every few
  minutes, so it sat idle after short runs. Now a run whose mutants × cold-run
  time is 540 seconds or less runs in one call with the Bash tool's 10-minute
  maximum, and the result is read at once. A longer one still runs in the
  background; the verifier waits for it with one looping call at a time, each
  ending by itself after about a tenth of its estimate (30 seconds to 5
  minutes) and made again while the run is going, never a bare sleep, which
  the Bash tool refuses, and never a call the tool moves to the background. A
  blocking run the tool cuts off is restored, then run again once in the
  background.
- **The cold-run time is measured once per mutant set.** The first pass writes
  it to `evidence/mutation-cold-run.txt`, and re-checks reuse it for the
  per-mutant timeout and the blocking-or-background choice. A time is saved
  only from a timed run that passed; a failing one is reported as a failing
  test. A pass with no usable saved value measures one first. Any pass then
  re-times it at most once more, when its run shows a timeout that was too
  short: the saved value makes `mutate.py`'s unmutated baseline time out (no
  longer reported as a failing test), more than half of the mutants time out,
  a mutant that survived the last pass times out, or, on a pass that reused a
  saved value, a mutant the last pass did not record as a timeout times out.
  So one pass times the cold run at most twice. Only the re-time's re-run gets
  a longer timeout: at least twice that of the run that timed out.
- **A run in flight resumes.** A run started on 4.8 has no
  `evidence/mutation-cold-run.txt`, so the first re-check that runs mutants
  measures a cold run, as 4.8 did on every pass, saves it, and later
  re-checks reuse it; like any pass, that re-check may re-time once more when
  its run shows a timeout that was too short. No `.auto-dev.yml` key changes.

## Upgrading from 4.7

- **A re-check re-runs only the mutants that may have changed.** The verifier
  used to run every mutant of its fixed set again on each re-check, one test
  run each. Now `autodev.py mutants select` compares the code with the tree the
  last finished pass tested and names the uncaught mutants, those in a file
  whose content changed and those added since; the others keep their caught
  result. An edited or deleted line in an existing test file (comments, blank
  lines, fixtures and installed acceptance checks included), a deleted or
  renamed test file, an added skip or focus marker, a changed test-runner
  config, or a missing or unusable record runs them all. `autodev.py mutants
  record` saves the tree and every result in `evidence/mutation-record.json`
  after each finished pass. SPEC_EVAL.md's Mutation line counts the whole set
  and says how many were carried forward.
- **A run in flight resumes.** A run started on 4.7 has no
  `evidence/mutation-record.json`, so its first re-check on 4.8 runs every
  mutant, as before, and records the result; later re-checks run only the
  stale ones.

## Upgrading from 4.6

- **Acceptance checks go where the repo's tests already are.** The acceptance
  tester used to write every check to a new `*.acceptance.*` test file, so each
  PR added test files no developer would have made. Now it adds a check to the
  test file the code it drives already has, and writes a new test file only for
  code that has none, with no `acceptance` marker: at the path the plan's
  test plan names for that code, or else named and placed like its sibling
  modules' tests. A check in an existing file may only add lines to it.
- **Checks are merged back in.** After the build, `install-checks` puts each
  check's added lines into its file among the coder's own changes, and the
  audit checks those lines are unchanged rather than the whole file. When a
  check can't go in mechanically (the coder made the same new test file, or
  rewrote the lines around a check), `next` spawns the acceptance tester in a
  new `fold` mode, which adds its tests to the coder's file (no round spent);
  only if that fails does the verifier report an install conflict.
- **A repair in place keeps the coder's lines.** Before the tester repairs an
  installed check, `next` makes the coder's version of that file the check's
  base, and on a re-check `install-checks --recheck` undoes only the edits that
  touched a check.
- **The coder and cleanup briefs name the checks' tests,** not just their
  files, since a file can hold the coder's tests too.
- **A run in flight resumes.** Checks sealed before 4.7 are new files with no
  `<path>.base`, and install as before. The audit now also accepts the coder's
  own lines added before or after such a file's sealed content, where it used
  to report ACCEPTANCE_MODIFIED.

## Upgrading from 4.5

- **A run can start in a worktree you made.** When you start auto-dev inside a
  linked worktree (one `git worktree add` made) on a branch other than the
  base, `autodev.py init` runs the task there, on that branch, instead of
  making a sibling `../<repo>-<slug>` worktree. The worktree must have no
  uncommitted changes; a detached HEAD gets the branch `<prefix>/<slug>` at the
  same commit, and commits already on the branch ship with the run. Starting in
  the main checkout, or in a linked worktree on the base or default branch,
  makes a new worktree as before. The run never removes a worktree you made:
  the last question (remove the worktree?) is skipped, and `cleanup-worktree`
  refuses it.
- **`auto-dev continue` picks the run you are in.** With no task named and
  several runs open, `resume` used to ask which one. Started inside a run's
  worktree, it now continues that run; from anywhere else it asks as before.
- **A run in flight resumes.** `state.json` gains only optional `repo.adopted` and
  `repo.ahead` keys, which a run started before 4.6 doesn't have.

## Upgrading from 4.4

- **A correction's re-review skips the nested skills.** A pass that reviews a
  correction used to run `/code-review` in each of the three reviewers and
  `/security-review` in the security reviewer. Now the three code reviewers
  review the correction and everything downstream of it themselves, and the
  security reviewer gets a `focus` naming the correction, re-checks it and what
  it reaches, and carries its earlier findings forward. The panel stays at
  three reviewers.
- **A run in flight resumes.** A reviewer briefed before 4.5 has no `focus` and
  runs as before. Every pass started on 4.5 uses the new briefs.

## Upgrading from 4.3

- **The security review runs alongside the code review panel.** It used to
  start only after the panel and its corrections had settled, so a security
  finding cost a second correction and a second panel pass. Now `next` spawns
  the security reviewer in the same message as the three code reviewers, the
  judge verifies the security findings while it consolidates the panel, and one
  correction (one round) fixes what both left open: the coder gets both
  required-changes files. A security lead the panel raises that the security
  review hasn't seen goes to the next pass's security review, or to a security
  run of its own when nothing else is open.
- **A run in flight resumes.** A review pass started on 4.3 or earlier, whose
  panel ran without the security reviewer, gets its security review as soon as
  `next` sees it missing: before the judge if the panel was still running,
  after it otherwise. Every new pass uses the new order.

## Upgrading from 4.2

- **The plan sets the code reviewers' effort.** `IMPLEMENTATION.md` has a new
  `Review effort: high | xhigh — <reason>` line, which `check-artifact` checks
  when present. `next` prints an `EFFORT` line after each code reviewer's
  `PROMPT` (only for code reviewers), and `SKILL.md` tells the orchestrator to
  pass it as the Agent tool's `effort` parameter. The state's review passes
  record the effort they ran at.
- **A run in flight resumes.** A plan written before 4.3 has no `Review
  effort:` line, which means `xhigh`, the effort the reviewers ran at before.

## Upgrading from 4.1

- **A test-gap finding asks for the whole gap.** A code reviewer who finds a
  changed behavior under-tested now lists every reachable case no test covers
  in one finding, the judge merges tests findings about the same behavior, and
  the required change asks the coder for a test of each case. Before, each
  review pass tended to find the next missing case, and each one cost a full
  correction round and re-review. The rule is in
  `skills/auto-dev/templates/rubric.md`.
- **A run in flight resumes.** Only agent files and templates changed; the
  next review pass uses the new rule.

## Upgrading from 4.0

- **Cleanup runs before the verifier.** Phase 5 used to run the verifier, then
  the cleanup agent, then the verifier again. Now `next` installs the sealed
  acceptance checks itself (and lists them in `acceptance/INSTALLED`), the
  cleanup agent simplifies the change and runs the quality gate, and the
  verifier's first pass checks the cleaned code. On the happy path the verifier
  runs once instead of twice. A correction still runs coder, cleanup, verifier,
  and a check the acceptance tester repairs goes through cleanup's quality
  gate before the verifier's re-check.
  If a sealed check's path already holds another file, nothing is installed
  and the verifier goes first, as before, to report the conflict.
- **A run in flight resumes.** A run that has already started Phase 5 on 4.0
  finishes it in the old order. One that hasn't reached Phase 5 uses the new
  one.

## Upgrading from 3.9

4.0 is a breaking release.

- **One PR per run.** The scope call is gone. The Define agent now returns a size
  check: a task that fits one PR runs every step, and one that doesn't is handed
  back to you with suggested split lines. auto-dev no longer splits a task into
  sub-tasks or opens several PRs, and the TRIVIAL fast path is gone, so the
  planner writes every plan and the `coder-trivial` worker is removed.
- **Jira moves later.** A ticket moves to In Progress after the size check, not
  in Phase 1, so a task handed back never shows as started.
- **The ledger changed.** The run's state lives in `.auto-dev/state.json`,
  written only by `skills/auto-dev/scripts/autodev.py`; `WORK_LOG.md` is
  generated from it for people to read. Its header has `Worktree`, `Size` and
  `High risk` lines in place of `Control worktree` and `Mode`.
- **Python 3.9+ and PyYAML are required** by `autodev.py`.
- **Workers write the fixes.** The verifier and the review judge write the
  required changes the coder gets; the Define and plan reviewers write exact
  FIX blocks that a script applies; the planner settles a `BLOCKED` step; a new
  `triager` worker reads red CI and human PR comments. The orchestrator no
  longer writes correction briefs or edits `SPEC.md` and `IMPLEMENTATION.md`.
- **Briefs live in the agent files.** Each worker's instructions are in
  `agents/<name>.md` (its system prompt); `autodev.py brief` writes only the
  values that vary, and the spawn prompt is one line. Every worker ends with an
  `auto-dev-result` block, which `autodev.py record` checks against what it
  wrote. Templates and the rubric moved to `skills/auto-dev/templates/`.
- **`autodev.py next` drives the run.** It prints the one next action from the
  run's state, so the orchestrator no longer works out the order of steps,
  when to spend a round, or how to assemble the PR description; `pr publish`
  opens or refreshes the PR. `resume` now records that a new session holds the
  run, and un-holds a gate so it is asked again.
- **Any model runs the orchestrator.** `SKILL.md` is now the `next` loop and
  its hard rules, with one short runbook per session
  (`skills/auto-dev/references/S1-plan.md`, `S2-build.md`, `S3-ship.md`) and
  one file of shared tables. The old phase references are gone. No session
  asks you to switch models.
- **Checkpoints count events, not tokens.** `next` ends a long session after 80
  events (about 35 workers) and asks you to continue in a fresh session.
- **No more by-hand fallbacks.** Without python3 3.9+ and PyYAML the run stops
  in Phase 1. `resume-point.py` is removed: `autodev.py resume` finds the run.
- **`init` finds the security directives** from `security_docs`, or the repo's
  `SECURITY.md`, `.github/SECURITY.md` and `docs/security/*.md`.
- **The PR follows the repo's PR template and links the ticket.** The
  description gets the template's sections, with a box of its checklist ticked
  only when the run's files show it is true, and `pr_review.inline_comments`
  now posts once, after the PR opens, only the review findings left open or
  advisory (3.x posted the Phase 6a findings). `record` checks every file a
  worker says it wrote against its template, and refuses a plan, or a plan
  reviewer's FIX, that copies `SPEC.md`'s wording. A push to the PR branch can
  now be brought in and re-checked instead of ending the run.
- **No staging branch.** The staging gate, the direct merge into staging and
  `autodev.py merge-staging` are gone: the PR targets the base branch and the
  main gate is the only merge gate. A `staging` branch on origin is ignored, and
  `validate-config.py` refuses `branches.staging` in `.auto-dev.yml`: delete
  the key.

A run in flight does not resume on 4.0. Finish it on 3.9, or remove its worktree
and start again.

## Upgrading from 3.8

3.9 keeps the proof that the held-out checks failed on the old code (see the
README's *How the build is verified*). The acceptance tester saves each condition's run on the
untouched tree as `acceptance/base-run/C<n>.txt`, and `MANIFEST.md` gains
*Covers* and *Level* columns. The orchestrator checks that every edge case has a
check or a reason it can't have one, and the verifier rates a condition Strong
only when its checks cover both its example and its edge case and the saved run
shows them failing for the right reason. The PR description quotes that run.

A run in flight resumes on 3.9. A run whose Phase 3 finished on 3.8 has no
`base-run/` and no *Covers* column, and the tester is not run again to add them.
The verifier trusts `MANIFEST.md`'s one-line *Base run* note, as before, and
says so in `SPEC_EVAL.md`; it reads each check to see what it covers. The PR
description then leaves out the old-code output. A verifier re-check on 3.9 can
rate a condition lower than 3.8 did (Adequate instead of Strong, when no check
covers its edge case or a check is below the level the spec asks for) and can
report a held-out check as too weak; a repair that follows spends a round as
usual.

## Upgrading from 3.7

3.8 rewrites the PR description for reviewers who don't know auto-dev (see
*How the build is verified*). The verifier now writes each `evidence/C<n>.txt`
in a fixed shape (expected, command, result, the last lines of output) for the
description to quote. A run in flight resumes on 3.8: only the description
changes. An evidence file written by an older verifier may have no output in
it; that requirement's entry then leaves the output block out. A PR opened on
3.7 gets the new sections the next time its description is refreshed.

## Upgrading from 3.6

3.7 stamps every report that judges the code (`SPEC_EVAL.md`, `lint/*.md`,
`CODE_REVIEW.md`, `SECURITY_REVIEW.md`) with a `Tree:` line naming the code it
checked, and adds `scripts/check-fresh.py`, which compares the stamps with the
code at each step that relies on them. The PR description gains a `Checked at
commit` line, and the main merge is locked to the checked commit with
`gh pr merge --match-head-commit`. If someone pushes to the PR before the main
gate, the pipeline checks their commits before asking you. A run in flight
resumes on 3.7: its reports have no stamp, which reads as stale, so the next
check re-runs the verifier, the quality gate and the reviews before going on.
Those re-runs spend no iteration budget.

## Upgrading from 3.5

3.6 removes the shipped stack profiles (Elixir, and the `default` discovery
fallback) along with the `profiles/` folder. The first run on each repo now has the new `profiler`
worker research the profile, and pauses once for you to confirm it, with an
offer to save it to `~/.config/auto-dev/profiles/` so later runs skip the
pause (see the README's *Stack profiles*). `.auto-dev.yml` keeps every key; `stack:` now only
names the stack and no longer selects a profile, and the
validator warns when it is set without `setup` and `gate`. A repo whose `.auto-dev.yml`
sets both `setup` and `gate` runs as before, with no research and no pause.
A run in flight resumes on 3.6: Phase 1 never runs again on a resume, and its
`profile.md` is read as written.

## Upgrading from 3.4

3.5 moves the Elixir-only `dexter` rule out of `SKILL.md` into a new optional
profile key, `symbol_lookup`, which any profile or `.auto-dev.yml` can set.
Phase 1 records the resolved lookup in `profile.md`. A run in flight can resume
on 3.5: a `profile.md` written by 3.4 has no _Symbol lookup_ line, and the
orchestrator then uses `grep -n`.

## Upgrading from 3.3

3.4 adds Example, Edge and Verify by lines under every `SPEC.md` condition, an
ambiguity probe in the Define review, and a mutation step in the verifier
(`scripts/mutate.py`, the `mutation.max` key in `.auto-dev.yml`). A run with a
3.3 `SPEC.md` still works: the acceptance tester falls back to the condition's
own words, and the mutation step needs nothing from the spec.

## Upgrading from 3.2

3.3 moves the Phase 5 acceptance check from the orchestrator to two new workers:
the `acceptance-tester`, which runs at the end of Phase 3, and the `verifier`.
It adds `acceptance/` and `evidence/` to `.auto-dev/`, an evidence tier and a
test-integrity section to `SPEC_EVAL.md`, and `scripts/check-tests.py`. A run
whose Phase 3 is already done has no sealed checks: finish it on 3.2, or re-run
its Phase 3 on 3.3 before the build.

## Upgrading from 3.1

3.2 replaces the single PR reviewer, which ran after the PR was opened, with a
code review panel and a separate security review that run before the PR gate.
`PR_REVIEW.md` is replaced by `CODE_REVIEW.md` and `SECURITY_REVIEW.md`, and the
`pr-reviewer` agents by `code-reviewer`, `review-judge`, `security-reviewer` and
`security-reviewer-sensitive`. A run that has not reached Phase 6 resumes
normally. A run already in Phase 6 should be finished on 3.1.

## Upgrading from 2.x

3.0 restructures the pipeline from ten phases to six and changes the artifact set:
`TICKET.md` and `ACCEPTANCE_CRITERIA.md` are merged into `SPEC.md`,
`CODING_TODO.md` is dropped (the plan's build sequence is the coder's worklist),
and `IMPLEMENTATION_EVAL.md` is dropped along with the plan-adherence check. A run
started on 2.x cannot be resumed on 3.0 — its `.auto-dev/` and its `WORK_LOG.md`
phase table won't match. Finish in-flight runs before upgrading.
