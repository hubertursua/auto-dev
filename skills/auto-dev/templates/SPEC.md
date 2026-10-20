<!-- auto-dev template: SPEC.md (strict). Copy everything below this comment, filling in every <...>. -->
# Spec — <task>

## Context
<the ticket restated, links, and the research findings needed to act on it: where
this lives in the code, the modules and flows involved, similar precedents,
constraints. Stakeholder-readable; no technical design.>

## Conditions
1. <observable, testable condition in plain language — no file names, no signatures>
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
