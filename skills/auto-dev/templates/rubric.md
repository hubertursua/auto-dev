<!-- auto-dev: the review rubric, read by the code reviewers, the review judge and the security reviewer. -->
# The review rubric

### Code review findings

**Category.** Only two categories can ever be must-fix:

- **Correctness:** wrong output, a crash, data loss, a race, or a broken edge
  case or error path.
- **Tests:** a changed behavior with no test, a test that cannot fail, or a test
  that misses the case the change is about.

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
and the input no test exercises. "This could fail" with no path is **noise**.
The judge confirms each path by reading the code itself. A path the judge cannot
confirm makes the finding noise, however many reviewers raised it.

**Votes.** A vote is a reviewer who raised the finding on their own (the judge
merges findings with the same root cause at the same place), or a re-vote of
`agree`.

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
| Pre-existing | High or Medium, confirmed by the judge | **for the user:** shown at the PR gate. It never blocks on its own |
| Pre-existing | Low | **advisory**, listed in the report only |

A High or Medium finding the judge refutes becomes **advisory**, with the reason
recorded.

### Overall report confidence

Each report's header carries one overall line. It tells the user how much the
report's silence is worth.

| Report | High | Medium | Low |
|---|---|---|---|
| **Code review** | All 3 reviewers finished, the scope was fully covered, and no must-fix finding was decided 2 votes to 1 | One reviewer failed and the panel rests on 2; or some files were only partly covered; or a must-fix finding was decided 2 votes to 1 | Fewer than 2 reviewers finished |
| **Security review** | The reviewer finished, the whole change was covered, and every High or Medium finding was verified | Some files were only partly covered, or a verification could not run | The reviewer could not finish |

A **Low** overall confidence is a warning at the PR gate, never a clean pass.
The summary says what failed.
