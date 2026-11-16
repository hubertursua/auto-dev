<!-- auto-dev template: PLAN.md (headings strict). Copy everything below this comment, filling in every <...>. -->
# Plan — <task>

Risk: <standard | high> — <one line: why>
Review effort: <high | xhigh> — <one line: why the code reviewers need that depth>

## Context
<the ask restated, links, and the research findings needed to act on it: where
this lives in the code, the modules and flows involved, similar precedents,
constraints>

## Conditions
1. <observable, testable condition in plain language: what must be true, not how>
   - Example: Given <starting state>, when <action>, then <observable result>.
   - Edge: <negative, boundary or error case> → <observable result>
     (or `none — <why the condition has no edge>`)
   - Verify by: <unit | integration | end-to-end | manual — <why no agent can observe it>>
2. <…>

<where a condition is hard to observe, say so in Verify by and give the closest
observable proxy>

## Assumptions
- <each ambiguity resolved, and how it was resolved>

## Security/Compliance criteria
S1. <the specific control, pulled from the sources profile.md names>
   - Example: Given <state>, when <the abusive or unauthorized action>, then <it is refused, and how>.
   - Verify by: <unit | integration | end-to-end | manual — <why>>
<Omit this section entirely when the task touches no sensitive path.>

## Size check
<FITS or OVERSIZED, with one line of why. For OVERSIZED, add a `- Subsystem:` line
for each subsystem touched, with a rough file count, and a `- Split:` line for each
suggested part of the task.>

## Files
- `<path>` — <create | modify>: <what changes there>

## Design
<modules, functions, data structures, how data moves through the change, and
why this shape where it is not obvious>

## Build sequence
1. <small, independently verifiable unit> — conditions: <C1, …> — test: `<test file>`
2. <…>

## Test plan
| Test | Location | Proves | Condition |
|------|----------|--------|-----------|
| <test name> | `<path>` | <the behavior> | <#> |

## Migrations / config
<schema migrations, config or env changes — or "none">
