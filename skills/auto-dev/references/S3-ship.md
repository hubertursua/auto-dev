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

1. Three `code-reviewer`s and a security reviewer in one message, then the
   `review-judge` (twice in one message when the security review found
   something to verify), maybe re-votes by the reviewers. Must-fix findings
   from either review run one correction (`coder`, `cleanup`, `verifier`), and
   the panel and the security reviewer review it, without the nested skills. A finding that a held-out
   acceptance check is wrong goes to the `acceptance-tester` in repair mode,
   never the coder; it may fix the check or answer `STANDS` with its reason,
   and a check that stands is not sent back a second time.
2. The PR gate (exit 5). With pre-existing security findings it asks one more
   question per finding (_What each gate option does_ in
   `references/tables.md`): run the `mark triage-<ID>` line for each answer.
3. Commit, push, PR body, publish: steps 3–5 below.
4. `ci-watch`. Whatever it exits, run its `AFTER` line (`next`): `next` asks
   for `ci-watch` again only while CI is `PENDING`. After `TIMEOUT` or
   `UNAVAILABLE` the run goes on, and the main gate shows CI as not monitored;
   never call it green. A red check sends the `triager`. A code failure runs a
   correction, a review and a new commit. Any other class (`INFRA`, `FLAKY`,
   `UNKNOWN`, `SECRET`) is not the code's to fix: `next` stops and reports it
   (exit 4) before Jira moves to In Review. Once the cause is fixed and CI
   re-run, `auto-dev continue` watches it again.
5. Jira In Review, the `triager` on human PR comments, `gh pr ready`, CI watched once more (some workflows skip drafts, so green from the
   draft's checks doesn't count), the main gate, `merge-pr`. A human blocker
   goes to the coder; a comment saying a held-out check is wrong goes to the
   acceptance tester's repair mode (the triager writes it to
   `triage/human-<n>-checks.md`). When both come back, the tester goes first.
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

`next` names `pr-body.md`. It holds lines like `<!-- WRITE: ... -->`: always
one for the Summary and one for the Assumptions, and one for each section of
the repo's own PR template the script couldn't fill, or whose checklist is
yours to tick. Replace each with plain sentences for a developer who has never
heard of auto-dev:

- **Summary:** what changed and why, 2–4 sentences, from `SPEC.md`'s Context.
- **Assumptions:** the open assumptions from `SPEC.md`'s Assumptions section a
  reviewer should check, one bullet each, or `None.`
- **A template section:** answer what its WRITE line asks, from `SPEC.md` or
  `HANDOFF.md`. If neither says, write `N/A`. Never read the code to answer it.
- **A template checklist:** tick a box (`- [x]`) when `SPEC.md`, `HANDOFF.md`
  or the description's own sections show it is true, and leave it unticked when
  they don't, or when only a person can confirm it (a manual test, a sign-off).
  Never read the code to decide. Add no note saying why: the code and the rest
  of the description show it. Keep every item's words, and don't add, drop or
  reorder one (`pr publish` refuses that). Then delete the WRITE line. This
  counts only when the PR has no description yet: after that the live
  checklist stands, as a person may have ticked or edited it on GitHub.

No condition IDs (`C1`), no finding IDs, no `.auto-dev/` paths, no words like
"verifier" or "pipeline". What the description quotes word for word (test
names, commands and their output, the verifier's reasons under Changes to
tests and Test strength, between the `<!-- auto-dev:quoted -->` markers) is exempt from the ID, `.auto-dev/` path, term and tier checks, and is not yours to
edit. Change nothing else in the file: the follow-ups the user sent to a
separate PR at the PR gate are already listed in it.
`pr publish` ends everything it posts with `<!-- auto-dev -->`, which tells
the triager to skip it; never post on the PR yourself. Then run the `AFTER`
line, `autodev.py pr publish`:

| Exit | Do |
|---|---|
| 0 | published: run `next`. A failure to post the review findings (its `inline_comments` line) is saved; `next`'s final-report step names it |
| 1 | IF it names a WRITE line or a problem in a section you wrote, fix them and run it again. ELSE tell the user what it printed and stop |
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

**Unresolved / skipped:** <unmet conditions, open findings, skipped steps — or "none">

**Follow-ups:** <findings the user sent to a separate PR — or "none">
```

Say plainly what was skipped or left open. Never report a step as done that
wasn't. A run that stopped early uses the same shape and says where it stopped.

## 9. The worktree

The last question (exit 5) is whether to remove the worktree. On `Remove it`,
`next` exits 3 with a `cleanup-worktree` command: run it from the main checkout.
If git refuses (exit 1), leave the tree and tell the user which files are in
it.

## Stops in S3

Every stop is exit 4 with its reason in `REPORT`
(`references/tables.md`, _Stop conditions_). The ones that need care:

- **CI red at the main gate (#18):** never merge over it; name each red check.
- **Someone pushed to the PR branch (#17):** tell the user what the `REPORT`
  says: to ship those commits, they bring them into the worktree with the
  `git merge --ff-only` command it names and say `auto-dev continue`. `next`
  then re-checks them (quality gate, verifier, a review pass on what they
  changed), `commit` verifies the new head, or commits the re-check's edits on
  top, and the main gate is asked again.
- **GitHub refused or queued the merge (#19):** say what blocks it; Jira stays
  where it is.
