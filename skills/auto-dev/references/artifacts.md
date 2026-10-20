# Artifacts — the `.auto-dev/` scratch directory

Every run of the pipeline hands state between phases through files under
`.auto-dev/` in the run's worktree — the one Phase 1 creates. This directory
is **scratch, not shippable code**: Phase 1 makes it self-excluding and it must
never appear in a commit, a staged diff, or a PR (see the guardrails in
`SKILL.md`).

The pipeline keeps **two** descriptions of the work — `SPEC.md` (what) and
`IMPLEMENTATION.md` (how) — and nothing in between. Every other file here is
either setup state, a ledger, or verification: the held-out acceptance checks
and the reports that judge the build.

## Contents

- **Why two documents** — why `SPEC.md` and `IMPLEMENTATION.md` stay separate, and
  why the coder never sees the spec.
- **Where artifacts live: `<worktree>` and `<artifact-dir>`** — the two paths every
  brief carries.
- **Layout** — the directory tree.
- **Never commit `.auto-dev/`** — the Phase 1 self-excluding `.gitignore` (written
  and verified by `scripts/exclude-artifacts.py`), why not `.git/info/exclude`,
  and the pre-commit staged check (`scripts/check-staged.py`).
- **`WORK_LOG.md` — the progress ledger** — status rules and:
  - **Template**
  - **Resuming an interrupted run** — read this on any re-entry, planned or not;
    `scripts/resume-point.py` reads the ledger and names the resume point.
  - **Session checklists** — the S1 / S2 / S3 progress checklists to copy into
    TodoWrite, mirroring the ledger.
- **Artifact contracts (what each file must contain)** — what each file *is*, plus
  what deliberately is not an artifact.
- **Stamps: which code each result checked** — the `Tree:` line on every report
  that judges the code, when `scripts/check-fresh.py` compares it with the code
  now, and what its exit codes mean.
- **Artifact templates** — where the skeletons live (`templates/`), and how strict each
  output is (strict vs. flexible, and what reads it back):
  - **`HANDOFF.md` (end of S1 and S2, or a context checkpoint; orchestrator)**
  - **`profile.md` (Phase 1, orchestrator)**
  - **`SPEC.md` (Phase 2, Define agent)**
  - **`IMPLEMENTATION.md` (Phase 3, planner)**
  - **`acceptance/MANIFEST.md` (Phase 3, acceptance tester)**
  - **`SPEC_EVAL.md` (Phase 5, verifier)**
  - **`review/pass-<n>/R<k>.md` (Phase 6a, code reviewer)**
  - **`review/pass-<n>/VOTES-R<k>.md` (Phase 6a, code reviewer re-voting)**
  - **`CODE_REVIEW.md` (Phase 6a, review judge)**
  - **`SECURITY_REVIEW.md` (Phase 6a, security reviewer + review judge)**
  - **`lint/<CHECK>.md` (Phase 5, cleanup agent) — one per `gate` entry**
