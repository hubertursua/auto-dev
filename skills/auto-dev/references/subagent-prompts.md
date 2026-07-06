# Subagent prompt templates

Brief templates for every delegated Task Agent, plus the tool-permission
requirement for each. The orchestrator fills the `<…>` placeholders and always
hands the worker: the **worktree absolute path**, `.auto-dev/profile.md`, the
repo's binding rules (from Phase 1), and only the inputs that phase needs.

> All phase briefs are authored (Phases 2–8). Phase 1 is deterministic
> orchestrator work (see `SKILL.md`); Phase 6 is an orchestrator check with a
> coder correction brief; Phases 9–10 are orchestrator git/gh operations.

## Conventions for every brief

- **Non-interactive:** the worker never asks the user; it resolves ambiguity with
  a recorded assumption.
- State the worktree path and "work entirely inside it; do not touch other trees."
- Name the exact artifact file(s) to write and their contract
  (`references/artifacts.md`).
- Require a short structured return: what it did, assumptions, risks, and (for
  reviewers) findings grouped **blocker / should-fix / nit**.
- Pass the binding rules + org security directives; they override "finish."
- Reviewers are **read-only** and must **not** rewrite files — they return
  findings; the orchestrator applies fixes (it holds the context and this consumes
  the shared iteration budget).

---

## Phase 2 — Ticket-analysis agent
_Tools: Write + Read, Grep, Glob (research is read-only; it must not modify source)._

One pass that researches the ticket against the codebase, drafts the **acceptance
criteria** (stakeholder view), assesses **testability**, and returns a
**complexity/scope signal** the orchestrator uses for the scoping decision.

```
You are the TICKET-ANALYSIS phase of an autonomous dev pipeline. Work entirely
inside the worktree at <abs-path>. Do NOT modify any source code. Do NOT ask the
user anything — resolve every ambiguity yourself and record it as an assumption.

Ticket / task: <the ticket summary + description, or the user's task text, verbatim>
Ticket source: <JIRA-KEY and link, or "free-form task (no ticket)">
Project profile: read .auto-dev/profile.md for the stack, conventions, and gate.
Binding rules: <repo CLAUDE.md/CONTRIBUTING/security docs summary + org security
directives>. These constrain what "done" and "acceptable" mean.

Explore the relevant code enough to understand what the ticket really asks: find
the feature area, similar existing features, the modules/flows involved, and any
constraints (auth, data, migrations, external services). Do NOT design a solution.

Write exactly two files:

1. .auto-dev/TICKET.md — the normalized ticket for humans: title, a clear restated
   description, links, and a "Research findings" section (where this lives in the
   code, relevant modules/paths, similar precedents, constraints, open questions
   you resolved as assumptions). Stakeholder-facing; no technical design.

2. .auto-dev/ACCEPTANCE_CRITERIA.md — WHAT THE TICKET ASKS, in stakeholder
   language: the observable outcomes someone would sign off on. Bullet list of
   criteria a non-engineer could verify. NOT test code, NOT design. For each
   criterion add a one-line "testability" note (how it could be observed/verified,
   or "hard to test because …"). Add an "Assumptions" section for every ambiguity
   you resolved. If the task touches a sensitive path (auth, data handling,
   payments, access control, anything the repo's guidelines flag), add a
   "Security/Compliance" note pulling the relevant controls from the repo's docs
   and the org directives.

Return a structured summary:
- slug: a short kebab-case slug for the branch/work
- assumptions: the key ones you made
- risks: the main correctness/security/scope risks
- SCOPE SIGNAL: subsystems/services touched (list), rough count of files to
  change, whether the work has independent deliverables that could ship
  separately, and your one-line call: FITS_ONE_PR or OVERSIZED (with why).
```

After it returns, read both files. Use the **SCOPE SIGNAL** for the scoping
decision below.

### Scoping & decomposition (orchestrator)

Decide single-PR vs. multi-PR:

- **FITS_ONE_PR** (small, one subsystem, cohesive): proceed to Phase 3 as a
  single-PR run. Record `Mode: single-PR` in `WORK_LOG.md`.
