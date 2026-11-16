# auto-dev

An orchestration skill for autonomous development.

It takes one coding task (a ticket, an idea or a spec) to a merged pull
request. It stops to ask you only at a few gates, chiefly before it opens the
PR and before it merges ([*Human gates*](#human-gates--integrations)).

Each job goes to a purpose-built **worker** (a subagent), and the workers hand
structured artifacts to each other through a `.auto-dev/` scratch directory.

It is **stack-agnostic**: it ships no stack profile. On the first run
in a repo it researches the setup and quality-gate commands, confirms them with
you and can save them for later runs. Jira and CI are optional; each is
detected automatically and skipped when absent.

Upgrading from an earlier version? See [`UPGRADING.md`](UPGRADING.md).

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

auto-dev also needs `git`, `gh` (signed in), Python 3.9+ and PyYAML: see
[*Dependencies*](#dependencies).

As a safeguard, add the scratch directory to each project's `.gitignore` so its
planning artifacts can never be committed:

```
echo ".auto-dev/" >> .gitignore
```

To keep a run from stopping on permission prompts, add the rules in
[*Permissions for unattended runs*](#permissions-for-unattended-runs): the
profile folder, the plugin's files and scripts, the run's worktree and your
repo's own commands.

### Install without the plugin

If policy blocks plugins, link the agents into your user folder instead
(replace `/path/to/auto-dev` with where you cloned this repo):

```
ln -s /path/to/auto-dev/agents ~/.claude/agents
```

This works only when `~/.claude/agents` does not exist yet. If it exists, link
each file into it:

```
ln -s /path/to/auto-dev/agents/*.md ~/.claude/agents/
```

The agents load as `auto-dev-<name>`, and the orchestrator falls back to that form.
Link the skill too:

```
ln -s /path/to/auto-dev/skills/auto-dev ~/.claude/skills/auto-dev
```

## What it does

Ask Claude to take a whole task off your plate, e.g. *"auto-dev this…"*,
*"take it all the way to a PR"*, *"pick up JIRA-1234 and ship it"*. The
orchestrator runs:

| Phase | Worker | Output |
|-------|--------|--------|
| 1 Setup | orchestrator, profiler (first run on a repo) | detect repo, load the saved profile or research one and confirm it with you, resolve ticket, isolated worktree + branch (or the worktree you started in), `.auto-dev/` |
| 2 Define | Define agent + reviewer | `SPEC.md` — context, testable conditions, assumptions, security criteria; plus the **size check** (too big for one PR → back to you) |
| 3 Plan | planner + plan reviewer, acceptance tester | `IMPLEMENTATION.md` — the technical how; `acceptance/` — held-out checks sealed from the coder (optional approval gate) |
| 4 Build | coder | code + tests given **only** the plan |
| 5 Verify | cleanup agent, then verifier | the sealed checks are installed, `/simplify` + the profile's quality gate run to green, then the verifier runs the held-out checks and audits the tests against the withheld spec → `SPEC_EVAL.md` (correction loop to Phase 4: coder, cleanup, verifier) |
| 6 Ship | orchestrator, 3 code reviewers + judge, security reviewer, triager | commit + **draft PR** first (CI starts there), then the code review panel and security review on it alongside CI (each correction is committed on top), then the ready-for-review gate, the PR marked ready, merge to main + Jira Done, pausing at each gate |

Workers never negotiate the contract between themselves. A coder that finds
a plan step wrong builds it the way that works and records the deviation for
you to see. A later step that finds the spec wrong, or a check the acceptance
tester and another worker disagree on, stops the run and asks you (see
[*How the build is verified*](#how-the-build-is-verified)).

When the run stops (a red quality gate, an impossible spec, a worker that
failed twice), it asks you how to go on instead of ending: tell it how to fix
the cause and a **fixer** does exactly that, or say you fixed it yourself, sign
the result off, talk it through, or leave it. Only the step that stopped runs
again (see [*Human gates & integrations*](#human-gates--integrations)).

## Agent hierarchy

The main agent is the orchestrator and never writes code. It spawns a fresh
worker for each job, and they hand off through files in `.auto-dev/`, never
shared memory. It doesn't choose the order of steps either: it runs
`autodev.py next`, does the one action printed, and runs it again. It doesn't
judge the build or write correction briefs; the workers that found a problem
write those, and the orchestrator passes them on unedited. It never reads the
code (a `lookup` worker answers its questions of fact in a line, and declines
to say whether code is right, since the orchestrator would act on that verdict
unchecked), and it sees the spec only as the parts `pr-write.md` quotes for the
PR description.
The run's history lives in `.auto-dev/state.json`, which only `autodev.py`
writes, and each judge is a fresh worker that sees only what its brief names.

```
Orchestrator (main agent) ── runs the `next` loop and the human gates; never reads code
│
├─ Phase 1  Setup ......... detect repo, profile (saved, or profiler + your OK), ticket, worktree
├─ Phase 2  Define agent .. SPEC.md — the testable contract + SIZE CHECK  (→ reviewer)
├─ Phase 3  Planner ....... IMPLEMENTATION.md — the technical how  (→ reviewer)
│           Acceptance tester  held-out checks from the spec, proven to fail, sealed [optional gate]
├─ Phase 4  Coder ......... code + tests (given only the plan)
├─ Phase 5  Cleanup + verifier  /simplify → quality gate → RUN the checks vs. the withheld spec
└─ Phase 6  orch + reviewers  draft PR → code review panel ∥ security review ∥ CI → [GATE] ready → [GATE] main
            Triager ......... reads red CI logs and human PR comments, so the orchestrator never does
            Planner ......... settles a step the coder stopped (Phases 4–6)
            Acceptance tester  repairs a questioned check, or says why it is right (Phases 4–6)
            Lookup .......... reads code, diffs or long files and answers the orchestrator in a line
            Fixer ........... at a stop, does what you said to fix it, and nothing more (any phase)
```

Two documents describe the work. `SPEC.md` answers *did we build the right
thing*; `IMPLEMENTATION.md` answers *did we build it the way we decided*. A plan
executed faithfully can still miss the outcome, so the pipeline checks both.

The coder builds from the plan, never the spec. The plan must cover every spec
condition, so nothing is hidden from the coder except the spec's wording: the
coder can't satisfy a check by echoing that wording back in a test name.

## How the build is verified

Tests the coder wrote are the coder's own evidence, so they can't be the main
proof. Agents are known to mark work done too early and to make tests pass by
weakening them. Verification is built around that:

- **A spec written to be tested.** Every condition in `SPEC.md` has a concrete
  example (Given / When / Then), its tricky edge case, and how it should be
  verified. The Define reviewer flags any condition that two different
  implementations could both satisfy, and the Define agent rewrites it.
- **Held-out checks, proven to fail first.** Before any code is written, an
  acceptance tester writes black-box tests from the spec alone: one for each
  condition's example and one for its edge case. Every check for new behavior
  must **fail on the untouched code for the right reason**, and the tester
  saves that run. Each check goes where a developer would put that test: into
  the test file the code already has, or a new test file only for code that
  has none, so the PR adds no test files just for the checks. The checks are
  then sealed out of the worktree; the coder never sees them
  (`agents/acceptance-tester.md`).
- **Put back after the build, unchanged.** Before cleanup, the pipeline puts
  each check back into its file among the coder's own changes to it
  (`skills/auto-dev/scripts/lib/sealed.py`); when it can't, the acceptance
  tester adds its tests to the coder's file. From then on only the acceptance
  tester may change a check: `record` refuses a coder or cleanup result that
  edits one.
- **Only the workers that write code change it.** The ones that write or review
  the spec and the plan, judge the review, or triage CI and PR comments never
  change a repo file. `brief` notes the tree each one starts from, and
  `record` refuses a result that changed a file outside `.auto-dev/` (one git
  ignores isn't compared) and puts the file back, keeping the worker's version
  in `.auto-dev/tree/`. A change someone else could have made is left alone:
  a file written after the worker returned, a commit, anything while another
  worker was out, or while setup ran
  (`skills/auto-dev/scripts/lib/tree_guard.py`).
- **An independent verifier that runs things.** After cleanup, a fresh
  verifier **runs** the checks, without seeing the plan or the coder's report.
  Each condition gets a verdict and an evidence tier:
  - **Strong:** the checks pass, cover the example and edge case at the level
    the spec asks, and their run on the old code, saved before the build,
    showed what it should (a check for new behavior failing for the right
    reason).
  - **Adequate:** the checks pass, and for what they don't prove, the
    verifier ran something itself and saw what it predicted.
  - **Weak:** a code citation, which never counts as met.

  A repaired check can't be re-run on the old code, so its condition is
  Adequate at most. A condition no agent can observe is handed
  to you at the ready-for-review gate as a manual check. The routine steps of each pass are
  one script call (`autodev.py verify prep`), so the verifier spends its turns
  on the judging (`agents/verifier.md`).
- **A test-integrity audit.** `skills/auto-dev/scripts/check-tests.py` flags
  deleted, skipped or focused tests, removed assertions, new tests that assert
  nothing, changes to the test runner's config, and any edit to a sealed
  check, even one sharing a file with the coder's tests. Each finding must be
  justified by the spec or it goes back to the coder.
- **Targeted mutation testing.** The verifier plants small bugs in the
  changed lines with `skills/auto-dev/scripts/mutate.py`, which restores every
  file afterwards. A planted bug no test catches, on a line a condition
  depends on, is a test gap and goes back to the coder. The bugs are chosen
  once and kept for every pass: at most 20 in all, set by `mutation.max` in
  `.auto-dev.yml` (`0` turns it off). A re-check runs again the mutants no
  test caught, those in files changed since the last pass, and new ones; the
  rest keep their result, unless an existing test was edited or deleted, a
  skip or focus marker was added, or the runner config changed, which re-runs
  them all. `autodev.py mutants run` runs them in the background, sized by a
  timed test run
  (`skills/auto-dev/scripts/lib/cmd_mutants.py`, `lib/mutation_run.py`).
- **The contract is yours to change.** Later work may show that a plan
  step, a held-out check or the spec itself is wrong. A wrong plan step is
  the coder's to fix as it builds: it builds the step the way that works and
  lists each deviation and why in `deviations/coder-<n>.md`, and the ready-for-review gate
  shows you every one. A check another worker calls wrong goes to the
  acceptance tester, which repairs it; if the tester finds the check right,
  the run stops and asks you. A criterion a later worker finds wrong or
  missing (the verifier, the review judge, a security reviewer, or the
  triager from a PR comment) is listed in `spec-problems/<worker>-<n>.md`,
  and the run stops and asks you before it acts on that result: no worker
  changes `SPEC.md`. You say how to change it (the fixer does that, then the
  verifier checks again), or sign off to keep it as written; every later
  worker that judges it is told what you kept.
- **Re-checked after every change.** Cleanup (`/simplify` and the quality gate)
  runs before the verifier, so the verifier checks the code that ships, and
  both run again after every fix.
- **Every result names the code it checked.** Each verdict, quality-gate report
  and review report carries the git tree hash of the code it checked.
  `skills/auto-dev/scripts/check-fresh.py` compares those stamps with the
  current code before anything relies on them, and a stale result is run
  again (without spending the iteration budget). If a re-run is stale again at
  once (something keeps rewriting the code), the run stops.
- **A PR description a stranger can check.** It is written for a reviewer who
  has never heard of auto-dev: for each requirement it links the test written
  before the code, with that test's result on the old code and now. It also
  lists every flagged test change with its reason, says how many planted bugs
  the tests caught, and turns each manual check into steps.

The verifier's and tester's full rules are in `agents/verifier.md` and
`agents/acceptance-tester.md`.

## Three sessions, not one

The pipeline is split into three sessions: **Plan** (phases 1–3), **Build**
(4–5) and **Ship** (6). At the end of each it writes `.auto-dev/HANDOFF.md`, a
short brief for the next one, and stops. Start a fresh session and say
`auto-dev continue` to pick up. Started inside a run's worktree, it continues
that run; elsewhere, it asks when several runs are open. Each session follows a short runbook
(`skills/auto-dev/references/S1-plan.md`, `S2-build.md`, `S3-ship.md`) and is
never asked to judge, so any model can run it.

The orchestrator's context is the real cost: every added turn makes every later
turn more expensive. So it delegates reads to workers, and each worker's reply
is its result block alone (its files hold the rest; a few lines above the block
only when it stopped, or has something the user must be told). `next` records
each result itself before it decides, checking it against the worker's files,
so a worker costs no extra orchestrator turn; a refused one goes back to the same
worker, which fixes the listed issues in what it wrote rather than redoing the
job. `next` also ends a long
session at a **checkpoint** after 80 recorded events (about 35 workers;
`checkpoint_events` in `.auto-dev.yml` changes it). Nothing crosses a session
boundary except `.auto-dev/` and the git tree, which also makes an interrupted
run resumable: `autodev.py resume` finds it, and `next` picks up where it
stopped.

## Size check: one PR, or back to you

The Define agent says whether the task fits one PR:

- **FITS** — the pipeline runs every step, the same way for every task: **11
  worker roles** (roles, not spawns). The profiler runs only when the repo has
  no saved profile, the triager only when CI fails or a person comments,
  `lookup` when the orchestrator needs a fact from the code, and the fixer
  only when you tell a stopped run how to fix it. When `SPEC.md`
  has security criteria, the security reviewer for sensitive paths takes the
  regular one's place.
- **OVERSIZED** — several independent deliverables or subsystems, or a large
  file count. auto-dev builds nothing and hands the task back with its reasons
  and suggested lines to split along. Jira is left alone, and the worktree and
  branch stay, with the commands to remove them. Split the task and run
  auto-dev on each part, or answer the stop: sign it off to build it as one
  PR anyway, or tell the fixer how to narrow `SPEC.md` (a new session can
  answer too).

Define also flags a task as **high-risk** (security criteria, auth, payments,
access control or a data migration), which turns on the post-plan gate.

## Review on the draft PR

The verified build is committed and pushed as a **draft PR before any
review**, so CI runs while it is reviewed; its description says it is not
reviewed yet. (A repo that must not push unreviewed code sets `gates.open_pr:
true` in `.auto-dev.yml`: the run then asks before the first push.) The draft
is reviewed twice, at the same time:

1. **Code review panel.** Three reviewers run `/code-review` on the changed
   files independently, at the effort the plan sets for the review (see
   [*Models and effort*](#models-and-effort)). `next` merges their reports into
   one list, and a judge decides which findings are one, checks each one's
   trigger path in the code and writes the fix for each must-fix finding, in a
   short `JUDGMENT.md`. `autodev.py review-build` then applies the rubric's
   vote table and writes `CODE_REVIEW.md` with its counts, history and
   overall confidence, so the judge never retypes the report. A finding that
   could be must-fix but only one reviewer raised goes to the other two for a
   re-vote.
2. **Security review.** A security reviewer runs `/security-review` over the
   whole change, and the judge double-checks every High or Medium finding.
   When `SPEC.md` has security criteria (a change on a sensitive path), a
   reviewer that weights those paths hardest does it.

One correction fixes every must-fix finding from both, for one round of the
iteration budget; it is reviewed before it is committed on top and pushed.
With no round left before the PR is marked ready, the run goes on to the
ready-for-review gate, which names every must-fix finding still open; after
that (a red CI fix, a PR comment), a must-fix finding with no round left stops
the run. A finding about a held-out check goes to the acceptance
tester, never the coder; if the tester finds the check right, the run stops
and shows you both sides. A problem that lies in `SPEC.md` rather than the code
goes in a reviewer's report; the judge confirms it for the panel, and once the
pass has settled the run stops and asks you.
After the correction, the full panel reviews it again. Once the reviews
settle, the PR's description is published again with them, and you decide at
the ready-for-review gate whether the PR leaves draft. A re-review of a correction skips the nested `/code-review` and `/security-review` skills: the
reviewers follow the correction and everything downstream of it themselves.
When the judge passes a security lead from the panel on, a security run that
skips `/security-review` checks just those leads.

A **rubric** (`skills/auto-dev/templates/rubric.md`) decides what must be fixed:

- **Code findings.** Only correctness bugs, missing or weak tests, and a broken
  held-out check can be must-fix, and each needs a concrete trigger path and 2
  of the 3 reviewers' votes. Scope, performance and design findings are
  advisory. Problems the change didn't introduce are dropped.
- **Test gaps, whole.** A test-gap finding lists every reachable case no test
  covers, so the coder closes the whole gap in one round.
- **Security findings.** One this change introduced, rated High or Medium with
  a traced path the judge confirms, is must-fix; a Low one is advisory. A High
  or Medium one that was already there is shown to you at the ready-for-review gate, to note
  as a follow-up or ignore; this PR never fixes it.
- **Confidence.** Every finding and every report carries a confidence level. A
  low-confidence report (say, two reviewers failed, or the security reviewer
  couldn't finish) is flagged at the gate, never
  shown as a clean pass.

Once the draft PR is open, a **triager** reads red CI logs, and once it is
marked ready, people's review comments,
so their text never reaches the orchestrator and can't steer the run. It sends
only real code problems to the coder (and comments about a held-out check to
the acceptance tester). A red CI run the code can't fix (a missing secret,
infrastructure, a flaky test, an unknown cause) stops the run before Jira
moves; once the cause is fixed and CI re-run, `auto-dev continue` watches it
again. The reviewers'
instructions are in `agents/code-reviewer.md`, `agents/review-judge.md`,
`agents/security-reviewer.md`, `agents/security-reviewer-sensitive.md` and
`agents/triager.md`.

## Human gates & integrations

Planning and build run unattended. The draft PR opens without asking, so CI
runs while the change is reviewed. The pipeline pauses for approval:

- before the PR leaves draft (the **ready-for-review gate**, once the reviews
  on the draft have settled), and
- before the **main merge**,
- plus an optional **post-plan gate** (on for high-risk tasks, or with
  `gates.post_plan`) and an optional **open-the-PR gate** before the first
  push (with `gates.open_pr`, for repos that must not push unreviewed code).

Three more pauses fire only when their situation arises: the **profile
confirmation** (a repo with no valid saved profile and no `.auto-dev.yml`
that declares one), the **Jira In Progress confirmation** (only with a ticket, once
the size check says the task fits, and skipped when the ticket is already in
progress; you can also answer that it is), and the
**worktree cleanup offer** (after the final report; never for a worktree you
made).

Declining is safe at every gate: `Stop` ends the run; `Hold`, at the
open-the-PR, ready-for-review and main gates, pauses it so you can resume later. Both leave the branch, the worktree and every artifact on
disk. What each option does is in `skills/auto-dev/references/tables.md`.

- **The PR** opens as a draft before any review, its description saying it is
  not reviewed yet; once the reviews settle the description is published
  again with them, and the PR is marked ready after the ready-for-review gate.
  Its description follows the repo's default PR template (never one from a
  `PULL_REQUEST_TEMPLATE/` folder) and links the Jira ticket. A checklist box in
  the template is ticked only when the run's files show it is true.
  With `pr_review.inline_comments: true`, the review findings left open or
  advisory are posted on the PR once the reviews settle.
- **The merge** goes only through `gh pr merge`, respecting branch protection
  and never with `--admin`: `--squash` by default, `--merge` if the repo
  disallows squash, `--rebase` only when it is the one method allowed. It is
  locked to the checked commit with `--match-head-commit`. If someone pushed to
  the PR branch, the run stops and tells you how to bring those commits in to
  be checked. auto-dev has no staging step; the PR targets the base branch.
- **Jira** only moves the ticket (In Progress → In Review → Done), and is
  skipped without a ticket. The ticket's text is stored at setup and given to
  the Define agent, which has no Jira access
  (`skills/auto-dev/references/gates-and-jira.md`).
- **CI** is watched with a time limit on the draft PR, again once it is marked
  ready (some workflows skip drafts), and after the merge. A draft with no
  check after a grace period doesn't hold the run up. CI that timed out, never
  ran or couldn't be watched is shown as not monitored, never as green.
- **Deviations from the plan** the coder recorded are listed in the
  ready-for-review and main gate summaries and the final report, each with its
  reason.
- **A stop asks how to go on.** When the run stops on a result or a worker,
  you answer (any reply other than a pick is an instruction):
  - **Your instruction:** the fixer agent does what you said, and nothing
    more. Your words are its consent: it may change the code, or the run's
    `SPEC.md`, plan or held-out checks when you name them. If the fix needs
    more than you said, it changes nothing and asks you to approve its
    proposal. `record` refuses its report if it leaves out a file it changed,
    the run's settings in `state.json` included; when its result is anything
    but `FIXED`, all of it is put back, settings too.
    It changes a held-out check through the pipeline, never by hand: it edits
    an installed check in the worktree and `record` seals it again, and
    `autodev.py amend-checks` drops, adds or renames a check's `MANIFEST.md` rows, seals a new check file, or reseals one before the install.
    Auto mode can refuse an agent's own edit of those files as test removal;
    the `autodev.py` permission rule below covers the command.
  - **I fixed it myself:** only the step that stopped runs again.
  - **Sign off and go on:** the result is accepted as if it passed, and the
    sign-off is named in the ready-for-review gate summary and the PR body. At a wrong
    criterion or a disputed check, signing off keeps it as written, and every
    later worker that judges it is told so. Never on red CI,
    a confirmed security finding, a possibly planted bug, stale results or
    commits the pipeline didn't check.
  - **Let's talk it through**, or **leave it stopped** (a new session asks
    again).

  Re-running the stopped step costs no round. Whatever a fix changed is
  checked again before the run goes on: the quality gate and the verifier on
  changed code, the verifier's first pass on a changed spec or plan, and in
  Phase 6 a review of the changed files
  (`skills/auto-dev/references/tables.md`, _Overriding a stop_).

## Stack profiles

A **profile** says how a repo installs its dependencies and which commands make
up its quality gate (test, lint, format check, type check, build). Phase 1 gets
one in this order:

1. **A saved profile.** If you saved one for this repo on an earlier run, Phase 1
   loads it without asking. If it lists a check whose tool the repo never
   adopted, the run drops that check and tells you, so you can fix the file.
   An invalid saved profile is researched again, and you're offered to
   overwrite it.
2. **A committed `.auto-dev.yml` that sets both `setup` and `gate`.** The repo
   has declared its profile, so there is nothing to research.
3. **Research.** Otherwise the `profiler` worker reads the repo (CI config, task
   runners, manifests, lockfiles, contributing docs) and drafts a profile, citing
   the file and line each command came from and naming anything it guessed. The
   run shows you the draft and asks: save it for this repo, use it for this run
   only, change something, or stop.

`.auto-dev.yml` is applied on top in every case. The schema is in
`skills/auto-dev/references/profiles.md`.

Workers run the profile's checks through `autodev.py run gate|test`, which runs
the command exactly as the profile lists it, in the run's worktree, and saves
its output, so no worker has to rewrite a command with `cd`, which a
permission check refuses. A check can also give a scoped form (`files`, with
`<files>` where the paths go), so a worker can run it on only the files it
changed or wrote; the profiler looks for one.

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
research it again. It holds only how the stack installs and checks itself;
repo policy such as branches and the iteration budget stays in `.auto-dev.yml`.

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

A plugin install keeps its files under `~/.claude/plugins/cache/`, and a run
works in a worktree next to your repo, so both need rules too. Add these to
`~/.claude/settings.json`, replacing `<home>` with your absolute home folder
(a Bash rule matches the command's text, so `~` does not work there):

```json
{
  "permissions": {
    "allow": [
      "Read(~/.claude/plugins/cache/auto-dev-marketplace/auto-dev/**)",
      "Bash(python3 <home>/.claude/plugins/cache/auto-dev-marketplace/auto-dev/*/skills/auto-dev/scripts/autodev.py *)",
      "Bash(python3 <home>/.claude/plugins/cache/auto-dev-marketplace/auto-dev/*/skills/auto-dev/scripts/profile-path.py *)",
      "Bash(python3 <home>/.claude/plugins/cache/auto-dev-marketplace/auto-dev/*/skills/auto-dev/scripts/validate-config.py *)",
      "Bash(python3 <home>/.claude/plugins/cache/auto-dev-marketplace/auto-dev/*/skills/auto-dev/scripts/check-fresh.py *)"
    ]
  }
}
```

- The `autodev.py` rule also lets workers run the profile's gate and test
  commands through `autodev.py run`, and lets the fixer change held-out checks
  with `autodev.py amend-checks` while the fix you asked for is open. It runs only the commands in the profile
  you confirmed, never one a worker writes.
- One rule per script, not `scripts/*`, so you can leave one out. The
  `autodev.py` rule also covers the test-integrity audit and mutation testing:
  `autodev.py verify prep` runs `check-tests.py`, and `autodev.py mutants run`
  runs `mutate.py`, which edits files in the run's worktree to plant bugs and
  restores them. `mutation.max: 0` turns mutation off.
- The `*` for the version survives plugin upgrades. It also matches `..` and
  spaces, so pin the version (`auto-dev/<version>/skills/…`) to be strict, and
  redo the rules after each upgrade. Never start a rule with `*`: it allows
  any folder.
- Installed without the plugin? Use `<home>/.claude/skills/auto-dev/scripts/<name>.py *`.
- Each run works in a worktree beside the main checkout
  (`../<repo>-<slug>`), outside the folder Claude Code started in. Add
  `Read(//<parent>/<repo>-*/**)` and `Edit(//<parent>/<repo>-*/**)`, where
  `<parent>` is the absolute path of the folder holding your repo (for a
  worktree you made yourself, allow its own path instead). With the
  Bash sandbox on, also add that parent folder to `allowWrite`.

`autodev.py init` runs the setup commands and `autodev.py run` the gate, so
the `autodev.py` rule covers the profile's commands during a run. To run the profile's commands yourself
without prompts, add them to the main checkout's `.claude/settings.local.json`
(or to the worktree you made, when the run started in one), which applies to
that repo only. Example in TypeScript:

```json
{
  "permissions": {
    "allow": [
      "Bash(npm ci *)",
      "Bash(npm test *)"
    ]
  }
}
```

A rule matches the command's text, so copy the commands exactly as the profile
lists them. Optional: `Bash(gh run list *)`, `Bash(gh run view *)`,
`Bash(gh pr view *)` and `Bash(gh repo view *)` for the CI and PR lookups
(`gh api` can also write, so allow it only if you accept that), the Jira tools
if you use a ticket (`mcp__<server>__getJiraIssue` and the transition tools),
and `Skill(simplify)`, `Skill(code-review)` and `Skill(security-review)` for
the cleanup and review workers. At the profile confirmation the orchestrator
prints these snippets filled in with your real paths and commands. It never
edits your settings itself.

### `.auto-dev.yml`

The keys most runs touch:

| Key | What it sets |
| --- | ------------ |
| `iteration_budget` | revise rounds per task (default 4) |
| `mutation.max` | mutants kept across the verifier's passes (default 20, at most 50, `0` = off) |
| `gates.post_plan` | turn the post-plan gate on |
| `gates.open_pr` | ask before the first push (off: the draft PR opens before any review) |
| `branches` | `base` and `prefix` |
| `ci`, `ci_timeout_minutes` | the CI provider, and how long to watch it (default 30 minutes) |
| `worktree_files` | gitignored files (an `.env`, say) to copy into the run's worktree |
| `security_docs` | the repo's security directives (default: `SECURITY.md`, `.github/SECURITY.md`, `docs/security/*.md`; `[]` = none) |
| `symbol_lookup` | a code-index tool to use instead of `grep` |
| `pr_review.inline_comments` | post the open and advisory review findings on the PR, once the reviews settle |
| `checkpoint_events` | events one session records before it checkpoints (default 80) |
| `jira.states` | the board's state names for In Progress, In Review and Done |

It can also set any profile key (`setup`, `gate`, `test_notes`, …) to override
the profile. Phase 1 validates the file with `scripts/validate-config.py`, so a
mistyped key is reported rather than silently ignored.

## Dependencies

- **Claude Code's built-in tools** only, no other plugins. The `Skill` tool runs
  `/simplify`, `/code-review` and `/security-review`.
- **git**, for the run's worktree and branch.
- **`gh`** on your `PATH` and authenticated. It opens and merges the PR and
  watches CI: any CI that reports checks to GitHub, such as GitHub Actions or
  CircleCI. Phase 1 stops if it is missing, signed out, or `origin` isn't on
  GitHub.
- **Python 3.9+** with **PyYAML** (`pip install pyyaml`). `autodev.py init`
  stops if either is missing.
- **Optional:** the Atlassian MCP for Jira (found by tool name, so it can be
  registered under any server name), and a code-index tool named by the
  profile's `symbol_lookup`.

The helper scripts in `skills/auto-dev/scripts/` use only Python's standard
library, except where they read YAML:

| Script | What it does |
| ------ | ------------ |
| `autodev.py` | the one entry point: keeps the run's state in `.auto-dev/state.json`, and `autodev.py next` prints the orchestrator's next action. `autodev.py --help` lists every subcommand |
| `validate-config.py` | checks `.auto-dev.yml`, or a saved profile with `--profile` |
| `profile-path.py` | prints the saved profile's path for a repo and whether it exists |
| `exclude-artifacts.py` | makes `.auto-dev/` ignore itself and checks it with git |
| `check-staged.py` | before each commit, checks nothing under `.auto-dev/` is staged |
| `check-fresh.py` | checks each report was produced on the code as it is now |
| `check-tests.py` | the verifier's test-integrity audit, run by `autodev.py verify prep` |
| `mutate.py` | the verifier's mutation testing, run by `autodev.py mutants run`; restores every file afterwards |

## Models and effort

Each worker is its own agent type in `agents/`, which fixes its tools, model and
effort. The types name model families (`opus`, `sonnet`, `haiku`), not versions,
so a new release is picked up without editing the plugin.

| Worker                                   | Agent type                       | Model · effort    |
| ---------------------------------------- | -------------------------------- | ----------------- |
| Profiler (first run on a repo)           | `auto-dev:profiler`              | `sonnet` · high   |
| Define agent                             | `auto-dev:define`                | `opus` · high     |
| Define reviewer                          | `auto-dev:define-reviewer`       | `opus` · high     |
| Planner                                  | `auto-dev:planner`               | `opus` · xhigh    |
| Plan reviewer                            | `auto-dev:plan-reviewer`         | `opus` · high     |
| Acceptance tester                        | `auto-dev:acceptance-tester`     | `opus` · high     |
| Coder (the build, all corrections)       | `auto-dev:coder`                 | `opus` · high     |
| Verifier                                 | `auto-dev:verifier`              | `opus` · high     |
| Cleanup agent                            | `auto-dev:cleanup`               | `sonnet` · high   |
| Code reviewer (×3 panel, and re-votes)   | `auto-dev:code-reviewer`         | `opus` · high     |
| Review judge                             | `auto-dev:review-judge`          | `opus` · xhigh    |
| Security reviewer                        | `auto-dev:security-reviewer`     | `opus` · xhigh    |
| Security reviewer (`SPEC.md` has security criteria) | `auto-dev:security-reviewer-sensitive` | `opus` · xhigh |
| Triager (red CI, human PR comments)      | `auto-dev:triager`               | `sonnet` · high   |
| Orchestrator lookups                     | `auto-dev:lookup`                | `haiku` · medium  |
| Fixer (your instruction at a stop)       | `auto-dev:fixer`                 | `opus` · high     |

`next` names each type as `auto-dev:<worker>`; a plugin install lists them as
`auto-dev:auto-dev-<worker>`, and the orchestrator maps one to the other.

The levels start from Anthropic's guidance for the Claude 5.5 models
([choosing a model](https://platform.claude.com/docs/en/about-claude/models/choosing-a-model)),
which says to start at each model's default and tune from your own evals.
The last three below were then checked against small scenarios with planted
bugs, where each found as much as the stronger setting it replaced:

- **`sonnet` workers run at `high`, Sonnet's default.** At `medium`, Sonnet 5.5
  scores 7 to 15 points lower on Anthropic's coding benchmarks
  ([optimizing for cost and intelligence](https://platform.claude.com/docs/en/about-claude/models/optimizing-for-cost-and-intelligence)).
- **`opus` workers run above Opus's default (`medium`).** A worker's miss
  costs a correction round. `xhigh` is kept for the plan, the judge and the
  security reviews, which the rest of the run builds on or ships.
- **The code reviewers run at `high`.** In the scenarios, `high` found every
  planted bug that `xhigh` did, in a little over half the time; the plan
  still asks for `xhigh` on a large change.
- **The sensitive-path security review runs on `opus` · `xhigh`, not `fable`.**
  Both found every planted hole, and `fable` costs about 2.5 times as much per
  token.
- **Lookups run on `haiku`.** Haiku answered as accurately as Sonnet, for a
  fraction of the cost.

The orchestrator runs on the session's model; `sonnet` at medium effort is
enough, since `next` makes the decisions and the workers do the judging. To
retune a worker, edit the `model:` / `effort:` frontmatter in `agents/<name>.md`
and the tables in `SKILL.md` and this README.

The code reviewers' effort is set per run. The planner writes a
`Review effort:` line in `IMPLEMENTATION.md`: `high` by default, `xhigh` for
a large change (many files, or logic across several modules). The
orchestrator passes it to each code reviewer, overriding the agent file's
`high`. On a first review, each
reviewer runs its nested `/code-review` at that effort too; a correction's
re-review skips it.

## The `.auto-dev/` scratch directory

Each run creates `.auto-dev/` in its worktree for the artifacts phases hand off.
It is scratch, not part of your project: the pipeline never commits it, and
writes a `.gitignore` containing `*` inside it, so even a stray `git add -A`
can't stage it. A committed `.auto-dev.yml` is separate and is *not* excluded.
Each artifact's template is in `skills/auto-dev/templates/`.

| Path | Written by | Holds |
| ---- | ---------- | ----- |
| `profile.md` | Phase 1 | the resolved stack, where the profile came from, commands, branches, CI and Jira settings |
| `state.json` | `autodev.py` only | the run's state: phases, size check, gates, budget and every round spent |
| `WORK_LOG.md` | generated from `state.json` | the same, for people to read |
| `setup.log`, `setup.json` | `autodev.py init` | the setup commands' output and result |
| `briefs/`, `returns/` | `autodev.py`, each worker | each worker's brief, and the result it returned |
| `tmp/` | workers; `autodev.py run` (`tmp/run/`) | long command output |
| `HANDOFF.md` | each session's end, and each checkpoint | the brief for the next session |
| `SPEC.md` | Phase 2 | the testable contract |
| `IMPLEMENTATION.md` | Phase 3 | the technical plan |
| `fixes/` | Phases 2–3 | the Define and plan reviewers' FIX blocks |
| `acceptance/` | Phase 3 (the tester; its repairs in Phases 4–6) | the sealed held-out checks (`files/<path>.sealed`, with `<path>.base`, the file a check adds to, and `<path>.installed`, that file as it was with the check whole), their `MANIFEST.md`, their runs on the old code (`base-run/`), `INSTALLED` once `next` puts the checks in, and `AMBIGUOUS.md`, a condition the tester found reads two ways |
| `blocked/` | Phases 4–6, coder | build steps the coder stopped on, for the planner |
| `lint/` | Phase 5 | one report per quality-gate check |
| `SPEC_EVAL.md`, `evidence/` | Phase 5 | the verifier's verdicts and what it ran: `verify prep`'s audit, change set, acceptance run and starting tree (`evidence/integrity.txt`, `changes.diff`, `acceptance.txt`, `tree-start.txt`) and one evidence file per condition (`evidence/C<n>.txt`); its required changes (`evidence/corrections.md`); the mutants it chose (`evidence/mutation-set.json`) and runs this pass (`mutants.json`); and the files `autodev.py mutants` writes and keeps across passes (`mutation-*`, `mutate.*`) |
| `review/`, `CODE_REVIEW.md`, `SECURITY_REVIEW.md` | Phase 6 | the panel's raw reports and their merged list (`review/pass-<n>/findings.md`), the re-votes (`VOTES-R<k>.md`), the judge's calls (`JUDGMENT.md`), the code review built from them (with the report as it stood before the pass, `CODE_REVIEW.before.md`), the security review, and the review's required changes for the coder (`review/pass-<n>/corrections.md`, `review/security-corrections.md`) |
| `pr-body.md`, `pr-write.md`, `pr-output-comment.md` | Phase 6 | the generated PR description; the sections of it the orchestrator writes (the Summary, the Assumptions, a template section), with the text they draw on, which `pr publish` puts into the description; and output moved out of it when too long |
| `triage/` | Phase 6 | the triager's required changes for red CI and human comments, and the comments about a held-out check, for the tester (`human-<n>-checks.md`) |
| `deviations/` | Phases 4–6, coder | each plan step the coder built differently, and why (`coder-<n>.md`), for the ready-for-review gate |
| `spec-problems/` | Phases 5–6 | a criterion a later worker found wrong or missing in `SPEC.md` (`<worker>-<n>.md`), for you to decide |
| `lookups/` | any phase | lookup answers |
| `tree/` | `autodev.py record` | a repo file a worker that never changes the repo changed anyway, as the worker left it, before `record` put it back (`tree/<worker>-<n>/<path>`) |
| `override/` | at a stop, the fixer and `autodev.py next` | the fixer's report (`fixer-<n>.md`); the run's `SPEC.md`, plan and checks as they were before it ran (`fixer-<n>.before/`), and, when it ended without fixing, the repo files it changed, as it left them, before they were put back (`fixer-<n>.after/`) |

## Safety

Autonomous but bounded:

- **One iteration budget per task** (default 4 revise rounds) covers every
  correction, every Define or plan re-review, every tester re-spawn for gaps
  and every re-dispatched `BLOCKED` step, one round each. When the budget
  runs out the run stops and names what is still open, except for review
  findings before the PR is marked ready: those go to the ready-for-review gate, which names each one,
  and you decide. To go on after a budget stop, say how many more rounds you
  want (1 to 10): the run adds them and carries on from the step that
  stopped. It never adds rounds unasked.
- **No worker changes the contract.** The spec, the checks and the plan's
  intent change only through you. A later worker that finds a criterion wrong
  or missing reports it and the run stops (PR comment wording reaches the
  report only as the triager's summary, and CI logs never do); the acceptance
  tester alone repairs a check, and a check it finds right against another
  worker's objection stops the run too. The coder may build a plan step
  differently only to make it work, and every such deviation is shown to you.
  A worker that edits `SPEC.md` is refused by `record`, whatever it returns.
- **It stops and reports** rather than commit a red build, weaken a security
  control, or carry on when a planted bug may be left in the tree, the build
  edited a submodule, or a commit holds code no result checked.
- **It never acts on stale results.** No gate is asked, and no PR description
  written, on results checked against other code. A result that is stale again
  right after its own re-run stops the run.
- **It refuses a quality gate with no test command**, which would pass by having
  nothing to check.
- **It merges to main only through a PR**, only after your approval, and if
  `gh pr merge` is refused it tells you why instead of working around branch
  protection.

No stop is a dead end. Each one asks how to go on, in the session that hit it
or a new one: your instruction to the fixer, a retry once you fixed the cause
yourself, or, where it is safe, a sign-off (above). Only the step that stopped
runs again, not the run. A push to the PR branch stops the run until you bring
those commits into the worktree, where they are checked again. The budget used
up stays until you add rounds.

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
    lib/                shared code for autodev.py and check-tests.py (not run directly)
  evals/                evals.json (pipeline evals, with fixtures in files/)
                        and trigger-eval.json (should / shouldn't trigger)
tests/                  unit tests for the helper scripts, tools/ and the eval fixtures
  fake_gh/              a fake `gh` that plays back scripted responses
tools/check-repo.py     checks that the repo's files agree with each other
tools/check-pr.py       checks a branch name and PR title against the conventions
tools/check-identity.py checks that no file names the person committing (run by the pre-commit hook)
tools/run-tests.py      runs the test suite with its test classes in parallel
tools/eval-run.py       gives each pipeline eval its own branches of the fixture repo, and cleans them up
ruff.toml               lint config
.github/                CI workflows (checks, PR conventions) and the PR template
.githooks/              the pre-commit hook (turn on with `git config core.hooksPath .githooks`)
CLAUDE.md               conventions for agents (and people) changing this repo
UPGRADING.md            what changed in each release, and whether a run in flight resumes
```

## Contributing

Before pushing, run the same checks CI runs:

```
ruff check .
python3 tools/check-repo.py
python3 tools/run-tests.py
```

Before opening a PR, check its branch name and title with `python3
tools/check-pr.py --branch <branch> --title "<PR title>"`; CI runs the same
check.

Turn on the pre-commit hook once per clone with `git config core.hooksPath
.githooks`. It runs `tools/check-identity.py`, which stops a commit when a
staged file names you: your git name or email, the email's local part, your
login name or your GitHub username. The repo's `<owner>/<repo>` slug and the
author and owner names in `.claude-plugin/*.json` may name you.

Branch and PR conventions, the README checklist, the language-agnostic rules,
the rules for changing a script and how to run the pipeline evals are in
[`CLAUDE.md`](CLAUDE.md).