- **The PR body** — who writes it in Phase 6a, who reads it (a developer who
  doesn't know auto-dev), and the sections it must keep.
- **The final report** — a flexible default shape for the run's last message.

## Why two documents

The pipeline keeps exactly two descriptions of the work, and they answer different
questions:

- **`SPEC.md` — did we build the right thing?** The testable contract: observable
  conditions, no design.
- **`IMPLEMENTATION.md` — did we build it the way we decided?** The technical how.

They fail **independently**. A plan executed faithfully can still miss the
outcome; an outcome can be delivered by a route the plan never described. Merging
them into one document collapses both into a single, weaker check.

**The coder builds from the plan, never the spec.** The plan is _required_ to
cover every condition (Phase 3), so this is not information-hiding — it is
**language**-hiding: the coder cannot satisfy the Phase 5 check by echoing the
spec's own wording back in a test name.

**A third description sits beside them: the held-out acceptance checks**
(`acceptance/`), executable tests written from `SPEC.md` alone before any code
exists, each new-behavior check proven to fail on the untouched tree. The coder
never sees them during the build. The Phase 5 verifier installs and runs them,
and it never sees the plan or the coder's account of the build: it judges the
code against the contract, with neither the builder's story nor the
orchestrator's correction history in its context.

## Where artifacts live: `<worktree>` and `<artifact-dir>`

Phase 1 creates one worktree for the run, and its `.auto-dev/` holds every
artifact. Every brief is filled with **two** absolute paths:

- **`<worktree>`** — where the code lives and the worker does its work.
- **`<artifact-dir>`** — where the artifacts are read and written: always
  `<worktree>/.auto-dev`.

Removing the worktree deletes the ledger with it, so the Phase 6c cleanup offer
waits until after the final report. **Never write `.auto-dev/…` literally into a
brief** — always substitute `<artifact-dir>`.

## Layout

```
.auto-dev/
  profile.md              # resolved project profile (Phase 1) — stack, commands, branches, Jira map
  WORK_LOG.md             # normalized ticket + progress ledger + resume point (Phase 1 onward)
  HANDOFF.md              # brief for the NEXT session; overwritten at each session boundary
  SPEC.md                 # the testable contract: context, conditions, assumptions, security (Phase 2)
  IMPLEMENTATION.md       # the technical plan — how (Phase 3)
  acceptance/             # held-out checks from SPEC.md alone (Phase 3, acceptance tester)
    MANIFEST.md           # condition → check, what it covers, level, kind, base-run result; what is not automatable
    base-run/C<n>.txt     # each condition's checks run on the untouched tree: command, result, output (<n> is MANIFEST's #: C2, CS1)
    files/<repo-path>.sealed  # the sealed copy of each check; the verifier installs it at <repo-path>
  SPEC_EVAL.md            # code vs. spec, with an evidence tier per condition (Phase 5, verifier)
  evidence/               # what the verifier ran and saw: integrity.txt, acceptance.txt, C<n>.txt, mutants.json(+.results.json)
    corrections.md        # the verifier's required changes for the coder (Phase 5)
  fixes/                  # the Define and plan reviewers' FIX blocks: define-<n>.md, plan-<n>.md (Phases 2–3)
  lint/                   # one report per quality-gate check (Phase 5)
    TYPECHECK.md          # one file per check in the profile's `gate` list —
    LINT.md               # example in TypeScript; the filenames come from the
    FORMAT.md             # profile, so another stack has another set
    TEST.md
  review/                 # raw code-review reports, one directory per pass (Phase 6a)
    pass-1/
      R1.md  R2.md  R3.md   # the three panelists' own findings
      VOTES-R2.md           # re-votes on lone findings, when any
      corrections.md        # the judge's required changes for this pass's open must-fix findings
    security-corrections.md # the security-verify judge's required changes
  CODE_REVIEW.md          # the judge's consolidated code review: verdicts, votes, confidence (Phase 6a)
  SECURITY_REVIEW.md      # the security review: origin, confidence, verification (Phase 6a)
  triage/                 # the triager's required changes: ci-<n>.md, human-<n>.md for the coder,
                          # human-<n>-checks.md for the acceptance tester (Phase 6)
  briefs/                 # each worker's brief file, <worker>-<n>.md (autodev.py brief)
  returns/                # each worker's result, <worker>-<n>.json
  lookups/                # lookup answers, <n>.md (any phase)
```

## Never commit `.auto-dev/`

In Phase 1, immediately after creating the worktree, run
`python3 <skill-dir>/scripts/exclude-artifacts.py <worktree>`. It does exactly
this, then proves it with `git status --porcelain --untracked-files=all --
.auto-dev/` (must print nothing) and `git check-ignore -q .auto-dev/WORK_LOG.md`
(must succeed):

```bash
mkdir -p .auto-dev/lint
printf '*\n' > .auto-dev/.gitignore
```

Without `python3` (exit `127`), run those two commands by hand and confirm with
`git status` that nothing under `.auto-dev/` appears. The script's exit handling
is in `references/phase-1-setup.md`, step 6.

The exclusion is mechanical, so it survives even a stray `git add -A`, and it is
removed along with the worktree.

**Do not use `.git/info/exclude`.** Inside a linked worktree `.git` is a *file*
(`gitdir: …`), not a directory, so `echo … >> .git/info/exclude` fails with "not
a directory" and the exclusion silently never happens. Nor is the path
`git rev-parse --git-path info/exclude` resolves to a fix: that is the **main
repository's shared** exclude file, so writing there affects every other worktree
and outlives this run.

Phase 6 also stages source paths **explicitly**
(`git add -- <path> …`, and `git rm --cached` for deleted paths) and never uses
`git add -A`/`.`, and before committing
confirms nothing under `.auto-dev/` is staged, with `scripts/check-staged.py`
or its manual equivalent (`references/phase-6-ship.md`, step 4).

Note: `.auto-dev.yml` (the optional repo-local **override**, see
`references/profiles.md`) is a *different* file — it lives at the repo root, is
meant to be committed by the project, and is **not** excluded. A **saved
profile** (`references/profiles.md`, _Saved profiles_) is not an artifact either:
it lives in the user's home directory, outside every checkout, and outlives the
run.

---

## `WORK_LOG.md` — the progress ledger

The single source of truth for progress within a run, and the **resume point** if a
run is interrupted. The orchestrator writes it in Phase 1, then marks each phase
`in-progress` **before** starting it and `done` once it finishes. Read it first when
resuming.

Write the row on entry, not only on completion: a phase updated only at the end would
still read `pending` after being cut off mid-flight, and step 3 below would trust its
half-written artifact as finished.

Its header also carries the **normalized ticket** — the restated task and its
link — so the ledger is self-describing without a separate ticket file.

**Strict: ALWAYS use the exact structure below** — the same header fields, table
columns and `status` values. Resume finds the run by its header lines and restarts
from the phase tables' `Status` column, so a renamed field or column breaks it.

### Template

```markdown
# Work Log

- **Task:** <one-line description>
- **Ticket:** <JIRA-KEY + link, or "none"> — <restated ask, 1–2 sentences>
- **Repo:** <repo-name>   **Base:** <base-branch>   **Stack:** <profile>
- **Worktree:** <abs-path>   **Branch:** <prefix/slug>
- **Size:** <FITS | OVERSIZED>   **High risk:** <yes | no>
- **Iteration budget:** <n> total revise rounds (<n> remaining)

## Phase status
| # | Phase | Status | Notes |
|---|-------|--------|-------|
| 1 | Setup | done | |
| 2 | Define | in-progress | |
| 3 | Plan | pending | |
| 4 | Build | pending | |
| 5 | Verify | pending | |
| 6 | Ship | pending | staging gate: n/a (no staging branch) |

## Decisions & assumptions
- <recorded as they happen>
```

`Size` and `High risk` are blank until the Define agent returns
(`references/subagent-prompts.md`, _Size check_).

`status` values: `pending` → `in-progress` → `done`. Also valid: `skipped` (the
phase was deliberately bypassed), `n/a` (the
step cannot apply — e.g. the staging gate with no staging branch, recorded in the
Phase 6 row's Notes since Phase 6 is one row), and `blocked`
(with a note; an OVERSIZED task leaves Phase 2 `blocked` with the Notes
`OVERSIZED`, and Phases 3–6 `n/a`). Never leave a phase that will never run sitting at `pending`.

### Resuming an interrupted run

The worktree, the branch, and every artifact produced so far are still on disk.

This covers both kinds of re-entry. A **planned** one — the session boundary at
the end of S1 or S2 (`SKILL.md`, *Session boundaries*) — left a `HANDOFF.md`,
which names the next phase outright; read it with `WORK_LOG.md` and skip to step
3. An **unplanned** one — a crash, a `/clear`, a machine restart — has no handoff
or a stale one, so run the detection below and trust the ledger over the handoff
wherever the two disagree.

1. **Detect.** Before Phase 1 does anything else, look for an existing run's
   worktree. You are standing in the main repo, which never holds `.auto-dev/` — the
   run's worktree is a sibling directory:
   ```bash
   git worktree list     # run worktrees are siblings: ../<repo-name>-<slug>
   ```
   Check each tree it lists for a `.auto-dev/WORK_LOG.md` and read the header. If one
   names this ticket (or states this task, by the rule below), that is the run to
   resume, and its **Worktree** line confirms the path. Two matches — the
   same ticket started twice — is a stop-and-ask, not a guess.

   The script does this check and step 3's lookup in one read-only call per
   tree; pass the Jira key, or the task text when there is no ticket (or no
   `--task` when the user names no task at all — see below):
   ```bash
   python3 <skill-dir>/scripts/resume-point.py <tree>/.auto-dev --task "<ticket or task>"
   ```
   A Jira key must appear as a whole token in the key/link part of the header's
   Ticket line (before the first spaced em dash ` — `; a key the restated ask
   mentions doesn't count, unless that part is a bare "none"), so
   `PROJ-12` never matches a `PROJ-123` ledger, and a Jira URL is matched by its
   key; any other text is compared word by word, ignoring case, punctuation and
   markdown, with the Task line and the ask the Ticket line restates. It matches
   when it has that line's words, or the line with a few words left out (at least
   80% kept, in order, no negation like `not` dropped). When one side's words all
   appear in the other but that is not a match — a fragment like
   `multi-currency`, or the user's longer original request containing the Task
   line — the script reports `NEAR-MISS`: possibly this run, worded differently.
   Whenever the user states the task itself (its ticket key, or what it does),
   pass it as `--task`, even a short one. Run without `--task` only when they
   state none: a bare "continue" or "resume", or a run they only refer to by a
   loose name like "the multi-currency run", which names the run rather than
   stating its task. An empty `--task` counts as omitted, and never pass a
   stand-in like "continue", which is matched as task text. Without `--task` the
   exit code says only what a tree holds: a `3` is a finished run left in place,
   not a candidate. List every tree that exits `0` with its printed task and
   ticket. One plainly the run the user means is the run; two or more, or any
   doubt, is a stop-and-ask, not a guess; none (and no `MALFORMED` ledger that
   may be the run) means there is nothing to continue — tell the user and ask
   what to work on rather than starting a fresh Phase 1.
   It prints the task, ticket, the first phase not complete (`done`, `skipped` or
   `n/a`) with its status, that phase's session, and the remaining budget.
   - `0` — this tree is the run; resume where it says, handling the status as
     step 3 does (and step 4 for Phase 6). A `Blocked:` line means ask the
     user, as step 3 says.
   - `3` — this tree is the run, but every phase is complete: nothing to resume.
     Tell the user the run already finished; re-run no phase.
   - `1` — read the message. `MISSING` or `MISMATCH`: this tree is not the run;
     check the next one. `NEAR-MISS`: it may be the run — after checking every
     tree, show the user each near-miss's task and ask which (if any) is theirs;
     never start a fresh run over one unasked. `MALFORMED` (it names the line or
     field): this may be the run with a broken ledger — read it by hand, and if
     steps 3–5 can't place the resume point, ask.
   - `2` — it couldn't run. Not a result: read that tree's header and phase table
     by hand, as above.
   - `127` — `python3` isn't installed: do the whole detection by hand, as above.
2. **Re-read, don't re-derive.** `profile.md` already holds the resolved stack,
   commands, branches, CI provider, and Jira mapping — do not re-detect any of it.
   The ledger header holds the ticket, worktree, branch, and remaining budget.
3. **Restart at the first phase that is not `done`,** reading its status:
   - `pending` — run it normally.
   - `in-progress` — the phase was cut off mid-flight, so its artifact may be
     partial. **Re-run the whole phase and overwrite the artifact.** Never resume
     *inside* a phase: a half-written artifact is indistinguishable from a
     finished one.
   - `skipped` / `n/a` — move on; the decision behind it still holds.
   - `blocked` — do not quietly retry. Report the recorded reason and ask.
4. **Phase 6 is the exception to blind re-running.** Check the world before
   acting: `git log`, `git status`, whether the branch is on the remote,
   `gh pr view`. A PR may already be open, or already merged. Reconcile the ledger
   to what git and `gh` actually report, then continue from there. With no commit
   on the branch and no PR-gate approval recorded in the Notes, the PR gate has
   not passed: the run was in the reviews, which come before it. Resume them as
   `references/review.md`, _The review loop_, says: re-run every review step the
   Notes do not record as done, and never trust a review report the Notes do not
   vouch for. A correction the Notes record as dispatched but not re-reviewed
   is re-dispatched without spending another round.

   **Before resuming, check the results still match the code** (_Stamps_,
   below). With no commit yet, run `scripts/check-fresh.py <worktree>
   <artifact-dir> --phase 5`; on `1`, re-run them first
   (`references/correction-loop.md`, _Stale results_). Skip it when a correction
   is being re-dispatched: that correction's refresh re-runs and restamps every
   report anyway. With a commit the Notes don't record as `verified commit
   <sha>`, run `check-fresh.py <worktree> <artifact-dir> --ref HEAD` before any
   push; on `1`, push nothing, and stop and report. A verified commit needs
   nothing more here: the PR body and main gate checks cover it.
5. **Re-confirm nothing already confirmed.** A gate approved before the
   interruption stays approved (the ledger records it); a gate not yet reached
   still fires. Do not repeat a Jira transition — read the issue's current status
   instead of assuming it.

The budget carries over: a resumed run continues from the remaining count in the
ledger's header, never a fresh 4 (`references/correction-loop.md`).

### Session checklists

At the start of each session, copy that session's checklist into TodoWrite and
tick items off as you go. The checklist **mirrors the ledger and never replaces
it**: `WORK_LOG.md` stays the source of truth and the resume point, so update its
phase row as well as ticking the item. On a resume, tick whatever the ledger
already marks `done`, `skipped` or `n/a`, and start at the first open item as
steps 3–4 above decide. Each item restates a step from `SKILL.md`, in the same
order. The checklist adds no step, and the detail lives where `SKILL.md` puts it.

```
S1 Plan progress:
- [ ] 1.1 Detect repo & branches; check gh first (missing/unauthenticated/non-GitHub → stop-and-report)
- [ ] 1.2 Resolve the profile: saved (profile-path.py) or researched + confirmed (+ saved if chosen); apply .auto-dev.yml (validated); record CI provider
- [ ] 1.3 Resolve the ticket
- [ ] 1.4 Read binding rules; resolve security directives
- [ ] 1.5 Worktree + branch from fresh origin/<base>; seed worktree_files (each must be gitignored); run setup
- [ ] 1.6 Prep .auto-dev/ self-excluding: exclude-artifacts.py exits 0 (127: by hand; git status shows nothing under it)
- [ ] 1.7 Write profile.md; initialize WORK_LOG.md
- [ ] 2   Define agent → SPEC.md
- [ ] 2.1 Size check (OVERSIZED: record it, report to the user, STOP)
- [ ] 2.2 Jira → In Progress (ticket only, confirmed)
- [ ] 2.3 Define review
- [ ] 3.1 Planner → IMPLEMENTATION.md
- [ ] 3.2 Plan review
- [ ] 3.3 Acceptance tester → acceptance/ (checks sealed, worktree unchanged)
- [ ] 3.4 Post-plan gate (only if enabled for this run)
- [ ] Boundary: update WORK_LOG.md → overwrite HANDOFF.md → tell the user → STOP
```

```
S2 Build progress:
- [ ] 4   Coder builds from IMPLEMENTATION.md only; settle any BLOCKED step; note plan deviations
- [ ] 5.1 Verifier (first pass) → SPEC_EVAL.md (unmet / partial / unjustified integrity → correction + verifier re-check)
- [ ] 5.2 Simplify (cleanup agent, after the acceptance loop settles — not per correction; no budget)
- [ ] 5.3 Quality gate to green → lint/*.md (never by weakening a test)
- [ ] 5.4 Verifier re-check over the final code (unmet → correction + cleanup re-spawn + re-check)
- [ ] 5.5 check-fresh.py --phase 5 exits 0 (stale → re-run them; 127: by hand)
- [ ] Boundary: update WORK_LOG.md → overwrite HANDOFF.md → tell the user → STOP
```

```
S3 Ship progress:
- [ ] 6a.0 Before the commit: check-fresh.py --phase 5 exits 0 (stale → re-run them)
- [ ] 6a.1 Code review panel: 3 × code-reviewer (/code-review xhigh) → judge → re-votes → CODE_REVIEW.md (must-fix → correction loop + cleanup re-spawn + re-review on the fix's files)
- [ ] 6a.2 Security review: security reviewer (/security-review) → judge verifies High/Medium → SECURITY_REVIEW.md (must-fix → correction loop, then 6a.1 on the fix's files, then 6a.2 again)
- [ ] 6a.3 PR gate, once check-fresh.py exits 0 (both reviews' confidence + counts; open must-fix; pre-existing security for the user to triage)
- [ ] 6a.4 Commit: check-fresh.py again first (stale → re-run them, re-ask the gate); explicit paths; check-staged.py --expect <paths> exits 0 (127: by hand) — nothing under .auto-dev/ staged;
           then check-fresh.py --ref HEAD exits 0 (1 → don't push: stop and report)
- [ ] 6a.5 Push (never --force); open PR, its body per _The PR body_ (for a reader who doesn't know auto-dev; "Checked at commit"; size checked); inline review comments only if asked or configured
- [ ] 6a.6 CI monitoring (red pre-merge → correction loop + cleanup re-spawn + Phase 6a refresh, its fix reviewed before re-push)
- [ ] 6a.7 Jira → In Review
- [ ] 6b   Staging gate → direct merge → CI on staging (n/a without staging)
- [ ] 6c.1 Read human reviews; mark the PR ready
- [ ] 6c.2 PR merged/closed → report, stop; fetch the PR branch and base; check-fresh.py --ref origin/<branch> exits 0
           (outside commits → merge them in, re-run the stale results, refresh the PR body)
- [ ] 6c.3 Main gate
- [ ] 6c.4 gh pr merge, explicit method, --match-head-commit <checked sha>, never --admin
           (head moved → back to 6c.2; other refusal → report, stop);
           confirm state MERGED (queued/auto-merge → report, stop)
- [ ] 6c.5 CI on main; Jira → Done
- [ ] Final report
- [ ] Offer worktree cleanup, only now (removing it deletes .auto-dev/)
```

---

## Artifact contracts (what each file must contain)

Briefs for the agents that produce these are in `references/subagent-prompts.md`.
The contracts below define what each file *is*; the templates that follow fix the
shape.

- **`profile.md`** — the resolved project profile from Phase 1: the stack and
  where the profile came from (a saved file, or researched and confirmed, and
  whether it was saved), the exact `setup`/`gate` commands (post-override)
  and any check dropped for a missing tool, base/staging/prefix, CI provider and
  timeout, the iteration budget, the mutation cap, the resolved security-directive sources, and Jira
  availability + state mapping. Every later phase reads this instead of re-detecting.
- **`HANDOFF.md`** — the brief the *next* session reads. It, `WORK_LOG.md` and
  `profile.md` are what a session opens on entry; everything else in here is read
  only by the phase that needs it (`SKILL.md`, *Session boundaries*).
  **Under 60 lines**, overwritten — not appended — at the end
  of S1 and S2 and at any context checkpoint: what is done, the exact next phase, the 3–8 file paths that matter,
  open assumptions, and the one command to re-enter. It is a pointer sheet, not a
  summary: never restate `SPEC.md` or `IMPLEMENTATION.md` in it. A session that
  needs their content either opens them where its own phase requires it (the
  Phase 5 correction briefs, the Phase 6a checklist) or spawns a worker that reads
  them — copying them into the handoff just pays for them twice.
- **`SPEC.md`** — *the testable contract*, and the only statement of what the task
  asks. Four sections: **Context** (the ticket restated, links, and the research
  findings needed to act on it — stakeholder-readable, no technical design);
  **Conditions** (observable, testable conditions defining "this works," in plain
  language, no file names or signatures); **Assumptions** (every resolved
  ambiguity); and **Security/Compliance criteria** when the task touches a
  sensitive path (controls pulled from the security-directive sources `profile.md`
  names). Written in Phase 2; **withheld from the coder**; the basis of the
  acceptance checks, the Phase 5 verifier's verdicts and the PR body's acceptance conditions.
- **`IMPLEMENTATION.md`** — the technical *how*, self-contained: files to
  create/modify, design, data flow, the ordered build sequence (which is the
  coder's worklist), test plan (which test proves which behavior, and where),
  migrations/config. Buildable without the spec; every spec condition maps to a
  build step and a test. Written by the planner in Phase 3.
- **`acceptance/`** — the held-out checks (Phase 3, acceptance tester).
  `MANIFEST.md` maps each `SPEC.md` condition to its checks, each check's part
  of the condition (its Example, its Edge or another part), level, kind
  (`fail-to-pass` or `pass-to-pass`) and its run on the untouched tree, and lists
  the conditions, or edges, no check can drive, with an observable proxy where
  one exists. `base-run/C<n>.txt` keeps each condition's run on the untouched
  tree: the command and its output, the proof that a check for new behavior
  failed before the change. The verifier reads it rather than re-running the
  checks on the old code, and the PR body quotes it.
  `files/` holds the **sealed** copy of each check at its repo-relative path plus
  `.sealed`, a suffix no test runner collects; the worktree holds no copy until
  the verifier installs them in Phase 5. The coder is never given the path, but
  `.auto-dev/` is in its worktree: like `SPEC.md`, the checks
  are withheld by the brief, not by the filesystem. Once
  installed they ship in the PR like any other test, and
  `scripts/check-tests.py` fails any run where an installed copy differs from its
  sealed one.
- **`SPEC_EVAL.md`** — the verifier's judgment of the build against `SPEC.md`
  (which the coder never saw): per condition, security/compliance criteria
  included, a verdict (**met / partial / unmet / manual**), an **evidence tier**
  (**Strong** — the held-out checks passed and prove the whole condition, as
  the verifier's brief defines it; **Adequate** — something the verifier
  ran itself matched its stated expectation; **Weak** — a citation nobody ran,
  which caps the verdict at partial), and the evidence; plus the test-integrity
  audit, each finding judged justified or not, and the mutation check, each
  surviving mutant judged equivalent or a test gap (a test gap on a condition's
  lines caps it at partial). Stamped with the tree it checked (_Stamps_,
  below). Drives the Phase 5 correction loop
  back into the coder. Rewritten in full by every verifier re-spawn. Nothing is
  committed at this point, so the evidence comes from the working tree rather than
  a commit range — `agents/verifier.md` gives the exact invocation, and
  `references/subagent-prompts.md`, _Verifier_, why each half of it matters.
- **`evidence/`** — what the verifier ran and saw: the audit output
  (`integrity.txt`), the acceptance run (`acceptance.txt`), and per condition its
  stated expectation, the command, the result and the last lines of output
  (`C<n>.txt`, which the PR body quotes so a reviewer sees what was run), and
  the mutants it ran with their results (`mutants.json`, `mutants.json.results.json`), plus the
  fixed mutant set and the diff it was chosen from (`mutation-set.json`,
  `mutation-base.diff`), kept across passes so re-checks re-run the same
  mutants and only add new ones for code written since.
  `SPEC_EVAL.md` cites these; the correction brief quotes them.
- **`lint/<CHECK>.md`** — one report per quality-gate command, named per the
  loaded profile — **one per `gate` entry, all of them** (example in
  TypeScript: `TYPECHECK.md`, `LINT.md`, `FORMAT.md`, `TEST.md`): the command run, final
  status, what had to be fixed, and the tail of the final run's output, which
  the PR body quotes.
- **`review/pass-<n>/R<k>.md`** — one code reviewer's own findings for one pass,
  each with a trigger path, plus security leads it noticed. Raw input to the
  judge; nothing else reads it.
- **`review/pass-<n>/VOTES-R<k>.md`** — one reviewer's `agree` / `disagree` on
  the lone findings it did not raise. The orchestrator counts them into
  `CODE_REVIEW.md`.
- **`CODE_REVIEW.md`** — the consolidated code review, across every pass: each
  finding's verdict (must-fix, advisory, noise), votes, confidence, the judge's
  reason, and whether a must-fix finding is `open` or `fixed`; plus the report's
  overall confidence. Drives the review-stage correction loop and the PR gate
  summary.
- **`SECURITY_REVIEW.md`** — the security review of the whole change: each
  finding's origin (introduced or pre-existing), confidence, the judge's
  verification, and verdict (must-fix, for the user, advisory); plus the overall
  confidence. Drives the security corrections and the PR gate's triage of
  pre-existing findings.

  Both review reports stay on disk. Their findings are posted as inline PR
  comments only when the user asks during the run or `.auto-dev.yml` sets
  `pr_review.inline_comments: true` (`references/profiles.md`).

**Not artifacts.** Three things deliberately live outside this directory: the
coder's **report** (deviations, test changes, `BLOCKED` steps), which is part of
its structured return, read by the orchestrator and never by the verifier; the reviewers'
findings (Define review, plan review), which are returned to the orchestrator and
applied as edits to `SPEC.md` / `IMPLEMENTATION.md` rather than written to disk;
and the **PR body**, contracted below.

## Stamps: which code each result checked

Every report that judges the code says which code it judged: a `Tree:` line
holding the git tree hash of the worktree at the moment its writer checked it.
Four reports carry one: `SPEC_EVAL.md` (the verifier), each `lint/<CHECK>.md`
(the cleanup agent), `CODE_REVIEW.md` (the review judge) and `SECURITY_REVIEW.md`
(the security reviewer). The writer gets the hash from
`python3 <skill-dir>/scripts/check-fresh.py --print-tree <worktree>`, and the
templates below show where the line goes. Without `python3`, its brief gets the
by-hand command at the end of this section instead.

**The stamp is the code that was checked, not the code at writing time.** A
writer that checks over a while compares the tree before and after, and writes
`Tree: changed during the run` (read as no stamp, so stale) if they differ. The
verifier does this itself. The two reviews are checked by other agents before
their writer runs, so you take the hash: run `--print-tree` just before
spawning the code review panel, and pass it to the judge's brief
(`--set tree=<hash taken before the panel>`); `autodev.py brief` fills the
security reviewer's `tree` slot itself, at its spawn. The writer writes it only if its own `--print-tree`
still matches.

**Why a tree hash.** The checks run before anything is committed, so there is no
commit to name yet. A tree hash names the exact contents of every file, committed
or not, and every commit carries one, so the same stamp can be compared with the
working tree now, with `HEAD` after the commit, and with the PR's branch on
GitHub. Ignored files and `.auto-dev/` are not part of it.

**Why it matters.** Without a stamp, a result says nothing about which code it
checked. A person editing the worktree, a teammate pushing to the PR, GitHub
merging the base into the branch, or a run cut off between a fix and its re-check
all leave reports that describe code which no longer exists, and nothing would
notice. The stamp makes that visible, and the pipeline re-runs the checks before
any gate or PR body presents them.

**Check before you rely on a result.** Run
`python3 <skill-dir>/scripts/check-fresh.py <worktree> <artifact-dir>` with the
flags below at each of these points. It compares every stamp with the code and
lists each report that checked something else.

| When | Flags | Rule stated in |
|---|---|---|
| End of S2, before the handoff | `--phase 5` | `SKILL.md`, _Phase 5_ step 4 |
| Entry to S3, while nothing is committed | `--phase 5` | `SKILL.md`, _Session boundaries_; _Resuming an interrupted run_, step 4 |
| Before asking the PR gate | none: all four reports, against the working tree | `references/gates-and-jira.md`, _PR gate_ |
| After every Phase 6 commit, before its push | `--ref HEAD` | `references/phase-6-ship.md`, step 4 |
| Before writing or refreshing the PR body | `--ref <the commit the body describes>` | _The PR body_, below |
| Before asking the main gate, after fetching the PR branch | `--ref origin/<branch>` | `references/phase-6-ship.md`, 6c step 2 |

`--phase 5` checks only the reports Phase 5 writes (`SPEC_EVAL.md` and
`lint/*.md`); without it, the two review reports must match too. Its exit code:

- `0` — **fresh**: every report checked exactly this code. Note the tree it
  prints (`Tree now: …`) in the phase row's Notes in `WORK_LOG.md`, and after a
  commit the commit too (`verified commit <sha>`), so the final report and a
  resumed run can say which code was checked.
- `1` — **stale**: a report checked other code, is missing, or has no stamp. It
  lists each one and, while git still holds the old tree, the files changed
  since. Follow `references/correction-loop.md`, _Stale results_, then run the
  check again. Never present a stale result as current, at a gate or in the PR
  body.
- `2` — it couldn't run (git missing, not a work tree, an unknown `--ref`). Not a
  pass: fix the cause it names and re-run it.
- `127` — `python3` isn't installed. Get the hash by hand and compare it with the
  first `Tree:` line of each report (`grep -m1 'Tree:' <report>`). The working
  tree's hash, written through a temporary index so the real one is untouched
  (`cp -p` keeps the index's mtime, without which git can miss an edit made in
  the same second):
  ```bash
  t=$(mktemp); cp -p "$(git rev-parse --git-path index)" "$t"; GIT_INDEX_FILE=$t git add -A -- . ':(exclude).auto-dev/' && GIT_INDEX_FILE=$t git write-tree; rm -f "$t"
  ```
  A commit's: `git rev-parse <rev>^{tree}`.

## Artifact templates

Skeletons for the artifacts a worker or the orchestrator writes. They fix the
*shape* — the contracts above fix the content. Keep the headings; a later phase reads
them back (Phase 6a builds the PR body straight out of `SPEC_EVAL.md`).

**The templates are files in `templates/`.** Each worker's agent file names the
one it writes, and the worker reads it there by path; `autodev.py
check-artifact` checks the result against it.

**How strict each template is.** Match the output to its consumer:

- **Strict** — ALWAYS use the exact template structure: the same headings in the
  same order, the same header fields, the same table columns. Fill the `<…>`
  placeholders; never rename, merge or drop a heading (beyond an omission the
  template itself allows). A later step reads these back by section or field name.
- **Flexible** — a sensible default. Adapt the sections to the task, using your
  best judgment; only the parts named as fixed must stay.

| Output | Strictness | Read back by |
|--------|------------|--------------|
| `WORK_LOG.md` | strict | the resume procedure and `scripts/resume-point.py` (header lines, phase-table `Status`); every session's entry |
| `HANDOFF.md` | strict | the next session's entry |
| `profile.md` | strict | every phase and worker (`setup`/`gate` commands run verbatim) |
| `SPEC.md` | strict | Define reviewer, acceptance tester, verifier, code reviewers, security-reviewer type choice (`Security/Compliance criteria`), PR body |
| `IMPLEMENTATION.md` | headings strict, content flexible | coder (`Build sequence`), plan reviewer, acceptance tester (entry points only), code reviewers |
| `acceptance/MANIFEST.md` | strict | the orchestrator's check of the tester's return (coverage, levels), verifier (tiers, install), post-plan gate summary, correction briefs (the paths not to touch), PR body (each test's name and its result on the old code) |
| `acceptance/base-run/C<n>.txt` | strict | the orchestrator's check of the tester's return, verifier (Strong tier), PR body (the old code's output) |
| `SPEC_EVAL.md` | strict | `autodev.py eval-status` (the Phase 5 decision), the next verifier re-check, the PR body, PR gate summary, `scripts/check-fresh.py` (`Tree:`) |
| `evidence/corrections.md`, `review/pass-<n>/corrections.md`, `review/security-corrections.md`, `triage/<ci|human>-<n>.md` | strict (`# Required changes`, numbered entries) | the coder, passed unedited as its correction brief; `autodev.py spec-overlap`, which `autodev.py record` runs on it |
| `triage/human-<n>-checks.md` | strict (as above) | the acceptance tester's repair mode: comments saying a held-out check is wrong |
| `fixes/<define|plan>-<n>.md` | strict (FIX blocks) | `autodev.py apply-fix`; the Define agent's or planner's revise mode when a block doesn't apply |
| `review/pass-<n>/R<k>.md` | strict | the review judge |
| `review/pass-<n>/VOTES-R<k>.md` | strict | `autodev.py votes --apply` |
| `CODE_REVIEW.md` | strict | open must-fix → correction loop; PR gate and main gate summaries; PR body `Review`; `scripts/check-fresh.py` (`Tree:`) |
| `SECURITY_REVIEW.md` | strict | the security-verify judge; open must-fix → correction loop; PR gate triage; PR body `Review`; `scripts/check-fresh.py` (`Tree:`) |
| `lint/<CHECK>.md` | strict | PR body `Quality gate`, PR gate summary, `scripts/check-fresh.py` (`Tree:`) |
| PR body | required sections strict, prose flexible | the human reviewer; refreshed after a Phase 6 correction |
| Final report | flexible | the user |

### `HANDOFF.md` (end of S1 and S2, or a context checkpoint; orchestrator)

```markdown
# Handoff — <ticket or task> → <S1 Plan | S2 Build | S3 Ship> (<next session | resume>)

Re-enter with: `cd <absolute worktree path>`
Branch: <prefix>/<slug>   Base: origin/<base>
Iteration budget remaining: <n>/<total>

## Done
- <phase>: <one line, outcome only>

## Next
Phase <n> — <name>. <One or two sentences on the first action.>
Pick up at: <start of Phase <n> | Phase 6, after <last gate passed> — reconcile first>

## Files that matter
- <path> — <why>            # 3–8 entries, no more

## Open assumptions
- <assumption the next session must not silently re-decide>

## Do not
- <anything already settled that a fresh context might redo — e.g. re-run Phase 1,
  re-review the spec, re-resolve the profile>
```

`(next session)` is the planned boundary at the end of S1 or S2. `(resume)` is a
context checkpoint (`SKILL.md`, _Context budget_): the target is the session the
checkpoint fired in, resumed in a fresh context. `Pick up at` tells that session
where in the phase to start. For a phase the ledger marks `in-progress` that is
its start, because an `in-progress` phase re-runs whole (_Resuming an
interrupted run_, step 3). Only Phase 6 resumes inside the phase: name the last
gate passed, and reconcile with git and `gh` before acting (step 4).

Paths absolute; a fresh session does not know where it is. Do not include a
narrative of how the last session went — the ledger has that, and the next
session does not need it.

### `profile.md` (Phase 1, orchestrator)

```markdown
# Project profile

- **Stack:** <stack>
- **Profile:** saved — `<path>` <(not machine-validated: <reason>)> | researched, confirmed by the user, saved to `<path>` | researched, confirmed, not saved — <user chose this run only | save failed: <reason> | no save path: <reason>> | `.auto-dev.yml` (sets setup and gate)
- **Repo:** <repo-name>   **CI:** <github-actions|circleci|gitlab|none>   **CI timeout:** <n> min
- **Base:** <branch>   **Staging:** <branch | n/a — no staging branch>   **Prefix:** <prefix>
- **Iteration budget:** <n> per task
- **Mutation cap:** <n> mutants per verifier pass (default 20) | off (`mutation.max: 0`)
- **Worktree files seeded:** <paths copied from the main checkout | none>
- **Symbol lookup:** `<definition command>` / `<references command>` | `grep -n` — <none in profile | `<tool>` not on PATH>
- **`.auto-dev.yml`:** <validated | not machine-validated: <reason> — checked by hand | none>
- **Post-plan gate:** <on | off> — <which condition enabled it>
- **Security directives:** <resolved paths> | none found — repo coding rules only
- **Jira:** <available, cloudId cached | unavailable — no ticket / MCP unreachable>
  in_progress `<name>` · in_review `<name>` · done `<name>`

## Setup — run in order, verbatim
1. `<command>`

## Quality gate — run in order, verbatim (the Definition of Done)
| # | kind | command | report |
|---|------|---------|--------|
| 1 | compile | `<command>` | `COMPILE.md` |

**Dropped checks:** `<check>` — <tool absent: no dependency declared / no config file>

## Test notes
<required services, monorepo/umbrella scope, slow tiers>

## Assumptions
<anything inferred rather than found, and every profiler question the user answered, with the answer>
```

### `SPEC.md` (Phase 2, Define agent)

Template: `templates/SPEC.md`, which the worker reads by path.

Every condition and criterion carries its Example, Verify by and (conditions)
Edge lines: they are what the acceptance tester turns into checks, so a condition
without them leaves the tester to guess what the spec meant.

### `IMPLEMENTATION.md` (Phase 3, planner)

**Headings strict, content flexible.** Keep every heading below, in this order —
the coder works `Build sequence` top to bottom, and the plan reviewer checks
`Build sequence` and `Test plan` against the spec. What goes under `Design` and
`Data flow` adapts to the task.

Template: `templates/IMPLEMENTATION.md`, which the worker reads by path.

Cite spec conditions **by number only**, never by their wording: the coder reads
this file, and the spec's language stays out of it (*Why two documents*).

### `acceptance/MANIFEST.md` (Phase 3, acceptance tester)

Template: `templates/MANIFEST.md`, which the worker reads by path.

### `SPEC_EVAL.md` (Phase 5, verifier)

Template: `templates/SPEC_EVAL.md`, which the worker reads by path.

The verifier rewrites the whole file on every pass, from scratch and without
reading the previous version: its verdicts must not lean on the last pass's.
The correction history — what each round was dispatched for and what it
bought — lives in `WORK_LOG.md`, which the verifier never reads; the final
report and the stop-and-report's "what was tried" come from there.

### `review/pass-<n>/R<k>.md` (Phase 6a, code reviewer)

Template: `templates/R.md`, which the worker reads by path.

An empty `Findings` section says `none — <what you tried>`. An empty
`Security leads` section says `none`.

### `review/pass-<n>/VOTES-R<k>.md` (Phase 6a, code reviewer re-voting)

Template: `templates/VOTES.md`, which the worker reads by path.

### `CODE_REVIEW.md` (Phase 6a, review judge)

The judge writes it, and the orchestrator updates it after the re-votes (moving
each `Pending re-vote` row to `Must-fix` or `Advisory`, and finalizing the
overall line). It holds every pass, so earlier must-fix findings stay visible as
`fixed`.

Template: `templates/CODE_REVIEW.md`, which the worker reads by path.

An empty section says `none`; an empty table is a section nobody filled, not a
clean one. `Pending re-vote` is empty once the orchestrator has applied the votes.

### `SECURITY_REVIEW.md` (Phase 6a, security reviewer + review judge)

The security reviewer writes it with every `Verified` cell `pending`; the
security-verify judge fills those cells, corrects any origin, and recomputes the
header.

Template: `templates/SECURITY_REVIEW.md`, which the worker reads by path.

### `lint/<CHECK>.md` (Phase 5, cleanup agent) — one per `gate` entry

Template: `templates/lint.md`, which the worker reads by path.

## The PR body

`.auto-dev/` is never committed, so the PR body is the one place this pipeline's
reasoning reaches a human reviewer. The orchestrator assembles it in Phase 6a
from artifacts that are about to become invisible to everyone but itself.

**Who writes it.** The orchestrator, in Phase 6a, whatever route opens the PR —
directly with `gh pr create`, or through a fitting skill from its available-skills
list (`references/phase-6-ship.md`, step 5, has the full requirements). Where the
repo has a PR template, fill it and carry these sections inside it; otherwise use
this shape as-is, attribution line included. Brevity rules may trim the Summary,
but nothing drops the three sections this pipeline writes and refreshes:
**Acceptance conditions** (with its three subsections), **Quality gate** and
**Review**. So: those sections, their headings and the attribution line are
**strict**; the Summary and Assumptions prose is **flexible**.

**Who reads it: a developer who has never heard of auto-dev** and cannot open
`.auto-dev/`. Write every line for that reader:

- **Plain words, no pipeline terms.** No condition or finding numbers (`C2`,
  `M7`, `S1`), no evidence tiers (`Strong`, `Adequate`), and none of "held-out",
  "fail-to-pass", "verifier" or "mutant". The template below says each of them
  in plain words: "the tests written before the code", "small deliberate bugs".
  Explain the method once, in the opening lines the template gives, not per
  condition.
- **No `.auto-dev/` paths.** Nobody else can open them. Quote what the reader
  needs from those files instead.
- **Clean pasted output before it goes in.** The PR may be public. In every
  output block, replace the worktree's absolute path with `.` and a home
  directory with `~`, and drop any line holding a token, password, key,
  connection string or other secret-looking value. When you can't tell whether
  a line is safe, leave the block out and say the output was withheld.
- **Every claim points at something the reader can open:** a test in the diff,
  linked; a commit, linked; or the command and the end of its output, pasted in
  a collapsed `<details>` block.

**Links.** Take the repo's web address from `gh repo view --json url -q .url`
(`<repo-url>`; it is right on GitHub Enterprise too). Link a file at a commit,
by its full sha, never at the branch, which would show whatever the branch holds
later: `<repo-url>/blob/<sha>/<path>#L<line>`, with `<line>` where the test
starts (`grep -n` its name). A line the change removed, or a file it deleted,
exists only in the old code: link it at `<cut>` instead, with its old line
number. Name a commit by its full sha in plain text, not in backticks: GitHub
links it by itself. A refresh re-points every link at `<sha>` to the new
commit; links into the old code stay as they are.

**Why the PR gate uses IDs and the body doesn't.** The PR gate summary is for
the user running auto-dev, who can open the run's files and ask the orchestrator
about `C2` or `M7`; the IDs keep it short and let them point at one item. The PR
body is for everyone else, and an ID there names a file they can't see.

**Where each part comes from.** Read these in S3 to write it:

| Part of the body | Source |
|---|---|
| Each condition, ticked or not | `SPEC.md` (the wording), `SPEC_EVAL.md` (the verdict) |
| The tests written before the code, and each one's result on the old code | `acceptance/MANIFEST.md` (`Check`, `Base run`), `acceptance/base-run/C<n>.txt` (the command and output) |
| What was run, what was expected, what came out | `evidence/C<n>.txt` |
| Checks for a person | `SPEC_EVAL.md`'s `manual` rows and the Edges its _Unresolved_ leaves for a person, `MANIFEST.md`'s _Not automatable_ proxy, `evidence/C<n>.txt` |
| Changes to tests | `SPEC_EVAL.md`, _Test integrity_ |
| Test strength | `SPEC_EVAL.md`, _Mutation_ |
| Quality gate | `lint/*.md` (status, _Output tail (final run)_) |
| Review | `CODE_REVIEW.md`, `SECURITY_REVIEW.md` |

`<cut>` is the commit the change is measured from (`SPEC_EVAL.md`'s header names
it), `<old sha>` the commit the tests written before the code ran on
(`MANIFEST.md`'s header names it, and a base-run file's `Commit` line gives it
in full; after a base merge it is older than `<cut>`),
`<sha>` the commit the body describes. An evidence file written before 3.8
may hold no `Output` part: leave that condition's output block out rather than
inventing one; its test link still lets the reader check. Tests written before
3.9 have no `base-run/` files: leave the old-code block out. A corrected
test's lines there show it before it was corrected: leave those lines out,
and the block too if nothing else is left.

Template: `templates/pr-body.md`, which the worker reads by path.

**One box per condition.** Every `SPEC.md` condition, security/compliance
criteria included, appears exactly once: ticked under _Acceptance conditions_
when `SPEC_EVAL.md` says `met`, unticked there when `partial` or `unmet`, and
unticked under _Checks for a person_ when `manual`. The one exception: a met
condition whose Edge `SPEC_EVAL.md` leaves for a person is ticked under
_Acceptance conditions_ and also has a box for that Edge alone under _Checks
for a person_, worded as the Edge. A condition checked by more
than one test written before the code gets one test line each and one output
block, from the run of all of them. "Start review with" lists each file those
tests are in once, corrected ones included.

**Counting the deliberate bugs.** "We put <n>" counts every bug that ran
(`SPEC_EVAL.md`'s killed, timed-out and survived counts, not the invalid ones);
"they caught" counts the killed and timed-out ones. A bug that made the tests
hang was noticed.

**Filled in.** An example in TypeScript, for one met condition and one test
change (an assertion the change removed, so it links to the old code). Its
output blocks hold only the lines of each run that name this test:

````markdown
- [x] **A user cannot delete another user's todo**
  Test written before the code: [`src/todos/todo-delete.acceptance.test.ts` › deleting another user's todo returns not found](https://github.com/acme/todos/blob/3f9c2ab41e07d8c5b6a9f0e2d4c1b7a8e6f5d3c2/src/todos/todo-delete.acceptance.test.ts#L24) —
  old code: failed: expected 404, got 200 · now: passes
  <details><summary>Command and output</summary>

  On the old code, ran `npx vitest run src/todos/todo-delete.acceptance.test.ts`:
  ```
   × src/todos/todo-delete.acceptance.test.ts > deleting another user's todo returns not found 9ms
     → expected 404 "Not Found", got 200 "OK"
  ```
  Now, ran `npx vitest run src/todos/*.acceptance.test.ts`, expecting this test to pass.
  ```
   ✓ src/todos/todo-delete.acceptance.test.ts > deleting another user's todo returns not found 12ms
  ```
  </details>

### Changes to tests
- [`src/todos/todos.test.ts`](https://github.com/acme/todos/blob/9b1e4d7c2a6f8e3b5d0c7a9f1e2b4d6c8a0f3e5b/src/todos/todos.test.ts#L42): the assertion that deleting any todo returns 200 was replaced by one that expects 404 for someone else's todo — because a user can no longer delete another user's todo
````

**Size.** GitHub refuses a body or a comment over 65,536 characters; keep each
under 60,000, measured with `wc -m` before publishing. Over that: cut each
output block to its last 10 lines. Still over: move every `<details>` block into
one PR comment whose first line is `Command output for commit <short sha>`,
posted right after the PR opens or the body is refreshed, and leave `(output in
the comment "Command output for commit <short sha>")` in each block's place. If
the comment would still be over, cut its blocks to their last 3 lines. This
comment is part of the body, not a review finding, so the rule that findings
stay on disk does not apply to it. Note its id (the number at the end of the
URL `gh pr comment` prints) in the Phase 6 row's Notes in `WORK_LOG.md`. A
refresh, or a resume that finds no id noted, first looks for that comment
(`gh pr view <pr> --json comments`: a body starting `Command output for
commit`, its id at the end of its `url`) and edits it
(`gh api -X PATCH repos/{owner}/{repo}/issues/comments/<id> -F body=@<file>`;
`gh` fills in `{owner}/{repo}`) rather than posting another. When a refreshed
body fits with its blocks inline, edit that comment to one line instead:
`Superseded: the description holds the output for commit <short sha>.` A body
still over 60,000 with every block moved out is not published cut short: report
it at the gate, or in the final report after the PR gate.

**The body describes one commit, and says which.** Its `Checked at commit` line
names the commit whose code the results checked, and the body is written or
refreshed only once `scripts/check-fresh.py <worktree> <artifact-dir> --ref <that
commit>` exits `0` (_Stamps_, above). A stale result is re-run first, never
published; a body that names an older commit than the PR carries is out of date.

**Ship the unticked box rather than a tidy list.** A condition surfaced as unmet
is a decision the reviewer gets to make; a condition quietly dropped from the
list is the one failure of this pipeline nobody can catch downstream. If a
Phase 6 correction lands, every section this pipeline writes is part of what it
invalidates (`references/correction-loop.md`). Refresh them on the open PR with
`gh pr edit <pr> --body-file <file>`, since the PR already exists by then and
re-running PR creation would open a second one. Replace those sections whole,
from the template, in the live body, and keep the rest, so edits made on GitHub
survive. One thing inside them survives too: a _Checks for a person_ box someone
ticked on GitHub stays ticked while its condition and steps are unchanged. A body written before 3.8 has the older shape inside those sections
(tier names, `Needs a human check:` items, a `Mutation:` line): the same
replacement rewrites them, subsections included.

## The final report

**Flexible — a sensible default; adapt it as needed.** It is for the user, and
nothing reads it back. Every item `SKILL.md`, _Final report_, lists must appear;
the order, wording and grouping are yours. A run ended early (a `Stop` at a gate,
a stop-and-report condition) uses the same shape and says where it stopped.

```markdown
## auto-dev — <task or ticket> — <shipped | stopped at <phase>: <reason>>

- **PR:** <url> (<merged | open | draft>)   **Branch:** <prefix/slug>   **Worktree:** <abs-path>
- **Built:** <what changed, 1–3 sentences>
- **Quality gate:** <each check and its final status>
- **Checked at:** <the verified commit, from WORK_LOG.md: every result here was produced on it>
- **Review:** code <confidence>, <n> must-fix fixed, <n> open · security <confidence>, <n> must-fix fixed, <n> open, <n> pre-existing for the user
- **Jira:** <transitions performed | none — no ticket>
- **Iteration budget:** <remaining>/<total>

**Assumptions:** <the ones a reviewer should know about>

**Unresolved / skipped:** <unmet conditions, open must-fix findings, skipped steps — or "none">

**Follow-ups:** <pre-existing security findings the user sent to a separate PR — or "none">
```
