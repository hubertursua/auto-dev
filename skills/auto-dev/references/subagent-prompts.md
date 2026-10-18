# Subagent prompt templates

Brief templates for every worker (the subagent for each delegated job), plus the tool-permission
requirement for each. The orchestrator fills the `<…>` placeholders and always
hands the worker **two absolute paths** — `<worktree>` (where the code lives and
the work happens) and `<artifact-dir>` (where this task's artifacts are read and
written) — plus `<artifact-dir>/profile.md`, the repo's binding rules (from
Phase 1), and only the inputs that phase needs.

**Substitute both paths; never leave `<artifact-dir>` as a literal `.auto-dev/`.**
On a single-PR run the two coincide (`<artifact-dir>` = `<worktree>/.auto-dev`).
On a multi-PR run each sub-task builds in its own worktree while its artifacts
stay in the control worktree at `<control-worktree>/.auto-dev/tasks/<id>`, so the
two point at different trees — see `references/artifacts.md`.

> Every delegated job is briefed here (Phases 2–6). Phase 1 is deterministic
> orchestrator work (see `references/phase-1-setup.md`); in Phase 5 the verifier
> judges and the orchestrator turns its verdicts into coder correction briefs; the
> Phase 6 git/gh operations are the orchestrator's (`references/phase-6-ship.md`).

**Agent types: spawn each brief with the `_Agent type:_` it names**, and never pass
the Agent tool's `model` parameter. The type fixes the worker's model and effort
(`agents/<name>.md` in this plugin). See the model table in `SKILL.md`.

## Contents

- **Models** — why judgment stays on `opus` and what moves to `sonnet`.
- **Tools per worker** — the tool list each worker type gets.
- **Conventions for every brief** — rules every brief states, whatever the phase.
- **Phase 2 — Define**
  - **Define agent** — writes `SPEC.md`.
  - **Define reviewer**
  - **Scope decision (orchestrator)** — TRIVIAL, STANDARD or OVERSIZED.
- **Phase 3 — Plan**
  - **Planner** — writes `IMPLEMENTATION.md`.
  - **Plan reviewer**
  - **Acceptance tester** — writes and seals the held-out checks under
    `acceptance/`.
  - **Optional post-plan gate (orchestrator)**
- **Phase 4 — Build**
  - **Coder (TDD)** — includes what to do with a `BLOCKED` report.
- **Phase 5 — Verify**
  - **Verifier** — runs the checks, writes `SPEC_EVAL.md`.
  - **Acting on SPEC_EVAL.md (orchestrator)** — the coder correction brief, and
    repairing a defective acceptance check.
  - **Cleanup agent (simplify + quality gate)** — writes `lint/<CHECK>.md`.
  - **Re-verify after cleanup (verifier re-spawn)**
- **Phase 6 — Ship** (the procedure and the rubric are in `references/review.md`)
  - **Code reviewer: review mode** — one of three; writes `review/pass-<n>/R<k>.md`.
  - **Code reviewer: re-vote mode** — writes `review/pass-<n>/VOTES-R<k>.md`.
  - **Review judge: consolidate** — writes `CODE_REVIEW.md`.
  - **Security reviewer** — writes `SECURITY_REVIEW.md`.
  - **Review judge: security-verify** — fills `SECURITY_REVIEW.md`'s `Verified`
    cells.

## Models

Judgment stays on `opus`: a weak reviewer returns "no findings," which
is indistinguishable from a clean pass, and a weak plan spends revise rounds
downstream. Only work that a later check verifies moves down to `sonnet`: the
TRIVIAL build (acceptance and the quality gate catch it), the cleanup agent (the
quality gate and the re-verify catch it), and lookups (they only report). The
acceptance tester, the verifier, the review panel, the judge and the security
reviewer are all judgment, so all stay on `opus` (or
`fable` for the sensitive-path security reviewer). The routing rules (corrections always
to `auto-dev:coder`; `auto-dev:security-reviewer-sensitive` for sensitive paths) are in
`SKILL.md` and on each brief's `_Agent type:_` line below.

The types name model **families** (`opus`, `sonnet`, `fable`), never a version, so
each resolves to the current release without editing this skill.

## Tools per worker

Each type's `tools:` frontmatter, this list, and the `_Tools:_` line on each brief
below state the same thing; change them together:

- **Orchestrator (you):** TodoWrite, Bash (git/gh/CI, worktree, setup), Read,
  Edit (revise artifacts after critique, and apply re-votes to `CODE_REVIEW.md`),
  Write (`WORK_LOG.md`, `profile.md`, and `IMPLEMENTATION.md` on the TRIVIAL
  fast path or after a `BLOCKED` report there), the
  Agent/Task tool (spawn every worker), AskUserQuestion
  (gates), Skill (only if a fitting skill opens the PR in 6a), and — when a
  ticket is present — ToolSearch to locate the Atlassian MCP Jira tools, then those
  tools.
- **Define agent (Phase 2):** Write + Read, Grep, Glob (research is read-only; it
  writes `SPEC.md`).
- **Define reviewer (Phase 2):** Read, Grep, Glob only.
- **Planner (Phase 3):** Write + Read, Grep, Glob.
- **Plan reviewer (Phase 3):** Read, Grep, Glob only.
- **Acceptance tester (Phase 3):** Read, Write, Edit, Bash, Grep, Glob — writes
  only its own checks (removed from the worktree before it returns) and
  `acceptance/`; never source.
- **Coder (Phase 4):** Read, Write, Edit, Bash, Grep, Glob.
- **Verifier (Phase 5, re-spawned after every later change):** Read, Grep, Glob,
  Bash, Write — read-only w.r.t. source and tests (its mutants are applied and
  restored by `scripts/mutate.py`, never by hand); it installs the sealed
  acceptance checks and writes `SPEC_EVAL.md` and `evidence/`.
- **Cleanup agent (Phase 5, re-spawned after later corrections):** Read, Edit, Write, Bash, Grep,
  Glob, plus the **Skill** tool to run `/simplify`.
- **Code reviewer (Phase 6a):** Read, Grep, Glob, Bash (`git diff`, `git blame`),
  Write, plus the **Skill** tool to run `/code-review` — read-only **w.r.t.
  source**; it writes only its own report under `review/pass-<n>/`.
- **Review judge (Phase 6a):** Read, Grep, Glob, Bash (`git diff`, `git blame`),
  Write — read-only w.r.t. source; it writes `CODE_REVIEW.md`, or edits
  `SECURITY_REVIEW.md` in security-verify mode.
- **Security reviewer (Phase 6a), both types:** Read, Grep, Glob, Bash, Write, plus
  the **Skill** tool to run `/security-review` — read-only w.r.t. source; it writes
  `SECURITY_REVIEW.md`.
- **Lookup (any phase):** Read, Grep, Glob, Bash — answers a question, writes
  nothing.

## Conventions for every brief

- **Non-interactive:** the worker never asks the user; it resolves ambiguity with
  a recorded assumption.
- State the worktree path and "work entirely inside it; do not touch other trees."
  Where `<artifact-dir>` lies outside that tree (multi-PR runs), say so
  explicitly: it is the one path the worker may read and write outside `<worktree>`.
- Name the exact artifact file(s) to write, and **paste that artifact's template
  from `references/artifacts.md` into the brief**, with its strictness (strict, or
  headings-strict for `IMPLEMENTATION.md`). A worker has no path to the
  reference files and cannot follow a pointer to one.
- Require a short structured return: what it did, assumptions, risks, and (for
  reviewers) findings grouped **blocker / should-fix / nit**.
- Pass the binding rules and the security directives Phase 1 resolved into
  `profile.md`; they override "finish."
- Reviewers are **read-only** and must **not** rewrite files — they return
  findings; the orchestrator applies fixes (it holds the context and this consumes
  the shared iteration budget).
- **Spill large output to `$TMPDIR`; return a digest, never a corpus.** Say it in
  every brief: redirect long command output (suite runs, dialyzer, full diffs) to a
  file under `$TMPDIR` and quote only the failing tail. A worker that pastes a
  10k-line log into its return has burned the context the artifacts exist to save.
