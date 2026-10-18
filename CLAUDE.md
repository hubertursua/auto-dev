# auto-dev — notes for agents working on this repo

This repo is the auto-dev plugin: an orchestration skill (`skills/auto-dev/`) and
its worker agent types (`agents/`). `README.md` is the user-facing description of
the pipeline, and it is the file most often left stale.

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
- **Scripts** stay standard-library Python (except `validate-config.py`, which
  needs PyYAML) and executable (`chmod +x`).

## Writing style

Plain, direct sentences. Say what the pipeline does, and why when it isn't
obvious. Reference files by their repo path (`skills/auto-dev/references/…`)
in the README, and by `references/…` inside `SKILL.md`.
