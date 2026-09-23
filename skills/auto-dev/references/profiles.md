# Stack profiles — schema, detection, and overrides

A **stack profile** captures everything the pipeline needs to know about *how a
given ecosystem builds, verifies, and ships*: how to detect it, how to install
dependencies, and the exact quality-gate commands that constitute "done." Profiles
are what make the pipeline language/framework-agnostic — adding support for a new
stack is dropping a new `profiles/<stack>.md` file in, no changes to `SKILL.md`.

Currently shipped: **`elixir.md`** and a generic **`default.md`** fallback. More
stacks are added by following the schema below.

## How Phase 1 uses profiles

1. **Detect** the stack by matching `detect` signals against the repo (see
   precedence below).
2. **Load** the matching `profiles/<stack>.md`; if none matches, load
   `default.md` and fill gaps by runtime discovery (read CI config, Makefile,
   mix.exs/package.json scripts, etc.).
3. **Merge** in anything discovered from the repo's own docs/CI that the profile
   didn't specify.
4. **Apply** the repo-local `.auto-dev.yml` override (if present) — it wins over
   both the profile and discovery. **Validate it first:**
   ```bash
   python3 skills/auto-dev/scripts/validate-config.py <repo>/.auto-dev.yml
   ```
   An unrecognized key is silently ignored otherwise, so a typo reads as "the
   override did nothing" — the validator names the key and suggests the one it
   probably meant. Exit `1` is a stop-and-report; exit `2` means validation could not
   run (no PyYAML), which is not a pass — say so and apply the file with care.
5. **Drop any gate check whose tool isn't actually there.** A profile lists the
   conventional gate for its ecosystem; a given repo may not use all of it. Keep a
   check only where its tool is genuinely available — the dependency is declared,
   or its config file exists — and otherwise drop it and **record the omission**
   in `profile.md`. This is a rule for every stack, not just the ones that
   document it (Elixir's Credo and Dialyzer are the usual case). Never keep a
   check that cannot run: Phase 5 would never go green, and the pipeline would
   stop on a tool the project never adopted.
6. **Refuse an empty gate.** Once unavailable checks are dropped, the resolved
   `gate` must still contain at least one command that runs the project's tests. A
   gate with nothing in it makes Phase 5 pass by having nothing to check, and the
   change then rides through every remaining gate unverified — the one failure mode
   this pipeline cannot detect downstream. If neither the profile nor discovery can
   find a way to run the tests, **stop and report**: it is a setup problem the user
   fixes in one line of `.auto-dev.yml`, and guessing is worse than asking.
7. **Record** the fully-resolved result to `.auto-dev/profile.md`. Every later
   phase reads that file rather than re-detecting.

## Profile schema

Each profile is a markdown file with one fenced ```yaml``` block the orchestrator
reads. **Commands are run verbatim** — never paraphrase or "improve" a command
string; if a command is wrong, fix the profile or the override, not the
invocation.

```yaml
stack: elixir                 # profile id
# Detection signals. `any` = matches if ANY listed path exists; `all` = every
# listed path must. When more than one profile matches, the most specific wins —
# resolved by "Detection precedence" below, not by the order signals appear here.
detect:
  any: ["mix.exs"]
# Dependency install / toolchain activation, run once in Phase 1 after worktree
# creation. Run in order; stop on first failure and report.
setup:
  - "mix deps.get"
# The quality gate: the ordered checks that must all be green in Phase 5.
# Each check maps to a lint/<report>.md artifact.
# kind is advisory (compile|format|lint|typecheck|test|build); `command` is
# what actually runs; `report` is the .auto-dev/lint/ filename.
gate:
  - { kind: compile,  command: "mix compile --warnings-as-errors", report: "COMPILE.md" }
  - { kind: format,   command: "mix format --check-formatted",     report: "FORMAT.md" }
  - { kind: lint,     command: "mix credo --strict",               report: "CREDO.md" }
  - { kind: typecheck, command: "mix dialyzer",                    report: "DIALYZER.md" }
  - { kind: test,     command: "mix test",                         report: "TEST.md" }
# Optional: gitignored files copied from the main checkout into each new worktree
# before `setup` runs — env/config a suite needs but git does not track.
worktree_files: [".env", ".env.test"]
# Optional: how tests are scoped (services required, monorepo/umbrella, slow tiers)
test_notes: "…"
```

Fields:

- **`stack`** (required) — the profile id, matches the filename.
- **`detect`** (required) — signals used to identify the stack. `any:` is a list
  of paths; the stack matches if any exist. May also use `all:` (every path must
  exist) for disambiguation.
- **`setup`** (required) — ordered install/activation commands.
- **`gate`** (required) — the ordered quality-gate checks. Each is
  `{ kind, command, report }`. The pipeline is only "green" when every `command`
  exits clean.
- **`worktree_files`** (optional) — gitignored paths seeded into every new worktree
  before `setup`. A fresh worktree has no `.env`, and the resulting failure looks
  like broken code rather than missing config.
- **`test_notes`** (optional) — hints passed into the coding/cleanup briefs so
  tests run at the right scope.

## Detection precedence

When multiple profiles could match:

1. **Most specific wins.** A profile requiring `all:` of several signals
   outranks one matching a single common file. (e.g. a hypothetical
   `node-typescript` requiring both `package.json` **and** `tsconfig.json`
   outranks a bare `node`.)
2. **Lockfiles/manifests over incidental files.** `mix.exs`, `package.json`,
   `go.mod`, `pyproject.toml` are strong signals; a stray `.ts` file is not.
3. **Tie → ask, don't guess.** If two profiles match with equal specificity and
   it's not a known multi-stack case, surface it to the user rather than pick
   silently.

## Monorepos, umbrellas, and multi-stack repos

- **Elixir umbrella** (`apps/*/mix.exs`): run `mix` from the umbrella root; the
  gate commands operate across apps. Record the umbrella layout in `profile.md`
  and pass it as a test note so the coder/cleanup run the right app's suite.
- **Polyglot monorepo** (e.g. a JS frontend + Python backend): scope to the
  package the task actually touches. Detect the sub-package from the task/ticket
  and the files in play, record the chosen package and its own gate in
  `profile.md`, and note in `WORK_LOG.md` that other packages were out of scope.
  If the task genuinely spans packages, that's a decomposition signal (see the
  task-orchestration layer in `SKILL.md`).
