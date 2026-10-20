# S3 — Ship (Phase 6)

`autodev.py next` drives S3 too, but here it hands you a few steps to do with
your own tools: writing a commit subject and two PR paragraphs, pushing,
moving Jira, watching CI after a merge, and the final report. Each is below.
`autodev.py` means `python3 <skill-dir>/scripts/autodev.py`.

## 1. Enter the worktree

`cd <worktree>` (the tree `resume` printed). Read `.auto-dev/HANDOFF.md`.

## 2. Run the loop

Follow **The loop** in `SKILL.md` until `next` exits 3, 4 or 6. What you will
see in S3, in order:

1. Three `code-reviewer`s in one message, then the `review-judge`, maybe
   re-votes by the reviewers, then a security reviewer and the judge again.
   A must-fix finding runs a correction (`coder`, `cleanup`, `verifier`) and
   the panel reviews the files it changed.
2. The PR gate (exit 5).
3. Commit, push, PR body, publish: steps 3–5 below.
4. `ci-watch`; a red check sends the `triager`, and a code failure runs a
   correction, a review and a new commit.
5. Jira In Review, the staging gate, the `triager` on human PR comments, `gh pr
   ready`, the main gate, `merge-pr`.
6. CI on the base branch, Jira Done, the final report, the worktree question.

## 3. Commit

`next` prints a `commit` command with `--message "<type>(<scope>): <summary>"`.
Replace it with a Conventional Commits subject for the change: `feat`, `fix`,
`refactor`, `test`, `docs` or `chore`; a scope only if the repo's history uses
them; an imperative summary under 72 characters. Take the summary from the
`HANDOFF.md` task line, not from the code. Run it, then `next` (it reads the
result, whatever the exit code).

## 4. Push

`git -C <worktree> push -u origin HEAD`, exactly as printed. Never `--force`.
If the push is rejected, tell the user what git printed and stop; don't run the
`AFTER` line.

## 5. The PR body

`next` names `pr-body.md`. It holds two lines like `<!-- WRITE: ... -->`.
Replace each with plain sentences for a developer who has never heard of
auto-dev:

- **Summary:** what changed and why, 2–4 sentences, from `SPEC.md`'s Context.
- **Assumptions:** the open assumptions from `SPEC.md`'s Assumptions section a
  reviewer should check, one bullet each, or `None.`

No condition IDs (`C1`), no finding IDs, no `.auto-dev/` paths, no words like
"verifier" or "pipeline". Change nothing else in the file. Then run the `AFTER`
line, `autodev.py pr publish`:

| Exit | Do |
|---|---|
| 0 | published: run `next` |
| 1 | IF it names a WRITE line or a problem in your two sections, fix them and run it again. ELSE tell the user what it printed and stop |
| 2 | tell the user the error and stop |

## 6. Jira

When `next` says to move the ticket, do it as `references/gates-and-jira.md`,
_Moving a ticket_ says, then run its `AFTER` line.

## 7. CI after a merge (staging, then the base branch)

`next` asks you to watch CI on a branch that was just merged into, then run
`autodev.py mark <staging-ci | main-ci> --value <result>`.

1. IF `profile.md`'s CI line says `none`, the value is `not watched`.
2. ELSE run `gh run list --branch <branch> --limit 1 --json
   status,conclusion,url` every 30 seconds, for up to the CI timeout in
   `profile.md`. `completed` with `success` → `green`. `completed` with
   anything else → `red`. Still running at the timeout, or nothing listed →
   `not watched`.
3. IF `red`: tell the user at once, with the link, that the merge is already in
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
- **Review:** <must-fix fixed and open, from the code and security reviews; pre-existing findings left for the user>
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

- **CI red at the main gate (#19):** never merge over it; name each red check.
- **Someone pushed to the PR branch (#18):** tell the user; the pipeline must
  re-check those commits before merging.
- **GitHub refused or queued the merge (#20):** say what blocks it; Jira stays
  where it is.
