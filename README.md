# auto-dev

An orchestration skill for autonomous development.

It takes one coding task from a ticket to a merged pull request without you
stepping in. Each job goes to a purpose-built **worker** (a subagent), and the
workers hand structured artifacts to each other through a `.auto-dev/` scratch
directory. It is **stack-agnostic**: it ships no stack profile. On the first run
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
Link `skills/auto-dev` into `~/.claude/skills/` too.

## What it does

Ask Claude to take a whole task off your plate, e.g. *"auto-dev this…"*,
*"take it all the way to a PR"*, *"pick up JIRA-1234 and ship it"*. The
orchestrator runs:

| Phase | Worker | Output |
|-------|--------|--------|
| 1 Setup | orchestrator, profiler (first run on a repo) | detect repo, load the saved profile or research one and confirm it with you, resolve ticket, isolated worktree + branch (or the worktree you started in), `.auto-dev/` |
| 2 Define | Define agent + reviewer | `SPEC.md` — context, testable conditions, assumptions, security criteria; plus the **size check** (too big for one PR → back to you) |
| 3 Plan | planner + plan reviewer, acceptance tester | `IMPLEMENTATION.md` — the technical how; `acceptance/` — held-out checks sealed from the coder (optional approval gate) |
| 4 Build | coder (planner and acceptance tester when the coder proposes a plan or check change) | code + tests given **only** the plan; a step or check the coder finds wrong goes to its owner (the planner, then the acceptance tester) before the coder goes on |
| 5 Verify | cleanup agent, then verifier (acceptance tester to fold a check or rule on a questioned one, when needed; Define agent when the verifier proposes a spec change; planner when the coder proposes a plan change) | the sealed checks are installed, `/simplify` + the profile's quality gate run to green, then the verifier runs the held-out checks and audits the tests vs. the withheld spec → `SPEC_EVAL.md` (correction loop to Phase 4: coder, cleanup, verifier); a spec proposal goes to the Define agent first, and an applied one is redone (plan, its checks, code, a full verifier pass) |
| 6 Ship | orchestrator, 3 code reviewers + judge, security reviewer, triager (Define agent for a spec proposal; planner and acceptance tester for plan and check proposals) | code review panel and security review on the uncommitted change (correction loop to Phase 4 for must-fix findings), then commit + draft PR + CI, then main + Jira Done — pausing at each gate; a spec proposal from the review or a PR comment goes to the Define agent, and an applied one is redone, reviewed again and shown at the next gate |

## Agent hierarchy

The main agent is the orchestrator and never writes code. It spawns a fresh
worker for each job, and they hand off through files in `.auto-dev/`, never
shared memory. It doesn't choose the order of steps either: it runs
`autodev.py next`, does the one action printed, and runs it again. It doesn't
judge the build or write correction briefs; the workers that found a problem
write those, and the orchestrator passes them on unedited. It holds the plan
and the story of every round, which is the context a judge must not have.