- **Keep any single command under 5 minutes.** A worker's prompt cache is
  short-lived (minutes, where the orchestrator's is far longer), so a worker idling
  on a long blocking command has its whole context re-billed at write price. Where a check is
  genuinely long (a full suite, a cold build), tell the worker to scope it
  (`--only`, a directory, the affected files) and hand the full run back to the
  orchestrator, which can afford to wait or background it. **The cleanup agent's
  Step 2 is the one exception** — the quality gate is the Definition of Done and
  must run in full; its brief says how.

---

## Phase 2 — Define

### Define agent
_Agent type: `auto-dev:define`._
_Tools: Write + Read, Grep, Glob (research is read-only; it must not modify source)._

One pass that researches the ticket against the codebase, states the acceptance
conditions **as a testable contract**, and returns the **scope call** the
orchestrator branches on. Research and spec are the same worker's job on
purpose: the worker holding the codebase research is the one best positioned to
know what is actually observable.

```
You are the DEFINE phase of an autonomous dev pipeline. Work entirely inside the
worktree at <worktree>. Do NOT modify any source code. Do NOT ask the user
anything — resolve every ambiguity yourself and record it as an assumption.

Ticket / task: <the ticket summary + description, or the user's task text, verbatim>
Ticket source: <JIRA-KEY and link, or "free-form task (no ticket)">
Project profile: read <artifact-dir>/profile.md for the stack, conventions, and quality gate.
Binding rules: <repo CLAUDE.md/CONTRIBUTING summary + the security directives named
in profile.md>. These constrain what "done" and "acceptable" mean.

Explore the relevant code enough to understand what the ticket really asks: find
the feature area, similar existing features, the modules/flows involved, and any
constraints (auth, data, migrations, external services). Do NOT design a solution.

Write exactly one file: <artifact-dir>/SPEC.md — the TESTABLE CONTRACT. Sections:

1. "Context" — the ticket restated clearly, links, and your research findings:
   where this lives in the code, relevant modules/paths, similar precedents,
   constraints. Stakeholder-readable; no technical design.

2. "Conditions" — WHAT MUST BE TRUE for this to be done, as observable, testable
   conditions in plain language. Each defines "this works" in terms someone could
   verify by using the system. NO technical design, no file names, no function
   signatures. If a condition is hard to observe, say so and state the closest
   observable proxy.
     Good:  "A signed-in user who deletes one of their own todos no longer sees it
             in their list, and reloading the page does not bring it back."
     Vague: "Deleting todos works correctly."  (nothing to observe)
     Leaky: "The delete handler calls TodoRepo.remove()."  (design, not behavior)
   Under each condition add three lines, because a later agent turns them into
   tests without asking you what you meant:
     - Example: one concrete Given / When / Then with real-looking values.
         "Given user A owns todo 7, when A deletes todo 7, then A's list no
          longer contains todo 7."
     - Edge: the negative, boundary or error case that most tempts a wrong
       implementation, and its observable result ("B deletes A's todo 7 → not
       found, and todo 7 is still in A's list"); or "none — <why>".
     - Verify by: unit, integration, end-to-end, or manual with the reason no
       agent can observe it (visual layout, a third-party service with no test
       double). Prefer the most external level the repo's tests can reach.
   Write the condition so ONE reading fits: if two implementations could both
   satisfy the words yet behave differently on some input, pick one and say so in
   the Example or the Assumptions.

3. "Assumptions" — every ambiguity you resolved.

4. "Security/Compliance criteria" — when the task touches a sensitive path (auth,
   data handling, payments, access control, anything the repo's guidelines flag),
   pull the specific controls from the security-directive sources named in
   <artifact-dir>/profile.md (e.g. parameterized queries, authz checks, no
   secrets/PII). If it records "none found", fall back to the repo's coding rules
   and say so in this section. Number them S1, S2, …, each with an Example (the
   abusive or unauthorized action, and how it is refused) and a Verify by line.

Use the SPEC.md template below exactly (strict):
<paste the SPEC.md template from references/artifacts.md>

Return a structured summary:
- assumptions: the key ones you made
- risks: the main correctness/security/scope risks
- SCOPE CALL: exactly one of TRIVIAL / STANDARD / OVERSIZED, with one line of why.
  * TRIVIAL   = one subsystem, one behavior, no new abstraction or interface, no
                migration or config change, and an existing test file covers it.
  * STANDARD  = fits one PR but is none of the above.
  * OVERSIZED = multiple independent deliverables, several subsystems, or a large
                file count. Also list the subsystems touched and a rough file count.
  For example, in a todo app:
    "Trim whitespace from titles before saving"        → TRIVIAL (one behavior; an
                                                          existing test file covers it)
    "Add a due date to todos and sort the list by it"  → STANDARD (needs a migration)
    "Add teams: shared lists, email invites, roles"    → OVERSIZED (three deliverables)
```

After it returns, read `SPEC.md`. **You hold it and withhold it from the coder**
(Phase 4); it is your independent check in Phase 5.

No brief returns a slug: Phase 1 derived it and cut the branch and worktree before
this phase ran, so a slug proposed here could only conflict with paths already on
disk.

### Define reviewer
_Agent type: `auto-dev:define-reviewer`._
_Tools: Read, Grep, Glob only (must not rewrite the file)._
**Skip this agent entirely when the scope call is TRIVIAL.**

```
You are the DEFINE-REVIEW phase. Read <artifact-dir>/SPEC.md and the binding rules
(<summary>) in the worktree at <worktree>.

Critique SPEC.md and return findings grouped blocker / should-fix / nit:
- Are all conditions observable and TESTABLE (not vague)?
- Does every condition have an Example with concrete values, an Edge line (a real
  negative or boundary case, or a credible "none"), and a Verify by line? Is a
  `manual` Verify by justified, or could a test observe it after all?
- Ambiguity probe: for each condition, try to describe two implementations that
  both satisfy its words but behave differently on some input. If you can, name
  both readings — a blocker unless the Example or Assumptions already settle it.
- Free of technical leakage (no design masquerading as a requirement)?
- Does the Context section actually support the conditions — is anything asserted
  in a condition that the research doesn't back up?
- Are the assumptions reasonable, and the security/compliance criteria complete
  for what the task touches?
- Anything the ticket asks for that no condition covers?
Do NOT rewrite the file. Return findings only.
```

Apply fixes yourself by editing `SPEC.md`. Re-review only if the critique had
blockers, and repeat until a review returns none. Each re-review consumes a round
of the shared iteration budget; at zero, stop and report the open blockers
(`references/correction-loop.md`).

### Scope decision (orchestrator)

Branch on the **SCOPE CALL**:

- **TRIVIAL** — skip the Define review, the planner and the plan reviewer. Write
  a short `IMPLEMENTATION.md` yourself: the files to touch and the test that
  proves it. Then spawn the acceptance tester and end S1 at its boundary as
  usual, Phase 4 next (but see the post-plan gate below — it still fires if
  enabled).
  Record `Mode: single-PR` and `Scope call: TRIVIAL` in `WORK_LOG.md`. Phase 3
  still runs the acceptance tester, so its ledger row goes `in-progress` and then
  `done` like any phase — never `skipped`, or a run cut off before the tester
  would resume past it — with the Notes "TRIVIAL: plan by orchestrator; planner
  and plan review skipped".
- **STANDARD** — proceed to Phase 3 as a single-PR run. Record `Mode: single-PR`
  and `Scope call: STANDARD`.
- **OVERSIZED** — **skip the Define reviewer here too.** The parent `SPEC.md` exists
  to inform the decomposition, not to be built from: every sub-task re-runs Define
  and gets its own reviewed `SPEC.md`. Reviewing a spec that is about to be
  superseded spends budget on a discarded artifact.
  Do **not** cram the work onto one branch. Draft an ordered
  decomposition into sub-tasks — each independently shippable, with dependencies
  noted — and:
  1. Write the sub-task table to the control worktree's `.auto-dev/WORK_LOG.md`
     (`Mode: multi-PR`; see `references/artifacts.md`).
  2. **Alert the user** with the proposed breakdown and ask to proceed
     (`AskUserQuestion`). If they adjust it, update the ledger. If they choose
     `Do it as one PR anyway`, the run becomes STANDARD — and the Define reviewer
     skipped just above must now run, or the whole PR is built from an unreviewed
     spec (`references/gates-and-jira.md`).
  3. On approval, run Phases 2–6 **per sub-task** in dependency order, updating the
     ledger after each. Each sub-task re-runs the Define brief scoped to itself, so
     it gets its own `SPEC.md` **and its own scope call** (a sub-task may well be
     TRIVIAL). Set `<artifact-dir>` to `<control-worktree>/.auto-dev/tasks/<id>`,
     and create it — `lint/` included — before that sub-task's first agent.

     **Create each sub-task's worktree when that sub-task starts, never all at once
     up front**, and cut it from a freshly fetched base:
     ```bash
     git fetch origin
     git worktree add ../<repo-name>-<slug>-<id> -b <prefix>/<slug>-<id> origin/<base>
     ```
     Cutting them all at the beginning is the bug this avoids: a sub-task that
     depends on an earlier one would branch from a base predating it, and its PR
     would conflict with work already merged. Fetching first is what gives the
     `depends on` column its meaning — by the time a dependent sub-task starts, its
     dependency is already on `origin/<base>`.

     Then **prepare that worktree the way Phase 1 step 5 prepares the control
     worktree** (`references/phase-1-setup.md`): seed the `worktree_files` from the
     main checkout and confirm git ignores each one, then run the profile's `setup`
     commands — stopping and reporting wherever that step says to. A bare
     `worktree add` has neither, and the sub-task's tests would then fail in ways
     that read exactly like broken code. Only the seeding, ignore check and `setup`
     carry over: the slug is the run's, and `profile.md` is the run's shared record
     — leave it alone and note what was seeded in the Notes of the sub-task's
     Phase 2 row instead.

     Write the sub-task's phase table only once that prep has succeeded, so a run
     cut off mid-prep still reads as never started. On resume, if
     `git worktree list` already shows this sub-task's worktree, skip the
     `worktree add` (its branch exists too) and redo the prep in place. If prep
     stops, write the phase table with Phase 2 `blocked` and the reason in its
     Notes; once the user resolves it, redo the prep before Define runs.

     **A sub-task's own scope call may not be OVERSIZED.** If one comes back that
     way, the parent decomposition was wrong — and that decomposition is the thing
     the user approved. Stop, report which sub-task exceeds one PR and why, and
     offer to re-cut the parent breakdown. Never decompose inside a decomposition:
     the ledger has no shape for nested sub-tasks, and the recursion has no base
     case.

Borderline between STANDARD and OVERSIZED? Prefer surfacing the decomposition and
letting the user choose over silently committing to one giant PR. Borderline
between TRIVIAL and STANDARD? Prefer STANDARD — the planning head is cheap
relative to shipping the wrong thing.

---

## Phase 3 — Plan

**On TRIVIAL the planner and plan reviewer are skipped** — the orchestrator
writes a short `IMPLEMENTATION.md` directly instead. **The acceptance tester runs
at every scope**: it is the head of the verification tail, not of the planning.

### Planner
_Agent type: `auto-dev:planner`._
_Tools: Write + Read, Grep, Glob._

```
You are the IMPLEMENTATION-PLAN phase. Work inside the worktree at <worktree>. Do
NOT modify source. Do NOT ask the user — record assumptions.

Read <artifact-dir>/SPEC.md — your plan must satisfy every condition in it. Read
<artifact-dir>/profile.md (the `gate` commands are the Definition of Done) and the
binding rules (<summary>). Explore the code (find similar features, map the
architecture, identify the exact files you'll touch) before designing.

Write exactly one file: <artifact-dir>/IMPLEMENTATION.md — the technical HOW, sufficient
to build from ON ITS OWN. Include: files to create/modify (paths); the design
(modules/functions/data structures); data flow; the ordered build sequence (this
is the coder's worklist — make each step a small, verifiable unit with its test);
the test plan (which test proves which behavior, and where it lives — at the
level each condition's Verify by line names); any
migration/config. It must be self-contained — a competent engineer who has NOT
seen the spec should build the right thing from this plan alone. Ensure every
SPEC.md condition maps to a build step AND a test.

Return: assumptions, key risks.
```

### Plan reviewer
_Agent type: `auto-dev:plan-reviewer`._
_Tools: Read, Grep, Glob only._

```
You are the PLAN-REVIEW phase. Read <artifact-dir>/IMPLEMENTATION.md and <artifact-dir>/SPEC.md
and the binding rules (<summary>) in the worktree at <worktree>.

Critique IMPLEMENTATION.md; findings grouped blocker / should-fix / nit:
- Complete and self-contained (buildable without the spec)?
- Does every SPEC.md condition map to a build step AND a test? List gaps both ways
  (a condition with no step/test; a step that traces to no condition).
- Is the build sequence ordered so each step is independently verifiable?
- Follows repo conventions and security constraints? Correctness/security/scope
  risks? Anything over-engineered for the task?
Do NOT rewrite the file. Return findings only.
```

Apply fixes yourself. Re-review only if the critique had blockers, and repeat until
a review returns none. Each re-review consumes a round of the shared budget; at
zero, stop and report the open blockers (`references/correction-loop.md`).
A spec condition with no plan step is cheapest to catch here, before code exists.

### Acceptance tester
_Agent type: `auto-dev:acceptance-tester`._
_Tools: Read, Write, Edit, Bash, Grep, Glob._ Runs once the plan is final (after
the plan review settles, or after you write the TRIVIAL plan), before the
post-plan gate and before any code exists.

The coder's own tests are written by the agent whose work they judge, so they
cannot be the main evidence that the work is right. This agent writes a second,
**held-out** set from `SPEC.md` alone, proves each new-behavior check fails on
the untouched tree (a check that passes before the change exists proves nothing
about it), and then **seals** them: removes them from the worktree and keeps the
only copy under `<artifact-dir>/acceptance/`. The coder never sees them during
the build; the verifier installs them afterwards (Phase 5).

```
You are the ACCEPTANCE-TEST phase. Work inside the worktree at <worktree>;
<artifact-dir> is the one other path you may write to. Do NOT modify source code.
Do NOT ask the user — record assumptions.

Inputs:
- <artifact-dir>/SPEC.md — the conditions. It is your ONLY source for what the
  right outcome is.
- <artifact-dir>/IMPLEMENTATION.md — read it ONLY for the entry points the change
  will expose (routes, public modules/functions, CLI commands, pages) and where
  tests live. Never take an expected value from it.
- <artifact-dir>/profile.md — the test command and test_notes; and the repo's
  existing tests, for conventions, helpers and fixtures.
Binding rules: <summary>. Use synthetic test data only.

Scope: <ALL CONDITIONS | ONLY conditions <numbers>, because <a coverage gap /
the other reading of an ambiguous condition / a plan revision changed their
entry points>>.
- ALL CONDITIONS: start clean. If <artifact-dir>/acceptance/ exists from an
  earlier, cut-off run, delete it, and remove from the worktree any untracked
  test file with `acceptance` in its name that `git status --porcelain
  --untracked-files=all` shows. The worktree must hold no change before you begin.
- ONLY named conditions: keep <artifact-dir>/acceptance/ — every other
  condition's sealed checks and MANIFEST rows stay exactly as they are. Replace
  only the named conditions' sealed files and rows.

For every SPEC.md condition, Security/Compliance criteria included:
1. Write at least one black-box check that fails if the condition does not hold.
   Drive it through the most external entry point the repo's tests can reach (a
   request/controller/LiveView test, a CLI invocation, the public API), not
   internal helpers. Take expected values from the spec's words, never from how
   the code computes them. Each condition's Example is your first check, with its
   values; its Edge line is your second. Its Verify by line names the level to
   test at (a `manual` one goes straight to Not automatable, step 4).
   If a condition reads two ways — two implementations could both satisfy its
   words yet differ on some input — pick the reading its Example supports, test
   that one, and report AMBIGUOUS with both readings.
   Put the checks in NEW files in the repo's test tree, following its naming
   conventions, with `acceptance` in each file name (e.g.
   `test/<app>/acceptance/<slug>_acceptance_test.exs`). Never edit an existing
   test file. Name each test after the behavior it checks.
2. Classify each check: `fail-to-pass` (new or changed behavior — must FAIL on
   this untouched tree) or `pass-to-pass` (behavior the change must preserve —
   must PASS on it).
3. Run your checks with the profile's test command scoped to your files, output
   to $TMPDIR. A fail-to-pass check must fail FOR THE RIGHT REASON: an assertion,
   or the entry point being absent or returning the wrong result (a compile error
   that names the missing entry point counts). A syntax error, a broken fixture or
   a setup crash in the check itself is a broken check: fix it. A pass-to-pass
   check must pass. If you cannot make a check behave, drop it and list the
   condition under Not automatable with the reason.
   Then make the check files pass the profile's non-test `gate` commands
   (format, lint, compile warnings) scoped to your files — run the formatter on
   them if the gate has one. Nobody may edit a check after it is sealed, so a
   check that fails the quality gate can never be fixed later.
4. A condition no check can drive (visual layout, an external service with no
   test double, wording only a human can judge) goes under Not automatable, with
   the closest observable proxy a later agent could run, if there is one (a CLI
   call, a request, a log line).

Then SEAL the checks:
- create <artifact-dir>/acceptance/files/ even if you sealed no check (every
  condition not automatable) — the audit treats a missing directory as an error;
- copy each check file to <artifact-dir>/acceptance/files/<its repo-relative
  path>.sealed (the `.sealed` suffix keeps every test runner from collecting it);
- delete it from the worktree, and any directory you created for it;
- confirm `git status --porcelain --untracked-files=all` lists none of your files.
Write <artifact-dir>/acceptance/MANIFEST.md to this template (strict):
<paste the MANIFEST.md template from references/artifacts.md>

Spill long output to $TMPDIR; quote only failing tails. Keep each command under
5 minutes.

Return: the checks per condition (path :: test name, kind), each check's base-run
result, the not-automatable conditions, AMBIGUOUS (each condition, both readings,
the one you tested — or "none"), and your assumptions.
```

Check the return before moving on: every condition is either covered by a check
or listed under Not automatable, and `git status` in the worktree is unchanged.
For each **AMBIGUOUS** condition, decide against the ticket which reading is
meant — on TRIVIAL runs this is the only ambiguity probe the spec gets. If the
tester's reading is right, record it in `SPEC.md`'s Assumptions (no round). If
not, record the other reading there and re-spawn the tester with Scope "ONLY
condition <n>" (a round, consumer #2).
Fix a gap by re-spawning this agent with Scope "ONLY conditions <the gap>" (a
first pass is not a round; a re-spawn spends one, consumer #2 in
`references/correction-loop.md`). Only the first spawn of a run uses ALL
CONDITIONS; every re-spawn names its conditions, or it would wipe the rest.

**Repair mode.** A check is repaired, never edited by the coder, when you agree
against `SPEC.md` that it is wrong. Three things lead here: the verifier reports
it defective (_Acting on SPEC_EVAL.md_, below); a `BLOCKED` plan revision or a
post-plan-gate revision changes an entry point it calls; or, in Phase 6, a
must-fix review finding or a human reviewer's blocker is about the check itself.
If you disagree, the check stands and its failure is the coder's to fix. To
repair, re-spawn this agent with the same brief, Scope "ONLY conditions <the
checks' conditions>", plus: "The tree now holds the built change and
these checks are installed at their paths. Fix each one IN PLACE at its
installed path, then copy it over its sealed copy so the two stay
byte-identical; do not remove it from the worktree. Skip the base run and
record its Base run as `not re-run (repair)`. Update its MANIFEST row; leave
every other check alone." Checks are installed only from Phase 5 on. Before
that, nothing is installed, so the repair re-runs the brief with Scope "ONLY
conditions <those checks' conditions>" and seals as on a first run (removing
the checks from the worktree again): after a post-plan-gate revision, with
the base run; after a Phase 4 `BLOCKED` revision, the tree already holds
partial code, so record the Base run as `not re-run (repair)`. Then re-spawn the verifier in re-check mode. A repaired
check no longer proves the change was needed, so the verifier counts it as
Adequate evidence at most, never Strong. A repair spends a round from the entry
point that led to it (consumer #3 in Phase 4–5, #4 or #5 in Phase 6); a
post-plan-gate revision's spends none, like the revision itself.

### Optional post-plan gate (orchestrator)
If enabled for this run, pause here (`AskUserQuestion`) for the user to approve
`SPEC.md` + `IMPLEMENTATION.md` before any code is written, with
`acceptance/MANIFEST.md`'s coverage (checks per condition, and what is not
automatable) in the summary. Off by default; see
`references/gates-and-jira.md`.

