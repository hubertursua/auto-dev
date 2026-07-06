# Subagent prompt templates

Brief templates for every delegated Task Agent, plus the tool-permission
requirement for each. The orchestrator fills the `<…>` placeholders and always
hands the worker: the **worktree absolute path**, `.auto-dev/profile.md`, the
repo's binding rules (from Phase 1), and only the inputs that phase needs.

> **Status:** scaffold. The Phase 2–4 briefs are authored in **M1**; the Phase 5
> (coder / impl-eval) and Phase 7 (cleanup) briefs in **M2**; the Phase 8
> adversarial PR-review brief in **M3**. Section headers below are the contract;
> each is filled in as its milestone lands.

## Conventions for every brief

- Non-interactive: the worker never asks the user; it resolves ambiguity with a
  recorded assumption.
- State the worktree path and "work entirely inside it; do not touch other trees."
- Name the exact artifact file(s) to write and their contract
  (`references/artifacts.md`).
- Require a short structured return: what it did, assumptions, risks, and (for
  reviewers) findings grouped blocker / should-fix / nit.
- Pass the binding rules + org security directives; they override "finish."

## Phase 2 — Ticket-analysis agent  *(M1)*
_Tools: Write + Read, Grep, Glob._

## Phase 3 — Spec Writing agent · Spec Review agent  *(M1)*
_Writing: Write + Read, Grep, Glob. Review: Read, Grep, Glob._

## Phase 4 — Impl Writing agent · Impl Review agent  *(M1)*
_Writing: Write + Read, Grep, Glob. Review: Read, Grep, Glob._

## Phase 5 — Coding agent (TDD) · Impl-Eval agent  *(M2)*
_Coding: Read, Write, Edit, Bash, Grep, Glob (plan only, never the spec).
Impl-Eval: Read, Grep, Glob, Bash._

## Phase 7 — Cleanup agent  *(M2)*
_Read, Edit, Write, Bash, plus a way to run code-simplifier._

## Phase 8 — Adversarial PR Review agent  *(M3)*
_Read, Grep, Glob, Bash (`git diff`, `gh`); read-only w.r.t. source; writes
`PR_REVIEW.md`; briefed to find problems, not rubber-stamp._
