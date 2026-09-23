# Subagent prompt templates

Brief templates for every delegated Task Agent, plus the tool-permission
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
> orchestrator work (see `SKILL.md`); the Phase 5 acceptance check is an
> orchestrator check with a coder correction brief; the Phase 6 git/gh
> operations are the orchestrator's.

**Models: every worker inherits the orchestrator's model.** No brief pins one —
see the model note in `SKILL.md`.

## Conventions for every brief

- **Non-interactive:** the worker never asks the user; it resolves ambiguity with
  a recorded assumption.
- State the worktree path and "work entirely inside it; do not touch other trees."
  Where `<artifact-dir>` lies outside that tree (multi-PR runs), say so
  explicitly: it is the one path the worker may read and write outside `<worktree>`.
- Name the exact artifact file(s) to write, and **paste that artifact's template
  from `references/artifacts.md` into the brief**. A worker has no path to the
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
- **Keep any single command under 5 minutes.** A subagent's prompt cache expires
  after 5 minutes — the orchestrator's lasts an hour — so a worker idling on a long
  blocking command has its whole context re-billed at write price. Where a check is
  genuinely long (a full suite, a cold build), tell the worker to scope it
  (`--only`, a directory, the affected files) and hand the full run back to the
  orchestrator, which can afford to wait or background it. **The cleanup agent's
  Step 2 is the one exception** — the quality gate is the Definition of Done and
  must run in full; its brief says how.

---

## Phase 2 — Define

### Define agent
_Tools: Write + Read, Grep, Glob (research is read-only; it must not modify source)._

One pass that researches the ticket against the codebase, states the acceptance
conditions **as a testable contract**, and returns the **scope call** the
orchestrator branches on. Research and contract are the same agent's job on
purpose: the agent holding the codebase research is the one best positioned to
know what is actually observable.

```
You are the DEFINE phase of an autonomous dev pipeline. Work entirely inside the
worktree at <worktree>. Do NOT modify any source code. Do NOT ask the user
anything — resolve every ambiguity yourself and record it as an assumption.

Ticket / task: <the ticket summary + description, or the user's task text, verbatim>
Ticket source: <JIRA-KEY and link, or "free-form task (no ticket)">
Project profile: read <artifact-dir>/profile.md for the stack, conventions, and gate.
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

3. "Assumptions" — every ambiguity you resolved.

4. "Security/Compliance criteria" — when the task touches a sensitive path (auth,
   data handling, payments, access control, anything the repo's guidelines flag),
   pull the specific controls from the security-directive sources named in
   <artifact-dir>/profile.md (e.g. parameterized queries, authz checks, no
   secrets/PII). If it records "none found", fall back to the repo's coding rules
   and say so in this section.

Return a structured summary:
- assumptions: the key ones you made
- risks: the main correctness/security/scope risks
- SCOPE CALL: exactly one of TRIVIAL / STANDARD / OVERSIZED, with one line of why.
  * TRIVIAL   = one subsystem, one behavior, no new abstraction or interface, no
                migration or config change, and an existing test file covers it.
  * STANDARD  = fits one PR but is none of the above.
  * OVERSIZED = multiple independent deliverables, several subsystems, or a large
                file count. Also list the subsystems touched and a rough file count.
```

After it returns, read `SPEC.md`. **You hold it and withhold it from the coder**
(Phase 4); it is your independent check in Phase 5.

No brief returns a slug: Phase 1 derived it and cut the branch and worktree before
this phase ran, so a slug proposed here could only conflict with paths already on
disk.

### Define reviewer
_Tools: Read, Grep, Glob only (must not rewrite the file)._
**Skip this agent entirely when the scope call is TRIVIAL.**

```
You are the DEFINE-REVIEW phase. Read <artifact-dir>/SPEC.md and the binding rules
(<summary>) in the worktree at <worktree>.

Critique SPEC.md and return findings grouped blocker / should-fix / nit:
- Are all conditions observable and TESTABLE (not vague)?
- Free of technical leakage (no design masquerading as a requirement)?
- Does the Context section actually support the conditions — is anything asserted
  in a condition that the research doesn't back up?
- Are the assumptions reasonable, and the security/compliance criteria complete
  for what the task touches?
- Anything the ticket asks for that no condition covers?
Do NOT rewrite the file. Return findings only.
```

Apply fixes yourself by editing `SPEC.md`; re-review only if blockers remain.
Consumes the shared iteration budget.

### Scope decision (orchestrator)

Branch on the **SCOPE CALL**:

- **TRIVIAL** — skip the Define review and the Phase 3 agents. Write a short
  `IMPLEMENTATION.md` yourself: the files to touch and the test that proves it.
  Go to Phase 4 (but see the post-plan gate below — it still fires if enabled).
  Record `Mode: single-PR` and `Scope call: TRIVIAL` in `WORK_LOG.md`, and mark
  Phase 3's ledger row `skipped`.
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

