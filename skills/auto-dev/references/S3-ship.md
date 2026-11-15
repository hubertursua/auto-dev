# S3 — Ship (Phase 6)

`autodev.py next` drives S3 too, but here it hands you a few steps to do with
your own tools: writing a commit subject and two PR paragraphs, pushing,
moving Jira, watching CI after the merge, and the final report. Each is below.
`autodev.py` means `python3 <skill-dir>/scripts/autodev.py`.

## 1. Enter the worktree

`cd <worktree>` (the tree `resume` printed). Read `.auto-dev/HANDOFF.md`.

## 2. Run the loop

Follow **The loop** in `SKILL.md` until `next` exits 3, 4 or 6. What you will
see in S3, in order:

1. Commit, push, the PR body and `pr publish`: steps 3–5 below. The verified
   build opens as a **draft PR before any review**, so CI starts on it while
   the reviews run; its description says it is not reviewed yet. With
   `gates.open_pr: true` in `.auto-dev.yml`, the open-the-PR gate asks first
   (exit 5): `Open PR`, `Hold (don't push yet)` or `Stop`.
2. Three `code-reviewer`s and a security reviewer in one message, on the
   draft's commit, then the `review-judge` (twice in one message when the
   security review found something to verify), maybe re-votes by the
   reviewers. Must-fix findings from either review run one correction
   (`coder`, `cleanup`, `verifier`), and the panel and the security reviewer
   review it, without the nested skills, before it is committed on top,
   pushed and published again (steps 3–5). A finding that a held-out
   acceptance check is wrong goes to the `acceptance-tester` in repair mode,
   never the coder, on the same round; it repairs the check, or answers
   `STANDS` when it finds the check right, which stops the run and asks the
   user (#22).
   A criterion the judge (for the panel) or the security reviewer finds wrong
   or missing in SPEC.md (`spec-problems/<worker>-<n>.md`) stops the run once
   the judge has consolidated the pass and checked the security findings,
   before any correction (#21): no worker changes the
   spec, the user decides (`references/S2-build.md`, step 4).
   Once the reviews settle, `next` asks you to run `pr publish` again: the
   description gets the reviews.
3. `ci-watch` on the draft. Whatever it exits, run its `AFTER` line (`next`):
   `next` asks for `ci-watch` again only while CI is `PENDING`. A draft with no
   check after the grace period (some workflows skip drafts) is `UNAVAILABLE`:
   the run goes on, and CI is watched again once the PR is marked ready; CI
   that never ran is shown as not monitored, never as green. A red check
   sends the `triager`. A code failure runs a correction, a review and a new
   commit. Any other class (`INFRA`, `FLAKY`, `UNKNOWN`, `SECRET`) is not the
   code's to fix: `next` stops and reports it (exit 4). Once the cause is
   fixed and CI re-run, _I fixed it myself_ (or `auto-dev continue`) watches
   it again.
4. The ready-for-review gate (exit 5): `Mark ready for review`, `Hold (keep it
   a draft)` or `Stop`. With pre-existing security findings it asks one more
   question per finding (_What each gate option does_ in
   `references/tables.md`): run the `mark triage-<ID>` line for each answer.
   Then `gh pr ready`, as printed.
5. Jira In Review, CI watched once more (workflows that skip drafts run now,
   so green from the draft's checks doesn't count), the `triager` on human
   PR comments, the main gate, `merge-pr`. A human blocker goes to the coder;
   a comment saying a held-out check is wrong goes to the acceptance tester's
   repair mode (the triager writes it to `triage/human-<n>-checks.md`), and a
   `STANDS` stops the run as above. When both come back, the tester goes
   first, on one round. A comment that says the spec itself is wrong is a
   claim: the triager lists it, in its own words and naming the comment's id,
   in `spec-problems/triager-<n>.md`, and the run stops for the user before
   any correction (#21). CI mode never reports one.
6. CI on the base branch, Jira Done, the final report, the worktree question.

## 3. Commit

`next` prints a `commit` command with `--message "<type>(<scope>): <summary>"`.
Replace it, inside its single quotes, with a Conventional Commits subject for
the change: `feat`, `fix`, `refactor`, `test`, `docs` or `chore`; a scope only
if the repo's history uses them; an imperative summary under 72 characters,
with no single quote in it (rephrase, or use ’). Take the summary from the
`Task:` and `Ask:` lines of `HANDOFF.md`, not from the code. Run it, then `next` (it reads the
result, whatever the exit code).

## 4. Push

`git -C <worktree> push -u origin HEAD`, exactly as printed. Never `--force`.
If the push is rejected, tell the user what git printed and stop; don't run the
`AFTER` line.

## 5. The PR body

`next` names `pr-write.md`: the sections of the generated `pr-body.md` that
are yours to write, after the sources they draw on, quoted: `SPEC.md`'s
Context and Assumptions, the task, and the description's checked requirements,
Quality gate and Review. Edit `pr-write.md` below its line `<!-- auto-dev: the
sections you write start here; keep this line -->`, never `pr-body.md`, and
don't read `pr-body.md`: `pr publish` puts each of your sections into it by
heading, and refuses when a heading is changed, missing or added (start no
line of an answer with `## `).
(A run whose `next` names `pr-body.md` alone predates this file: edit that.)
Each section holds a line like `<!-- WRITE: ... -->`: always one for the
Summary and one for the Assumptions, and one for each section of the repo's
own PR template the script couldn't fill, or whose checklist is yours to tick.
Replace each with plain sentences for a developer who has never heard of
auto-dev, and keep every `## ` heading as it is:

- **Summary:** what changed and why, 2–4 sentences, from `SPEC.md`'s Context.
- **Assumptions:** the open assumptions from `SPEC.md`'s Assumptions section a
  reviewer should check, one bullet each, or `None.`
- **A template section:** answer what its WRITE line asks, from `SPEC.md` or
  `HANDOFF.md`. If neither says, write `N/A`. Never read the code to answer it.
- **A template checklist:** tick a box (`- [x]`) when the sources, `SPEC.md`
  or `HANDOFF.md` show it is true, and leave it unticked when they don't, or
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
the triager to skip it; never post on the PR yourself. Then run the `AFTER`
line, `autodev.py pr publish`:

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
`state.json` (`autodev.py show`), `HANDOFF.md`, `profile.md` and what `next`
printed. Then run its `AFTER` line.

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
A run that started in a worktree the user made never asks: that worktree stays.
If git refuses (exit 1), leave the tree and tell the user which files are in
it.

## Stops in S3

Every stop is exit 4 with its reason in `REPORT`
(`references/tables.md`, _Stop conditions_), and most ask how to go on
(`SKILL.md`, _A stop_). The ones that need care:

- **CI red at the main gate (#18):** never merge over it; name each red check.
- **The budget ran out after the commit (#12):** tell the user each open
  finding or red check the `REPORT` names, and that they can go on with more
  rounds if they say how many (`references/tables.md`, _The iteration
  budget_).
- **Someone pushed to the PR branch (#17):** tell the user what the `REPORT`
  says: to ship those commits, they bring them into the worktree with the
  `git merge --ff-only` command it names and say `auto-dev continue`. `next`
  then re-checks them (quality gate, verifier, a review pass on what they
  changed), `commit` verifies the new head, or commits the re-check's edits on
  top, and the main gate is asked again.
- **GitHub refused or queued the merge (#19):** say what blocks it; Jira stays
  where it is.
