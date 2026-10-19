# Stack profiles — research, confirmation, saving, and overrides

A **stack profile** tells the pipeline how a repo installs its dependencies and
which quality-gate commands constitute "done."

auto-dev ships **no** stack profile. Each repo gets its own: the first run
researches it (the `auto-dev:profiler` worker), the user confirms it, and the
user may save it on their machine, outside every checkout, where later runs from
any clone or worktree of the same repo find it.

## Contents

- **How Phase 1 resolves the profile** — find a saved profile, else research and
  confirm one, offer to save it, apply the override, drop missing tools, record
  `profile.md`.
- **Profile schema** — the keys a profile holds and what each means.
- **Saved profiles** — where they live and how a run finds them.
- **Permissions** — what the user allows so a run reads and saves the profile
  without prompts, and the guidance to show them.
- **Monorepos, umbrellas, and multi-stack repos** — scoping the quality gate to
  the right package.
- **Repo-local override — `.auto-dev.yml`** — every key a project can override.

## How Phase 1 resolves the profile

`<repo>` below is the main checkout you started in, as an absolute path; the
worktree does not exist yet.

1. **Look for a saved profile.** Run the script; don't work the path out
   yourself:
   ```bash
   python3 <skill-dir>/scripts/profile-path.py <repo>
   ```
   `<skill-dir>` is this skill's own directory (the one holding `SKILL.md`; Claude
   Code names it as the skill's base directory when the skill loads). It prints
   `FOUND: <path>` or `NOT FOUND: <path>`, then `DIR: <profiles-dir>`. Keep both
   paths: the second line is the directory the permissions guidance names.
   - `0` — **found.** Validate it with
     `python3 <skill-dir>/scripts/validate-config.py --profile <path>`, then read
     it. Exit `0`: use it as the profile and tell the user in one line
     ("Using the saved profile at `<path>`"); **don't ask again**, since the user
     confirmed it when it was saved. Exit `1`: show the user the errors, then
     research as if none were saved (step 3), and offer to overwrite the file at
     the confirmation. Exit `2` (no PyYAML): check the file by hand against
     _Profile schema_ and record "not machine-validated" on `profile.md`'s
     _Profile_ line. If reading the file is denied or prompts, show the
     _Permissions_ guidance; if the user won't allow it, research instead.
   - `1` — **none saved.** The printed path is where a save goes (step 5).
   - `2` — it can't name a location (the reason is on stderr: no `origin`, or a
     URL it can't turn into a safe path). Research anyway, and leave the save
     option out of the confirmation. Record the reason.
   - `127` — no `python3`. Same as `2`: research, and offer no save.
2. **A committed full override skips research.** If there is no usable saved
   profile and `.auto-dev.yml` sets both `setup` and `gate`, the repo has already
   declared its profile: use it (step 6) with no research, no confirmation and no
   save offer.
3. **Research.** Otherwise run `git fetch origin <base>` (the profiler reads
   files as they are on `origin/<base>`, which the run is cut from), then spawn
   `auto-dev:profiler` on `<repo>` with its brief
   (`references/subagent-prompts.md`, _Phase 1 — Profile research_). It reads
   the repo and returns a draft profile, the evidence for each command, and what
   it had to guess.
4. **Confirm with the user** — the **profile confirmation** pause
   (`references/gates-and-jira.md`, _Conditional pauses_). Show the draft, its
   evidence and guesses, which keys `.auto-dev.yml` will override, the save path,
   and the _Permissions_ guidance filled in with this run's paths and commands.
   On `Change something`, apply the user's corrections to the draft yourself and
   ask again. A correction here is the user's, so it spends no iteration-budget
   round. `Stop` ends the run before any worktree exists.
5. **Save, if the user chose to.** Write the confirmed profile, exactly as
   confirmed and without the `.auto-dev.yml` overrides, to the path `profile-path.py`
   printed (over a broken saved file, when step 1 found one)
   (the Write tool creates the folders). Start the file with a comment naming the
   repo and the date. Then run `validate-config.py --profile <path>`; on exit `1`,
   fix what it names and re-run. If the write is denied or blocked, don't retry
   another way: show the _Permissions_ guidance and the YAML, tell the user they
   can save it at that path themselves, and continue with the confirmed profile.
   A save that failed never stops the run. Never save a profile the user did not
   confirm.
