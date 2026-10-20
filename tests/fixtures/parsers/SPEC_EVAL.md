# Acceptance evaluation — due dates

Read from the working tree, against the commit the worktree was cut from (`abc`).
Tree: {tree}
Pass: first · acceptance run: 4 passed / 4 total (`evidence/acceptance.txt`)

| # | Condition | Verdict | Tier | Evidence |
|---|-----------|---------|------|----------|
| 1 | due date shown | {v1} | Strong | acceptance passed (`evidence/C1.txt`) |
| 2 | sorted | {v2} | Adequate | {e2} |
| S1 | owner only | met | Strong | acceptance passed |

## Test integrity
`check-tests.py` exit 0 (`evidence/integrity.txt`)

| Finding | Location | Judgment | Reason |
|---------|----------|----------|--------|
| REMOVED_ASSERTION | `src/todos.test.ts:-42` | {judgment} | condition 1 changes the response |

## Mutation
4 mutants (cap 20): 3 killed · 0 timeout (counted caught) · 1 survived · 0 invalid

| Mutant | Location | Change | Condition | Judgment |
|--------|----------|--------|-----------|----------|
| M2 | `src/sort.ts:4` | `a < b` → `a <= b` | — | Equivalent — no two todos share a date |

## Defective acceptance checks
{defective}

## Unresolved
none
