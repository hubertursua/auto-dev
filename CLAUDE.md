# auto-dev — notes for agents working on this repo

This repo is the auto-dev plugin: an orchestration skill (`skills/auto-dev/`) and
its worker agent types (`agents/`). Most of it is Markdown that another agent
follows; the rest is helper scripts (`skills/auto-dev/scripts/`): `autodev.py`, the one
entry point, with its shared code in `scripts/lib/`, and the single-purpose
scripts it and the workers call. `README.md`
is the user-facing description of the pipeline, and it is the file most often
left stale.

## Before every push

Run all three from the repo root. CI (`.github/workflows/checks.yml`) runs the
same on Python 3.9 and 3.13, and a PR isn't ready until they pass.

```
ruff check .                              # lint (config: ruff.toml)
python3 tools/check-repo.py               # files agree with each other
python3 -m unittest discover -s tests     # helper-script tests
```

`tools/check-repo.py` catches drift a reviewer would miss: the model tables in
`SKILL.md` and `README.md` against `agents/*.md`, paths the docs name that don't
exist, a script the README doesn't mention, a script that isn't executable, and
`plugin.json` / `marketplace.json` disagreeing. When you add a sync rule below
that a script can check, add it there.

## Changing a helper script

- **Standard library only**, Python 3.9+ (`validate-config.py`, and
  `autodev.py init`, which reads YAML, may use PyYAML). Users run these with
  whatever `python3` they have.
- **Shared code goes in `scripts/lib/`**, imported by `autodev.py`. Modules
  there aren't run directly, so they need no shebang, no executable bit and no
  README mention. A new subcommand's docstring is its `--help`, as for a script.
- **Keep the CLI contract.** Each script's docstring is its `--help` and lists
  its exit codes; the skill's docs tell the orchestrator what each code means.
  If you change an exit code or an output line, update the docstring and every
  reference file that quotes it (`grep -rn "<script>.py" skills/`).
