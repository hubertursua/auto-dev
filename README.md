# auto-dev

An orchestration skill for autonomous development.

It drives a single coding task from a ticket to a merged pull request hands-off,
delegating each job to a purpose-built **worker** (a subagent) and handing
structured artifacts between them through a `.auto-dev/` scratch directory. It is
**stack-agnostic**: it ships no stack profile, and instead researches each repo's
setup and quality-gate commands on the first run, confirms them with you and can
save them for later runs. It integrates
optionally with Jira and CI — each auto-detected and skipped when absent.

## Agent hierarchy

The main agent stays the orchestrator and never writes code itself — it spawns a
fresh worker per delegated job and hands off through files in `.auto-dev/`,
never shared memory. It doesn't decide the order of steps either: it runs
`autodev.py next`, does the one action printed, and runs it again. Phase 1's
profile and ticket steps are its own work. Correction briefs come from the
workers that found the problem (the verifier, the review judge, the triager),
and the orchestrator passes them on unedited. Judging the build is not its job
either — it holds the plan and the story of every round, which is the context a
judge must not have.

```
Orchestrator (main agent) ── owns the pipeline, holds the spec, runs the human gates
│
├─ Phase 1  Setup ......... detect repo, profile (saved, or profiler + your OK), ticket, worktree
├─ Phase 2  Define agent .. SPEC.md — the testable contract + SIZE CHECK  (→ reviewer)
├─ Phase 3  Planner ....... IMPLEMENTATION.md — the technical how  (→ reviewer)
│           Acceptance tester  held-out checks from the spec, proven to fail, sealed [optional gate]
├─ Phase 4  Coder ......... code + tests (given only the plan)
├─ Phase 5  Verifier + cleanup  RUN the checks vs. the withheld spec → /simplify → quality gate → re-check
└─ Phase 6  orch + reviewers  code review panel → security review → [GATE] PR + CI → [GATE] main
            Triager ......... reads red CI logs and human PR comments, so the orchestrator never does
```

Two documents describe the work, and they answer different questions: `SPEC.md`
asks *did we build the right thing*, `IMPLEMENTATION.md` asks *did we build it the
way we decided*. They fail independently — a plan executed faithfully can still
miss the outcome — so the pipeline checks both.

The coder builds from the plan, never the contract. The plan is *required* to
cover every condition, so this isn't information-hiding — it's **language**-hiding:
the coder can't satisfy the check by echoing the contract's own wording back in a
test name.

## How the build is verified

Tests the coder wrote are evidence the coder produced, so they can't be the main
proof that the work is right. Agents are known to mark work done too early and to
make tests pass by weakening them. Verification is built around that:

- **A spec written to be tested.** Every condition in `SPEC.md` carries a
  concrete example (Given / When / Then), its tricky edge case, and how it should
  be verified (unit, integration, end-to-end or manual). The Define reviewer runs
  an ambiguity probe: if two different implementations both fit a condition's
  words, the condition is rewritten before anything is built.
