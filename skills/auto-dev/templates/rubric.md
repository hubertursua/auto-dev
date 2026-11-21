<!-- auto-dev: the review rubric, read by the code reviewers, the reviewer, the review judge and the security reviewers. -->
# The review rubric

### Before you report a finding

A short list of real defects is worth more than a long list of guesses. Each
finding that doesn't hold costs a judge's trace or a correction round, and
most findings that don't hold are claims about code the reviewer never read.
Zero findings is a correct result for a clean change, once you have tried to
break it.

**Read before you judge.** Read each changed file in full as the scope has it,
not only its hunks, and the binding rules (the repo's CLAUDE.md or AGENTS.md,
CONTRIBUTING and coding-guideline docs, and the security directives
`profile.md` names). Read
the docs, comments and PLAN.md text the change touches: behavior they describe
as intended is not a defect. A comment this change adds is the exception: it is
the author's claim, to check like the code. Behavior PLAN.md asks for that you
think is wrong is a spec problem, not a finding.

**Verify every finding.** Before you report a finding, and before you confirm
one as judge:

1. **Read what the claim depends on.** Every function, method or command it
   relies on: its definition, every branch, and its declared types or
   signature. Never guess a return value, an error it raises, a default or a
   retry: read it.
2. **Find the layer that may already handle it.** Input validation, the
   framework's or a middleware's guards, the type system, a schema or database
   constraint, an early return, the callers. Grep for every caller. For a
   tests finding, this layer is the test suite: search it for the case
   (another test file, a parameterized or table-driven case, an acceptance
   check) before you call the case untested.
3. **Ask the repo, not your memory.** Check what the repo can answer: the code
   itself (an option is often set where the code builds the object, not in a
   config file), `git log`, the source of a dependency the repo vendors or has
   installed, and schema or interface definitions. Never assume how a library
   or service behaves when the repo shows it.
4. **Name a path that real use takes.** The trigger path starts where normal
   use starts: a real caller, a request, the command as users run it, a file
   the code really reads. A finding that only old data, a hand edit or an
   impossible state can reach is not a finding: leave it out (as judge,
   `Holds: no`).
5. **Try to prove it wrong.** If you can, or if you still aren't sure, leave
   it out (as judge, `Holds: no`). A security finding is the one exception:
   one you can't prove wrong but can't trace either is Low (_Security
   findings_, below), listed as advisory rather than left out.

A finding's `path:line` is a line that exists in the file as the scope has it:
open the file to confirm it. A performance finding shows its cost from the code
(a query inside a loop over every row, a whole file read for each item); "may
be slow" or "profile it to be sure" is not a finding.

**A required change you checked.** Whoever writes a finding's `Required change`
(the judge, a security reviewer, or the reviewer that judges its own findings)
checks it as they check the finding. Every name it uses (a function, file, option, key or
command) must exist: grep for it. It must not add a failure the code doesn't
have now: a new error raised, a case left unhandled, a crash on input the code
handles today. When you can't check a fix, say what must hold and where,
without code.

### Code review findings

**Category.** Only three categories can ever be must-fix:

- **Correctness:** wrong output, a crash, data loss, a race, or a broken edge
  case or error path.
- **Tests:** a changed behavior with no test, a test that cannot fail, or a test
  that misses the case the change is about.
- **Acceptance check** (`acceptance-check`): an acceptance check asserts
  the wrong thing, or can't fail when its condition is unmet. It goes to the
  acceptance tester's repair mode, never the coder.

**A test gap is the whole class.** A tests finding is about one changed
behavior, and it lists every case of that behavior no test exercises, not just
the first one found: each configuration value or option the behavior reads
that no test varies, each boundary, each error path and the message it
produces, and each value the plan says must fail closed. For a payout cap, say:
a cap above the default, the refusal message under that cap, and each missing
value the plan says must be refused, not one of them per finding. Only cases a
real caller can reach count (the trigger path rule, below), and the list holds
the separate cases, not their combinations. The judge merges tests findings
about the same changed behavior into one, and its `Test:` and
`Required change:` lines ask for a test of every case on the list, so one
correction closes the gap. A tests finding is `fixed` only when every case it
lists has a test.