```
Orchestrator (main agent) ── owns the pipeline, holds the spec, runs the human gates
│
├─ Phase 1  Setup ......... detect repo, profile (saved, or profiler + your OK), ticket, worktree
├─ Phase 2  Define agent .. SPEC.md — the testable contract + SIZE CHECK  (→ reviewer)
├─ Phase 3  Planner ....... IMPLEMENTATION.md — the technical how  (→ reviewer)
│           Acceptance tester  held-out checks from the spec, proven to fail, sealed [optional gate]
├─ Phase 4  Coder ......... code + tests (given only the plan)
├─ Phase 5  Cleanup + verifier  /simplify → quality gate → RUN the checks vs. the withheld spec
└─ Phase 6  orch + reviewers  code review panel ∥ security review → [GATE] PR + CI → [GATE] main
            Triager ......... reads red CI logs and human PR comments, so the orchestrator never does
            Define agent .... rules again when a later step proposes a SPEC.md change (Phases 5–6)
            Planner ......... rules on the coder's plan proposals (Phases 4–6)
            Acceptance tester  rules per condition on every questioned check (Phases 4–6)
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
- **Held-out acceptance checks.** An acceptance tester writes black-box tests
  from the spec alone, one for each condition's example and one for its edge
  case. Every check for new behavior must **fail on the untouched code for the
  right reason**, and the tester saves that run. Each check goes where a
  developer would put that test: into the test file the code already has, or
  a new test file only for code that has none, so the PR adds no test files
  just for the checks. The checks are then sealed out of the worktree; the
  coder never sees them.
- **Merged back in after the build.** The pipeline puts each check back into
  its file among the coder's own changes to it
  (`skills/auto-dev/scripts/lib/sealed.py`). When it can't (the coder made the
  same new test file, or rewrote the lines around a check), the acceptance
  tester adds its tests to the coder's file, changing none of the coder's
  lines.
- **An independent verifier that runs things.** After the build, a fresh
  verifier installs the checks and **runs** them, without seeing the plan or the
  coder's report. Each condition gets a verdict and an evidence tier: **Strong**
  (the held-out checks pass, cover the example and edge case, and were seen
  failing on the old code), **Adequate** (the checks pass, and for what they
  don't prove it ran something itself and saw what it predicted) or **Weak** (a
  code citation, which never counts as met). A condition no agent can observe is
  handed to you at the PR gate as a manual check.
- **A test-integrity audit.** `scripts/check-tests.py` flags deleted or skipped
  tests, removed assertions, new tests that assert nothing, and any edit to a
  sealed check, even one sharing a file with the coder's tests. Each finding must be justified by the spec or it goes back to
  the coder.
- **Targeted mutation testing.** The verifier plants a few small bugs in the
  changed lines with `scripts/mutate.py`, which restores every file afterwards.
  A planted bug no test catches, on a line a condition depends on, is a test gap
  and goes back to the coder. At most 20 mutants per pass; `mutation.max` in
  `.auto-dev.yml` changes that (`0` turns it off). The planted bugs are chosen
  once and kept for every pass. A re-check runs again only the ones no test
  caught, the ones in files changed since the last finished pass, and new ones;
  the rest keep their earlier result (`autodev.py mutants select` picks them,
  from the code the last finished pass tested). An edited or deleted line in an
  existing test file, a deleted or renamed test file, an added skip or focus
  marker, or a changed test-runner config makes it run them all, and so does a
  missing record. Each pass sizes its run by one cold scoped test run, timed
  when the set is chosen and kept in `evidence/mutation-cold-run.txt` for later
  passes; a pass with no usable saved time measures one first. Any pass then
  re-times it at most once more when its run shows a timeout that was too
  short: the saved time makes the unchanged tests time out, most mutants time
  out, an earlier survivor times out, or, on a pass that reused a saved time,
  a mutant not caught by a timeout last time now times out. So one pass times
  the cold run at most twice, and only the re-time's re-run gets a longer
  timeout, at least twice the first. A time is saved only from a timed run
  that passed; a failing one is reported as a failing test. When the mutants
  to run × that time come to 540 seconds or less, the verifier runs them in
  one blocking call and reads the result at once; a longer run goes to the
  background, and the verifier waits for it with calls that each end by
  themselves after about a tenth of its estimate (30 seconds to 5 minutes),
  repeated until the run is done. The detail is in step 7 of
  `agents/verifier.md`.
- **A spec that can be corrected, but only by its owner.** When late work
  shows `SPEC.md` itself is wrong or incomplete, the verifier, the review judge
  (on the panel's behalf), the security reviewer or the triager (from a PR
  comment) may file a *spec proposal* (`skills/auto-dev/templates/PROPOSAL.md`);
  no other worker can, and none may edit `SPEC.md`. Before the result that
  carried it is acted on, the Define agent rules on it: it applies it, or
  answers STANDS with its reason, and `record` checks `SPEC.md` against each
  answer. A STANDS holds for the rest of the run (the proposal is never sent
  again, and every later verifier pass is told the ruling), and the result is
  acted on as if it carried no proposal, unless a verifier (on that result or
  a later one) finds the code doing what the stood proposal described: then the
  *deviation gate* asks you before the correction would undo it (see *Human
  gates & integrations*). An applied change is redone before
  anything relies on it: the planner revises the plan for the changed
  conditions, the acceptance tester rewrites only their checks (the others are
  held as they are), the coder gets the plan's change (only when the plan
  changed, or a review or PR-comment fix rides along), then cleanup and a full
  first-pass verification; in Phase 6, a re-review and the gate again. Sending
  the proposals costs the round the result's own correction would; the redo
  costs nothing more (`skills/auto-dev/references/S2-build.md`).
- **The plan and the checks can be questioned too, by their owners' rules.**
  Each upstream artifact has one owner who rules on proposals against it, and
  only some workers may file against each:
  - `SPEC.md` (the Define agent): the verifier, the review judge, the security
    reviewer and the triager, as above.
  - The plan's build steps (the planner): the coder alone. A plan proposal
    changes named steps or adds one after the last
    (`skills/auto-dev/templates/CODER_PROPOSAL.md`).
  - The held-out checks (the acceptance tester): the coder, for a check its
    correction brief listed; the verifier, through `REPAIR`; the review judge,
    through a must-fix finding of category `acceptance-check`; and the
    triager, through an `ACCEPTANCE_CHECK` comment. The tester rules once per
    condition: every condition with a manifest row naming the questioned
    check, or with a check in the file a finding or comment names.

  The coder never sees `SPEC.md`, so it can't propose against it; the
  verifier never reads the plan, so it can't propose against that. The owner
  answers each proposal `applied` (the tester: `repaired`) or `stands` with a
  reason, and `record` holds its answer to the rulings: the plan's build
  sequence changes only where an applied proposal says, and a sealed check
  changes only for a condition ruled repaired. When one result carries
  proposals against several artifacts, they settle in order: spec, then plan,
  then checks. A step or condition ruled to stand is not sent again for the
  rest of the run unless something later changes it, and every later
  verifier pass is told which conditions' checks stand. The coder is then
  spawned again in its mode and told only `repaired` or `stands` for each of
  its proposals, never an owner's reason; when the plan changed, its brief
  quotes the revised lines.
- **Re-checked after every change.** Cleanup (`/simplify` and the quality gate)
  runs before the verifier, so the verifier checks the code that ships, and
  both run again after every fix.
- **Every result names the code it checked.** Each verdict, quality-gate report
  and review report carries the git tree hash of the code it checked.
  `scripts/check-fresh.py` compares those stamps with the current code before
  anything relies on them, and a stale result is run again (without spending
  the iteration budget).
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
turn more expensive. So it delegates reads to workers, and `next` ends a long
session at a **checkpoint** after 80 recorded events (about 35 workers;
`checkpoint_events` in `.auto-dev.yml` changes it). Nothing crosses a session
boundary except `.auto-dev/` and the git tree, which also makes an interrupted
run resumable: `autodev.py resume` finds it, and `next` picks up where it
stopped.

## Size check: one PR, or back to you

The Define agent says whether the task fits one PR:

- **FITS** — the pipeline runs every step, the same way for every task: **11
  worker roles** (roles, not spawns). The profiler runs only when the repo has
  no saved profile, and the triager only when CI fails or a person comments.
- **OVERSIZED** — several independent deliverables or subsystems, or a large
  file count. auto-dev builds nothing and hands the task back with its reasons
  and suggested lines to split along. Jira is left alone, and the worktree and
  branch stay, with the commands to remove them. Split the task and run
  auto-dev on each part.

Define also flags a task as **high-risk** (security criteria, auth, payments,
access control or a data migration), which turns on the post-plan gate.

## Review before the PR

Nothing is committed or pushed until the uncommitted change has been reviewed
twice, at the same time, and you have seen the results:

1. **Code review panel.** Three reviewers run `/code-review xhigh`
   independently; the plan sets the reviewer agents' effort (see
   [*Models and effort*](#models-and-effort)). A judge merges their findings and
   checks each one's trigger path in the code. A finding that could be must-fix
   but only one reviewer raised goes to the other two for a re-vote.
2. **Security review.** A security reviewer runs `/security-review` over the
   whole change, and the judge double-checks every High or Medium finding.

One correction fixes every must-fix finding from both, for one round of the
iteration budget. A finding about a held-out check goes to the acceptance
tester, never the coder, and the tester rules on it per condition; a finding
about a check the tester already ruled to stand is not sent to it again (with
nothing else open, the run stops and shows you both sides). A problem that lies in `SPEC.md` rather than the code
goes in a reviewer's report, and the judge files a spec proposal for the panel;
the pass's proposals go to the Define agent together once the pass has settled.
After the correction, the full panel reviews the result again. A re-review of a correction skips the nested `/code-review` and `/security-review` skills: the
reviewers follow the correction and everything downstream of it themselves.

A **rubric** (`skills/auto-dev/templates/rubric.md`) decides what must be fixed:

- **Code findings.** Only correctness bugs, missing or weak tests, and a broken
  held-out check can be must-fix, and each needs a concrete trigger path and 2
  of the 3 reviewers' votes. Scope, performance and design findings are
  advisory. Problems the change didn't introduce are dropped.
- **Test gaps, whole.** A test-gap finding lists every reachable case no test
  covers, so the coder closes the whole gap in one round.
- **Security findings.** One this change introduced, rated High or Medium with
  a traced path the judge confirms, is must-fix; a Low one is advisory. A High
  or Medium one that was already there is shown to you at the PR gate, to note
  as a follow-up or ignore; this PR never fixes it.
- **Confidence.** Every finding and every report carries a confidence level. A
  low-confidence report (say, two reviewers failed, or the security reviewer
  couldn't finish) is flagged at the gate, never
  shown as a clean pass.

After the PR opens, a **triager** reads red CI logs and human review comments,
so their text never reaches the orchestrator and can't steer the run. It sends
only real code problems to the coder (and comments about a held-out check to
the acceptance tester). A red CI run the code can't fix (a missing secret,
infrastructure, a flaky test, an unknown cause) stops the run before Jira
moves; once the cause is fixed and CI re-run, `auto-dev continue` watches it
again. The reviewers'
instructions are in `agents/code-reviewer.md`, `agents/review-judge.md`,
`agents/security-reviewer.md` and `agents/triager.md`.

## Human gates & integrations

Planning and build run unattended. The pipeline pauses for approval:

- before **opening the PR**, and
- before the **main merge**,
- plus an optional **post-plan gate** (on for high-risk tasks, or with
  `gates.post_plan`).

Four more pauses fire only when their situation arises: the **profile
confirmation** (a repo with no saved profile), the **Jira In Progress
confirmation** (only with a ticket, once the size check says the task fits), the
**deviation gate** (below), and the **worktree cleanup offer** (after the merge).

Declining is safe at every gate: `Stop` ends the run; `Hold`, at the PR and
main gates, pauses it so you can resume later. Both leave the branch, the worktree and every artifact on
disk. What each option does is in `skills/auto-dev/references/tables.md`.

- **The PR** opens as a draft and is marked ready before the main gate. Its
  description follows the repo's default PR template (never one from a
  `PULL_REQUEST_TEMPLATE/` folder) and links the Jira ticket. A checklist box in
  the template is ticked only when the run's files show it is true.
  With `pr_review.inline_comments: true`, the review findings left open or
  advisory are posted on the PR.
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
- **CI** is watched with a time limit on the PR, and again after the merge. CI
  that timed out or couldn't be watched is shown as not monitored, never as
  green.
- **Spec changes** made during the run are listed in the PR and main gate
  summaries, each with the worker that proposed it, along with the proposals
  ruled to stand and any no round was left to send. The PR gate summary also
  names each plan or check proposal no round was left to send. After a spec
  change from a PR comment, the redo is committed and the main gate is asked
  again before any merge.
- **The deviation gate** fires when a spec proposal was ruled to stand but the
  verifier finds the code still doing what it described (the condition partial
  or unmet), whoever first proposed it. For that one condition you choose
  `Accept the deviation` (the verifier re-checks, told so; the reviewers are
  told too, and nothing undoes it; no round is spent), `Keep the spec (correct
  the code)` or `Stop`. Accept is not offered for an unmet condition, whose
  acceptance check may fail the quality gate, and a Security/Compliance
  criterion is never deviated from. Accepted deviations are listed in the PR
  and main gate summaries and the final report.

## Stack profiles

A **profile** says how a repo installs its dependencies and which commands make
up its quality gate (test, lint, format check, type check, build). Phase 1 gets
one in this order:

1. **A saved profile.** If you saved one for this repo on an earlier run, Phase 1
   loads it without asking.
2. **A committed `.auto-dev.yml` that sets both `setup` and `gate`.** The repo
   has declared its profile, so there is nothing to research.
3. **Research.** Otherwise the `profiler` worker reads the repo (CI config, task
   runners, manifests, lockfiles, contributing docs) and drafts a profile, citing
   the file and line each command came from and naming anything it guessed. The
   run shows you the draft and asks: save it for this repo, use it for this run
   only, change something, or stop.

`.auto-dev.yml` is applied on top in every case. The schema is in
`skills/auto-dev/references/profiles.md`.

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
      "Bash(python3 <home>/.claude/plugins/cache/auto-dev-marketplace/auto-dev/*/skills/auto-dev/scripts/check-fresh.py *)",
      "Bash(python3 <home>/.claude/plugins/cache/auto-dev-marketplace/auto-dev/*/skills/auto-dev/scripts/check-tests.py *)",
      "Bash(python3 <home>/.claude/plugins/cache/auto-dev-marketplace/auto-dev/*/skills/auto-dev/scripts/mutate.py *)"
    ]
  }
}
```