- **Held-out acceptance checks.** After planning, an acceptance tester turns each
  spec condition into a black-box test from the spec alone, one for its example
  and one for its edge case, at the level the spec asks for (or the highest the
  repo's tests reach, saying why). Every
  check for new behavior must **fail on the untouched code for the right
  reason**, since a test that passes before the change exists proves nothing.
  The tester saves that run (the command and its output) next to the checks.
  The orchestrator reads it and sends the tester back for an edge case left
  out without a reason, or a check that failed for the wrong reason. The checks
  are then sealed out of the worktree (stored where no test runner collects
  them), and the coder's brief never names them.
- **An independent verifier that runs things.** After the build, a fresh verifier
  installs the checks and **runs** them. It never sees the plan or the coder's
  report. Each condition gets a verdict and an evidence tier: **Strong** (the
  held-out checks passed, they cover both the example and the edge case at the
  level the spec asks for, and the saved run shows each check for new behavior
  failing on the old code for the right reason), **Adequate** (it ran
  something itself for what the checks don't prove and saw what it predicted
  beforehand) or **Weak** (a code citation, which can never count as met). The
  verifier reads the saved run rather than running the checks on the old code
  again, which would need a second setup of the repo. A held-out check too weak
  to prove what it claims is reported; the tester repairs it only when the
  condition can't be shown to hold any other way. A condition no agent can
  observe is marked `manual` and handed to you at the PR gate as a check to
  make, and so is an edge case no agent can observe.
- **A test-integrity audit.** `scripts/check-tests.py` flags deleted or skipped
  tests, removed assertions, new tests that assert nothing, and any edit to a
  sealed check. Each finding must be justified by the spec or it goes back to the
  coder. The coder and cleanup agent are told never to game tests, and the coder
  has a `BLOCKED` exit for when a step can't be done honestly.
- **Targeted mutation testing.** Passing tests show the code works; they don't
  show the tests would notice if it broke. The verifier plants a few small bugs
  in the changed lines (a flipped comparison, a boundary moved by one) with
  `scripts/mutate.py`, which restores every file afterwards. A bug no test
  catches on a line a condition depends on is a test gap and goes back to the
  coder. Capped at 20 mutants per pass by default; set `mutation.max` in
  `.auto-dev.yml` (0 turns it off).
- **Fixes described by the verifier.** Once its verdicts are final, the
  verifier writes `evidence/corrections.md`: what the code must do, where, the
  failure it saw and the test to add, in its own words, never the spec's. The
  coder gets that file unedited. A script refuses one that copies the spec's
  wording, which would let the coder echo it back in a test name.
- **Re-checked after every change.** The verifier runs again after `/simplify`
  and after every later fix, so the PR description always reflects the final
  code.
- **Every result names the code it checked.** `SPEC_EVAL.md`, each quality-gate
  report and both review reports carry a `Tree:` line: the git tree hash of the
  code when it was checked. `scripts/check-fresh.py` compares those stamps with
  the code as it is now at the end of the build session, on entry to the ship
  session, before the PR gate, after the commit, before the PR description is
  written, and before the main gate. A result checked on other code, because
  someone edited the worktree, pushed to the PR or merged the base into it, is
  run again before anything relies on it. Those re-runs spend no iteration
  budget; anything they find is fixed like any other problem. The PR description
  names the commit its results were checked on.
- **A PR description a stranger can check.** It is written for a reviewer who
  has never heard of auto-dev and can't see `.auto-dev/`: plain words, no
  condition or mutant IDs. For each requirement it links the test written
  before the code, at the checked commit, with that test's result on the old
  code and now, and both runs' commands and output in a collapsed block. It lists
  every test change the audit flagged with its reason, says how many small
  deliberate bugs the tests caught and, for each one they missed, why it is
  harmless or what no test checks,
  and turns each check left to a person into steps. It tells the reviewer to
  start with the tests written before the code. A description too long for
  GitHub moves its output blocks into one PR comment. The PR gate keeps the
  short IDs (`C2`, `M7`), since you can open the run's files.

## What it does

Invoke it when you want a whole task taken off your plate and delivered as a
finished PR, hands-off — e.g. *"auto-dev this…"*, *"take it all the way to a
PR"*, *"pick up JIRA-1234 and ship it"*. The orchestrator runs:

| Phase | Worker | Output |
|-------|--------|--------|
| 1 Setup | orchestrator, profiler (first run on a repo) | detect repo, load the saved profile or research one and confirm it with you, resolve ticket, isolated worktree + branch, `.auto-dev/` |
| 2 Define | Define agent + reviewer | `SPEC.md` — context, testable conditions, assumptions, security criteria; plus the **size check** (too big for one PR → back to you) |
| 3 Plan | planner + plan reviewer, acceptance tester | `IMPLEMENTATION.md` — the technical how; `acceptance/` — held-out checks sealed from the coder (optional approval gate) |
| 4 Build | coder | code + tests given **only** the plan |
| 5 Verify | verifier, then cleanup agent | the verifier runs the held-out checks and audits the tests vs. the withheld spec → `SPEC_EVAL.md` (correction loop to Phase 4), then `/simplify` + the profile's quality gate to green, then a verifier re-check |
| 6 Ship | orchestrator, 3 code reviewers + judge, security reviewer, triager | code review panel and security review on the uncommitted change (correction loop to Phase 4 for must-fix findings), then commit + draft PR + CI, then main + Jira Done — pausing at each gate |

## Three sessions, not one

The pipeline deliberately does **not** run end-to-end in a single context. It is
cut into three sessions — **Plan** (phases 1–3), **Build** (4–5) and **Ship** (6)
— and stops at each boundary after writing `.auto-dev/HANDOFF.md`, a short brief
for the next one. Start a fresh session and say `auto-dev continue` to pick up.

Every session runs on whatever model you pick; the orchestrator follows short
runbooks (`skills/auto-dev/references/S1-plan.md`, `S2-build.md`,
`S3-ship.md`) and is never asked to judge, so it doesn't need a stronger model
for any of them, and it never asks you to switch.

Orchestrator context is the real cost driver: every added turn makes every later
turn more expensive. So the orchestrator holds the pipeline, not the code — it
delegates reads and keeps large artifacts in workers — and `next` ends a long
session at a **checkpoint**: after 80 recorded events in one session (about 35
workers; `checkpoint_events` in `.auto-dev.yml` changes the count), at the next point where the step would be an action and no worker is
in flight (a stop or a question the step would print comes first), it writes `HANDOFF.md`
and asks you to continue in a fresh session. Continuing after a checkpoint
lifts no stop: a worker that failed once before it and once after still stops
the run. Nothing crosses a boundary except `.auto-dev/` on disk and the git tree,
which is also what makes an interrupted run resumable.

## Size check: one PR, or back to you

The Define agent says whether the task fits one PR:

- **FITS** — the pipeline runs every step, the same way for every task: **11
  worker roles**. (Roles, not spawns — the code review panel alone spawns three
  reviewers and a judge, and a correction round re-spawns workers.) This count
  leaves out Phase 1's profiler, which runs only when the repo has no saved
  profile.
- **OVERSIZED** — multiple independent deliverables, several subsystems, or a
  large file count. auto-dev builds nothing and hands the task back to you with
  Define's reasons, the subsystems it found and suggested lines to split along.
  Jira is left alone, and the worktree and branch stay in place, with the
  commands to remove them. Split the task (by hand or with another tool) and run
  auto-dev on each part.

Define also flags a task as **high-risk** (security criteria, auth, payments,
access control or a data migration), which turns on the post-plan gate. A
security criterion that a later revision or review fix adds to `SPEC.md` turns
it on too; nothing turns it off.

An interrupted run resumes from `.auto-dev/state.json`: `autodev.py resume`
finds it, and `next` picks up at the step it stopped on.

## Review before the PR

Nothing is committed or pushed until the change has been reviewed twice, on the
uncommitted working tree, and you have seen the results:

1. **Code review panel.** Three reviewers run `/code-review xhigh` on the change
   independently. A judge merges their findings and checks each trigger path in
   the code. A correctness or test finding that only one reviewer raised goes to
   the other two for a re-vote.
2. **Security review.** One security reviewer runs `/security-review` over the
   whole change, and the judge double-checks every finding rated High or Medium.

A **rubric** decides what must be fixed and what is noise:

- **Code findings.** Only correctness bugs, missing or weak tests, and a
  held-out acceptance check that asserts the wrong thing or can't fail can be
  must-fix. Each one needs a concrete trigger path, a real input or sequence that
  leads to the failure, and at least 2 of the 3 reviewers' votes. A finding
  about an acceptance check goes to the acceptance tester's repair mode, never
  the coder. Scope, performance and design findings are advisory. Problems the
  change didn't introduce are dropped.
- **Security findings.** One this change introduced, with a traced path, is
  must-fix. One that was already there is shown to you at the PR gate to triage:
  note it as a follow-up for a separate PR (the PR description lists it), or
  ignore it. This PR never fixes it, because that would widen the PR's scope.
  Your answer is recorded in the run's state, not just noted.
- **Confidence.** Every finding carries a confidence level (High, Medium or
  Low), and so does each report as a whole. A report whose confidence is Low
  (say, a reviewer failed) is flagged at the gate as a warning, never shown as a
  clean pass.

The judge writes a **required change** for each must-fix finding, and those go
back to the coder unedited, through the same correction loop as an unmet spec
condition; the fix is reviewed again before anything moves on. After the PR is
open, a **triager** reads what the orchestrator never sees: a red CI run's logs
(is it the code, the infrastructure, a flaky test or a missing secret? only the
code goes to the coder) and human reviewers' comments (blocker, nit, question,
already addressed, or about a held-out check, which goes to the acceptance
tester rather than the coder; when both kinds come back, the tester goes first
and the coder second, in one revise round). After a correction refreshes the PR,
the next triager reads the earlier rounds' triage files and what became of them,
so a comment about a check the tester ruled right, or a blocker the code now
fixes, is sorted as addressed and doesn't spend another round. Everything the pipeline posts on
the PR ends with `<!-- auto-dev -->`, and the triager skips those comments.
A red CI run the code can't fix (a secret, infrastructure, a flaky test,
unknown) stops the run and is reported before Jira moves;
once the cause is fixed and CI re-run, resuming watches it again. CI that times
out or can't be watched is shown at the main gate as not monitored, never as
green.
Comment text never reaches the orchestrator, so a comment can't steer the run.
The coder gets every required change unedited, so `autodev.py record` refuses
one that copies `SPEC.md`'s wording. Those fixes are reviewed the
same way before they are pushed. The reviewers' instructions are in
`agents/code-reviewer.md`, `agents/review-judge.md` and
`agents/security-reviewer.md`, and the full rubric in
`skills/auto-dev/templates/rubric.md`.

