<!-- auto-dev template: spec proposals (strict) — proposals/<worker>-<n>.md, written by the verifier, the review judge (consolidate mode), the security reviewer or the triager (human mode) when SPEC.md itself is wrong or incomplete. One `## P<k>` block per proposal, numbered from P1. A proposal changes the conditions its Target names (New text holds each one's whole new statement, numbered as now) or adds one item: `new condition`, numbered after the last condition, or `new security criterion`, written `S<k>.` after the last S row (S1 when there is none) with Example and Verify by lines only. It never removes or renumbers a condition, and never names an existing S row. `Comment:` is the PR comment's id for a proposal from a PR comment, else `none`. `next` copies the parts it sends into proposals/batch-<k>.md, with an extra `- From:` line. A filer with nothing to propose writes no file. Copy everything below this comment, filling in every <...>. -->
# Spec proposals

## P1
- Target: <condition <n> | conditions <n>, <m> | new condition | new security criterion>
- Why: <what the code, a review or a PR comment showed that SPEC.md gets wrong or leaves out, in your own words>
- Comment: <the PR comment's id, for a proposal from a PR comment; else none>
- New text:
<n>. <the condition's whole new statement, as SPEC.md would read>
   - Example: Given <...>, when <...>, then <...>.
   - Edge: <...> → <...>
   - Verify by: <unit | integration | end-to-end | manual — <why>>