**Skipped as an agent phase when the scope call is TRIVIAL** — the orchestrator
writes a short `IMPLEMENTATION.md` directly instead.

### Plan agent
_Tools: Write + Read, Grep, Glob._

```
You are the IMPLEMENTATION-PLAN phase. Work inside the worktree at <worktree>. Do
NOT modify source. Do NOT ask the user — record assumptions.

Read <artifact-dir>/SPEC.md — your plan must satisfy every condition in it. Read
<artifact-dir>/profile.md (the gate commands are the Definition of Done) and the
binding rules (<summary>). Explore the code (find similar features, map the
architecture, identify the exact files you'll touch) before designing.

Write exactly one file: <artifact-dir>/IMPLEMENTATION.md — the technical HOW, sufficient
to build from ON ITS OWN. Include: files to create/modify (paths); the design
(modules/functions/data structures); data flow; the ordered build sequence (this
is the coder's worklist — make each step a small, verifiable unit with its test);
the test plan (which test proves which behavior, and where it lives); any
migration/config. It must be self-contained — a competent engineer who has NOT
seen the spec should build the right thing from this plan alone. Ensure every
SPEC.md condition maps to a build step AND a test.

Return: assumptions, key risks.
```

### Plan reviewer
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

Apply fixes yourself; re-review if blockers remain. Consumes the shared budget.
A spec condition with no plan step is cheapest to catch here, before code exists.

### Optional post-plan gate (orchestrator)
If enabled for this run, pause here (`AskUserQuestion`) for the user to approve
`SPEC.md` + `IMPLEMENTATION.md` before any code is written. Off by default; see
`references/gates-and-jira.md`.

**This gate is independent of the scope call.** On the TRIVIAL path the agents
above are skipped but this gate is not — the user asked to see a plan before code
exists, and the short plan you wrote yourself is still that plan.

---

## Phase 4 — Build

### Coding agent (TDD)
_Tools: Read, Write, Edit, Bash, Grep, Glob._ Spawn with the **plan only — never
SPEC.md** (see *Why two documents* in `SKILL.md`).

```
You are the IMPLEMENTATION phase. Work inside the worktree at <worktree>. Do NOT
ask the user — record assumptions.

Implement the change in <artifact-dir>/IMPLEMENTATION.md, working through its build
sequence in order. Read <artifact-dir>/profile.md for the toolchain and test command,
and the binding rules (<summary>) — follow the repo's security and coding
guidelines, never log/expose sensitive data, never hardcode secrets, use
synthetic/test data only.

Work test-first where practical: for each step, add or extend the test the plan
calls for, then make it pass. Follow existing codebase conventions and
abstractions closely. Run the relevant tests as you go and get them green
(test command: <from profile.md>; scope hints: <profile.md test_notes>). Do NOT
commit and do NOT open a PR — just leave the working tree with the change
implemented.

Return:
- files created/modified, and tests added
- which build-sequence steps are done
- DEVIATIONS: any step you did differently than the plan describes, or could not
  do at all, and why. Be specific and honest — a better route is a fine reason,
  and this report is read as information, not as a failure.
```

**Read the DEVIATIONS report as context going into Phase 5 — not as a defect list.**
The plan is a route; Phase 5's acceptance check is what decides whether the
destination was reached. Do not spend budget reconciling code with a plan it
improved on.

---

## Phase 5 — Verify

### Acceptance check (orchestrator)

**You**, holding `SPEC.md` (which the coder never saw), verify the build against
every condition. Read the diff, the tests, and the coder's DEVIATIONS report.

The coder is told not to commit, so **the change set is the working tree**:

```bash
git add -N .              # intent-to-add, so newly created files appear in the diff
git diff origin/<base>
```

Both halves are load-bearing and both fail silently — `SKILL.md` Phase 5 gives the
reasoning, including why the base is `origin/<base>` and not the local branch.

Write `<artifact-dir>/SPEC_EVAL.md` to the template in `references/artifacts.md`:
per condition, **met / partial / unmet** with evidence (file:line or test name),
security/compliance conditions included.

For each unmet/partial condition, re-dispatch the **coding agent** with a targeted
correction brief (this is the feedback loop; it consumes the shared budget):

```
You are the IMPLEMENTATION phase, applying a correction. Work inside the worktree
at <worktree>. The following required behavior is not yet satisfied:

<translate the unmet SPEC condition into CONCRETE required behavior — do NOT quote
the spec verbatim; describe what the code must do and where>. Relevant files:
<paths>. Implement the fix and its test, run the relevant tests green, and report
what changed. Do not commit or open a PR.
```

After it returns, **you** re-run the affected profile `gate` commands directly
(you have Bash) to confirm the correction broke nothing, then re-evaluate. The
cleanup agent is **not** re-spawned for this: it runs once, after this loop
settles, so `/simplify` sees the final code. If conditions remain unmet when the
budget is exhausted, **stop and report** exactly which are unsatisfied and what
was tried.