- When scoping is ambiguous, surface it rather than guess.

## Repo-local override — `.auto-dev.yml`

A project can commit a `.auto-dev.yml` at its repo root to override anything the
profile or discovery got wrong, or to declare project-specific conventions. It is
NOT scratch and is NOT excluded from git. Keys mirror the profile plus repo/CI/Jira
settings; anything present overrides the resolved value:

```yaml
# .auto-dev.yml  (committed at repo root; all keys optional)
stack: elixir                 # force a profile instead of auto-detecting
setup: ["mix deps.get", "mix compile"]
gate:
  - { kind: lint, command: "mix credo --strict --all", report: "CREDO.md" }
branches:
  base: develop               # base branch to cut from and target with the PR
  staging: staging            # staging branch for the direct-merge step; omit to skip gate 6b
  prefix: feature             # branch-name prefix
ci: circleci                  # github-actions | circleci | gitlab | none
ci_timeout_minutes: 30        # bound on CI watching before it reports and holds
iteration_budget: 4           # revise rounds per task (per sub-task on a multi-PR run)
worktree_files: [".env"]      # gitignored files to seed every new worktree with
security_docs:                # the security directives every worker must obey;
  - "SECURITY.md"             # first source Phase 1 checks, ahead of repo defaults
  - "docs/security/authz.md"
pr_review:
  inline_comments: false      # post Phase 6a findings as inline PR comments
gates:
  post_plan: true             # force the Phase 3 post-plan gate on for this repo
jira:
  states:                     # map pipeline milestones to this board's state names
    in_progress: "In Progress"
    in_review: "In Review"
    done: "Done"
```

Resolution order (last wins): **profile → runtime discovery → `.auto-dev.yml`**.
The fully-resolved values are written to `.auto-dev/profile.md`.

`iteration_budget`, `ci_timeout_minutes`, `security_docs`, `pr_review`, and
`gates.post_plan` are not stack settings, but they resolve the same way and land in
the same `profile.md` — see `references/correction-loop.md`,
`references/gates-and-jira.md`, and Phase 1 step 4 in `SKILL.md`.
