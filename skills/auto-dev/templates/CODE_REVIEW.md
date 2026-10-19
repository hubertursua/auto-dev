<!-- auto-dev template: CODE_REVIEW.md (strict). Copy everything below this comment, filling in every <...>. -->
# Code review — <branch>

**Overall confidence: <High | Medium | Low | provisional (re-votes pending)>** — <reviewers finished: n/3; coverage: full | partial; must-fix decided 2–1: <IDs | none>>
Latest pass: <n> — scope: <scope>
Tree: <hash from check-fresh.py --print-tree for this pass>
Must-fix: <open> open · <fixed> fixed   ·   Advisory: <n>   ·   Noise: <n>   ·   Dropped (pre-existing): <n>

## Must-fix
| ID | Finding | Location | Category | Votes | Confidence | Status |
|----|---------|----------|----------|-------|------------|--------|
| C1 | <title> | `path:line` | correctness | 3/3 | High | open |
| C2 | <title> | `path:line` | tests | 2/3 (re-vote) | Medium | fixed (pass 2) |

### C1 — <title>
Trigger path: <entry point `file:line` → … → failure, as the judge confirmed it>
Judge: <why it holds>
Required change: <what the code must do and where, for the coder>
In plain words: <one sentence for the PR's reader>

## Pending re-vote
| ID | Finding | Location | Category | Raised by | Re-voters | Votes |
|----|---------|----------|----------|-----------|-----------|-------|

## Advisory
| ID | Finding | Location | Category | Votes | Confidence | Why advisory |
|----|---------|----------|----------|-------|------------|--------------|

## Noise
| ID | Finding | Raised by | Why dismissed |
|----|---------|-----------|---------------|

## Security leads
- `path:line` — <lead> (raised by R<k>) → passed to the security review

## Passes
| Pass | Scope | Reviewers finished | Must-fix found | Re-votes |
|------|-------|--------------------|----------------|----------|
| 1 | whole change | 3/3 | 2 | 1 |