## Stack profiles

The pipeline is language/framework-agnostic and ships no stack profile. A
**profile** says how a repo installs its dependencies and which commands make up
its quality gate (test, lint, format check, type check, build). Phase 1 gets one
in this order:

1. **A saved profile.** If you saved one for this repo on an earlier run, Phase 1
   loads it without asking.
2. **A committed `.auto-dev.yml` that sets both `setup` and `gate`.** The repo
   has declared its profile, so there is nothing to research.
3. **Research.** Otherwise the `profiler` worker reads the repo (CI config, task
   runners, manifests, lockfiles, contributing docs) and returns a draft profile
   with the file and line each command came from, plus anything it had to guess.
   The run pauses to show you the draft and asks: save it for this repo, use it
   for this run only, change something, or stop.

`.auto-dev.yml` is applied on top in every case. The schema is in
`skills/auto-dev/references/profiles.md`, and the steps in
`skills/auto-dev/references/S1-plan.md`.

### Where saved profiles live

A saved profile is a YAML file on your machine, outside every checkout, named
after the repo's `origin` remote:

```
~/.config/auto-dev/profiles/<host>/<owner>/<repo>.yml
```

So `git@github.com:acme/web-app.git` is saved as
`~/.config/auto-dev/profiles/github.com/acme/web-app.yml`, and every clone and
worktree of that repo finds the same file. Set `AUTO_DEV_PROFILES_DIR` to use
another directory (`$XDG_CONFIG_HOME/auto-dev/profiles` is used when that is
set). `skills/auto-dev/scripts/profile-path.py <repo>` prints the path for a
repo. Edit the file to change the profile, or delete it to have the next run
research it again. It holds only how the stack installs and checks itself; repo
policy such as branches and the iteration budget stays in `.auto-dev.yml`.

### Permissions for unattended runs

Claude Code asks before reading or writing a file outside the directory it was
started in, so loading and saving a profile prompts unless you allow it. Add
these rules to `~/.claude/settings.json` (or run `/permissions`):

```json
{
  "permissions": {
    "allow": [
      "Read(~/.config/auto-dev/**)",
      "Edit(~/.config/auto-dev/**)"
    ]
  }
}
```

- `Edit(...)` also covers creating the file; there is no separate `Write` rule.
- If you moved the directory with `AUTO_DEV_PROFILES_DIR` or `XDG_CONFIG_HOME`,
  use that path instead: `~/…` inside your home directory, `//…` for any other
  absolute path (`Read(//opt/auto-dev/profiles/**)`).
- For a single session, start with `claude --add-dir ~/.config/auto-dev` or run
  `/add-dir ~/.config/auto-dev`. Reads stop prompting; saving still asks unless
  you accept edits.
- With the Bash sandbox on, also add
  `"sandbox": { "filesystem": { "allowWrite": ["~/.config/auto-dev"] } }`.
- The directory is deliberately not under `~/.claude/`: Claude Code protects
  that folder, and every write there prompts whatever your rules say.

The run also executes the helper scripts and the profile's commands through
Bash. To let those run without prompts, add `Bash(...)` rules for them to the
main checkout's `.claude/settings.local.json`. Example in TypeScript:

```json
{
  "permissions": {
    "allow": [
      "Bash(python3 /path/to/auto-dev/skills/auto-dev/scripts/*)",
      "Bash(npm ci *)",
      "Bash(npm test *)"
    ]
  }
}
```

A rule matches the command's text, so copy the commands exactly as the profile
lists them. Workers write their git commands as `git -C <worktree> …` with the
cut commit as a literal sha, never `cd … && git` or `$(…)`, which a headless
run refuses even when the command is allowed. A worker whose call the
permission check refuses retries it once in that form, and stops only if it is
refused again; a call you deny stops it straight away. At the profile
confirmation the orchestrator prints these snippets filled in with your real
paths and commands. It never edits your settings itself; you choose what to
allow.