- One rule per script, not `scripts/*`, so you can leave one out. `mutate.py`
  edits files in the run's worktree to plant bugs and restores them; mutation
  is on by default, so without that rule the verifier waits on a prompt. Drop
  `mutation.max: 0` turns mutation off; drop the rule to approve each run.
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

Then add the profile's own commands to the main checkout's
`.claude/settings.local.json`, which applies to that repo only. Example in
TypeScript:

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
| `mutation.max` | mutants per verifier pass (default 20, `0` = off) |
| `gates.post_plan` | turn the post-plan gate on |
| `branches` | `base` and `prefix` |
| `ci`, `ci_timeout_minutes` | CI watching |
| `worktree_files` | gitignored files (an `.env`, say) to copy into the run's worktree |
| `security_docs` | the repo's security directives (default: `SECURITY.md`, `.github/SECURITY.md`, `docs/security/*.md`; `[]` = none) |
| `symbol_lookup` | a code-index tool to use instead of `grep` |
| `pr_review.inline_comments` | post the open and advisory review findings on the PR |
| `checkpoint_events` | events one session records before it checkpoints (default 80) |
| `jira.states` | the board's state names for In Progress, In Review and Done |

It can also set any profile key (`setup`, `gate`, `test_notes`, …) to override
the profile. Phase 1 validates the file with `scripts/validate-config.py`, so a
mistyped key is reported rather than silently ignored.

