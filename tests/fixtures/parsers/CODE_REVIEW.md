# Code review — feat/due-dates

**Overall confidence: provisional (re-votes pending)** — reviewers finished: 3/3; coverage: full; must-fix decided 2–1: none
Latest pass: 1 — scope: whole change
Tree: {tree}
Must-fix: 1 open · 0 fixed   ·   Advisory: 0   ·   Noise: 0   ·   Dropped (pre-existing): 0

## Must-fix
| ID | Finding | Location | Category | Votes | Confidence | Status |
|----|---------|----------|----------|-------|------------|--------|
| C1 | null due date crashes sort | `src/sort.ts:4` | correctness | 3/3 | High | open |

## Pending re-vote
| ID | Finding | Location | Category | Raised by | Re-voters | Votes |
|----|---------|----------|----------|-----------|-----------|-------|
| C4 | empty list indexed | `src/list.ts:42` | correctness | R1 | R2, R3 | |
| C6 | blank title saved | `src/save.ts:18` | tests | R2 | R1, R3 | |

### C4 — empty list indexed
Trigger path: `GET /todos` with no todos → `src/list.ts:42` reads `items[0].id`
Judge: confirmed; nothing guards the empty list.
Required change: in `src/list.ts`, return an empty page when there are no todos instead of reading the first item
In plain words: listing todos crashed when there were none.

### C6 — blank title saved
Trigger path: `POST /todos` with title "" → `src/save.ts:18`
Judge: confirmed.
Required change: in `src/save.ts`, reject a blank title with the existing validation error
In plain words: a todo could be saved with no title.

## Advisory
| ID | Finding | Location | Category | Votes | Confidence | Why advisory |
|----|---------|----------|----------|-------|------------|--------------|

## Noise
none

## Passes
| Pass | Scope | Reviewers finished | Must-fix found | Re-votes |
|------|-------|--------------------|----------------|----------|
| 1 | whole change | 3/3 | 1 | 2 |