- **Add a test** for every fix or new behavior, in the file for what you
  changed: `tests/test_scripts.py` (the single-purpose scripts),
  `tests/test_autodev.py` (`autodev.py`'s other subcommands),
  `tests/test_work.py` (`brief`, `record`, `check-artifact`),
  `tests/test_next.py` (`next`, `pr publish`), `tests/test_parsers.py` (the
  artifact parsers) or `tests/test_eval_fixtures.py` (the eval fixtures;
  regenerate them with `AUTODEV_WRITE_FIXTURES=1 python3 -m unittest
  tests.test_eval_fixtures`), and check that it fails without your change. Tests run the script as a subprocess,
  the way the pipeline does, and build throwaway git repos in a temp dir. A
  command that calls `gh` is tested against `tests/fake_gh/gh`, which plays
  back the responses the test scripts; never call the real GitHub from a test.
- **Fail safe.** "Could not run" is exit 2, never a pass. Never leave the user's
  tree changed (see how `mutate.py` backs up and restores).
- Keep the file executable and its `#!/usr/bin/env python3` line.

## Changing the skill's Markdown

- `SKILL.md` is the spine the orchestrator always holds; keep detail in
  `references/` and point to it. A worker's instructions are its agent file
  (`agents/<name>.md`), never a reference file: the orchestrator doesn't read
  them, `autodev.py brief` only fills their `{{slots}}`. Artifact templates and
  the rubric live once, in `skills/auto-dev/templates/`. Say each rule in one place and link to it,
  rather than repeating it (a repeated rule drifts).
- After editing a rule, grep for other places that state it
  (`grep -rn "<key phrase>" skills/ agents/ README.md`) and make them agree.
- Behavior changes need matching eval expectations (`skills/auto-dev/evals/`).
  The full eval suite is slow and needs a GitHub-hosted fixture repo, so PRs
  usually don't run it. Say so in the PR's Testing section.

## Keep auto-dev language-agnostic

auto-dev has to work the same in a Python, Node, Go or Elixir repo. It ships no
stack profile: a run learns the repo's stack from the profile saved on the
user's machine, or from the `profiler` worker's research, confirmed by the user
(`skills/auto-dev/references/profiles.md`). Nothing in this repo may assume a
stack. Agents copy what they read, so a rule or example written for one language
becomes a default for every repo.

- **Stack-specific facts live in the run's profile.** Commands, tool names, file
  layouts and test-framework syntax are researched per repo, never written into
  this repo. `SKILL.md`, `references/`, `agents/` and the evals describe the step
  in neutral terms ("the profile's test command", "the framework's skip marker")
  and read the specifics from the run's `profile.md`. Don't add a shipped
  profile back; teach the profiler's brief what to look for instead.
- **A rule for one stack goes through the profile.** If a step needs a tool
  only one ecosystem has, add an optional profile key the step reads, with a
  stack-neutral fallback when it's absent. `symbol_lookup` is the model: the
  `lookup` worker's agent file uses `{{symbol_lookup}}`, which `brief` fills
  from `profile.md`'s Symbol lookup line and which falls back to `grep -n`, and
  the profiler fills it in only when the repo's ecosystem has a code-index tool
  on PATH.
- **Examples are in TypeScript, and say so.** An example that names a command,
  path or code uses TypeScript, a language most readers know, and is labeled
  "example in TypeScript" (or "Filled-in rows are an example in TypeScript." above
  a template). The label goes outside a template block, so an agent filling the
  template doesn't copy it; in a `templates/` file it goes in the first-line
  comment, which agents are told not to copy. Where no example is needed, use a neutral placeholder
  (`<test command>`, `src/<module>`). No other language is allowed.
- **Scripts stay language-blind.** A helper script takes paths and commands as
  input and never hardcodes one stack's test runner or syntax. Where it has to
  recognize code (as `check-tests.py` does for skips and assertions), the
  patterns cover several stacks, with a test for each one you add.
- **Evals and fixtures don't assume a stack.** A setup step says what to plant
  ("mark a test as skipped"), not one framework's syntax; ledger fixtures use
  placeholders such as `<profile>`; trigger queries span several languages.

Before pushing, grep what you changed for one stack's terms
(`grep -rn -i -E "elixir|exunit|mix |credo|dialyzer|\.exs?\b" skills/ agents/`,
and the same for any other stack your change mentions). Each hit should be scoped
to that stack or one example among several.

## Every PR keeps README.md current

If a PR changes how the pipeline behaves, update `README.md` **in the same PR**.
Don't leave it for a follow-up. Before you open or update a PR, compare the diff
against this list and edit each README section it touches:

| If the PR changes…                                         | Update in README.md |
| ---------------------------------------------------------- | ------------------- |
| a phase, its order, or which worker runs it                | *Agent hierarchy* diagram, *What it does* table |
| how the build is verified (spec format, acceptance checks, verifier, audit, mutation) | *How the build is verified* |
| the size check or the number of worker roles               | *Size check* |
| session boundaries or the context budget                   | *Three sessions, not one* |
| the code review panel, security review or rubric           | *Review before the PR* |
| a gate, a conditional pause, Jira, CI, or the merge method | *Human gates & integrations* |
| profile research, saved profiles, permissions guidance, or a `.auto-dev.yml` key | *Stack profiles* |
| a script in `skills/auto-dev/scripts/`, or a new tool or dependency | *Dependencies* |
| an agent's `model:` / `effort:`, or a new or renamed agent | *Models and effort* table |
| a file in `.auto-dev/`                                     | *The `.auto-dev/` scratch directory* table |
| a stop condition or the iteration budget                   | *Safety* |
| the repo's folders                                         | *Repository layout* |
| install steps or the plugin/marketplace name               | *Install* |

A pure wording fix inside `references/` that changes no behavior needs no README
change. If you're unsure, check: would someone reading only the README now be
wrong about something? If yes, fix the README.

## Keep these in sync too

- **Models.** The worker table in `SKILL.md` (_Tool permissions & models_), the
  table in `README.md` (_Models and effort_), and each `agents/<name>.md`
  frontmatter must agree.
- **Version.** Bump `.claude-plugin/plugin.json` as _Branches, commits and
  PRs_ says. An *Upgrading from X.Y* section in the README (newest first) says
  what changed and whether a run in flight can resume on the new version.
- **Descriptions.** `plugin.json` and `marketplace.json` carry the same plugin
  description.
- **Evals.** When behavior changes, update the expectations in
  `skills/auto-dev/evals/evals.json` that describe it. A `state.json` fixture in
  `evals/files/` sits beside the `WORK_LOG.md` generated from it.
  `tests/test_eval_fixtures.py` checks that each pair agrees, replays S1 to
  check that the resume-s2 fixtures (with its `HANDOFF.md`) are what S1 writes
  now, and runs `resume` on the resume-s2 and old-version fixtures (and `next`
  on resume-s2). When the state or the handoff changes, regenerate the resume-s2
  fixtures with `AUTODEV_WRITE_FIXTURES=1 python3 -m unittest
  tests.test_eval_fixtures`, never by hand.
- **Briefs and results.** Each `{{slot}}` in an agent file is listed as AUTO,
  CALLER or OPTIONAL in `skills/auto-dev/scripts/lib/briefs.py`, and each agent
  file's `auto-dev-result` block lists exactly the `next` tokens `RESULTS` gives
  it there. `tools/check-repo.py` checks both, and that every template a script
  parses or an agent names exists.

## Branches, commits and PRs

Earlier PRs in this repo predate these rules, so don't copy their style; follow
this section. CI (`.github/workflows/pr-conventions.yml`) checks the branch name
and PR title. Run the same check locally before opening a PR:

```
python3 tools/check-pr.py --branch "$(git branch --show-current)" --title "<PR title>"
```

**Types.** One list is used for both branch names and PR titles:

| Type       | For                                                   | Version bump |
| ---------- | ----------------------------------------------------- | ------------ |
| `feat`     | new pipeline behavior, worker, artifact, script, key  | minor        |
| `fix`      | a bug in a script or a wrong or contradictory rule    | patch        |
| `docs`     | README, CLAUDE.md, or wording that changes no behavior | none        |
| `refactor` | restructuring that changes no behavior                | none         |
| `test`     | tests or evals only                                   | none         |
| `chore`    | metadata, housekeeping                                | none         |
| `ci`       | workflows, lint config, `tools/`                      | none         |

A breaking change (a run in flight can't resume on the new version, or a
`.auto-dev.yml` key or artifact is removed or renamed) adds `!` and is a major
bump.

**Branches: `<type>/<short-kebab-description>`.** Lowercase, words joined by
single hyphens, no ticket numbers or dates: `fix/mutate-mtime`,
`feat/acceptance-tester`, `docs/readme-refresh`. Always branch from an
up-to-date `main`, and never commit to `main` directly. The one exception:
Claude Code cloud sessions are assigned a `claude/…` branch and can't choose
another, so the check accepts `claude/<anything>`; the PR title must still
follow the rules.

**PR titles: `<type>: <summary>`.** `<type>!: <summary>` for a breaking
change. The summary is imperative, lowercase after the colon, no trailing
period, 72 characters at most in total: `fix: give each mutant its own mtime`.
A PR that releases a version names it: `feat: verify builds by running
held-out checks (3.4.0)`.

**Always squash merge.** Every PR lands on `main` as exactly one commit whose
subject is the PR title, so the title is what the history shows. Never use a
merge commit or rebase merge, and never merge with `--admin`. With `gh`:
`gh pr merge <n> --squash --delete-branch`. Edit the squash message so its
body is the PR's Summary, not a list of the branch's commits.

**One topic per PR.** Unrelated fixes go in separate PRs, even small ones,
because a squash merge can't be partly reverted.

**PR bodies** follow `.github/pull_request_template.md`: *Summary* (what and
why), *Testing* (what you ran and saw, before and after for a fix, and what was
not tested), *Docs*, and *Not included* when something is left for later.

**Commits on the branch** are squashed away, so they only need to make sense
during review: a short imperative subject, one logical change each. Fix review
findings in new commits; don't force-push over a branch someone is reviewing.
Bring in `main` by merging it, not rebasing, once a review has started.

**Versioning.** The version in `.claude-plugin/plugin.json` follows the bump in
the types table, in the same PR. A minor or major bump also adds an
*Upgrading from X.Y* section to the README.

## Writing style

Plain, direct sentences. Say what the pipeline does, and why when it isn't
obvious. Reference files by their repo path (`skills/auto-dev/references/…`)
in the README, and by `references/…` inside `SKILL.md`.
