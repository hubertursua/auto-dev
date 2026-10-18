# auto-dev — notes for agents working on this repo

This repo is the auto-dev plugin: an orchestration skill (`skills/auto-dev/`) and
its worker agent types (`agents/`). Most of it is Markdown that another agent
follows; the rest is six helper scripts (`skills/auto-dev/scripts/`). `README.md`
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

- **Standard library only**, Python 3.9+ (`validate-config.py` alone may use
  PyYAML). Users run these with whatever `python3` they have.
- **Keep the CLI contract.** Each script's docstring is its `--help` and lists
  its exit codes; the skill's docs tell the orchestrator what each code means.
  If you change an exit code or an output line, update the docstring and every
  reference file that quotes it (`grep -rn "<script>.py" skills/`).
- **Add a test** in `tests/test_scripts.py` for every fix or new behavior, and
  check that it fails without your change. Tests run the script as a subprocess,
  the way the pipeline does, and build throwaway git repos in a temp dir.
- **Fail safe.** "Could not run" is exit 2, never a pass. Never leave the user's
  tree changed (see how `mutate.py` backs up and restores).
- Keep the file executable and its `#!/usr/bin/env python3` line.

## Changing the skill's Markdown

- `SKILL.md` is the spine the orchestrator always holds; keep detail in
  `references/` and point to it. Say each rule in one place and link to it,
  rather than repeating it (a repeated rule drifts).
- After editing a rule, grep for other places that state it
  (`grep -rn "<key phrase>" skills/ agents/ README.md`) and make them agree.
- Behavior changes need matching eval expectations (`skills/auto-dev/evals/`).
  The full eval suite is slow and needs a GitHub-hosted fixture repo, so PRs
  usually don't run it. Say so in the PR's Testing section.

## Every PR keeps README.md current

If a PR changes how the pipeline behaves, update `README.md` **in the same PR**.
Don't leave it for a follow-up. Before you open or update a PR, compare the diff
against this list and edit each README section it touches:

| If the PR changes…                                         | Update in README.md |
| ---------------------------------------------------------- | ------------------- |
| a phase, its order, or which worker runs it                | *Agent hierarchy* diagram, *What it does* table |
| how the build is verified (spec format, acceptance checks, verifier, audit, mutation) | *How the build is verified* |
| the scope call or the number of worker roles per scope     | *Scope call* |
| session boundaries or the context budget                   | *Three sessions, not one* |
| the code review panel, security review or rubric           | *Review before the PR* |
| a gate, a conditional pause, Jira, CI, or the merge method | *Human gates & integrations* |
| a profile, or a `.auto-dev.yml` key                        | *Stack profiles* |
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
- **Version.** A release that changes artifacts or how a run resumes bumps
  `version` in `.claude-plugin/plugin.json` and adds an *Upgrading from X.Y*
  section to the README (newest first). Say whether a run in flight can resume on
  the new version.
- **Descriptions.** `plugin.json` and `marketplace.json` carry the same plugin
  description.
- **Evals.** When behavior changes, update the expectations in
  `skills/auto-dev/evals/evals.json` that describe it.

## Branches, commits and PRs

- **One topic per PR.** Unrelated fixes go in separate PRs, even small ones.
  PRs are squash-merged, so the PR title becomes the commit on `main`.
- **Titles** are a plain imperative sentence saying what changes, with no
  `feat:`-style prefix: "Return exit 2 when resume-point cannot stat the
  artifact dir". A release adds the version: "… (3.3 → 3.4)".
- **Bodies** follow `.github/pull_request_template.md`: *Summary* (what and
  why), *Testing* (what you ran and saw, before and after for a fix, and what
  was not tested), *Docs*, and *Not included* when something is left for
  later.
- **Commit messages** inside a PR: a short imperative subject, then a body
  explaining why. Fix review findings in new commits; don't force-push over a
  branch someone is reviewing.
- **Versioning** (semver in `plugin.json`): patch for fixes and wording,
  minor for a new behavior, artifact or worker, major for a change that breaks
  resuming a run in flight.

## Writing style

Plain, direct sentences. Say what the pipeline does, and why when it isn't
obvious. Reference files by their repo path (`skills/auto-dev/references/…`)
in the README, and by `references/…` inside `SKILL.md`.
