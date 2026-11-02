<!-- auto-dev template: JUDGMENT.md (strict) — review/pass-<n>/JUDGMENT.md, the review judge's calls on the panel's merged findings (review/pass-<n>/findings.md). `autodev.py review-build` builds CODE_REVIEW.md and the pass's corrections.md from it. One `## J<k>` block per finding you judge, numbered from J1: one block can merge several F findings (`From:`), and every F finding is in exactly one `From:` line. Each line stays on one line. `Holds:` is `yes`, `no — <why the path fails or the code already handles it>`, or `pre-existing — <why>`. The six lines from `Trigger path:` on are required when it holds and its Category is correctness, tests or acceptance-check, and may be left out otherwise. With no findings (findings.md says so), write no `## J<k>` block. `## Earlier must-fix` names every earlier must-fix finding findings.md lists as open, or `none`. `## Security leads` copies each lead findings.md gives word for word, ending `→ passed to the security review` or `→ covered by S<n>`, or `none`. Filled-in values are an example in TypeScript. Copy everything below this comment, filling in every <...>. -->
# Judgment — pass <n>

## J1
- From: <F1, F3>
- Finding: <title>
- Location: `<path:line>`
- Category: <correctness | tests | acceptance-check | scope | performance | design | conventions | style>
- Holds: <yes | no — <why> | pre-existing — <why>>
- Trigger path: <entry point `file:line` → … → failure, as you confirmed it>
- Judge: <why it holds>
- Where: `<path:line>` — <the code, or the acceptance check, that has to change>
- Test: <the test to add or restore, and what it asserts; for a tests finding, one per case it lists, separated by `;`>
- Required change: <what must change and where: for the coder, or for the acceptance tester when the category is acceptance-check>
- In plain words: <one sentence for the PR's reader>

## Earlier must-fix
- <C2>: <fixed | open>

## Security leads
- `src/todos/export.ts:31` — <lead> (raised by R<k>) → <passed to the security review | covered by S<n>>
