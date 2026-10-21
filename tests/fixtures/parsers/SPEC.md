# Spec — due dates

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
