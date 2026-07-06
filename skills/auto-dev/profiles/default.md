# Profile: default (fallback)

Loaded when no shipped profile matches the repo. It ships **no hardcoded
commands** — it tells Phase 1 to discover the ecosystem's real setup and gate
commands at runtime and write them into `.auto-dev/profile.md`, exactly as the
predecessor skill's Stage 0 did. This keeps the pipeline "fully general": an
unknown stack still runs, it just relies on discovery instead of a curated
profile.

```yaml
stack: default
detect:
  any: []          # never auto-selected by signals; used only as the fallback
setup: []          # discover at runtime (see below)
gate: []           # discover at runtime (see below)
```

## Runtime discovery checklist (Phase 1 fills these in)

Read the repo and record concrete commands into `profile.md`:

- **Ecosystem & install** — detect from manifest/lock files (`package.json`,
  `pyproject.toml`/`requirements.txt`, `go.mod`, `Cargo.toml`, `Gemfile`,
  `pom.xml`/`build.gradle`, `composer.json`) and version pins (`.tool-versions`,
  `.nvmrc`, `mise.toml`, `.python-version`). Note the install command
  (`npm ci`, `pnpm install`, `uv sync`, `poetry install`, `go mod download`,
  `bundle install`, `cargo fetch`, …) and any toolchain activation
  (`mise install`, `nvm use`, …).
- **Quality gate** — find the commands that define "done": test, lint,
  format-check, type-check, build. Look in CI config (`.github/workflows`,
  `.circleci/config.yml`, `.gitlab-ci.yml`), `Makefile`/`Justfile`/`Taskfile`,
  `package.json` scripts, and `pre-commit` config. Prefer an aggregate the repo
  already defines (`make check`, `npm run verify`) and add checks it omits. Map
  each to a `lint/<CHECK>.md` report.
- **Test scope** — required databases/services, monorepo package layout, fast vs.
  slow tiers — so later phases run the right scope.

If a check genuinely can't be determined, use the conventional default for the
detected ecosystem and **record the assumption** in `profile.md` rather than
skipping verification.

## Adding a curated profile

When a stack comes up repeatedly, promote discovery into a real profile: copy the
schema from `references/profiles.md`, fill `detect`/`setup`/`gate`, and drop it in
as `profiles/<stack>.md`. No `SKILL.md` change is needed.