- **OVERSIZED** (multiple independent deliverables, several subsystems, or a large
  file count): do **not** cram it onto one branch. Draft an ordered decomposition
  into sub-tasks — each independently shippable, with dependencies noted — and:
  1. Write the sub-task table to `.auto-dev/WORK_LOG.md` (`Mode: multi-PR`; see
     `references/artifacts.md`).
  2. **Alert the user** with the proposed breakdown and ask to proceed
     (`AskUserQuestion`). If they adjust it, update the ledger.
  3. On approval, run Phases 3–10 **per sub-task** in dependency order — each in
     its own branch/worktree and `.auto-dev/tasks/<id>/` subtree — updating the
     ledger after each. Each sub-task re-runs the ticket-analysis brief scoped to
     that sub-task (so it gets its own ACCEPTANCE_CRITERIA).

Borderline? Prefer surfacing the decomposition and letting the user choose over
silently committing to one giant PR.

---

## Phase 3 — Spec Definition

### Problem Breakdown (orchestrator)
Before spawning the spec agent, frame the problem for it: restate the goal in one
paragraph, list the acceptance criteria it must turn into testable conditions, and
call out the sensitive paths. This goes into the spec agent's brief.

### Spec Writing agent
_Tools: Write + Read, Grep, Glob._

Turns the stakeholder acceptance criteria into the **testable contract**.

```
You are the SPECIFICATION phase. Work inside the worktree at <abs-path>. Do NOT
modify source. Do NOT ask the user — record assumptions instead.

Read .auto-dev/ACCEPTANCE_CRITERIA.md and .auto-dev/TICKET.md. Read
.auto-dev/profile.md and the binding rules: <summary>.

Write exactly one file: .auto-dev/SPEC.md — the ACCEPTANCE CRITERIA AS A TESTABLE
CONTRACT. Every entry is an observable, testable condition that defines "this
works," in plain language. NO technical design, no file names, no function
signatures. Trace each condition back to an acceptance criterion (every criterion
must be covered). Include:
- an "Assumptions" section for every ambiguity you resolved;
- a "Security/Compliance criteria" section when the task touches a sensitive path,
  pulling the specific controls from the repo's security docs and the org
  directives (e.g. parameterized queries, authz checks, no secrets/PII).

Return: the slug, assumptions made, key risks, and any acceptance criterion you
could not make testable (with why).
```

Read `SPEC.md` yourself — **you hold it and withhold it from the coder** (Phase 5);
it is your independent check in Phase 6.

### Spec Review agent
_Tools: Read, Grep, Glob only (must not rewrite the file)._

```
You are the SPEC-REVIEW phase. Read .auto-dev/SPEC.md, .auto-dev/ACCEPTANCE_CRITERIA.md,
and the binding rules (<summary>) in the worktree at <abs-path>.

Critique SPEC.md and return findings grouped blocker / should-fix / nit:
- Are all conditions observable and TESTABLE (not vague)?
- Free of technical leakage (no design masquerading as a requirement)?
- Does every acceptance criterion map to a testable condition (list any gap)?
- Are the assumptions reasonable, and the security/compliance criteria complete
  for what the task touches?
Do NOT rewrite the file. Return findings only.
```

Apply fixes yourself by editing `SPEC.md`; re-review only if blockers remain.
Consumes the shared iteration budget.

---

## Phase 4 — Implementation Planning

### Impl Writing agent
_Tools: Write + Read, Grep, Glob._

```
You are the IMPLEMENTATION-PLAN phase. Work inside the worktree at <abs-path>. Do
NOT modify source. Do NOT ask the user — record assumptions.

Read .auto-dev/SPEC.md — your plan must satisfy every condition in it. Read
.auto-dev/profile.md (the gate commands are the Definition of Done) and the
binding rules (<summary>). Explore the code (find similar features, map the
architecture, identify the exact files you'll touch) before designing.

Write exactly one file: .auto-dev/IMPLEMENTATION.md — the technical HOW, sufficient
to build from ON ITS OWN. Include: files to create/modify (paths); the design
(modules/functions/data structures); data flow; the ordered build sequence; the
test plan (which test proves which behavior, and where it lives); any
migration/config. It must be self-contained — a competent engineer who has NOT
seen the acceptance criteria should build the right thing from this plan alone.
Ensure every SPEC.md condition maps to a plan step AND a test.

Return: the slug, assumptions, key risks.
```