## Dependencies

- **Claude Code's built-in tools** only, no other plugins. The `Skill` tool runs
  `/simplify`, `/code-review` and `/security-review`.
- **`gh`** on your `PATH` and authenticated. It opens and merges the PR and
  watches CI (GitHub Actions); Phase 1 stops if it is missing, signed out, or
  `origin` isn't on GitHub.
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
| `check-tests.py` | the verifier's test-integrity audit |
| `mutate.py` | the verifier's mutation testing; restores every file afterwards |

## Models and effort

Each worker is its own agent type in `agents/`, which fixes its tools, model and
effort. The types name model families (`opus`, `sonnet`, `fable`), not versions,
so a new release is picked up without editing the plugin.

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

The orchestrator runs on the session's model; `sonnet` at medium effort is
enough, since `next` makes the decisions and the workers do the judging. To
retune a worker, edit the `model:` / `effort:` frontmatter in `agents/<name>.md`
and the table in `SKILL.md`.

The code reviewers' effort is set per run. The planner writes a
`Review effort:` line in `IMPLEMENTATION.md`: `high` for a small, local,
straightforward change, otherwise `xhigh`. The orchestrator passes it to each
code reviewer, overriding the agent file's `xhigh`.

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
| `tmp/` | workers | long command output |
| `HANDOFF.md` | each session's end, and each checkpoint | the brief for the next session |
| `SPEC.md` | Phase 2 | the testable contract |
| `IMPLEMENTATION.md` | Phase 3 | the technical plan |
| `fixes/` | Phases 2–3 | the Define and plan reviewers' FIX blocks |
| `acceptance/` | Phase 3 | the sealed held-out checks (`files/<path>.sealed`, with `<path>.base`, the file a check adds to, and `<path>.installed`, that file as it was with the check whole), their `MANIFEST.md`, and their runs on the old code |
| `blocked/` | Phases 4–6, coder | build steps the coder stopped on, for the planner |
| `lint/` | Phase 5 | one report per quality-gate check |
| `SPEC_EVAL.md`, `evidence/` | Phase 5 | the verifier's verdicts, what it ran, its required changes (`evidence/corrections.md`), the mutants it keeps across passes (`evidence/mutation-set.json`) and the last finished pass's tree and mutant results (`evidence/mutation-record.json`), plus each re-check's mutant pick (`evidence/mutation-select.txt`) and the cold test-run time it sizes mutant runs by (`evidence/mutation-cold-run.txt`) |
| `review/`, `CODE_REVIEW.md`, `SECURITY_REVIEW.md` | Phase 6 | the panel's raw reports, the judge's code review, the security review, and the review's required changes for the coder |
| `pr-body.md`, `pr-output-comment.md` | Phase 6 | the generated PR description, and output moved out of it when too long |
| `triage/` | Phase 6 | the triager's required changes for red CI and human comments |
| `proposals/` | Phases 4–6 | the filers' spec proposals (`<worker>-<n>.md`) and the coder's plan and check proposals (`coder-<n>.md`); each batch sent to the Define agent (`batch-<k>.md`), the planner (`plan-<k>.md`) or the acceptance tester (`checks-<k>.md`), and its rulings (`…-<k>-rulings.md`); copies of `SPEC.md` taken when a filer or the Define agent was briefed (`spec-<sha>.md`), and of the plan and the sealed checks taken when the planner or the tester was briefed to change them (`snapshots/`) |
| `redo/` | Phases 5–6 | the plan as it was before a spec redo revised it, and the plan's change for the coder |
| `lookups/` | any phase | lookup answers |