### `.auto-dev.yml`

The keys most runs touch in `.auto-dev.yml`: `iteration_budget` (revise rounds,
default 4), `mutation.max` (mutants per verifier pass, default 20, `0` = off),
`gates.post_plan` (turn the post-plan gate on), `branches` (`base`,
`prefix`), `ci` and `ci_timeout_minutes`, `worktree_files`, `security_docs`,
`symbol_lookup` (a code-index tool to use instead of grep),
`pr_review.inline_comments` (post the open and advisory review findings on the
PR), `checkpoint_events` (events one session writes before `next` checkpoints
it, default 80), and `jira.states`.
It can also set any profile key (`setup`, `gate`, `test_notes`, …) to override the
profile. Phase 1 validates the file with `scripts/validate-config.py`, so a
mistyped key is reported rather than silently ignored. Without
`security_docs`, `autodev.py init` uses the repo's `SECURITY.md`,
`.github/SECURITY.md` and `docs/security/*.md`; `security_docs: []` turns them
off, and a listed path the worktree doesn't have is dropped with a warning. See
`skills/auto-dev/references/profiles.md`.

## Human gates & integrations

Planning and build run unattended; the pipeline pauses for approval before
**opening the PR** and before the **main merge**
(plus an optional post-plan gate you can enable per run). The PR opens as a
**draft** unless you ask for it ready for review, and is marked ready before the
main gate. Its description follows the repo's default PR template when there is
one (never a template from a `PULL_REQUEST_TEMPLATE/` folder, which GitHub only
applies when asked), and links the Jira ticket. A checklist in the template
keeps its items word for word; the orchestrator ticks a box only when the spec,
the handoff or the description's own sections show it is true, and leaves the
rest for a person. With
`pr_review.inline_comments: true`, the review findings left open or advisory are
posted on the PR once it opens: inline at their line when it is in the diff, the
rest in one comment. The main gate doesn't count those posts as people's
comments, and CI that timed out or couldn't be watched shows there as not
monitored, never as green. Main is merged only via `gh pr merge` (respecting branch protection,
never `--admin`), with `--squash` by default — `--merge` if the repo disallows
squash, `--rebase` only when it is the one method allowed. Before the main gate
the pipeline fetches the PR branch and checks it still holds the code every
result was checked on. If someone pushed to it, the run stops and tells you,
rather than merging commits nothing checked. To ship those commits, bring them
into the worktree with the `git merge --ff-only origin/<branch>` command the stop
names and say `auto-dev continue`: the quality gate and the verifier run again,
a review pass covers what the commits (and the re-check) changed, `commit`
verifies the new head, and the main gate is asked again. The merge is locked to that commit with
`--match-head-commit`, so a push made after the check makes GitHub refuse the
merge instead of shipping unchecked code. The PR targets the base branch, and the
main merge is the only merge: auto-dev has no staging step, and ignores a
`staging` branch on origin. **Jira** integration is
status-transitions-only (In Progress → In Review → Done) and is skipped if no
ticket is given; the ticket's summary and description are stored at setup
(`autodev.py init --ticket-text-file`) and given to the Define agent verbatim,
since it has no Jira access. **CI** is monitored, with a bounded timeout, on the PR before
merge (and once more after the PR is marked ready, since some workflows skip
drafts), and again after the main merge to confirm the merge itself didn't
break the branch.

Three more pauses are **conditional** and fire only when their situation
arises: the **profile confirmation** (Phase 1, only on a repo with no saved
profile), the **Jira In Progress confirmation** (Phase 2, only with a ticket,
once the size check says the task fits one PR) and the **worktree cleanup
offer** (after the main merge). Everything
else runs without check-ins.

Declining is safe at every gate: `Stop` ends the run, `Hold` (where a gate offers
it) pauses a run you can resume later, and both leave the branch, the worktree,
and every artifact on disk. What each option does is in
`skills/auto-dev/references/tables.md`, and how a Jira ticket is moved in
`skills/auto-dev/references/gates-and-jira.md`.

## Install

Add this repo as a marketplace, then install the plugin. From GitHub:

```
/plugin marketplace add hubertursua/auto-dev
/plugin install auto-dev@auto-dev-marketplace
```

Or from a local clone, point at the directory that contains `.claude-plugin/`:

```
/plugin marketplace add ./auto-dev
/plugin install auto-dev@auto-dev-marketplace
```

As a safeguard, add the scratch directory to each project's `.gitignore` so its
planning artifacts can never be committed:

```
echo ".auto-dev/" >> .gitignore
```

Now ask Claude to "auto-dev" a task and the skill triggers. To keep a run from
stopping on permission prompts, add the rules in *Permissions for unattended
runs* under *Stack profiles*.

### Install without the plugin

If policy blocks plugins, link the agents into your user folder instead:

```
ln -s ~/Dev/auto-dev/agents ~/.claude/agents
```

This works only when `~/.claude/agents` does not exist yet. If it exists, link
each file into it:

```
ln -s ~/Dev/auto-dev/agents/*.md ~/.claude/agents/
```

The agents load as `auto-dev-<name>`, and the orchestrator falls back to that form.
Link `skills/auto-dev` into `~/.claude/skills/` too.

## Dependencies

