<!-- auto-dev template: SECURITY_REVIEW.md (strict). Copy everything below this comment, filling in every <...>. -->
# Security review — <branch>

**Overall confidence: <High | Medium | Low>** — <finished: yes | no; coverage: full | partial; High/Medium verified: <n>/<n>>
Run <n> — reviewer: <security-reviewer | security-reviewer-sensitive> — scope: <the whole change since `<merge-base>` | a focused re-check of <the brief's focus>; the rest carried from run <n-1>>
Tree: <hash from check-fresh.py --print-tree for this run>
Must-fix: <open> open · <fixed> fixed   ·   For the user (pre-existing): <n>   ·   Advisory: <n>

## Findings
| ID | Finding | Location | Origin | Confidence | Verified | Verdict | Status |
|----|---------|----------|--------|------------|----------|---------|--------|
| S1 | <title> | `path:line` | introduced | High | confirmed | must-fix | open |
| S2 | <title> | `path:line` | pre-existing | Medium | confirmed | for the user | — |
| S3 | <title> | `path:line` | introduced | Low | — | advisory | — |

### S1 — <title>
Path: <untrusted input → `file:line` → … → the exploit>
Depends on: <the configuration or assumption — Medium only>
Verified: <the judge's reason>
Required change: <confirmed, introduced must-fix only: what the code must do and where>
In plain words: <one sentence for the PR's reader>

## Panel leads checked
| Lead | Result |
|------|--------|
| `path:line` — <lead> | <finding ID, or "not a vulnerability: <why>"> |

## Coverage
<what was covered; any file not covered, and why>
