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
2. `next` installs the sealed checks in the worktree itself, then `cleanup`
   simplifies the change and runs the quality gate to green. A check that
   fails the gate goes to the `acceptance-tester` in repair mode, then cleanup
   again.
3. `verifier`, first pass, on the cleaned code: it runs the sealed checks
   against the spec and writes its verdicts and, if anything is open,
   `evidence/corrections.md`. (If a sealed check's path already holds another
   file, `next` installs nothing and the verifier goes first, to report it.)
4. While something is open: the `coder` in correction mode with that file
   (each one spends a round; `BUDGET:` shows what's left), then `cleanup`, then
   a `verifier` re-check. Defective checks go to the `acceptance-tester` first, in repair
   mode: it fixes them (then `cleanup` runs the gate on the repaired checks
   before the re-check), or answers `STANDS` with its reason, and the verifier
   then judges those checks as written. A check that stands is never sent back
   on the same condition; if the verifier and the tester still disagree, `next`
   stops and reports both sides.
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
  not to build on the tree until they've checked the paths named.