**This gate is independent of the scope call.** On the TRIVIAL path the agents
above are skipped but this gate is not — the user asked to see a plan before code
exists, and the short plan you wrote yourself is still that plan.

---

## Phase 4 — Build

### Coder (TDD)
_Agent type: `auto-dev:coder` (STANDARD), `auto-dev:coder-trivial` (TRIVIAL first
build only)._
_Tools: Read, Write, Edit, Bash, Grep, Glob._ Spawn with the **plan only — never
SPEC.md** (see *Why two documents* in `references/artifacts.md`).

```
You are the IMPLEMENTATION phase. Work inside the worktree at <worktree>. Do NOT
ask the user — record assumptions.

Implement the change in <artifact-dir>/IMPLEMENTATION.md, working through its build
sequence in order. Read <artifact-dir>/profile.md for the toolchain and test command,
and the binding rules (<summary>) — follow the repo's security and coding
guidelines, never log/expose sensitive data, never hardcode secrets, use
synthetic/test data only.

Work test-first: for each step, add or extend the test the plan calls for, run
it and see it FAIL, then make it pass. Follow existing codebase conventions and
abstractions closely. Run the relevant tests as you go and get them green
(test command: <from profile.md>; scope hints: <profile.md test_notes>). Do NOT
commit and do NOT open a PR — just leave the working tree with the change
implemented.

Tests are evidence, so keep them honest. A later, independent check audits every
test change and runs checks you have not seen:
- Never delete, skip, xfail or weaken an existing test, or change what it
  asserts, unless the plan's behavior change requires it. List every such edit
  under TEST CHANGES with the reason.
- Never make a test pass by special-casing its inputs, detecting the test
  environment, hard-coding the expected value, or mocking out the very behavior
  the test names. Every test you add must fail if that behavior breaks.
- Never modify a file this brief names as an acceptance check.
If the plan conflicts with the code as you find it, or a step can only be made
green by breaking one of these rules, STOP that step — do not force it. Report it
under BLOCKED and carry on with the steps it does not affect.

Return:
- files created/modified, and tests added
- which build-sequence steps are done
- TEST CHANGES: every existing test you edited, skipped or removed, and why
  (write "none" if none)
- BLOCKED: each step you stopped, what conflicts, and what you would need to
  finish it (write "none" if none)
- DEVIATIONS: any step you did differently than the plan describes, and why. Be
  specific and honest — a better route is a fine reason, and this report is read
  as information, not as a failure.
```