## Safety

Autonomous but bounded:

- **One iteration budget per task** (default 4 revise rounds) covers every
  correction, every Define or plan re-review, and every batch of spec
  proposals sent to the Define agent (the redo after it costs nothing more).
  A coder result's plan and check proposals cost one round, from the consumer
  that pays for that coder run, covering the owners' rulings and the coder's
  next run; a result that is also `BLOCKED` still costs one.
- **A later step can only propose a spec change.** Only the verifier, the
  review judge, the security reviewer and the triager may file one; a
  Security/Compliance criterion can be added, never edited or removed; PR
  comment wording reaches the Define agent only as the triager's summary,
  marked as a claim to check (CI logs never reach it); a spec change after the
  PR opens is committed and shown at the main gate before any merge; a
  proposal with no round left is named in the stop report or gate summary.
  Code that deviates from a condition ruled to stand ships only if you accept
  that deviation at the deviation gate, one condition at a time.
- **Each artifact has one owner, and only some workers may question it.** The
  coder proposes against the plan's steps and the checks it was shown, never
  `SPEC.md`; the verifier, the review judge and the triager question a check
  only through their own routes, never in a proposal file; the security
  reviewers file against `SPEC.md` alone; `record` refuses anything else. A
  question about a check the tester ruled to stand, raised again with nothing
  else open, stops the run and reports both sides, and a step or check ruled
  to stand is never sent again unless something changes it.
  A spec redo whose rewritten checks still have gaps after its one free tester
  re-spawn, or that needs a second ambiguity ruling, stops the run instead of
  looping.
