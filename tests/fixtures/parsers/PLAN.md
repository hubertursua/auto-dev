# Plan — due dates

Risk: high — only the owner may set a due date
Review effort: high — a small change

## Context
Todos have no due dates.

## Conditions
1. A todo can carry a due date that the list shows next to its title
   - Example: Given todo 7, when its due date is set to 2026-01-02, then the list shows 2026-01-02.
   - Edge: an invalid date is rejected → 400
   - Verify by: integration
2. The list sorts todos by due date with the earliest first
   - Example: Given two todos, when listed, then the earlier one is first.
   - Edge: none — every todo has a place in the order
   - Verify by: unit

## Assumptions
- none

## Security/Compliance criteria
S1. Only the owner can set a todo's due date
   - Example: Given user B, when B sets A's due date, then it is refused with 404.
   - Verify by: integration

## Size check
FITS — one field and one sort

## Files
- `src/due.ts` — modify: add the due date

## Design
A due date on each todo, sorted earliest first.

## Build sequence
1. add the field — conditions: C1, S1 — test: `src/due.test.ts`
2. sort the list — conditions: C2 — test: `src/sort.test.ts`

## Test plan
| Test | Location | Proves | Condition |
|------|----------|--------|-----------|
| shows the due date | `src/due.test.ts` | the field | 1 |

## Migrations / config
none