Built-in tools only — no plugins required: `Task`/`Agent`, `Bash`,
`Read`, `Edit`, `Write`, `Grep`, `Glob`, `AskUserQuestion`, and the `Skill` tool
(the Phase 5 cleanup agent runs `/simplify` with it, the code reviewers
`/code-review`, and the security reviewer `/security-review`). `gh` must be on your `PATH`
and authenticated: Phase 1 checks, and stops before doing any work if it isn't.
Optional integration: the Atlassian MCP (Jira transitions). CI is watched with
`gh` alone (`gh pr checks` on the PR, `gh run list` after a merge, GitHub
Actions only); no CI provider's own CLI is needed.
The Jira tools are found by base name (`getJiraIssue`, …) with `ToolSearch`, so
the MCP server can be registered under any name; no match means Jira is skipped.
`autodev.py pr publish` opens the PR (with `gh pr create`) and refreshes its
description; no PR skill is used.
**Python 3.9+** with **PyYAML** (`pip install pyyaml`) is required:
`autodev.py init` checks both and stops before doing any work without them.
The helpers in `skills/auto-dev/scripts/` need only Python's standard library,
except `validate-config.py` (checks a repo's `.auto-dev.yml`, or a saved
profile with `--profile`, so a mistyped key is reported rather than silently
ignored) and `autodev.py init`, which read YAML. The orchestrator runs
`profile-path.py` itself (names the saved profile's path for a repo and says
whether it exists). `autodev.py` runs the others: `exclude-artifacts.py`
(makes `.auto-dev/` self-excluding and verifies it with git),
`check-staged.py` (the read-only check before each commit that nothing under
`.auto-dev/` is staged) and `check-fresh.py` (the read-only check that every
report was produced on the code as it is now; the verifier, cleanup agent,
review judge and security reviewer also run its `--print-tree` to stamp their
reports). Two are run by the Phase 5 verifier: `check-tests.py` (the
test-integrity audit) and `mutate.py` (applies mutants one at a time and
restores every file afterwards).
`skills/auto-dev/scripts/autodev.py` is the one entry point for the steps
4.0 moves out of the orchestrator's prose, so a user allows one command. It
keeps the run's state in
`.auto-dev/state.json`, which only it writes; `WORK_LOG.md` is generated from
it. Its subcommands: `init` (Phase 1's preflight, config, worktree,
seeded files, security directives and setup, run in the background past the
Bash tool's 10-minute limit), `resume` (finds the run to continue, or says to start fresh or ask),
`show`, `phase`, `note`, `size` (the Define agent's size check), `budget`
(spends a revise round once per correction, and refuses at zero with what to do
next), `gate` (records a gate decision; `hold` and `stop` are different states)
and `handoff` (writes `HANDOFF.md` and the message that ends a session). For
Phase 6: `commit` (re-checks freshness, stages every changed path by name, runs
`check-staged.py`, commits, and verifies the commit carries the checked code,
unstaging if anything fails), `ci-watch` (polls `gh pr checks` with a bound and
says green, red with links, pending, timed out or unwatchable; never assumes
green), `merge-pr` (`gh pr merge` locked with `--match-head-commit`, never
`--admin`, then confirms it merged), `pr-body` (generates the PR description
from the run's artifacts, with links at the checked commit, paths hidden and
output cut to fit, the ticket linked and the repo's own PR template's
sections added, leaving the Summary, the Assumptions, any template section
it can't fill and the template checklist's boxes to write; with
`--check`, lints one: strict sections, the checked commit, size, no internal
IDs, paths or secrets, the template checklist's items unchanged; the ID, term
and tier checks skip the test names, commands, output and verifier reasons it quotes word for word), `pr publish` (opens the one PR, or refreshes the
sections the pipeline writes in the live description, keeps overflowing output
in one comment edited in place, and reads the PR back) and `cleanup-worktree`. Parsers that turn a worker's artifact into a decision:
`check-manifest` (the acceptance tester's `MANIFEST.md` against `SPEC.md`: which
conditions to re-spawn it for), `eval-status` (`SPEC_EVAL.md` into `ALL_MET`,
`CORRECT`, `REPAIR` or `STOP`, with the survivors to carry forward), `apply-fix`
(applies a reviewer's exact old → new FIX blocks, all or nothing),
`spec-overlap` (refuses a brief or plan that copies `SPEC.md`'s wording),
`install-checks` (the verifier installs the sealed acceptance checks with it,
or copies them back over an edit with `--recheck`),
`votes` (plans the code-review re-votes and applies them to `CODE_REVIEW.md`,
adding each new must-fix finding to the pass's `corrections.md` for the coder,
except one about an acceptance check, which it names for the acceptance tester),
`security-reviewer` (which security reviewer to spawn: the sensitive one when
`SPEC.md` lists Security/Compliance criteria), `review-scope` (the snapshot a
correction is diffed against) and `gate-summary` (checks a gate's preconditions
and prints its summary and question). For workers: `brief` (writes a worker's
brief file from state (with `--out`, a profiler or pre-run lookup brief, before
any state exists), refusing when a value only the orchestrator can give is
missing, and prints the one-line prompt to spawn it with), `record` (checks the
result a worker wrote against the artifact it wrote, checks every other file it
wrote against its template and the planner's IMPLEMENTATION.md with
`spec-overlap`, and stops on a mismatch, saving the issues so the next `next` re-spawns that job with them; `brief
--retry <n>` does the same by hand) and
`check-artifact` (the workers with a shell check what they wrote against its
template before returning; `record` checks the rest). And `next`, the orchestrator's loop: it reads the state, the recorded results and the artifacts,
and prints the one next action (spawn these agents with these briefs, run this
command, ask this gate, stop and report, or end the session), with the command
to run after it. It does the mechanical steps itself: writing briefs, spending
a round before a correction, applying FIX blocks, checking the manifest,
reading the verdicts, planning and applying re-votes, taking the review
snapshot and generating the PR body. It also ends a long session at a
checkpoint. `next --explain` shows the action and the
rule that chose it without taking it (it writes and saves nothing). A step
`next` can't take is a stop that says why, never a bare failure.
Shared code lives in `skills/auto-dev/scripts/lib/`.
Also optional: a code-index tool a profile names under `symbol_lookup`, which the
`lookup` worker uses instead of `grep` to find a symbol's definition and
callers. The profiler names one only if the repo's ecosystem uses one and it is
on your `PATH`; without it, the worker uses `grep`.

## Models and effort

Each worker ships as its own agent type in `agents/`, which fixes its tools, model
and effort. The types name model families (`opus`, `sonnet`, `fable`), not
versions, so a new release is picked up without editing the plugin.

| Worker                                   | Agent type                       | Model · effort    |
| ---------------------------------------- | -------------------------------- | ----------------- |
| Profiler (first run on a repo)           | `auto-dev:profiler`              | `sonnet` · medium |
| Define agent                             | `auto-dev:define`                | `opus` · high     |
| Define reviewer                          | `auto-dev:define-reviewer`       | `opus` · high     |
| Planner                                  | `auto-dev:planner`               | `opus` · xhigh    |
| Plan reviewer                            | `auto-dev:plan-reviewer`         | `opus` · high     |
| Acceptance tester                        | `auto-dev:acceptance-tester`     | `opus` · high     |
| Coder (the build, all corrections)       | `auto-dev:coder`                 | `opus` · high     |
| Verifier                                 | `auto-dev:verifier`              | `opus` · high     |
| Cleanup agent                            | `auto-dev:cleanup`               | `sonnet` · medium |
| Code reviewer (×3 panel, and re-votes)   | `auto-dev:code-reviewer`         | `opus` · xhigh    |
| Review judge                             | `auto-dev:review-judge`          | `opus` · xhigh    |
| Security reviewer                        | `auto-dev:security-reviewer`     | `opus` · xhigh    |
| Security reviewer (sensitive paths)      | `auto-dev:security-reviewer-sensitive` | `fable` · high |
| Triager (red CI, human PR comments)      | `auto-dev:triager`               | `sonnet` · high   |
| Orchestrator lookups                     | `auto-dev:lookup`                | `sonnet` · medium |

The orchestrator runs on the session's model, whichever you pick; `sonnet` at
medium effort is enough for every session, since `next` makes the decisions and
the workers above do the judging. To retune a worker,
edit the `model:` / `effort:` frontmatter in `agents/<name>.md` and the table in
`SKILL.md`.

## The `.auto-dev/` scratch directory

Each run creates `.auto-dev/` holding the artifacts phases hand off:

| Path | Written by | Holds |
| ---- | ---------- | ----- |
| `profile.md` | Phase 1 | the resolved stack, where the profile came from, commands, branches, CI and Jira settings |
| `state.json` | `autodev.py`, Phase 1 onward | the run's state: phases, size check, gates, budget and every round spent; written only by `autodev.py` |
| `WORK_LOG.md` | generated from `state.json` | the ledger for people to read: phase status, size check, high-risk flag, gate decisions, budget |
| `setup.log`, `setup.json` | `autodev.py init` | the setup commands' output and result |
| `briefs/`, `returns/` | `autodev.py brief` and `next`, each worker | each worker's brief file, and the result it returned |
| `tmp/` | `autodev.py brief` | where workers spill long command output, a literal path in place of `$TMPDIR` |
| `blocked/` | Phases 4–6, coder | the build steps the coder stopped, for the planner |
| `pr-body.md`, `pr-output-comment.md` | Phase 6, `autodev.py next` | the generated PR description, and the command output moved out of it when it would be too long |
| `HANDOFF.md` | each session's end, and each checkpoint | the brief for the next session: the task, what is done, what comes next, the run files its orchestrator may open |
| `SPEC.md` | Phase 2 | the testable contract |
| `IMPLEMENTATION.md` | Phase 3 | the technical plan |
| `acceptance/` | Phase 3 | the sealed held-out checks, their `MANIFEST.md` (what each check covers, its level, its result on the old code) and `base-run/`, each condition's run on the old code; `AMBIGUOUS.md` lists a condition that reads two ways, for the Define agent |
| `SPEC_EVAL.md`, `evidence/` | Phase 5 | the verifier's verdicts and evidence tiers, and what it ran |
| `lint/` | Phase 5 | one report per quality-gate check |
| `review/`, `CODE_REVIEW.md`, `SECURITY_REVIEW.md` | Phase 6a | the panel's raw reports, the judge's code review, the security review, and the judge's required changes |
| `fixes/` | Phases 2–3 | the Define and plan reviewers' FIX blocks |
| `evidence/corrections.md` | Phase 5 | the verifier's required changes for the coder |
| `triage/` | Phase 6 | the triager's required changes for red CI and human blockers (`<ci\|human>-<n>.md`, for the coder), and the comments about a held-out check (`human-<n>-checks.md`, for the acceptance tester) |
| `lookups/` | any phase | lookup answers |

Each artifact's template is in `skills/auto-dev/templates/`. This is scratch, not part of your
project — the pipeline never commits it and makes the directory self-ignoring (a
`.gitignore` containing `*`, written into `.auto-dev/` itself) automatically, so
it cannot be staged even by a stray `git add -A`. (Note: a committed
`.auto-dev.yml` override file is separate and is *not* excluded.)

## Safety

Autonomous but bounded: the correction loop and the Define/plan re-reviews share
one iteration budget per task (default 4 revise rounds), and the pipeline stops
and reports
rather than committing a red build or weakening any security control. It also
stops if the mutation step may have left a planted bug in the tree, if the
build edited source inside a submodule, or if a commit holds code that no result
checked. It stops instead of spending another round when the verifier and the
acceptance tester disagree about a check, when a correction after the commit
changes nothing, or when a re-voter fails twice. A worker that stops on
purpose (`blocked`) is spawned once more, told to write any refused command out
in full; a stop on a worker (it stopped on purpose twice, failed twice, or
never returned) lasts until you resume:
then that worker is spawned again, and a refused `pr publish` is run
again the same way. A stop on a result (a red quality gate, an
impossible spec, a possibly planted bug, the budget used up) stays. A stop
because someone pushed to the PR branch lasts until you bring those commits
into the worktree; then they are re-checked before the main gate. If Define's size check returns OVERSIZED, it builds nothing and hands
the task back to you; Jira is left alone, and the worktree and branch stay in
place (see *Size check* above). It never asks you at a gate, or writes a PR description, on results
that were checked on other code. It refuses a
resolved quality gate with no test command in it, since that would pass Phase 5 by
having nothing to check. It merges to main only through a PR, only after your
approval, and if `gh pr merge` is refused it tells you why instead of working around
branch protection.

## Repository layout

```
.claude-plugin/         plugin.json (name, version) and marketplace.json
agents/                 one agent type per worker: tools, model, effort, and its whole brief
skills/auto-dev/
  SKILL.md              the orchestrator's spine: the rules and the `next` loop
  references/           one runbook per session (S1-plan, S2-build, S3-ship), the
                        shared tables, the profile schema and the Jira steps
  templates/            the artifact templates and the review rubric workers read by path
  scripts/              the Python helpers listed under Dependencies
    lib/                shared code for autodev.py (not run directly)
  evals/                evals.json (pipeline evals, with fixtures in files/)
                        and trigger-eval.json (should / shouldn't trigger)
tests/                  unit tests for the helper scripts, tools/ and the eval fixtures
  fake_gh/              a fake `gh` that plays back scripted responses
tools/check-repo.py     checks that the repo's files agree with each other
tools/check-pr.py       checks a branch name and PR title against the conventions
tools/eval-run.py       gives each pipeline eval its own branches of the fixture repo, and cleans them up
ruff.toml               lint config
.github/                CI workflow and PR template
CLAUDE.md               conventions for agents (and people) changing this repo
```

## Contributing

Before pushing, run the same checks CI runs:

```
ruff check .
python3 tools/check-repo.py
python3 -m unittest discover -s tests
```

To run a pipeline eval (`skills/auto-dev/evals/evals.json`), give it its own
branches of a GitHub-hosted fixture repo with `python3 tools/eval-run.py setup
--repo <owner>/<name> --run <run> --eval <id>`, and remove the run's PRs,
branches, run-named secrets and clones afterwards with `python3
tools/eval-run.py cleanup --repo <owner>/<name> --run <run>`. It needs push
access and `gh` with the `repo` scope (plus `workflow` to push a CI change),
never a token that can delete repos. The fixture's CI must run on PRs to any
branch and on pushes to `eval/**`.

Every change that alters how the pipeline behaves updates this README in the same
PR: the phase table, the worker and model table, the dependencies, the
`.auto-dev/` layout, and an *Upgrading* note for a version bump.

Branches are named `<type>/<short-kebab-description>` (`fix/mutate-mtime`), PR
titles `<type>: <summary>`, with types `feat`, `fix`, `docs`, `refactor`, `test`,
`chore` and `ci`. Every PR is squash-merged. No change may tie the pipeline to
one language: stack-specific commands and syntax belong in the run's profile, never in this repo. PR
conventions, the full README checklist, the language-agnostic rules and the
rules for changing a script are in `CLAUDE.md`.

## Upgrading from 3.9

4.0 is a breaking release.

- **One PR per run.** The scope call is gone. The Define agent now returns a size
  check: a task that fits one PR runs every step, and one that doesn't is handed
  back to you with suggested split lines. auto-dev no longer splits a task into
  sub-tasks or opens several PRs, and the TRIVIAL fast path is gone, so the
  planner writes every plan and the `coder-trivial` worker is removed.
- **Jira moves later.** A ticket moves to In Progress after the size check, not
  in Phase 1, so a task handed back never shows as started.
- **The ledger changed.** The run's state lives in `.auto-dev/state.json`,
  written only by `skills/auto-dev/scripts/autodev.py`; `WORK_LOG.md` is
  generated from it for people to read. Its header has `Worktree`, `Size` and
  `High risk` lines in place of `Control worktree` and `Mode`.
- **Python 3.9+ and PyYAML are required** by `autodev.py`.
- **Workers write the fixes.** The verifier and the review judge write the
  required changes the coder gets; the Define and plan reviewers write exact
  FIX blocks that a script applies; the planner settles a `BLOCKED` step; a new
  `triager` worker reads red CI and human PR comments. The orchestrator no
  longer writes correction briefs or edits `SPEC.md` and `IMPLEMENTATION.md`.
- **Briefs live in the agent files.** Each worker's instructions are in
  `agents/<name>.md` (its system prompt); `autodev.py brief` writes only the
  values that vary, and the spawn prompt is one line. Every worker ends with an
  `auto-dev-result` block, which `autodev.py record` checks against what it
  wrote. Templates and the rubric moved to `skills/auto-dev/templates/`.
- **`autodev.py next` drives the run.** It prints the one next action from the
  run's state, so the orchestrator no longer works out the order of steps,
  when to spend a round, or how to assemble the PR description; `pr publish`
  opens or refreshes the PR. `resume` now records that a new session holds the
  run, and un-holds a gate so it is asked again.
- **Any model runs the orchestrator.** `SKILL.md` is now the `next` loop and
  its hard rules, with one short runbook per session
  (`skills/auto-dev/references/S1-plan.md`, `S2-build.md`, `S3-ship.md`) and
  one file of shared tables. The old phase references are gone. No session
  asks you to switch models.
- **Checkpoints count events, not tokens.** `next` ends a long session after 80
  events (about 35 workers) and asks you to continue in a fresh session.
- **No more by-hand fallbacks.** Without python3 3.9+ and PyYAML the run stops
  in Phase 1. `resume-point.py` is removed: `autodev.py resume` finds the run.
- **`init` finds the security directives** from `security_docs`, or the repo's
  `SECURITY.md`, `.github/SECURITY.md` and `docs/security/*.md`.
- **The PR follows the repo's PR template and links the ticket.** The
  description gets the template's sections, with a box of its checklist ticked
  only when the run's files show it is true, and `pr_review.inline_comments`
  now posts once, after the PR opens, only the review findings left open or
  advisory (3.x posted the Phase 6a findings). `record` checks every file a
  worker says it wrote against its template, and refuses a plan, or a plan
  reviewer's FIX, that copies `SPEC.md`'s wording. A push to the PR branch can
  now be brought in and re-checked instead of ending the run.
- **No staging branch.** The staging gate, the direct merge into staging and
  `autodev.py merge-staging` are gone: the PR targets the base branch and the
  main gate is the only merge gate. A `staging` branch on origin is ignored, and
  `validate-config.py` refuses `branches.staging` in `.auto-dev.yml`: delete
  the key.

A run in flight does not resume on 4.0. Finish it on 3.9, or remove its worktree
and start again.

## Upgrading from 3.8

3.9 keeps the proof that the held-out checks failed on the old code (see *How
the build is verified*). The acceptance tester saves each condition's run on the
untouched tree as `acceptance/base-run/C<n>.txt`, and `MANIFEST.md` gains
*Covers* and *Level* columns. The orchestrator checks that every edge case has a
check or a reason it can't have one, and the verifier rates a condition Strong
only when its checks cover both its example and its edge case and the saved run
shows them failing for the right reason. The PR description quotes that run.

A run in flight resumes on 3.9. A run whose Phase 3 finished on 3.8 has no
`base-run/` and no *Covers* column, and the tester is not run again to add them.
The verifier trusts `MANIFEST.md`'s one-line *Base run* note, as before, and
says so in `SPEC_EVAL.md`; it reads each check to see what it covers. The PR
description then leaves out the old-code output. A verifier re-check on 3.9 can
rate a condition lower than 3.8 did (Adequate instead of Strong, when no check
covers its edge case or a check is below the level the spec asks for) and can
report a held-out check as too weak; a repair that follows spends a round as
usual.

## Upgrading from 3.7

3.8 rewrites the PR description for reviewers who don't know auto-dev (see
*How the build is verified*). The verifier now writes each `evidence/C<n>.txt`
in a fixed shape (expected, command, result, the last lines of output) for the
description to quote. A run in flight resumes on 3.8: only the description
changes. An evidence file written by an older verifier may have no output in
it; that requirement's entry then leaves the output block out. A PR opened on
3.7 gets the new sections the next time its description is refreshed.

## Upgrading from 3.6

3.7 stamps every report that judges the code (`SPEC_EVAL.md`, `lint/*.md`,
`CODE_REVIEW.md`, `SECURITY_REVIEW.md`) with a `Tree:` line naming the code it
checked, and adds `scripts/check-fresh.py`, which compares the stamps with the
code at each step that relies on them. The PR description gains a `Checked at
commit` line, and the main merge is locked to the checked commit with
`gh pr merge --match-head-commit`. If someone pushes to the PR before the main
gate, the pipeline checks their commits before asking you. A run in flight
resumes on 3.7: its reports have no stamp, which reads as stale, so the next
check re-runs the verifier, the quality gate and the reviews before going on.
Those re-runs spend no iteration budget.

## Upgrading from 3.5

3.6 removes the shipped stack profiles (Elixir, and the `default` discovery
fallback) along with the `profiles/` folder. The first run on each repo now has the new `profiler`
worker research the profile, and pauses once for you to confirm it, with an
offer to save it to `~/.config/auto-dev/profiles/` so later runs skip the
pause (see *Stack profiles*). `.auto-dev.yml` keeps every key; `stack:` now only
names the stack and no longer selects a profile, and the
validator warns when it is set without `setup` and `gate`. A repo whose `.auto-dev.yml`
sets both `setup` and `gate` runs as before, with no research and no pause.
A run in flight resumes on 3.6: Phase 1 never runs again on a resume, and its
`profile.md` is read as written.

## Upgrading from 3.4

3.5 moves the Elixir-only `dexter` rule out of `SKILL.md` into a new optional
profile key, `symbol_lookup`, which any profile or `.auto-dev.yml` can set.
Phase 1 records the resolved lookup in `profile.md`. A run in flight can resume
on 3.5: a `profile.md` written by 3.4 has no _Symbol lookup_ line, and the
orchestrator then uses `grep -n`.

## Upgrading from 3.3

3.4 adds Example, Edge and Verify by lines under every `SPEC.md` condition, an
ambiguity probe in the Define review, and a mutation step in the verifier
(`scripts/mutate.py`, the `mutation.max` key in `.auto-dev.yml`). A run with a
3.3 `SPEC.md` still works: the acceptance tester falls back to the condition's
own words, and the mutation step needs nothing from the spec.

## Upgrading from 3.2

3.3 moves the Phase 5 acceptance check from the orchestrator to two new workers:
the `acceptance-tester`, which runs at the end of Phase 3, and the `verifier`.
It adds `acceptance/` and `evidence/` to `.auto-dev/`, an evidence tier and a
test-integrity section to `SPEC_EVAL.md`, and `scripts/check-tests.py`. A run
whose Phase 3 is already done has no sealed checks: finish it on 3.2, or re-run
its Phase 3 on 3.3 before the build.

## Upgrading from 3.1

3.2 replaces the single PR reviewer, which ran after the PR was opened, with a
code review panel and a separate security review that run before the PR gate.
`PR_REVIEW.md` is replaced by `CODE_REVIEW.md` and `SECURITY_REVIEW.md`, and the
`pr-reviewer` agents by `code-reviewer`, `review-judge`, `security-reviewer` and
`security-reviewer-sensitive`. A run that has not reached Phase 6 resumes
normally. A run already in Phase 6 should be finished on 3.1.

## Upgrading from 2.x

3.0 restructures the pipeline from ten phases to six and changes the artifact set:
`TICKET.md` and `ACCEPTANCE_CRITERIA.md` are merged into `SPEC.md`,
`CODING_TODO.md` is dropped (the plan's build sequence is the coder's worklist),
and `IMPLEMENTATION_EVAL.md` is dropped along with the plan-adherence check. A run
started on 2.x cannot be resumed on 3.0 — its `.auto-dev/` and its `WORK_LOG.md`
phase table won't match. Finish in-flight runs before upgrading.