### Impl Review agent
_Tools: Read, Grep, Glob only._

```
You are the PLAN-REVIEW phase. Read .auto-dev/IMPLEMENTATION.md and .auto-dev/SPEC.md
and the binding rules (<summary>) in the worktree at <abs-path>.

Critique IMPLEMENTATION.md; findings grouped blocker / should-fix / nit:
- Complete and self-contained (buildable without the spec)?
- Does every SPEC.md condition map to a plan step AND a test? List gaps both ways
  (a condition with no step/test; a step that traces to no condition).
- Follows repo conventions and security constraints? Correctness/security/scope
  risks? Anything over-engineered for the task?
Do NOT rewrite the file. Return findings only.
```

Apply fixes yourself; re-review if blockers remain. Consumes the shared budget.

### Optional post-plan gate (orchestrator)
If enabled for this run, pause here (`AskUserQuestion`) for the user to approve
`SPEC.md` + `IMPLEMENTATION.md` before any code is written. Off by default; see
`references/gates-and-jira.md`.

---

## Phase 5 — Implementation

### Steps Breakdown (orchestrator)
Before spawning the coder, derive `.auto-dev/CODING_TODO.md` from
`IMPLEMENTATION.md`: the ordered, checkable list of implementation steps (each a
small, verifiable unit, in build order, with its test). This is the coder's
worklist and the visible progress trail. Keep it in sync with the plan — it is a
projection of the plan, not a new source of truth.

### Coding agent (TDD)
_Tools: Read, Write, Edit, Bash, Grep, Glob._ Spawn with the **plan +
CODING_TODO only — never SPEC.md** (that independence is what makes Phase 6 real).

```
You are the IMPLEMENTATION phase. Work inside the worktree at <abs-path>. Do NOT
ask the user — record assumptions.

Implement the change in .auto-dev/IMPLEMENTATION.md, working through
.auto-dev/CODING_TODO.md in order. Read .auto-dev/profile.md for the toolchain and
test command, and the binding rules (<summary>) — follow the repo's security and
coding guidelines, never log/expose sensitive data, never hardcode secrets, use
synthetic/test data only.

Work test-first where practical: for each step, add or extend the test the plan
calls for, then make it pass. Follow existing codebase conventions and
abstractions closely. Run the relevant tests as you go and get them green
(test command: <from profile.md>; scope hints: <profile.md test_notes>). Do NOT
commit and do NOT open a PR — just leave the working tree with the change
implemented and CODING_TODO items checked off.

Return: files created/modified, tests added, which CODING_TODO items are done, and
anything in the plan you could NOT do and why.
```

### Impl-Eval agent
_Tools: Read, Grep, Glob, Bash (read-only w.r.t. source — no Edit/Write to code)._
Checks the code against the **plan**, not the spec.

```
You are the IMPLEMENTATION-EVAL phase (plan-adherence check). Work inside the
worktree at <abs-path>. Do NOT modify source.

Read .auto-dev/IMPLEMENTATION.md and .auto-dev/CODING_TODO.md, then inspect what
was actually built (`git diff <base>...HEAD`, the changed files, the tests).

Write .auto-dev/IMPLEMENTATION_EVAL.md: for each plan step, is it implemented as
designed? Findings grouped blocker / should-fix / nit, each with file:line.
Specifically flag: plan steps not implemented (or done differently without an
assumption), tests the plan required that are missing, and code added that the
plan didn't call for. Do NOT rewrite code. Return the blocker count.
```

Blockers feed back to the coding agent with a specific fix brief; consumes the
shared iteration budget.

## Phase 6 — Evaluation (acceptance) · orchestrator

**You**, holding `SPEC.md` (which the coder never saw), verify the build against
every acceptance condition. Read the diff (`git diff <base>...HEAD`) and the
tests. Write `.auto-dev/SPEC_EVAL.md`: per condition, **met / partial / unmet**
with evidence (file:line or test name); include the security/compliance
conditions.

