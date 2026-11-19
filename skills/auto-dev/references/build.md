# Build stage (Phases 4–5)

`autodev.py next` drives the Build stage; the one step it hands you is running
the quality gate. `autodev.py` means `python3 <skill-dir>/scripts/autodev.py`.

## 1. Enter the worktree

Coming from the Plan stage, you are in it already. On a run resumed in the
Build stage, `cd <worktree>` (the tree `resume` printed) and read
`.auto-dev/HANDOFF.md` if there is one, and nothing else in `.auto-dev/`: the only other file it
lists, `profile.md`, is there for a question about the stack, and nothing in
this stage's loop needs it.

## 2. Run the loop

Follow **The loop** in `SKILL.md` until `next` exits 3, 4 or 6. `next` names
each worker to spawn. The steps that are yours:

- **The quality gate.** `next` asks **you** to run it as a script, with no
  worker: `autodev.py quality-gate --dir <artifact-dir>`, with the Bash tool's
  timeout at 600000 ms (when the whole gate can take longer, run it in the
  background and wait for it). Whatever it exits, run its `AFTER` line
  (`next`). You never read the lint reports or the code.
- **Into the Ship stage.** Once the gate is green, `next` says the run goes on
  to the Ship stage in this session: read `references/ship.md`, as its
  `ACTION` says, then run `next`. Don't stop or hand off.

## Stops in the Build stage

Every stop is exit 4 with its reason in `REPORT`
(`references/tables.md`, _Stop conditions_), and most ask how to go on
(`SKILL.md`, _A stop_). The usual ones here:

- the quality gate is still red after the coder's correction, or `next` asked
  for the gate 3 times on the same code with no run recorded (#9): the user
  fixes it (the fixer, or themselves), retries (_I fixed it myself_ runs the
  gate again), or signs the failing checks off, which counts them green for
  the rest of the run;
- the coder stopped a step and the planner found the conditions can't be met
  as written (#8), or the coder stopped a step again after the planner's
  decision (#22).
