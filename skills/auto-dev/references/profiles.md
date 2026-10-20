# Stack profiles — research, confirmation, saving, and overrides

A **stack profile** tells the pipeline how a repo installs its dependencies and
which quality-gate commands constitute "done."

auto-dev ships **no** stack profile. Each repo gets its own: the first run
researches it (the `auto-dev:profiler` worker), the user confirms it, and the
user may save it on their machine, outside every checkout, where later runs from
any clone or worktree of the same repo find it.

## Contents

- **Profile schema** — the keys a profile holds and what each means.
- **Saved profiles** — where they live and how a run finds them.
- **Permissions** — what the user allows so a run reads and saves the profile
  without prompts, and the guidance to show them.
- **Monorepos, umbrellas, and multi-stack repos** — scoping the quality gate to
  the right package.
- **Repo-local override — `.auto-dev.yml`** — every key a project can override.

How a run finds, researches and confirms the profile is `references/S1-plan.md`,
step 4. `autodev.py init` then validates it, applies `.auto-dev.yml` over it,
refuses a quality gate with no test command, and writes `.auto-dev/profile.md`.

## Profile schema

A profile is plain YAML: a subset of the `.auto-dev.yml` keys, the ones that
describe how the stack installs and checks itself. Repo policy (branches, budget,
gates, Jira) stays in `.auto-dev.yml` and never goes into a saved profile;
`validate-config.py --profile` refuses it. **Commands are run verbatim** — never
paraphrase or "improve" a command string; if a command is wrong, fix the profile
or the override, not the invocation.

Example in TypeScript:

```yaml
stack: typescript             # the stack's name, recorded in profile.md
# Dependency install / toolchain activation, run once in Phase 1 after worktree
# creation. Run in order; stop on first failure and report.
setup:
  - "npm ci"
# The quality gate: the ordered checks that must all be green in Phase 5.
# Each check maps to a lint/<report>.md artifact.
# kind is advisory (compile|format|lint|typecheck|test|build); `command` is
# what actually runs; `report` is the .auto-dev/lint/ filename.
gate:
  - { kind: typecheck, command: "npx tsc --noEmit",       report: "TYPECHECK.md" }
  - { kind: lint,      command: "npx eslint .",           report: "LINT.md" }
  - { kind: format,    command: "npx prettier --check .", report: "FORMAT.md" }
  - { kind: test,      command: "npm test",               report: "TEST.md" }
# Optional: gitignored files copied from the main checkout into each new worktree
# before `setup` runs — env/config a suite needs but git does not track.
worktree_files: [".env", ".env.test"]
# Optional: how tests are scoped (services required, monorepo layout, slow tiers)
test_notes: "…"
# Optional: a code-index tool for finding a symbol's definition and callers.
# <symbol> is replaced by the name looked up. Omit it to use `grep -n`.
symbol_lookup:
  definition: "<index-tool> definition <symbol>"
  references: "<index-tool> references <symbol>"
# Optional: the CI provider Phase 6 watches (github-actions|circleci|gitlab|none).
ci: github-actions
```

Fields:

- **`stack`** (optional) — a short name for the stack, recorded in `profile.md`.
  It selects nothing.
- **`setup`** (required) — ordered install/activation commands; may be `[]`.
- **`gate`** (required) — the ordered quality-gate checks. Each is
  `{ kind, command, report }`, and one must be `kind: test`. The pipeline is
  only "green" when every `command` exits clean.
- **`worktree_files`** (optional) — gitignored paths seeded into every new worktree
  before `setup`. A fresh worktree has no `.env`, and the resulting failure looks
  like broken code rather than missing config.
- **`test_notes`** (optional) — hints passed into the coding/cleanup briefs so
  tests run at the right scope.
- **`symbol_lookup`** (optional) — commands the `lookup` worker uses instead
  of grep to find where a module, function or class is defined (`definition`) and
  used (`references`). Each must contain `<symbol>`. Phase 1 keeps them only if
  the tool is on PATH; otherwise, or when the profile has none, `profile.md`
  records `grep -n`. A code index answers with less noise than grep, which
  keeps the worker's answers short.
- **`ci`** (optional) — the CI provider. When absent, Phase 1 reads the repo's CI
  config to find it.

## Saved profiles

A saved profile is one YAML file per repo, on the user's machine, named after the
repo's `origin` remote so every clone and worktree of that repo maps to the same
file:

```
<profiles-dir>/<host>/<owner>/<repo>.yml
```

`git@github.com:Acme/Web-App.git` and `https://github.com/acme/web-app` both map
to `~/.config/auto-dev/profiles/github.com/acme/web-app.yml`: lowercased, `.git`
dropped, and a nested path (a GitLab subgroup) keeps every segment.
`<profiles-dir>` is `$AUTO_DEV_PROFILES_DIR` if set, else
`$XDG_CONFIG_HOME/auto-dev/profiles`, else `~/.config/auto-dev/profiles`.
`scripts/profile-path.py` applies this convention; always use it rather than
building the path by hand. A fork has its own `origin`, so it gets its own file.

The file is the user's: they can edit it, or delete it to have the next run
research the profile again. Its commands run verbatim, like a profile's, so it
belongs only in the user's own home directory, never in a repo. It is kept out of
`~/.claude/`, which Claude Code protects: every write there prompts, whatever the
allow rules say.

## Permissions

The saved profile lives outside the working directory, so Claude Code asks
before reading or writing it, and the Bash sandbox (when the user has turned it
on) blocks writes outside the working directory. A run also runs the helper
scripts and the profile's commands through Bash, and each new command can
prompt. Show the user the guidance below at the profile confirmation, and again
whenever a read or write of the saved profile is denied. Fill in the real
`<profiles-dir>`, `<skill-dir>` and commands. **Never edit the user's settings
files yourself**: the user decides what to allow.

