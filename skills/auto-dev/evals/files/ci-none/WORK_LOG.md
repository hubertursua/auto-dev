# Work Log

- **Task:** Make the expiry validation error name the invalid field
- **Ticket:** none — the expiry validation error says 'invalid date'; it should say which field was invalid
- **Repo:** <repo-name>   **Base:** main   **Stack:** <profile>
- **Worktree:** <abs-path-to-worktree>   **Branch:** fix/expiry-error-field
- **Size:** FITS   **High risk:** no
- **Iteration budget:** 4 total revise rounds (4 remaining)

## Phase status
| # | Phase | Status | Notes |
|---|-------|--------|-------|
| 1 | Setup | done | CI provider: none (no CI config found) |
| 2 | Define | done | size FITS; define review clean on first pass |
| 3 | Plan | done | plan review clean on first pass; acceptance checks sealed |
| 4 | Build | done | |
| 5 | Verify | done | all conditions met; quality gate green |
| 6 | Ship | pending | staging gate: n/a (no staging branch) |

## Decisions & assumptions
- Phase 2: the message names the field as it appears in the API params.
