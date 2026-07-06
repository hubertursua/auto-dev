# Subagent prompt templates

Brief templates for every delegated Task Agent, plus the tool-permission
requirement for each. The orchestrator fills the `<…>` placeholders and always
hands the worker: the **worktree absolute path**, `.auto-dev/profile.md`, the
repo's binding rules (from Phase 1), and only the inputs that phase needs.

> **Status:** Phase 2–4 briefs authored (M1). Phase 5 (coder / impl-eval) and
> Phase 7 (cleanup) briefs land in **M2**; the Phase 8 adversarial PR-review brief
> in **M3**.

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

## Phase 5 — Coding agent (TDD) · Impl-Eval agent  *(M2)*
_Coding: Read, Write, Edit, Bash, Grep, Glob (given the plan + CODING_TODO,
**never the spec**). Impl-Eval: Read, Grep, Glob, Bash._

## Phase 7 — Cleanup agent  *(M2)*
_Read, Edit, Write, Bash, plus a way to run code-simplifier._

## Phase 8 — Adversarial PR Review agent  *(M3)*
_Read, Grep, Glob, Bash (`git diff`, `gh`); read-only w.r.t. source; writes
`PR_REVIEW.md`; briefed to find problems, not rubber-stamp._