Guidance to show (adapt the paths):

> **Let auto-dev read and save this repo's profile without asking.** Add these
> rules to `~/.claude/settings.json` (your user settings, which apply in every
> repo), or run `/permissions` and add them there:
>
> ```json
> {
>   "permissions": {
>     "allow": [
>       "Read(~/.config/auto-dev/**)",
>       "Edit(~/.config/auto-dev/**)"
>     ]
>   }
> }
> ```
>
> - `Edit(...)` also covers creating the file; there is no separate `Write` rule.
> - If the profiles directory is not under `~/.config/auto-dev` (you set
>   `AUTO_DEV_PROFILES_DIR` or `XDG_CONFIG_HOME`), use that path: `~/…` for a
>   path in your home directory, `//…` for any other absolute path (for example
>   `Read(//opt/auto-dev/profiles/**)`).
> - For one session only, start Claude Code with
>   `claude --add-dir ~/.config/auto-dev` (or run `/add-dir ~/.config/auto-dev`).
>   Reads there stop prompting; saving still asks unless you accept edits.
> - If you use the Bash sandbox, also add
>   `"sandbox": { "filesystem": { "allowWrite": ["~/.config/auto-dev"] } }`, so a
>   shell command can write there too.
>
> **Let the run's commands go without asking.** Add rules for the helper
> scripts and for this repo's setup and quality-gate commands, in the main
> checkout's `.claude/settings.local.json` (not committed; it applies only to
> this repo):
>
> ```json
> {
>   "permissions": {
>     "allow": [
>       "Bash(python3 <skill-dir>/scripts/*)",
>       "Bash(npm ci *)",
>       "Bash(npm test *)"
>     ]
>   }
> }
> ```
>
> A rule matches the command's text, so use the commands exactly as the profile
> lists them; a trailing ` *` also allows extra arguments. Allow only commands
> you trust to run unattended.

The commands in the second snippet are an example in TypeScript; list this run's
`setup` and `gate` commands there. Rules in `.claude/settings.json` or
`.claude/settings.local.json` apply in the directory Claude Code was started
in, which is the main checkout, also when the run works in a worktree.

## Monorepos, umbrellas, and multi-stack repos

- **Workspaces** (example in TypeScript: `workspaces` in the root
  `package.json`, or `pnpm-workspace.yaml`): run the `gate` in the package the
  task touches (`npm test -w <package>`). Record the layout in `profile.md` and
  pass it as a test note so the coder/cleanup run the right package's suite. The
  profiler describes the repo's layout in the profile's `test_notes`; which
  package a task touches is the run's call, so it goes in `profile.md`, never in
  the saved profile.
- **Polyglot monorepo** (e.g. a JS frontend + Python backend): scope to the
  package the task actually touches. Detect the sub-package from the task/ticket
  and the files in play, and use that package's own `gate`; record with
  `autodev.py note` that the other packages were out of scope.
  If the task genuinely spans packages, that's a sign it is OVERSIZED (the Define
  agent's size check).
- When scoping is ambiguous, surface it rather than guess.

## Repo-local override — `.auto-dev.yml`

A project can commit a `.auto-dev.yml` at its repo root to override anything the
profile got wrong, or to declare project-specific conventions. It is
NOT scratch and is NOT excluded from git. Keys mirror the profile plus repo/CI/Jira
settings; anything present overrides the resolved value. Example in TypeScript:

```yaml
# .auto-dev.yml  (committed at repo root; all keys optional)
stack: typescript             # the stack's name, recorded in profile.md (selects nothing)
setup: ["npm ci", "npm run build"]
gate:
  - { kind: lint, command: "npx eslint . --max-warnings 0", report: "LINT.md" }
  - { kind: test, command: "npm test",                      report: "TEST.md" }
branches:
  base: develop               # base branch to cut from and target with the PR
  staging: staging            # staging branch for the direct-merge step; omit to skip the 6b staging gate
  prefix: feature             # branch-name prefix
ci: circleci                  # github-actions | circleci | gitlab | none
ci_timeout_minutes: 30        # bound on CI watching; then the gates show CI as not monitored
iteration_budget: 4           # revise rounds per task
checkpoint_events: 80         # events one session writes before `next` checkpoints it
worktree_files: [".env"]      # gitignored files to seed every new worktree with
symbol_lookup:                # code-index commands instead of grep; <symbol> is the name
  definition: "<index-tool> definition <symbol>"
  references: "<index-tool> references <symbol>"
security_docs:                # the security directives every worker must obey, used
  - "SECURITY.md"             # instead of the repo defaults; [] turns them off, and
  - "docs/security/authz.md"  # a listed path that doesn't exist is dropped with a warning
pr_review:
  inline_comments: false      # when the PR opens, post the review findings left open or advisory on it
gates:
  post_plan: true             # force the Phase 3 post-plan gate on for this repo
mutation:
  max: 20                     # mutants per Phase 5 verifier pass (0 = off; at most 50)
jira:
  states:                     # map pipeline milestones to this board's state names
    in_progress: "In Progress"
    in_review: "In Review"
    done: "Done"
```

Resolution order (last wins): **saved or researched profile → `.auto-dev.yml`**.
The fully-resolved values are written to `.auto-dev/profile.md`.

`iteration_budget`, `ci_timeout_minutes`, `checkpoint_events`, `security_docs`,
`pr_review`, `gates.post_plan` and `mutation.max` are not stack settings, but they resolve the
same way and land in the same `profile.md`: the budget is in
`references/tables.md`; the verifier reads the mutation cap. Turn mutation off
only for a repo whose suite cannot run a scoped subset in seconds: each mutant
is one scoped test run.
