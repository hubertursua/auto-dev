<!-- auto-dev template: MANIFEST.md (strict). Filled-in rows are an example in TypeScript. Replace them. Copy everything below this comment, filling in every <...>. -->
# Acceptance checks — <task>

Written from SPEC.md alone, run on the untouched tree at <short sha> (`git rev-parse HEAD` before any check was written: the commit the worktree was cut from).
Sealed copies are under `files/`; the verifier installs them after the build.
Each condition's run on that tree is in `base-run/C<n>.txt`.

| # | Condition | Check (path :: test name) | Covers | Level | Kind | Base run |
|---|-----------|---------------------------|--------|-------|------|----------|
| 1 | <condition, in the spec's own words> | `src/todos/todos.test.ts` :: "owner deleting a todo removes it from the list" | Example | integration | fail-to-pass | failed: `TypeError: todos.delete is not a function` |
| 1 | <same condition> | `src/todos/todos.test.ts` :: "deleting a todo that does not exist returns not found" | Edge | integration | fail-to-pass | failed: `TypeError: todos.delete is not a function` |
| 2 | <condition> | <path :: name> | <Example, Edge, or Other: <which part>> | <unit, integration or end-to-end> | pass-to-pass | passed |
| S1 | <security/compliance criterion> | <path :: name> | Example | integration | fail-to-pass | failed: expected 404, got 200 |

A fail-to-pass check whose Base run is not a right-reason failure does not belong
here. A repaired check reads `not re-run (repair)`. Covers may name more than
one part (`Example, Edge`) when one check covers both.

## Not automatable
| # | Condition | Why no check can drive it | Proxy a verifier can run |
|---|-----------|---------------------------|--------------------------|
| <n> | <condition> | <reason> | <command, request or log line — or "none"> |
| <n> (Edge) | <the condition's Edge line> | <reason> | <proxy — or "none"> |

<"None." when every condition, and every Edge, has a check>

## Assumptions
- <each choice made about entry points or expected values, and why>
