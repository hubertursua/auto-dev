# Security review — feat/due-dates

**Overall confidence: High** — finished: yes; coverage: full; High/Medium verified: 1/1
Run 1 — reviewer: security-reviewer — scope: the whole change since `abc`
Tree: {tree}
Must-fix: 0 open · 0 fixed   ·   For the user (pre-existing): 1   ·   Advisory: 0

## Findings
| ID | Finding | Location | Origin | Confidence | Verified | Verdict | Status |
|----|---------|----------|--------|------------|----------|---------|--------|
| S2 | session token not rotated | `src/auth.ts:88` | pre-existing | Medium | confirmed | for the user | — |

## Coverage
Every changed file.
