<!-- auto-dev template: SPEC_EVAL.md (strict). Filled-in rows are an example in TypeScript. Replace them. Copy everything below this comment, filling in every <...>. -->
# Acceptance evaluation — <task>

Read from the working tree, against the commit the worktree was cut from (`<CUT sha>`).
Tree: <hash from check-fresh.py --print-tree after your last run>
Pass: <first | re-check after <what changed>> · acceptance run: <n passed / n total> (`evidence/acceptance.txt`)

| # | Condition | Verdict | Tier | Evidence | In plain words |
|---|-----------|---------|------|----------|----------------|
| 1 | <condition, in the spec's own words> | met | Strong | acceptance `todos.test.ts` :: "owner deleting…" passed (`evidence/C1.txt`) | the test written before the code passes |
| 2 | <condition> | met | Adequate | expected `GET /todos` without the deleted id; saw it (`evidence/C2.txt`) | checked by listing the todos after a delete |
| 3 | <condition> | partial | Weak | <what holds, what was not run, and why> | <the same, for a reader who doesn't know this pipeline> |
| 4 | <condition> | unmet | Strong | acceptance check failed: <the failing assertion, one line> | <what still fails, in a sentence> |
| 5 | <condition> | manual | — | a human must check: <exactly what, and how> | <what a person should check> |
| S1 | <security/compliance criterion> | met | Strong | <check passed> | <one sentence> |

Verdicts: `met` needs every acceptance check for the condition passing AND Strong
or Adequate evidence AND no surviving mutant judged a test gap on its lines; Weak evidence caps a condition at `partial`; a failing
acceptance check is `unmet`; `manual` only for a condition MANIFEST.md lists as not
automatable that could not be observed here either. Security/compliance criteria
are rows in this table — never a separate pass.

## Test integrity
`check-tests.py` exit <0 | 1 | 3> (`evidence/integrity.txt`)

| Finding | Location | Judgment | Reason |
|---------|----------|----------|--------|
| REMOVED_ASSERTION | `src/todos/todos.test.ts:-42` | Justified | condition 3 changes the response to 404 |
| ADDED_SKIP | `src/todos/list.test.ts:10` | Unjustified | no condition removes this behavior |

<"None." when the audit is clean and the diff shows no gaming>

## Mutation
<n> mutants (cap <n> | off): <n> killed · <n> timeout (counted caught) · <n> survived · <n> invalid · <n> carried forward (`evidence/mutation-record.json`)

| Mutant | Location | Change | Condition | Judgment |
|--------|----------|--------|-----------|----------|
| M4 | `src/todos/todos.ts:58` | `n <= 10` → `n < 10` | 2 | Test gap — no test accepts exactly 10; condition 2 partial |
| M7 | `src/todos/todos.ts:71` | `items.sort(byDue)` → `items.sort((a, b) => byDue(b, a))` | — | Equivalent — the list has at most one element here |

<this pass's survivors only: a carried-forward mutant was caught, so it is never listed; "None survived." when none did>

## Defective acceptance checks
<each check that asserts something SPEC.md does not say, or is too weak for
what MANIFEST.md says it covers, named as MANIFEST.md names it (`path` ::
"test name"), and why — or "None.">

## Unresolved
<every condition still partial or unmet, and every Unjustified finding, as this
pass found them, then every `manual` condition, then every Edge left for a
person (a met condition whose `<n> (Edge)` you could not observe). This is
what the PR body's unticked boxes are drawn from.>
