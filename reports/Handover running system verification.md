# Handover: verify the build against the running system

This is a handover for an agent that will change auto-dev (this repo). It says
what was researched, what was concluded, and what to build, in order. Read
`CLAUDE.md` first: its rules (language-agnostic, README kept current, spawn
budget, tests, evals, one topic per PR) apply to every item here.

## The problem in one paragraph

The maintainer's concern: auto-dev's verification leans on tests written by
agents, at the unit or integration level, and never checks the real, running
system. The research says the concern is half right. auto-dev's handling of
agent-written checks is stricter than anything the surveyed pipelines publish.
What it lacks is any step where something other than the coder **starts the
software and uses it**, and any statement to the reviewer of which conditions
were never checked at that level. The work below closes that gap without
adding stack knowledge to the repo and without adding a worker spawn to the
happy path.

## Where the research is

All of it is on the branch `claude/friendly-mayer-lavuop`.

| File | What it is |
| --- | --- |
| `reports/Software factory verification primary sources.md` | **The report to rely on.** Every claim re-checked against the primary pages, each with a grade (verified, snippet, secondhand, unverified). Starts with a table of what the re-check corrected. |
| `reports/Software factory verification practices.md` | The first-pass report, written from search snippets. Superseded; keep only for history. |
| `research_notes/Software factory verification primary sources/` | Four notes files with the exact quotes, dates and corrections behind the final report. |
| `research_notes/Software factory verification practices/` | The first-pass notes. Several details in them were later corrected; don't quote from them. |

These files are research output, not part of the plugin. Before a PR into
`main`, ask the maintainer whether they should stay in the repo; by default
leave them out of the PR.

## What the research found

Short version; the report has the sources and caveats.

- **Passing tests is weak proof.** METR found roughly half of 296 test-passing
  agent PRs would not be merged by maintainers (single-attempt patches, no
  feedback loop). ImpossibleBench found models special-case or edit tests when
  the honest route is blocked; read-only tests stop edits but not
  special-casing.
- **Enterprise in-house agents** (Stripe, Google, Spotify, Atlassian) rely on
  the existing human-owned suite, the real CI build and a human reviewer. None
  publishes a rule against agents editing tests or a held-out check. Spotify
  removed its LLM judge, and reports an automatically merged change that
  passed its checks and failed in production.
- **Commercial agents** (Devin, Cursor, Codex, Copilot, Jules, Replit, Warp)
  can boot the app and return screenshots or recordings, but the pass is
  narrow: Devin's docs call it "a quick sanity check" of one primary flow.
  Warp's verifier is the clearest model of an honest verdict: it names the
  tested commit, marks each criterion passed, failed or unverified, never
  infers success from missing proof, and may not edit the branch.
- **Labs.** Anthropic's harness has a separate evaluator use the running app
  through a browser; it caught wiring bugs (a route shadowed by another route,
  a handler with a wrong condition) that unit tests with test doubles pass
  over. OpenAI makes the app bootable per worktree and lets the agent drive it
  and read its logs, but describes no independent check. StrongDM judges by
  end-to-end scenarios "often stored outside the codebase".
- **Where auto-dev is ahead:** checks proven to fail on the old code and shown
  to the reviewer, checks guarded by a scripted audit, mutation testing.
- **Where auto-dev is behind:** nothing observes the running system; the
  reviewer gets text only; there is no per-condition "not verified at this
  level" state; the coder can read every committed check (a smaller gap than
  it first looked).

Not verified, and nothing below rests on them: Factory's Missions, Replit's
"Potemkin interfaces" post, Uber's agent self-validation, Kent Beck's
guidance, and a report of a lights-off factory being shut down.

## What auto-dev already has that this builds on

Check these before designing anything, so the change extends what exists:

- `skills/auto-dev/templates/PLAN.md`: each condition has a `Verify by:` line
  (`unit | integration | end-to-end | manual`).