For each unmet/partial condition, re-dispatch the **coding agent** with a targeted
correction brief (this is the feedback loop; it consumes the shared budget):

```
You are the IMPLEMENTATION phase, applying a correction. Work inside the worktree
at <abs-path>. The following required behavior is not yet satisfied:

<translate the unmet SPEC condition into CONCRETE required behavior — do NOT quote
the spec verbatim; describe what the code must do and where>. Relevant files:
<paths>. Implement the fix and its test, run the relevant tests green, and report
what changed. Do not commit or open a PR.
```

After it returns, re-run the affected Phase 7 gate checks, then re-evaluate. If
conditions remain unmet when the budget is exhausted, **stop and report** exactly
which conditions are unsatisfied and what was tried.

## Phase 7 — Cleanup agent (simplify + quality gate)
_Tools: Read, Edit, Write, Bash, plus a way to run code-simplifier (the Skill
tool, or spawn `code-simplifier:code-simplifier`)._

```
You are the POLISH + QUALITY-GATE phase. Work inside the worktree at <abs-path>.

Step 1 — Simplify: run code-simplifier over the code changed on this branch (diff
against <base>). Apply behavior-preserving simplifications only (clarity, DRY,
remove dead/over-built code). Do NOT change what the code does. If code-simplifier
is unavailable, skip this step and note it.

Step 2 — Quality gate (the Definition of Done, from .auto-dev/profile.md `gate`).
Run each command IN ORDER, verbatim, and make it clean, fixing issues you
introduced or surfaced:
  <list the profile's gate commands explicitly, with their report filenames>
For each check, write .auto-dev/lint/<REPORT>.md: the exact command, final status
(pass/fail), and the tail of any output you had to fix. Re-run until every gate
command is green. If a warning must be suppressed, suppress it as narrowly as
possible and explain why in the report.

Heads-up on tests (from profile.md test_notes): <notes — required services,
umbrella/monorepo scope, slow tiers>. Ensure prerequisites are up before running.

Return: what you simplified, and the final status of each gate command.
```

If the gate cannot be made green (e.g. a failure that traces to a genuine design
problem in the plan), **stop the pipeline and report** — never commit a red build.
Gate fixes consume the shared budget.

## Phase 8 — Adversarial PR Review agent
_Tools: Read, Grep, Glob, Bash (`git diff`, `gh`) — read-only w.r.t. source._
Briefed to **find problems, not rubber-stamp**. Runs after the PR is opened.

```
You are the ADVERSARIAL PR-REVIEW phase. Work inside the worktree at <abs-path>.
Your job is to FIND PROBLEMS in the change on this branch — not to approve it.
Assume there ARE bugs and go looking for them.

Read the diff (`git diff <base>...HEAD`), the changed files, and the tests. Read
.auto-dev/SPEC.md, .auto-dev/IMPLEMENTATION.md, and the binding rules (<summary>)
plus the org security directives.

Hunt across these lenses and actively try to break each:
- Correctness: edge cases, error paths, off-by-one, nil/empty/boundary inputs,
  concurrency, wrong assumptions. Name an input that breaks it.
- Security: injection, authz gaps, secret/PII exposure, unsafe deserialization,
  weakened TLS/crypto — check against the org directives (SEC-*).
- Scope: anything built beyond the spec, or a spec condition not actually met.
- Tests: do they PROVE the behavior, or are they tautological / missing the
  important cases?
- Conventions: deviations from repo patterns.

Write .auto-dev/PR_REVIEW.md: findings grouped blocker / should-fix / nit, each
with file:line and a concrete "why this is wrong / how to trigger it." If a lens
genuinely turns up nothing, say so briefly — but default to skepticism. Do NOT
modify code. Return the blocker count.
```

If the review returns blockers: feed them back to the **coding agent** (Phase 5
correction brief) and re-run the affected Phase 7 gate checks before proceeding —
this consumes the shared budget. If the budget is exhausted with blockers open,
surface them to the user at the PR gate rather than merging over them.
