# Handoff — allowed-set guard → S2 Build (next session)

Re-enter with: `cd <abs-path-to-worktree>`
Branch: feat/allowed-set-guard   Base: origin/main   Sub-task: n/a
Iteration budget remaining: 4/4

## Done
- Phase 1: worktree created, elixir profile loaded, .auto-dev/ excluded.
- Phase 2: SPEC.md written; scope call STANDARD; define review clean.
- Phase 3: IMPLEMENTATION.md written; plan review clean.

## Next
Phase 4 — Build. Spawn the coder (`auto-dev:coder`) with IMPLEMENTATION.md only.
Pick up at: start of Phase 4

## Files that matter
- <abs-path-to-worktree>/.auto-dev/WORK_LOG.md — ledger and budget
- <abs-path-to-worktree>/.auto-dev/profile.md — gate commands and CI provider
- <abs-path-to-worktree>/.auto-dev/IMPLEMENTATION.md — the coder's only input
- <abs-path-to-worktree>/.auto-dev/SPEC.md — yours for the Phase 5 acceptance check

## Open assumptions
- An out-of-set value is rejected outright; no default is substituted.

## Do not
- Re-run Phase 1, re-detect the stack, or re-review the spec or plan.
- Give the coder SPEC.md.
