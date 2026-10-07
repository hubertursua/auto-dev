# Phase 1 — Setup procedure

Deterministic, run by the orchestrator at the start of S1. `SKILL.md` keeps the
step list; this file holds each step's full procedure and exact commands. Phase 1
runs **once per run** — never again for a sub-task of a multi-PR run, and never on
a resume.

**First: is this a resumed run?** You are standing in the main repo, which has no
`.auto-dev/` — the control worktree is a sibling directory. Scan `git worktree list`
for one holding a `.auto-dev/WORK_LOG.md` whose header matches this task
(`<skill-dir>/scripts/resume-point.py <tree>/.auto-dev --task "<ticket or task>"`
checks each one). If one exists, do not re-run Phase 1: read the ledger and
continue from it. Full detection procedure and the script's exit handling:
`references/artifacts.md`, _Resuming an interrupted run_.

1. **Detect the repo & branches.** Canonical repo name from the git remote
   (`basename -s .git "$(git remote get-url origin)"`); default branch via
   `gh repo view --json defaultBranchRef`. Resolve `base`, `staging` (optional),
   and branch `prefix` — from `.auto-dev.yml` if present, else conventional
   defaults. Confirm the staging branch exists
   (`git ls-remote --heads origin <staging>`); if it does not, mark the Phase 6
   staging gate `n/a` in the ledger.
   **Check `gh` before anything else in this step** — `gh auth status`, and an
   `origin` that is GitHub. Phase 6 cannot open or merge a PR without it, so a
   missing, unauthenticated, or non-GitHub setup is a **stop-and-report now**, not
   a surprise after the build.
2. **Detect the stack & load the profile.** Match `detect` signals
   (`references/profiles.md`) → load `profiles/<stack>.md`, else `profiles/default.md` +
   runtime discovery. Merge in repo-doc/CI discovery, apply `.auto-dev.yml`
   (validated first by running `<skill-dir>/scripts/validate-config.py` — exact
   command and exit codes in `references/profiles.md`). Exit `1` (INVALID) is a
   stop-and-report; after the user fixes the file, re-run the validator on it
   before applying it and continue only on exit `0`, with the same exit handling.
   While reading CI config, **record the CI provider** (GitHub Actions / CircleCI /
   GitLab / none) — `profile.md` carries it and Phase 6 monitors with it.
3. **Resolve the ticket.** If the user gave a Jira key/URL, read it via the
   Atlassian MCP (`getJiraIssue`, called by its fully qualified
   `mcp__<server>__getJiraIssue` name, located as `references/gates-and-jira.md`
   § "MCP tools" describes); detect Jira availability and cache the issue.
   Otherwise treat the free-form task text as the ticket.
4. **Read the repo's binding rules** — `CLAUDE.md`/`AGENTS.md`, `CONTRIBUTING`,
   and the repo's coding-guideline docs — and carry them into every worker's brief.
   **Resolve the security directives** here, taking the first source that exists:
   the paths listed under `security_docs:` in `.auto-dev.yml`; the repo's own
   security docs (`SECURITY.md`, `docs/security/*`, a security section in
   `CONTRIBUTING`); the security section of `CLAUDE.md`/`AGENTS.md`. Record the
   resolved sources in `profile.md` — or `security directives: none found`, falling
   back to the repo's coding rules alone. Later phases cite what `profile.md`
   records; never point a worker at a directive it cannot look up.
5. **Create the isolated worktree** on its own branch (never the default branch):
   ```bash
   git fetch origin          # so origin/<base> is current, not whatever was last fetched
   git worktree add ../<repo-name>-<slug> -b <prefix>/<slug> origin/<base>
   ```
   Then **seed the gitignored files** listed under `worktree_files` by the profile
   or `.auto-dev.yml` (`.env`, `.env.test`, local config), copying them from the main
   checkout. A fresh worktree has none of them, and a suite that needs one fails in a
   way that reads exactly like broken code. Report any listed file that isn't there
   instead of continuing silently, and record what was seeded in `profile.md`.
   Then confirm git ignores each seeded file (each entry is a file path, not a
   directory): `git check-ignore -q -- <file>` from
   the worktree root must exit `0`. If one is not ignored, **stop and report** it:
   these files usually hold secrets, and an unignored one would show in the PR
   gate's file list and be staged into the commit.
   Then run the profile's `setup` commands. If one fails with "command not found"
   (exit `127`), the stack's toolchain isn't installed: **stop and report** the
   missing command. Don't install a toolchain yourself, and don't drop gate checks
   to get past it (`references/profiles.md`, step 5). Derive `<slug>` from the ticket/task:
   the slug is **yours alone**, since the branch and worktree exist before Phase 2
   runs. No later phase returns or renames one.
6. **Prep `.auto-dev/`** and make it self-excluding (see `references/artifacts.md`).
   Run the script. It creates `.auto-dev/lint/`, writes `.auto-dev/.gitignore` as
   `*` if that file is absent or wrong, and then verifies with git that nothing
   under `.auto-dev/` is visible:
   ```bash
   python3 <skill-dir>/scripts/exclude-artifacts.py <worktree>
   ```
   - `0` — created and verified; go on to step 7. Running it again is harmless.
   - `1` — git still sees the paths it prints (for example a file under
     `.auto-dev/` that the base branch tracks). Write no artifact yet: resolve
     what it names and re-run it; if that can't be resolved, stop and report.
   - `2` — it couldn't run (git missing, or `<worktree>` is not a git work tree
     or not its root). Not a pass: fix the cause it names and re-run it.
   - `127` — `python3` isn't installed. Do the step by hand instead, from the
     worktree root:
     ```bash
     mkdir -p .auto-dev/lint
     printf '*\n' > .auto-dev/.gitignore
     git status --porcelain --untracked-files=all -- .auto-dev/   # must print nothing
     ```

   Do **not** use `.git/info/exclude` here: inside a linked worktree `.git` is a
   _file_, not a directory, so that command fails outright — and the shared file
   it resolves to would leak into every other worktree.
7. **Write `.auto-dev/profile.md`** (fully-resolved profile) and initialize
   `.auto-dev/WORK_LOG.md` — whose header carries the normalized ticket.
8. **Jira → In Progress** (if a ticket exists), confirmed with the user as part of
   starting work (`references/gates-and-jira.md`).

All later phases run **inside the worktree directory**.
