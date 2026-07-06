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
   both the profile and discovery.
5. **Record** the fully-resolved result to `.auto-dev/profile.md`. Every later
   phase reads that file rather than re-detecting.

## Profile schema

Each profile is a markdown file with one fenced ```yaml``` block the orchestrator
reads. **Commands are run verbatim** — never paraphrase or "improve" a command
string; if a command is wrong, fix the profile or the override, not the
invocation.

```yaml
stack: elixir                 # profile id
# Detection signals, checked in order; first file that exists wins the vote.
# `any` = present if ANY listed path exists. Higher-precedence profiles list
# more specific signals (see precedence rules below).
detect:
  any: ["mix.exs"]
# Dependency install / toolchain activation, run once in Phase 1 after worktree
# creation. Run in order; stop on first failure and report.
setup:
  - "mix deps.get"
# The quality gate: the ordered checks that must all be green in Phase 7.
# Each check maps to a lint/<report>.md artifact.
# kind is advisory (compile|format|lint|typecheck|test|build); `command` is
# what actually runs; `report` is the .auto-dev/lint/ filename.
gate:
  - { kind: compile,  command: "mix compile --warnings-as-errors", report: "COMPILE.md" }
  - { kind: format,   command: "mix format --check-formatted",     report: "FORMAT.md" }
  - { kind: lint,     command: "mix credo --strict",               report: "CREDO.md" }
  - { kind: typecheck, command: "mix dialyzer",                    report: "DIALYZER.md" }
  - { kind: test,     command: "mix test",                         report: "TEST.md" }
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
  staging: staging            # staging branch for the direct-merge step; omit to skip Phase 9
  prefix: feature             # branch-name prefix
ci: circleci                  # github-actions | circleci | gitlab | none
jira:
  states:                     # map pipeline milestones to this board's state names
    in_progress: "In Progress"
    in_review: "In Review"
    done: "Done"
```

Resolution order (last wins): **profile → runtime discovery → `.auto-dev.yml`**.
The fully-resolved values are written to `.auto-dev/profile.md`.