- `skills/auto-dev/templates/MANIFEST.md`: each check has a `Level`, written
  as `<level> (below <Verify by>: <why>)` when the repo's tests can't reach
  the level the condition asks for.
- `agents/verifier.md`: a Strong verdict already requires that no check's
  Level is below the condition's Verify by; the verifier runs a probe of its
  own per condition and writes the expected outcome first.
- `skills/auto-dev/references/profiles.md`, `agents/profiler.md`,
  `skills/auto-dev/scripts/lib/briefs.py`, `lib/cmd_init.py`,
  `scripts/validate-config.py`: how the optional `symbol_lookup` profile key
  is researched, validated and filled into a brief, with a stack-neutral
  fallback. This is the model for any new profile key.
- `skills/auto-dev/scripts/mutate.py`: how a script changes the user's tree
  and always restores it. This is the model for a script that starts and stops
  a process.
- `skills/auto-dev/scripts/check-fresh.py`: the tree-hash stamp on every
  verdict.
- `skills/auto-dev/templates/SPEC_EVAL.md` and `templates/pr-body.md`: where
  per-condition evidence and manual checks are reported.

## What to build, in order

Each numbered item is one topic and so one PR (`CLAUDE.md`, *One topic per
PR*). Items 1 and 2 are the substance; ship 2 first, because it needs no
profile work and no running app.

### 1. Run recipe in the profile, and one running-system pass in the verifier

The main value. Ship after item 2.

- **Profile.** Add an optional block of keys, modelled on `symbol_lookup`: a
  start command, a readiness check (a command that exits zero when the app
  answers), a stop command, an optional seed or sign-in step, and a line
  saying how the app is exercised (requests to an address, the built command
  line, or a browser-automation tool found on the machine). The profiler
  researches it and the user confirms it with the rest of the profile. Absent
  by default; the repo ships no stack's values.
- **Script.** A helper (a new `autodev.py` subcommand) wraps start, wait for
  ready, a time cap and stop, and always stops what it started, including on
  failure or timeout. "Could not start" is exit 2, never a pass.
- **Verifier.** One pass at the end, inside the existing verifier spawn: for
  each condition about externally visible behavior, write the expected outcome
  first, exercise the app through the interface a user or caller has (never by
  reaching into internals), and save the transcript as that condition's
  evidence. Test only what the conditions name. Keep repeated steps such as
  sign-in in the recipe, not improvised.
- **No recipe.** The pass is reported as not run, with the reason. It is never
  counted as a pass, and it never blocks the run.
- **Constraint.** No new spawn on the happy path; `LeanTest` in
  `tests/test_next.py` pins the counts and must not change.

### 2. Make the level part of the verdict

Ship first.

- A condition whose `Verify by` is end-to-end, or that describes behavior a
  user or caller of the running system sees, gets an explicit state in
  `SPEC_EVAL.md` and the PR body: verified against the running system, or
  **not verified against the running system** with the reason (no recipe, app
  failed to start, no tool to drive it).
- Once item 1 exists: with a recipe, such a condition cannot be Strong without
  a running-system observation.
- The plan critic flags a user-visible condition whose only planned check is
  at the unit level, and an acceptance check that asserts an implementation
  detail the condition does not state.
- The rule to encode, from Warp: don't infer success from missing proof.
- Add an eval: a fixture whose app fails to start, expecting the report to
  name the blocker and leave the condition unverified.

### 3. Show the reviewer what was observed, captured by a script

Depends on item 1.

- The PR body gains, per condition, a short "verified against the running
  app" part: the command or request, what came back, and a screenshot where a
  browser tool produced one. Beside the manual checks, a plain "not verified"
  list.
- The evidence file is written by the wrapper script that ran the command,
  never typed by the verifier. A script checks that each cited evidence file
  exists, is non-empty and carries the tree hash.
- When the running pass finds a fault, the fix routes through the acceptance
  tester, so the case lands as a committed, fail-first check.

