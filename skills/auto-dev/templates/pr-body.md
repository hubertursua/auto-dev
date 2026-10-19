<!-- auto-dev template: pr-body.md (required sections strict, prose flexible). Copy everything below this comment, filling in every <...>. -->
## Summary
<what changed and why, 2–4 sentences — drawn from SPEC.md's Context>

## Acceptance conditions
**How this was checked.** Before any code was written, a test was written from
the requirements alone for each requirement below that a test could check, and
run on the old code (`<base>` at <old sha>), where the tests for new behavior
failed. The code was first written without those tests in view; then they were
added back, and any later fix had to make them pass without changing them.
Checked at commit <sha>: every result below was produced on this code.

**Start review with** the tests written before the code. They state what this
change must do: [`<path>`](<link>), [`<path>`](<link>)

<When no requirement could be checked by a test, replace both paragraphs above
with: "No requirement here could be checked by an automated test, so each one
is under _Checks for a person_. Checked at commit <sha>.">

- [x] **<condition, in the spec's own words>**
  Test written before the code: [`<path>` › <test name>](<link to its line>) —
  old code: <failed: <the one-line reason> | passed: it guards behavior that must not change> · now: passes
  <details><summary>Command and output</summary>

  On the old code, ran `<the base run's command>`:
  ```
  <the lines of its output that show this condition's tests failing or passing>
  ```
  Now, ran `<command>`, expecting <the expectation>.
  ```
  <the last lines of output>
  ```
  <for each further run in evidence/C<n>.txt: Also ran `<command>`, expecting
  <the expectation>, and the same kind of block>
  </details>
- [x] **<condition no test written before the code checks in full>**
  <when there is one: Test written before the code: [`<path>` › <test name>](<link>) —
  <it covers only part of this | it was wrong and was corrected, so it never ran on the old code |
  it runs at a lower level than this needs, because <why> | its run on the old code didn't
  show it failing for the reason it should> · now: passes>
  Checked by running <what, in a few words>: expected <the expectation>, saw
  <the result>. <when no test could drive it: why>
  <details>…the same block…</details>
- [ ] **<condition>** — <partly met | not met>: <what holds, what doesn't, and
  why it is being shipped anyway>
  <when there is one: Test written before the code: [`<path>` › <test name>](<link>) —
  old code: <…> · now: <passes | fails: <the failing assertion, one line>>>
  <details>…the same block, when something was run…</details>

### Checks for a person
<"None: every requirement was checked automatically." — or, per requirement or
edge case no automated check could observe:>
- [ ] **<condition, or the edge case, in the spec's own words>**
  1. <what to do>
  2. <what you should see>

  Already checked automatically: <what was run instead and what it showed |
  nothing could be, because <reason>>

### Changes to tests
<"No existing test was deleted, skipped or weakened, and every new test checks
something." — only when SPEC_EVAL.md's Test integrity section is "None.". A
clean new test is not listed: it is in the diff. Otherwise one line per finding
in that section, whatever it is about (an existing test changed, a new test
that asserts nothing, a change to the test setup):>
- [`<path>`](<link to the line>): <what changed, in plain words> — <because
  <the requirement that changes this behavior> | not justified: <why it is
  being shipped anyway>>

### Test strength
We put <n> small deliberate bugs into the changed code (for example, a
comparison flipped or a boundary moved by one) and ran the tests against each.
They caught <n>. <"Every one was caught." — or, per bug they missed:>
- `<path>:<line>`, `<original>` changed to `<bug>`: <harmless: no input can tell
  the two apart, because <reason> | not caught: no test checks <the behavior>,
  so <the requirement above is partly met | it affects no requirement above>>
<or: "Not run: <reason>." when the check was off or could not run>

## Quality gate
The repo's own checks, run on commit <short sha>:
- `<command>`: <passed | failed: <one line>>
  <details><summary>Output</summary>

  ```
  <the last lines of output>
  ```
  </details>

## Review
- Code review (<n> independent reviewers) — confidence <High | Medium | Low>:
  <its one-line reason>. <n> problems that had to be fixed: <n> fixed, <n> open
- Security review — confidence <High | Medium | Low>: <its one-line reason>.
  <n> problems that had to be fixed: <n> fixed, <n> open
<then one line per problem still open: what it is, where, and why it is being
shipped anyway. Minor suggestions stay out. A security problem that predates
this change appears here only if the user chose `Separate PR` (listed as a
follow-up) or `Fix it in this PR` (listed as fixed) at the PR gate.>

## Assumptions
<the unresolved assumptions from SPEC.md a reviewer should sanity-check>

Generated with [Claude Code](https://claude.com/claude-code)
