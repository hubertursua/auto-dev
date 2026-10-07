# Work Log

- **Task:** Add multi-currency support across the wallet, the ledger and the payout service
- **Ticket:** none — wallets, ledger entries and payouts carry a currency; amounts in different currencies are never summed together
- **Repo:** <repo-name>   **Base:** main   **Stack:** elixir
- **Control worktree:** <abs-path-to-control-worktree>   **Branch:** feat/multi-currency
- **Mode:** multi-PR   **Scope call:** OVERSIZED   (`OVERSIZED` runs multi-PR)
- **Iteration budget:** 4 total revise rounds per sub-task

## Sub-tasks
| id | slug | depends on | scope | budget | status | branch | worktree | PR |
|----|------|-----------|-------|--------|--------|--------|----------|----|
| 01 | wallet-currency | — | STANDARD | 3/4 | done | feat/multi-currency-01 | <abs-path-01> | <pr-url-01> |
| 02 | ledger-currency | 01 | STANDARD | 2/4 | in-progress | feat/multi-currency-02 | <abs-path-02> | |
| 03 | payout-currency | 01, 02 | — | 4/4 | pending | | | |

### 01-wallet-currency
| # | Phase | Status | Notes |
|---|-------|--------|-------|
| 2 | Define | done | scope call STANDARD |
| 3 | Plan | done | |
| 4 | Build | done | |
| 5 | Verify | done | 1 acceptance correction |
| 6 | Ship | done | merged; staging gate: n/a (no staging branch) |

### 02-ledger-currency
| # | Phase | Status | Notes |
|---|-------|--------|-------|
| 2 | Define | done | scope call STANDARD; 1 define re-review |
| 3 | Plan | done | 1 plan re-review |
| 4 | Build | in-progress | cut off mid-build |
| 5 | Verify | pending | |
| 6 | Ship | pending | staging gate: n/a (no staging branch) |

## Decisions & assumptions
- Decomposition approved by the user: 01 → 02 → 03, one PR each.
- 01: currency is an ISO 4217 code stored on the wallet; existing wallets default to the account's currency in the migration.