**Read the DEVIATIONS report as information, not a defect list.** The plan is a
route; the Phase 5 verifier decides whether the destination was reached. Do not
spend budget reconciling code with a plan it improved on. The verifier never sees
this report: it judges the code, not the coder's account of it.

**A `BLOCKED` report** means a step stopped rather than going green dishonestly.
Settle it before Phase 5, against `SPEC.md`, which you hold:

- **The plan is wrong or incomplete** (it names a function that cannot work that
  way, misses a caller, contradicts the code): on STANDARD, re-spawn the planner
  with the blocker and have it revise only the affected steps; on TRIVIAL, edit
  `IMPLEMENTATION.md` yourself. If the revision changes an entry point an
  acceptance check calls, repair those checks too (_Acceptance tester_, repair
  mode). Then re-dispatch `auto-dev:coder` for the stopped steps. This spends one
  round (consumer #3, `references/correction-loop.md`).
- **The spec itself cannot be met as written** (two conditions contradict each
  other, or the codebase makes one impossible): that is the _self-contradictory or
  impossible_ stop-and-report in `SKILL.md`. Report which conditions and why.
- **An existing test asserts the old behavior the spec changes**: not a blocker.
  Tell the coder, in the re-dispatch, that updating that test is in scope and to
  list it under TEST CHANGES.

---

## Phase 5 — Verify

### Verifier
_Agent type: `auto-dev:verifier`._
_Tools: Read, Grep, Glob, Bash, Write._ It never edits source; the one time source
changes under it is inside `scripts/mutate.py`, which restores every file it
mutates. Spawn it **without** `IMPLEMENTATION.md`,
the coder's return, or your correction history: it gets the contract and the
code, nothing that explains the code.

The verifier replaces reading the diff and judging it. Two things make its
verdicts worth more than a read: it **runs** the evidence instead of citing it,
and it holds none of the context that wants the build to have worked — the plan,
the coder's account, the rounds already spent. Anthropic's harness work found
agents "reliably skew positive" when grading work whose story they already hold,
and that an evaluator that clicks through the running system catches what one
that reads the code does not.

**Its first pass** runs once the build returns with nothing `BLOCKED`. **It is
re-spawned** — in re-check mode, never spending a round — after every
acceptance correction, after the cleanup agent (_Re-verify after cleanup_,
below), and after every Phase 6 correction (`references/correction-loop.md`,
_The Phase 6a refresh_).

The coder is told not to commit, so **the change set is the working tree**, and
the brief's diff step has two halves that both fail silently. Without
intent-to-add, every file the coder _created_ is invisible to `git diff` —
usually most of the change. Mark the untracked files only, never `git add -N .`:
that also stages every deletion — real staged changes, not intent-to-add markers,
made before the PR gate approved any commit. And `git diff origin/<base>...HEAD`
reports an **empty** diff, because nothing is committed yet. Diff against
`origin/<base>` — the ref Phase 1 cut the worktree from — not the local branch,
which may be stale. (Phase 6a's reviews run before the commit too, so they also
read the working tree; `references/review.md`, _What each review pass covers_.)

```
You are the VERIFY phase. Work inside the worktree at <worktree>; <artifact-dir>
is the one other path you may write to. Do NOT ask the user. Do NOT modify source
or tests: your only writes are installing the sealed acceptance checks,
<artifact-dir>/evidence/, and <artifact-dir>/SPEC_EVAL.md.

You did not build this change and you have not seen its plan. Your job is to find
the condition that is NOT met. Missing evidence means not met.

Read: <artifact-dir>/SPEC.md (the contract), <artifact-dir>/acceptance/MANIFEST.md
and the sealed checks under <artifact-dir>/acceptance/files/, <artifact-dir>/profile.md
(test command, test_notes), and the binding rules (<summary>). Do NOT read
IMPLEMENTATION.md or any other file under <artifact-dir>.

Mode: <FIRST PASS | RE-CHECK after <what changed: an acceptance correction / an
acceptance-check repair / the cleanup pass / a Phase 6 correction>>. On a
re-check, do NOT read the existing SPEC_EVAL.md: judge from scratch and overwrite
it.

0. If <artifact-dir>/evidence/mutants.json.backup exists, an earlier pass was
   killed mid-mutant and the source may still hold its bug. Before anything
   else run `python3 <skill-dir>/scripts/mutate.py <worktree> --restore --mutants
   <artifact-dir>/evidence/mutants.json`. Exit 4: STOP and return MUTATION LEFT
   CHANGES.
1. Integrity, then install. Paths below are absolute.
   Each sealed check <artifact-dir>/acceptance/files/<path>.sealed installs at
   <worktree>/<path>.
   - FIRST PASS: check every path before copying any. A file already there and
     byte-identical to its sealed copy is already installed (a resumed pass):
     leave it. A file there that differs is not yours: copy NOTHING, and return
     INSTALL CONFLICT with every such path. Otherwise install the rest, then run
     the audit (below).
   - RE-CHECK: run the audit first, then re-copy every sealed check over its
     installed path (this undoes any edit; the audit has already recorded it).
   Audit: python3 <skill-dir>/scripts/check-tests.py <worktree> --base origin/<base> --acceptance <artifact-dir>/acceptance
   Exit 0 clean, 1 findings, 3 an acceptance check missing or modified, 2 an
   error (report it; do not guess). Save its output to <artifact-dir>/evidence/integrity.txt.
2. The change set: run
     git ls-files -z --others --exclude-standard | xargs -0 git add -N --
     git diff origin/<base>
   and read it whole (spill it to $TMPDIR if long). Never `git add -N .`.
3. Run the acceptance checks with the profile's test command scoped to their
   files; save the output to <artifact-dir>/evidence/acceptance.txt. Confirm the
   runner executed every test MANIFEST.md lists — a test excluded, filtered or
   skipped did not pass: its condition is unmet, and the cause is an Unjustified
   integrity finding.
4. For each SPEC.md condition (Security/Compliance criteria included), decide its
   evidence tier. Before running anything for it, write down the outcome you
   expect; then run and compare. Save what you ran and saw to
   <artifact-dir>/evidence/C<n>.txt.
   - Strong: the condition's acceptance checks all passed in step 3, and each
     fail-to-pass one failed on the base per MANIFEST.md.
   - Adequate: no usable Strong evidence (the condition is not automatable, a
     check was repaired, or the checks cover only part of it), but you ran
     something yourself and it matched your stated expectation — a test in the
     change (read it first: it must assert the condition's observable outcome,
     not a mock of the code under test), or a direct observation such as a CLI
     call, a request against a test server, or a script through the project's
     runner.
   - Weak: a code citation you did not execute.
   Verdict:
   - unmet — any acceptance check for it fails, or the behavior is absent or
     contradicted.
   - met — every acceptance check for it passes, the evidence is Strong or
     Adequate, no unjustified integrity finding touches it, and no Test gap
     (step 7) sits on its lines. Settle verdicts only after step 7.
   - partial — some of it holds, or the only evidence is Weak.
   - manual — ONLY when MANIFEST.md lists it as not automatable AND you found no
     way to observe it here. Say exactly what a human must check, and how.
5. Judge each integrity finding: Justified (name the SPEC.md condition that
   changes or removes that behavior) or Unjustified. ACCEPTANCE_* findings are
   never justified, and so is TEST_CONFIG_CHANGED when it excludes, skips or
   focuses tests. Also look through the diff for gaming the audit cannot see:
   production code branching on values that appear only in tests, checks for a
   test environment, logic stubbed out or returning a constant. Each is an
   Unjustified finding.
6. If an acceptance check itself is defective — it asserts something SPEC.md
   does not say, or contradicts it — say so and why. Do not edit it.
7. Mutation check (cap: <mutation cap from profile.md; TRIVIAL: at most 8>).
   Passing tests show the code works; mutants show the tests would notice if it
   stopped working. Start by deleting <artifact-dir>/evidence/mutants.json and
   its .results.json from any earlier pass. At cap 0, write "off" and stop here.
   Every pass, first pass and re-check alike, picks a FRESH set over the whole
   change, plus one mutant re-creating each previous survivor listed below (find
   its line again — the code may have moved).
   Previous survivors: <the Mutation table rows from the last SPEC_EVAL.md, or "none">
   Keep a previous Equivalent judgment unless that code changed.
   Choose mutants on CHANGED SOURCE lines the conditions depend on — never tests,
   config, logging or docs — at most one per line, each the small edit most
   likely to break the behavior while still compiling: flip a comparison or
   boolean, drop a guard or a negation, move a boundary by one, return a
   plausible wrong value, remove a call that has an effect. Tag each with the
   condition it threatens. Line numbers are grep -n's. Before every run, first
   pass and re-run alike, delete <artifact-dir>/evidence/mutate.exit and
   mutate.log, so a stale exit file is never read as this run's. Write them to
   <artifact-dir>/evidence/mutants.json (a JSON list of {"id", "file", "line",
   "find", "replace", "condition"}), save `git status --porcelain` and
   `git diff origin/<base> | sha256sum`, then run:
     python3 <skill-dir>/scripts/mutate.py <worktree> --mutants <artifact-dir>/evidence/mutants.json --max <cap> --timeout <about 3× one COLD scoped run, in seconds: touch one changed source file, then time the scoped command, since every mutant forces a rebuild> --cmd "<the profile's test command, scoped to the change's tests and the acceptance checks>" > <artifact-dir>/evidence/mutate.log 2>&1; echo $? > <artifact-dir>/evidence/mutate.exit
   The whole run can take longer than 5 minutes (one test run per mutant), so
   start it in the background and check <artifact-dir>/evidence/mutate.exit every
   few minutes until it exists; never block on it, never kill it, and never
   return while it is running — a run still going holds a mutant in the tree.
   If most mutants time out, the timeout was too short, not the tests strong:
   raise it and re-run before judging. The
   scoped command must pass as-is and should take seconds; give a mutant its
   own narrower "cmd" when one file's tests are enough. Exit codes: 0 none
   survived; 1 some survived; 2 your mutants file is malformed — fix it and
   re-run; 3 the scoped tests fail unmutated — a test is already failing, which
   is unmet, report it; 5 leftover backups — run `python3
   <skill-dir>/scripts/mutate.py <worktree> --restore --mutants
   <artifact-dir>/evidence/mutants.json`, then re-run; 6 interrupted, every file
   restored — re-run it once, in the background; if it is interrupted again,
   write the mutation check as "not run" with the reason; 7 an I/O error such as a full disk — report
   it, do not retry; 8 every mutant was invalid (lines moved or `find` text
   wrong) — re-read the lines and re-write them, and if a second run is still
   all invalid, write the mutation check as "not run" with the reason; 4, or
   any other code (a crash), STOP and return MUTATION LEFT CHANGES. Afterwards both saved values must be unchanged; if they are not (the
   test command itself may have written files), return MUTATION LEFT CHANGES
   with the paths. Never commit, stage or keep a mutant.
   Judge each survivor: Equivalent (no input can tell the mutant from the code —
   say why) or a Test gap. A timeout counts as caught: the mutant made the code
   hang, and the run noticed. A Test gap on a line a condition depends on makes
   that condition `partial` (evidence: the mutant survived); any other Test gap
   is advisory.

Write <artifact-dir>/SPEC_EVAL.md to this template (strict):
<paste the SPEC_EVAL.md template from references/artifacts.md>

Never downgrade a failure you saw without writing why in its row. Spill long
output to $TMPDIR; keep each command under 5 minutes.

Return: one line per condition (number, verdict, tier); the unjustified integrity
findings; the mutation summary and each Test gap (mutant, line, condition, and the
behavior no test pins down); any defective acceptance check; INSTALL CONFLICT or
MUTATION LEFT CHANGES if either happened.
```

The verifier's run spends no round, on its first pass or any re-spawn: like the
quality gate and the reviews, it is a check, and what bounds the loop is the
correction that sent it back (`references/correction-loop.md`).

### Acting on SPEC_EVAL.md (orchestrator)

Read `SPEC_EVAL.md` — not the diff. Each of these is a Phase 5 correction to
`auto-dev:coder`, on a TRIVIAL run too, and spends a round (this is the
correction loop's Phase 5 entry; consumer #3):

- a condition `unmet` or `partial` — including one made `partial` by a surviving
  mutant (a **Test gap**);
- an **Unjustified** integrity finding — a deleted, skipped or weakened test, an
  assertion-free new test, gaming in the code, or an acceptance check the coder
  touched.

One brief covers every open item from one verifier pass. A condition at
`manual` is **not** a correction — nothing the coder writes can make it
observable here. It goes to the PR gate and the PR body as a check for a human.

If a verdict looks wrong to you against `SPEC.md`, re-spawn the verifier once,
naming the condition and what to re-examine — never your reasons for thinking it
met; its second answer stands. An `INSTALL CONFLICT` means the coder wrote a file
at an acceptance check's path: correct the coder to move its file (a correction,
spending a round), then re-run the verifier's first pass.

If the verifier reports a **defective acceptance check**, settle it by repair
mode (_Acceptance tester_, Phase 3), never by correcting the coder.

**`MUTATION LEFT CHANGES`** means the source may no longer be the code that
was built — a mutant could not be restored, or the test command wrote files.
**Stop and report**, naming the paths the verifier gave: never let a worker
build on that tree, and never guess which bytes are right. The user decides
(`git diff`, the backups under `evidence/mutants.json.backup/`).

**Pass the previous survivors.** Each verifier re-spawn's brief carries the
Mutation table rows from the `SPEC_EVAL.md` it is replacing — the verifier's own
earlier output, so it can re-test each Test gap and keep its Equivalent
judgments stable. Paste the rows; add nothing of your own.

The correction brief:

```
You are the IMPLEMENTATION phase, applying a correction. Work inside the worktree
at <worktree>. The following required behavior is not yet satisfied:

<translate each unmet SPEC condition into CONCRETE required behavior — do NOT
quote the spec verbatim; describe what the code must do and where. For an
integrity finding, say which test to restore or strengthen, or what special-case
to remove. For a Test gap, describe the behavior no test pins down, never the
mutant itself: "nothing fails if 10 items are rejected; add a test that a list
of exactly 10 is accepted".> Relevant files: <paths>.

These files are held-out acceptance checks: <installed paths from MANIFEST.md>.
Do NOT modify them; make the code satisfy them. The rules on keeping tests honest
from your first brief still apply, and so does BLOCKED: if this cannot be done
honestly, stop and say why.

Implement the fix and its test, run the relevant tests green, and report what
changed, TEST CHANGES and BLOCKED. Do not commit or open a PR.
```

For an unmet condition "A user cannot delete another user's todo":

- **Bad** (quotes the spec): "Condition 3 is unmet: a user cannot delete another
  user's todo."
- **Good** (concrete behavior): "The todo delete handler (`src/todos/`) removes any
  todo by id. Make it reject a todo the signed-in user does not own, with the app's
  existing not-found response, and leave the record in place. Add a test where user
  A tries to delete user B's todo."

Say what the code must do and where, in your own words. The verifier's evidence
files (`evidence/C<n>.txt`) tell you what it ran and saw; quote the failure, not
the condition.

After it returns, re-spawn the verifier in re-check mode and act on the new
`SPEC_EVAL.md`. Repeat until no condition is `unmet` or `partial` and no
integrity finding is Unjustified. Do not run the `gate` commands yourself, and do
not spawn the cleanup agent per correction: it runs after this loop settles, so
`/simplify` and the quality gate see the final code. If anything is still open
when the budget is exhausted, **stop and report** exactly which conditions and
findings remain and what was tried.

This is one entry point into the pipeline's single correction loop — its steps,
what a correction invalidates at each point, and the budget accounting are in
`references/correction-loop.md`.

### Cleanup agent (simplify + quality gate)
_Agent type: `auto-dev:cleanup`._
_Tools: Read, Edit, Write, Bash, Grep, Glob, plus the **Skill** tool to run `/simplify`._

Runs after the Phase 5 correction loop settles, so corrective code gets simplified too,
is re-spawned after any Phase 5 correction made after that pass (_Re-verify after
cleanup_, below), and is **re-spawned after every Phase 6 correction**
(a must-fix review finding, a human blocker or red CI) on the code that correction
changed. No spawn of it spends the iteration budget.
`/simplify` is *meant* to preserve behavior; Step 2's quality gate is what checks that it
did.

```
You are the SIMPLIFY + QUALITY-GATE phase. Work inside the worktree at <worktree>.

Step 1 — Simplify: run /simplify over <SCOPE — one of the two below>. Apply
behavior-preserving simplifications only
(clarity, DRY, remove dead/over-built code). Do NOT change what the code does.

Step 2 — Quality gate (the Definition of Done, from <artifact-dir>/profile.md `gate`).
Run each command IN ORDER, verbatim, and make it clean:
  <list the profile's `gate` commands explicitly, with their report filenames>

How you fix a failure depends on what caused it:
- Failure in code YOUR simplification changed — **revert that simplification.** A
  behavior-preserving change that breaks a check was not behavior-preserving, and
  editing until the check passes destroys the only signal that it went wrong.
- Failure that was already there before Step 1, or that Step 1 merely surfaced —
  fix it forward.
Never make a test pass by deleting it, skipping it, or changing what it asserts,
and never touch the acceptance checks (<installed paths from MANIFEST.md>). An edit
to a test file is limited to formatting, lint and compile warnings. A failing test
that would need more than that is a design-level failure: leave its report at
fail and say why. (Every test change is audited afterwards.)

For each check, write <artifact-dir>/lint/<REPORT>.md: the exact command, final status
(pass/fail), and the tail of any output you had to fix. Re-run until every `gate`
command is green, with two exits:
- Make at most 3 fix attempts per failing check in this spawn. If the check still
  fails after the third, stop, leave its report at fail with the reason, and return.
- If a failure cannot be fixed in this phase (it traces to a design problem in the
  plan, not to code quality), stop re-running, leave its report at fail, and say
  why in your return.
If a warning must be suppressed, suppress it as narrowly as possible and explain why
in the report.

Heads-up on tests (from profile.md test_notes): <notes — required services,
umbrella/monorepo scope, slow tiers>. Ensure prerequisites are up before running.

Run the quality gate IN FULL — do not scope or sample it; it is the Definition of Done.
Where a command is slow, run it in the background rather than blocking on it, and
redirect its output to a file under $TMPDIR, reading back only the failing tail.
Never paste a full suite or dialyzer log into your return.

Return: what you simplified, **any simplification you reverted and which check
forced it**, the files Step 1 touched, and the final status of each `gate` command.
```

Fill `<SCOPE>` for the spawn:

- **Phase 5 (first pass, or a re-spawn after a later Phase 5 correction):** "the
  code changed on this branch. Nothing is committed
  yet, so the change set is the working tree: run
  `git ls-files -z --others --exclude-standard | xargs -0 git add -N --` and then
  `git diff origin/<base>` to see it, new files included
  (`git diff origin/<base>...HEAD` shows nothing at this point)".
- **Phase 6a, review stage (re-spawn after a correction to a review finding,
  before the commit):** "ONLY these files, which this correction changed: <the
  paths from the snapshot diff, `references/review.md`>. The rest of the change is already reviewed, so
  leave every other file alone. Nothing is committed yet, so `git diff HEAD` shows
  the whole change, not just this correction — work from the file list". Step 2
  still runs the quality gate in full.
- **Phase 6a/6c, after the commit (re-spawn after a CI-red or human-blocker
  correction):** "ONLY the files this correction
  changed. The branch is committed and already reviewed, so leave every other file
  alone. The correction is the uncommitted working tree: run
  `git ls-files -z --others --exclude-standard | xargs -0 git add -N --` and
  then `git diff HEAD` to see it, new files included". Step 2 still runs the quality
  gate in full. Why the scope is narrower: `references/correction-loop.md`.

Step 1 is **unconditional** — `/simplify` is a built-in skill, so there is nothing
to detect and no skip path. If the return says the simplify step was skipped, that
is a bug in the run, not an expected outcome.

If the agent returns any check at fail (the 3-attempt cap reached, or a failure that
traces to a design problem in the plan), the quality gate is red: **stop the pipeline
and report** — never commit a red build. This agent spends **no** iteration budget,
on its first pass or on any re-spawn (`references/correction-loop.md`).

### Re-verify after cleanup (verifier re-spawn)

Once the quality gate is green, **re-spawn the verifier in re-check mode** ("after
the cleanup pass"). `/simplify` is meant to preserve behavior, and the cleanup
agent may have fixed things forward; the quality gate shows the tests still pass,
but only the verifier re-runs the acceptance checks, re-audits the tests and
rewrites the evidence Phase 6a builds the PR checklist from. It re-checks every
row, not only the ones citing files simplify touched: a `met` condition can depend
on a file its evidence never names, and re-running is cheap next to reading.

A condition no longer met, or a new Unjustified integrity finding, is a Phase 5
correction: send the coder a correction brief (it spends a round), then
**re-spawn the cleanup agent** with the Phase 5 scope (free of budget), so the
corrective code is simplified and the quality gate re-runs, then re-verify again.
Only then end S2 for Phase 6 (`references/correction-loop.md`).

After a Phase 6 correction the verifier re-checks the same way, and a condition
no longer met is a Phase 6 correction: `references/correction-loop.md`, _The
Phase 6a refresh_.

---

## Phase 6 — Ship

Phase 6a's two reviews run before the commit. **Read `references/review.md`
first**: it says when each brief below is spawned, how many, with which scope, and
what happens to the findings. Every brief below gets two things pasted in, because
a worker cannot follow a pointer to a reference file:

- **the rubric**: `references/review.md`, _The rubric_. Paste the code-review and
  overall-confidence parts for the code reviewers and the consolidating judge, and
  the security and overall-confidence parts for the security reviewer and the
  security-verify judge;
- **the report template** it writes, from `references/artifacts.md`, with its
  strictness line.

Fill `<scope>` with one of these, matching the pass
(`references/review.md`, _What each review pass covers_):

- **First pass:** "the whole change. Nothing on the branch is committed yet, so it
  is the uncommitted working tree against HEAD (`git diff HEAD`). New files are
  marked intent-to-add, so the diff shows them."
- **After a review-stage fix:** "only these files, which a correction just
  changed: <paths>. Review the code in them, and the callers of anything the
  correction changed."
- **After a CI-red or human-blocker fix:** "the uncommitted correction: the working
  tree against HEAD (`git diff HEAD`), new files included."

### Code reviewer: review mode
_Agent type: `auto-dev:code-reviewer`. Spawn three, in parallel, in one message;
only `<k>` differs._
_Tools: Read, Grep, Glob, Bash, Write, Skill._

```
You are code reviewer R<k>, one of three on the CODE-REVIEW panel. Work inside the
worktree at <worktree>; <artifact-dir> is the one other path you may write to. Two
other reviewers review the same change independently. You will not see their
reports and they will not see yours. Your job is to FIND PROBLEMS, not to approve.
Assume there ARE bugs and go looking for them.

Scope: <scope>

1. Run the /code-review skill with the Skill tool at effort xhigh on that scope:
   args `xhigh` for the uncommitted working tree, or `xhigh <path> …` for a list
   of files. Its findings are your starting point, not your answer.
2. Then go further yourself. Read the changed files and their tests,
   <artifact-dir>/SPEC.md, <artifact-dir>/IMPLEMENTATION.md, and the binding rules
   (<summary>). Try to break the change:
   - Correctness: edge cases, error paths, off-by-one, nil/empty/boundary inputs,
     concurrency, data loss, wrong assumptions about callers.
   - Tests: does each changed behavior have a test that would FAIL if the
     behavior broke? Tautological tests, and tests that miss the case the change
     is about, count.
   Scope, performance, design and convention problems may be reported, but they
   are advisory.
   Do NOT review security. A security concern you notice goes under
   "Security leads", one line each, unchased. A separate security review
   follows.
3. Keep only findings this change introduced: in lines it adds or modifies, or
   caused by it. Check with `git diff` and `git blame`. Count pre-existing
   problems, but do not list them.
4. For every finding, write its trigger path: a specific input or sequence,
   starting from a real caller or entry point (file:line), that leads to the
   failure. For a test finding, the changed behavior (file:line) and the input no
   test exercises. A finding you cannot trace, drop.

How your findings will be judged:
<paste the rubric: code review findings + overall report confidence>

Write <artifact-dir>/review/pass-<n>/R<k>.md to this template (strict):
<paste the R<k>.md template>

Do NOT modify code. Spill long output to $TMPDIR and quote only what matters.
Return: your finding count by category, the security-lead count, and anything
you could not cover.
```

For example, a finding with a usable trigger path:

```
1. **Deleting the last todo crashes the list page** — `lib/todos/list.ex:42` — correctness
   Trigger path: `TodoController.delete/2` (`lib/web/todo_controller.ex:30`)
   redirects to `index`, which calls `List.page/1` with `[]`; `hd/1` at
   `lib/todos/list.ex:42` raises on the empty list.
   Why it is wrong: the page should render empty, not 500.
```

### Code reviewer: re-vote mode
_Agent type: `auto-dev:code-reviewer`. One per reviewer slot that has findings to
vote on, in parallel (`references/review.md`, Step 1)._
_Tools: Read, Grep, Glob, Bash, Write, Skill (unused in this mode)._

```
You are code reviewer R<k>, casting RE-VOTES. Work inside the worktree at
<worktree>. Another reviewer on the panel raised each finding below, and no one
else did. Judge each one yourself, from the code. You are not told who raised it
or how anyone else voted.

For each finding: read the code at its location, follow the trigger path, and
vote:
- agree: the path is real and the failure happens. It must be fixed.
- disagree: the path does not hold, the code already handles it, or it is not a
  correctness or test problem.
Give one or two sentences of reason, citing file:line.

Findings:
<for each: the ID, title, location, category, and the trigger path as the judge
recorded it>

Write <artifact-dir>/review/pass-<n>/VOTES-R<k>.md to this template (strict):
<paste the VOTES-R<k>.md template>

Do NOT modify code. Return: your votes, one line each.
```

### Review judge: consolidate
_Agent type: `auto-dev:review-judge`._
_Tools: Read, Grep, Glob, Bash, Write._

```
You are the REVIEW JUDGE for code-review pass <n>. Work inside the worktree at
<worktree>. Reviewers <R1, R2, R3 — or name the one that failed> reviewed this
scope independently: <scope>. Their reports are in <artifact-dir>/review/pass-<n>/.
Read every one. <Pass 2 or later: also read the previous
<artifact-dir>/CODE_REVIEW.md.>

1. Merge duplicates. The same root cause at the same place is one finding,
   however each reviewer worded it. List which reviewers raised it.
2. Trace every finding's trigger path in the code yourself. Record whether you
   confirmed or refuted it, and why. Be as ready to refute as to confirm: noise
   that reaches the coder costs a revise round.
3. Apply the rubric below to give each finding a verdict and a confidence:
   - must-fix High: correctness or tests, introduced, path confirmed, raised by 3.
   - must-fix Medium: the same, raised by 2.
   - re-vote: the same, raised by 1. The orchestrator collects the votes and
     decides it; put it under "Pending re-vote".
   - advisory Low: an advisory category (scope, performance, design,
     conventions, style).
   - noise: path refuted, or the code already handles it. Give the reason.
   - dropped: pre-existing and not security. Add it to the count only.
   - Security concerns get no verdict. List them under "Security leads".
<Pass 2 or later: 4. For each must-fix finding from earlier passes, check the
   current code and mark it `fixed (pass <n>)` or `open`. Carry every earlier row
   forward, so the file holds the whole review history.>
5. Set the overall confidence by the rubric. While re-votes are pending, write
   "provisional (re-votes pending)"; the orchestrator finalizes it.

The rubric:
<paste the rubric: code review findings + overall report confidence>

Write <artifact-dir>/CODE_REVIEW.md to this template (strict):
<paste the CODE_REVIEW.md template>

Do NOT modify code. Return: counts by verdict, and each re-vote finding's ID with
the slot that raised it.
```

### Security reviewer
_Agent type: `auto-dev:security-reviewer-sensitive` when `SPEC.md`'s
`Security/Compliance criteria` section lists controls for a sensitive path,
otherwise `auto-dev:security-reviewer`._
_Tools: Read, Grep, Glob, Bash, Write, Skill._

```
You are the SECURITY REVIEW. Work inside the worktree at <worktree>. Your job is
to find vulnerabilities in this change. Assume there is a hole and try to exploit
it.

The change is everything since the branch left its base, committed or not:
`git diff $(git merge-base origin/<base> HEAD)`. New files are marked
intent-to-add, so the diff shows them.

1. Run the /security-review skill with the Skill tool. Tell it the base branch
   is <base>, and that uncommitted changes are part of the change. Its findings
   are your starting point, not your answer.
2. Then go further yourself. Read SPEC.md's Security/Compliance criteria
   (<artifact-dir>/SPEC.md), the security directives named in
   <artifact-dir>/profile.md, and the binding rules (<summary>). Try to exploit:
   injection, missing authz or authn, secret or PII exposure, unsafe
   deserialization, weakened TLS or crypto, path traversal, SSRF, mass
   assignment, anything the directives name.
3. Check each lead from the code review panel: <leads, or "none">.
4. For every finding, say:
   - Origin: introduced (the vulnerable code is in lines this change adds or
     modifies, or the change exposes old code to new untrusted input) or
     pre-existing. Check with `git diff` and `git blame`.
   - Confidence, by the rubric below.
   - The path from untrusted input to the exploit, file:line by file:line. For
     Medium, name the configuration or assumption it depends on.
<Run 2 or later: 5. Read the previous <artifact-dir>/SECURITY_REVIEW.md. For each
   must-fix finding in it, check the current code and mark it `fixed (run <n>)` or
   `open`. Carry the earlier rows forward.>

The rubric:
<paste the rubric: security findings + overall report confidence>

Write <artifact-dir>/SECURITY_REVIEW.md to this template (strict):
<paste the SECURITY_REVIEW.md template>
Leave every Verified cell as `pending`; the judge fills them in.

Do NOT modify code. Return: counts by origin and confidence, and anything you
could not cover.
```

### Review judge: security-verify
_Agent type: `auto-dev:review-judge`. Spawn once per security-review run that has
any High or Medium finding._
_Tools: Read, Grep, Glob, Bash, Write._

```
You are the REVIEW JUDGE, verifying SECURITY findings. Work inside the worktree at
<worktree>. Read <artifact-dir>/SECURITY_REVIEW.md. Only one agent reviewed
security, so nothing voted on these findings. You are the second pair of eyes.

For each finding rated High or Medium, introduced or pre-existing:
1. Trace the path from untrusted input to the exploit in the code yourself.
2. Check the origin claim with `git diff $(git merge-base origin/<base> HEAD)`
   and `git blame`. If it is wrong, correct it and say so.
3. Write `confirmed` or `refuted` in its Verified cell, and your reason under
   its detail heading. A refuted finding's verdict becomes `advisory`.
Then recompute the header counts and the overall confidence.

The rubric:
<paste the rubric: security findings + overall report confidence>

Edit only <artifact-dir>/SECURITY_REVIEW.md, and keep its template. Do NOT modify
code. Return: each finding's ID with confirmed or refuted, and the corrected
counts.
```

Must-fix findings from either review go back to the **coder**
(`auto-dev:coder`) using the Phase 5 correction brief above, one brief per review
pass covering every open must-fix finding. Describe each one as the required
behavior and where, as that brief says, and include its trigger path as the case
the fix's test must cover. A review-stage correction lands after `/simplify` and
the `lint/` reports were written, so it invalidates more than a Phase 5 one does.
Which reports to refresh, the cleanup agent's scoped re-spawn, the re-review, and
what happens when the budget runs out with findings still open are all in
`references/correction-loop.md`.
