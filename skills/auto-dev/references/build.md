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
     the coder again (no round), or the acceptance tester first when the plan's
     entry points changed.
   - When a plan step is wrong as written, the coder builds it the way that
     works and lists the deviation in `deviations/coder-<n>.md`. Nothing is
     sent anywhere and no round is spent; the ready-for-review gate's summary names each
     deviation.
   - Before it returns, the coder runs the quality gate to green itself.
2. The quality gate, which `next` asks **you** to run as a script, with no
   worker: `autodev.py quality-gate --dir <artifact-dir>`, with the Bash tool's
   timeout at 600000 ms (when the whole gate can take longer, run it in the
   background and wait for it; asked 3 times on the same code with no run
   recorded, `next` stops, #9). A run counts only for the code and the gate
   commands it ran on: a changed command runs it again. It runs every check of the profile's gate, in order,
   and writes one `lint/<REPORT>.md` per check (the acceptance checks are in
   the tree already, committed before the build). Whatever it exits, run its
   `AFTER` line (`next`). `GREEN` ends the stage. `RED` sends the `coder` in
   correction mode with the failing reports (no round), then the gate again. Red again after that correction is a stop (#9):
   the user fixes it (the fixer, or themselves), retries (_I fixed it myself_
   runs the gate again), or signs the failing checks off, which counts them
   green for the rest of the run.
3. Once the gate is green, `next` re-checks the risk tier from the diff (a
   sensitive path or a large change makes the run high-risk; it never goes
   down). Nothing is verified or reviewed here: the verifier and the review
   run on the draft PR, in the Ship stage (`references/ship.md`).
4. Once the gate is green, `next` says the run goes on to the Ship stage in
   this session: read `references/ship.md`, as its `ACTION` says, then run
   `next`. Don't stop or hand off.
5. Exit 6, a checkpoint: run its `AFTER` command exactly as printed (`handoff
   --checkpoint`), give the user its message, stop. A fresh session picks the
   run up where it is.

A worker whose result `next` refuses (a `RECORDED: … refused` line) is briefed
again by that `next`, with the refused issues. You pass every file on as `next` names it. You never read the lint reports
or the code.

## Stops in the Build stage

Every stop is exit 4 with its reason in `REPORT`
(`references/tables.md`, _Stop conditions_), and most ask how to go on
(`SKILL.md`, _A stop_). The usual ones here:

- the budget ran out before the quality gate's correction (#11): tell the user,
  and that they can go on with more rounds if they say how many
  (`references/tables.md`, _The iteration budget_);
- the quality gate is still red after the coder's correction (#9);
- the coder stopped a step and the planner found the conditions can't be met
  as written (#8).
