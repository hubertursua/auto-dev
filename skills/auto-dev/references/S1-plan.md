# S1 — Plan (Phases 1–3)

Phase 1 is the one part of the run you do by hand: steps 1–6 below. From step 7
on, `autodev.py next` drives. `autodev.py` means `python3
<skill-dir>/scripts/autodev.py`; `<repo>` is the absolute path of the checkout
you started in: the main checkout, or a worktree the user made for this task.

On a run resumed in S1 (`resume` printed `RESUME <tree>`), `cd <tree>`. IF
`resume` also printed an `action:` line (setup is not done), run it
(`autodev.py init --continue <tree>`, adding `--profile <file>` when the fix
was in the profile) and act on its exit code as step 5's table says. Then skip
to step 7.

## Phase 1 — Setup

### 1. The ticket

- IF the user gave a Jira key or URL:
  1. Find the Atlassian tools: ToolSearch for `getJiraIssue`. Take the server
     part of the match (`mcp__<server>__getJiraIssue`) and use it for every
     Jira tool (`references/gates-and-jira.md`, _MCP tools_). No match → Jira is
     unavailable: note it and treat the key as the task text.
  2. `getAccessibleAtlassianResources` → keep the `cloudId`.
  3. `getJiraIssue { cloudId, issueIdOrKey, responseContentFormat: "markdown" }`
     → keep the key, title, link and current status.
  4. Write the issue's summary and description, exactly as `getJiraIssue`
     returned them, to a new file under `$TMPDIR` (`<ticket-text>`): the
     summary on the first line, a blank line, then the description. Don't
     shorten, reword or translate them. Define has no Jira access; `init`
     stores this file's text and gives it to Define verbatim as the task.
- ELSE the task is the user's words.

Write a one- or two-sentence restatement of the ask (`--ask` below).

### 2. The slug

Make a kebab-case slug, 2–5 words, from the ticket key or task
(`proj-123-due-dates`, `due-dates`). It names the branch and worktree; nothing
renames it later. In a worktree the user made, the run keeps that worktree and
its branch, and the slug names the branch only if HEAD is detached.

### 3. The base branch

Run `gh repo view --json defaultBranchRef -q .defaultBranchRef.name` in
`<repo>`. If `<repo>/.auto-dev.yml` sets `branches.base`, use that instead.

### 4. The profile

1. Run `python3 <skill-dir>/scripts/profile-path.py <repo>`. Keep both printed
   paths (the profile path and `DIR:`).
2. IF exit 0 (`FOUND`): run `python3 <skill-dir>/scripts/validate-config.py
   --profile <path>`.
   - exit 0 → use it. Tell the user "Using the saved profile at `<path>`".
     Don't ask again. A saved profile can list a quality-gate check whose tool
     the repo never adopted (it was saved before the repo dropped the tool), and
     that check would never go green. You don't read repo files, so ask a
     lookup: `autodev.py brief lookup --out <tmp> --set worktree=<repo> --set
     question='for each of these quality-gate checks, has the repo adopted its
     tool (a declared dependency or a config file)? <the command of each check>'`,
     where `<tmp>` is a new folder under `$TMPDIR`. Keep the question in single
     quotes, with no single quote inside (rephrase, or use ’). Spawn the agent
     it prints with its prompt, and read the answer from its reply (no run
     exists yet, so there is nothing to record).
     - Its result is anything but `ANSWERED` (it failed, stopped, or called the
       question out of scope) → keep the profile as saved: go to step 5 with
       `--profile <path> --profile-source "saved profile <path>"`.
     - Every tool adopted → go to step 5 with `--profile <path>
       --profile-source "saved profile <path>"`.
     - A check whose tool the repo never adopted → copy the profile to
       `<tmp>/profile.yml` without that check, and go to step 5 with
       `--profile <tmp>/profile.yml --profile-source "saved profile <path>,
       without <check>"`. After step 6, record each dropped check with
       `autodev.py note "dropped gate check <command>: the repo never adopted
       its tool (saved profile <path>)"`, and tell the user, so they can fix
       the saved file. A check whose tool is adopted stays, even when the
       tool is missing from this machine: that is a setup problem for the user
       to fix, never a reason to drop the check.
   - exit 1 → show the user the errors, then research (3 below) and offer to
     overwrite the file.
   - exit 2 → stop: tell the user python3 3.9+ and PyYAML are required
     (`pip install pyyaml`).