- **It stops and reports** rather than commit a red build, weaken a security
  control, or carry on when a planted bug may be left in the tree, the build
  edited a submodule, or a commit holds code no result checked.
- **It never acts on stale results.** No gate is asked, and no PR description
  written, on results checked against other code.
- **It refuses a quality gate with no test command**, which would pass by having
  nothing to check.
- **It merges to main only through a PR**, only after your approval, and if
  `gh pr merge` is refused it tells you why instead of working around branch
  protection.

Some stops last until you fix the cause and say `auto-dev continue`: a stop on
a worker (it stopped on purpose twice, failed twice, or never left a usable
result), a refused `pr publish`, and red CI the code can't fix. A push to the PR
branch stops the run until you bring those commits into the worktree, where
they are checked again. A stop on a result (a red gate, an impossible spec, a
possibly planted bug, the budget used up) stays.

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
tools/eval-run.py       gives each pipeline eval its own branches of the fixture repo, and cleans them up
ruff.toml               lint config
.github/                CI workflow and PR template
.githooks/              the pre-commit hook (turn on with `git config core.hooksPath .githooks`)
CLAUDE.md               conventions for agents (and people) changing this repo
UPGRADING.md            what changed in each release, and whether a run in flight resumes
```

## Contributing

Before pushing, run the same checks CI runs:

```
ruff check .
python3 tools/check-repo.py
python3 -m unittest discover -s tests
```

Turn on the pre-commit hook once per clone with `git config core.hooksPath
.githooks`. It runs `tools/check-identity.py`, which stops a commit when a
staged file names you: your git name or email, your login name or your GitHub
username.

Branch and PR conventions, the README checklist, the language-agnostic rules,
the rules for changing a script and how to run the pipeline evals are in
[`CLAUDE.md`](CLAUDE.md).
