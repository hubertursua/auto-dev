# Ship stage (Phase 6)

`autodev.py next` drives the Ship stage too, but here it hands you a few steps to do with
your own tools: writing a commit subject and the PR body's sections, pushing,
moving Jira, watching CI after the merge, the final report and the worktree
question, plus the few in section 2. Each is below.
`autodev.py` means `python3 <skill-dir>/scripts/autodev.py`.

## 1. Enter the worktree

Coming from the Build stage, you are in it already. On a run resumed in the
Ship stage, `cd <worktree>` (the tree `resume` printed) and read
`.auto-dev/HANDOFF.md` if there is one.

## 2. Run the loop

Follow **The loop** in `SKILL.md` until `next` exits 3, 4 or 6. `next` names
each worker to spawn, each command to run and each gate to ask. The steps that
are yours, besides steps 3–9 below:

- **The quality gate**, when a correction runs, or when a CI watch can't see
  CI (it timed out or found no checks) after a gate that ran its test check
  only on the change's tests or left it to CI: `autodev.py quality-gate`, as
  printed, with the Bash tool's timeout at 600000 ms. Whatever it exits, run its `AFTER` line.
- **`ci-watch`.** Whatever it exits, run its `AFTER` line (`next`). Never
  report CI as green when it never ran. On `CONFLICT` (exit 4: the PR conflicts
  with its base, so no check runs), tell the user the PR conflicts with its
  base and that they bring the base in themselves, with the commands its line
  names (fetch the base, merge it in the worktree, resolve, push). You never
  merge or edit the code: you only run `next`, which re-checks a head pushed
  from the worktree that the run didn't make.
- **The ready-for-review gate (exit 5).** With pre-existing security findings
  it asks one more question per finding (_What each gate option does_ in
  `references/tables.md`): run the `mark triage-<ID>` line for each answer.
  Then `gh pr ready`, as printed.

## 3. Commit

`next` prints a `commit` command with `--message "<type>(<scope>): <summary>"`.
Replace it, inside its single quotes, with a Conventional Commits subject for
the change: `feat`, `fix`, `refactor`, `test`, `docs` or `chore`; a scope only
if the repo's history uses them; an imperative summary under 72 characters,
with no single quote in it (rephrase, or use ’). Take the summary from the
task and its restated ask (the `STATE:` and `ask:` lines `autodev.py show` prints), not from the code. Run it, then `next` (it reads the
result, whatever the exit code).

## 4. Push