3. IF exit 1 (`NOT FOUND`) or exit 2 (no path; leave out the save option):
   - IF `<repo>/.auto-dev.yml` exists, run `python3
     <skill-dir>/scripts/validate-config.py <repo>/.auto-dev.yml` and branch
     on its result:
     - exit 0 and its `VALID:` line lists both `setup` and `gate` → the repo
       declares its own profile: skip research and go to step 5 with no
       `--profile`.
     - exit 0 with a partial file (`setup` or `gate` missing) → research (below);
       `init` applies the file over the researched profile.
     - exit 1 → stop and show the errors.
     - exit 2 → stop: tell the user python3 3.9+ and PyYAML are required
       (`pip install pyyaml`).
   - IF there is no `.auto-dev.yml`, or it is partial, research:
     1. `git -C <repo> fetch origin <base>`.
     2. `autodev.py brief profiler --out <tmp> --set repo=<repo> --set
        base=<base> --set draft_path=<tmp>/profile.yml`, where `<tmp>` is a new
        folder under `$TMPDIR`.
     3. Spawn the agent it prints with the prompt it prints.
     4. Ask the user (AskUserQuestion), showing: the draft YAML, the evidence
        line for each command, everything under NOT INSTALLED and QUESTIONS
        (questions first), which keys `.auto-dev.yml` will override, the save
        path, and the permissions guidance from `references/profiles.md`,
        _Permissions_, with this run's paths and commands filled in. Options:
        `Looks right — save it for this repo` · `Looks right — use it for this
        run only` · `Change something (tell me what)` · `Stop`.
     5. `Change something` → edit `<tmp>/profile.yml` as the user said and ask
        again. `Stop` → stop; nothing was created.
     6. `save it` → write the file to the path `profile-path.py` printed, with a
        first-line comment naming the repo and today's date, then run
        `validate-config.py --profile <path>` (exit 1: fix what it names). A
        denied write never stops the run: show the permissions guidance and the
        YAML so the user can save it, and go on.
     7. Go to step 5 with `--profile <tmp>/profile.yml --profile-source
        "researched by the profiler, confirmed by the user"`.

### 5. Create the run

Run, from `<repo>`:

```
autodev.py init --repo <repo> --slug <slug> --task "<task, one line>" \
  --ask "<restated ask>" [--ticket <KEY> --ticket-url <link> \
  --ticket-text-file <ticket-text>] \
  [--profile <file> --profile-source "<where it came from>"] \
  --jira "<available, cloudId <id> | unavailable: <why> | no ticket>"
```

| Exit | Do |
|---|---|
| 0 | the worktree, state and setup are ready: go to step 6 |
| 1 | stop: tell the user the `STOP:` reason (`references/tables.md`, stop conditions 1–3). Once they fix it: IF the reason names `init --continue` (a setup command failed or its runner died), run `autodev.py init --continue <worktree>` (with `--profile <file>` when the fix was in the profile). ELSE re-run the same `init` command |
| 2 | could not run: tell the user the error |
| 3 | setup is still running: run `autodev.py init --continue <worktree>` until it exits 0 or 1 |

Pass `--ticket-text-file` whenever step 1 wrote one: without it, Define
works from your restated ask alone. When `<repo>` is a worktree the user made
(a linked worktree on a branch other than the base and the default branch),
`init` runs the task in it instead of making a new one, and prints `adopted:
yes`; it stops if the worktree has uncommitted changes. IF it also prints
`ahead: <n>`, tell the user the <n> commits already on that branch will be part
of the PR.
`init` finds the security directives itself (`security_docs` in
`.auto-dev.yml`, else `SECURITY.md`, `.github/SECURITY.md` and
`docs/security/`).

### 6. Move into the worktree

`cd <worktree>` (the path `INIT:` printed; the one you are in when `init`
used yours). Every later step runs there.

## Phases 2–3 — the loop

### 7. Run the loop

Follow **The loop** in `SKILL.md` until `next` exits 3, 4 or 6. What you will
see in S1, in order:

1. `define` writes `SPEC.md` and the size check, from the ticket text `init`
   stored (else your `--ask`). `OVERSIZED` → exit 4: tell
   the user Define's reasons, the subsystems it found and its suggested split
   lines, all in the `REPORT` (copied from SPEC.md's Size check). Nothing else.
2. With a ticket: the Jira question (exit 5). On `Move it`, a later exit 0
   says to move the ticket: do it as `references/gates-and-jira.md`,
   _Moving a ticket_ says, then run its `AFTER` line.
3. `define-reviewer`, maybe several rounds. A FIX block that doesn't apply
   sends `define` back in revise mode. You do nothing but spawn.
4. `planner`, then `plan-reviewer` the same way.
5. `acceptance-tester`. It may be spawned again for listed conditions, or send
   `define` a question about a condition that reads two ways.
   A worker whose result `record` refuses (exit 1) is briefed again by the
   next `next`, with the refused issues: just run `next`.
6. The post-plan gate (exit 5) when the task is high-risk or the repo turns it
   on.
7. Exit 6: run its `AFTER` command exactly as printed (`handoff` at the end of the
   session, `handoff --checkpoint` at a checkpoint), give the user its message,
   stop.

### Stops in S1

Every stop is exit 4 with its reason in `REPORT`. The full list is
`references/tables.md`, _Stop conditions_. The usual ones here: OVERSIZED,
budget used up on a review, a worker that stopped or failed twice.
