# Build stage (Phases 4–5)

The Build stage has no manual steps. `autodev.py next` drives all of it. `autodev.py` means
`python3 <skill-dir>/scripts/autodev.py`.

## 1. Enter the worktree

Coming from the Plan stage, you are in it already. On a run resumed in the
Build stage, `cd <worktree>` (the tree `resume` printed) and read
`.auto-dev/HANDOFF.md` if there is one, and nothing else in `.auto-dev/`: the only other file it
lists, `profile.md`, is there for a question about the stack, and nothing in
this stage's loop needs it.

## 2. Run the loop

Follow **The loop** in `SKILL.md` until `next` exits 3, 4 or 6. What you will
see in the Build stage, in order:

1. `coder` builds from the plan.
   - It may return `BLOCKED`: `next` sends the `planner` in blocked mode, then
     the coder again (a round), or the acceptance tester first when the plan's
     entry points changed.
   - When a plan step is wrong as written, the coder builds it the way that
     works and lists the deviation in `deviations/coder-<n>.md`. Nothing is
     sent anywhere and no round is spent; the ready-for-review gate's summary names each
     deviation.
2. `next` installs the sealed checks in the worktree itself (a check that
   adds tests to an existing file goes in among the coder's lines; if one
   can't, the `acceptance-tester` in fold mode adds its tests to the coder's
   file first, no round spent), then `cleanup`
   simplifies the change and runs the quality gate to green. A check that
   fails the gate goes to the `acceptance-tester` in repair mode, then cleanup
   again.
3. `verifier`, first pass, on the cleaned code: it runs the sealed checks
   against the plan's conditions and writes its verdicts and, if anything is open,
   `evidence/corrections.md`. (If a sealed check still can't go in after the
   fold, `next` installs nothing and the verifier goes first, to report it.)
4. While something is open: the `coder` in correction mode with that file
   (each one spends a round; `BUDGET:` shows what's left), then `cleanup`, then
   a `verifier` re-check. Defective checks go to the `acceptance-tester` first,
   in repair mode, on the same round: it repairs them (then `cleanup` runs the
   gate on the repaired checks before the re-check), or answers `STANDS` when
   it finds a check right as written. A `STANDS` stops the run (#21): the user
   decides, and a sign-off keeps the checks as written, which every later
   verifier is told (`checks_kept`).
   - A verifier that finds PLAN.md's conditions wrong or incomplete still
     judges every condition as written, and lists the problem in
     `spec-problems/verifier-<n>.md`. `next` stops before acting on that result
     (#20): no worker changes the plan's conditions. The user says how to
     change them (the fixer edits PLAN.md, and the checks when they say so; then the
     verifier's first pass runs again), retries, or signs off, which keeps
     PLAN.md as written and goes on with the result's correction; later
     verifiers are told what the user kept (`spec_kept`).
5. Once the build is verified, `next` says the run goes on to the Ship stage in
   this session: read `references/ship.md`, as its `ACTION` says, then run
   `next`. Don't stop or hand off.
6. Exit 6, a checkpoint: run its `AFTER` command exactly as printed (`handoff
   --checkpoint`), give the user its message, stop. A fresh session picks the
   run up where it is.

A worker whose result `next` refuses (a `RECORDED: … refused` line) is briefed
again by that `next`, with the refused issues. You pass every file on as `next` names it. You never read `SPEC_EVAL.md`,
`corrections.md` or the code.

## Stops in the Build stage

Every stop is exit 4 with its reason in `REPORT`
(`references/tables.md`, _Stop conditions_), and most ask how to go on
(`SKILL.md`, _A stop_). The usual ones here:

- the budget ran out with conditions still unmet (#11): tell the user each one
  the `REPORT` names, and that they can go on with more rounds if they say how
  many (`references/tables.md`, _The iteration budget_);
- the quality gate can't go green (#9);
- the conditions can't be met as written (#8);
- the mutation step may have left a change in the source (#10): tell the user
  not to build on the tree until they've checked the paths named;
- the verifier found a criterion wrong or missing (#20), or the acceptance
  tester ruled a check right that the verifier called defective (#21): tell
  the user each item the `REPORT` names, and ask how to go on.