A finding that breaks a binding rule (the repo's CLAUDE.md or AGENTS.md,
CONTRIBUTING and coding-guideline docs, and the security directives
`profile.md` names) is **correctness**, not conventions, so it can be
must-fix: cite the rule (file and line) and the code that breaks it
(`file:line`).

Scope, performance, design, conventions and style findings are **advisory**,
whatever their severity. Security findings are not the panel's job: they go to
`Security leads` for Step 2.

**Origin.** A finding counts only if this change introduced it: it sits in lines
the change adds or modifies, or the change causes it (for example, a new caller
that breaks an old function's assumption). A pre-existing problem that is not a
security issue is **dropped**. Count it in the report, but list it nowhere and
fix nothing.

**Evidence: a trigger path.** A must-fix finding names a specific input or
sequence, starting from a real caller or entry point (`file:line`), that leads
to the failure. For a test finding, it names the changed behavior (`file:line`)
and each input no test exercises. "This could fail" with no path is **noise**.
The judge confirms each path by reading the code itself. A path the judge cannot
confirm makes the finding noise, however many reviewers raised it.

**Votes.** A vote is a reviewer who raised the finding on their own (the judge
merges findings with the same root cause at the same place, and tests findings
about the same changed behavior), or a re-vote of `agree`. A merged tests
finding's votes are the reviewers who raised any of its cases: what they
corroborate is the gap in that behavior, and the judge's own trace of each case
stands in for a vote per case. The judge drops a case it cannot confirm, and
adds a reachable case it finds while tracing. A re-voter agrees with a tests
finding when the behavior has a real gap, and names in its reason any listed
case that does not hold.

**Verdict and confidence:**

| Verdict | Confidence | Rule |
|---|---|---|
| **must-fix** | **High** | All 3 reviewers raised it independently, and the judge confirmed the trigger path |
| **must-fix** | **Medium** | 2 of 3 raised it, independently or after a re-vote, and the judge confirmed the trigger path |
| **advisory** | **Low** | Only 1 of 3 after the re-vote, or an advisory category |
| **noise** | — | The judge refuted it: the path does not hold, the code already handles it, or the reviewer misread the code. The reason is recorded |
| **dropped** | — | Pre-existing and not a security issue. Counted only |

If only 2 reviewers finished, a lone finding is re-voted by the one other
reviewer, and must-fix still needs 2 votes.

### Security findings

| Origin | Confidence | Verdict |
|---|---|---|
| Introduced by this change | **High:** a clear path from untrusted input (a request, a file, a message, anything an outside party controls) to the exploit | **must-fix**, once the judge confirms it |
| Introduced by this change | **Medium:** the path exists but depends on a configuration or an assumption, which the finding names | **must-fix**, once the judge confirms it |
| Introduced by this change | **Low:** speculative, with no traced path | **advisory** |
| Pre-existing | High or Medium, confirmed by the judge | **for the user:** shown at the ready-for-review gate. It never blocks on its own |
| Pre-existing | Low | **advisory**, listed in the report only |

A High or Medium finding the judge refutes becomes **advisory**, with the reason
recorded.

### Overall report confidence

Each report's header carries one overall line. It tells the user how much the
report's silence is worth.

| Report | High | Medium | Low |
|---|---|---|---|
| **Code review** | All 3 reviewers finished, the scope was fully covered, and no must-fix finding was decided 2 votes to 1 | One reviewer failed and the panel rests on 2; or some files were only partly covered; or a must-fix finding was decided 2 votes to 1 | Fewer than 2 reviewers finished |
| **Security review** | The reviewer finished, the whole change was covered (a correction's focused re-check counts when earlier runs covered the rest), and every High or Medium finding was verified | Some files were only partly covered, or a verification could not run | The reviewer could not finish |

A **Low** overall confidence is a warning at the ready-for-review gate, never a clean pass.
The summary says what failed.
