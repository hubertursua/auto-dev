# auto-dev

An orchestration skill for autonomous development.

It takes one coding task (a ticket, an idea or a spec) to a merged pull
request. It stops to ask you only at a few gates, chiefly before the draft PR
is marked ready for review and before it merges
([*Human gates*](#human-gates--integrations)).

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
| 1 Setup | orchestrator (`next --repo`), lookup (a saved profile), profiler (first run on a repo) | resolve ticket; `autodev.py next --repo` loads the saved profile or has one researched and confirmed with you, then makes the isolated worktree + branch (or uses the worktree you started in) and `.auto-dev/` |
| 2 Plan | planner + plan critic | `PLAN.md` — the ask, testable conditions, assumptions, security criteria, the **size check** (too big for one PR → back to you), the **risk tier** and the build steps; a fresh critic checks it against the ticket and the code, and the planner revises once; then the post-plan gate when it is on (high risk, blockers left open, or the config) |
| 3 Tests | acceptance tester | `acceptance/` — a check per condition of the approved plan, proven to fail on the old code and **committed before the build** |
| 4 Build | coder | code + tests from the plan, making the committed checks pass, and the profile's quality gate run to green |
| 5 Gate | orchestrator (a script, no worker) | `autodev.py quality-gate` confirms the quality gate → `lint/` (red: one coder correction, then you decide); the risk tier re-checked from the diff |
| 6 Ship | orchestrator, verifier + reviewer (high risk: 3 code reviewers + judge, security reviewer), triager | commit + **draft PR** first (CI starts there), then the verifier and the review on it alongside CI → `SPEC_EVAL.md`, `CODE_REVIEW.md`, `SECURITY_REVIEW.md`; one correction takes what they left open and red CI (each committed on top), then the ready-for-review gate, the PR marked ready, merge to main + Jira Done, pausing at each gate |

Workers never negotiate the contract between themselves. A coder that finds
a plan step wrong builds it the way that works and records the deviation for
you to see. A later step that finds the conditions wrong, or a check the acceptance
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
unchecked), and it sees the plan only as the parts `pr-write.md` quotes for the
PR description.
The run's history lives in `.auto-dev/state.json`, which only `autodev.py`
writes, and each judge is a fresh worker that sees only what its brief names.

```
Orchestrator (main agent) ── runs the `next` loop and the human gates; never reads code
│
├─ Phase 1  Setup ......... ticket, then `next --repo`: profile (saved, or profiler + your OK), worktree
├─ Phase 2  Planner ....... PLAN.md — conditions, SIZE CHECK, risk tier, steps
│           Plan critic ..... checks it against the ticket and the code (one revision, one re-check)
│                             [optional post-plan gate]
├─ Phase 3  Acceptance tester  checks from the approved conditions, proven to fail, committed first
├─ Phase 4  Coder ......... code + tests, from PLAN.md, against the committed checks; quality gate green
├─ Phase 5  (script) ...... `quality-gate` confirms the gate; risk tier re-checked from the diff
└─ Phase 6  orch + workers  draft PR → verifier ∥ reviewer ∥ CI → [GATE] ready → [GATE] main
            (high risk: verifier, then 3-reviewer panel + judge ∥ security reviewer, ∥ CI)
            Triager ......... reads red CI logs and human PR comments, so the orchestrator never does
            Planner ......... settles a step the coder stopped (Phases 4–6)
            Acceptance tester  repairs a questioned check, or says why it is right (Phases 4–6)
            Lookup .......... reads code, diffs or long files and answers the orchestrator in a line
            Fixer ........... at a stop, does what you said to fix it, and nothing more (any phase)
```

One document describes the work. `PLAN.md` holds the conditions, which answer
*did we build the right thing*, and the build steps, which answer *did we build
it the way we decided*. A plan executed faithfully can still miss the outcome,
so the pipeline checks both. Nothing is hidden from the coder: it reads
`PLAN.md` whole, and the acceptance checks are committed before it starts.

## How the build is verified

Tests the coder wrote are the coder's own evidence, so they can't be the main
proof. Agents are known to mark work done too early and to make tests pass by
weakening them. Verification is built around that:

- **A plan written to be tested, and checked before the build.** Every
  condition in `PLAN.md` has a concrete example (Given / When / Then), its
  tricky edge case, and how it should be verified. A fresh plan critic, which
  sees the ticket, the plan and the repo but never the planner's reasoning,
  checks it in order: the whole ask and no more, conditions a test can decide,
  every file and function it names opened and confirmed, every condition
  covered by a step and a test, risk, and size. Each blocker cites its
  evidence (a quoted ticket line or a `path:line`), at most 7. The planner
  revises once; the critic re-checks only the revision, and a blocker still
  open goes to you at the post-plan gate (`agents/plan-critic.md`).
- **Acceptance checks, proven to fail first and committed.** Before any code is written, an
  acceptance tester writes black-box tests from the conditions alone: one for each
  condition's example and one for its edge case. Every check for new behavior
  must **fail on the untouched code for the right reason**, and the tester
  saves that run. Each check goes where a developer would put that test: into
  the test file the code already has, or a new test file only for code that
  has none, so the PR adds no test files just for the checks. `next` commits
  them as their own commit (`test: acceptance checks for <task>`) before the
  coder starts, so the coder builds against them in the open
  (`agents/acceptance-tester.md`).
- **Guarded against their commit.** From then on only the acceptance tester
  (or the fixer, at your instruction) may change a check, and each such
  change is committed as a new tests commit: only what that worker changed,
  leaving out the coder's own lines in a shared file (the whole file, noted,
  when the two can't be taken apart). `check-tests.py` compares the tree with
  every tests commit and refuses any change to a line one added, even in a
  file the coder's tests share. The tester itself may only add to a file the
  repo had, and may change no file but its checks.
- **Only the workers that write code change it.** The ones that write or review
  the plan, judge the review, or triage CI and PR comments never
  change a repo file. `brief` notes the tree each one starts from, and
  `record` refuses a result that changed a file outside `.auto-dev/` (one git
  ignores isn't compared) and puts the file back, keeping the worker's version
  in `.auto-dev/tree/`. A change someone else could have made is left alone:
  a file written after the worker returned, a commit, anything while another
  worker was out, or while setup ran
  (`skills/auto-dev/scripts/lib/tree_guard.py`).
- **The quality gate, confirmed before the push.** The coder runs the
  profile's quality gate to green itself; then `autodev.py quality-gate` runs
  every check again, as a script with no worker, and writes its reports. A red
  gate goes back to the coder once (no round); red again, the run stops and
  asks you.
- **An independent verifier that runs things.** Once the build is pushed as a
  draft PR, a fresh verifier, spawned with the review while CI runs,
  **runs** the checks, judging against PLAN.md's conditions, not its
  steps or the coder's report.
  Each condition gets a verdict and an evidence tier:
  - **Strong:** the checks pass, cover the example and edge case at the level
    the condition asks, and their run on the old code, saved before the build,
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
- **Code that passes a test without doing the work.** The coder can read the
  acceptance checks, so it could special-case them. The verifier and the
  reviewer both look for that: a branch on a value only the tests use, a check
  for a test environment, a constant where the condition asks for a
  computation. The verifier also runs a **probe** of its own for each
  condition, on every run, with inputs the committed checks don't use.
- **A test-integrity audit.** `skills/auto-dev/scripts/check-tests.py` flags
  deleted, skipped or focused tests, removed assertions, new tests that assert
  nothing, changes to the test runner's config, and any change to a line a
  tests commit added, even in a file shared with the coder's tests. Each finding must be
  justified by the conditions or it goes back to the coder.
- **Targeted mutation testing (high risk).** On a high-risk run, the verifier plants small bugs in the
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
  step, an acceptance check or the plan's conditions themselves are wrong. A wrong plan step is
  the coder's to fix as it builds: it builds the step the way that works and
  lists each deviation and why in `deviations/coder-<n>.md`, and the ready-for-review gate
  shows you every one. A check another worker calls wrong goes to the
  acceptance tester, which repairs it; if the tester finds the check right,
  the run stops and asks you. A criterion a later worker finds wrong or
  missing (the verifier, the reviewer, the review judge, a security reviewer,
  or the triager from a PR comment) is listed in `spec-problems/<worker>-<n>.md`,
  and the run stops and asks you before it acts on that result: no worker
  changes the conditions in `PLAN.md`. You say how to change it (the fixer does that, then the
  verifier checks again), or sign off to keep it as written; every later
  worker that judges it is told what you kept.
- **Re-checked after every change.** After every correction or fix, the
  quality gate runs again, then a pass (the verifier and the review) checks
  the change before it is committed on top.
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

## One session, with checkpoints

The run goes straight through in one session, in three stages: **Plan**
(phases 1–3), **Build** (4–5) and **Ship** (6). When the next phase belongs to
a new stage, `next` tells the orchestrator to read that stage's runbook
(`skills/auto-dev/references/plan.md`, `build.md`, `ship.md`) and carries on.
Each runbook is short and never asks the orchestrator to judge, so any model
can run it.

The orchestrator's context is the real cost: every added turn makes every later
turn more expensive. So it delegates reads to workers, and each worker's reply
is its result block alone (its files hold the rest; a few lines above the block
only when it stopped, or has something the user must be told). `next` records
each result itself before it decides, checking it against the worker's files,
so a worker costs no extra orchestrator turn; a refused one goes back to the same
worker, which fixes the listed issues in what it wrote rather than redoing the
job. `next` never sends a brief out twice while its worker may still be
running: it answers wait until the result is there, and sends the brief out
again only in a new session, after a retry at a stop, after 3 hours, or when
the orchestrator says every agent it waits for returned without a result
(`next --reissue`). A lone worker is spawned in the foreground. `next` ends a long
session at a **checkpoint** after 80 recorded events (about 35 workers;
`checkpoint_events` in `.auto-dev.yml` changes it). There it writes
`.auto-dev/HANDOFF.md` and stops; start a fresh session and say `auto-dev
continue` to pick up. Started inside a run's worktree, it continues that run;
elsewhere, it asks when several runs are open. Nothing crosses a session
boundary except `.auto-dev/` and the git tree, which also makes an interrupted
run resumable: `autodev.py resume` finds it, and `next` picks up where it
stopped. A run started on auto-dev 3.x or 4.x can't be resumed: `resume`
names it, and you finish it on that version or remove its worktree and start
again.

## Size check: one PR, or back to you

The planner says whether the task fits one PR:

- **FITS** — the pipeline runs every step: on a standard-risk task **6
  worker roles** (planner, plan critic, acceptance tester, coder, verifier,
  reviewer), and on a high-risk one the code review panel, the review judge
  and a security reviewer in the reviewer's place (roles, not spawns). A test
  holds the standard-risk happy path to its **spawn budget**: at most 5 worker
  spawns to the first push and 7 to ready-for-review. Today it takes 4 and 6;
  one plan revision makes it 6 and 8, since the critic's re-check is a spawn
  too. The profiler runs only when the repo has
  no saved profile (once more for each change you ask for to its draft), the triager only when CI fails or a person comments,
  `lookup` when the orchestrator needs a fact from the code, and the fixer
  only when you tell a stopped run how to fix it. When `PLAN.md`
  has security criteria, the security reviewer for sensitive paths takes the
  regular one's place.
- **OVERSIZED** — several independent deliverables or subsystems, or a large
  file count. auto-dev builds nothing and hands the task back with its reasons
  and suggested lines to split along. Jira is left alone, and the worktree and
  branch stay, with the commands to remove them. Split the task and run
  auto-dev on each part, or answer the stop: sign it off to build it as one
  PR anyway, or tell the fixer how to narrow `PLAN.md` (a new session can
  answer too).

The planner also proposes a **risk tier**: high for security criteria, auth,
payments, access control, secrets, a data migration or backward
compatibility, else standard. The plan critic can raise it, and once the
quality gate is green (the end of Phase 5), before anything is pushed, `next`
re-checks it from the diff: a path with a whole word that names a sensitive area (auth,
session, token, permission, payment, migration and the like, camelCase split),
a path matching one of the profile's `sensitive_paths` globs, a line the build
adds holding one of those words, or a large change (over 25 files or 800
lines, lock files left out) makes it high. It never goes down. A high tier before the build turns on the post-plan
gate; one raised after the build is shown at the ready-for-review gate. The
tier decides how much review the draft gets: a high tier adds the review
panel with its judge, the separate security reviewer and mutation testing.

## Review on the draft PR

The build, its quality gate green, is committed and pushed as a **draft PR
before any review**, so CI runs while it is checked; its description says it
is not verified or reviewed yet. (A repo that must not push unreviewed code
sets `gates.open_pr: true` in `.auto-dev.yml`: the run then asks before the
first push.) Each pass runs the verifier (above) and the review: together
on a standard-risk run; on a high-risk run the verifier goes first, since its
mutants are planted in the worktree, and the review follows on the same tree.

- **Standard risk: one reviewer**, for code and security both. It runs
  `/code-review` on the changed files at the effort the plan sets (see
  [*Models and effort*](#models-and-effort)) and `/security-review`, traces
  each finding's trigger path itself, and writes its calls in a short
  `JUDGMENT.md`; `autodev.py review-build --solo` builds `CODE_REVIEW.md` from
  them, every finding that holds in a must-fix category being must-fix. It
  writes `SECURITY_REVIEW.md` itself (`agents/reviewer.md`).
- **High risk: the panel and the security review.**
  1. **Code review panel.** Three reviewers run `/code-review` on the changed
     files independently, each through its own lens: correctness and edge
     cases, tests and overfitting, callers and compatibility
     (`agents/code-reviewer.md`). `next` merges their reports into one list, and a
     judge decides which findings are one, checks each one's trigger path in
     the code and writes the fix for each must-fix finding, in a short
     `JUDGMENT.md`. `autodev.py review-build` then applies the rubric's vote
     table and writes `CODE_REVIEW.md` with its counts, history and overall
     confidence. A finding that could be must-fix but only one reviewer raised
     goes to the other two for a re-vote.
  2. **Security review.** A security reviewer runs `/security-review` over
     the whole change, and the judge double-checks every High or Medium
     finding. When `PLAN.md` has security criteria (a change on a sensitive
     path), a reviewer that weights those paths hardest does it.

**One fix loop.** What a pass leaves open (the verifier's items, every
must-fix finding, a confirmed security finding) is fixed by one correction,
for one round of the iteration budget. With CI configured, CI settles on the
pushed commit first, and red CI the triager puts on the code joins the same
correction. The quality gate runs on the correction, and a new pass checks it
before it is committed on top and pushed. With no round left before the PR is
marked ready, the run goes on to the ready-for-review gate, which names
everything still open; after that (a red CI fix, a PR comment), a must-fix
finding with no round left stops the run. A finding about an acceptance check
goes to the acceptance tester, never the coder; if the tester finds the check
right, the run stops and shows you both sides. A problem that lies in
`PLAN.md`'s conditions rather than the code stops the run once the pass has
settled, and asks you. Once a pass settles, the PR's description is published
again with its results, and you decide at the ready-for-review gate whether
the PR leaves draft. A pass on a correction skips the nested `/code-review`
and `/security-review` skills: the reviewers follow the correction and
everything downstream of it themselves. When the judge passes a security lead
from the panel on, a security run that skips `/security-review` checks just
those leads.

A **rubric** (`skills/auto-dev/templates/rubric.md`) decides what must be fixed:

- **Code findings.** Only correctness bugs, missing or weak tests, and a broken
  acceptance check can be must-fix, and each needs a concrete trigger path and,
  on the panel, 2 of the 3 reviewers' votes. Scope, performance and design findings are
  advisory. Problems the change didn't introduce are dropped.
- **Checked before it's reported.** Before a reviewer reports a finding, or
  the judge confirms one, they read every function the claim depends on, look
  for a layer that already handles the case (validation, a guard, a
  constraint, a caller, an existing test) and name a path real use takes. A
  finding they can prove wrong, or aren't sure of, is left out: a short list of
  real defects beats a long list of guesses.
- **Test gaps, whole.** A test-gap finding lists every reachable case no test
  covers, so the coder closes the whole gap in one round.
- **Security findings.** One this change introduced, rated High or Medium with
  a traced path the judge (the reviewer itself, on a standard-risk run)
  confirms, is must-fix; a Low one is advisory. A High
  or Medium one that was already there is shown to you at the ready-for-review gate, to note
  as a follow-up or ignore; this PR never fixes it.
- **Confidence.** Every finding and every report carries a confidence level. A
  low-confidence report (say, two reviewers failed, or the security reviewer
  couldn't finish) is flagged at the gate, never
  shown as a clean pass.

Once the draft PR is open, a **triager** reads red CI logs, and once it is
marked ready, people's review comments,
so their text never reaches the orchestrator and can't steer the run. It sends
only real code problems to the coder (and comments about an acceptance check to
the acceptance tester). A red CI run the code can't fix (a missing secret,
infrastructure, a flaky test, an unknown cause) stops the run before Jira
moves; once the cause is fixed and CI re-run, `auto-dev continue` watches it
again. The reviewers'
instructions are in `agents/reviewer.md`, `agents/code-reviewer.md`, `agents/review-judge.md`,
`agents/security-reviewer.md`, `agents/security-reviewer-sensitive.md` and
`agents/triager.md`.

## Human gates & integrations

Planning and build run unattended. The draft PR opens without asking, so CI
runs while the change is reviewed. The pipeline pauses for approval:

- before the PR leaves draft (the **ready-for-review gate**, once the reviews
  on the draft have settled), and
- before the **main merge**,
- plus an optional **post-plan gate** (on for high-risk tasks, when the plan
  critic left blockers open after the planner's one revision, which it lists,
  or with `gates.post_plan`) and an optional **open-the-PR gate** before the first
  push (with `gates.open_pr`, for repos that must not push unreviewed code).

Four more pauses fire only when their situation arises: the **profile
question** (a repo with no valid saved profile and no `.auto-dev.yml`
that declares one; `next --repo` asks it), the **gate-check question** (a
saved profile whose lookup finds a gate check's tool not adopted: keep it,
leave it out of this run, or stop, before the run exists), the **Jira In Progress confirmation** (only with a ticket, once
the size check says the task fits, and skipped when the ticket is already in
progress; you can also answer that it is), and the
**worktree cleanup offer** (after the final report; never for a worktree you
made).

Declining is safe at every gate: `Stop` ends the run; `Hold`, at the
open-the-PR, ready-for-review and main gates, pauses it so you can resume later. Both leave the branch, the worktree and every artifact on
disk. When a review pass left must-fix findings open because no round was
left to correct them, the ready-for-review gate names them and offers a fourth
answer, **Add a round and fix it**: it adds one round to the budget, the run
corrects what is open, reviews and commits it, and asks the gate again. What
each option does is in `skills/auto-dev/references/tables.md`.

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
  the PR branch, the run stops before it watches CI, pushes or asks a gate, and
  tells you how to bring those commits in to be checked; a commit you pushed
  from the run's worktree (a base merged in by hand, say) is checked again with
  no stop. If you rebase or amend the branch in the worktree and don't push it,
  the run stops before its push and asks you to force-push it yourself: auto-dev
  never force-pushes. auto-dev has no staging step; the PR targets the base
  branch.
- **Jira** only moves the ticket (In Progress → In Review → Done), and is
  skipped without a ticket. The ticket's text is stored at setup and given to
  the planner and the plan critic, which have no Jira access
  (`skills/auto-dev/references/gates-and-jira.md`).
- **CI** is watched with a time limit on the draft PR, again once it is marked
  ready (some workflows skip drafts), and after the merge. A draft with no
  check after a grace period doesn't hold the run up. CI that timed out, never
  ran or couldn't be watched is shown as not monitored, never as green. A PR
  that conflicts with its base gets no checks from GitHub: the watch says so at
  once, you're told to fetch the base and merge it in yourself (the run never
  merges it), and the gates show CI as not run because of the conflict. When
  a review pass leaves findings open, CI settles first, and red CI that the
  code caused is fixed in the same correction, on the same round. CI is
  watched on the pushed commit, even when an unpushed tests commit sits on top
  of it; a watch that reported on another commit stops the run rather than
  waiting forever.
- **Deviations from the plan** the coder recorded are listed in the
  ready-for-review and main gate summaries and the final report, each with its
  reason.
- **A stop asks how to go on.** When the run stops on a result or a worker,
  you answer (any reply other than a pick is an instruction):
  - **Your instruction:** the fixer agent does what you said, and nothing
    more. Your words are its consent: it may change the code, or the run's
    `PLAN.md` or acceptance checks when you name them. If the fix needs
    more than you said, it changes nothing and asks you to approve its
    proposal. `record` refuses its report if it leaves out a file it changed,
    the run's settings in `state.json` included; when its result is anything
    but `FIXED`, all of it is put back, settings too.
    It edits a check in the worktree, and the pipeline commits that as a new
    tests commit once its fix is recorded; `autodev.py amend-checks` drops,
    adds or renames a check's `MANIFEST.md` rows.
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
  checked again before the run goes on: the quality gate on changed code,
  and in Phase 6 a pass on it (the verifier, judging every condition again
  when `PLAN.md` changed, with the review of the changed files)
  (`skills/auto-dev/references/tables.md`, _Overriding a stop_).

## Stack profiles

A **profile** says how a repo installs its dependencies and which commands make
up its quality gate (test, lint, format check, type check, build). Phase 1
(`autodev.py next --repo`, which does each step below itself and prints the
worker to spawn or the question to ask) gets one in this order:

1. **A saved profile.** If you saved one for this repo on an earlier run, Phase 1
   loads it without asking. A `lookup` worker checks that the repo still uses
   each gate check's tool. When it finds one not adopted, you're asked before
   the run is created: keep the check (if it fails, the coder first tries to
   make it green, which may change the repo; if it is still red, the run stops
   at the quality gate and you can sign it off), leave it out of this run, or
   stop.
   The saved file is never changed (only offered keep or stop when leaving
   the checks out would leave no test check). When the repo's `.auto-dev.yml`
   sets `gate`, its gate replaces the saved one, so there is no lookup and no
   question. An invalid saved profile
   is researched again, and you're offered to overwrite it.
2. **A committed `.auto-dev.yml` that sets both `setup` and `gate`.** The repo
   has declared its profile, so there is nothing to research.
3. **Research.** Otherwise the `profiler` worker reads the repo (CI config, task
   runners, manifests, lockfiles, contributing docs) and drafts a profile, citing
   the file and line each command came from and naming anything it guessed. It
   may also propose `sensitive_paths`: globs of files that hold sign-in,
   session, access-control, payment or secret-handling code under paths that
   don't say so, which the risk re-check then treats as sensitive. The
   run shows you the draft and asks: save it for this repo, use it for this run
   only, change something (the profiler redoes the draft as you say, and you're
   asked again), or stop. `autodev.py` writes the saved file.

`.auto-dev.yml` is applied on top in every case. The schema is in
`skills/auto-dev/references/profiles.md`.

Workers run the profile's checks through `autodev.py run gate|test`, which runs
the command exactly as the profile lists it, in the run's worktree, and saves
its output, so no worker has to rewrite a command with `cd`, which a
permission check refuses. A check can also give a scoped form (`files`, with
`<files>` where the paths go), so a worker can run it on only the files it
changed or wrote, and a test-ID form (`tests`, with `<tests>` for a list of
test IDs or `<test>` for one, plus a `tests_example`), so it can run only the
tests it names with `--tests`; the profiler looks for both. With no test-ID
form, `--tests` falls back to the file-scoped form on the `--files` given with
it, else to the whole check, and `run` prints which it used. The quality gate
runs every check whole through `run gate <n>`; a `run test` that runs the test
check whole when it could have been scoped prints a warning with the
ready-to-copy scoped lines, which the coder's, fixer's and acceptance tester's
briefs also carry. Claude Code moves a Bash call still running after 180 s to
the background, so a worker keeps each command under 3 minutes and waits on a
`run` that went to the background with `autodev.py run wait`, which blocks up
to 170 s, then prints that run's result exactly as `run` would have (or
`RUNNING`, to call it again), so the worker never polls.

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
repo (setup runs it for you). Edit the file to change the profile, or delete it to have the next run
research it again. It holds only how the stack installs and checks itself;
repo policy such as branches and the iteration budget stays in `.auto-dev.yml`.

### Permissions for unattended runs

`autodev.py` reads and saves the profile itself, so the `autodev.py` rule below
covers it; the orchestrator never touches the file.

- With the Bash sandbox on, add
  `"sandbox": { "filesystem": { "allowWrite": ["~/.config/auto-dev"] } }` to
  `~/.claude/settings.json`, so the script can save there: the profile, and
  each run's `metrics.json` copy (the moved directory instead, if you set
  `AUTO_DEV_PROFILES_DIR`, `AUTO_DEV_METRICS_DIR` or `XDG_CONFIG_HOME`).
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
      "Bash(python3 <home>/.claude/plugins/cache/auto-dev-marketplace/auto-dev/*/skills/auto-dev/scripts/check-fresh.py *)"
    ]
  }
}
```

- The `autodev.py` rule also covers setup (`next --repo`, which finds, checks
  and saves the profile), lets workers run the profile's gate and test
  commands through `autodev.py run`, and lets the fixer change acceptance checks'
  rows with `autodev.py amend-checks` while the fix you asked for is open. It runs only the commands in the profile
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

`autodev.py next` runs the setup commands and `autodev.py run` the gate, so
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
and `Skill(code-review)` and `Skill(security-review)` for the review
workers. At the profile question the orchestrator
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
| `sensitive_paths` | globs of files the risk re-check treats as sensitive (replaces the profile's list) |
| `pr_review.inline_comments` | post the open and advisory review findings on the PR, once the reviews settle |
| `checkpoint_events` | events one session records before it checkpoints (default 80) |
| `jira.states` | the board's state names for In Progress, In Review and Done |

It can also set any profile key (`setup`, `gate`, `test_notes`, …) to override
the profile. Phase 1 (`next --repo`) validates the file with
`scripts/validate-config.py`, so a mistyped key is reported rather than
silently ignored, before anything is created.

## Dependencies

- **Claude Code's built-in tools** only, no other plugins. The `Skill` tool runs
  `/code-review` and `/security-review`.
- **git**, for the run's worktree and branch.
- **`gh`** on your `PATH` and authenticated. It opens and merges the PR and
  watches CI: any CI that reports checks to GitHub, such as GitHub Actions or
  CircleCI. Phase 1 stops if it is missing, signed out, or `origin` isn't on
  GitHub.
- **Python 3.9+** with **PyYAML** (`pip install pyyaml`). Setup (`autodev.py
  next --repo`) stops if either is missing.
- **Optional:** the Atlassian MCP for Jira (found by tool name, so it can be
  registered under any server name), and a code-index tool named by the
  profile's `symbol_lookup`.

The helper scripts in `skills/auto-dev/scripts/` use only Python's standard
library, except where they read YAML:

| Script | What it does |
| ------ | ------------ |
| `autodev.py` | the one entry point: keeps the run's state in `.auto-dev/state.json`, and `autodev.py next` prints the orchestrator's next action (from Phase 1's setup, with `--repo`, on; `autodev.py setup-answer` records the answer to the profile question or the gate-check question). `autodev.py quality-gate` runs the profile's whole quality gate before the push. `autodev.py --help` lists every subcommand |
| `validate-config.py` | checks `.auto-dev.yml`, or a saved profile with `--profile` (setup runs it) |
| `profile-path.py` | prints the saved profile's path for a repo and whether it exists (setup runs it) |
| `exclude-artifacts.py` | makes `.auto-dev/` ignore itself and checks it with git |
| `check-staged.py` | before each commit, checks nothing under `.auto-dev/` is staged |
| `check-fresh.py` | checks each report was produced on the code as it is now |
| `check-tests.py` | the verifier's test-integrity audit, run by `autodev.py verify prep`: it also refuses any change to a line an acceptance tests commit added |
| `mutate.py` | the verifier's mutation testing, run by `autodev.py mutants run`; restores every file afterwards |

## Models and effort

Each worker is its own agent type in `agents/`, which fixes its tools, model and
effort. The types name model families (`opus`, `sonnet`, `haiku`), not versions,
so a new release is picked up without editing the plugin.

| Worker                                   | Agent type                       | Model · effort    | Turn cap |
| ---------------------------------------- | -------------------------------- | ----------------- | -------- |
| Profiler (first run on a repo)           | `auto-dev:profiler`              | `sonnet` · high   | —        |
| Planner                                  | `auto-dev:planner`               | `opus` · high     | —        |
| Plan critic                              | `auto-dev:plan-critic`           | `opus` · high     | —        |
| Acceptance tester                        | `auto-dev:acceptance-tester`     | `sonnet` · high   | 120      |
| Coder (the build, all corrections)       | `auto-dev:coder`                 | `opus` · medium   | 150      |
| Verifier                                 | `auto-dev:verifier`              | `opus` · high     | —        |
| Reviewer (standard risk: code and security) | `auto-dev:reviewer`           | `opus` · high     | —        |
| Code reviewer (high risk: ×3 panel, and re-votes) | `auto-dev:code-reviewer` | `opus` · high     | —        |
| Review judge (high risk)                 | `auto-dev:review-judge`          | `opus` · high     | —        |
| Security reviewer (high risk)            | `auto-dev:security-reviewer`     | `opus` · high     | —        |
| Security reviewer (`PLAN.md` has security criteria) | `auto-dev:security-reviewer-sensitive` | `opus` · high | —        |
| Triager (red CI, human PR comments)      | `auto-dev:triager`               | `sonnet` · high   | —        |
| Orchestrator lookups                     | `auto-dev:lookup`                | `haiku` · medium  | —        |
| Fixer (your instruction at a stop)       | `auto-dev:fixer`                 | `opus` · high     | —        |

`next` names each type as `auto-dev:<worker>`; a plugin install lists them as
`auto-dev:auto-dev-<worker>`, and the orchestrator maps one to the other.

The levels start from Anthropic's guidance for the Claude 5.5 models
([choosing a model](https://platform.claude.com/docs/en/about-claude/models/choosing-a-model)),
which says to start at each model's default and tune from your own evals.
The last five below were then checked on small scenarios (planted bugs for
the reviewers, the lookups and the acceptance tester's checks; a ticket with
hidden checks for the coder), each against the stronger setting it replaced:

- **`sonnet` workers run at `high`, Sonnet's default.** At `medium`, Sonnet 5.5
  scores 7 to 15 points lower on Anthropic's coding benchmarks
  ([optimizing for cost and intelligence](https://platform.claude.com/docs/en/about-claude/models/optimizing-for-cost-and-intelligence)).
- **`opus` workers other than the coder run at `high`, above Opus's default
  (`medium`).** A worker's miss costs a correction round. 5.0 lowered the planner, the judge
  and the security reviews from `xhigh` to `high`: the plan critic now checks
  the plan, and the run's time to its first push matters more.
- **The coder runs at `medium`, Opus's default.** Its misses cost a
  correction round too, but in the scenarios `medium` missed nothing the
  ticket stated: it built every condition correctly, as `high` did, at a
  little under two-thirds of the cost and in half the time. The one
  difference was a rounding flaw in existing code the change calls, which
  the ticket didn't mention: `high` avoided it in 3 of 3 runs, `medium` in
  2. The plan and the acceptance checks state what to build, and the
  verifier and the review check the result.
- **The acceptance tester runs on `sonnet`.** Its checks are the build's
  contract, so a weak one lets bad code pass, but in the scenarios (3 runs
  each) Sonnet's checks were as good as Opus's. Every new-behavior check
  failed on the untouched tree, every run's checks caught all 8 planted
  bugs, and both models' false alarms on correct builds came from the same
  gaps in the plan. Two Sonnet runs also caught builds that showed a
  downgrade's total as negative. Sonnet cost about half as much and took
  about a third less time.
- **The code reviewers run at `high`.** In the scenarios, `high` found every
  planted bug that `xhigh` did, in a little over half the time; the plan
  still asks for `xhigh` on a large change.
- **The sensitive-path security review runs on `opus`, not `fable`.**
  Both found every planted hole, and `fable` costs about 2.5 times as much per
  token.
- **Lookups run on `haiku`.** Haiku answered as accurately as Sonnet, for a
  fraction of the cost.

The orchestrator runs on the session's model; `sonnet` at medium effort is
enough, since `next` makes the decisions and the workers do the judging. To
retune a worker, edit the `model:` / `effort:` (or `maxTurns:`) frontmatter in
`agents/<name>.md` and the tables in `SKILL.md` and this README;
`tools/check-repo.py` fails when they disagree.

The coder and the acceptance tester cap their turns (`maxTurns`), so a spawn
that loops stops instead of running on. A capped spawn stopped at its cap
writes no result file; `next` then sends it out once more, told to keep its
edits and finish (see _Safety_).

The code reviewers' effort is set per run. The planner writes a
`Review effort:` line in `PLAN.md`: `high` by default, `xhigh` for
a large change (many files, or logic across several modules). The
orchestrator passes it to each code reviewer of the panel, overriding the
agent file's `high`. On a first review, each reviewer (the panel's, or the
standard-risk reviewer) runs its nested `/code-review` at that effort too; a correction's
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
| `state.json` | `autodev.py` only | the run's state: phases, size check, gates, budget and every round spent, and each quality-gate run (`gate_runs`) |
| `WORK_LOG.md` | generated from `state.json` | the same, for people to read |
| `setup.log`, `setup.json` | `autodev.py init` | the setup commands' output and result |
| `profile-origin.json`, `profile.yml`, `profile-retry.yml` | Phase 1 (`next`) | where the run's profile came from (the saved file and the checks left out of this run or kept at the gate-check question, a draft kept for this run only in `profile.yml`, or `.auto-dev.yml`), so a failed setup is retried from it; `profile-retry.yml` is the profile a retry re-read |
| `briefs/`, `returns/` | `autodev.py`, each worker | each worker's brief, and the result it returned |
| `tmp/` | workers; `autodev.py run` (`tmp/run/`) | long command output; `tmp/run/records/` holds each `run`'s record and result, which `run wait` reads |
| `HANDOFF.md` | a checkpoint, or the user asking to stop | the brief for the next session |
| `metrics.json` | `autodev.py next`, each time it completes or stops the run | the run's numbers for tuning auto-dev: spawns per worker, rounds spent, left and added, stops by their number, refused results, review findings kept and dropped, events and the build's diff size. Counts only, no code or task text. `next` writes the same file to `~/.config/auto-dev/metrics/<repo>/<branch>.json` (or `$AUTO_DEV_METRICS_DIR`, or `$XDG_CONFIG_HOME/auto-dev/metrics`), so it outlives the worktree |
| `PLAN.md` | Phase 2 | the plan: the conditions (the testable contract), size check, risk tier and build steps |
| `plan-review/` | Phase 2 | the plan critic's review (`<n>.md`): verdict, risk tier, blockers with evidence |
| `acceptance/` | Phase 3 (the tester; its repairs in Phases 4–6) | the checks' `MANIFEST.md` (the checks themselves are ordinary test files in the worktree, committed before the build), their runs on the old code (`base-run/`), and `AMBIGUOUS.md`, a condition the tester found reads two ways |
| `blocked/` | Phases 4–6, coder | build steps the coder stopped on, for the planner |
| `lint/` | `autodev.py quality-gate` (Phases 5–6) | one report per quality-gate check |
| `SPEC_EVAL.md`, `evidence/` | Phase 6, the verifier | the verifier's verdicts and what it ran: `verify prep`'s audit, change set, acceptance run and starting tree (`evidence/integrity.txt`, `changes.diff`, `acceptance.txt`, `tree-start.txt`) and one evidence file per condition (`evidence/C<n>.txt`); its required changes (`evidence/corrections.md`); the mutants it chose (`evidence/mutation-set.json`) and runs this pass (`mutants.json`); and the files `autodev.py mutants` writes and keeps across passes (`mutation-*`, `mutate.*`) |
| `review/`, `CODE_REVIEW.md`, `SECURITY_REVIEW.md` | Phase 6 | the panel's raw reports and their merged list (`review/pass-<n>/findings.md`), the re-votes (`VOTES-R<k>.md`), the judge's calls, or the standard-risk reviewer's own (`JUDGMENT.md`), the code review built from them (with the report as it stood before the pass, `CODE_REVIEW.before.md`), the security review, and the review's required changes for the coder (`review/pass-<n>/corrections.md`, `review/security-corrections.md`) |
| `pr-body.md`, `pr-write.md`, `pr-output-comment.md` | Phase 6 | the generated PR description; the sections of it the orchestrator writes (the Summary, the Assumptions, a template section), with the text they draw on, which `pr publish` puts into the description; and output moved out of it when too long |
| `triage/` | Phase 6 | the triager's required changes for red CI and human comments, and the comments about an acceptance check, for the tester (`human-<n>-checks.md`) |
| `deviations/` | Phases 4–6, coder | each plan step the coder built differently, and why (`coder-<n>.md`), for the ready-for-review gate |
| `spec-problems/` | Phase 6 | a condition a later worker found wrong or missing in `PLAN.md` (`<worker>-<n>.md`), for you to decide |
| `lookups/` | any phase | lookup answers |
| `tree/` | `autodev.py record` | a repo file a worker that never changes the repo changed anyway, as the worker left it, before `record` put it back (`tree/<worker>-<n>/<path>`) |
| `override/` | at a stop, the fixer and `autodev.py next` | the fixer's report (`fixer-<n>.md`); the run's `PLAN.md` and checks as they were before it ran (`fixer-<n>.before/`), and, when it ended without fixing, the repo files it changed, as it left them, before they were put back (`fixer-<n>.after/`) |

## Safety

Autonomous but bounded:

- **One iteration budget per task** (default 4 revise rounds) covers the
  planner's one revision for the critic and every fix loop (a review pass's
  open findings and red CI share one; people's comments, or red CI alone,
  get their own), one round each. The tester's one more go for gaps, a red
  gate's correction and a `BLOCKED` step's re-dispatch are free, once each:
  the same again stops and asks you. When the budget
  runs out the run stops and names what is still open, except for review
  findings before the PR is marked ready: those go to the ready-for-review gate, which names each one,
  and you decide: ship them listed in the PR, or add a round there to fix
  them. To go on after a budget stop, say how many more rounds you
  want (1 to 10): the run adds them and carries on from the step that
  stopped. It never adds rounds unasked.
- **A capped worker gets one more go.** The coder (150 turns) and the
  acceptance tester (120) cap their turns, so a spawn that loops ends. One
  that ends without writing its result file is sent out once more, as a new
  brief that tells it to keep the edits its earlier spawn made and finish; a
  second miss stops the run and asks you. Any other worker that returns no
  result is sent the same brief again, up to three spawns.
- **No worker changes the contract.** The conditions, the checks and the
  plan's intent change only through you, once the plan critic's one round is
  over. A later worker that finds a criterion wrong
  or missing reports it and the run stops (PR comment wording reaches the
  report only as the triager's summary, and CI logs never do); the acceptance
  tester alone repairs a check, and a check it finds right against another
  worker's objection stops the run too. The coder may build a plan step
  differently only to make it work, and every such deviation is shown to you.
  A worker that judges against `PLAN.md` and edits it is refused by
  `record`, whatever it returns.
- **It stops and reports** rather than commit a red build, weaken a security
  control, or carry on when a planted bug may be left in the tree, the build
  edited a submodule, a commit holds code no result checked, or CI reported on
  a commit other than the one it waits for.
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
runs again, not the run. A push to the PR branch from elsewhere stops the run
until you bring those commits into the worktree, where they are checked again;
one pushed from the worktree is checked again with no stop. A correction the
run checked that you commit (and push) yourself once its review pass is done
is recorded as the verified commit, not asked for again; one you commit while
that pass is still out is reviewed again. The budget used up stays until you
add rounds.

## Repository layout

```
.claude-plugin/         plugin.json (name, version) and marketplace.json
agents/                 one agent type per worker: tools, model, effort, and its whole brief
skills/auto-dev/
  SKILL.md              the orchestrator's spine: the rules and the `next` loop
  references/           one runbook per stage (plan, build, ship), the
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