`git -C <worktree> push -u origin HEAD`, exactly as printed. Never `--force`.
If the push is rejected, tell the user what git printed and stop; don't run the
`AFTER` line. When the user rebased or amended the branch in the worktree, so
it no longer builds on the commit the run pushed, `next` stops (#16) instead of
printing the push: only the user force-pushes.

## 5. The PR body

`next` names `pr-write.md`: the sections of the generated `pr-body.md` that
are yours to write, after the sources they draw on, quoted: `PLAN.md`'s
Context and Assumptions, the task, and the description's checked requirements,
Quality gate and Review. Edit `pr-write.md` below its line `<!-- auto-dev: the
sections you write start here; keep this line -->`, never `pr-body.md`, and
don't read `pr-body.md`: `pr publish` puts each of your sections into it by
heading, and refuses when a heading is changed, missing or added (start no
line of an answer with `## `).
Each section holds a line like `<!-- WRITE: ... -->`: always one for the
Summary and one for the Assumptions, and one for each section of the repo's
own PR template the script couldn't fill, or whose checklist is yours to tick.
Replace each with plain sentences for a developer who has never heard of
auto-dev, and keep every `## ` heading as it is:

- **Summary:** what changed and why, 2–4 sentences, from `PLAN.md`'s Context.
- **Assumptions:** the open assumptions from `PLAN.md`'s Assumptions section a
  reviewer should check, one bullet each, or `None.`
- **A template section:** answer what its WRITE line asks, from `PLAN.md` or
  the task (`autodev.py show`). If neither says, write `N/A`. Never read the code to answer it.
- **A template checklist:** tick a box (`- [x]`) when the sources, `PLAN.md`
  or the task show it is true, and leave it unticked when they don't, or
  when only a person can confirm it (a manual test, a sign-off).
  Never read the code to decide. Add no note saying why: the code and the rest
  of the description show it. Keep every item's words, and don't add, drop or
  reorder one (`pr publish` refuses that). Then delete the WRITE line. This
  counts only when the PR has no description yet: after that the live
  checklist stands, as a person may have ticked or edited it on GitHub.

No condition IDs (`C1`), no finding IDs, no `.auto-dev/` paths, no words like
"verifier" or "pipeline". What the description quotes word for word (test
names, commands and their output, and what the workers wrote: the verifier's
plain words and reasons, each check for a person, and the reviews' reasons and
open findings, between the `<!-- auto-dev:quoted -->` markers), and each
condition title and gate command it copies, is exempt from the ID,
`.auto-dev/` path, term and tier checks; it is not in
`pr-write.md`, and not yours to edit. Change nothing else in `pr-write.md`:
the follow-ups the user sent to a separate PR at the ready-for-review gate are
listed in the description once `next` publishes it again.
`pr publish` ends everything it posts with `<!-- auto-dev -->`, which tells
the triager to skip it; never post on the PR yourself. A description over
GitHub's limit has its quoted command output cut to the last lines, and moved
to the PR's output comment, by `pr publish` itself; when it is still too long,
its exit 1 names the sections written by hand to shorten in `pr-write.md`.
Then run the `AFTER` line, `autodev.py pr publish`:

| Exit | Do |
|---|---|
| 0 | published: run `next`. A failure to post the review findings (its `inline_comments` line) is saved; `next`'s final-report step names it |
| 1 | IF it names a WRITE line or a problem in a section you wrote, fix them in `pr-write.md` and run it again. ELSE tell the user what it printed and stop |
| 2 | tell the user the error and stop |

## 6. Jira

When `next` says to move the ticket, do it as `references/gates-and-jira.md`,
_Moving a ticket_ says, then run its `AFTER` line.

## 7. CI after the merge

`next` asks you to watch CI on the base branch once the PR is merged, then run
`autodev.py mark main-ci --value <result>`.

1. IF `profile.md`'s CI line is anything but `github-actions` (`none`,
   `circleci`, `gitlab`, …), the value is `not watched`: `gh run list` sees
   only GitHub Actions.
2. ELSE find the commit the merge made with the command `next`'s `ACTION`
   names: `gh pr view <PR number> --json mergeCommit -q .mergeCommit.oid`.
3. Run `gh run list --commit <sha> --json status,conclusion,url,workflowName`
   every 30 seconds, for up to the CI timeout in `profile.md`:
   - any run `completed` with a conclusion other than `success`, `skipped` or
     `neutral` → `red`;
   - at least one run listed, and every run `completed` with `success`,
     `skipped` or `neutral` → `green`;
   - nothing listed, or a run still going, at the timeout → `not watched`.
4. IF `red`: tell the user at once, with the link, that the merge is already in
   and the branch's CI failed. Never revert, re-push or fix it unasked. Then
   mark it and run `next`.

## 8. The final report

When `next` asks for it, write this for the user, filling every line from
`state.json` (`autodev.py show`), `profile.md` and what `next` printed. Then run its `AFTER` line.

```markdown
## auto-dev — <task or ticket> — <shipped | stopped at <phase>: <reason>>

- **PR:** <url> (<merged | open | draft>)   **Branch:** <branch>   **Worktree:** <path>
- **Built:** <what changed, 1–3 sentences>
- **Quality gate:** <each check and its final status>
- **Checked at:** <the verified commit>
- **Review:** <must-fix fixed and open, from the code and security reviews; pre-existing findings the user ignored>
- **Jira:** <transitions made | none — no ticket>
- **Iteration budget:** <remaining>/<total>

**Assumptions:** <the ones a reviewer should know about>

**Deviations from the plan:** <each step the coder built differently from the plan, and why (the `deviated from the plan` lines of the gate summaries) — or "none">

**Overrides at a stop:** <each sign-off, fix and retry the user chose when the run stopped, as the ready-for-review gate summary's `Signed off by the user` / `Fixed at the user's instruction` / `Run again after the user fixed the cause` lines name them — or "none">