This is one entry point into the pipeline's single corrective loop — its steps,
what a correction invalidates at each point, and the budget accounting are in
`references/correction-loop.md`.

### Cleanup agent (simplify + quality gate)
_Tools: Read, Edit, Write, Bash, plus the **Skill** tool to run `/simplify`._

Runs after the acceptance loop settles, so corrective code gets simplified too.
`/simplify` is *meant* to preserve behavior; Step 2's gate is what checks that it
did.

```
You are the POLISH + QUALITY-GATE phase. Work inside the worktree at <worktree>.

Step 1 — Simplify: run /simplify over the code changed on this branch. Nothing
is committed yet, so the change set is the working tree: run `git add -N .` and
then `git diff origin/<base>` to see it, new files included
(`git diff origin/<base>...HEAD` shows nothing at this point). Apply
behavior-preserving simplifications only
(clarity, DRY, remove dead/over-built code). Do NOT change what the code does.

Step 2 — Quality gate (the Definition of Done, from <artifact-dir>/profile.md `gate`).
Run each command IN ORDER, verbatim, and make it clean:
  <list the profile's gate commands explicitly, with their report filenames>

How you fix a failure depends on what caused it:
- Failure in code YOUR simplification changed — **revert that simplification.** A
  behavior-preserving change that breaks a check was not behavior-preserving, and
  editing until the check passes destroys the only signal that it went wrong.
- Failure that was already there before Step 1, or that Step 1 merely surfaced —
  fix it forward.

For each check, write <artifact-dir>/lint/<REPORT>.md: the exact command, final status
(pass/fail), and the tail of any output you had to fix. Re-run until every gate
command is green. If a warning must be suppressed, suppress it as narrowly as
possible and explain why in the report.

Heads-up on tests (from profile.md test_notes): <notes — required services,
umbrella/monorepo scope, slow tiers>. Ensure prerequisites are up before running.

Run the gate IN FULL — do not scope or sample it; it is the Definition of Done.
Where a command is slow, run it in the background rather than blocking on it, and
redirect its output to a file under $TMPDIR, reading back only the failing tail.
Never paste a full suite or dialyzer log into your return.

Return: what you simplified, **any simplification you reverted and which check
forced it**, the files Step 1 touched, and the final status of each gate command.
```

Step 1 is **unconditional** — `/simplify` is a built-in skill, so there is nothing
to detect and no skip path. If the return says the simplify step was skipped, that
is a bug in the run, not an expected outcome.

If the gate cannot be made green (e.g. a failure that traces to a design problem in
the plan), **stop the pipeline and report** — never commit a red build. This agent's
loop to green spends **no** iteration budget; only a later *re-spawn* of it does
(`references/correction-loop.md`).

---

## Phase 6 — Ship

### Adversarial PR Review agent
_Tools: Read, Grep, Glob, Bash (`git diff`, `gh`), Write — read-only **w.r.t.
source**, but it writes `<artifact-dir>/PR_REVIEW.md`._
Briefed to **find problems, not rubber-stamp**. Runs after the PR is opened. This
is the only check in the pipeline briefed to find what no checklist names.

```
You are the ADVERSARIAL PR-REVIEW phase. Work inside the worktree at <worktree>.
Your job is to FIND PROBLEMS in the change on this branch — not to approve it.
Assume there ARE bugs and go looking for them.

Read the diff (`git diff origin/<base>...HEAD` — the branch is committed by now, so
the three-dot form is the right one here), the changed files, and the tests. Read
<artifact-dir>/SPEC.md, <artifact-dir>/IMPLEMENTATION.md, and the binding rules (<summary>)
plus the security directives named in <artifact-dir>/profile.md.

Hunt across these lenses and actively try to break each:
- Correctness: edge cases, error paths, off-by-one, nil/empty/boundary inputs,
  concurrency, wrong assumptions. Name an input that breaks it.
- Security: injection, authz gaps, secret/PII exposure, unsafe deserialization,
  weakened TLS/crypto — check against the security directives in profile.md.
- Scope: anything built beyond the spec, or a spec condition not actually met.
- Tests: do they PROVE the behavior, or are they tautological / missing the
  important cases?
- Conventions: deviations from repo patterns.

Write <artifact-dir>/PR_REVIEW.md: findings grouped blocker / should-fix / nit, each
with file:line and a concrete "why this is wrong / how to trigger it." If a lens
genuinely turns up nothing, say so briefly — but default to skepticism. Do NOT
modify code. Return the blocker count.
```

If the review returns blockers, feed them back to the **coding agent** using the
Phase 5 correction brief above. A Phase 6 correction lands *after* `/simplify` and
the `lint/` reports were written, so it invalidates more than a Phase 5 one does —
which reports to refresh, why `/simplify` does not re-run, and what happens when
the budget runs out with blockers still open are all in
`references/correction-loop.md`.
