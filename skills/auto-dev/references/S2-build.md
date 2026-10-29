# S2 — Build (Phases 4–5)

S2 has no manual steps. `autodev.py next` drives all of it. `autodev.py` means
`python3 <skill-dir>/scripts/autodev.py`.

## 1. Enter the worktree

`cd <worktree>` (the tree `resume` printed). Read `.auto-dev/HANDOFF.md`, and
nothing else in `.auto-dev/`: the only other file it lists, `profile.md`, is
there for a question about the stack, and nothing in S2's loop needs it.

## 2. Run the loop

Follow **The loop** in `SKILL.md` until `next` exits 3, 4 or 6. What you will
see in S2, in order:

1. `coder` builds from the plan.
   - It may return `BLOCKED`: `next` sends the `planner` in blocked mode, then
     the coder again (a round), or the acceptance tester first when the plan's
     entry points changed.
   - It may file **plan and check proposals** (`proposals/coder-<n>.md`: a step
     of the plan, or a held-out check its correction brief listed, is wrong).
     `next` spends one round (`BUDGET:`, `coder-<n>`; a result that is also
     `BLOCKED` spends only that one), then sends them to their owners in
     order: the `planner` (in revise mode, or in blocked mode when the coder
     also stopped steps; one answer covers both), the free
     `acceptance-tester` repair when the revised plan's entry points changed,
     then the `acceptance-tester` in repair mode on the check proposals, one
     ruling per condition, and then the `coder` again in its mode, told only
     `repaired` or `stands` for each proposal and, when the plan changed, its
     revised lines. A step or condition already ruled to stand is not sent
     again: a result whose proposals are all on such items goes on from its
     `next` token, spending nothing. With no round left, nothing is sent: a
     `BUILT` result goes on, a `BLOCKED` one goes to the planner in blocked
     mode as before, and the next stop report or the PR gate summary names
     each proposal not sent.
2. `next` installs the sealed checks in the worktree itself (a check that
   adds tests to an existing file goes in among the coder's lines; if one
   can't, the `acceptance-tester` in fold mode adds its tests to the coder's
   file first, no round spent), then `cleanup`
   simplifies the change and runs the quality gate to green. A check that
   fails the gate goes to the `acceptance-tester` in repair mode, then cleanup
   again.
3. `verifier`, first pass, on the cleaned code: it runs the sealed checks
   against the spec and writes its verdicts and, if anything is open,
   `evidence/corrections.md`. (If a sealed check still can't go in after the
   fold, `next` installs nothing and the verifier goes first, to report it.)
4. While something is open: the `coder` in correction mode with that file
   (each one spends a round; `BUDGET:` shows what's left), then `cleanup`, then
   a `verifier` re-check. Defective checks go to the `acceptance-tester` first, in repair
   mode, as a batch of check proposals with one ruling per condition
   (`proposals/checks-<k>.md`): it fixes them (then `cleanup` runs the gate on
   the repaired checks before the re-check), or rules they stand with its
   reason, and the verifier then judges those checks as written (every later
   verifier brief's `rulings:` line names them). A condition
   whose checks stand is never sent back for the rest of the run, unless a
   spec change or an entry-point repair rewrites them; if the verifier and the
   tester still disagree with nothing else open, `next` stops and reports both
   sides. When a verifier result carries a spec proposal and defective checks,
   the `define` agent rules first and the tester only after its answer; a
   spec change applied to a condition also rewrites that condition's checks,
   so its separate repair is not sent.
   - A verifier result may carry a **spec proposal** (`proposals/verifier-<n>.md`:
     SPEC.md itself is wrong). `next` sends it to the `define` agent in revise
     mode first, spending the round the result's correction would (`BUDGET:`).
     On `STANDS`, the result is acted on as if it carried no proposal, and
     every later verifier is told the ruling; a proposal on a condition that
     stood is never sent again. When a verifier proposes on a condition that
     stood (in this result or a later one) and judges it partial or unmet, the
     code does what the proposal described: before the correction would undo
     it, `next` asks the **deviation gate** (exit 5, one condition at a time;
     _What each gate option does_ in `references/tables.md`). Accepting costs
     no round: the verifier re-checks, told the deviation is accepted, and later
     review passes are told too. Accept is not offered for an unmet condition.
     On an applied change, `next` runs the redo,
     spending nothing more: the `planner` in revise mode, the
     `acceptance-tester` in write mode for only the changed conditions' checks
     (rewritten in place), a free `acceptance-tester` repair when the plan's
     entry points changed, the `coder` with the plan's change when the plan
     changed (else straight to `cleanup`), `cleanup`, then a `verifier` first
     pass. The verifier's earlier corrections are dropped. With no round left,
     nothing is sent and the stop report names the proposal.
5. Exit 6: run its `AFTER` command exactly as printed (`handoff` at the end of the
   session, `handoff --checkpoint` at a checkpoint), give the user its message,
   stop.

A worker whose result `record` refuses (exit 1) is briefed again by the next
`next`, with the refused issues. You pass every file on as `next` names it. You never read `SPEC_EVAL.md`,
`corrections.md` or the code.

## Stops in S2

Every stop is exit 4 with its reason in `REPORT`
(`references/tables.md`, _Stop conditions_). The usual ones here:

- the budget ran out with conditions still unmet (#12): tell the user each one
  the `REPORT` names;
- the quality gate can't go green (#10);
- the spec can't be met as written (#9);
- the mutation step may have left a change in the source (#11): tell the user
  not to build on the tree until they've checked the paths named (a spec
  proposal the verifier filed with it is named, not sent);
- a spec redo's rewritten checks still have gaps after the tester's one free
  re-spawn, or a condition still reads two ways after the Define agent's one
  ruling (#21).