**Unresolved / skipped:** <unmet conditions, open findings, skipped steps — or "none">

**Follow-ups:** <findings the user sent to a separate PR — or "none">
```

Say plainly what was skipped or left open. Never report a step as done that
wasn't. A run that stopped early uses the same shape and says where it stopped.

## 9. The worktree

The last question (exit 5) is whether to remove the worktree. On `Remove it`,
`next` exits 3 with a `cleanup-worktree` command: run it from the main checkout.
The run's `metrics.json` survives it: `next` writes a copy outside the worktree,
at the path the question names. When that copy could not be written, the
question and the ACTION say so and name `.auto-dev/metrics.json` instead: the
user saves it, or says to go on, before `cleanup-worktree` runs; if they decide
to keep the worktree instead, run the `gate cleanup keep` command that ACTION
names. Until `cleanup-worktree` has run, `next` gives the same ACTION again (and
`resume` picks the run up for it), so a session that ended before the user
answered can finish it. If git refuses (exit 1), `cleanup-worktree` records the
worktree as kept, so the run is finished and `next` gives no ACTION for it
again: leave the tree and tell the user which files are in it. When git
removed part of the worktree before it failed, its `REFUSED` says so and names
what is left: tell the user, who removes it by hand. If the run's state is
still there, the `REFUSED` says so and the worktree is recorded as kept, so
`next` gives no ACTION for it again; if the state went with the tree, nothing
is recorded.
A run that started in a worktree the user made never asks: that worktree stays.

## Stops in the Ship stage

Every stop is exit 4 with its reason in `REPORT`
(`references/tables.md`, _Stop conditions_), and most ask how to go on
(`SKILL.md`, _A stop_). The ones that need care:

- **CI red at the main gate (#17):** never merge over it; name each red check.
- **CI red for a reason the code can't fix (#15: `INFRA`, `FLAKY`, `UNKNOWN`,
  `SECRET`):** tell the user the class and the check. Once the cause is fixed
  and CI re-run, _I fixed it myself_ (or `auto-dev continue`) watches it
  again.
- **The mutation step may have left a change in the source (#10, high risk
  only):** tell the user not to build on the tree until they've checked the
  paths named.
- **A worker found a criterion wrong or missing (#20), or the acceptance
  tester ruled a check right that the verifier or the review called wrong
  (#21):** tell the user each item the `REPORT` names, and ask how to go on.
- **The budget ran out after the commit (#11):** tell the user each open
  finding or red check the `REPORT` names, and that they can go on with more
  rounds if they say how many (`references/tables.md`, _The iteration
  budget_).
- **Someone pushed to the PR branch (#16):** `next` notices it before a CI
  watch, a push or a gate, as well as at the main gate. Tell the user what
  the `REPORT` says: to ship those commits, they bring them into the worktree
  with the `git merge --ff-only` command it names (or, when the run's own
  unpushed commit and theirs diverged, the `git merge` and the push it names)
  and say `auto-dev continue`. When the run's correction is still uncommitted,
  the `REPORT` has them set it aside first (`git add -A` and `git stash push
  --include-untracked`) and bring it back after (`git stash pop`, resolving
  any conflict). `next` then re-checks them (quality gate, verifier, a review
  pass on what they changed), `commit` verifies the new head, or commits the
  re-check's edits on top, and the run goes on from there: the push, CI on
  the new head and the gate it was at. A head pushed from the worktree itself
  needs no stop: `next` re-checks it the same way. When no one pushed but the
  user rebased or amended the branch in the worktree without pushing it, the
  PR branch is still at the commit the run pushed and a plain push would be
  refused: the `REPORT` says so and asks the user to push the rewritten branch
  themselves with the `git push --force-with-lease` command it names and say
  `auto-dev continue`. Never force-push it yourself, and never merge the old
  commits back in.
- **GitHub refused or queued the merge (#18):** say what blocks it; Jira stays
  where it is.