### 4. Hold one check back from the coder (experiment only)

Evidence is mixed, so trial it in the evals before it becomes a pipeline step.

- The acceptance tester writes one extra scenario per condition, also proven
  to fail on the old code, kept in `.auto-dev/` and first run by the verifier.
- A failure goes back to the coder in words, not as the check itself.
- Don't ship this to the default path without eval results that show it
  catches special-casing the probes miss.

### 5. Smaller extensions to the existing checks

Independent of the items above; each is small.

- A small mutation cap on standard-risk runs, limited to lines a condition
  depends on (today mutation runs on high-risk runs only).
- Run the verifier's probes against the old code as well as the new, to flag
  behavior changes no condition asked for.
- An optional profile key naming the repo's property-testing library, absent
  by default, so the tester can write a property for a condition that states
  an invariant.

### 6. Do not build

- An LLM judge as a pass/fail gate. Spotify removed its own; auto-dev's
  scripted test-integrity audit is the durable form.
- Clones of third-party services. A condition that needs an unreachable
  service becomes a manual check naming the environment it needs.
- Formal verification or deterministic simulation.
- Removing or weakening the human gates.

## Rules from CLAUDE.md that these changes will hit

- **Language-agnostic.** No stack's command, tool or path in `SKILL.md`,
  `references/`, `agents/` or the evals. Recipe values live in the run's
  profile. Examples are in TypeScript and labelled.
- **Spawn budget.** The happy path stays at 4 spawns to first push and 6 to
  ready-for-review.
- **README in the same PR.** Items 1–3 touch *How the build is verified*,
  *Stack profiles*, *Dependencies* (a new subcommand or script) and *The
  `.auto-dev/` scratch directory* (new evidence files).
- **Briefs and results.** A new `{{slot}}` in an agent file is listed in
  `skills/auto-dev/scripts/lib/briefs.py`; `tools/check-repo.py` checks it.
- **Scripts.** Standard library only, Python 3.9+, fail safe, a test for every
  behavior that fails without the change.
- **Evals.** Behavior changes need matching expectations in
  `skills/auto-dev/evals/evals.json`; regenerate fixtures, never edit by hand.
- **Version.** Each of items 1–5 is a `feat` (minor bump, plus an *Upgrading
  from X.Y* section in `UPGRADING.md`). The current version is 5.1.0. If the
  items are gathered in a release branch, follow the release-branch rule
  instead.
- **Before every push:** `ruff check .`, `python3 tools/check-repo.py`,
  `python3 tools/run-tests.py`, and the identity check.
- **Before a PR:** a fresh agent reviews the diff; the PR follows
  `.github/pull_request_template.md`.

## A separate bug found on the way

`skills/auto-dev/templates/pr-body.md` line 11 tells the PR's reviewer "The
code was first written without those tests in view; then they were added
back". The README and the agent files say the opposite: the acceptance checks
are committed first and the coder builds against them in the open. Every PR
auto-dev writes would describe the process wrongly. This is a `fix` and its
own PR; check `skills/auto-dev/scripts/lib/cmd_pr.py` and the tests for the
same sentence before changing it.

## Open questions for the maintainer

- Should the research notes and reports stay in the repo, move elsewhere, or
  be dropped from the branch before a PR?
- One PR per item into `main`, or a release branch gathering items 1–3?
- For item 1, which ways of exercising the app are in scope first: requests
  and command-line calls only, or a browser tool too when one is available?

## How to measure whether it worked

No source measures how many defects a running-system pass catches that
tests-first checks miss, or how often an agent reports "verified" when it
could not look. auto-dev can measure both in its evals: plant wiring faults
that unit-level checks pass (a route registered in the wrong order, a handler
bound to the wrong event) in a fixture, then count how many the running pass
catches, and how many conditions it reports as verified when the app never
started. The second count should be zero.