6. **Apply** the repo-local `.auto-dev.yml` override (if present) — it wins over
   the profile. **Validate it first** — run the script, don't read it:
   ```bash
   python3 <skill-dir>/scripts/validate-config.py <repo>/.auto-dev.yml
   ```
   Use absolute paths for both arguments so the command works from any working
   directory. A wrong script path makes `python3` itself exit `2` ("can't open
   file"), which is easy to misread as the validator's own exit `2`.
   Output: `VALID: …` on stdout, or `ERROR …` lines then `INVALID: …` (or
   `SKIPPED: …`) on stderr; `warning …` lines never fail the run.
   **Requires** Python 3.9+ and the third-party package PyYAML; everything else
   it imports is standard library. It checks for PyYAML itself, so there is no
   separate pre-check to run. On Python older than 3.9 it dies with a
   traceback (exit `1`, no `INVALID:` line) — treat that like exit `2`, not as an
   invalid file. No `python3` on PATH at all (exit `127`, "command not found") is
   handled the same way as exit `2`.
   An unrecognized key is silently ignored otherwise, so a typo reads as "the
   override did nothing" — the validator names the key and suggests the one it
   probably meant. Exit `0` is a pass — apply the file. Exit `1` is a
   stop-and-report; once the user has fixed `.auto-dev.yml`, re-run the validator
   on the fixed file before applying it, and continue only on exit `0`, handling
   every exit code exactly as on the first run. Exit `2` means validation could not run (no PyYAML, or the
   file could not be read), which is not a pass. Don't install PyYAML into the
   user's environment yourself. Instead check every key in the file by hand
   against "Repo-local override" below (spelling, type, allowed values), then apply it.
   Record "not machine-validated: <reason>" on `profile.md`'s `.auto-dev.yml`
   line and repeat it in the final report.
7. **Drop any quality-gate check whose tool isn't actually there.** A profile
   may list a check the repo doesn't use — a saved profile written before the
   repo dropped a tool, or a guess the user let through. Keep a check only where
   its tool is genuinely available — the dependency is declared, or its config
   file exists — and otherwise drop it and **record the omission** in
   `profile.md` (an ESLint check in a repo with no ESLint config is the usual
   case; example in TypeScript). Never keep a check that cannot run: Phase 5
   would never go green, and the pipeline would stop on a tool the project never
   adopted. "Available" means the project adopted it, not that it is on your
   PATH: a declared tool, or the toolchain itself, that is adopted but not
   installed is a setup failure. Stop and report the missing command; don't drop
   the check (Phase 1 step 5). When the profile came from a saved file, name that
   file in the report so the user can fix or delete it.
8. **Refuse an empty quality gate.** Once unavailable checks are dropped, the resolved
   `gate` must still contain at least one command that runs the project's tests. A
   quality gate with nothing in it makes Phase 5 pass by having nothing to check, and the
   change then rides through every remaining human gate unverified — the one failure mode
   this pipeline cannot detect downstream. If neither the profile nor the
   override has a way to run the tests, **stop and report**: it is a setup
   problem the user fixes in one line of `.auto-dev.yml`, and guessing is worse
   than asking.
9. **Record** the fully-resolved result to `.auto-dev/profile.md`, with where
   the profile came from. Every later phase reads that file rather than
   resolving it again.

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
- **`symbol_lookup`** (optional) — commands the orchestrator uses instead of
  grep to find where a module, function or class is defined (`definition`) and
  used (`references`). Each must contain `<symbol>`. Phase 1 keeps them only if
  the tool is on PATH; otherwise, or when the profile has none, `profile.md`
  records `grep -n`. A code index answers with less noise than grep, which
  saves the orchestrator's context.
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
  and the files in play, record the chosen package and its own `gate` in
  `profile.md`, and note in `WORK_LOG.md` that other packages were out of scope.
  If the task genuinely spans packages, that's a sign it is OVERSIZED (the Define
  agent's size check, `SKILL.md`).
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
ci_timeout_minutes: 30        # bound on CI watching before it reports and holds
iteration_budget: 4           # revise rounds per task
worktree_files: [".env"]      # gitignored files to seed every new worktree with
symbol_lookup:                # code-index commands instead of grep; <symbol> is the name
  definition: "<index-tool> definition <symbol>"
  references: "<index-tool> references <symbol>"
security_docs:                # the security directives every worker must obey;
  - "SECURITY.md"             # first source Phase 1 checks, ahead of repo defaults
  - "docs/security/authz.md"
pr_review:
  inline_comments: false      # post Phase 6a findings as inline PR comments
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

`iteration_budget`, `ci_timeout_minutes`, `security_docs`, `pr_review`,
`gates.post_plan` and `mutation.max` are not stack settings, but they resolve the same way and land in
the same `profile.md` — see `references/correction-loop.md`,
`references/gates-and-jira.md`, Phase 1 step 4 in `references/phase-1-setup.md`,
and, for `mutation.max`, the verifier's mutation step in
`references/subagent-prompts.md`. Turn mutation off only for a repo whose suite
cannot run a scoped subset in seconds: each mutant is one scoped test run.
