# Acceptance checks — due dates

| # | Condition | Check (path :: test name) | Covers | Level | Kind | Base run |
|---|-----------|---------------------------|--------|-------|------|----------|
| 1 | due date shown | `src/due.acceptance.test.ts` :: "shows the due date" | Example | integration | fail-to-pass | failed: no field |
| 1 | due date shown | `src/due.acceptance.test.ts` :: "rejects an invalid date" | Edge | integration | fail-to-pass | failed: 200 |
| 2 | sorted | `src/sort.acceptance.test.ts` :: "sorts earliest first" | Example | unit | fail-to-pass | failed: unsorted |
| S1 | owner only | `src/due.acceptance.test.ts` :: "owner only" | Example | integration | fail-to-pass | failed: 200 |

## Not automatable
None.

## Assumptions
- none
