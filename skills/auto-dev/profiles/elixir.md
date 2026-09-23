# Profile: elixir

Elixir / Mix projects (including umbrella apps). Detected by `mix.exs`. Commands
below are run **verbatim** by the pipeline; adjust per project with a repo-local
`.auto-dev.yml` override (see `references/profiles.md`) rather than editing this
file for one-off differences.

```yaml
stack: elixir
detect:
  any: ["mix.exs"]
setup:
  - "mix deps.get"
gate:
  - { kind: compile,   command: "mix compile --warnings-as-errors", report: "COMPILE.md" }
  - { kind: format,    command: "mix format --check-formatted",     report: "FORMAT.md" }
  - { kind: lint,      command: "mix credo --strict",               report: "CREDO.md" }
  - { kind: typecheck, command: "mix dialyzer",                     report: "DIALYZER.md" }
  - { kind: test,      command: "mix test",                         report: "TEST.md" }
test_notes: >-
  Run `mix` from the project (or umbrella) root. Some suites need a database or
  external services up first — check `config/test.exs`, `docker-compose*.yml`, and
  the repo's CLAUDE.md/README for the prerequisite (often `mix ecto.create &&
  mix ecto.migrate`, or a compose service). For an umbrella, `mix test` at the
  root runs all apps; scope to one app's suite with `mix cmd --app <app> mix test`
  when the task is confined to a single app. Dialyzer's first run builds a PLT and
  can be slow; that's expected, not a failure.
```

## Notes

- **Aggregate gate.** If the repo defines its own precommit aggregate (e.g. a
  `mix precommit` alias or a `Makefile`/`Justfile` target), prefer running that
  and add any check it omits. Discovery in Phase 1 will surface it; declare it via
  `.auto-dev.yml` `gate:` to make it authoritative.
- **Warnings as errors.** `--warnings-as-errors` on compile is intentional — a
  clean compile is part of the Definition of Done. If a project genuinely cannot
  meet that, relax it in the override, not here.
- **Credo / Dialyzer optional per repo.** Not every Elixir repo uses them, and
  this gate lists both. Phase 1 drops a check whose tool isn't actually present —
  the general rule for every stack, in `references/profiles.md`.
- **This is the reference profile.** It mirrors the conventional Elixir gate
  (`mix compile` / `format --check-formatted` / `credo` / `dialyzer` / `test`);
  other stacks follow the same schema.
