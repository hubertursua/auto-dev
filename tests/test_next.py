"""Tests for autodev.py next and pr publish: a run driven by simulated workers.

Run: python3 -m unittest discover -s tests -v   (from the repo root)

Each test plays the orchestrator: it runs `next`, does what it says (writing
the worker's result file and artifacts instead of spawning an agent), runs the
AFTER command, and runs `next` again. GitHub is tests/fake_gh/gh. Examples are
in TypeScript, as CLAUDE.md asks.
"""

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from importlib import import_module
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_autodev import AUTODEV, GH_OK, SCRIPTS, RunCase
from test_parsers import BASE_RUNS, CODE_REVIEW, MANIFEST, PLAN, SECURITY_REVIEW, SPEC_EVAL

# The planner's answer for the fixture PLAN.md, which says FITS and high risk.
PLANNED = {"risk": "high", "reading": "none", "entry_points_changed": "no"}
APPROVE = ("# Plan review — review\n\nVerdict: APPROVE\nRisk: {risk} — right\n\n"
           "## Blockers\nnone\n\n## Notes\nnone\n")


def plan_review(verdict="APPROVE", risk="high", blockers=1, kind="review"):
    """A plan critic's review file."""
    if verdict == "APPROVE":
        return APPROVE.format(risk=risk).replace("— review", f"— {kind}")
    rows = "".join(f"### B{i}. the plan misses case {i}\n- Evidence: `src/due.ts:{i}`\n"
                   f"- Change: add a step for case {i}\n\n" for i in range(1, blockers + 1))
    return (f"# Plan review — {kind}\n\nVerdict: REVISE\nRisk: {risk} — right\n\n"
            f"## Blockers\n{rows}## Notes\nnone\n")
CLEAN_REVIEW = CODE_REVIEW.split("## Must-fix")[0].replace(
    "provisional (re-votes pending)", "High").replace("1 open", "0 open") + """\
## Must-fix
| ID | Finding | Location | Category | Votes | Confidence | Status |
|----|---------|----------|----------|-------|------------|--------|

## Pending re-vote
| ID | Finding | Location | Category | Raised by | Re-voters | Votes |
|----|---------|----------|----------|-----------|-----------|-------|

## Advisory
| ID | Finding | Location | Category | Votes | Confidence | Why advisory |
|----|---------|----------|----------|-------|------------|--------------|

## Noise
none

## Security leads
none

## Passes
| Pass | Scope | Reviewers finished | Must-fix found | Re-votes |
|------|-------|--------------------|----------------|----------|
| 1 | whole change | 3/3 | 0 | 0 |
"""
OPEN_REVIEW = CLEAN_REVIEW.replace("0 open", "1 open").replace(
    "|----|---------|----------|----------|-------|------------|--------|\n",
    "|----|---------|----------|----------|-------|------------|--------|\n"
    "| C1 | null due date crashes sort | `src/sort.ts:4` | correctness | 3/3 | High | open |\n",
    1)
CHECK_REVIEW = OPEN_REVIEW.replace(
    "| C1 | null due date crashes sort | `src/sort.ts:4` | correctness |",
    "| C1 | the due-date check passes on the old code | `src/due.acceptance.test.ts:3` | "
    "acceptance-check |")
SECURITY_MUST_FIX = SECURITY_REVIEW.replace(
    "| S2 | session token not rotated |",
    "| S3 | any user can set another user's due date | `src/due.ts:9` | introduced | High "
    "| confirmed | must-fix | open |\n| S2 | session token not rotated |")

# The keys a worker's result block holds that most tests leave at their
# default: a count of nothing found.
DEFAULT_KEYS = {"coder": {"deviations": "0"}, "verifier": {"spec_problems": "0"},
                "reviewer": {"spec_problems": "0"},
                "review-judge": {"spec_problems": "0"},
                "security-reviewer": {"spec_problems": "0"},
                "security-reviewer-sensitive": {"spec_problems": "0"},
                "triager": {"spec_problems": "0"}}


def r_report(findings):
    """A code reviewer's report, with the sections its template requires. A
    finding given as a title alone is written in the template's shape."""
    if findings != "none" and not findings.startswith("1. "):
        findings = (f"1. **{findings.lstrip('- ')}** — `src/sort.ts:4` — correctness\n"
                    "   Trigger path: sorting a todo with no due date\n"
                    "   Why it is wrong: it throws")
    return (f"## Findings\n{findings}\n\n## Security leads\nnone\n\n"
            "## Pre-existing\nnone\n")


class NextCase(RunCase):
    def setUp(self):
        super().setUp()
        self.assertEqual(self.init().returncode, 0)
        acc = self.dir / "acceptance"
        for rel, text in (("PLAN.md", PLAN), ("acceptance/MANIFEST.md", MANIFEST)):
            (self.dir / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.dir / rel).write_text(text)
        (acc / "base-run").mkdir(parents=True, exist_ok=True)
        for name, text in BASE_RUNS.items():
            (acc / "base-run" / name).write_text(text)

    # -------------------------------------------------------------- driving

    def next(self, expect=None, refused_ok=False, reissue=False):
        r = self.autodev("next", *(["--reissue"] if reissue else []), "--dir", self.dir,
                         "--json")
        try:
            out = json.loads(r.stdout)
        except ValueError:
            self.fail(f"next printed no JSON (exit {r.returncode}):\n{r.stdout}{r.stderr}")
        if expect is not None:
            self.assertEqual(out.get("exit"), expect, json.dumps(out, indent=2))
        if not refused_ok:  # `answer` no longer runs `record`: a refusal would hide here
            self.assertFalse([ln for ln in out.get("RECORDED", []) if "refused" in ln],
                             json.dumps(out, indent=2))
        return out

    def raise_from_report(self, out, n):
        """Run the `budget raise` command a budget stop's report names, for n rounds."""
        line = next(ln for ln in out["REPORT"] if "budget raise" in ln)
        command = re.search(r"`([^`]*budget raise[^`]*)`", line).group(1)
        r = subprocess.run(command.replace("'<n>'", str(n)), shell=True,
                           capture_output=True, text=True, env=self.env, cwd=self.tmp,
                           check=False)
        self.assertEqual(r.returncode, 0, command + "\n" + r.stdout + r.stderr)
        self.assertIn("RAISED", r.stdout)

    def sign_off(self, out, text="the user keeps it as written"):
        """At a stop `out` that offers it, sign off with `text`."""
        self.assertIn("Sign off and go on", out.get("QUESTION", ""), json.dumps(out, indent=2))
        r = self.autodev("override", "signoff", "--text", text, "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def spawned(self, out):
        """[(worker, n)] the action asks to spawn."""
        return [(Path(b).stem.rsplit("-", 1)[0], int(Path(b).stem.rsplit("-", 1)[1]))
                for b in out.get("BRIEF", [])]

    def sets(self, worker, n):
        return next(b for b in self.state()["briefs"]
                    if b["worker"] == worker and b["n"] == n)["sets"]

    REPAIR_LINE = "// repaired by the acceptance tester"
    CHECKS = ("src/due.acceptance.test.ts", "src/sort.acceptance.test.ts")

    def answer(self, worker, n, nxt, status="ok", **data):
        data = {**DEFAULT_KEYS.get(worker, {}), **data}
        if worker == "acceptance-tester" and nxt == "WRITTEN":
            # The tester leaves its checks in the worktree; `next` commits them.
            for path in self.CHECKS:
                check = self.worktree / path
                if not check.exists():
                    check.parent.mkdir(parents=True, exist_ok=True)
                    check.write_text("test")
        if worker == "review-judge" and nxt != "VERIFIED" and status == "ok":
            # The simulated judge's calls; the test writes CODE_REVIEW.md itself.
            judged = (self.dir / "review" /
                      f"pass-{self.state()['phase6'].get('review_pass') or 1}" / "JUDGMENT.md")
            judged.parent.mkdir(parents=True, exist_ok=True)
            judged.write_text("# Judgment\n")
        path = self.dir / "returns" / f"{worker}-{n}.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps({"worker": worker, "status": status, "next": nxt,
                                    **data}))
        # No `record` call: the next `next` records it, as in a run.

    def expect(self, worker, nxt=None, **data):
        """Run next, check it spawns `worker`, answer with `nxt` (if given)."""
        out = self.next(0)
        jobs = self.spawned(out)
        self.assertEqual([w for w, _ in jobs], [worker] * len(jobs), json.dumps(out))
        self.assertTrue(jobs, json.dumps(out, indent=2))
        if nxt is not None:
            for w, n in jobs:
                self.answer(w, n, nxt, **data)
        return out, jobs

    def after(self, out, choice=None):
        """Run the AFTER command (for a question, the one for `choice`)."""
        lines = out["AFTER"]
        if choice is not None:
            lines = [ln.split(" → ", 1)[1] for ln in lines if ln.startswith(f'"{choice}"')]
        for line in lines:
            r = subprocess.run(line, shell=True, capture_output=True, text=True,
                               env=self.env, cwd=self.tmp, check=False)
            self.assertEqual(r.returncode, 0, line + "\n" + r.stdout + r.stderr)

    def tree(self):
        return subprocess.run([sys.executable, str(SCRIPTS / "check-fresh.py"),
                               "--print-tree", self.worktree], capture_output=True,
                              text=True, check=True).stdout.strip()

    def spec_eval(self, v1="met", defective="None."):
        (self.dir / "SPEC_EVAL.md").write_text(SPEC_EVAL.format(
            tree=self.tree(), v1=v1, v2="met", e2="ran the sort", judgment="Justified",
            defective=defective))

    lint_tail = "all good"
    plan_text = PLAN

    def lint(self, status="pass"):
        (self.dir / "lint").mkdir(exist_ok=True)
        (self.dir / "lint" / "TEST.md").write_text(
            f"# TEST — {status}\n\n- **Command:** `true`\n- **Tree:** {self.tree()}\n\n"
            f"## Output tail (final run)\n```\n{self.lint_tail}\n```\n")

    def resume(self):
        r = self.autodev("resume", "--repo", self.repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("RESUME", r.stdout)

    # -------------------------------------------------------------- whole sessions

    def critic(self, verdict="APPROVE", risk="high", blockers=1, mode="review"):
        """Expect the plan critic in `mode`; write its review file and answer."""
        out, jobs = self.expect("plan-critic")
        (w, n), = jobs
        self.assertEqual(self.mode(w, n), mode)
        path = self.dir / "plan-review" / f"{n}.md"
        path.parent.mkdir(exist_ok=True)
        path.write_text(plan_review(verdict, risk, blockers, mode))
        self.answer(w, n, verdict, risk=risk,
                    blockers=str(blockers if verdict == "REVISE" else 0))
        return out, jobs

    def planned(self, gate=True):
        """Phase 2 on the happy path: the planner writes PLAN.md (the fixture),
        the critic approves it, and (with `gate`) the user approves it at the
        post-plan gate, which the fixture's high risk turns on."""
        (self.dir / "PLAN.md").write_text(self.plan_text)
        self.expect("planner", "FITS", **PLANNED)
        self.critic()
        if gate:
            out = self.next(5)
            self.assertIn("post-plan gate", out["QUESTION"])
            self.after(out, "Approve & build")

    def plan_session(self):
        self.planned()  # HIGH_RISK turns the post-plan gate on, before the tester
        self.expect("acceptance-tester", "WRITTEN", checks="4", ambiguous="none")
        self.enter_stage("build")  # the same session goes on

    def enter_stage(self, stage):
        """`next` moves the run on to `stage` in the same session: the
        orchestrator reads its runbook, then runs `next`."""
        out = self.next(0)
        self.assertIn(f"read references/{stage}.md", out["ACTION"], json.dumps(out))
        self.assertEqual(self.state()["stage"], stage)
        # AFTER is `next` itself: the caller runs it and acts on what it prints
        # (run here, the spawn it printed would be lost, and then waited for).
        self.assertEqual(out["AFTER"], [self.next_cmd()])

    def build_session(self):
        self.expect("coder", "BUILT", blocked="0", test_changes="none")
        (self.worktree / "due.ts").write_text("export const due = 1;\n")
        self.quality_gate()
        self.enter_stage("ship")

    def quality_gate(self, red=False):
        """`next` asks for the quality gate (a script, no worker): run it, with
        the profile's check failing when `red`."""
        out = self.next(0)
        self.assertIn("quality-gate", out["ACTION"], json.dumps(out, indent=2))
        if red:
            state = self.state()
            state["settings"]["gate"][0]["command"] = "false"
            self.write_state(state)
        r = self.autodev("quality-gate", "--dir", self.dir)
        self.assertEqual(r.returncode, 1 if red else 0, r.stdout + r.stderr)
        if red:  # the profile's command back, and the run counted as its run
            state = self.state()
            state["settings"]["gate"][0]["command"] = "true"
            sys.path.insert(0, str(SCRIPTS))
            state["gate_runs"][-1]["gate"] = import_module("lib.cmd_gate").gate_key(state)
            self.write_state(state)
        self.assertEqual(out["AFTER"], [self.next_cmd()])  # AFTER is `next` itself
        return out

    def next_cmd(self):
        return " ".join(shlex.quote(str(w)) for w in (
            "python3", SCRIPTS / "autodev.py", "next", "--dir", self.dir))

    def verifier_first(self, nxt="ALL_MET"):
        """A high-risk pass starts with the verifier alone: answer it `nxt`."""
        out = self.next(0)
        jobs = self.spawned(out)
        self.assertEqual([w for w, _ in jobs], ["verifier"], json.dumps(out, indent=2))
        self.verifier_answer(jobs[0], nxt)
        return jobs[0]

    def verifier_answer(self, job, nxt="ALL_MET", **kw):
        """Answer the pass's verifier: SPEC_EVAL.md on the tree as it is."""
        if nxt == "CORRECT" and not kw:
            kw = {"v1": "unmet"}
        if nxt != "MUTATION_LEFT_CHANGES":
            self.spec_eval(**kw)
        data = {"tree": "x", "corrections": "0"}
        if nxt == "CORRECT":
            (self.dir / "evidence").mkdir(exist_ok=True)
            (self.dir / "evidence" / "corrections.md").write_text(
                "# Required changes\n1. C1: make the sort stable\n")
            data["corrections"] = "1"
        self.answer(*job, nxt, **data)

    def reviewers(self, security=None, count=3, problems=None, verifier="ALL_MET"):
        """A high-risk pass: the verifier first (its mutants are planted in the
        tree), answered `verifier`; then the panel (`count` code reviewers) and
        the security reviewer, spawned in one message. Answer the security
        reviewer with `security` (text, next, must_fix, pre_existing; clean by
        default), reporting `problems` (a spec-problems file's text) when
        given, and return the panel's jobs. With `count` 0 (a security run on
        leads), no verifier runs."""
        out = self.next(0)
        jobs = self.spawned(out)
        self.verifier_job = None
        if count:
            self.assertEqual([w for w, _ in jobs], ["verifier"], json.dumps(out))
            self.verifier_job = jobs[0]
            self.verifier_answer(jobs[0], verifier)
            if verifier == "MUTATION_LEFT_CHANGES":
                return out, []
            out = self.next(0)
            jobs = self.spawned(out)
        sec = [j for j in jobs if j[0].startswith("security-reviewer")]
        panel = [j for j in jobs if j[0] == "code-reviewer"]
        self.assertEqual((len(panel), len(sec), len(jobs)), (count, 1, count + 1),
                         json.dumps(out))
        self.security_job = sec[0]
        text, nxt, must_fix, pre = security or (SECURITY_REVIEW, "CLEAN", "0", "0")
        (self.dir / "SECURITY_REVIEW.md").write_text(text.format(tree=self.tree()))
        extra = {}
        if problems is not None:
            path = self.dir / "spec-problems" / f"{sec[0][0]}-{sec[0][1]}.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(problems)
            extra["spec_problems"] = str(sum(1 for ln in problems.splitlines()
                                             if ln.startswith("- ")))
        self.answer(*sec[0], nxt, must_fix=must_fix, pre_existing=pre, **extra)
        return out, panel

    def mode(self, worker, n):
        return next(b for b in self.state()["briefs"]
                    if b["worker"] == worker and b["n"] == n).get("mode")

    def panel(self, review=None, judged="CLEAN", corrections=None, security=None,
              count=3, verifier="ALL_MET"):
        """The verifier (answered `verifier`), the three reviewers and the
        security reviewer, then the judge, who writes `review`. Returns the
        judge's security-verify job, if spawned."""
        _, jobs = self.reviewers(security, count, verifier=verifier)
        pass_dir = self.dir / "review" / f"pass-{self.state()['phase6']['review_pass']}"
        for w, n in jobs:
            slot = self.sets(w, n)["reviewer"]
            (pass_dir / f"{slot}.md").write_text(r_report("none"))
            self.answer(w, n, "REVIEWED", findings="0", leads="0")
        review = review or getattr(self, "review_text", CLEAN_REVIEW)
        (self.dir / "CODE_REVIEW.md").write_text(review.format(tree=self.tree()))
        if corrections is not None:
            (pass_dir / "corrections.md").write_text(corrections)
        is_open = judged == "MUST_FIX"
        _, jobs = self.expect("review-judge")
        consolidate = [j for j in jobs if self.mode(*j) == "consolidate"]
        self.assertEqual(len(consolidate), 1, jobs)
        self.answer(*consolidate[0], judged, must_fix_open=str(int(is_open)), revote="0")
        return [j for j in jobs if j not in consolidate]

    def review_clean(self, count=3):
        self.assertEqual(self.panel(count=count), [])

    def write_return(self, worker, n, data):
        (self.dir / "returns" / f"{worker}-{n}.json").write_text(json.dumps(
            {"worker": worker, "status": "ok", **DEFAULT_KEYS.get(worker, {}),
             **data}))

    def next_reissue(self, expect=None):
        """`next --reissue`: every agent the last wait named has returned."""
        r = self.autodev("next", "--reissue", "--dir", self.dir, "--json")
        try:
            out = json.loads(r.stdout)
        except ValueError:
            self.fail(f"next --reissue printed no JSON (exit {r.returncode}):\n"
                      f"{r.stdout}{r.stderr}")
        if expect is not None:
            self.assertEqual(out.get("exit"), expect, json.dumps(out, indent=2))
        return out

    def assert_waits_for(self, out, *names):
        """`out` tells the orchestrator to wait for each of `names` (`planner #1`)
        and spawns nothing."""
        shown = json.dumps(out, indent=2)
        self.assertEqual(out.get("exit"), 0, shown)
        self.assertTrue(out.get("ACTION", "").startswith("wait"), shown)
        for name in names:
            self.assertIn(name, out["ACTION"], shown)
        self.assertNotIn("AGENT", out, shown)
        self.assertNotIn("BRIEF", out, shown)

    def assert_spawns_planner_1_again(self, out):
        shown = json.dumps(out, indent=2)
        self.assertEqual(out.get("exit"), 0, shown)
        self.assertEqual(out.get("AGENT"), ["auto-dev:planner"], shown)
        self.assertEqual(self.spawned(out), [("planner", 1)], shown)
        self.assertFalse((self.dir / "briefs" / "planner-2.md").exists())

    def brief_files(self):
        return sorted(p.name for p in (self.dir / "briefs").iterdir())

    def stopped_after_three_spawns(self):
        """planner #1 spawned, then `next --reissue` three times: the third stops."""
        self.expect("planner")
        for _ in range(2):
            self.assertEqual(self.spawned(self.next_reissue(0)), [("planner", 1)])
        out = self.next_reissue(4)
        self.assertIn("spawned 3 times", " ".join(out["REPORT"]))
        return out

    def sent_out_ago(self, worker, n, **ago):
        """Make `worker` #`n`'s brief look as if it was last sent out `ago` back."""
        when = (datetime.now(timezone.utc) - timedelta(**ago)).replace(microsecond=0)
        state = self.state()
        brief = next(b for b in state["briefs"] if (b["worker"], b["n"]) == (worker, n))
        brief["at"] = when.isoformat()
        if "issued_at" in brief:
            brief["issued_at"] = when.isoformat()
        self.write_state(state)


OVERSIZED_PLAN = PLAN.split("## Size check")[0] + (
    "## Size check\nOVERSIZED: three deliverables.\n"
    "- Subsystems: lists (~6 files), invites (~8 files)\n"
    "- Split: ship shared lists first, then invites\n")


class PlanTest(NextCase):
    def test_the_checks_are_committed_after_the_tester_before_the_build(self):
        self.planned()
        head = self.sh("git", "rev-parse", "HEAD", cwd=self.worktree).strip()
        _, jobs = self.expect("acceptance-tester", "WRITTEN", checks="4", ambiguous="none")
        r = self.autodev("record", *map(str, jobs[0]), "--dir", self.dir)  # as `next` would
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        out = self.autodev("next", "--explain", "--dir", self.dir)
        self.assertIn("commit the acceptance checks as their own commit", out.stdout)
        self.assertEqual(self.sh("git", "rev-parse", "HEAD", cwd=self.worktree).strip(),
                         head)  # --explain commits nothing
        self.enter_stage("build")  # the gate came before the tester
        commits = self.state()["tests_commits"]
        self.assertEqual(len(commits), 1)
        self.assertEqual(self.sh("git", "rev-parse", "HEAD", cwd=self.worktree).strip(),
                         commits[0]["sha"])
        shown = self.sh("git", "show", "--name-only", "--format=%s", "HEAD",
                        cwd=self.worktree).split("\n")
        self.assertTrue(shown[0].startswith("test: acceptance checks for Add due dates"))
        self.assertEqual(sorted(x for x in shown[1:] if x),
                         ["src/due.acceptance.test.ts", "src/sort.acceptance.test.ts"])
        self.assertEqual(len(self.state()["tests_commits"]), 1)  # once

    def test_a_tests_commit_state_json_lost_is_adopted_not_refused(self):
        # The commit is saved at once; were state.json to lose it anyway (a run
        # killed between the two), the next `next` adopts the commit instead of
        # refusing the checks as unchanged.
        self.planned()
        self.expect("acceptance-tester", "WRITTEN", checks="4", ambiguous="none")
        self.next(0)  # the step to the Build stage, once the checks are committed
        sha = self.state()["tests_commits"][0]["sha"]
        state = self.state()
        del state["tests_commits"], state["tests_synced"]
        self.write_state(state)
        self.expect("coder")  # no stop: the commit is adopted
        self.assertEqual([c["sha"] for c in self.state()["tests_commits"]], [sha])

    def test_the_checks_are_not_committed_while_the_manifest_has_gaps(self):
        self.planned()
        (self.dir / "acceptance" / "base-run" / "C2.txt").unlink()
        self.expect("acceptance-tester", "WRITTEN", checks="4", ambiguous="none")
        _, jobs = self.expect("acceptance-tester")  # re-spawned for the gap
        self.assertNotIn("tests_commits", self.state())
        (self.dir / "acceptance" / "base-run" / "C2.txt").write_text(BASE_RUNS["C2.txt"])
        self.answer(*jobs[0], "WRITTEN", checks="1", ambiguous="none")
        self.next(0)
        self.assertEqual(len(self.state()["tests_commits"]), 1)

    def test_plan_session_ends_at_the_boundary(self):
        self.plan_session()
        state = self.state()
        self.assertEqual(state["phases"]["3"]["status"], "done")
        self.assertEqual(state["phases"]["2"]["notes"], "FITS, risk: high")
        self.assertEqual(state["budget"]["remaining"], state["budget"]["total"])

    def test_oversized_stops_and_reports(self):
        (self.dir / "PLAN.md").write_text(OVERSIZED_PLAN)
        self.expect("planner", "OVERSIZED", **PLANNED)
        out = self.next(4)
        self.assertIn("too big for one PR", " ".join(out["REPORT"]))
        self.assertIn("Jira was not moved", " ".join(out["REPORT"]))
        # The reasons themselves, so the orchestrator never reads PLAN.md.
        self.assertIn("- Split: ship shared lists first, then invites", out["REPORT"])
        self.assertIn("- Subsystems: lists (~6 files), invites (~8 files)", out["REPORT"])

    def test_oversized_with_no_size_check_section_points_at_the_plan_not_a_reply(self):
        (self.dir / "PLAN.md").write_text(OVERSIZED_PLAN)
        self.expect("planner", "OVERSIZED", **PLANNED)
        self.next(4)
        (self.dir / "PLAN.md").write_text(OVERSIZED_PLAN.split("## Size check")[0])
        report = " ".join(self.next(4)["REPORT"])
        self.assertIn("PLAN.md has no Size check section", report)
        self.assertNotIn("reply", report)  # a worker's reply is its result block alone

    def test_oversized_retry_runs_the_planner_again(self):
        (self.dir / "PLAN.md").write_text(OVERSIZED_PLAN)
        self.expect("planner", "OVERSIZED", **PLANNED)
        self.next(4)
        r = self.autodev("override", "retry", "--text", "I narrowed the ticket",
                         "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        _, jobs = self.expect("planner")
        self.assertEqual(self.mode(*jobs[0]), "write")
        self.assertEqual(jobs, [("planner", 2)])

    def test_a_fits_sign_off_keeps_the_plan_s_high_risk(self):
        (self.dir / "PLAN.md").write_text(OVERSIZED_PLAN)
        self.expect("planner", "OVERSIZED", **PLANNED)
        out = self.next(4)
        self.assertIsNone(self.state()["high_risk"] or None)
        self.sign_off(out, "it fits: one PR is fine")
        state = self.state()
        self.assertEqual(state["size"], "FITS")
        self.assertTrue(state["high_risk"])
        self.assertTrue(state["settings"]["post_plan_gate"])
        self.write_steps()
        self.critic()

    def write_steps(self):
        """The OVERSIZED plan kept as one PR: the planner writes its steps once
        (no round), before the critic reads it."""
        budget = self.state()["budget"]["remaining"]
        _, jobs = self.expect("planner")
        (w, n), = jobs
        self.assertEqual(self.mode(w, n), "revise")
        self.assertIn("set the Size check to FITS and write the steps",
                      self.sets(w, n)["direction"])
        (self.dir / "PLAN.md").write_text(PLAN)
        self.answer(w, n, "REVISED", **PLANNED)
        self.assertEqual(self.state()["budget"]["remaining"], budget)

    def test_a_kept_oversized_plan_s_revision_needs_its_steps(self):
        (self.dir / "PLAN.md").write_text(OVERSIZED_PLAN)
        self.expect("planner", "OVERSIZED", **PLANNED)
        self.sign_off(self.next(4), "it fits: one PR is fine")
        _, jobs = self.expect("planner")
        (self.dir / "PLAN.md").write_text(OVERSIZED_PLAN.replace(
            "OVERSIZED: three deliverables.", "FITS: one PR after all."))
        self.answer(*jobs[0], "REVISED", **PLANNED)
        self.next(refused_ok=True)  # FITS with no steps: refused, re-spawned
        self.assertIn("## Build sequence",
                      " ".join(self.state()["refused"][f"planner-{jobs[0][1]}"]))

    def test_a_revision_that_says_oversized_is_refused(self):
        self.planned()
        _, jobs = self.expect("acceptance-tester")
        (self.dir / "acceptance" / "AMBIGUOUS.md").write_text("- 2: a / b\n")
        self.answer(*jobs[0], "WRITTEN", checks="4", ambiguous="2")
        _, jobs = self.expect("planner")
        (self.dir / "PLAN.md").write_text(PLAN.replace(
            "## Size check\nFITS", "## Size check\nOVERSIZED"))
        self.answer(*jobs[0], "REVISED", **{**PLANNED, "reading": "tester"})
        self.next(refused_ok=True)
        self.assertIn("a revision keeps the plan FITS",
                      " ".join(self.state()["refused"][f"planner-{jobs[0][1]}"]))

    def test_a_ticket_asks_before_moving_jira(self):
        state = self.state()
        state["task"]["ticket"] = "TODO-7"
        self.write_state(state)
        self.expect("planner", "FITS", **PLANNED)
        out = self.next(5)
        self.assertIn("TODO-7", out["QUESTION"])
        self.after(out, "Move it")
        out = self.next(0)
        self.assertIn("move Jira ticket TODO-7 to `In Progress`", out["ACTION"])
        # The can't-move command is printed whole: no AFTER line to edit.
        self.assertIn("mark jira-in-progress --value skipped", out["ACTION"])
        self.after(out)
        self.expect("plan-critic")

    def test_a_ticket_already_in_progress_is_not_moved_or_asked_about(self):
        state = self.state()
        state["task"]["ticket"] = "TODO-7"
        self.write_state(state)
        self.expect("planner", "FITS", **PLANNED)
        out = self.next(5)
        # Read the status first: a ticket in progress already is not asked about.
        self.assertIn("first read TODO-7's status", out["ACTION"])
        self.assertIn('run the "Already In Progress" AFTER line', out["ACTION"])
        self.assertIn("Already In Progress", out["QUESTION"])
        line = [ln.split(" → ", 1)[1] for ln in out["AFTER"]
                if ln.startswith('"Already In Progress"')]
        self.assertEqual(len(line), 1, out["AFTER"])
        r = subprocess.run(line[0], shell=True, capture_output=True, text=True,
                           env=self.env, cwd=self.tmp, check=False)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("jira: already", r.stdout)
        self.assertIn("start work without moving Jira now; later milestones move it",
                      r.stdout)
        self.assertEqual(self.state()["gates"][-1]["choice"], "already")
        self.expect("plan-critic")  # no move now
        self.assertNotIn("jira-in-progress", self.state().get("marks", {}))

    def test_the_already_answer_names_the_board_s_in_progress_state(self):
        state = self.state()
        state["task"]["ticket"] = "TODO-7"
        state["settings"]["jira_states"] = {"in_progress": "Doing"}
        self.write_state(state)
        self.expect("planner", "FITS", **PLANNED)
        out = self.next(5)
        self.assertIn("Already Doing", out["QUESTION"])
        self.assertNotIn("Already In Progress", out["QUESTION"])
        self.assertIn('run the "Already Doing" AFTER line', out["ACTION"])
        self.assertIn("already `Doing` or past it", out["ACTION"])
        self.assertTrue(any(ln.startswith('"Already Doing" → ') for ln in out["AFTER"]))

    # -------------------------------------------------------------- the critic

    def standard_plan(self):
        """The fixture plan at standard risk: no Security/Compliance criteria."""
        text = PLAN.replace("Risk: high", "Risk: standard")
        text = text.split("## Security/Compliance criteria")[0] + \
            "## Size check" + text.split("## Size check")[1]
        (self.dir / "PLAN.md").write_text(text)
        self.expect("planner", "FITS", **{**PLANNED, "risk": "standard"})

    def test_an_approved_plan_goes_to_the_acceptance_tester(self):
        self.standard_plan()
        _, jobs = self.critic("APPROVE", risk="standard")
        self.assertEqual(self.sets(*jobs[0]), {})
        self.assertIn(f"{self.dir}/plan-review/{jobs[0][1]}.md",
                      (self.dir / "briefs" / f"plan-critic-{jobs[0][1]}.md").read_text())
        self.expect("acceptance-tester", "WRITTEN", checks="4", ambiguous="none")
        self.assertEqual(self.next(0)["ACTION"].split(":")[0],
                         "the run goes on to the Build stage in this session")
        state = self.state()
        self.assertFalse(state["high_risk"])
        self.assertNotIn("plan_blockers", state)
        self.assertEqual(state["budget"]["remaining"], state["budget"]["total"])

    def test_blockers_send_the_plan_back_once_then_a_recheck(self):
        self.standard_plan()
        self.critic("REVISE", risk="standard", blockers=2)
        out, jobs = self.expect("planner", "REVISED", **{**PLANNED, "risk": "standard"})
        self.assertEqual(self.mode(*jobs[0]), "revise")
        self.assertEqual(self.sets(*jobs[0]),
                         {"review_file": f"{self.dir}/plan-review/1.md"})
        self.assertIn("plan-critic-1", out["BUDGET"])
        self.assertEqual(self.state()["budget"]["remaining"], 3)
        out, jobs = self.critic("APPROVE", risk="standard", mode="recheck")
        self.assertEqual(self.sets(*jobs[0]), {"earlier": f"{self.dir}/plan-review/1.md"})
        self.assertNotIn("BUDGET", out)  # the recheck is free
        self.expect("acceptance-tester", "WRITTEN", checks="4", ambiguous="none")
        self.assertIn("Build stage", self.next(0)["ACTION"])  # no gate at standard risk
        self.assertEqual(self.state()["budget"]["remaining"], 3)

    def test_blockers_still_open_after_the_revision_go_to_the_user(self):
        self.standard_plan()
        self.critic("REVISE", risk="standard", blockers=2)
        self.expect("planner", "REVISED", **{**PLANNED, "risk": "standard"})
        self.critic("REVISE", risk="standard", blockers=1, mode="recheck")
        out = self.next(5)  # asked even at standard risk, before any check is written
        state = self.state()
        self.assertEqual(state["plan_blockers"], 2)
        self.assertTrue(state["settings"]["post_plan_gate"])
        self.assertFalse(state["high_risk"])
        self.assertNotIn("tests_commits", state)
        self.assertIn("left these blockers open", " ".join(out["SUMMARY"]))
        text = json.dumps(out)
        self.assertIn("B1. the plan misses case 1", text)
        self.assertIn("plan-review/2.md", text)
        self.assertEqual(self.state()["budget"]["remaining"], 3)  # one round in all

    def test_explain_at_the_open_blockers_step_writes_nothing(self):
        self.standard_plan()
        self.critic("REVISE", risk="standard", blockers=2)
        self.expect("planner", "REVISED", **{**PLANNED, "risk": "standard"})
        _, jobs = self.critic("REVISE", risk="standard", blockers=1, mode="recheck")
        r = self.autodev("record", *map(str, jobs[0]), "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        r = self.autodev("next", "--dir", self.dir, "--explain")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("send the open blockers to the post-plan gate", r.stdout)
        state = self.state()
        self.assertNotIn("plan_blockers", state)
        self.assertFalse(state["settings"]["post_plan_gate"])

    def test_revising_at_the_gate_clears_the_open_blockers(self):
        self.standard_plan()
        self.critic("REVISE", risk="standard", blockers=1)
        self.expect("planner", "REVISED", **{**PLANNED, "risk": "standard"})
        self.critic("REVISE", risk="standard", blockers=1, mode="recheck")
        self.next(5)
        self.autodev("gate", "post-plan", "revise", "--reason", "drop case 1",
                     "--dir", self.dir)
        self.expect("planner", "REVISED", **{**PLANNED, "risk": "standard"})
        out = self.next(5)  # asked again, without the old blockers
        self.assertNotIn("plan_blockers", self.state())
        self.assertNotIn("left these blockers open", json.dumps(out))
        notes = [n["text"] for n in self.state()["notes"] if "still open" in n["text"]]
        self.assertEqual(len(notes), 1)  # the critic's blockers are not sent twice
        self.after(out, "Approve & build")
        self.expect("acceptance-tester")
        self.assertNotIn("plan_blockers", self.state())

    def test_no_round_left_for_a_revision_stops(self):
        state = self.state()
        state["budget"]["remaining"] = 0
        self.write_state(state)
        self.standard_plan()
        self.critic("REVISE", risk="standard", blockers=1)
        out = self.next(4)
        self.assertIn("no round left to revise the plan", json.dumps(out))
        self.assertIn("plan-review/1.md", json.dumps(out))

    def test_the_critic_raises_the_risk_and_turns_the_gate_on(self):
        self.standard_plan()
        self.assertFalse(self.state()["high_risk"])
        self.critic("APPROVE", risk="high")
        out = self.next(5)
        state = self.state()
        self.assertTrue(state["high_risk"])
        self.assertTrue(state["settings"]["post_plan_gate"])
        self.assertTrue(any("plan critic says the risk is high" in n["text"]
                            for n in state["notes"]))
        self.after(out, "Approve & build")
        self.expect("acceptance-tester")

    def test_the_critic_can_t_lower_a_high_tier(self):
        self.expect("planner", "FITS", **PLANNED)  # the fixture: high
        self.critic("APPROVE", risk="standard")
        out = self.next(0, refused_ok=True)  # refused, and briefed again
        self.assertEqual(self.spawned(out), [("plan-critic", 2)])
        self.assertIn("the critic can't lower the tier",
                      " ".join(self.state()["refused"]["plan-critic-1"]))
        self.assertTrue(self.state()["high_risk"])

    def test_an_ambiguous_return_needs_the_readings_file(self):
        self.planned()
        _, jobs = self.expect("acceptance-tester")
        self.answer(*jobs[0], "WRITTEN", checks="4", ambiguous="2")
        out = self.next(0, refused_ok=True)
        self.assertIn(f"acceptance-tester-{jobs[0][1]}: refused (MISMATCH)", out["RECORDED"])
        self.assertIn("AMBIGUOUS.md does not exist",
                      " ".join(self.state()["refused"][f"acceptance-tester-{jobs[0][1]}"]))

    def test_a_planner_value_next_compares_word_for_word_is_checked(self):
        (self.dir / "PLAN.md").write_text(self.plan_text)
        _, jobs = self.expect("planner")
        self.answer(*jobs[0], "FITS", **{**PLANNED, "entry_points_changed": "Yes"})
        out = self.next(0, refused_ok=True)
        self.assertIn("planner-1: refused (MISMATCH)", out["RECORDED"])
        self.assertIn("entry_points_changed is 'Yes'",
                      " ".join(self.state()["refused"]["planner-1"]))

    def test_an_ambiguous_condition_goes_to_the_planner(self):
        self.planned()
        _, jobs = self.expect("acceptance-tester")
        (self.dir / "acceptance" / "AMBIGUOUS.md").write_text("- 2: a / b\n")
        self.answer(*jobs[0], "WRITTEN", checks="4", ambiguous="2")
        out, jobs = self.expect("planner", "REVISED", **{**PLANNED, "reading": "other"})
        self.assertIn("conditions 2", self.sets(*jobs[0])["ambiguous"])
        out, jobs = self.expect("acceptance-tester")
        self.assertTrue(self.sets(*jobs[0])["scope"].startswith("ONLY conditions 2"))
        self.assertNotIn("BUDGET", out)  # the other reading costs no round

    def test_a_condition_still_ambiguous_after_the_planner_decided_stops(self):
        self.planned()
        _, jobs = self.expect("acceptance-tester")
        (self.dir / "acceptance" / "AMBIGUOUS.md").write_text("- 2: a / b\n")
        self.answer(*jobs[0], "WRITTEN", checks="4", ambiguous="2")
        self.expect("planner", "REVISED", **{**PLANNED, "reading": "other"})
        _, jobs = self.expect("acceptance-tester")
        self.answer(*jobs[0], "WRITTEN", checks="1", ambiguous="2")  # still two ways
        out = self.next(4)  # free, but once: no planner/tester loop
        self.assertIn("still finds condition(s) 2 reading two ways",
                      " ".join(out["REPORT"]))

    def test_an_ambiguous_condition_read_the_tester_s_way_goes_on(self):
        self.planned()
        _, jobs = self.expect("acceptance-tester")
        (self.dir / "acceptance" / "AMBIGUOUS.md").write_text("- 2: a / b\n")
        self.answer(*jobs[0], "WRITTEN", checks="4", ambiguous="2")
        self.expect("planner", "REVISED", **{**PLANNED, "reading": "tester"})
        self.enter_stage("build")

    # ------------------------------------------------------------------

    def test_acceptance_gaps_respawn_the_tester_for_those_conditions(self):
        (self.dir / "acceptance" / "base-run" / "C2.txt").unlink()
        self.planned()
        self.expect("acceptance-tester", "WRITTEN", checks="4", ambiguous="none")
        out, jobs = self.expect("acceptance-tester")
        self.assertTrue(self.sets(*jobs[0])["scope"].startswith("ONLY conditions 2:"))
        self.assertNotIn("BUDGET", out)  # free, once
        self.answer(*jobs[0], "WRITTEN", checks="1", ambiguous="none")  # gaps still
        out = self.next(4)
        self.assertIn("gaps after the tester's second try", " ".join(out["REPORT"]))

    def test_post_plan_revise_goes_to_the_planner_then_asks_again(self):
        self.planned(gate=False)
        self.next(5)
        self.autodev("gate", "post-plan", "revise", "--reason", "store dates in UTC",
                     "--dir", self.dir)
        out, jobs = self.expect("planner", "REVISED", **PLANNED)
        self.assertEqual(self.sets(*jobs[0])["direction"], "store dates in UTC")
        self.assertNotIn("BUDGET", out)
        self.after(self.next(5), "Approve & build")
        self.expect("acceptance-tester", "WRITTEN", checks="4", ambiguous="none")
        self.enter_stage("build")

    def test_an_unrecorded_brief_is_reissued_then_stops(self):
        out, jobs = self.expect("planner")
        self.assertEqual(self.spawned(self.next(0, reissue=True)), jobs)
        self.next(0, reissue=True)
        out = self.next(4, reissue=True)
        self.assertIn("spawned 3 times", " ".join(out["REPORT"]))

    def test_a_long_session_checkpoints_and_resumes_where_it_stopped(self):
        state = self.state()
        state["settings"]["checkpoint_events"] = state["events"] + 4
        (self.dir / "state.json").write_text(json.dumps(state))
        self.expect("planner", "FITS", **PLANNED)
        _, jobs = self.expect("plan-critic")  # a brief in flight is finished first
        self.assertTrue(self.next(0)["ACTION"].startswith("wait"))  # not a checkpoint
        (self.dir / "plan-review").mkdir(exist_ok=True)
        (self.dir / "plan-review" / "1.md").write_text(plan_review())
        self.answer(*jobs[0], "APPROVE", blockers="0", risk="high")
        self.after(self.next(5), "Approve & build")  # a question comes before a checkpoint
        out = self.next(6)
        self.assertIn("--checkpoint", out["AFTER"][0])
        self.after(out)
        self.assertIn("(checkpoint)", (self.dir / "HANDOFF.md").read_text())
        self.resume()
        self.expect("acceptance-tester")

    def test_a_checkpoint_resume_keeps_a_worker_s_first_failure(self):
        _, jobs = self.expect("planner")
        self.answer(*jobs[0], "", status="failed")
        state = self.state()
        state["settings"]["checkpoint_events"] = state["events"]
        self.write_state(state)
        out = self.next(6)  # the re-spawn is an action: a clean point
        self.assertIn("--checkpoint", out["AFTER"][0])
        self.after(out)
        self.resume()
        state = self.state()
        state["settings"]["checkpoint_events"] = 1000
        self.write_state(state)
        _, jobs = self.expect("planner")
        self.answer(*jobs[0], "", status="failed")
        self.assertIn("failed twice", " ".join(self.next(4)["REPORT"]))

    def test_a_checkpoint_count_that_is_not_a_number_falls_back_to_80(self):
        events = self.state()["events"]
        for value in ("lots", 0):
            with self.subTest(value=value):
                state = self.state()
                state["settings"]["checkpoint_events"] = value
                state["events"] = 80
                self.write_state(state)
                self.assertEqual(self.next()["exit"], 6)  # a checkpoint, not exit 2
        state = self.state()
        state["events"] = events  # far below 80
        self.write_state(state)
        self.assertEqual(self.next()["exit"], 0)

    def test_a_refused_return_is_respawned_with_its_issues(self):
        self.expect("planner")
        (self.dir / "returns" / "planner-1.json").write_text(json.dumps(
            {"worker": "planner", "status": "ok", "next": "FITS"}))
        r = self.autodev("record", "planner", "1", "--dir", self.dir)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("MALFORMED", r.stdout)
        out = self.next(0)
        self.assertEqual(self.spawned(out), [("planner", 2)])
        self.assertNotIn("AFTER", out)  # `next` records planner #2's result itself
        brief = (self.dir / "briefs" / "planner-2.md").read_text()
        self.assertIn("risk", brief)  # the refused issues ride along
        self.next(0, reissue=True)
        self.assertIn("spawned 3 times", " ".join(self.next(4, reissue=True)["REPORT"]))

    def test_next_records_a_returned_worker_itself(self):
        self.expect("planner")
        self.write_return("planner", 1, {"next": "FITS", **PLANNED})
        before = self.state()["events"]
        out = self.next(0)  # no `record` call
        self.assertEqual(out["RECORDED"], ["planner-1: ok FITS"])
        self.assertEqual(self.spawned(out), [("plan-critic", 1)])
        state = self.state()
        self.assertEqual([(e["worker"], e["n"], e["next"]) for e in state["log"]],
                         [("planner", 1, "FITS")])
        self.assertEqual(state["size"], "FITS")
        # Two events, as `record` then `next` were: the result is stamped before
        # the brief written after it, so `next` orders them as before.
        self.assertEqual(state["events"], before + 2)
        entry = next(b for b in state["briefs"] if b["worker"] == "plan-critic")
        self.assertLess(state["log"][0]["seq"], entry["seq"])
        self.assertNotIn("RECORDED", self.next(0))  # recorded once
        # A brief with no result file is issued again as it is, not refused.
        self.assertEqual(self.spawned(self.next(0, reissue=True)), [("plan-critic", 1)])
        self.assertNotIn("plan-critic-1", self.state().get("refused", {}))

    def test_next_refuses_a_bad_result_itself_and_briefs_the_job_again(self):
        self.expect("planner")
        self.write_return("planner", 1, {"next": "FITS"})  # risk, reading left out
        out = self.next(0, refused_ok=True)
        self.assertEqual(out["RECORDED"], ["planner-1: refused (MALFORMED)"])
        self.assertEqual(self.spawned(out), [("planner", 2)])
        self.assertIn("risk", (self.dir / "briefs" / "planner-2.md").read_text())

    def test_explain_says_it_would_record_and_records_nothing(self):
        self.expect("planner")
        self.write_return("planner", 1, {"next": "FITS", **PLANNED})
        before = (self.dir / "state.json").read_text()
        r = self.autodev("next", "--dir", self.dir, "--explain")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("next would record planner-1 first", r.stdout)
        self.assertEqual((self.dir / "state.json").read_text(), before)
        self.assertEqual(self.next(0)["RECORDED"], ["planner-1: ok FITS"])

    def test_a_result_recorded_before_a_stop_counts_one_event(self):
        self.expect("planner")
        (self.dir / "PLAN.md").write_text(OVERSIZED_PLAN)
        self.write_return("planner", 1, {"next": "OVERSIZED", **PLANNED})
        before = self.state()["events"]
        out = self.next(4)  # the stop writes nothing of its own
        self.assertEqual(out["RECORDED"], ["planner-1: ok OVERSIZED"])
        self.assertEqual(self.state()["events"], before + 1)  # as `record` alone was

    def test_explain_only_looks(self):
        for _ in range(4):
            r = self.autodev("next", "--dir", self.dir, "--explain")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("nothing was done", r.stdout)
            self.assertIn("RULE: Phase 2 starts with the planner", r.stdout)
        self.assertFalse((self.dir / "briefs" / "planner-1.md").exists())
        _, jobs = self.expect("planner")
        self.assertEqual(jobs, [("planner", 1)])
        for _ in range(3):  # an explain is not a spawn
            self.assertEqual(self.autodev("next", "--dir", self.dir, "--explain").returncode, 0)
        self.assertEqual(self.spawned(self.next(0, reissue=True)), [("planner", 1)])

    def test_a_malformed_manifest_check_is_not_a_round(self):
        self.planned()
        self.expect("acceptance-tester", "WRITTEN", checks="4", ambiguous="none")
        (self.dir / "PLAN.md").write_text("# Plan\n\nNo conditions here.\n")
        r = self.autodev("next", "--dir", self.dir)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)  # check-manifest MALFORMED
        self.assertIn("MALFORMED", r.stderr)
        state = self.state()
        self.assertEqual(state["budget"]["remaining"], state["budget"]["total"])

    def test_a_retry_brief_written_by_hand_is_spawned_once(self):
        self.expect("planner")
        self.write_return("planner", 1, {"next": "FITS"})
        r = self.autodev("record", "planner", "1", "--dir", self.dir)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("autodev.py next", r.stdout)
        r = self.autodev("brief", "planner", "--mode", "write", "--retry", "1", "--dir",
                         self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        out = self.next(0)  # `brief` printed the spawn: planner #2 is out
        self.assertTrue(out["ACTION"].startswith("wait"), out)
        self.assertIn("planner #2", out["ACTION"])
        self.assertNotIn("BRIEF", out)
        self.assertEqual(self.spawned(self.next(0, reissue=True)), [("planner", 2)])

    def test_recording_a_job_again_keeps_its_place(self):
        self.expect("planner", "FITS", **PLANNED)
        self.critic()
        r = self.autodev("record", "planner", "1", "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        # The review stands (planner-1 is no newer): on to the post-plan gate.
        self.assertIn("post-plan gate", self.next(5)["QUESTION"])

    def test_a_worker_blocked_once_is_spawned_again_and_twice_stops(self):
        _, jobs = self.expect("planner")
        self.answer(*jobs[0], "", status="blocked")
        _, jobs = self.expect("planner")  # once: spawned again, told why
        self.assertEqual(jobs, [("planner", 2)])
        brief = (self.dir / "briefs" / "planner-2.md").read_text()
        self.assertIn("returned `blocked`", brief)
        self.answer(*jobs[0], "", status="blocked")
        self.assertIn("stopped on purpose twice running",
                      " ".join(self.next(4)["REPORT"]))
        self.assertEqual(self.next(4)["exit"], 4)
        self.resume()
        _, jobs = self.expect("planner")
        self.assertEqual(jobs, [("planner", 3)])
        self.assertNotIn("returned `blocked`",  # after a resume, a fresh brief
                         (self.dir / "briefs" / "planner-3.md").read_text())

    def test_failed_then_blocked_stops_too(self):
        # Mixed non-ok results must not re-spawn a worker forever.
        _, jobs = self.expect("planner")
        self.answer(*jobs[0], "", status="failed")
        _, jobs = self.expect("planner")
        self.answer(*jobs[0], "", status="blocked")
        self.assertIn("did not return ok twice running", " ".join(self.next(4)["REPORT"]))

    def test_resume_after_a_worker_never_returned_spawns_it_again(self):
        self.expect("planner")
        self.next(0, reissue=True)
        self.next(0, reissue=True)
        self.assertIn("spawned 3 times", " ".join(self.next(4, reissue=True)["REPORT"]))
        self.resume()
        self.assertEqual(self.spawned(self.next(0)), [("planner", 1)])

    def test_a_worker_that_failed_is_respawned_once(self):
        _, jobs = self.expect("planner")
        self.answer(*jobs[0], "", status="failed")
        _, jobs = self.expect("planner")
        self.answer(*jobs[0], "", status="failed")
        self.assertIn("failed twice", " ".join(self.next(4)["REPORT"]))

    def test_a_brief_out_in_this_session_is_waited_for(self):
        self.expect("planner")
        before = self.brief_files()
        out = self.next(0)
        self.assert_waits_for(out, "planner #1")
        self.assertEqual(self.brief_files(), before)  # no brief written

    def test_asking_again_and_again_while_a_worker_is_out_never_stops_the_run(self):
        self.expect("planner")
        events = self.state()["events"]
        actions = []
        for _ in range(5):
            out = self.next()
            self.assertNotIn("spawned 3 times", " ".join(out.get("REPORT", [])))
            self.assert_waits_for(out, "planner #1")
            self.assertEqual(self.state()["events"], events)
            actions.append(out["ACTION"])
        self.assertEqual(len(set(actions)), 1, actions)  # the same wait each time

    def test_reissue_sends_the_same_brief_and_a_plain_next_then_waits(self):
        self.expect("planner")
        self.assert_spawns_planner_1_again(self.next_reissue(0))
        self.assert_waits_for(self.next(0), "planner #1")

    def test_three_spawns_by_reissue_still_stop_the_run(self):
        self.expect("planner")
        self.assertEqual(self.spawned(self.next_reissue(0)), [("planner", 1)])
        self.assertEqual(self.spawned(self.next_reissue(0)), [("planner", 1)])
        out = self.next_reissue(4)
        self.assertIn("spawned 3 times", " ".join(out["REPORT"]))

    def test_a_brief_from_an_earlier_session_is_sent_again(self):
        self.expect("planner")
        self.resume()
        self.assert_spawns_planner_1_again(self.next(0))

    def test_a_brief_sent_again_after_a_resume_is_waited_for(self):
        self.expect("planner")
        self.resume()
        self.assert_spawns_planner_1_again(self.next(0))
        self.assert_waits_for(self.next(0), "planner #1")

    def test_a_brief_out_over_three_hours_is_sent_again_then_waited_for(self):
        self.expect("planner")
        self.sent_out_ago("planner", 1, hours=3, minutes=10)
        self.assert_spawns_planner_1_again(self.next(0))
        self.assert_waits_for(self.next(0), "planner #1")

    def test_a_brief_out_under_three_hours_is_waited_for(self):
        self.expect("planner")
        self.sent_out_ago("planner", 1, hours=2, minutes=50)
        before = self.brief_files()
        self.assert_waits_for(self.next(0), "planner #1")
        self.assertEqual(self.brief_files(), before)

    def test_a_retry_at_the_three_spawn_stop_sends_the_brief_again(self):
        self.stopped_after_three_spawns()
        r = self.autodev("override", "retry", "--text", "I fixed the cause", "--dir",
                         self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assert_spawns_planner_1_again(self.next(0))

    def test_the_brief_sent_again_after_a_retry_is_waited_for(self):
        self.stopped_after_three_spawns()
        r = self.autodev("override", "retry", "--text", "I fixed the cause", "--dir",
                         self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assert_spawns_planner_1_again(self.next(0))
        before = self.brief_files()
        self.assert_waits_for(self.next(0), "planner #1")
        self.assertEqual(self.brief_files(), before)

    def test_a_reissue_stamps_when_it_sent_the_brief_out(self):
        self.expect("planner")
        first = next(b for b in self.state()["briefs"] if b["worker"] == "planner")
        self.next(0, reissue=True)
        again = next(b for b in self.state()["briefs"] if b["worker"] == "planner")
        self.assertEqual((again["at"], again["seq"]), (first["at"], first["seq"]))
        self.assertGreater(again["issued_seq"], first["seq"])
        self.assertIn("issued_at", again)

    def test_a_brief_whose_issue_time_is_unreadable_is_sent_again(self):
        for at in ("not a time", "2026-01-01T00:00:00"):  # the second has no zone
            with self.subTest(at=at):
                self.setUp()
                self.expect("planner")
                state = self.state()
                state["briefs"][-1]["at"] = at
                self.write_state(state)
                self.assert_spawns_planner_1_again(self.next(0))

    def test_explain_waits_too_and_writes_nothing(self):
        self.expect("planner")
        before = (self.dir / "state.json").read_text()
        r = self.autodev("next", "--dir", self.dir, "--explain")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("nothing was done; run `next` to act) wait: planner #1", r.stdout)
        self.assertEqual((self.dir / "state.json").read_text(), before)

    def test_a_lone_spawn_is_sent_in_the_foreground(self):
        out = self.next(0)
        self.assertEqual(out.get("AGENT"), ["auto-dev:planner"], json.dumps(out, indent=2))
        self.assertIn("auto-dev:planner", out["ACTION"])
        self.assertIn("run_in_background: false", out["ACTION"])


class BuildTest(NextCase):
    def test_the_run_goes_straight_through_in_one_session(self):
        # 5.0: plan, build and ship in one session. Each stage
        # starts with its runbook; no session ends, so no HANDOFF.md is written.
        events = self.state()["events"]
        self.plan_session()
        self.build_session()
        state = self.state()
        self.assertEqual(state["phases"]["5"]["status"], "done")
        self.assertEqual(state["stage"], "ship")
        self.assertFalse((self.dir / "HANDOFF.md").exists())
        self.assertNotIn("resumed_seq", state)
        self.assertGreater(state["events"], events)
        self.assertIn("commit: run", self.next(0)["ACTION"])  # Ship work, same session

    def test_a_checkpoint_at_the_end_of_a_stage_resumes_into_the_next(self):
        self.planned()
        self.expect("acceptance-tester", "WRITTEN", checks="4", ambiguous="none")
        state = self.state()
        state["settings"]["checkpoint_events"] = 1  # due as the Plan stage ends
        self.write_state(state)
        out = self.next(6)
        self.after(out)
        # Phase 3 is closed by the next `next`, so the handoff still names it
        self.assertIn("Plan stage (checkpoint)", (self.dir / "HANDOFF.md").read_text())
        self.resume()
        state = self.state()
        state["settings"]["checkpoint_events"] = 1000
        self.write_state(state)
        self.enter_stage("build")  # one step to the Build stage, then the coder
        self.expect("coder")

    def test_the_step_to_a_new_stage_deletes_an_old_handoff(self):
        # a HANDOFF.md from an earlier stage must not brief a later session
        self.planned()
        self.expect("acceptance-tester", "WRITTEN", checks="4", ambiguous="none")
        (self.dir / "HANDOFF.md").write_text("# auto-dev handoff → Plan stage (checkpoint)\n")
        self.enter_stage("build")
        self.assertFalse((self.dir / "HANDOFF.md").exists())

    def test_a_4x_run_that_ended_is_finished_not_old(self):
        self.plan_session()
        state = self.state()
        state["schema"] = 4
        for phase in state["phases"].values():
            phase["status"] = "done"
        self.write_state(state)
        r = self.autodev("resume", "--repo", self.worktree)  # started in its worktree
        self.assertTrue(r.stdout.startswith(f"FINISHED: {self.worktree}"), r.stdout)
        r = self.autodev("resume", "--repo", self.repo)  # not picked as open
        self.assertTrue(r.stdout.startswith("ASK"), r.stdout)

    def test_a_4x_run_is_refused(self):
        self.plan_session()
        state = self.state()
        state["schema"] = 4  # a run started on 4.x
        self.write_state(state)
        r = self.autodev("resume", "--repo", self.repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(r.stdout.startswith(f"OLD-VERSION: {self.worktree}"), r.stdout)
        self.assertIn("auto-dev 4.x; finish it on 4.27", r.stdout)
        r = self.autodev("next", "--dir", self.dir)  # nor does `next` run it
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("a run started on auto-dev 4.x", r.stderr)

    def test_explain_at_a_new_stage_writes_nothing(self):
        self.plan_session()
        self.build_session()
        state = self.state()
        state["stage"] = "build"  # as if the Ship stage's runbook was not read yet
        self.write_state(state)
        r = self.autodev("next", "--dir", self.dir, "--explain")
        self.assertIn("move on to the Ship stage", r.stdout)
        self.assertEqual(self.state()["stage"], "build")
        self.enter_stage("ship")

    def test_a_blocked_step_goes_to_the_planner_then_the_coder(self):
        self.plan_session()
        self.resume()
        out, jobs = self.expect("coder")
        (self.dir / "blocked" / "coder-1.md").write_text("- step 1: the store has no date type\n")
        self.answer(*jobs[0], "BLOCKED", blocked="1", test_changes="none")
        out, jobs = self.expect("planner", "PLAN_REVISED", **PLANNED)
        self.assertIn("blocked/coder-1.md", self.sets(*jobs[0])["blocked"])
        out, jobs = self.expect("coder", "BUILT", blocked="0", test_changes="none")
        self.assertNotIn("BUDGET", out)  # a blocked step's re-dispatch is free
        self.quality_gate()

    def test_a_step_blocked_again_after_the_planner_stops(self):
        self.plan_session()
        self.resume()
        _, jobs = self.expect("coder")
        (self.dir / "blocked" / "coder-1.md").write_text("- step 1: the store has no date type\n")
        self.answer(*jobs[0], "BLOCKED", blocked="1", test_changes="none")
        self.expect("planner", "PLAN_REVISED", **PLANNED)
        _, jobs = self.expect("coder")
        (self.dir / "blocked" / f"coder-{jobs[0][1]}.md").write_text("- step 2: still no type\n")
        self.answer(*jobs[0], "BLOCKED", blocked="1", test_changes="none")
        out = self.next(4)  # once is free; again in the same change, the user decides
        self.assertIn("stopped a step again", " ".join(out["REPORT"]))

    def test_phase_5_runs_the_quality_gate_itself_on_the_committed_checks(self):
        self.plan_session()
        self.resume()
        commits = self.state()["tests_commits"]
        self.assertEqual(len(commits), 1)  # committed in Phase 3, before the build
        self.assertEqual(commits[0]["paths"],
                         ["src/due.acceptance.test.ts", "src/sort.acceptance.test.ts"])
        _, jobs = self.expect("coder", "BUILT", blocked="0", test_changes="none")
        (self.worktree / "due.ts").write_text("export const due = 1;\n")
        r = self.autodev("record", jobs[0][0], jobs[0][1], "--dir", self.dir)  # as `next` would
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        out = self.autodev("next", "--explain", "--dir", self.dir)
        self.assertIn("quality-gate", out.stdout)  # a script: no worker
        self.quality_gate()
        report = (self.dir / "lint" / "TEST.md").read_text()
        self.assertTrue(report.startswith("# TEST — pass"), report)
        self.assertIn(f"- **Tree:** {self.tree()}", report)
        self.enter_stage("ship")  # nothing verified or reviewed before the push
        self.assertFalse([b for b in self.state()["briefs"]
                          if b["worker"] not in ("planner", "plan-critic",
                                                 "acceptance-tester", "coder")])

    def test_a_red_gate_goes_to_the_coder_once_then_stops(self):
        self.plan_session()
        self.resume()
        self.expect("coder", "BUILT", blocked="0", test_changes="none")
        (self.worktree / "due.ts").write_text("export const due = 1;\n")
        self.quality_gate(red=True)
        out, jobs = self.expect("coder")
        self.assertEqual(self.mode(*jobs[0]), "correction")
        self.assertIn("the failing quality-gate checks", self.sets(*jobs[0])["corrections_file"])
        self.assertIn("lint/TEST.md", self.sets(*jobs[0])["corrections_file"])
        self.assertNotIn("BUDGET", out)  # free: red again after it is a stop
        self.answer(*jobs[0], "BUILT", blocked="0", test_changes="none")
        self.quality_gate(red=True)
        out = self.next(4)  # red again after its correction: the user decides
        self.assertIn("still red after the coder's correction", " ".join(out["REPORT"]))
        self.assertEqual(self.state()["stop"]["kind"], "red-gate")
        r = self.autodev("override", "retry", "--text", "I fixed the check", "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.quality_gate()  # a retry runs the gate again
        self.enter_stage("ship")

    def test_a_gate_that_never_finishes_stops_after_three_asks(self):
        self.plan_session()
        self.resume()
        self.expect("coder", "BUILT", blocked="0", test_changes="none")
        (self.worktree / "due.ts").write_text("export const due = 1;\n")
        for _ in range(3):  # the orchestrator's command was killed each time
            self.assertIn("quality-gate", self.next(0)["ACTION"])
        out = self.next(4)
        self.assertIn("no run was recorded", " ".join(out["REPORT"]))
        r = self.autodev("override", "retry", "--text", "run it in the background",
                         "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.quality_gate()
        self.enter_stage("ship")

    def test_a_changed_gate_runs_again_on_the_same_code(self):
        self.plan_session()
        self.resume()
        self.expect("coder", "BUILT", blocked="0", test_changes="none")
        (self.worktree / "due.ts").write_text("export const due = 1;\n")
        self.quality_gate()
        self.enter_stage("ship")
        state = self.state()  # a fix at a stop changed a gate command, say
        state["settings"]["gate"][0]["command"] = "true --strict"
        self.write_state(state)
        state = self.state()
        state["phase6"].setdefault("corrections", []).append(
            {"entry": "fix", "file": None, "checks": None, "seq": state["events"] + 1,
             "after_commit": False, "rule": "a fix", "budget": None, "spend_id": None})
        self.write_state(state)
        self.assertIn("quality-gate", self.next(0)["ACTION"])

    def test_a_red_gate_signed_off_goes_on(self):
        self.plan_session()
        self.resume()
        self.expect("coder", "BUILT", blocked="0", test_changes="none")
        (self.worktree / "due.ts").write_text("export const due = 1;\n")
        self.quality_gate(red=True)
        self.expect("coder", "BUILT", blocked="0", test_changes="none")
        self.quality_gate(red=True)
        self.sign_off(self.next(4), "the flaky check is known")
        self.enter_stage("ship")

    def test_a_repair_commits_the_testers_change_not_the_coders_lines(self):
        # The coder added its own test to a check file, then stopped a step;
        # the revised plan changed an entry point, so the tester repairs a
        # check in that file. The tests commit holds the repair alone: the
        # coder's line stays uncommitted, and unguarded.
        self.plan_session()
        self.resume()
        _, jobs = self.expect("coder")
        check = self.worktree / "src" / "due.acceptance.test.ts"
        check.write_text("the coder's own test\ntest")
        (self.dir / "blocked" / "coder-1.md").write_text("- step 1: the store has no date type\n")
        self.answer(*jobs[0], "BLOCKED", blocked="1", test_changes="none")
        self.expect("planner", "PLAN_REVISED", **{**PLANNED, "entry_points_changed": "yes"})
        _, jobs = self.expect("acceptance-tester")
        check.write_text("the coder's own test\ntest, repaired")
        self.answer(*jobs[0], "REPAIRED", checks="1", ambiguous="none")
        self.expect("coder")  # the repair is committed first
        self.assertEqual(self.sh("git", "show", "HEAD:src/due.acceptance.test.ts",
                                 cwd=self.worktree), "test, repaired")
        self.assertIn("src/due.acceptance.test.ts",
                      self.sh("git", "status", "--porcelain", cwd=self.worktree))
        self.assertEqual(self.sh("git", "diff", "--cached", "--name-only",
                                 cwd=self.worktree), "")
        notes = " ".join(n["text"] for n in self.state()["notes"])
        self.assertNotIn("whole file was committed", notes)

    def test_a_repair_that_cant_apply_alone_commits_the_whole_file_and_says_so(self):
        self.plan_session()
        self.resume()
        _, jobs = self.expect("coder")
        check = self.worktree / "src" / "due.acceptance.test.ts"
        check.write_text("the coder's own test\ntest")
        (self.dir / "blocked" / "coder-1.md").write_text("- step 1: the store has no date type\n")
        self.answer(*jobs[0], "BLOCKED", blocked="1", test_changes="none")
        self.expect("planner", "PLAN_REVISED", **{**PLANNED, "entry_points_changed": "yes"})
        _, jobs = self.expect("acceptance-tester")
        check.write_text("the coder's test, rewritten by the tester\ntest, repaired")
        self.answer(*jobs[0], "REPAIRED", checks="1", ambiguous="none")
        self.expect("coder")
        self.assertEqual(self.sh("git", "show", "HEAD:src/due.acceptance.test.ts",
                                 cwd=self.worktree), check.read_text())
        notes = " ".join(n["text"] for n in self.state()["notes"])
        self.assertIn("whole file was committed", notes)

    def test_a_coder_that_edits_a_committed_check_is_refused(self):
        # The checks are committed before the build; the coder sees them and
        # may add its own tests around them, never change one of their lines.
        self.plan_session()
        self.resume()
        _, jobs = self.expect("coder")
        check = self.worktree / "src" / "due.acceptance.test.ts"
        check.write_text("weakened\n")
        self.answer(*jobs[0], "BUILT", blocked="0", test_changes="none")
        out = self.next(0, refused_ok=True)
        self.assertIn("coder-1: refused (MISMATCH)", out["RECORDED"])
        issues = self.state()["refused"]["coder-1"]
        self.assertIn("src/due.acceptance.test.ts at line(s) 1", " ".join(issues))
        retry = self.spawned(out)
        self.assertEqual(retry, [("coder", 2)])
        check.write_text("the coder's own test\ntest")  # around them is fine
        self.answer(*retry[0], "BUILT", blocked="0", test_changes="none")
        self.quality_gate()

    def test_a_freshness_check_that_could_not_run_exits_2(self):
        self.plan_session()
        self.resume()
        self.expect("coder", "BUILT", blocked="0", test_changes="none")
        (self.worktree / "due.ts").write_text("export const due = 1;\n")
        (self.tmp / "no-git").mkdir()
        env = {**self.env, "PATH": str(self.tmp / "no-git")}  # check-fresh can't run git
        r = subprocess.run([sys.executable, str(AUTODEV), "next", "--dir", str(self.dir)],
                           capture_output=True, text=True, env=env, check=False)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("'git'", r.stderr)
        self.assertNotIn("stale", r.stdout)

    def test_rounds_added_after_the_stop_take_the_step_that_stopped(self):
        state = self.state()
        state["budget"].update(total=1, remaining=0)
        self.write_state(state)
        self.expect("planner", "FITS", **PLANNED)
        self.critic("REVISE", blockers=1)
        self.next(4)  # no round for the plan's revision
        out = self.next(4)  # it stops at the same place again
        self.raise_from_report(out, 2)
        out, jobs = self.expect("planner")
        self.assertEqual(self.mode(*jobs[0]), "revise")
        self.assertIn("spent `plan-critic-1`", out["BUDGET"])
        self.assertIn("1 of 3 left", out["BUDGET"])
        budget = self.state()["budget"]
        self.assertNotIn("stopped", budget)
        self.assertEqual([r["by"] for r in budget["raises"]], [2])

    def test_a_step_past_a_budget_stop_clears_it(self):
        self.plan_session()
        state = self.state()
        state["budget"]["stopped"] = {"seq": 1, "what": "x"}
        self.write_state(state)
        self.resume()
        self.expect("coder")
        self.assertNotIn("stopped", self.state()["budget"])
        r = self.autodev("budget", "raise", "--by", "1", "--dir", self.dir)
        self.assertEqual(r.returncode, 1, r.stdout)


class ShipTest(NextCase):
    def ship_ready(self):
        self.plan_session()
        self.build_session()
        self.resume()

    def test_review_must_fix_runs_a_correction_then_reviews_its_files(self):
        self.correction_re_review()

    def test_the_first_push_and_the_draft_pr_come_before_any_review_spawn(self):
        # 5.0: the first push and the draft PR come before any review.
        self.draft_pr()
        state = self.state()
        self.assertFalse([b for b in state["briefs"] if b["worker"] in (
            "code-reviewer", "review-judge", "security-reviewer",
            "security-reviewer-sensitive")])
        pushed = state["marks"]["pushed"]["seq"]
        published = state["phase6"]["body"]["published_seq"]
        log = [json.loads(ln) for ln in (self.tmp / "gh.log").read_text().splitlines()]
        self.assertTrue(any(e["args"][:3] == ["pr", "create", "--draft"] for e in log))
        _, jobs = self.reviewers()  # the review is spawned only now, on the draft
        first = min(b["seq"] for b in self.state()["briefs"]
                    if b["worker"] == "code-reviewer")
        self.assertLess(pushed, first)
        self.assertLess(published, first)
        self.assertEqual(self.sets(*jobs[0])["scope"], "first")

    def test_next_records_the_panel_s_parallel_results_in_spawn_order(self):
        self.draft_pr()
        self.verifier_first()
        out = self.next(0)
        jobs = self.spawned(out)
        self.assertEqual(len(jobs), 4, out)
        (self.dir / "SECURITY_REVIEW.md").write_text(SECURITY_REVIEW.format(tree=self.tree()))
        for w, n in jobs:  # every result written, none recorded by hand
            if w == "code-reviewer":
                (self.dir / "review" / "pass-1" / f"{self.sets(w, n)['reviewer']}.md"
                 ).write_text(r_report("none"))
                self.write_return(w, n, {"next": "REVIEWED", "findings": "0",
                                         "leads": "0"})
            else:
                self.write_return(w, n, {"next": "CLEAN", "must_fix": "0",
                                         "pre_existing": "0"})
        out = self.next(0)
        self.assertEqual([line.split(":")[0] for line in out["RECORDED"]],
                         [f"{w}-{n}" for w, n in jobs])
        self.assertEqual([w for w, _ in self.spawned(out)], ["review-judge"])
        # The judge's brief comes with the panel's findings merged.
        findings = (self.dir / "review" / "pass-1" / "findings.md").read_text()
        self.assertIn("Reviewers finished: R1, R2, R3 (3/3)", findings)
        self.assertIn("No findings:", findings)
        state = self.state()
        seqs = [e["seq"] for e in state["log"][-4:]]
        self.assertEqual(seqs, sorted(set(seqs)))  # each its own event
        judge = state["briefs"][-1]
        self.assertGreater(judge["seq"], seqs[-1])

    def test_a_judge_result_with_no_judgment_is_refused(self):
        self.draft_pr()
        _, jobs = self.reviewers(None, 3)
        for w, n in jobs:
            (self.dir / "review" / "pass-1" / f"{self.sets(w, n)['reviewer']}.md").write_text(
                r_report("none"))
            self.answer(w, n, "REVIEWED", findings="0", leads="0")
        _, jobs = self.expect("review-judge")
        judge = next(j for j in jobs if self.mode(*j) == "consolidate")
        # The judge wrote CODE_REVIEW.md by hand, with no JUDGMENT.md.
        (self.dir / "CODE_REVIEW.md").write_text(CLEAN_REVIEW.format(tree=self.tree()))
        path = self.dir / "returns" / f"review-judge-{judge[1]}.json"
        path.write_text(json.dumps({"worker": "review-judge", "status": "ok", "next": "CLEAN",
                                    "must_fix_open": "0", "revote": "0", "spec_problems": "0"}))
        out = self.next(refused_ok=True)
        self.assertTrue(any("refused" in ln for ln in out["RECORDED"]), json.dumps(out))
        brief = (self.dir / "briefs" / f"review-judge-{self.spawned(out)[0][1]}.md").read_text()
        self.assertIn("JUDGMENT.md: write your calls there", brief)

    def correction_re_review(self):
        """Pass 1 (on the draft PR) finds must-fix C1; its one-line correction
        runs on top of the commit, then pass 2 is spawned: the whole panel on the
        uncommitted correction, and a security reviewer focused on it."""
        self.draft_pr()
        out, jobs = self.reviewers()
        for w, n in jobs:
            (self.dir / "review" / "pass-1" / f"{self.sets(w, n)['reviewer']}.md").write_text(
                r_report("- null due date crashes sort"))
            self.answer(w, n, "REVIEWED", findings="1", leads="0")
        (self.dir / "CODE_REVIEW.md").write_text(OPEN_REVIEW.format(tree=self.tree()))
        (self.dir / "review" / "pass-1" / "corrections.md").write_text(
            "# Required changes\n1. C1: guard the sort in src/sort.ts against a "
            "missing due date\n")
        _, jobs = self.expect("review-judge", "MUST_FIX", must_fix_open="1", revote="0")
        self.assertEqual(self.sets(*jobs[0])["tree"],  # the tree the panel reviewed
                         self.state()["phase6"]["passes"][0]["tree"])
        out, jobs = self.expect("coder")
        self.assertEqual(self.sets(*jobs[0])["corrections_file"],
                         f"{self.dir}/review/pass-1/corrections.md")
        self.assertIn("spent `pass-1`", out["BUDGET"])
        (self.worktree / "sort.ts").write_text("export const sort = 1;\n")
        self.answer(*jobs[0], "BUILT", blocked="0", test_changes="none")
        self.quality_gate()  # a script, no worker
        out, jobs = self.reviewers()  # a one-line correction: still the whole panel
        self.assertEqual(self.sets(*jobs[0])["scope"], "after-commit")
        self.assertEqual(self.sets(*self.verifier_job)["mode"], "re-check")
        self.assertNotIn("files", self.sets(*jobs[0]))
        self.assertEqual(self.sets(*self.security_job)["focus"],
                         "the uncommitted correction (the working tree against HEAD)")
        self.assertEqual(self.state()["phase6"]["review_pass"], 2)

    def to_body(self, extra=(), first=(), answers=(), started=False):
        """Run S3 to the draft PR's first body, before any review: returns
        (sha, url, out, body). `answers`: the open-the-PR gate's, when it is on.
        `started`: S3 has started already (the test ran S1 and S2 itself)."""
        if not started:
            self.ship_ready()
        self.lint()
        if answers:
            out = self.next(5)
            self.assertIn("pr gate", out["QUESTION"])
            for choice in answers:
                self.after(out, choice)
        out = self.next(0)
        self.assertIn("commit: run", out["ACTION"])
        r = self.autodev("commit", "--message", "feat(todos): add due dates", "--dir",
                         self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        sha = self.state()["phase6"]["verified_sha"]
        out = self.next(0)
        self.assertIn("push -u origin HEAD", out["ACTION"])
        self.sh("git", "push", "-q", "-u", "origin", "HEAD", cwd=self.worktree)
        self.after(out)
        url = "https://github.com/acme/app"
        self.script_gh(list(first) + GH_OK + [
            {"args": ["repo", "view", "--json", "url"], "stdout": json.dumps({"url": url})},
            {"args": ["pr", "list"], "stdout": "[]"},
            {"args": ["pr", "create"], "stdout": f"{url}/pull/12\n"},
            {"args": ["pr", "edit", "12"], "stdout": ""},
            {"args": ["pr", "view", "12", "--json", "number,url,body"],
             "stdout": json.dumps({"number": 12, "url": f"{url}/pull/12",
                                   "body": f"Checked at commit {sha}"})},
            {"args": ["pr", "view", "12", "--json", "state"], "stdout": '{"state": "MERGED"}'},
            {"args": ["pr", "view", "12", "--json"],  # the main gate's summary
             "stdout": json.dumps({"url": f"{url}/pull/12", "isDraft": False,
                                   "state": "OPEN", "headRefOid": sha})},
            {"args": ["repo", "view", "--json",
                      "squashMergeAllowed,mergeCommitAllowed,rebaseMergeAllowed"],
             "stdout": json.dumps({"squashMergeAllowed": True})},
            {"args": ["pr", "merge"], "stdout": ""},
            *extra,
        ])
        out = self.next(0)
        body = self.dir / "pr-body.md"
        self.assertIn(str(body), out["ACTION"])
        text = body.read_text()
        self.assertIn(f"Checked at commit {sha}", text)
        self.assertIn("Not reviewed yet", text)  # the draft opens before any review
        self.assertIn("Not verified yet", text)  # and before the verifier
        self.assertIn(f"{url}/blob/{sha}/src/due.acceptance.test.ts", text)
        self.assertNotIn(str(self.worktree), text)
        return sha, url, out, body

    def draft_pr(self, extra=(), first=(), answers=(), started=False):
        """Run S3 to the published draft PR, before any review; returns (sha, url)."""
        sha, url, out, body = self.to_body(extra, first, answers, started)
        text = body.read_text()
        r = self.autodev("pr", "publish", "--dir", self.dir)
        self.assertEqual(r.returncode, 1)  # the Summary is not written yet
        self.assertIn("WRITE", r.stderr)
        body.write_text(re.sub(r"<!-- WRITE: .*?-->", "Todos can carry a due date.", text))
        self.after(out)
        self.assertEqual(self.state()["phase6"]["pr"], 12)
        return sha, url

    def refresh_body(self):
        """`next` asks to publish the refreshed description: publish it."""
        out = self.next(0)
        self.assertIn("pr publish", out["ACTION"], json.dumps(out, indent=2))
        gh = json.loads((self.tmp / "gh.json").read_text())  # GitHub holds what was sent
        sha = self.state()["phase6"]["verified_sha"]
        url = "https://github.com/acme/app"
        self.script_gh([{"args": ["pr", "view", "12", "--json", "body"],
                         "stdout": json.dumps({"body": self.published()})},
                        {"args": ["pr", "view", "12", "--json", "number,url,body"],
                         "stdout": json.dumps({"number": 12, "url": f"{url}/pull/12",
                                               "body": f"Checked at commit {sha}"})}] + gh)
        r = self.autodev("pr", "publish", "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def reviewed_pr(self, extra=(), first=()):
        """The draft PR, then a clean review on it and its refreshed description."""
        sha, url = self.draft_pr(extra, first)
        self.review_clean()
        self.refresh_body()
        self.assertNotIn("Not reviewed yet", (self.dir / "pr-body.md").read_text())
        return sha, url

    def mark_ready(self, *answers):
        """Answer the ready-for-review gate (and `answers`, its triage
        questions), publish the description with the answers, and mark the PR
        ready."""
        out = self.next(5)
        self.assertIn("ready gate", out["QUESTION"])
        for choice in (*answers, "Mark ready for review"):
            self.after(out, choice)
        self.refresh_body()  # the description gets the gate's answers
        out = self.next(0)
        self.assertIn("gh pr ready 12", out["ACTION"])
        self.after(out)

    def open_pr(self, extra=(), first=()):
        """Run S3 to the reviewed PR marked ready for review; returns (sha, url)."""
        sha, url = self.reviewed_pr(extra, first)
        self.mark_ready()
        return sha, url

    def published(self):
        """The description `pr create` or `pr edit` was last given."""
        log = [json.loads(ln) for ln in (self.tmp / "gh.log").read_text().splitlines()]
        sent = [e["files"] for e in log if e["args"][:2] in (["pr", "create"],
                                                              ["pr", "edit"])]
        return "".join(sent[-1].values())

    MARK = "<!-- auto-dev: the sections you write start here; keep this line -->"

    def slots(self, fill="Todos can carry a due date."):
        """pr-write.md split at its mark: (sources, sections), the WRITE lines in
        the sections replaced with `fill` when given."""
        sources, mine = (self.dir / "pr-write.md").read_text().split(self.MARK)
        if fill is not None:
            mine = re.sub(r"<!-- WRITE: .*?-->", fill, mine)
        return sources, mine

    def write_slots(self, sources, mine):
        (self.dir / "pr-write.md").write_text(sources + self.MARK + mine)

    def test_the_orchestrator_writes_only_the_sections_in_pr_write_md(self):
        sha, _, out, body = self.to_body()
        slots = self.dir / "pr-write.md"
        self.assertIn(str(slots), out["ACTION"])
        generated = body.read_text()
        sources, mine = self.slots(fill=None)
        self.assertIn("## Summary\n<!-- WRITE:", mine)
        self.assertIn("## Assumptions\n<!-- WRITE:", mine)
        self.assertNotIn("## Acceptance conditions", mine)  # the script's own sections
        self.assertNotIn("<!-- auto-dev -->", mine)  # the closing lines stay put
        self.assertNotIn("## Quality gate", mine)
        spec = (self.dir / "PLAN.md").read_text()
        context = spec.split("## Context", 1)[1].split("\n## ", 1)[0].strip()
        self.assertIn("### Source: PLAN.md Context\n> " + context.splitlines()[0], sources)
        self.assertIn("### Source: the task\n> ", sources)
        self.assertIn("### Source: this description's Quality gate\n> ", sources)
        self.assertIn("> - A todo can carry a due date", sources)  # a checked requirement
        self.assertNotIn("\n## ", sources)  # quoted: no heading of theirs counts
        r = self.autodev("pr", "publish", "--dir", self.dir)
        self.assertEqual(r.returncode, 1)
        self.assertIn("pr-write.md still holds", r.stderr)
        self.write_slots(*self.slots())
        self.after(out)
        self.assertEqual(self.state()["phase6"]["pr"], 12)
        self.assertEqual(body.read_text(), generated)  # spliced in memory only
        sent = self.published()
        self.assertIn("## Summary\nTodos can carry a due date.", sent)
        self.assertIn(f"Checked at commit {sha}", sent)
        self.assertNotIn("WRITE", sent)
        self.assertNotIn("### Source:", sent)  # the sources stay out
        self.assertTrue(sent.endswith("Generated with [Claude Code]"
                                      "(https://claude.com/claude-code)\n<!-- auto-dev -->\n"))

    def test_a_section_written_in_pr_body_md_stands(self):
        _, _, out, body = self.to_body()
        body.write_text(body.read_text().replace(
            "## Summary\n<!-- WRITE:", "## Summary\nBy hand.\n<!-- gone:", 1).replace(
            "<!-- gone: what changed and why, 2–4 sentences, drawn from PLAN.md's "
            "Context -->", "", 1))
        self.write_slots(*self.slots("From the slots."))
        self.after(out)
        sent = self.published()
        self.assertIn("## Summary\nBy hand.", sent)
        self.assertNotIn("## Summary\nFrom the slots.", sent)
        self.assertIn("## Assumptions\nFrom the slots.", sent)

    def test_a_heading_in_the_task_text_never_reaches_the_description(self):
        _, _, out, _ = self.to_body()
        state = self.state()
        state["task"]["text"] = ("Ticket body\n## Summary\nThe ticket's own summary\n"
                                 "## Assumptions\nticket notes")
        self.write_state(state)
        r = self.lib("pr-body", "--dir", self.dir)  # generated again from the task
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("pr-write.md", r.stdout)
        self.write_slots(*self.slots())
        self.after(out)
        sent = self.published()
        self.assertIn("## Summary\nTodos can carry a due date.", sent)
        self.assertNotIn("The ticket's own summary", sent)
        self.assertNotIn("ticket notes", sent)

    def test_a_stray_or_renamed_heading_or_a_lost_mark_is_refused(self):
        self.to_body()
        sources, mine = self.slots()

        def publish(text):
            (self.dir / "pr-write.md").write_text(text)
            r = self.autodev("pr", "publish", "--dir", self.dir)
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            return r.stderr
        stray = mine.replace("Todos can carry a due date.", "Todos can carry a due date."
                             "\n## Assumptions\nextra", 1)
        self.assertIn("start no line of an answer with `## `",
                      publish(sources + self.MARK + stray))
        renamed = mine.replace("## Assumptions", "## assumptions")
        err = publish(sources + self.MARK + renamed)
        self.assertIn("`## Assumptions` is not written", err)
        self.assertIn("`## assumptions` section(s) where it was written with 0", err)
        self.assertIn("has lost its line", publish(sources + mine))
        # A heading of the description that pr-write.md was not written with.
        review = mine.replace("Todos can carry a due date.", "Line one.\n## Review\nlost", 1)
        self.assertIn("`## Review` section(s) where it was written with 0",
                      publish(sources + self.MARK + review))
        self.assertIn("text between its line", publish(sources + self.MARK + "\nloose\n"
                                                        + mine))
        # The write step `next` goes back to says what was refused.
        self.assertIn("refused the last one", self.next(0)["ACTION"])
        self.assertEqual(self.state()["phase6"]["publish_attempt"]["result"], "unwritten")

    def test_a_body_with_no_pr_write_md_is_named_as_before(self):
        _, _, _, body = self.to_body()
        (self.dir / "pr-write.md").unlink()  # as a description generated before 4.17
        out = self.next(0)
        self.assertIn(f"fill in the PR body {body}", out["ACTION"])
        self.assertNotIn("pr-write.md", out["ACTION"])

    def test_no_budget_for_a_review_fix_goes_to_the_ready_gate(self):
        self.draft_pr()
        state = self.state()
        state["budget"]["remaining"] = 0
        self.write_state(state)
        _, jobs = self.reviewers()
        for w, n in jobs:
            (self.dir / "review" / "pass-1" / f"{self.sets(w, n)['reviewer']}.md").write_text(
                r_report("- null due date crashes sort"))
            self.answer(w, n, "REVIEWED", findings="1", leads="0")
        (self.dir / "CODE_REVIEW.md").write_text(OPEN_REVIEW.format(tree=self.tree()))
        (self.dir / "review" / "pass-1" / "corrections.md").write_text(
            "# Required changes\n1. C1: guard the sort in src/sort.ts against a "
            "missing due date\n")
        self.expect("review-judge", "MUST_FIX", must_fix_open="1", revote="0")
        self.refresh_body()  # the description names the open finding
        out = self.next(5)
        self.assertIn("ready gate", out["QUESTION"])
        summary = " ".join(out["SUMMARY"])
        self.assertIn("Budget exhausted", summary)
        self.assertIn("No round was left to correct what is still open", summary)

    def test_no_round_left_inside_a_review_correction_goes_to_the_ready_gate(self):
        self.draft_pr()
        state = self.state()
        state["budget"]["remaining"] = 1  # the review correction's round, no more
        self.write_state(state)
        _, jobs = self.reviewers()
        for w, n in jobs:
            (self.dir / "review" / "pass-1" / f"{self.sets(w, n)['reviewer']}.md").write_text(
                r_report("- null due date crashes sort"))
            self.answer(w, n, "REVIEWED", findings="1", leads="0")
        (self.dir / "CODE_REVIEW.md").write_text(OPEN_REVIEW.format(tree=self.tree()))
        (self.dir / "review" / "pass-1" / "corrections.md").write_text(
            "# Required changes\n1. C1: guard the sort in src/sort.ts\n")
        self.expect("review-judge", "MUST_FIX", must_fix_open="1", revote="0")
        _, jobs = self.expect("coder")
        (self.worktree / "sort.ts").write_text("export const sort = 1;\n")
        self.answer(*jobs[0], "BUILT", blocked="0", test_changes="none")
        self.quality_gate()
        # Pass 2 on the correction: the verifier still finds an item open, and
        # no round is left for another correction: not a stop, before the PR is
        # ready. It goes to the ready-for-review gate.
        self.review_text = CLEAN_REVIEW
        self.panel(verifier="CORRECT")
        p6 = self.state()["phase6"]
        self.assertEqual(p6["passes"][-1]["scope"], "after-commit")
        self.assertIn("commit: run", self.next(0)["ACTION"])
        self.assertTrue(self.state()["phase6"]["exhausted"]["open"])

    def test_an_edit_at_the_ready_gate_is_re_checked_and_the_gate_asked_again(self):
        self.test_no_budget_for_a_review_fix_goes_to_the_ready_gate()
        (self.worktree / "due.ts").write_text("export const due = 2;\n")  # outside edit
        self.quality_gate()  # the gate's checks found it stale: it runs again
        _, jobs = self.reviewers()
        pass_dir = self.dir / "review" / f"pass-{self.state()['phase6']['review_pass']}"
        self.assertEqual(self.sets(*jobs[0])["scope"], "after-commit")
        for w, n in jobs:
            (pass_dir / f"{self.sets(w, n)['reviewer']}.md").write_text(
                r_report("- null due date crashes sort"))
            self.answer(w, n, "REVIEWED", findings="1", leads="0")
        (self.dir / "CODE_REVIEW.md").write_text(OPEN_REVIEW.format(tree=self.tree()))
        (pass_dir / "corrections.md").write_text("# Required changes\n1. C1: guard\n")
        self.expect("review-judge", "MUST_FIX", must_fix_open="1", revote="0")
        self.assertIn("commit: run", self.next(0)["ACTION"])  # on top, no round left
        r = self.autodev("commit", "--message", "chore: due", "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        out = self.next(0)
        self.assertIn("push", out["ACTION"])
        self.sh("git", "push", "-q", "origin", "HEAD", cwd=self.worktree)
        self.after(out)
        self.refresh_body()
        out = self.next(5)  # the gate again, still naming the open finding
        self.assertIn("ready gate", out["QUESTION"])
        self.assertIn("Budget exhausted", " ".join(out["SUMMARY"]))

    def test_a_ticket_already_in_progress_still_moves_to_in_review(self):
        self.open_pr()
        state = self.state()
        state["task"]["ticket"] = "TODO-7"
        state["gates"].append({"gate": "jira", "choice": "already", "reason": None,
                               "at": "2026-01-01T00:00:00Z", "seq": 1})
        self.write_state(state)
        out = self.next(0)
        self.assertIn("move Jira ticket TODO-7 to `In Review`", out["ACTION"])
        state["gates"][-1]["choice"] = "leave"
        self.write_state(state)
        self.assertNotIn("move Jira ticket", self.next(0)["ACTION"])

    def test_a_ticket_already_in_progress_still_moves_to_done_after_the_merge(self):
        sha, _ = self.open_pr()
        state = self.state()
        state["task"]["ticket"] = "TODO-7"
        state["gates"].append({"gate": "jira", "choice": "already", "reason": None,
                               "at": "2026-01-01T00:00:00Z", "seq": 1})
        self.write_state(state)
        out = self.next(0)
        self.assertIn("move Jira ticket TODO-7 to `In Review`", out["ACTION"])
        self.after(out)
        self.expect("triager", "TRIAGED", blockers="0", acceptance_checks="0",
                    triage_file="none", checks_file="none")
        self.after(self.next(5), "Merge PR to main")
        r = self.autodev("merge-pr", "--pr", "12", "--sha", sha, "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.next(0)
        self.autodev("mark", "main-ci", "--value", "green", "--dir", self.dir)
        out = self.next(0)
        self.assertIn("move Jira ticket TODO-7 to `Done`", out["ACTION"])
        self.assertIn("mark jira-done", out["AFTER"][0])

    def test_ship_session_runs_to_the_merge(self):
        sha, _ = self.open_pr()
        self.expect("triager", "TRIAGED", blockers="0", acceptance_checks="0",
                    triage_file="none", checks_file="none")
        out = self.next(5)
        self.assertIn("main gate", out["QUESTION"])
        self.after(out, "Merge PR to main")
        out = self.next(0)
        self.assertIn(f"merge-pr --pr 12 --sha {sha}", out["ACTION"])
        r = self.autodev("merge-pr", "--pr", "12", "--sha", sha, "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        out = self.next(0)
        self.assertIn("mark main-ci", out["AFTER"][0])
        self.assertIn("gh pr view 12 --json mergeCommit", out["ACTION"])  # names the PR
        self.autodev("mark", "main-ci", "--value", "green", "--dir", self.dir)
        out = self.next(0)
        self.assertIn("final report", out["ACTION"])
        self.after(out)
        out = self.next(5)
        self.after(out, "Keep it")
        out = self.next(3)
        self.assertEqual(self.state()["phases"]["6"]["status"], "done")
        log = [json.loads(ln)["args"] for ln in
               (self.tmp / "gh.log").read_text().splitlines()]
        self.assertEqual(sum(1 for a in log if a[:2] == ["pr", "create"]), 1)

    def test_a_worktree_the_user_made_is_never_offered_for_removal(self):
        sha, _ = self.open_pr()
        state = self.state()
        state["repo"]["adopted"] = True  # as `init` writes it in the user's worktree
        self.write_state(state)
        self.expect("triager", "TRIAGED", blockers="0", acceptance_checks="0",
                    triage_file="none", checks_file="none")
        self.after(self.next(5), "Merge PR to main")
        self.next(0)
        self.autodev("merge-pr", "--pr", "12", "--sha", sha, "--dir", self.dir)
        self.next(0)
        self.autodev("mark", "main-ci", "--value", "green", "--dir", self.dir)
        self.after(self.next(0))  # the final report
        out = self.next(3)  # done: no worktree question
        self.assertNotIn("cleanup-worktree", out["ACTION"])
        self.assertNotIn("cleanup", [g["gate"] for g in self.state()["gates"]])
        self.assertEqual(self.state()["phases"]["6"]["status"], "done")

    def test_a_high_risk_pass_runs_the_panel_after_the_verifier(self):
        # The verifier's mutants are planted in the worktree: no reviewer may
        # read the tree while they are.
        self.draft_pr()
        out = self.next(0)
        self.assertEqual([w for w, _ in self.spawned(out)], ["verifier"])
        waiting = self.next(0)  # not returned yet: waited for, not spawned again
        self.assertTrue(waiting["ACTION"].startswith("wait"), waiting)
        self.assertIn(f"verifier #{self.spawned(out)[0][1]}", waiting["ACTION"])
        self.assertNotIn("BRIEF", waiting)
        self.answer(*self.spawned(out)[0], None, status="failed")
        again = self.spawned(self.next(0))
        self.assertEqual([w for w, _ in again], ["verifier"])  # still alone
        self.verifier_answer(again[0])
        out = self.next(0)
        self.assertEqual(sorted({w for w, _ in self.spawned(out)}),
                         ["code-reviewer", "security-reviewer-sensitive"])
        sec = next(j for j in self.spawned(out) if j[0].startswith("security"))
        # The panel of this pass has written nothing yet: no stale leads.
        self.assertEqual(self.sets(*sec)["leads"], "none")

    def test_a_security_must_fix_is_verified_then_corrected(self):
        self.draft_pr()
        jobs = self.panel(security=(SECURITY_MUST_FIX, "MUST_FIX", "1", "0"))
        self.assertEqual(len(jobs), 1)  # spawned with the consolidating judge
        self.assertEqual(self.sets(*jobs[0]), {})
        self.assertIn("mode: security-verify",
                      (self.dir / "briefs" / f"review-judge-{jobs[0][1]}.md").read_text())
        (self.dir / "review" / "security-corrections.md").write_text(
            "# Required changes\n1. S3: in src/due.ts, check that the caller owns the todo "
            "before its date is stored\n")
        self.answer(*jobs[0], "VERIFIED", must_fix_open="1", revote="0")
        out, jobs = self.expect("coder")
        self.assertEqual(self.sets(*jobs[0])["corrections_file"],
                         f"{self.dir}/review/security-corrections.md")
        self.assertIn("spent `pass-1`", out["BUDGET"])  # one id per pass

    def test_panel_and_security_findings_share_one_correction(self):
        self.draft_pr()
        remaining = self.state()["budget"]["remaining"]
        corrections = ("# Required changes\n1. C1: guard the sort in src/sort.ts against "
                       "a missing due date\n")
        jobs = self.panel(OPEN_REVIEW, "MUST_FIX", corrections=corrections,
                          security=(SECURITY_MUST_FIX, "MUST_FIX", "1", "0"))
        (self.dir / "review" / "security-corrections.md").write_text(
            "# Required changes\n1. S3: in src/due.ts, check that the caller owns the todo "
            "before its date is stored\n")
        self.answer(*jobs[0], "VERIFIED", must_fix_open="1", revote="0")
        out, jobs = self.expect("coder")
        self.assertEqual(self.sets(*jobs[0])["corrections_file"],
                         f"{self.dir}/review/pass-1/corrections.md and "
                         f"{self.dir}/review/security-corrections.md")
        self.assertIn("spent `pass-1`", out["BUDGET"])
        self.assertEqual(self.state()["budget"]["remaining"], remaining - 1)

    def test_a_lead_the_security_review_has_not_seen_gets_a_security_run(self):
        self.draft_pr()
        lead = ("- `src/due.ts:9` — the owner is not checked (raised by R2) → passed to "
                "the security review")
        covered = "- `src/due.ts:3` — dates are not escaped (raised by R1) → covered by S2"
        review = CLEAN_REVIEW.replace("## Security leads\nnone",
                                      f"## Security leads\n{lead}\n{covered}")
        self.assertEqual(self.panel(review), [])
        _, jobs = self.expect("security-reviewer-sensitive")
        self.assertEqual(self.sets(*jobs[0])["leads"], lead)
        self.assertEqual(self.state()["phase6"]["security_run"], 2)
        self.answer(*jobs[0], "CLEAN", must_fix="0", pre_existing="0")
        self.lint()
        self.spec_eval()
        self.refresh_body()
        self.assertIn("ready gate", self.next(5)["QUESTION"])  # seen now: no third run

    def test_a_pass_started_without_the_security_review_runs_it_before_the_judge(self):
        self.draft_pr()  # as a run started before 4.4.0 left it
        _, jobs = self.reviewers()
        state = self.state()
        sec = [e for e in state["log"] if e["worker"].startswith("security-reviewer")]
        state["log"] = [e for e in state["log"] if e not in sec]
        state["briefs"] = [b for b in state["briefs"]
                           if not b["worker"].startswith("security-reviewer")]
        self.write_state(state)
        for w, n in jobs:
            (self.dir / "review" / "pass-1" / f"{self.sets(w, n)['reviewer']}.md"
             ).write_text(r_report("none"))
            self.answer(w, n, "REVIEWED", findings="0", leads="0")
        (self.dir / "CODE_REVIEW.md").write_text(CLEAN_REVIEW.format(tree=self.tree()))
        _, jobs = self.expect("security-reviewer-sensitive")
        self.assertEqual(self.sets(*jobs[0])["leads"], "none")

    def test_with_no_round_left_open_findings_go_to_the_gate_after_the_leads_run(self):
        self.draft_pr()
        state = self.state()
        state["budget"]["remaining"] = 0
        self.write_state(state)
        lead = ("- `src/due.ts:9` — the owner is not checked (raised by R2) → passed to "
                "the security review")
        review = OPEN_REVIEW.replace("## Security leads\nnone", f"## Security leads\n{lead}")
        jobs = self.panel(review, "MUST_FIX",
                          corrections="# Required changes\n1. C1: guard the sort in "
                                      "src/sort.ts against a missing due date\n",
                          security=(SECURITY_MUST_FIX, "MUST_FIX", "1", "0"))
        (self.dir / "review" / "security-corrections.md").write_text(
            "# Required changes\n1. S3: in src/due.ts, check that the caller owns the todo "
            "before its date is stored\n")
        self.answer(*jobs[0], "VERIFIED", must_fix_open="1", revote="0")
        # No round for the correction, but the lead still gets its security run:
        # the gate can only name what someone checked.
        _, jobs = self.expect("security-reviewer-sensitive")
        self.assertEqual(self.sets(*jobs[0])["leads"], lead)
        (self.dir / "SECURITY_REVIEW.md").write_text(SECURITY_MUST_FIX.format(
            tree=self.tree()))
        self.answer(*jobs[0], "MUST_FIX", must_fix="1", pre_existing="0")
        self.expect("review-judge", "VERIFIED", must_fix_open="1", revote="0")
        self.lint()
        self.spec_eval()
        self.refresh_body()
        out = self.next(5)
        self.assertIn("ready gate", out["QUESTION"])
        self.assertIn("Budget exhausted", " ".join(out["SUMMARY"]))

    def test_a_wrapped_lead_is_sent_whole_and_a_placeholder_is_not_a_lead(self):
        self.draft_pr()
        leads = ("- `src/due.ts:9` — the owner is not checked when a todo's date\n"
                 "  is moved (raised by R2) → passed to the security review\n"
                 "- `path:line` — <lead> (raised by R<k>) → passed to the security review\n"
                 "- `src/due.ts:3` — dates are not escaped (raised by R1) → covered by S2")
        refuted = SECURITY_REVIEW.replace("| Medium | confirmed |", "| Medium | refuted |")
        self.panel(CLEAN_REVIEW.replace("## Security leads\nnone",
                                        f"## Security leads\n{leads}"),
                   security=(refuted, "CLEAN", "0", "0"))
        _, jobs = self.expect("security-reviewer-sensitive")
        sent = self.sets(*jobs[0])["leads"]
        self.assertIn("`src/due.ts:9` — the owner is not checked when a todo's date", sent)
        self.assertIn("is moved (raised by R2)", sent)
        self.assertIn("covered by S2", sent)  # S2 was refuted: the lead stands
        self.assertNotIn("<lead>", sent)

    def test_a_run_on_leads_alone_is_focused_on_them_and_so_is_its_re_spawn(self):
        self.draft_pr()
        lead = ("- `src/due.ts:9` — the owner is not checked (raised by R2) → passed to "
                "the security review")
        self.panel(CLEAN_REVIEW.replace("## Security leads\nnone",
                                        f"## Security leads\n{lead}"))
        _, jobs = self.expect("security-reviewer-sensitive")
        sets = self.sets(*jobs[0])
        # The pass's first run covered the whole change: this one skips
        # /security-review and follows the leads.
        self.assertIn("leads", sets["focus"])
        self.assertNotEqual(sets["focus"], "none")
        self.answer(*jobs[0], "", status="failed")
        _, again = self.expect("security-reviewer-sensitive", "", status="failed")
        self.assertEqual(self.sets(*again[0])["focus"], sets["focus"])
        self.assertEqual(self.sets(*again[0])["leads"], sets["leads"])

    def test_the_judge_s_two_modes_fail_apart(self):
        self.draft_pr()
        _, jobs = self.reviewers(security=(SECURITY_MUST_FIX, "MUST_FIX", "1", "0"))
        for w, n in jobs:
            (self.dir / "review" / "pass-1" / f"{self.sets(w, n)['reviewer']}.md"
             ).write_text(r_report("none"))
            self.answer(w, n, "REVIEWED", findings="0", leads="0")
        (self.dir / "CODE_REVIEW.md").write_text(CLEAN_REVIEW.format(tree=self.tree()))
        _, jobs = self.expect("review-judge")
        verify = next(j for j in jobs if self.mode(*j) == "security-verify")
        consolidate = next(j for j in jobs if j != verify)
        self.answer(*verify, "", status="blocked")
        self.answer(*consolidate, "CLEAN", must_fix_open="0", revote="0")
        _, jobs = self.expect("review-judge")
        brief = (self.dir / "briefs" / f"review-judge-{jobs[0][1]}.md").read_text()
        self.assertIn("mode: security-verify", brief)
        self.assertIn("returned `blocked`, and the run spawned you again once", brief)
        self.answer(*jobs[0], "", status="blocked")
        out = self.next(4)
        self.assertIn("stopped on purpose twice running", " ".join(out["REPORT"]))

    def test_a_security_reviewer_that_fails_beside_the_panel_is_respawned_once(self):
        self.draft_pr()
        self.verifier_first()
        out = self.next(0)
        jobs = self.spawned(out)
        sec = next(j for j in jobs if j[0].startswith("security-reviewer"))
        self.answer(*sec, "", status="failed")
        for w, n in jobs:  # the panel's results come after the failure
            if w == "code-reviewer":
                (self.dir / "review" / "pass-1" / f"{self.sets(w, n)['reviewer']}.md"
                 ).write_text(r_report("none"))
                self.answer(w, n, "REVIEWED", findings="0", leads="0")
        _, again = self.expect("security-reviewer-sensitive", "", status="failed")
        self.assertEqual(len(again), 1)
        self.assertEqual(self.sets(*again[0])["leads"], "none")
        out = self.next(4)
        self.assertIn("failed twice running", " ".join(out["REPORT"]))

    def test_a_security_reviewer_blocked_beside_the_panel_is_told_why(self):
        self.draft_pr()
        self.verifier_first()
        jobs = self.spawned(self.next(0))
        sec = next(j for j in jobs if j[0].startswith("security-reviewer"))
        self.answer(*sec, "", status="blocked")
        for w, n in jobs:
            if w == "code-reviewer":
                (self.dir / "review" / "pass-1" / f"{self.sets(w, n)['reviewer']}.md"
                 ).write_text(r_report("none"))
                self.answer(w, n, "REVIEWED", findings="0", leads="0")
        _, again = self.expect("security-reviewer-sensitive")
        brief = (self.dir / "briefs" / f"{again[0][0]}-{again[0][1]}.md").read_text()
        self.assertIn("returned `blocked`, and the run spawned you again once", brief)

    def test_an_acceptance_check_finding_goes_to_the_tester(self):
        self.draft_pr()
        self.panel(CHECK_REVIEW, "MUST_FIX", corrections="# Required changes\nNone.\n")
        out, jobs = self.expect("acceptance-tester")
        sets = self.sets(*jobs[0])
        self.assertTrue(sets["scope"].startswith("ONLY conditions 1, S1:"), sets)
        self.assertIn("CODE_REVIEW.md, must-fix finding(s) C1", sets["report"])
        self.assertIn("spent `pass-1`", out["BUDGET"])
        (self.worktree / "src" / "due.acceptance.test.ts").write_text("test, repaired")
        self.answer(*jobs[0], "REPAIRED", checks="1", ambiguous="none")
        self.quality_gate()
        out = self.next(0)  # never the coder: nothing else is open; the pass
        self.assertIn("auto-dev:verifier", out["AGENT"])
        self.assertNotIn("auto-dev:coder", out["AGENT"])

    def test_a_check_repaired_after_the_commit_is_reviewed_and_verified_as_head(self):
        # The repair is a tests commit on top of the verified commit, and the
        # tree is clean: the panel reviews everything since the verified
        # commit, and `commit` verifies HEAD instead of finding nothing.
        self.draft_pr()
        verified = self.state()["phase6"]["verified_sha"]
        self.panel(CHECK_REVIEW, "MUST_FIX", corrections="# Required changes\nNone.\n")
        _, jobs = self.expect("acceptance-tester")
        (self.worktree / "src" / "due.acceptance.test.ts").write_text("test, repaired")
        self.answer(*jobs[0], "REPAIRED", checks="1", ambiguous="none")
        self.quality_gate()  # the gate runs on the change
        head = self.sh("git", "rev-parse", "HEAD", cwd=self.worktree).strip()
        self.assertEqual(self.state()["tests_commits"][-1]["sha"], head)
        self.assertNotEqual(head, verified)
        out = self.next(0)  # the pass: the verifier and the review, since `verified`
        self.assertIn("auto-dev:verifier", out["AGENT"])
        p6 = self.state()["phase6"]
        self.assertEqual(p6.get("unverified_commit"), head)
        self.assertEqual(p6["passes"][-1]["scope"], "outside")
        self.assertEqual(p6["passes"][-1]["since"], verified)
        self.assertIn("src/due.acceptance.test.ts", p6["passes"][-1]["files"])

    def triage_files(self):
        triage = self.dir / "triage"
        (triage / "human-1.md").write_text(
            "# Required changes\n1. In src/sort.ts, keep todos with no date at the end\n")
        (triage / "human-1-checks.md").write_text(
            "# Required changes\n1. The sort check should cover two todos on one day\n")
        return triage / "human-1.md", triage / "human-1-checks.md"

    def test_a_pr_comment_that_says_the_spec_is_wrong_stops_the_run(self):
        self.open_pr()
        _, jobs = self.expect("triager")
        path = self.dir / "spec-problems" / f"triager-{jobs[0][1]}.md"
        path.write_text("- condition 2: comment 77: it says todos should sort newest first\n")
        self.answer(*jobs[0], "TRIAGED", blockers="0", acceptance_checks="0",
                    triage_file="none", checks_file="none", spec_problems="1")
        out = self.next(4)
        report = " ".join(out["REPORT"])
        self.assertIn("from a comment on the PR", report)
        self.assertIn("condition 2: comment 77", report)
        self.sign_off(out, "the spec is right")
        self.assertIn("main gate", self.next(5)["QUESTION"])  # nothing else open

    def test_a_security_reviewer_that_finds_a_criterion_missing_stops_after_the_pass(self):
        self.draft_pr()
        _, jobs = self.reviewers(problems="- missing: the due date must be the owner's to "
                                          "set\n")
        for w, n in jobs:
            (self.dir / "review" / "pass-1" / f"{self.sets(w, n)['reviewer']}.md").write_text(
                r_report("none"))
            self.answer(w, n, "REVIEWED", findings="0", leads="0")
        (self.dir / "CODE_REVIEW.md").write_text(CLEAN_REVIEW.format(tree=self.tree()))
        _, jobs = self.expect("review-judge")
        self.answer(*jobs[0], "CLEAN", must_fix_open="0", revote="0")
        out = self.next(4)
        report = " ".join(out["REPORT"])
        self.assertIn("in review pass 1", report)
        self.assertIn("a missing criterion: the due date must be the owner's", report)
        self.sign_off(out)
        self.refresh_body()
        self.assertIn("ready gate", self.next(5)["QUESTION"])

    def test_a_retry_at_a_judge_s_spec_problem_applies_the_re_votes_again(self):
        self.draft_pr()
        _, jobs = self.reviewers()
        for w, n in jobs:
            (self.dir / "review" / "pass-1" / f"{self.sets(w, n)['reviewer']}.md").write_text(
                r_report("none"))
            self.answer(w, n, "REVIEWED", findings="0", leads="0")
        (self.dir / "CODE_REVIEW.md").write_text(CLEAN_REVIEW.format(tree=self.tree()))
        _, jobs = self.expect("review-judge")
        (self.dir / "spec-problems").mkdir(exist_ok=True)
        (self.dir / "spec-problems" / f"review-judge-{jobs[0][1]}.md").write_text(
            "- condition 1: the panel shows the order is backwards\n")
        self.answer(*jobs[0], "CLEAN", must_fix_open="0", revote="0", spec_problems="1")
        self.next(4)
        state = self.state()
        state["phase6"]["votes"] = {"1": 5}  # as if the pass's re-votes were applied
        self.write_state(state)
        r = self.autodev("override", "retry", "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("1", self.state()["phase6"].get("votes", {}))
        self.expect("review-judge")  # it consolidates the pass again

    def test_the_pr_gate_lists_the_coder_s_deviations_from_the_plan(self):
        self.plan_session()
        self.resume()
        _, jobs = self.expect("coder")
        (self.dir / "deviations").mkdir(exist_ok=True)
        (self.dir / "deviations" / f"coder-{jobs[0][1]}.md").write_text(
            "- step 1: the field goes on the Todo type, which the list reads\n")
        self.answer(*jobs[0], "BUILT", blocked="0", test_changes="none", deviations="1")
        (self.worktree / "due.ts").write_text("export const due = 1;\n")
        self.quality_gate()
        self.enter_stage("ship")
        self.resume()
        self.draft_pr(started=True)
        self.review_clean()
        self.refresh_body()
        summary = "\n".join(self.next(5)["SUMMARY"])  # the ready-for-review gate
        self.assertIn("Coder #1 deviated from the plan", summary)
        self.assertIn("- step 1: the field goes on the Todo type", summary)

    def test_human_blockers_and_checks_share_one_round(self):
        self.open_pr()
        blockers, checks = self.triage_files()
        self.expect("triager", "TRIAGED", blockers="1", acceptance_checks="1",
                    triage_file=str(blockers), checks_file=str(checks))
        out, jobs = self.expect("acceptance-tester")
        self.assertEqual(self.sets(*jobs[0])["report"], str(checks))
        self.assertIn("human-1", out["BUDGET"])
        left = self.state()["budget"]["remaining"]
        self.answer(*jobs[0], "REPAIRED", checks="1", ambiguous="none")
        out, jobs = self.expect("coder")
        self.assertEqual(self.sets(*jobs[0])["corrections_file"], str(blockers))
        self.assertNotIn("BUDGET", out)
        self.assertEqual(self.state()["budget"]["remaining"], left)

    def test_a_correction_that_changes_nothing_reaches_the_gates(self):
        self.open_pr()
        _, checks = self.triage_files()
        self.expect("triager", "TRIAGED", blockers="0", acceptance_checks="1",
                    triage_file="none", checks_file=str(checks))
        self.expect("acceptance-tester", "STANDS", checks="0", ambiguous="none")
        self.sign_off(self.next(4))
        # The code is what the last green gate checked: no gate run, no commit,
        # no empty review pass, no second triage: the main gate.
        self.assertIn("main gate", self.next(5)["QUESTION"])
        self.assertNotIn("commit_attempt", self.state()["phase6"])

    def test_commit_refuses_a_changed_acceptance_check(self):
        self.ship_ready()
        self.lint()
        (self.worktree / "src" / "due.acceptance.test.ts").write_text("weakened\n")
        r = self.autodev("commit", "--message", "feat: x", "--dir", self.dir)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("the committed acceptance checks changed", r.stdout + r.stderr)
        self.assertNotIn("verified_sha", self.state()["phase6"])  # nothing pushed

    def test_a_commit_made_but_not_checked_is_checked_not_refused(self):
        self.ship_ready()
        self.lint()
        self.spec_eval()
        self.assertIn("commit: run", self.next(0)["ACTION"])  # before any review
        # `commit` committed, then could not check the commit (killed, say).
        self.sh("git", "add", "-A", "--", ".", ":!.auto-dev", cwd=self.worktree)
        self.sh("git", "commit", "-q", "-m", "feat: x", cwd=self.worktree)
        head = self.sh("git", "rev-parse", "HEAD", cwd=self.worktree).strip()
        state = self.state()
        state["phase6"]["unverified_commit"] = head
        self.write_state(state)
        self.assertIn("commit: run", self.next(0)["ACTION"])  # not "nothing to commit"
        r = self.autodev("commit", "--message", "feat: x", "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(f"COMMITTED: {head}", r.stdout)
        state = self.state()
        del state["phase6"]["verified_sha"]
        state["phase6"]["commit_attempt"] = {"result": "not-verified",
                                             "seq": state["events"] + 1}
        self.write_state(state)
        self.assertIn("The commit step failed (not-verified)",
                      " ".join(self.next(4)["REPORT"]))

    def test_gh_failing_at_publish_is_not_a_refusal(self):
        _sha, _url, _out, body = self.to_body(first=[
            {"args": ["pr", "create"], "stderr": "HTTP 502: Bad Gateway", "exit": 1}])
        body.write_text(re.sub(r"<!-- WRITE: .*?-->", "Todos can carry a due date.",
                               body.read_text()))
        r = self.autodev("pr", "publish", "--dir", self.dir)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertNotIn("publish_attempt", self.state()["phase6"])
        self.assertIn("pr publish", " ".join(self.next(0)["AFTER"]))

    def test_a_check_the_tester_ruled_right_on_a_pr_comment_gets_no_second_round(self):
        self.open_pr()
        _, checks = self.triage_files()
        self.expect("triager", "TRIAGED", blockers="0", acceptance_checks="1",
                    triage_file="none", checks_file=str(checks))
        self.expect("acceptance-tester", "STANDS", checks="0", ambiguous="none")
        left = self.state()["budget"]["remaining"]  # human-1 is spent
        out = self.next(4)  # the tester and the comment disagree: the user decides
        self.assertIn("a PR comment judges them wrong", " ".join(out["REPORT"]))
        self.sign_off(out)
        # Nothing changed: no second round, no pass; the main gate asks.
        self.assertIn("main gate", self.next(5)["QUESTION"])
        self.assertEqual(self.state()["budget"]["remaining"], left)

    def republished_triage(self, ruling):
        """A human round (one blocker, one check comment the tester answers
        `ruling`), then the refreshed PR: returns the second triager's sets and
        the first round's two files."""
        _, url = self.open_pr()
        blockers, checks = self.triage_files()
        self.expect("triager", "TRIAGED", blockers="1", acceptance_checks="1",
                    triage_file=str(blockers), checks_file=str(checks))
        self.expect("acceptance-tester", ruling, checks="0", ambiguous="none")
        if ruling == "STANDS":
            self.sign_off(self.next(4))
        _, jobs = self.expect("coder")
        (self.worktree / "sort.ts").write_text("export const sort = 1;\n")
        self.answer(*jobs[0], "BUILT", blocked="0", test_changes="none")
        self.quality_gate()
        self.review_clean()
        self.assertIn("commit: run", self.next(0)["ACTION"])
        r = self.autodev("commit", "--message", "fix: x", "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        out = self.next(0)
        self.assertIn("push", out["ACTION"])
        self.sh("git", "push", "-q", "origin", "HEAD", cwd=self.worktree)
        self.after(out)
        out = self.next(0)
        self.assertIn("pr publish", out["ACTION"])
        body = self.dir / "pr-body.md"
        body.write_text(re.sub(r"<!-- WRITE: .*?-->", "Todos can carry a due date.",
                               body.read_text()))
        sha = self.state()["phase6"]["verified_sha"]
        gh = json.loads((self.tmp / "gh.json").read_text())
        self.script_gh([
            {"args": ["pr", "edit", "12"], "stdout": ""},
            {"args": ["pr", "view", "12", "--json", "number,url,body"],
             "stdout": json.dumps({"number": 12, "url": f"{url}/pull/12",
                                   "body": f"Checked at commit {sha}"})}] + gh)
        r = self.autodev("pr", "publish", "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        _, jobs = self.expect("triager")
        self.assertIn("earlier: human-1 (triaged ", (self.dir / "briefs" /
                                                    f"triager-{jobs[0][1]}.md").read_text())
        self.assertNotIn("earlier", self.sets("triager", 1))  # nothing earlier then
        return self.sets(*jobs[0]), blockers, checks

    def test_a_republished_pr_tells_the_triager_what_earlier_rounds_handled(self):
        sets, blockers, checks = self.republished_triage("STANDS")
        self.assertIn(f"the coder worked on the blockers in {blockers}", sets["earlier"])
        self.assertIn(f"the acceptance tester ruled them right as written, and the user "
                      f"kept them for the comments in {checks}", sets["earlier"])

    def test_a_repaired_check_is_named_as_repaired_to_the_next_triager(self):
        sets, _, checks = self.republished_triage("REPAIRED")
        self.assertIn(f"the acceptance tester repaired them for the comments in {checks}",
                      sets["earlier"])

    def test_a_refused_publish_stops(self):
        _sha, _url, out, body = self.to_body()
        r = self.autodev("pr", "publish", "--dir", self.dir)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn(str(body), self.next(0)["ACTION"])  # back to the write step once
        r = self.autodev("pr", "publish", "--dir", self.dir)
        state = self.state()
        state["settings"]["checkpoint_events"] = 1  # a checkpoint is due
        self.write_state(state)
        self.assertIn("unwritten", " ".join(self.next(4)["REPORT"]))  # the stop wins
        state = self.state()
        state["settings"]["checkpoint_events"] = 1000
        self.write_state(state)
        body.write_text(re.sub(r"<!-- WRITE: .*?-->", "Details in .auto-dev/PLAN.md.",
                               body.read_text()))
        r = self.autodev("pr", "publish", "--dir", self.dir)
        self.assertIn("PROBLEMS", r.stdout)
        out = self.next(4)  # never exit 1, never the same publish again
        self.assertIn(".auto-dev/", " ".join(out["REPORT"]))
        self.assertIn("auto-dev continue", " ".join(out["REPORT"]))
        self.resume()  # the user fixed it: a resume lifts the stop
        self.assertIn(str(body), self.next(0)["ACTION"])

    def merge_ready(self, first=()):
        sha, _ = self.open_pr(first=first)
        self.expect("triager", "TRIAGED", blockers="0", acceptance_checks="0",
                    triage_file="none", checks_file="none")
        self.after(self.next(5), "Merge PR to main")
        return sha

    def test_a_merge_whose_outcome_is_unknown_is_never_offered_again(self):
        sha = self.merge_ready(first=[{"args": ["pr", "view", "12", "--json", "state"],
                                       "stderr": "HTTP 502", "exit": 1}])
        r = self.autodev("merge-pr", "--pr", "12", "--sha", sha, "--dir", self.dir)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        out = self.next(4)
        self.assertIn("gh pr view 12 --json state", " ".join(out["REPORT"]))
        self.assertEqual(self.next(4)["exit"], 4)

    def test_a_triage_answer_is_kept_and_listed_as_a_follow_up(self):
        self.reviewed_pr()
        self.mark_ready("S2: Separate PR (note it as a follow-up)")
        self.assertEqual(self.state()["marks"]["triage-S2"]["value"], "separate")
        body = self.dir / "pr-body.md"
        text = body.read_text()
        self.assertIn("Follow-up for a separate PR: session token not rotated", text)
        body.write_text(re.sub(r"<!-- WRITE: .*?-->", "Todos can carry a due date.", text))
        r = self.lib("pr-body", "--check", body, "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_an_edit_answered_at_the_ready_gate_is_re_checked_again(self):
        self.reviewed_pr()
        (self.worktree / "extra.ts").write_text("export const extra = 1;\n")
        self.lint()  # stale for the gate: the code changed after the reviews
        self.quality_gate()  # the gate runs on the edit: no worker
        self.review_clean()  # a pass on the edit, before it is committed on top
        self.assertEqual(self.state()["phase6"]["passes"][-1]["scope"], "after-commit")
        r = self.autodev("commit", "--message", "chore: extra", "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        out = self.next(0)
        self.assertIn("push", out["ACTION"])
        self.sh("git", "push", "-q", "origin", "HEAD", cwd=self.worktree)
        self.after(out)
        self.refresh_body()
        self.after(self.next(5), "Hold (keep it a draft)")
        (self.worktree / "extra.ts").write_text("export const extra = 2;\n")
        self.resume()
        self.quality_gate()  # a new check, not "stale twice"

    def test_a_hold_at_the_ready_gate_stops_and_resume_asks_again(self):
        self.reviewed_pr()
        out = self.next(5)
        self.assertIn("ready gate", out["QUESTION"])
        self.assertIn("Draft PR https://github.com/acme/app/pull/12", out["SUMMARY"][0])
        self.after(out, "Hold (keep it a draft)")
        out = self.next(4)
        self.assertIn("held", " ".join(out["REPORT"]))
        self.resume()
        self.assertIn("ready gate", self.next(5)["QUESTION"])

    def test_the_open_pr_gate_asks_before_the_first_push_only_when_on(self):
        self.ship_ready()
        state = self.state()
        state["settings"]["open_pr_gate"] = True
        self.write_state(state)
        self.lint()
        out = self.next(5)  # nothing is committed or pushed before the answer
        self.assertIn("pr gate", out["QUESTION"])
        self.assertIn("Not verified or reviewed yet", " ".join(out["SUMMARY"]))
        files = next(ln for ln in out["SUMMARY"] if ln.startswith("Files changed"))
        self.assertIn("src/due.acceptance.test.ts", files)  # committed before the build
        self.assertIn("due.ts", files)  # and the build, not committed yet
        self.assertNotIn("verified_sha", self.state()["phase6"])
        self.after(out, "Hold (don't push yet)")
        self.assertIn("held", " ".join(self.next(4)["REPORT"]))
        self.resume()
        self.after(self.next(5), "Open PR")
        self.assertIn("commit: run", self.next(0)["ACTION"])
        # The code changes after the answer: re-checked, then the gate again,
        # since it was asked on other code.
        (self.worktree / "extra.ts").write_text("export const extra = 1;\n")
        r = self.autodev("commit", "--message", "feat: x", "--dir", self.dir)
        self.assertEqual(r.returncode, 1, r.stdout)  # stale: nothing committed
        self.quality_gate()  # the gate runs again on the changed code: no worker
        self.assertIn("pr gate", self.next(5)["QUESTION"])
        self.assertNotIn("verified_sha", self.state()["phase6"])

    def test_the_planted_bug_count_covers_carried_and_rerun_mutants_once(self):
        # A re-check's Mutation line counts every mutant of the set, carried
        # forward or run again, and says how many were carried forward.
        write = self.spec_eval

        def spec_eval(**kw):
            write(**kw)
            path = self.dir / "SPEC_EVAL.md"
            path.write_text(path.read_text().replace(
                "4 mutants (cap 20): 3 killed · 0 timeout (counted caught) · 1 survived "
                "· 0 invalid",
                "5 mutants (cap 20): 4 killed · 0 timeout (counted caught) · 1 survived "
                "· 0 invalid · 3 carried forward (`evidence/mutation-record.json`)").replace(
                "| M2 | `src/sort.ts:4` |", "| M5 | `src/sort.ts:4` |"))
        self.spec_eval = spec_eval
        self.reviewed_pr()  # the verifier runs on the draft
        self.assertIn("3 carried forward", (self.dir / "SPEC_EVAL.md").read_text())
        text = (self.dir / "pr-body.md").read_text()
        self.assertIn("We put 5 small deliberate bugs", text)
        self.assertIn("They caught 4.", text)


# A standard-risk plan: no Security/Compliance criteria, so no S1 check.
STANDARD_PLAN = (PLAN.replace("Risk: high — only the owner may set a due date",
                              "Risk: standard — one field and one sort")
                 .split("## Security/Compliance criteria")[0]
                 + "## Size check" + PLAN.split("## Size check", 1)[1].replace("C1, S1", "C1"))
STANDARD_MANIFEST = "".join(ln for ln in MANIFEST.splitlines(True)
                            if not ln.startswith("| S1 "))
SOLO_FINDING = """\
## J1
- Finding: null due date crashes sort
- Location: `src/sort.ts:4`
- Category: correctness
- Holds: yes
- Trigger path: `list()` (`src/list.ts:3`) sorts a todo with no due date; `a.due` is undefined
- Judge: the sort reads the date of every todo
- Where: `src/sort.ts:4` — the comparison
- Test: a todo with no due date sorts last
- Required change: in src/sort.ts, sort a todo with no due date after the others
- In plain words: a todo with no due date no longer breaks the list

"""
SOLO_SECURITY = SECURITY_REVIEW.replace("reviewer: security-reviewer", "reviewer: reviewer")


class LeanTest(NextCase):
    """A standard-risk run: the verifier and one reviewer, on the draft PR."""
    to_body = ShipTest.to_body
    draft_pr = ShipTest.draft_pr
    refresh_body = ShipTest.refresh_body
    published = ShipTest.published
    mark_ready = ShipTest.mark_ready
    plan_text = STANDARD_PLAN

    def setUp(self):
        super().setUp()
        (self.dir / "PLAN.md").write_text(STANDARD_PLAN)
        (self.dir / "acceptance" / "MANIFEST.md").write_text(STANDARD_MANIFEST)

    def spec_eval(self, **kw):
        NextCase.spec_eval(self, **kw)
        path = self.dir / "SPEC_EVAL.md"
        path.write_text("".join(ln for ln in path.read_text().splitlines(True)
                                if not ln.startswith("| S1 ")))

    def plan_session(self, verdict="APPROVE"):
        (self.dir / "PLAN.md").write_text(STANDARD_PLAN)
        self.expect("planner", "FITS", **{**PLANNED, "risk": "standard"})
        if verdict == "REVISE":
            self.critic("REVISE", risk="standard")
            self.expect("planner", "REVISED", **{**PLANNED, "risk": "standard"})
            self.critic(risk="standard", mode="recheck")
        else:
            self.critic(risk="standard")
        self.expect("acceptance-tester", "WRITTEN", checks="3", ambiguous="none")
        self.enter_stage("build")  # no post-plan gate on a standard-risk run

    def ship_ready(self):
        self.plan_session()
        self.build_session()

    def solo(self, verifier="ALL_MET", finding=False, security=None, problems=None):
        """The pass: the verifier and the reviewer, spawned together. Answer the
        verifier `verifier` (None: leave it), and the reviewer with one open
        must-fix finding when `finding`, built by `review-build --solo`.
        Returns (verifier job, reviewer job)."""
        out = self.next(0)
        jobs = self.spawned(out)
        self.assertEqual(sorted(w for w, _ in jobs), ["reviewer", "verifier"],
                         json.dumps(out, indent=2))
        ver = next(j for j in jobs if j[0] == "verifier")
        rev = next(j for j in jobs if j[0] == "reviewer")
        if verifier is not None:
            self.verifier_answer(ver, verifier)
        self.reviewer_answer(rev, finding, security, problems)
        return ver, rev

    def reviewer_answer(self, rev, finding=False, security=None, problems=None):
        n = self.state()["phase6"]["review_pass"]
        folder = self.dir / "review" / f"pass-{n}"
        earlier = "\n".join(f"- {r}: fixed" for r in self.open_rows()) or "none"
        (folder / "JUDGMENT.md").write_text(f"# Judgment — pass {n}\n\n"
                                            + (SOLO_FINDING if finding else "")
                                            + f"## Earlier must-fix\n{earlier}\n")
        r = self.autodev("review-build", "--solo", "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        text, nxt, must_fix = security or (SOLO_SECURITY, None, "0")
        (self.dir / "SECURITY_REVIEW.md").write_text(text.format(tree=self.tree()))
        (self.dir / "review" / "security-corrections.md").write_text(
            "# Required changes\nNone.\n" if must_fix == "0" else
            "# Required changes\n1. S3: in src/due.ts, check the caller owns the todo\n")
        extra = {}
        if problems is not None:
            path = self.dir / "spec-problems" / f"reviewer-{rev[1]}.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(problems)
            extra["spec_problems"] = "1"
        open_ = int(finding)
        self.answer(*rev, nxt or ("MUST_FIX" if open_ or must_fix != "0" else "CLEAN"),
                    must_fix_open=str(open_), must_fix=must_fix, pre_existing="1",
                    **extra)

    def open_rows(self):
        path = self.dir / "CODE_REVIEW.md"
        if not path.exists():
            return []
        return [ln.split("|")[1].strip() for ln in path.read_text().splitlines()
                if ln.startswith("| C") and ln.rstrip().endswith("| open |")]

    def spawns(self):
        return len(self.state()["briefs"])

    def walk_to_ready(self, verdict):
        """The default lane's happy path: (spawns at the first push, spawns at
        the ready-for-review gate)."""
        self.plan_session(verdict)
        self.build_session()
        at_push = self.spawns()  # the commit and the first push spawn nothing
        self.draft_pr(started=True)
        self.assertEqual(self.spawns(), at_push)
        self.assertTrue(self.state()["marks"]["pushed"])
        self.solo()
        self.refresh_body()
        self.assertIn("ready gate", self.next(5)["QUESTION"])
        return at_push, self.spawns()

    def test_the_default_lane_holds_the_spawn_budget(self):
        # The spawn budget (CLAUDE.md): at most 5 worker spawns to the first push and 7
        # to ready-for-review. A PR that adds a step raises these on purpose.
        at_push, at_ready = self.walk_to_ready("APPROVE")
        self.assertLessEqual(at_push, 5)
        self.assertLessEqual(at_ready, 7)
        self.assertEqual((at_push, at_ready), (4, 6))  # planner, critic, tester, coder

    def test_one_plan_revision_adds_the_revision_and_the_critic_s_re_check(self):
        at_push, at_ready = self.walk_to_ready("REVISE")
        self.assertEqual((at_push, at_ready), (6, 8))

    def test_a_standard_run_verifies_without_mutation_or_probes(self):
        self.draft_pr()
        ver, rev = self.solo(verifier=None)
        brief = (self.dir / "briefs" / f"verifier-{ver[1]}.md").read_text()
        self.assertIn("mutation_cap: 0 (off: a standard-risk run)", brief)
        self.assertIn("probes: off (a standard-risk run)", brief)
        self.assertEqual(self.sets(*rev)["scope"], "first")
        self.assertEqual(self.sets(*rev)["tree"], self.state()["phase6"]["passes"][0]["tree"])
        self.assertEqual(self.state()["phase6"]["passes"][0]["lane"], "standard")
        report = (self.dir / "CODE_REVIEW.md").read_text()
        self.assertIn("reviewers finished: 1/1", report)
        self.assertIn("Latest pass: 1 — scope: the whole change, as committed on the "
                      "branch: ", report)

    def test_a_solo_finding_and_the_verifier_s_items_share_one_correction(self):
        self.draft_pr()
        left = self.state()["budget"]["remaining"]
        self.solo(verifier="CORRECT", finding=True)
        self.assertIn("| C1 | null due date crashes sort | `src/sort.ts:4` | correctness | "
                      "1/1 | Medium | open |", (self.dir / "CODE_REVIEW.md").read_text())
        out, jobs = self.expect("coder")
        self.assertEqual(self.sets(*jobs[0])["corrections_file"],
                         f"{self.dir}/evidence/corrections.md and "
                         f"{self.dir}/review/pass-1/corrections.md")
        self.assertIn("spent `pass-1`", out["BUDGET"])
        self.assertEqual(self.state()["budget"]["remaining"], left - 1)
        (self.worktree / "sort.ts").write_text("export const sort = 1;\n")
        self.answer(*jobs[0], "BUILT", blocked="0", test_changes="none")
        self.quality_gate()
        ver, rev = self.solo()  # pass 2, on the uncommitted correction
        self.assertEqual(self.sets(*ver)["mode"], "re-check")
        self.assertEqual(self.sets(*rev)["scope"], "after-commit")
        self.assertIn("| C1 |", (self.dir / "CODE_REVIEW.md").read_text())
        self.assertEqual(self.open_rows(), [])  # fixed (pass 2)
        self.assertIn("commit: run", self.next(0)["ACTION"])

    def test_a_plan_revised_in_a_correction_is_judged_again_whole(self):
        self.draft_pr()
        self.solo(verifier="CORRECT")
        _, jobs = self.expect("coder")
        (self.dir / "blocked" / f"coder-{jobs[0][1]}.md").write_text("- step 2: no type\n")
        self.answer(*jobs[0], "BLOCKED", blocked="1", test_changes="none")
        self.expect("planner", "PLAN_REVISED", **{**PLANNED, "risk": "standard"})
        _, jobs = self.expect("coder")
        (self.worktree / "sort.ts").write_text("export const sort = 1;\n")
        self.answer(*jobs[0], "BUILT", blocked="0", test_changes="none")
        self.quality_gate()
        ver, _ = self.solo()
        self.assertEqual(self.sets(*ver)["mode"], "first pass")  # PLAN.md changed

    def test_a_check_the_verifier_questions_is_repaired_then_re_checked(self):
        self.draft_pr()
        verified = self.state()["phase6"]["verified_sha"]
        ver, _ = self.solo(verifier=None)
        self.spec_eval(v1="partial",
                       defective='`src/due.acceptance.test.ts` :: "shows the due date"')
        self.answer(*ver, "REPAIR", tree="x", corrections="0")
        out, jobs = self.expect("acceptance-tester")
        sets = self.sets(*jobs[0])
        self.assertTrue(sets["scope"].startswith("ONLY conditions 1: the verifier"), sets)
        self.assertIn("SPEC_EVAL.md, section Defective acceptance checks", sets["report"])
        self.assertIn("spent `pass-1`", out["BUDGET"])
        (self.worktree / "src" / "due.acceptance.test.ts").write_text("test, repaired\n")
        self.answer(*jobs[0], "REPAIRED", checks="1", ambiguous="none")
        self.quality_gate()  # the repaired check goes through the gate
        commits = self.state()["tests_commits"]  # the repair is a tests commit of its own
        self.assertEqual([c["paths"] for c in commits][1:], [["src/due.acceptance.test.ts"]])
        ver, _ = self.solo()
        p6 = self.state()["phase6"]
        self.assertEqual((p6["passes"][-1]["scope"], p6["passes"][-1]["since"]),
                         ("outside", verified))
        self.assertEqual(self.sets(*ver)["mode"], "first pass")

    def test_a_check_the_tester_rules_right_stops_and_a_sign_off_keeps_it(self):
        self.draft_pr()
        ver, _ = self.solo(verifier=None)
        defective = '`src/due.acceptance.test.ts` :: "shows the due date"'
        self.spec_eval(v1="partial", defective=defective)
        self.answer(*ver, "REPAIR", tree="x", corrections="0")
        out, jobs = self.expect("acceptance-tester")
        self.assertNotIn("proposals", self.sets(*jobs[0]))  # the tester repairs; nobody rules
        self.answer(*jobs[0], "STANDS", checks="0", ambiguous="none")
        out = self.next(4)  # workers never settle it between themselves
        report = " ".join(out["REPORT"])
        self.assertIn("checks of condition(s) 1 right as written", report)
        self.assertIn("the verifier or the code review judges them wrong", report)
        self.sign_off(out, "the check is right")
        self.refresh_body()  # nothing changed: on to the ready gate
        out = self.next(5)
        self.assertIn("ready gate", out["QUESTION"])
        state = self.state()
        self.assertEqual(state["budget"]["remaining"], state["budget"]["total"] - 1)
        sys.path.insert(0, str(SCRIPTS))
        cmd_next = import_module("lib.cmd_next")
        kept = cmd_next.kept_texts(type("C", (), {"state": state})())
        self.assertIn("1 (the user's words: the check is right)", kept["checks_kept"])

    def test_a_failed_verifier_is_spawned_again_as_a_first_pass(self):
        self.draft_pr()
        ver, _ = self.solo(verifier=None)
        self.answer(*ver, None, status="failed")
        _, jobs = self.expect("verifier")  # the reviewer's result stands
        self.assertEqual(self.sets(*jobs[0])["mode"], "first pass")
        self.answer(*jobs[0], None, status="failed")
        out = self.next(4)
        self.assertIn("did not return ok twice running", " ".join(out["REPORT"]))

    def spec_problem(self, worker, n, text="- condition 1: the ticket asks for the latest "
                                           "due date first\n"):
        path = self.dir / "spec-problems" / f"{worker}-{n}.md"
        path.parent.mkdir(exist_ok=True)
        path.write_text(text)
        return path

    def test_a_verifier_that_finds_a_criterion_wrong_stops_before_any_correction(self):
        self.draft_pr()
        ver, _ = self.solo(verifier=None)
        self.spec_eval(v1="unmet")
        (self.dir / "evidence").mkdir(exist_ok=True)
        (self.dir / "evidence" / "corrections.md").write_text("# Required changes\n1. x\n")
        self.spec_problem(*ver)
        self.answer(*ver, "CORRECT", tree="x", corrections="1", spec_problems="1")
        left = self.state()["budget"]["remaining"]
        out = self.next(4)
        report = " ".join(out["REPORT"])
        self.assertIn("found PLAN.md wrong in review pass 1", report)
        self.assertIn("condition 1: the ticket asks for the latest due date first", report)
        self.assertEqual(self.state()["stop"]["kind"], "spec-problem")
        self.assertEqual(self.state()["budget"]["remaining"], left)  # no round, no coder
        self.sign_off(out, "the spec is right")
        out, jobs = self.expect("coder")  # the verifier's correction goes ahead
        self.assertEqual(self.mode(*jobs[0]), "correction")
        self.assertIn("pass-1", out["BUDGET"])
        (self.worktree / "sort.ts").write_text("export const sort = 1;\n")
        self.answer(*jobs[0], "BUILT", blocked="0", test_changes="none")
        self.quality_gate()
        ver, rev = self.solo(verifier=None)
        self.assertIn("kept PLAN.md as written for: 1 (the user's words: the spec is right)",
                      self.sets(*ver)["spec_kept"])
        self.assertIn("kept PLAN.md as written", self.sets(*rev)["spec_kept"])

    def test_a_retry_at_a_spec_problem_runs_the_verifier_again(self):
        self.draft_pr()
        ver, _ = self.solo(verifier=None)
        self.spec_eval()
        self.spec_problem(*ver, "- missing: a todo with no due date must sort last\n")
        self.answer(*ver, "ALL_MET", tree="x", corrections="0", spec_problems="1")
        out = self.next(4)
        self.assertIn("a missing criterion: a todo with no due date", " ".join(out["REPORT"]))
        r = self.autodev("override", "retry", "--text", "I added it to PLAN.md",
                         "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        _, again = self.expect("verifier")
        self.assertGreater(again[0][1], ver[1])
        # The user may have changed PLAN.md: the verifier judges every condition again.
        self.assertEqual(self.sets(*again[0])["mode"], "first pass")

    def test_a_fix_to_the_spec_holds_a_brief_still_out_to_the_new_spec(self):
        self.draft_pr()
        jobs = self.spawned(self.next(0))
        ver = next(j for j in jobs if j[0] == "verifier")
        state = self.state()
        brief = next(b for b in state["briefs"] if (b["worker"], b["n"]) == ver)
        before = brief["spec"]
        (self.dir / "PLAN.md").write_text(STANDARD_PLAN.replace("earliest first",
                                                                "latest first"))
        sys.path.insert(0, str(SCRIPTS))
        from lib import cmd_work
        cmd_work.refresh_spec(state, self.dir)
        brief = next(b for b in state["briefs"] if (b["worker"], b["n"]) == ver)
        self.assertNotEqual(brief["spec"], before)
        self.assertEqual(brief["spec"], cmd_work.digest(self.dir / "PLAN.md"))

    def test_a_confirmed_security_finding_goes_to_the_coder(self):
        self.draft_pr()
        self.solo(security=(SOLO_SECURITY.replace(
            "| S2 | session token not rotated |",
            "| S3 | any user can set another user's due date | `src/due.ts:9` | "
            "introduced | High | confirmed | must-fix | open |\n"
            "| S2 | session token not rotated |"), None, "1"))
        out, jobs = self.expect("coder")
        self.assertEqual(self.sets(*jobs[0])["corrections_file"],
                         f"{self.dir}/review/security-corrections.md")
        self.assertIn("spent `pass-1`", out["BUDGET"])

    def test_a_reviewer_whose_counts_disagree_with_its_reports_is_refused(self):
        self.draft_pr()
        out = self.next(0)
        ver, rev = sorted(self.spawned(out), key=lambda j: j[0] != "verifier")
        self.verifier_answer(ver)
        self.reviewer_answer(rev, finding=True)
        path = self.dir / "returns" / f"reviewer-{rev[1]}.json"
        data = json.loads(path.read_text())
        path.write_text(json.dumps({**data, "next": "CLEAN", "must_fix_open": "0"}))
        out = self.next(0, refused_ok=True)
        self.assertIn(f"reviewer-{rev[1]}: refused (MISMATCH)", out["RECORDED"])
        issues = " ".join(self.state()["refused"][f"reviewer-{rev[1]}"])
        self.assertIn("must_fix_open is 0 but CODE_REVIEW.md has 1", issues)
        self.assertIn("next is CLEAN", issues)

    def test_a_reviewer_that_fails_twice_stops(self):
        self.draft_pr()
        _, rev = self.solo(verifier="ALL_MET")
        state = self.state()  # the reviewer's result: failed, not the one solo wrote
        state["log"] = [e for e in state["log"] if (e["worker"], e["n"]) != rev]
        self.write_state(state)
        self.answer(*rev, None, status="failed")
        _, jobs = self.expect("reviewer")  # the verifier's result stands
        self.answer(*jobs[0], None, status="failed")
        out = self.next(4)
        self.assertIn("reviewer #", " ".join(out["REPORT"]))
        self.assertIn("did not return ok twice running", " ".join(out["REPORT"]))

    def ci_on(self, checks=None):
        state = self.state()
        state["settings"]["ci"] = "github"
        self.write_state(state)
        return [{"args": ["pr", "checks"], "stdout": json.dumps(checks or [])}]

    def test_ci_that_never_settles_does_not_hold_the_correction(self):
        self.draft_pr(extra=self.ci_on())
        self.solo(finding=True)
        state = self.state()  # CI watched to its end: unavailable (no checks reported)
        state["phase6"]["ci"] = {"sha": state["phase6"]["verified_sha"],
                                 "status": "unavailable", "seq": state["events"]}
        self.write_state(state)
        _, jobs = self.expect("coder")
        self.assertEqual(self.sets(*jobs[0])["corrections_file"],
                         f"{self.dir}/review/pass-1/corrections.md")
        self.assertNotIn("also", self.state()["phase6"]["corrections"][-1])

    def test_red_ci_the_code_can_t_fix_stops_before_the_correction(self):
        checks = [{"name": "test", "state": "FAILURE", "bucket": "fail",
                   "link": "https://ci/1"}]
        self.draft_pr(extra=self.ci_on(checks))
        self.solo(finding=True)
        self.assertIn("ci-watch", self.next(0)["ACTION"])
        r = self.autodev("ci-watch", "--dir", self.dir, "--max-wait", "0")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        _, jobs = self.expect("triager")
        (self.dir / "triage" / "ci-1.md").write_text("# Triage\nThe runner ran out of disk.\n")
        self.answer(*jobs[0], "INFRA", blockers="0", acceptance_checks="0",
                    triage_file=str(self.dir / "triage" / "ci-1.md"), checks_file="none")
        out = self.next(4)
        self.assertIn("classed it INFRA", " ".join(out["REPORT"]))
        self.assertEqual(self.state()["phase6"]["corrections"], [])  # no round spent

    def test_red_ci_on_the_draft_joins_the_review_s_correction(self):
        state = self.state()
        state["settings"]["ci"] = "github"
        self.write_state(state)
        checks = [{"name": "test", "state": "FAILURE", "bucket": "fail",
                   "link": "https://ci/1"}]
        self.draft_pr(extra=[{"args": ["pr", "checks"], "stdout": json.dumps(checks)}])
        left = self.state()["budget"]["remaining"]
        self.solo(finding=True)
        out = self.next(0)  # findings are open: CI settles first
        self.assertIn("ci-watch", out["ACTION"])
        r = self.autodev("ci-watch", "--dir", self.dir, "--max-wait", "0")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        _, jobs = self.expect("triager")
        (self.dir / "triage" / "ci-1.md").write_text(
            "# Required changes\n1. Handle a missing due date in src/sort.ts\n")
        self.answer(*jobs[0], "CODE", blockers="0", acceptance_checks="0",
                    triage_file=str(self.dir / "triage" / "ci-1.md"), checks_file="none")
        out, jobs = self.expect("coder")
        self.assertEqual(self.sets(*jobs[0])["corrections_file"],
                         f"{self.dir}/review/pass-1/corrections.md and "
                         f"{self.dir}/triage/ci-1.md")
        self.assertIn("spent `pass-1`", out["BUDGET"])
        self.assertEqual(self.state()["budget"]["remaining"], left - 1)  # one round
        self.assertEqual(self.state()["phase6"]["corrections"][-1]["also"], ["ci-1"])

    def test_a_pass_half_returned_records_and_waits(self):
        self.draft_pr()
        ver, rev = self.solo(verifier=None)  # only the reviewer's result is written
        out = self.next(0)
        shown = json.dumps(out, indent=2)
        self.assertTrue([ln for ln in out.get("RECORDED", [])
                         if ln.startswith(f"reviewer-{rev[1]}:")], shown)
        self.assert_waits_for(out, f"verifier #{ver[1]}")
        self.assertNotIn(f"reviewer #{rev[1]}", out["ACTION"], shown)
        self.assertIn("only once every agent this wait names has returned", out["ACTION"])

    def test_a_pass_whose_last_worker_returns_moves_on_without_a_respawn(self):
        self.draft_pr()
        ver, _ = self.solo(verifier=None)
        self.next(0)  # the reviewer's result is recorded
        self.verifier_answer(ver)
        out = self.next(0)
        shown = json.dumps(out, indent=2)
        self.assertTrue([ln for ln in out.get("RECORDED", [])
                         if ln.startswith(f"verifier-{ver[1]}:")], shown)
        self.assertFalse([w for w, _ in self.spawned(out) if w in ("verifier", "reviewer")],
                         shown)
        self.assertFalse(out.get("ACTION", "").startswith("wait"), shown)

    def test_a_parallel_pass_is_sent_in_one_message_not_the_foreground(self):
        self.draft_pr()
        out = self.next(0)
        self.assertEqual(sorted(w for w, _ in self.spawned(out)), ["reviewer", "verifier"],
                         json.dumps(out, indent=2))
        self.assertIn("in one message, in parallel", out["ACTION"])
        self.assertNotIn("run_in_background: false", out["ACTION"])

    def test_the_three_spawn_stop_on_a_pass_ends_both_workers(self):
        # Neither worker of the pass ever returns: the stop ends both spawns, so
        # after talk the stop is asked again, not a wait for the other worker.
        self.draft_pr()
        out = self.next(0)
        self.assertEqual(sorted(w for w, _ in self.spawned(out)), ["reviewer", "verifier"],
                         json.dumps(out, indent=2))
        for _ in range(2):
            self.assertEqual(len(self.spawned(self.next_reissue(0))), 2)
        out = self.next_reissue(4)
        self.assertIn("spawned 3 times", " ".join(out["REPORT"]), json.dumps(out, indent=2))
        r = self.autodev("override", "talk", "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        out = self.next(4)
        shown = json.dumps(out, indent=2)
        self.assertIn("spawned 3 times", " ".join(out["REPORT"]), shown)
        self.assertIn("QUESTION", out, shown)
        self.assertFalse(out.get("ACTION", "").startswith("wait"), shown)


class PublishTest(NextCase):
    def test_a_refresh_brings_the_overrides_made_after_the_draft_opened(self):
        sys.path.insert(0, str(SCRIPTS))
        cmd_pr = import_module("lib.cmd_pr")
        live = ("## Summary\nWritten on GitHub.\n\n## Acceptance conditions\nold\n\n"
                "## Quality gate\nold\n\n## Review\nold\n\n## Assumptions\nUTC.\n")
        new = ("## Summary\n<!-- WRITE: x -->\n\n## Acceptance conditions\nnew\n\n"
               "## Quality gate\nnew\n\n## Review\nnew\n\n## Overrides by the user\n"
               "- signed off TEST.md\n\n## Assumptions\n<!-- WRITE: y -->\n")
        merged = cmd_pr.merge_live(live, new)
        self.assertIn("## Overrides by the user\n- signed off TEST.md", merged)
        again = cmd_pr.merge_live(merged, new.replace("signed off TEST.md", "a fix"))
        self.assertIn("- a fix", again)  # refreshed, never frozen at the draft's
        self.assertNotIn("signed off TEST.md", again)
        gone = cmd_pr.merge_live(again, new.split("## Overrides")[0] + "## Assumptions\nx\n")
        self.assertNotIn("## Overrides by the user", gone)

    def test_the_review_line_names_one_reviewer_or_the_panel(self):
        sys.path.insert(0, str(SCRIPTS))
        cmd_pr = import_module("lib.cmd_pr")
        (self.dir / "CODE_REVIEW.md").write_text(CLEAN_REVIEW.format(tree="x"))
        lines = " ".join(cmd_pr.review_lines(self.dir, self.state()))
        self.assertIn("Code review (3 independent reviewers)", lines)
        (self.dir / "CODE_REVIEW.md").write_text(CLEAN_REVIEW.format(tree="x").replace(
            "reviewers finished: 3/3", "reviewers finished: 1/1"))
        lines = " ".join(cmd_pr.review_lines(self.dir, self.state()))
        self.assertIn("Code review (one reviewer)", lines)

    def test_a_refresh_keeps_the_live_summary_and_ticked_boxes(self):
        from importlib import import_module
        sys.path.insert(0, str(SCRIPTS))
        cmd_pr = import_module("lib.cmd_pr")
        live = ("## Summary\nWritten on GitHub.\n\n## Acceptance conditions\nold\n\n"
                "### Checks for a person\n- [x] **Looks right on a phone**\n\n"
                "## Quality gate\nold\n\n## Review\nold\n\n## Assumptions\nUTC.\n\n"
                "Generated with [Claude Code](https://claude.com/claude-code)\n")
        new = ("## Summary\n<!-- WRITE: x -->\n\n## Acceptance conditions\nnew\n\n"
               "### Checks for a person\n- [ ] **Looks right on a phone**\n\n"
               "## Quality gate\nnew\n\n## Review\nnew\n\n## Assumptions\n<!-- WRITE: y -->\n")
        merged = cmd_pr.merge_live(live, new)
        self.assertIn("Written on GitHub.", merged)
        self.assertIn("UTC.", merged)
        self.assertNotIn("WRITE", merged)
        self.assertNotIn("old", merged)
        self.assertIn("- [x] **Looks right on a phone**", merged)

    def test_a_refresh_keeps_a_checklist_a_person_edited_on_github(self):
        cmd_pr = self.cmd_pr()
        from lib.cmd_ship import lint_body
        tmp = Path(os.path.realpath(tempfile.mkdtemp()))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        (tmp / "pull_request_template.md").write_text("## Checklist\n- [ ] Docs updated\n")
        live = "## Summary\nx\n\n## Checklist\n- [x] Docs updated in the wiki\n"
        merged = cmd_pr.merge_live(live, "## Summary\nz\n\n## Checklist\n- [ ] Docs updated\n")
        self.assertIn("- [x] Docs updated in the wiki", merged)
        state = {"worktree": str(tmp), "phase6": {}}
        self.assertTrue(any("checklist" in p for p in lint_body(merged, state)))
        self.assertFalse(any("checklist" in p
                             for p in lint_body(merged, state, checklist=False)))

    def cmd_pr(self):
        from importlib import import_module
        sys.path.insert(0, str(SCRIPTS))
        return import_module("lib.cmd_pr")

    def test_everything_posted_ends_with_the_marker(self):
        cmd_pr = self.cmd_pr()
        live = "## Summary\nx\n\n## Assumptions\ny\n\n" + cmd_pr.ATTRIBUTION + "\n"
        new = "## Summary\nz\n\n## Quality gate\nnew\n\n## Assumptions\nw\n"
        merged = cmd_pr.merge_live(live, new).rstrip("\n").split("\n")
        self.assertEqual(merged[-2:], [cmd_pr.ATTRIBUTION, cmd_pr.MARKER])
        posted = []

        def gh(_wt, *args):
            name = args[args.index("-F") + 1].split("@", 1)[1]
            posted.append(Path(name).read_text())
            return 0, "", ""
        real = cmd_pr.gh
        cmd_pr.gh = gh
        self.addCleanup(setattr, cmd_pr, "gh", real)
        cmd_pr.output_comment(".", self.dir, 12, "55", "a" * 40)  # the output moved back
        self.assertTrue(posted[0].startswith(f"{cmd_pr.COMMENT_HEAD} aaaaaaaaaaaa"))
        self.assertEqual(posted[0].rstrip("\n").split("\n")[-1], cmd_pr.MARKER)

    def test_an_id_the_body_quotes_passes_but_one_written_in_is_refused(self):
        # The tester named a test after S1 and the verifier wrote S1 in its
        # Expected line: generate quotes both word for word, and nobody may
        # edit them, so the lint skips them. An ID in the Summary still fails.
        sha = self.sh("git", "rev-parse", "HEAD", cwd=self.worktree).strip()
        state = self.state()
        state["phase6"]["verified_sha"] = sha
        self.write_state(state)
        manifest = self.dir / "acceptance" / "MANIFEST.md"
        manifest.write_text(manifest.read_text().replace('"owner only"',
                                                         '"criterion S1: owner only"'))
        (self.dir / "acceptance" / "base-run").mkdir(parents=True, exist_ok=True)
        (self.dir / "acceptance" / "base-run" / "CS1.txt").write_text(
            f"Commit: {sha}\nCommand: npx vitest run -t \"criterion S1:\"\n"
            "Result: failed\nOutput (last lines):\n  FAIL criterion S1: owner only\n")
        (self.dir / "evidence").mkdir(exist_ok=True)
        (self.dir / "evidence" / "CS1.txt").write_text(
            "Expected: the S1 check passes\nCommand: npx vitest run -t \"criterion S1:\"\n"
            "Result: passed\nOutput (last lines):\n  PASS criterion S1: owner only\n")
        (self.dir / "CODE_REVIEW.md").write_text(OPEN_REVIEW.format(tree=self.tree()))
        (self.dir / "SECURITY_REVIEW.md").write_text(SECURITY_REVIEW.format(
            tree=self.tree()))
        self.spec_eval()
        self.lint()
        lint = self.dir / "lint" / "TEST.md"  # a verbose reporter names the tests
        lint.write_text(lint.read_text().replace("all good", "PASS criterion S1: owner only"))
        r = self.lib("pr-body", "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        body = self.dir / "pr-body.md"
        text = body.read_text()
        self.assertIn("criterion S1: owner only", text)
        self.assertIn("- `true`: passed <!-- auto-dev:quoted -->", text)
        self.assertIn("- [x] **Only the owner can set a todo's due date** "
                      "<!-- auto-dev:quoted -->", text)
        self.assertIn("expecting the S1 check passes", text)
        written = re.sub(r"<!-- WRITE: .*?-->", "Todos can carry a due date.", text)
        body.write_text(written)
        r = self.lib("pr-body", "--check", body, "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        body.write_text(written.replace("Todos can carry a due date.",
                                        "Todos can carry a due date (S1).", 1))
        r = self.lib("pr-body", "--check", body, "--dir", self.dir)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("uses a condition or finding ID: S1", r.stdout)
        # A quoted region edited after generate is linted like any other text.
        body.write_text(written.replace("expecting the S1 check passes",
                                        "expecting the S1 check to pass"))
        r = self.lib("pr-body", "--check", body, "--dir", self.dir)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("uses a condition or finding ID: S1", r.stdout)

    def test_a_scratch_path_the_body_quotes_passes_but_one_written_in_is_refused(self):
        # The verifier's evidence ran a formatter over `.` and named a .auto-dev/
        # file in its command: generate quotes both word for word, and nobody may
        # edit them, so the lint skips them. A .auto-dev/ path in the Summary
        # still fails.
        sha = self.sh("git", "rev-parse", "HEAD", cwd=self.worktree).strip()
        state = self.state()
        state["phase6"]["verified_sha"] = sha
        self.write_state(state)
        (self.dir / "evidence").mkdir(exist_ok=True)
        (self.dir / "evidence" / "CS1.txt").write_text(
            "Expected: the format check passes\n"
            "Command: git check-ignore -v .auto-dev/PLAN.md; npx prettier --check .\n"
            "Result: passed\nOutput (last lines):\n  [warn] .auto-dev/PLAN.md\n")
        (self.dir / "CODE_REVIEW.md").write_text(OPEN_REVIEW.format(tree=self.tree()))
        (self.dir / "SECURITY_REVIEW.md").write_text(SECURITY_REVIEW.format(
            tree=self.tree()))
        self.spec_eval()
        self.lint()
        r = self.lib("pr-body", "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        body = self.dir / "pr-body.md"
        text = body.read_text()
        self.assertIn("[warn] .auto-dev/PLAN.md", text)
        written = re.sub(r"<!-- WRITE: .*?-->", "Todos can carry a due date.", text)
        body.write_text(written)
        r = self.lib("pr-body", "--check", body, "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        body.write_text(written.replace("Todos can carry a due date.",
                                        "See .auto-dev/PLAN.md.", 1))
        r = self.lib("pr-body", "--check", body, "--dir", self.dir)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("names a .auto-dev/ path", r.stdout)

    def test_what_workers_wrote_is_quoted_so_the_body_passes_its_own_lint(self):
        # A proxy cell naming .auto-dev/, a review's confidence reason and an
        # open finding naming an ID, the verifier's plain words and a person's
        # check naming one, a condition's own title naming one and a gate
        # command naming .auto-dev/: generate copies each word for word, so
        # the lint skips each, and pr publish no longer refuses the text
        # generate wrote itself.
        sha = self.sh("git", "rev-parse", "HEAD", cwd=self.worktree).strip()
        state = self.state()
        state["phase6"]["verified_sha"] = sha
        state["settings"]["gate"][0]["command"] = "true --ignore .auto-dev/"
        self.write_state(state)
        spec = self.dir / "PLAN.md"
        spec.write_text(spec.read_text().replace("with the earliest first",
                                                 "with the earliest first, as in S1"))
        manifest = self.dir / "acceptance" / "MANIFEST.md"
        manifest.write_text(manifest.read_text().replace(
            "## Not automatable\nNone.",
            "## Not automatable\n"
            "| # | Condition | Why no check can drive it | Proxy a verifier can run |\n"
            "|---|-----------|---------------------------|--------------------------|\n"
            "| 1 (Edge) | an invalid date is rejected | the formatter, not a test, judges it "
            "| `npm run format:check` must exit 0 and list no file outside `.auto-dev/` |\n"))
        (self.dir / "CODE_REVIEW.md").write_text(OPEN_REVIEW.format(tree=self.tree()).replace(
            "must-fix decided 2–1: none", "must-fix decided 2–1: C1").replace(
            "null due date crashes sort |", "null due date crashes sort, as S1 did |"))
        (self.dir / "SECURITY_REVIEW.md").write_text(SECURITY_REVIEW.format(
            tree=self.tree()).replace("High/Medium verified: 1/1",
                                      "High/Medium verified: 1/1 (S2 confirmed)"))
        self.spec_eval(v1="partial")
        eval_md = self.dir / "SPEC_EVAL.md"
        eval_md.write_text(eval_md.read_text().replace(
            "| Evidence |\n|---|-----------|---------|------|----------|",
            "| Evidence | In plain words |\n"
            "|---|-----------|---------|------|----------|----------------|").replace(
            "(`evidence/C1.txt`) |",
            "(`evidence/C1.txt`) | the date shows; S1 still holds |").replace(
            "| 2 | sorted | met | Adequate | ran the sort |",
            "| 2 | sorted | manual | Weak | a human must check: see S1 in `.auto-dev/x` | "
            "none |"))
        self.lint()
        r = self.lib("pr-body", "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        body = self.dir / "pr-body.md"
        text = body.read_text()
        self.assertIn("Already checked automatically: `npm run format:check` must exit 0 "
                      "and list no file outside `.auto-dev/`", text)  # no doubled marks
        self.assertIn("- [ ] **an invalid date is rejected → 400** <!-- auto-dev:quoted -->",
                      text)
        self.assertIn("must-fix decided 2–1: C1", text)
        self.assertIn("(S2 confirmed)", text)
        self.assertIn("the date shows; S1 still holds", text)
        self.assertIn("1. see S1 in `.auto-dev/x`", text)
        self.assertIn("crashes sort, as S1 did", text)
        self.assertIn("1 problem that had to be fixed", text)
        self.assertIn("- `true --ignore .auto-dev/`: passed", text)
        written = re.sub(r"<!-- WRITE: .*?-->", "Todos can carry a due date.", text)
        body.write_text(written)
        r = self.lib("pr-body", "--check", body, "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        # A person ticking the box on GitHub leaves the quoted region as it was.
        body.write_text(written.replace("- [ ] **an invalid date is rejected",
                                        "- [x] **an invalid date is rejected"))
        r = self.lib("pr-body", "--check", body, "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_a_finding_s_plain_words_stay_in_its_own_block(self):
        review = OPEN_REVIEW.replace("## Pending re-vote", (
            "### C1 — null due date crashes sort\nTrigger path: sorting a todo with no date\n"
            "Required change: in src/sort.ts, order a missing date last\n"
            "In plain words: sorting crashed on a todo with no due date.\n\n"
            "### C2 — blank title\nIn plain words: a blank title was saved.\n\n"
            "## Pending re-vote"), 1)
        sha = self.sh("git", "rev-parse", "HEAD", cwd=self.worktree).strip()
        state = self.state()
        state["phase6"]["verified_sha"] = sha
        self.write_state(state)
        (self.dir / "CODE_REVIEW.md").write_text(review.format(tree=self.tree()))
        (self.dir / "SECURITY_REVIEW.md").write_text(SECURITY_REVIEW.format(
            tree=self.tree()))
        self.spec_eval()
        self.lint()
        r = self.lib("pr-body", "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        body = self.dir / "pr-body.md"
        text = body.read_text()
        still = [ln for ln in text.splitlines() if "Still open" in ln]
        self.assertEqual(still, [("  - Still open: sorting crashed on a todo with no due "
                                  "date. (`src/sort.ts:4`); shipped at the user's call at "
                                  "the ready-for-review gate")])
        body.write_text(re.sub(r"<!-- WRITE: .*?-->", "Todos can carry a due date.", text))
        r = self.lib("pr-body", "--check", body, "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


class TemplateTest(unittest.TestCase):
    """The repo's own PR template and the ticket link in the generated body."""

    def setUp(self):
        sys.path.insert(0, str(SCRIPTS))
        self.cmd_pr = import_module("lib.cmd_pr")
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp()))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def write(self, rel, text):
        path = self.tmp / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def test_template_sections_are_added_answered_or_left_to_write(self):
        self.write(".GitHub/PULL_REQUEST_TEMPLATE.md",
                   "## Description\n<!-- what and why -->\n\n"
                   "## How has this been tested?\n<!-- describe -->\n\n"
                   "## Screenshots\n<!-- add screenshots for UI changes -->\n\n"
                   "## Checklist\nPlease check:\n- [x] I added tests\n- [ ] Docs updated\n")
        found = self.cmd_pr.find_template(self.tmp)
        self.assertIsNotNone(found)
        text = "\n".join(self.cmd_pr.template_sections(found))
        self.assertNotIn("Description", text)
        self.assertIn("## How has this been tested?\nSee _Acceptance conditions_", text)
        self.assertIn("## Screenshots\n<!-- WRITE: the repo's PR template asks for this "
                      "section (add screenshots for UI changes)", text)
        self.assertIn("## Checklist\n- [ ] I added tests\n- [ ] Docs updated\n"
                      "<!-- WRITE: tick each box", text)
        self.assertNotIn("Please check", text)

    def test_a_checklist_may_be_ticked_never_reworded(self):
        self.write("pull_request_template.md",
                   "## Testing\n- [ ] Ran it\n\n"  # a testing section is ours to fill
                   "## Checklist\n<!-- tick what applies -->\n- [ ] I added tests\n"
                   "- [ ] Docs updated\n")
        problems = self.cmd_pr.checklist_problems
        ok = "## Summary\nx\n\n## Checklist\n- [x] I added tests\n- [ ] Docs updated\n"
        self.assertEqual(problems(ok, self.tmp), [])
        self.assertEqual(problems(ok.replace("- [ ] Docs", "- [X] Docs"), self.tmp), [])
        for bad in (ok.replace("I added tests", "I added unit tests"),
                    ok.replace("- [ ] Docs updated\n", ""),
                    ok + "- [x] Reviewed by a person\n",
                    ok.replace("- [x] I added tests\n- [ ] Docs updated",
                               "- [ ] Docs updated\n- [x] I added tests")):
            self.assertEqual(len(problems(bad, self.tmp)), 1, bad)
            self.assertIn("keep the PR template's items", problems(bad, self.tmp)[0])
        self.assertIn("missing", problems("## Summary\nx\n", self.tmp)[0])

    def test_a_generated_checklist_passes_as_it_is(self):
        # Two sections under one heading, and an item the secret filter drops.
        self.write("pull_request_template.md",
                   "## Frontend\n### Checklist\n- [ ] a11y checked\n"
                   "## Backend\n### Checklist\n- [ ] migrations reversible\n"
                   "- [ ] No hardcoded password: verified by grep\n")
        lines = self.cmd_pr.template_sections(self.cmd_pr.find_template(self.tmp))
        body = self.cmd_pr.clean("\n".join(lines), str(self.tmp))
        self.assertEqual(body.count("## Checklist"), 2)
        self.assertEqual(self.cmd_pr.checklist_problems(body, self.tmp), [])
        swapped = body.replace("a11y checked", "X").replace("migrations reversible",
                                                            "a11y checked")
        self.assertEqual(len(self.cmd_pr.checklist_problems(swapped, self.tmp)), 2)

    def test_no_template_checklist_no_checklist_problem(self):
        self.assertEqual(self.cmd_pr.checklist_problems("## Summary\n", self.tmp), [])
        self.write("pull_request_template.md", "## Risk\nDescribe it.\n")
        self.assertEqual(self.cmd_pr.checklist_problems("## Summary\n", self.tmp), [])

    def test_a_txt_template_is_found_and_md_wins_beside_it(self):
        # GitHub accepts a .txt template in the same places as a .md one.
        txt = self.write(".github/Pull_Request_Template.TXT", "## Rollout\nThe plan.\n")
        self.assertEqual(self.cmd_pr.find_template(self.tmp), txt)
        self.assertIn("## Rollout", self.cmd_pr.template_sections(txt))
        md = self.write(".github/pull_request_template.md", "## Risk\n")
        self.assertEqual(self.cmd_pr.find_template(self.tmp), md)
        self.write("pull_request_template.md", "## Root\n")
        self.assertEqual(self.cmd_pr.find_template(self.tmp), md)  # .github/ first

    def test_a_template_folder_is_never_the_default(self):
        # GitHub applies a template from this folder only when a PR asks for it.
        self.write(".github/PULL_REQUEST_TEMPLATE/bug.md", "## Bug\n")
        self.write(".github/PULL_REQUEST_TEMPLATE/feature.md", "## Feature\n")
        self.assertIsNone(self.cmd_pr.find_template(self.tmp))
        (self.tmp / ".github/PULL_REQUEST_TEMPLATE/feature.md").unlink()
        self.assertIsNone(self.cmd_pr.find_template(self.tmp))

    def test_headings_in_comments_and_code_blocks_are_not_sections(self):
        found = self.write("pull_request_template.md",
                           "## Rollout\n<!--\n## Example heading in a comment\n-->\n"
                           "```md\n# not a heading\n```\n~~~\n## nor this\n~~~\n")
        lines = self.cmd_pr.template_sections(found)
        self.assertEqual([ln for ln in lines if ln.startswith("#")], ["## Rollout"])
        self.assertNotIn("not a heading", "\n".join(lines))

    def test_a_section_s_plain_instructions_reach_its_write_line(self):
        found = self.write("pull_request_template.md",
                           "## Risk\nDescribe the risk and the rollout plan.\n")
        self.assertIn("## Risk\n<!-- WRITE: the repo's PR template asks for this section "
                      "(Describe the risk and the rollout plan.)",
                      "\n".join(self.cmd_pr.template_sections(found)))

    def test_no_template_adds_nothing(self):
        self.assertEqual(self.cmd_pr.template_sections(self.cmd_pr.find_template(self.tmp)),
                         [])


class ReviewFindingsTest(unittest.TestCase):
    """Which review rows `pr publish` posts, without GitHub."""

    def test_open_and_advisory_rows_are_posted_fixed_ones_are_not(self):
        sys.path.insert(0, str(SCRIPTS))
        cmd_pr = import_module("lib.cmd_pr")
        tmp = Path(os.path.realpath(tempfile.mkdtemp()))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        code = OPEN_REVIEW.replace(
            "| open |\n",
            "| open |\n| C2 | blank title | `src/save.ts:3` | correctness | 3/3 | High "
            "| fixed |\n", 1)
        (tmp / "CODE_REVIEW.md").write_text(code.format(tree="0" * 40))
        sec = SECURITY_MUST_FIX.replace(
            "| S2 | session token not rotated |",
            "| S4 | verbose error | `src/err.ts:2` | introduced | Low | confirmed "
            "| advisory | — |\n| S2 | session token not rotated |")
        (tmp / "SECURITY_REVIEW.md").write_text(sec.format(tree="0" * 40))
        found = cmd_pr.review_findings(tmp, {"marks": {}})
        self.assertEqual(sorted(f["where"] for f in found),
                         ["src/due.ts:9", "src/err.ts:2", "src/sort.ts:4"])

    def test_a_finding_is_posted_in_its_plain_words(self):
        sys.path.insert(0, str(SCRIPTS))
        cmd_pr = import_module("lib.cmd_pr")
        tmp = Path(os.path.realpath(tempfile.mkdtemp()))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        review = OPEN_REVIEW.replace("## Pending re-vote", (
            "### C1 — null due date crashes sort\n"
            "In plain words: sorting crashed on a todo with no due date.\n\n"
            "## Pending re-vote"), 1)
        (tmp / "CODE_REVIEW.md").write_text(review.format(tree="0" * 40))
        found = cmd_pr.review_findings(tmp, {"marks": {}})
        self.assertIn("sorting crashed on a todo with no due date", found[0]["text"])

    def test_others_sent_to_a_separate_pr_are_posted(self):
        sys.path.insert(0, str(SCRIPTS))
        cmd_pr = import_module("lib.cmd_pr")
        tmp = Path(os.path.realpath(tempfile.mkdtemp()))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        rows = "".join(f"| S{i} | old issue {i} | `src/old{i}.ts:{i}` | pre-existing | Medium "
                       "| confirmed | for the user | — |\n" for i in range(5, 9))
        sec = SECURITY_REVIEW.replace("| S2 | session token not rotated |",
                                      rows + "| S2 | session token not rotated |")
        (tmp / "SECURITY_REVIEW.md").write_text(sec.format(tree="0" * 40))
        found = cmd_pr.review_findings(tmp, {"marks": {"triage-others": {"value": "separate"}}})
        self.assertEqual(len(found), 3)  # the gate asked two one by one; three were "Others"

    def test_a_template_hint_cannot_end_the_write_comment(self):
        sys.path.insert(0, str(SCRIPTS))
        cmd_pr = import_module("lib.cmd_pr")
        tmp = Path(os.path.realpath(tempfile.mkdtemp()))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        (tmp / "pull_request_template.md").write_text("## Rollout\n<!-- flag a--b -->\n")
        line = cmd_pr.template_sections(cmd_pr.find_template(tmp))[1]
        self.assertEqual(line.count("--"), 2)  # only the comment's own <!-- and -->

    def test_the_ticket_link(self):
        sys.path.insert(0, str(SCRIPTS))
        cmd_pr = import_module("lib.cmd_pr")
        self.assertEqual(cmd_pr.ticket_link({"ticket": "none"}), "")
        self.assertEqual(cmd_pr.ticket_link({}), "")
        self.assertEqual(cmd_pr.ticket_link({"ticket": "TODO-7"}), "Ticket: TODO-7")


class TicketTest(NextCase):
    to_body = ShipTest.to_body
    open_pr = ShipTest.open_pr
    draft_pr = ShipTest.draft_pr
    refresh_body = ShipTest.refresh_body
    reviewed_pr = ShipTest.reviewed_pr
    mark_ready = ShipTest.mark_ready
    published = ShipTest.published

    def ship_ready(self):
        ShipTest.ship_ready(self)
        state = self.state()
        state["task"].update(ticket="TODO-7", ticket_url="https://acme.atlassian.net/browse/TODO-7")
        self.write_state(state)

    def test_the_repo_s_pr_template_reaches_the_body(self):
        self.ship_ready()
        (self.worktree / ".github").mkdir(exist_ok=True)
        (self.worktree / ".github" / "pull_request_template.md").write_text(
            "## Screenshots\n<!-- for UI changes -->\n")
        sha = self.sh("git", "rev-parse", "HEAD", cwd=self.worktree).strip()
        state = self.state()
        state["phase6"]["verified_sha"] = sha
        self.write_state(state)
        (self.dir / "CODE_REVIEW.md").write_text(CLEAN_REVIEW.format(tree=self.tree()))
        (self.dir / "SECURITY_REVIEW.md").write_text(SECURITY_REVIEW.format(tree=self.tree()))
        self.spec_eval()
        self.lint()
        r = self.lib("pr-body", "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        text = (self.dir / "pr-body.md").read_text()
        self.assertIn("## Screenshots\n<!-- WRITE: the repo's PR template asks for this "
                      "section (for UI changes)", text)
        self.assertLess(text.index("## Screenshots"), text.index("## Assumptions"))

    def test_publish_refuses_a_reworded_checklist_and_takes_a_ticked_one(self):
        _, _, _, body = self.to_body()
        (self.worktree / "pull_request_template.md").write_text(
            "## Checklist\n- [ ] I added tests\n- [ ] Docs updated\n")
        r = self.lib("pr-body", "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        text = body.read_text()
        self.assertIn("## Checklist\n- [ ] I added tests\n- [ ] Docs updated\n"
                      "<!-- WRITE: tick each box", text)
        text = re.sub(r"<!-- WRITE: .*?-->", "Todos can carry a due date.", text)
        body.write_text(text.replace("- [ ] Docs updated", "- [x] Docs updated if needed"))
        r = self.lib("pr-body", "--check", body, "--dir", self.dir)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("keep the PR template's items", r.stdout)
        r = self.autodev("pr", "publish", "--dir", self.dir)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("keep the PR template's items", r.stdout)
        self.assertIsNone(self.state()["phase6"].get("pr"))
        body.write_text(text.replace("- [ ] I added tests", "- [x] I added tests"))
        r = self.autodev("pr", "publish", "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.state()["phase6"]["pr"], 12)

    def checklist_on_open_pr(self, live):
        """A reworded checklist published to an open PR whose description is `live`."""
        _, _, _, body = self.to_body(first=[
            {"args": ["pr", "list"], "stdout": '[{"number": 12}]'},
            {"args": ["pr", "view", "12", "--json", "body"],
             "stdout": json.dumps({"body": live})},
            {"args": ["pr", "edit"], "stdout": ""}])
        (self.worktree / "pull_request_template.md").write_text(
            "## Checklist\n- [ ] Docs updated\n")
        r = self.lib("pr-body", "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        text = re.sub(r"<!-- WRITE: .*?-->", "Todos can carry a due date.",
                      body.read_text())
        body.write_text(text.replace("- [ ] Docs updated", "- [x] Docs in the wiki"))
        return self.autodev("pr", "publish", "--dir", self.dir)

    def test_a_person_s_edits_to_a_live_checklist_stand(self):
        r = self.checklist_on_open_pr("## Summary\nBy hand.\n\n## Checklist\n"
                                      "- [x] Docs updated in the wiki\n")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        log = [json.loads(ln) for ln in (self.tmp / "gh.log").read_text().splitlines()]
        sent = next(e["files"] for e in log if e["args"][:2] == ["pr", "edit"])
        self.assertIn("- [x] Docs updated in the wiki", "".join(sent.values()))

    def test_an_empty_live_description_still_checks_the_checklist(self):
        r = self.checklist_on_open_pr("")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("keep the PR template's items", r.stdout)

    def test_the_ticket_is_linked_in_the_summary(self):
        self.open_pr()
        text = (self.dir / "pr-body.md").read_text()
        summary = text.split("## Acceptance conditions")[0]
        self.assertIn("Ticket: [TODO-7](https://acme.atlassian.net/browse/TODO-7)", summary)

    def test_the_verifier_s_reasons_may_name_an_id(self):
        # A survivor's judgment quotes the verifier, who names conditions by ID.
        write = self.spec_eval

        def spec_eval(**kw):
            write(**kw)
            path = self.dir / "SPEC_EVAL.md"
            path.write_text(path.read_text().replace(
                "Equivalent — no two todos share a date",
                "Test gap — the C1 checks still pass with the mutant in place"))
        self.spec_eval = spec_eval
        self.open_pr()
        text = (self.dir / "pr-body.md").read_text()
        self.assertIn("not caught: the C1 checks still pass", text)

    def test_gate_output_about_scratch_files_stays_out_of_the_body(self):
        # A formatter over `.` lists the git-ignored .auto-dev/ files; cleanup
        # passes the check, and publish must not refuse the body for them.
        self.lint_tail = ("[warn] .auto-dev/PLAN.md\n[warn] .auto-dev/state.json\n"
                          "[warn] Code style issues found in 2 files.")
        self.open_pr()
        gate = (self.dir / "pr-body.md").read_text().split("## Quality gate")[1]
        self.assertNotIn(".auto-dev/", gate)
        self.assertIn("Code style issues found in 2 files.", gate)
        self.assertIn("(2 line(s) about git-ignored pipeline files left out)", gate)


class InlineCommentsTest(NextCase):
    to_body = ShipTest.to_body
    open_pr = ShipTest.open_pr
    draft_pr = ShipTest.draft_pr
    refresh_body = ShipTest.refresh_body
    reviewed_pr = ShipTest.reviewed_pr
    mark_ready = ShipTest.mark_ready
    published = ShipTest.published
    review_text = CLEAN_REVIEW.replace(
        "|----|---------|----------|----------|-------|------------|--------------|\n",
        "|----|---------|----------|----------|-------|------------|--------------|\n"
        "| C5 | magic number | `due.ts:1` | style | 1/3 | Low | style only |\n"
        "| C6 | slow loop | `app.ts:40` | performance | 1/3 | Medium | not on a hot path |\n")

    inline = True

    def ship_ready(self):
        ShipTest.ship_ready(self)
        state = self.state()
        state["settings"]["inline_comments"] = self.inline
        self.write_state(state)

    def calls(self):
        return [json.loads(ln) for ln in (self.tmp / "gh.log").read_text().splitlines()]

    def test_findings_go_inline_in_the_diff_and_the_rest_in_one_comment(self):
        sha, _ = self.open_pr(extra=[
            {"args": ["api", "--method", "POST"], "stdout": "{}"},
            {"args": ["pr", "comment"], "stdout": "https://x/pull/12#issuecomment-5\n"}])
        calls = self.calls()
        review = [c for c in calls if c["args"][:3] == ["api", "--method", "POST"]]
        self.assertEqual(len(review), 1)
        self.assertIn("repos/{owner}/{repo}/pulls/12/reviews", review[0]["args"])
        payload = json.loads(next(iter(review[0]["files"].values())))
        self.assertEqual(payload["commit_id"], sha)
        self.assertEqual(payload["event"], "COMMENT")
        self.assertEqual([(c["path"], c["line"]) for c in payload["comments"]],
                         [("due.ts", 1)])
        self.assertIn("**Advisory** (confidence Low): magic number",
                      payload["comments"][0]["body"])
        general = [c for c in calls if c["args"][:2] == ["pr", "comment"]]
        self.assertEqual(len(general), 1)
        comment = next(iter(general[0]["files"].values()))
        self.assertIn("`app.ts:40`: **Advisory** (confidence Medium): slow loop", comment)
        # everything the pipeline posts ends with the marker the triager skips
        sys.path.insert(0, str(SCRIPTS))
        from importlib import import_module as load
        marker = load("lib.cmd_pr").MARKER
        self.assertEqual(comment.rstrip("\n").split("\n")[-1], marker)
        self.assertTrue(payload["body"].endswith(marker))
        self.assertTrue(payload["comments"][0]["body"].endswith(marker))
        self.assertEqual(self.state()["phase6"]["inline"]["inline"], 1)

    def test_findings_are_posted_once_the_ready_gate_is_answered_separate_pr_included(self):
        self.reviewed_pr(extra=[
            {"args": ["api", "--method", "POST"], "stdout": "{}"},
            {"args": ["pr", "comment"], "stdout": "https://x/pull/12#issuecomment-5\n"}])
        self.assertNotIn("inline", self.state()["phase6"])  # the gate is not asked yet
        self.mark_ready("S2: Separate PR (note it as a follow-up)")
        self.assertIn("inline", self.state()["phase6"])
        general = [c for c in self.calls() if c["args"][:2] == ["pr", "comment"]]
        comment = next(iter(general[-1]["files"].values()))
        self.assertIn("left for a separate PR", comment)
        self.assertIn("src/auth.ts:88", comment)

    def test_a_pre_existing_finding_is_posted_only_when_sent_to_a_separate_pr(self):
        sys.path.insert(0, str(SCRIPTS))
        cmd_pr = import_module("lib.cmd_pr")
        (self.dir / "SECURITY_REVIEW.md").write_text(SECURITY_REVIEW.format(tree="0" * 40))
        state = {"marks": {"triage-S2": {"value": "ignore"}}}
        self.assertEqual(cmd_pr.review_findings(self.dir, state), [])
        state["marks"]["triage-S2"]["value"] = "separate"
        found = cmd_pr.review_findings(self.dir, state)
        self.assertEqual([(f["path"], f["line"]) for f in found], [("src/auth.ts", 88)])
        self.assertIn("left for a separate PR", found[0]["text"])

    def test_a_failed_post_is_reported_not_fatal(self):
        self.open_pr(extra=[
            {"args": ["api", "--method", "POST"], "stderr": "Unprocessable", "exit": 1},
            {"args": ["pr", "comment"], "stderr": "Forbidden", "exit": 1}])
        inline = self.state()["phase6"]["inline"]
        self.assertEqual((inline["inline"], inline["general"]), (0, 0))
        self.assertIn("Unprocessable", inline["error"])
        self.assertIn("Forbidden", inline["error"])

    def test_a_republish_posts_the_findings_only_once(self):
        self.open_pr(
            first=[{"args": ["pr", "view", "12", "--json", "body"], "stdout": '{"body": ""}'}],
            extra=[{"args": ["api", "--method", "POST"], "stdout": "{}"},
                   {"args": ["pr", "comment"], "stdout": "https://x/pull/12#issuecomment-5\n"},
                   {"args": ["pr", "edit"], "stdout": ""}])
        r = self.autodev("pr", "publish", "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        calls = self.calls()
        self.assertEqual(len([c for c in calls if c["args"][:1] == ["api"]]), 1)
        self.assertEqual(len([c for c in calls if c["args"][:2] == ["pr", "comment"]]), 1)

    def test_a_refused_review_moves_every_finding_to_the_general_comment(self):
        self.open_pr(extra=[
            {"args": ["api", "--method", "POST"], "stderr": "Unprocessable", "exit": 1},
            {"args": ["pr", "comment"], "stdout": "https://x/pull/12#issuecomment-5\n"}])
        inline = self.state()["phase6"]["inline"]
        self.assertEqual((inline["inline"], inline["general"]), (0, 2))
        self.assertIn("Unprocessable", inline["error"])
        general = [c for c in self.calls() if c["args"][:2] == ["pr", "comment"]]
        comment = next(iter(general[0]["files"].values()))
        self.assertIn("`due.ts:1`", comment)
        self.assertIn("`app.ts:40`", comment)

    def test_the_publish_output_says_how_findings_were_posted(self):
        _sha, _url, _out, body = self.to_body(extra=[
            {"args": ["api", "--method", "POST"], "stdout": "{}"},
            {"args": ["pr", "comment"], "stdout": "https://x/pull/12#issuecomment-5\n"}])
        body.write_text(re.sub(r"<!-- WRITE: .*?-->", "Todos can carry a due date.",
                               body.read_text()))
        r = self.autodev("pr", "publish", "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("posted", r.stdout)  # the draft opens before any review
        self.assertNotIn("inline", self.state()["phase6"])
        self.review_clean()
        self.refresh_body()  # the reviews are in the description, still nothing posted
        self.assertNotIn("inline", self.state()["phase6"])
        self.after(self.next(5), "Mark ready for review")
        self.assertIn("pr publish", self.next(0)["ACTION"])
        gh = json.loads((self.tmp / "gh.json").read_text())
        self.script_gh([{"args": ["pr", "view", "12", "--json", "body"],
                         "stdout": json.dumps({"body": self.published()})}] + gh)
        r = self.autodev("pr", "publish", "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("1 posted inline, 1 in a general comment", r.stdout)

    def test_a_secret_looking_finding_does_not_blank_the_others(self):
        self.review_text = self.review_text.replace(
            "| C6 |", "| C7 | token = abcdef1234567890XYZ | `due.ts:1` | security | 1/3 "
            "| Low | test data |\n| C6 |")
        self.open_pr(extra=[
            {"args": ["api", "--method", "POST"], "stdout": "{}"},
            {"args": ["pr", "comment"], "stdout": "https://x/pull/12#issuecomment-5\n"}])
        review = [c for c in self.calls() if c["args"][:3] == ["api", "--method", "POST"]]
        payload = json.loads(next(iter(review[0]["files"].values())))
        self.assertEqual([c["body"].split("\n")[0] for c in payload["comments"]],
                         ["**Advisory** (confidence Low): magic number"])
        inline = self.state()["phase6"]["inline"]
        self.assertEqual((inline["inline"], inline["general"], inline["error"]), (1, 1, ""))

    def test_the_user_s_diff_settings_do_not_hide_the_diff(self):
        for key, value in (("diff.noprefix", "true"), ("color.diff", "always"),
                           ("color.ui", "always")):
            self.sh("git", "config", key, value, cwd=self.worktree)
        self.open_pr(extra=[
            {"args": ["api", "--method", "POST"], "stdout": "{}"},
            {"args": ["pr", "comment"], "stdout": "https://x/pull/12#issuecomment-5\n"}])
        inline = self.state()["phase6"]["inline"]
        self.assertEqual((inline["inline"], inline["general"]), (1, 1))

    def test_nothing_is_posted_when_the_key_is_off(self):
        self.inline = False
        self.open_pr()
        self.assertFalse([c for c in self.calls() if c["args"][:1] == ["api"]
                          or c["args"][:2] == ["pr", "comment"]])
        self.assertNotIn("inline", self.state()["phase6"])


class CiTest(NextCase):
    ship_ready = ShipTest.ship_ready
    to_body = ShipTest.to_body
    open_pr = ShipTest.open_pr
    draft_pr = ShipTest.draft_pr
    refresh_body = ShipTest.refresh_body
    reviewed_pr = ShipTest.reviewed_pr
    mark_ready = ShipTest.mark_ready
    published = ShipTest.published

    def test_red_ci_is_triaged_and_corrected_after_the_commit(self):
        state = self.state()
        state["settings"]["ci"] = "github"
        self.write_state(state)
        checks = [{"name": "test", "state": "FAILURE", "bucket": "fail",
                   "link": "https://ci/1"}]
        _sha, _ = self.reviewed_pr(extra=[{"args": ["pr", "checks"],
                                      "stdout": json.dumps(checks)}])
        out = self.next(0)
        self.assertIn("ci-watch", out["ACTION"])
        r = self.autodev("ci-watch", "--dir", self.dir, "--max-wait", "0")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        out, jobs = self.expect("triager")
        self.assertEqual(self.sets(*jobs[0])["failing"], "test — https://ci/1")
        (self.dir / "triage" / "ci-1.md").write_text(
            "# Required changes\n1. Handle a missing due date in src/sort.ts\n")
        self.answer(*jobs[0], "CODE", blockers="0", acceptance_checks="0",
                    triage_file=str(self.dir / "triage" / "ci-1.md"), checks_file="none")
        out, jobs = self.expect("coder")
        (self.worktree / "sort.ts").write_text("export const sort = 1;\n")
        self.answer(*jobs[0], "BUILT", blocked="0", test_changes="none")
        self.assertEqual(self.sets(*jobs[0])["corrections_file"],
                         f"{self.dir}/triage/ci-1.md")
        self.assertIn("ci-1", out["BUDGET"])
        self.quality_gate()
        out, jobs = self.reviewers()
        self.assertEqual(self.sets(*jobs[0])["scope"], "after-commit")
        self.assertEqual(self.sets(*self.security_job)["focus"],
                         "the uncommitted correction (the working tree against HEAD)")

    def test_a_pending_watch_goes_back_through_next(self):
        state = self.state()
        state["settings"]["ci"] = "github"
        self.write_state(state)
        pending = [{"name": "test", "state": "PENDING", "bucket": "pending", "link": ""}]
        self.reviewed_pr(extra=[{"args": ["pr", "checks"], "stdout": json.dumps(pending)}])
        out = self.next(0)
        self.assertIn("ci-watch", out["ACTION"])
        self.assertIn("then run AFTER whatever it exits", out["ACTION"])
        self.assertNotIn("run it again", out["ACTION"])
        self.assertEqual(len(out["AFTER"]), 1)
        self.assertIn(" next", out["AFTER"][0])
        r = self.autodev("ci-watch", "--dir", self.dir, "--max-wait", "0")
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertIn("run `next`, which watches again", r.stdout)
        self.assertNotIn("run ci-watch again", r.stdout)
        self.assertIn("ci-watch", self.next(0)["ACTION"])

    def test_red_ci_with_no_round_left_stops_and_names_the_check(self):
        state = self.state()
        state["settings"]["ci"] = "github"
        self.write_state(state)
        checks = [{"name": "test", "state": "FAILURE", "bucket": "fail",
                   "link": "https://ci/1"}]
        self.reviewed_pr(extra=[{"args": ["pr", "checks"], "stdout": json.dumps(checks)}])
        self.next(0)
        self.autodev("ci-watch", "--dir", self.dir, "--max-wait", "0")
        _, jobs = self.expect("triager")
        state = self.state()
        state["budget"]["remaining"] = 0
        state["settings"]["checkpoint_events"] = 1  # the stop still wins
        self.write_state(state)
        (self.dir / "triage" / "ci-1.md").write_text("# Required changes\n1. x\n")
        self.answer(*jobs[0], "CODE", blockers="0", acceptance_checks="0",
                    triage_file=str(self.dir / "triage" / "ci-1.md"), checks_file="none")
        report = " ".join(self.next(4)["REPORT"])
        self.assertIn("Red checks: test", report)
        self.assertIn("Red checks: test — https://ci/1", report)
        self.assertNotIn("hold", report)

    def test_rounds_added_after_the_commit_fix_ci_not_findings_shipped_past(self):
        state = self.state()
        state["settings"]["ci"] = "github"
        self.write_state(state)
        checks = [{"name": "test", "state": "FAILURE", "bucket": "fail",
                   "link": "https://ci/1"}]
        self.reviewed_pr(extra=[{"args": ["pr", "checks"], "stdout": json.dumps(checks)}])
        self.next(0)
        self.autodev("ci-watch", "--dir", self.dir, "--max-wait", "0")
        _, jobs = self.expect("triager")
        # The review pass on the draft ran out of rounds: its must-fix finding
        # went to the ready-for-review gate.
        (self.dir / "CODE_REVIEW.md").write_text(OPEN_REVIEW.format(tree=self.tree()))
        state = self.state()
        state["budget"]["remaining"] = 0
        state["phase6"]["exhausted"] = {"seq": 1, "open": ["x"]}
        self.write_state(state)
        (self.dir / "triage" / "ci-1.md").write_text("# Required changes\n1. x\n")
        self.answer(*jobs[0], "CODE", blockers="0", acceptance_checks="0",
                    triage_file=str(self.dir / "triage" / "ci-1.md"), checks_file="none")
        out = self.next(4)
        self.raise_from_report(out, 1)
        out, jobs = self.expect("coder")
        self.assertIn("spent `ci-1`", out["BUDGET"])
        self.assertEqual(self.sets(*jobs[0])["corrections_file"],
                         str(self.dir / "triage" / "ci-1.md"))


    @staticmethod
    def checks(started, **extra):
        return {"args": ["pr", "checks"], **extra, "stdout": json.dumps(
            [{"name": "test", "state": "SUCCESS", "bucket": "pass", "link": "https://ci/1",
              "startedAt": started}])}

    GREEN = (checks.__func__("2999-01-01T00:00:00Z"),)  # started after any mark

    def github_ci(self):
        state = self.state()
        state["settings"]["ci"] = "github"
        self.write_state(state)

    def watch(self, code=0):
        self.assertIn("ci-watch", self.next(0)["ACTION"])
        r = self.autodev("ci-watch", "--dir", self.dir, "--max-wait", "0")
        self.assertEqual(r.returncode, code, r.stdout + r.stderr)

    def ready(self, extra=None):
        """The reviewed draft, CI watched on it, then the PR marked ready."""
        self.github_ci()
        sha, _ = self.reviewed_pr(extra=extra or self.GREEN)
        self.watch()  # CI on the draft, before the ready-for-review gate
        self.mark_ready()
        return sha

    def no_comments(self):
        self.expect("triager", "TRIAGED", blockers="0", acceptance_checks="0",
                    triage_file="none", checks_file="none")

    def test_ci_is_watched_again_once_the_pr_is_ready(self):
        self.ready()
        self.watch()  # workflows that skip drafts run now
        self.no_comments()
        self.assertIn("main gate", self.next(5)["QUESTION"])

    def test_the_draft_s_green_checks_do_not_count_once_the_pr_is_ready(self):
        old = self.checks("2000-01-01T00:00:00Z", times=2)
        self.ready(extra=[old, *self.GREEN])
        self.watch(3)  # only the draft's checks so far: still pending
        self.watch()  # a check started after the mark: green
        self.no_comments()
        self.assertIn("main gate", self.next(5)["QUESTION"])

    def test_a_resume_after_the_merge_goes_on_from_the_merge(self):
        sha = self.ready()
        self.watch()
        self.no_comments()
        self.after(self.next(5), "Merge PR to main")
        r = self.autodev("merge-pr", "--pr", "12", "--sha", sha, "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        state = self.state()
        state["phase6"]["ci"]["status"] = "timeout"  # nothing before the merge re-runs
        self.write_state(state)
        self.resume()
        out = self.next(0)
        self.assertIn("mark main-ci", out["AFTER"][0])

    def test_a_failed_findings_post_reaches_the_final_report(self):
        sha = self.ready()
        self.watch()
        self.no_comments()
        self.after(self.next(5), "Merge PR to main")
        r = self.autodev("merge-pr", "--pr", "12", "--sha", sha, "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        state = self.state()
        state["phase6"]["inline"] = {"sha": sha, "inline": 0, "general": 0,
                                     "error": "general comment: Forbidden"}
        self.write_state(state)
        self.assertIn("mark main-ci", self.next(0)["AFTER"][0])
        r = self.autodev("mark", "main-ci", "--value", "green", "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        out = self.next(0)
        self.assertIn("final report", out["ACTION"])
        self.assertIn("could not all be posted on the PR (general comment: Forbidden)",
                      out["ACTION"])

    def test_the_main_gate_comes_next_and_shows_only_people_s_comments(self):
        self.ready()
        self.watch()
        self.no_comments()
        # A staging branch on origin is ignored: the next gate is the main gate.
        self.sh("git", "push", "-q", "origin", "origin/main:refs/heads/staging",
                cwd=self.worktree)
        sys.path.insert(0, str(SCRIPTS))
        marker = import_module("lib.cmd_pr").MARKER
        responses = json.loads((self.tmp / "gh.json").read_text())
        sha = self.state()["phase6"]["verified_sha"]
        responses.insert(0, {"args": ["pr", "view", "12", "--json"], "stdout": json.dumps({
            "url": "https://github.com/acme/app/pull/12", "isDraft": False,
            "state": "OPEN", "headRefOid": sha,
            "comments": [{"body": f"Command output\n\n{marker}"}, {"body": "LGTM"}],
            "reviews": [{"body": f"Findings\n\n{marker}"}]})})
        self.script_gh(responses)
        out = self.next(5)
        summary = " ".join(out["SUMMARY"])
        self.assertIn("main", out["QUESTION"])
        self.assertNotIn("staging", (out["QUESTION"] + summary).lower())
        self.assertIn("1 human review(s)/comment(s)", summary)

    def test_red_ci_the_code_cannot_fix_holds_before_jira(self):
        self.github_ci()
        checks = [{"name": "test", "state": "FAILURE", "bucket": "fail",
                   "link": "https://ci/1"}]
        self.reviewed_pr(extra=[{"args": ["pr", "checks"], "stdout": json.dumps(checks)}])
        self.watch(1)
        self.expect("triager", "INFRA", blockers="0", acceptance_checks="0",
                    triage_file="none", checks_file="none")
        report = " ".join(self.next(4)["REPORT"])
        self.assertIn("INFRA", report)
        self.assertIn("triage/ci-1.md", report)
        self.assertIn("The run stops here", report)

    def test_a_secret_ci_failure_stops_and_continue_watches_again(self):
        self.github_ci()
        checks = [{"name": "test", "state": "FAILURE", "bucket": "fail",
                   "link": "https://ci/1"}]
        self.reviewed_pr(extra=[{"args": ["pr", "checks"], "stdout": json.dumps(checks)}])
        self.watch(1)
        self.expect("triager", "SECRET", blockers="0", acceptance_checks="0",
                    triage_file="none", checks_file="none")
        report = " ".join(self.next(4)["REPORT"])
        self.assertIn("Once the secret is fixed and CI re-run", report)
        self.assertNotIn("do not re-run", report)
        self.resume()
        self.assertIn("ci-watch", self.next(0)["ACTION"])

    def test_the_main_gate_shows_ci_that_timed_out_as_not_monitored(self):
        self.ready()
        state = self.state()
        state["phase6"]["ci"]["status"] = "timeout"
        state["phase6"]["ci"]["seq"] = state["events"] + 1
        self.write_state(state)
        self.no_comments()
        out = self.next(5)
        self.assertIn("CI: not monitored (timeout) — never assume green",
                      " ".join(out["SUMMARY"]))


class HumanAndMainGateTest(NextCase):
    ship_ready = ShipTest.ship_ready
    to_body = ShipTest.to_body
    open_pr = ShipTest.open_pr
    draft_pr = ShipTest.draft_pr
    refresh_body = ShipTest.refresh_body
    reviewed_pr = ShipTest.reviewed_pr
    mark_ready = ShipTest.mark_ready
    published = ShipTest.published

    def test_a_reviewer_blocker_becomes_a_correction(self):
        self.open_pr()
        _, jobs = self.expect("triager")
        self.assertEqual(next(b for b in self.state()["briefs"]
                              if (b["worker"], b["n"]) == jobs[0])["mode"], "human")
        (self.dir / "triage" / "human-1.md").write_text(
            "# Required changes\n1. c-77: keep the field name when it is empty\n")
        self.answer(*jobs[0], "TRIAGED", blockers="1", acceptance_checks="0",
                    triage_file=str(self.dir / "triage" / "human-1.md"), checks_file="none")
        out, jobs = self.expect("coder")
        self.assertEqual(self.sets(*jobs[0])["corrections_file"],
                         f"{self.dir}/triage/human-1.md")
        self.assertIn("human-1", out["BUDGET"])

    def push_outside(self, text):
        """Someone pushes a commit changing app.ts to the PR branch."""
        branch = self.state()["branch"]
        other = self.tmp / "other"
        if not other.exists():
            self.sh("git", "clone", "-q", "-b", branch, str(self.tmp / "origin.git"),
                    str(other))
        (other / "app.ts").write_text(text)
        self.sh("git", "commit", "-q", "-am", "reword", cwd=other)
        self.sh("git", "push", "-q", "origin", branch, cwd=other)
        return branch

    def held_then_pushed(self):
        """Eval 16 up to its stop; returns (old verified sha, PR url, branch)."""
        old, url = self.open_pr()
        self.expect("triager", "TRIAGED", blockers="0", acceptance_checks="0",
                    triage_file="none", checks_file="none")
        out = self.next(5)
        self.assertIn("main", out["QUESTION"])
        self.after(out, "Hold")
        self.next(4)
        branch = self.push_outside("export const one = 1; // reworded\n")
        self.resume()  # un-holds the main gate
        out = self.next(4)
        report = " ".join(out["REPORT"])
        self.assertIn("someone pushed", report)
        self.assertIn("app.ts", report)
        # The main gate is not asked: only how to go on from the stop.
        self.assertNotIn("main gate", out.get("QUESTION", ""))
        self.assertNotIn("Sign off", out.get("QUESTION", ""))
        self.assertNotIn("merge-pr", json.dumps(out))
        self.assertIn(f"merge --ff-only origin/{branch}", report)
        return old, url, branch

    def recheck(self, old, branch, edit=None):
        """The user brings the commits in; the re-check runs up to the commit
        action. `edit` is a file written during it, before the gate runs.
        Returns the new HEAD and the review pass."""
        self.sh("git", "merge", "-q", "--ff-only", f"origin/{branch}", cwd=self.worktree)
        head = self.sh("git", "rev-parse", "HEAD", cwd=self.worktree).strip()
        out = self.next(0)
        self.assertIn("quality-gate", out["ACTION"])  # the gate first, no worker
        self.assertEqual(self.state()["phase6"]["unverified_commit"], head)
        if edit:
            (self.worktree / edit).write_text("export const tidy = 1;\n")
        r = self.autodev("quality-gate", "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.panel()  # the verifier, three reviewers and the security reviewer
        p = self.state()["phase6"]["passes"][-1]
        self.assertEqual((p["scope"], p["since"]), ("outside", old))
        sets = self.sets("code-reviewer", max(n for w, n in (
            (b["worker"], b["n"]) for b in self.state()["briefs"]) if w == "code-reviewer"))
        self.assertEqual((sets["scope"], sets["files"], sets["since"]),
                         ("outside", ", ".join(p["files"]), old))
        self.assertIn("commit: run", self.next(0)["ACTION"])
        return head, p

    def to_main_gate(self, url, head):
        """From a verified `head` to the main gate asked again."""
        out = self.next(0)
        self.assertIn("push -u origin HEAD", out["ACTION"])
        self.sh("git", "push", "-q", "-u", "origin", "HEAD", cwd=self.worktree)
        self.after(out)
        self.script_gh(GH_OK + [
            {"args": ["repo", "view", "--json", "url"], "stdout": json.dumps({"url": url})},
            {"args": ["pr", "view", "12", "--json", "body"], "stdout": '{"body": ""}'},
            {"args": ["pr", "edit"], "stdout": ""},
            {"args": ["pr", "view", "12", "--json", "number,url,body"],
             "stdout": json.dumps({"number": 12, "url": f"{url}/pull/12",
                                   "body": f"Checked at commit {head}"})},
            {"args": ["pr", "view", "12", "--json"],
             "stdout": json.dumps({"url": f"{url}/pull/12", "isDraft": False,
                                   "state": "OPEN", "headRefOid": head})}])
        out = self.next(0)
        body = self.dir / "pr-body.md"
        self.assertIn(f"Checked at commit {head}", body.read_text())
        body.write_text(re.sub(r"<!-- WRITE: .*?-->", "Todos can carry a due date.",
                               body.read_text()))
        self.after(out)
        out = self.next(0)
        self.assertIn("pr publish", out["ACTION"])
        r = self.autodev("pr", "publish", "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.expect("triager", "TRIAGED", blockers="0", acceptance_checks="0",
                    triage_file="none", checks_file="none")
        out = self.next(5)
        self.assertIn("main", out["QUESTION"])
        self.assertIn(f"Head {head}", " ".join(out["SUMMARY"]))

    def verify_only(self, head):
        r = self.autodev("commit", "--message", "unused", "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(f"COMMITTED: {head}", r.stdout)  # verified, no new commit
        self.assertEqual(self.sh("git", "rev-parse", "HEAD", cwd=self.worktree).strip(), head)
        self.assertEqual(self.state()["phase6"]["verified_sha"], head)

    def test_an_outside_push_after_a_held_main_gate_is_re_checked_before_it_is_asked(self):
        # Eval 16: the main gate is held, someone pushes to the PR branch, and a
        # fresh session resumes the run.
        old, url, branch = self.held_then_pushed()
        self.sh("git", "fetch", "-q", "origin", cwd=self.worktree)
        before = self.state()
        self.sh("git", "merge", "-q", "--ff-only", f"origin/{branch}", cwd=self.worktree)
        r = self.autodev("next", "--explain", "--dir", self.dir)
        self.assertIn("re-check the PR branch's commits", r.stdout)
        self.assertEqual(self.state(), before)  # --explain writes nothing
        self.resume()
        head, p = self.recheck(old, branch)
        self.assertEqual(p["files"], ["app.ts"])
        self.verify_only(head)
        self.to_main_gate(url, head)

    def test_an_edit_made_while_re_checking_an_outside_push_is_reviewed(self):
        old, url, branch = self.held_then_pushed()
        head, p = self.recheck(old, branch, edit="other.ts")
        self.assertEqual(p["files"], ["app.ts", "other.ts"])  # the pass saw cleanup's edit
        r = self.autodev("commit", "--message", "chore: tidy", "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        new = self.state()["phase6"]["verified_sha"]
        self.assertNotEqual(new, head)  # cleanup's edit is committed on top
        self.to_main_gate(url, new)

    def test_a_second_outside_push_in_the_same_session_is_re_checked_too(self):
        old, url, branch = self.held_then_pushed()
        head, _ = self.recheck(old, branch)
        self.verify_only(head)
        self.to_main_gate(url, head)
        self.push_outside("export const one = 1; // reworded again\n")
        self.sh("git", "fetch", "-q", "origin", cwd=self.worktree)
        report = " ".join(self.next(4)["REPORT"])  # no resume: the same session
        self.assertIn("someone pushed", report)
        second, p = self.recheck(head, branch)  # not "stale twice running"
        self.assertEqual(p["files"], ["app.ts"])
        self.verify_only(second)


class ReVoteTest(NextCase):
    ship_ready = ShipTest.ship_ready
    to_body = ShipTest.to_body
    draft_pr = ShipTest.draft_pr
    published = ShipTest.published

    def test_lone_findings_are_re_voted_then_applied(self):
        self.draft_pr()
        _out, jobs = self.reviewers()
        for w, n in jobs:
            slot = self.sets(w, n)["reviewer"]
            (self.dir / "review" / "pass-1" / f"{slot}.md").write_text(r_report("x"))
            self.answer(w, n, "REVIEWED", findings="1", leads="0")
        (self.dir / "CODE_REVIEW.md").write_text(CODE_REVIEW.format(tree=self.tree()))
        self.expect("review-judge", "REVOTE", must_fix_open="1", revote="2")
        _, jobs = self.expect("code-reviewer")
        voters = sorted(self.sets(w, n)["reviewer"] for w, n in jobs)
        self.assertEqual(voters, ["R1", "R2", "R3"])
        for w, n in jobs:
            slot = self.sets(w, n)["reviewer"]
            self.assertIn("C", self.sets(w, n)["findings"])
            rows = "".join(f"| {fid} | disagree | not reachable |\n" for fid in ("C4", "C6")
                           if fid in self.sets(w, n)["findings"])
            (self.dir / "review" / "pass-1" / f"VOTES-{slot}.md").write_text(
                "| Finding | Vote | Reason |\n|---|---|---|\n" + rows)
            self.answer(w, n, "VOTED", findings="1", leads="0")
        _, jobs = self.expect("coder")  # C1 is still open: a correction
        text = (self.dir / "CODE_REVIEW.md").read_text()
        self.assertNotIn("| C4 | empty list indexed | `src/list.ts:42` | correctness | R1", text)
        self.assertIn("lone finding; re-vote 1/3", text)

    def test_a_re_voter_that_fails_twice_stops(self):
        self.draft_pr()
        _out, jobs = self.reviewers()
        for w, n in jobs:
            slot = self.sets(w, n)["reviewer"]
            (self.dir / "review" / "pass-1" / f"{slot}.md").write_text(r_report("x"))
            self.answer(w, n, "REVIEWED", findings="1", leads="0")
        (self.dir / "CODE_REVIEW.md").write_text(CODE_REVIEW.format(tree=self.tree()))
        self.expect("review-judge", "REVOTE", must_fix_open="1", revote="2")
        _, jobs = self.expect("code-reviewer")
        for w, n in jobs:
            slot = self.sets(w, n)["reviewer"]
            if slot == "R3":
                self.answer(w, n, "", status="failed")
                continue
            rows = "".join(f"| {fid} | disagree | not reachable |\n" for fid in ("C4", "C6")
                           if fid in self.sets(w, n)["findings"])
            (self.dir / "review" / "pass-1" / f"VOTES-{slot}.md").write_text(
                "| Finding | Vote | Reason |\n|---|---|---|\n" + rows)
            self.answer(w, n, "VOTED", findings="1", leads="0")
        _, jobs = self.expect("code-reviewer", "", status="failed")  # one more try
        self.assertEqual([self.sets(*j)["reviewer"] for j in jobs], ["R3"])
        out = self.next(4)
        self.assertIn("R3 (failed twice)", " ".join(out["REPORT"]))


class RiskRecheckTest(NextCase):
    """Once the build is verified (the end of Phase 5), `next` re-checks the
    risk tier from the diff of the code that ships: it only goes up."""

    def standard_session(self, risk="standard"):
        text = PLAN.replace("Risk: high", f"Risk: {risk}")
        text = text.split("## Security/Compliance criteria")[0] + \
            "## Size check" + text.split("## Size check")[1]
        (self.dir / "PLAN.md").write_text(text)
        self.expect("planner", "FITS", **{**PLANNED, "risk": risk})
        self.critic("APPROVE", risk=risk)
        if risk == "high":
            self.after(self.next(5), "Approve & build")
        self.expect("acceptance-tester", "WRITTEN", checks="4", ambiguous="none")
        self.enter_stage("build")
        self.expect("coder", "BUILT", blocked="0", test_changes="none")

    def write(self, rel, text="export const x = 1;\n"):
        path = self.worktree / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def verified(self):
        """The quality gate is green: Phase 5 ends with the re-check."""
        out = self.next(0)
        self.assertIn("quality-gate", out["ACTION"])
        self.assertNotIn("risk_recheck", self.state())  # not before the gate
        r = self.autodev("quality-gate", "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.enter_stage("ship")
        return self.state()

    def test_a_small_neutral_change_stays_standard(self):
        self.standard_session()
        self.write("src/due.ts")
        state = self.verified()
        self.assertEqual(state["risk_recheck"]["high"], False)
        self.assertFalse(state["high_risk"])

    def test_a_high_tier_stays_high_on_a_neutral_change(self):
        self.standard_session("high")
        self.write("src/due.ts")
        state = self.verified()
        self.assertEqual(state["risk_recheck"]["high"], False)
        self.assertTrue(state["high_risk"])

    def test_a_sensitive_path_raises_the_risk(self):
        self.standard_session()
        self.write("src/auth/login.ts")
        state = self.verified()
        self.assertTrue(state["high_risk"])
        self.assertEqual(state["risk_recheck"]["why"], ["it touches src/auth/login.ts"])
        self.assertIn("risk raised to high after the build: it touches src/auth/login.ts",
                      [n["text"] for n in state["notes"]])

    def test_a_camel_case_word_counts_and_a_longer_word_does_not(self):
        self.standard_session()
        self.write("src/author.ts")       # `author` is not `auth`
        self.write("src/tokenizer.ts")    # nor is `tokenizer` `token`
        self.write("src/UserAuth.ts")     # user, auth, ts
        state = self.verified()
        self.assertEqual(state["risk_recheck"]["why"], ["it touches src/UserAuth.ts"])

    def test_a_large_change_raises_the_risk(self):
        self.standard_session()
        for i in range(30):
            self.write(f"src/part{i}.ts")
        state = self.verified()
        self.assertTrue(state["high_risk"])
        # the 30 files and the two installed acceptance checks, which ship too
        self.assertIn("it is large (32 files", state["risk_recheck"]["why"][0])

    def test_a_lock_file_is_left_out_of_the_line_count(self):
        self.standard_session()
        self.write("src/due.ts")
        self.write("package-lock.json", "{}\n" * 2000)
        state = self.verified()
        self.assertEqual(state["risk_recheck"]["high"], False, state["risk_recheck"])
        self.assertFalse(state["high_risk"])

    def test_it_runs_once_and_explain_writes_nothing(self):
        self.standard_session()
        self.write("src/auth/login.ts")
        self.next(0)
        r = self.autodev("quality-gate", "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        r = self.autodev("next", "--dir", self.dir, "--explain")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("risk_recheck", self.state())
        self.enter_stage("ship")
        seq = self.state()["risk_recheck"]["seq"]
        self.next(0)
        self.assertEqual(self.state()["risk_recheck"]["seq"], seq)


class RiskAtTheReadyGateTest(NextCase):
    ship_ready = ShipTest.ship_ready
    to_body = ShipTest.to_body
    draft_pr = ShipTest.draft_pr
    reviewed_pr = ShipTest.reviewed_pr
    refresh_body = ShipTest.refresh_body
    published = ShipTest.published

    def build_session(self):
        (self.worktree / "src" / "auth").mkdir(parents=True, exist_ok=True)
        (self.worktree / "src" / "auth" / "token.ts").write_text("export const t = 1;\n")
        super().build_session()

    def test_the_ready_gate_says_the_build_raised_the_risk(self):
        self.reviewed_pr()
        out = self.next(5)
        self.assertIn("ready gate", out["QUESTION"])
        self.assertIn("Risk: high after the build (it touches src/auth/token.ts)",
                      out["SUMMARY"])


class ReviewEffortTest(NextCase):
    ship_ready = ShipTest.ship_ready
    to_body = ShipTest.to_body
    draft_pr = ShipTest.draft_pr
    published = ShipTest.published

    plan_text = PLAN.replace("Review effort: high — a small change",
                             "Review effort: xhigh — a state machine across three modules")

    def to_panel(self):
        self.draft_pr()  # the review runs on the draft PR

    def test_the_plan_s_xhigh_effort_reaches_every_code_reviewer_spawn(self):
        self.to_panel()
        out, jobs = self.reviewers()  # the security reviewer spawns at its own effort
        self.assertEqual(out["EFFORT"], ["xhigh"] * 3 + [""])
        self.assertIn("passing its EFFORT as the Agent tool's `effort`", out["ACTION"])
        self.assertEqual(self.state()["phase6"]["passes"][0]["effort"], "xhigh")
        self.assertIn("review pass 1: the panel runs at effort xhigh",
                      (self.dir / "WORK_LOG.md").read_text())
        # Re-issued (not recorded yet), in text: each PROMPT is followed by its EFFORT.
        r = self.autodev("next", "--reissue", "--dir", self.dir)
        lines = r.stdout.splitlines()
        prompts = [i for i, ln in enumerate(lines) if ln.startswith("PROMPT: ")]
        self.assertEqual(len(prompts), 3, r.stdout)
        for i in prompts:
            self.assertEqual(lines[i + 1], "EFFORT: xhigh", r.stdout)
        # The plan changing mid-pass (high now) does not change the pass's effort.
        (self.dir / "PLAN.md").write_text(PLAN)
        for w, n in jobs:
            slot = self.sets(w, n)["reviewer"]
            if slot == "R3":
                self.answer(w, n, "", status="failed")
                continue
            (self.dir / "review" / "pass-1" / f"{slot}.md").write_text(r_report("x"))
            self.answer(w, n, "REVIEWED", findings="1", leads="0")
        out, jobs = self.expect("code-reviewer")  # the failed one's one re-spawn
        self.assertEqual(out["EFFORT"], ["xhigh"])
        (self.dir / "review" / "pass-1" / "R3.md").write_text(r_report("x"))
        self.answer(*jobs[0], "REVIEWED", findings="1", leads="0")
        (self.dir / "CODE_REVIEW.md").write_text(CODE_REVIEW.format(tree=self.tree()))
        out, _ = self.expect("review-judge", "REVOTE", must_fix_open="1", revote="2")
        self.assertNotIn("EFFORT", out)  # only code reviewers get one
        out, _ = self.expect("code-reviewer")  # the re-votes
        self.assertEqual(out["EFFORT"], ["xhigh"] * 3)

    def test_the_nested_code_review_gets_the_pass_s_effort_and_the_changed_files(self):
        self.to_panel()
        _, jobs = self.reviewers()
        for w, n in jobs:
            sets = self.sets(w, n)
            self.assertEqual(sets["review_effort"], "xhigh")
            files = sets["files"].split(", ")
            self.assertIn("due.ts", files)  # the branch's change, as committed
            self.assertFalse([f for f in files if f.startswith(".auto-dev/")], files)
            brief = (self.dir / "briefs" / f"{w}-{n}.md").read_text()
            self.assertIn("review_effort: xhigh", brief)
        # A failed reviewer's re-spawn gets the same effort and files.
        for w, n in jobs:
            slot = self.sets(w, n)["reviewer"]
            if slot == "R2":
                self.answer(w, n, "", status="failed")
                failed = self.sets(w, n)
                continue
            (self.dir / "review" / "pass-1" / f"{slot}.md").write_text(r_report("x"))
            self.answer(w, n, "REVIEWED", findings="1", leads="0")
        _, again = self.expect("code-reviewer")
        self.assertEqual(self.sets(*again[0]), failed)

    def test_a_plan_at_high_effort_runs_the_reviewers_at_high(self):
        self.plan_text = PLAN
        self.to_panel()
        out, jobs = self.reviewers()
        self.assertEqual(out["EFFORT"], ["high"] * 3 + [""])
        self.assertEqual(self.state()["phase6"]["passes"][0]["effort"], "high")
        self.assertEqual({self.sets(*j)["review_effort"] for j in jobs}, {"high"})

    def test_a_pass_started_before_4_3_reads_the_plan(self):
        self.to_panel()
        self.reviewers()
        state = json.loads((self.dir / "state.json").read_text())
        del state["phase6"]["passes"][0]["effort"]  # as an older `next` saved it
        (self.dir / "state.json").write_text(json.dumps(state))
        self.assertEqual(self.next(0, reissue=True)["EFFORT"],  # the plan, not the default
                         ["xhigh"] * 3)


class QuoteTest(RunCase):
    def test_printed_commands_survive_a_path_with_spaces(self):
        self.repo = self.tmp / "my app"
        self.sh("git", "clone", "-q", str(self.tmp / "origin.git"), str(self.repo))
        (self.repo / ".env").write_text("SECRET=1\n")
        self.worktree = self.tmp / "my app-due-dates"
        self.dir = self.worktree / ".auto-dev"
        r = self.init()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        state = json.loads((self.dir / "state.json").read_text())
        state["settings"]["checkpoint_events"] = 1  # so a printed command comes out
        (self.dir / "state.json").write_text(json.dumps(state))
        out = json.loads(self.autodev("next", "--dir", self.dir, "--json").stdout)
        self.assertEqual(out["exit"], 6, out)
        r = subprocess.run(out["AFTER"][0], shell=True, capture_output=True, text=True,
                           env=self.env, cwd=self.tmp, check=False)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)  # it ran
        self.assertTrue((self.dir / "HANDOFF.md").is_file())
        state = json.loads((self.dir / "state.json").read_text())
        state["settings"]["checkpoint_events"] = 1000
        (self.dir / "state.json").write_text(json.dumps(state))
        r = self.autodev("resume", "--repo", self.repo)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        out = json.loads(self.autodev("next", "--dir", self.dir, "--json").stdout)
        self.assertTrue(Path(out["BRIEF"][0]).is_file(), out)
        # `next` records the result under the path with a space.
        (self.dir / "returns" / "planner-1.json").write_text(json.dumps(
            {"worker": "planner", "status": "ok", "next": "FITS"}))
        out = json.loads(self.autodev("next", "--dir", self.dir, "--json").stdout)
        self.assertEqual(out["RECORDED"], ["planner-1: refused (MALFORMED)"])
        self.assertTrue(Path(out["BRIEF"][0]).is_file(), out)


class TextOutputTest(NextCase):
    def test_lines_are_printed_in_order(self):
        r = self.autodev("next", "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.splitlines()
        self.assertTrue(lines[0].startswith("ACTION: spawn auto-dev:planner"))
        self.assertEqual(lines[1], "AGENT: auto-dev:planner")
        self.assertTrue(lines[2].startswith(f"BRIEF: {self.dir}/briefs/planner-1.md"))
        self.assertTrue(lines[3].startswith("PROMPT: Your brief is at"))
        self.assertEqual(len(lines), 4)  # no AFTER: the next `next` records the result
        self.assertIn("run `next` (it records its result)", lines[0])
        self.assertFalse(any(ln.startswith("RULE:") for ln in lines))
        r = self.autodev("next", "--dir", self.dir, "--explain")
        self.assertIn("nothing was done; run `next` to act) wait: planner #1", r.stdout)
        self.assertIn("RULE: a brief sent out in this session has no result yet", r.stdout)
        r = self.autodev("next", "--reissue", "--dir", self.dir, "--explain")
        self.assertIn("RULE: a brief was issued", r.stdout)


class OverrideCase(NextCase):
    """A stop the user can override: `next` asks how to go on, and
    `autodev.py override` records the answer (fix, approve, retry, signoff,
    talk, leave)."""

    def answer_stop(self, out, label, text="the user's words"):
        """Run the AFTER line for `label`, its placeholder filled with `text`."""
        line = next(ln.split(" → ", 1)[1] for ln in out["AFTER"]
                    if ln.startswith(f'"{label}"'))
        line = re.sub(r"'<[^']*>'", "'" + text.replace("'", "’") + "'", line)
        return subprocess.run(line, shell=True, capture_output=True, text=True,
                              env=self.env, cwd=self.tmp, check=False)

    def overrides(self):
        sys.path.insert(0, str(SCRIPTS))
        return import_module("lib.overrides")

    def labels(self, out):
        return [o["label"] for o in json.loads(out["QUESTION"])["questions"][0]["options"]]

    to_body = ShipTest.to_body
    draft_pr = ShipTest.draft_pr
    published = ShipTest.published

    def red_gate(self):
        self.plan_session()
        self.resume()
        self.expect("coder", "BUILT", blocked="0", test_changes="none")
        (self.worktree / "due.ts").write_text("export const due = 1;\n")
        self.quality_gate(red=True)
        _, jobs = self.expect("coder", "BUILT", blocked="0", test_changes="none")
        self.quality_gate(red=True)
        out = self.next(4)
        self.assertIn("still red after the coder's correction", " ".join(out["REPORT"]))
        return out, jobs[0]

    def fix(self, out, instruction="make the date sort stable"):
        r = self.answer_stop(out, "<a typed answer>", instruction)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        _, jobs = self.expect("fixer")
        self.assertEqual(self.sets(*jobs[0])["instruction"], instruction)
        return jobs[0]

    def report(self, n, changed="none", proposal="none", why="none"):
        path = self.dir / "override" / f"fixer-{n}.md"
        path.write_text(f"# Fix report\n\n## Instruction\nx\n\n## Changed\n{changed}\n\n"
                        f"## Proposal\n{proposal}\n\n## Why not\n{why}\n")
        return path


class OverrideTest(OverrideCase):
    def test_a_red_gate_asks_how_to_go_on(self):
        out, _ = self.red_gate()
        self.assertEqual(self.labels(out), ["I fixed it myself", "Sign off and go on",
                                            "Let's talk it through", "Leave it stopped"])
        self.assertTrue(any(ln.startswith('"<a typed answer>" → ') and "override fix" in ln
                            for ln in out["AFTER"]), out["AFTER"])
        self.assertEqual(self.state()["stop"]["rule"],
                         "the quality gate is red after its correction")

    def test_override_is_refused_when_the_run_did_not_stop(self):
        self.plan_session()
        r = self.autodev("override", "retry", "--dir", self.dir)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("did not just stop", r.stdout + r.stderr)

    def test_a_fix_with_no_instruction_is_refused(self):
        self.red_gate()
        r = self.autodev("override", "fix", "--text", " ", "--dir", self.dir)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("needs --text", r.stdout + r.stderr)
        self.assertIn("stop", self.state())  # nothing recorded

    def test_retry_runs_only_the_step_that_stopped_again(self):
        out, _ = self.red_gate()
        r = self.answer_stop(out, "I fixed it myself", "I fixed the lint config")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("stop", self.state())
        self.quality_gate()  # the gate runs again, no worker
        self.enter_stage("ship")
        self.assertEqual(self.state()["budget"]["remaining"], 4)  # the gate's correction is free

    def test_a_typed_instruction_spawns_the_fixer_and_the_gate_runs_again(self):
        out, _ = self.red_gate()
        n = self.fix(out)[1]
        brief = (self.dir / "briefs" / f"fixer-{n}.md").read_text()
        self.assertIn("the quality gate is red after its correction", brief)
        (self.worktree / "src").mkdir(exist_ok=True)
        (self.worktree / "src" / "sorted.ts").write_text("export const stable = true;\n")
        self.report(n, changed="- `src/sorted.ts` — the stable sort the user asked for")
        self.answer("fixer", n, "FIXED", fix_report=str(self.dir / "override" /
                                                        f"fixer-{n}.md"), changed="1")
        self.quality_gate()  # the stopped step, again
        fix = self.state()["overrides"][-1]
        self.assertEqual((fix["status"], fix["changed"]), ("fixed", ["src/sorted.ts"]))
        self.enter_stage("ship")
        self.assertIn("make the date sort stable", "\n".join(
            self.overrides().summary_lines(self.state())))

    def test_a_fixer_report_that_leaves_a_change_out_is_refused(self):
        out, _ = self.red_gate()
        n = self.fix(out)[1]
        (self.worktree / "src").mkdir(exist_ok=True)
        (self.worktree / "src" / "sorted.ts").write_text("x\n")
        (self.worktree / "src" / "other.ts").write_text("y\n")
        self.report(n, changed="- `src/sorted.ts` — the sort")
        self.answer("fixer", n, "FIXED", fix_report="x", changed="1")
        out = self.next(0, refused_ok=True)
        self.assertIn(f"fixer-{n}: refused (MISMATCH)", out["RECORDED"])
        issues = self.state()["refused"][f"fixer-{n}"]
        self.assertTrue(any("src/other.ts" in i for i in issues), issues)

    def test_a_blocked_fixer_that_says_fixed_is_refused(self):
        out, _ = self.red_gate()
        n = self.fix(out)[1]
        (self.worktree / "src").mkdir(exist_ok=True)
        (self.worktree / "src" / "sorted.ts").write_text("x\n")
        self.report(n, changed="- `src/sorted.ts` — the sort")
        self.answer("fixer", n, "FIXED", status="blocked", fix_report="x", changed="1")
        out = self.next(0, refused_ok=True)
        self.assertIn(f"fixer-{n}: refused (MISMATCH)", out["RECORDED"])
        issues = self.state()["refused"][f"fixer-{n}"]
        self.assertTrue(any("status is blocked but next is FIXED" in i for i in issues),
                        issues)
        self.assertEqual(self.state()["overrides"][-1]["status"], "open")

    def test_a_blocked_fixer_with_no_next_is_put_back(self):
        out, _ = self.red_gate()
        n = self.fix(out)[1]
        (self.worktree / "src").mkdir(exist_ok=True)
        (self.worktree / "src" / "half.ts").write_text("half done\n")
        self.answer("fixer", n, "none", status="blocked")
        self.next(4)
        self.assertFalse((self.worktree / "src" / "half.ts").exists())
        self.assertEqual(self.state()["overrides"][-1]["status"], "failed")

    def change_settings(self):
        """Edit the run's settings in state.json, as a fixer might; the old ones."""
        state = self.state()
        before = json.loads(json.dumps(state["settings"]))
        gate = state["settings"]["gate"][0]
        gate["command"] = "env X=1 " + gate["command"]
        (self.dir / "state.json").write_text(json.dumps(state, indent=2))
        return before, gate["command"]

    def test_a_fixer_settings_change_must_be_named_and_is_kept(self):
        out, _ = self.red_gate()
        n = self.fix(out, "wrap the gate command in env X=1")[1]
        before, command = self.change_settings()
        report = str(self.report(n, changed="none"))
        self.answer("fixer", n, "FIXED", fix_report=report, changed="0")
        out = self.next(0, refused_ok=True)
        self.assertIn(f"fixer-{n}: refused (MISMATCH)", out["RECORDED"])
        issues = self.state()["refused"][f"fixer-{n}"]
        self.assertTrue(any("`.auto-dev/state.json`" in i for i in issues), issues)
        jobs = self.spawned(out)  # the retry, held to the first brief's copy
        self.assertEqual([w for w, _ in jobs], ["fixer"], json.dumps(out, indent=2))
        m = jobs[0][1]
        entry = next(b for b in self.state()["briefs"]
                     if b["worker"] == "fixer" and b["n"] == m)
        self.assertEqual(entry["settings"], before)
        report = str(self.report(m, changed="- `.auto-dev/state.json` — the gate command"))
        self.answer("fixer", m, "FIXED", fix_report=report, changed="1")
        self.quality_gate()
        state = self.state()
        self.assertEqual(state["settings"]["gate"][0]["command"], command)
        fix = state["overrides"][-1]
        self.assertEqual((fix["status"], fix["changed"]), ("fixed", [".auto-dev/state.json"]))
        # The new gate command ran (quality_gate above): a run counts only for its gate.

    def test_a_fixer_settings_change_is_put_back_when_it_does_not_fix(self):
        out, _ = self.red_gate()
        n = self.fix(out)[1]
        before, _ = self.change_settings()
        self.report(n, proposal="Also wrap the gate command.")
        self.answer("fixer", n, "NEEDS_CONSENT", fix_report="x", changed="0")
        self.next(4)
        state = self.state()
        self.assertEqual(state["settings"], before)
        self.assertIn(".auto-dev/state.json", state["overrides"][-1]["undone"])

    def test_settings_changed_after_the_fix_is_dropped_are_not_the_fixer_s(self):
        out, _ = self.red_gate()
        n = self.fix(out)[1]
        state = self.state()  # a later answer at a stop replaced the fix
        state["overrides"][-1]["status"] = "dropped"
        (self.dir / "state.json").write_text(json.dumps(state, indent=2))
        _, command = self.change_settings()  # not the fixer's change
        self.report(n, changed="none")
        self.answer("fixer", n, "FIXED", fix_report="x", changed="0")
        # No fix open: back at the step that stopped, the gate, which runs
        # again since its command changed (the red run was another gate's).
        out = self.next(0)
        self.assertIn("quality-gate", out["ACTION"])
        self.assertEqual(out["RECORDED"], [f"fixer-{n}: ok FIXED"])
        self.assertEqual(self.state()["settings"]["gate"][0]["command"], command)

    def test_a_proposal_changes_nothing_and_can_be_approved(self):
        out, _ = self.red_gate()
        n = self.fix(out)[1]
        (self.worktree / "src").mkdir(exist_ok=True)
        (self.worktree / "src" / "half.ts").write_text("half done\n")
        spec = (self.dir / "PLAN.md").read_text()
        (self.dir / "PLAN.md").write_text(spec + "\nan edit\n")
        self.report(n, proposal="Also change the sort comparator in src/sort.ts.")
        self.answer("fixer", n, "NEEDS_CONSENT", fix_report="x", changed="0")
        out = self.next(4)
        self.assertFalse((self.worktree / "src" / "half.ts").exists())  # put back
        self.assertEqual((self.dir / "PLAN.md").read_text(), spec)
        self.assertEqual(self.labels(out)[0], "Approve the fixer's proposal")
        self.assertIn("proposal", " ".join(out["SUMMARY"]))
        r = self.answer_stop(out, "Approve the fixer's proposal")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        _, jobs = self.expect("fixer")
        self.assertIn("approved the proposal", self.sets(*jobs[0])["instruction"])

    def test_a_fixer_edit_to_a_check_is_committed_as_a_tests_commit(self):
        # The fixer edits a committed check at the user's instruction: once its
        # FIXED is recorded, `next` commits the file as a new tests commit, the
        # one the guard holds it to from then on.
        out, _ = self.red_gate()
        n = self.fix(out, "change the due-date check")[1]
        check = self.worktree / "src" / "due.acceptance.test.ts"
        check.write_text("test v2")
        self.report(n, changed="- `src/due.acceptance.test.ts` — what the user asked")
        self.answer("fixer", n, "FIXED", fix_report="x", changed="1")
        self.quality_gate()
        commits = self.state()["tests_commits"]
        self.assertEqual(len(commits), 2)
        self.assertEqual(commits[1]["paths"], ["src/due.acceptance.test.ts"])
        self.assertEqual(self.state()["overrides"][-1]["status"], "fixed")

    def test_a_fix_that_edits_no_check_previews_no_tests_commit(self):
        out, _ = self.red_gate()
        n = self.fix(out, "make the date sort stable")[1]
        (self.worktree / "src").mkdir(exist_ok=True)
        (self.worktree / "src" / "sorted.ts").write_text("x\n")
        self.report(n, changed="- `src/sorted.ts` — the sort")
        self.answer("fixer", n, "FIXED", fix_report="x", changed="1")
        r = self.autodev("record", "fixer", str(n), "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        out = self.autodev("next", "--explain", "--dir", self.dir)
        self.assertNotIn("commit the acceptance checks", out.stdout)
        self.quality_gate()
        self.assertEqual(len(self.state()["tests_commits"]), 1)

    def test_a_fixer_that_proposes_puts_the_check_back_and_commits_nothing(self):
        out, _ = self.red_gate()
        n = self.fix(out, "change the due-date check")[1]
        check = self.worktree / "src" / "due.acceptance.test.ts"
        check.write_text("test v2")
        self.report(n, proposal="- change the sort check too")
        self.answer("fixer", n, "NEEDS_CONSENT", fix_report="x", changed="0")
        self.next(4)
        self.assertEqual(check.read_text(), "test")
        self.assertEqual(len(self.state()["tests_commits"]), 1)

    def amend(self, *args):
        return self.autodev("amend-checks", "--dir", self.dir, *args)

    def test_amend_checks_is_refused_with_no_fix_open(self):
        self.red_gate()
        r = self.amend("--drop", "src/sort.acceptance.test.ts :: sorts earliest first")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("no fix is open", r.stdout + r.stderr)

    def test_the_fixer_drops_a_check_through_amend_checks(self):
        # The fixer removes the check file itself and drops its one row; the
        # deletion is committed as a tests commit, so the guard lets it go.
        out, _ = self.red_gate()
        n = self.fix(out, "drop the sort check")[1]
        check = self.worktree / "src" / "sort.acceptance.test.ts"
        check.unlink()
        r = self.amend("--drop", '`src/sort.acceptance.test.ts` :: "sorts earliest first"',
                       "--not-automatable", "| 2 | sorted | the user dropped it | none |")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        manifest = (self.dir / "acceptance" / "MANIFEST.md").read_text()
        self.assertNotIn("sorts earliest first", manifest)
        self.assertIn("shows the due date", manifest)
        changed = [ln.split("changed: ", 1)[1] for ln in r.stdout.splitlines()
                   if "changed: " in ln]
        self.assertEqual(changed, [".auto-dev/acceptance/MANIFEST.md"])
        self.report(n, changed="- `.auto-dev/acceptance/MANIFEST.md` — dropped\n"
                    "- `src/sort.acceptance.test.ts` — removed")
        self.answer("fixer", n, "FIXED", fix_report="x", changed="2")
        self.quality_gate()
        commits = self.state()["tests_commits"]
        self.assertEqual(commits[-1]["paths"], ["src/sort.acceptance.test.ts"])
        r = subprocess.run([sys.executable, str(SCRIPTS / "check-tests.py"), self.worktree,
                            "--base", "HEAD", *[a for c in commits
                                                 for a in ("--tests-commit", c["sha"])]],
                           capture_output=True, text=True, check=False)
        self.assertNotIn("ACCEPTANCE_MISSING", r.stdout)
        self.assertEqual(self.state()["overrides"][-1]["status"], "fixed")

    def test_amend_checks_refuses_a_check_no_row_names(self):
        out, _ = self.red_gate()
        self.fix(out)
        before = (self.dir / "acceptance" / "MANIFEST.md").read_text()
        r = self.amend("--drop", "src/sort.acceptance.test.ts :: sorts earliest first",
                       "--drop", "src/sort.acceptance.test.ts :: no such test")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn('no MANIFEST.md row names `src/sort.acceptance.test.ts` :: '
                      '"no such test"', r.stdout + r.stderr)
        self.assertEqual((self.dir / "acceptance" / "MANIFEST.md").read_text(), before)

    def test_a_condition_left_with_no_check_is_refused_until_it_is_covered(self):
        # S1's one check is dropped: `record` refuses until S1 has a Not
        # automatable row (or leaves PLAN.md); a dropped test still in its
        # file is refused too.
        check = self.worktree / "src" / "due.acceptance.test.ts"
        check.parent.mkdir(parents=True, exist_ok=True)
        check.write_text('test("owner only")\n')  # as the tester writes it
        out, _ = self.red_gate()
        n = self.fix(out, "drop the owner check, keep S1 as not automatable")[1]
        r = self.amend("--drop", "src/due.acceptance.test.ts :: owner only")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        changed = [ln.split("changed: ", 1)[1] for ln in r.stdout.splitlines()
                   if "changed: " in ln]
        self.assertEqual(changed, [".auto-dev/acceptance/MANIFEST.md"])  # other rows stay
        self.report(n, changed="- `.auto-dev/acceptance/MANIFEST.md` — dropped")
        self.answer("fixer", n, "FIXED", fix_report="x", changed="1")
        out = self.next(0, refused_ok=True)
        issues = self.state()["refused"][f"fixer-{n}"]
        self.assertTrue(any("still holds its test" in i for i in issues), issues)
        self.assertTrue(any("condition S1 has no check left" in i for i in issues), issues)
        # The retry takes the test out and adds the row.
        jobs = self.spawned(out)
        self.assertEqual([w for w, _ in jobs], ["fixer"], json.dumps(out, indent=2))
        installed = self.worktree / "src" / "due.acceptance.test.ts"
        installed.write_text("")
        r = self.amend("--not-automatable",
                       "| S1 | owner only | the user dropped it | none |")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        manifest = (self.dir / "acceptance" / "MANIFEST.md").read_text()
        self.assertIn("| S1 | owner only | the user dropped it | none |", manifest)
        self.assertNotIn("None.", manifest)
        self.report(jobs[0][1], changed="- `.auto-dev/acceptance/MANIFEST.md` — dropped\n"
                    "- `src/due.acceptance.test.ts` — the test out")
        self.answer(*jobs[0], "FIXED", fix_report="x", changed="2")
        self.quality_gate()
        self.assertEqual(self.state()["tests_commits"][-1]["paths"],
                         ["src/due.acceptance.test.ts"])  # the test out, committed
        r = self.amend("--drop", "src/sort.acceptance.test.ts :: sorts earliest first")
        self.assertIn("no fix is open", r.stdout + r.stderr)  # recorded: closed

    def test_amend_checks_adds_rows_and_a_new_check_file(self):
        out, _ = self.red_gate()
        self.fix(out, "rename the sort check and add a check file")
        new = self.worktree / "src" / "new.acceptance.test.ts"
        new.write_text('test("new check")\n')
        path = self.dir / "acceptance" / "MANIFEST.md"
        path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))  # kept CRLF
        r = self.amend(
            "--drop", "src/sort.acceptance.test.ts :: sorts earliest first",
            "--row", '| 2 | sorted | `src/sort.acceptance.test.ts` :: "sorts by date" | '
                     "Example | unit | fail-to-pass | failed: unsorted |",
            "--row", '| 2 | sorted | `src/new.acceptance.test.ts` :: "new check" | '
                     "Edge | unit | fail-to-pass | failed: unsorted |")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        manifest = path.read_bytes().decode()
        self.assertNotIn("sorts earliest first", manifest)
        self.assertIn('"sorts by date" | Example | unit | fail-to-pass | failed: unsorted |\r\n',
                      manifest)
        self.assertNotIn("\n", manifest.replace("\r\n", ""))
        # The sort file still has a row, so it stays.
        self.assertTrue((self.worktree / "src" / "sort.acceptance.test.ts").exists())
        for args, why in ((["--row", "| 2 | too few |"], "needs 7 cells"),
                          (["--drop", "../outside.ts :: x"], "not a path inside the repo"),
                          (["--drop", "/abs.ts :: x"], "not a path inside the repo")):
            r = self.amend(*args)
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            self.assertIn(why, r.stdout + r.stderr)

    def test_a_check_dropped_and_added_back_is_kept(self):
        # A drop and a --row with the same name moves the check (here to an
        # Edge row): its test rightly stays, and `record` takes it.
        out, _ = self.red_gate()
        n = self.fix(out, "make the sort check an Edge check")[1]
        r = self.amend("--drop", "src/sort.acceptance.test.ts :: sorts earliest first",
                       "--row", '| 2 | sorted | `src/sort.acceptance.test.ts` :: '
                                '"sorts earliest first" | Edge | unit | fail-to-pass | '
                                "failed: unsorted |")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.report(n, changed="- `.auto-dev/acceptance/MANIFEST.md` — Covers")
        self.answer("fixer", n, "FIXED", fix_report="x", changed="1")
        self.quality_gate()

    def test_a_red_gate_signed_off_goes_on_to_the_push(self):
        out, _ = self.red_gate()
        r = self.answer_stop(out, "Sign off and go on", "the lint rule is wrong here")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.enter_stage("ship")  # nothing verified before the push
        self.assertEqual(self.overrides().signed_reports(self.state()), {"TEST.md"})
        lines = self.overrides().summary_lines(self.state())
        self.assertIn("Signed off by the user", lines[0])

    def test_a_signed_off_check_stays_signed_off_but_a_new_failure_goes_to_the_coder(self):
        out, _ = self.red_gate()
        self.answer_stop(out, "Sign off and go on", "the lint rule is wrong here")
        self.enter_stage("ship")
        (self.worktree / "extra.ts").write_text("export const extra = 1;\n")
        self.quality_gate(red=True)  # the same check, still failing: signed off
        self.assertIn("commit: run", self.next(0)["ACTION"])
        state = self.state()  # a second gate check, failing: not signed off
        state["settings"]["gate"].append({"command": "false", "kind": "lint",
                                          "report": "LINT.md"})
        self.write_state(state)
        (self.worktree / "extra.ts").write_text("export const extra = 2;\n")
        r = self.autodev("commit", "--message", "feat: x", "--dir", self.dir)
        self.assertEqual(r.returncode, 1, r.stdout)  # stale: re-checked first
        self.resume()  # a new session: not "stale twice running"
        out = self.next(0)
        self.assertIn("quality-gate", out["ACTION"])
        r = self.autodev("quality-gate", "--dir", self.dir)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertFalse(self.overrides().signed_reports(self.state()) >= {"LINT.md"})
        out, jobs = self.expect("coder")
        self.assertIn("lint/LINT.md", self.sets(*jobs[0])["corrections_file"])

    def test_a_mutation_that_may_have_left_changes_cannot_be_signed_off(self):
        self.plan_session()
        self.resume()
        self.build_session()
        self.draft_pr(started=True)
        _, panel = self.reviewers(verifier="MUTATION_LEFT_CHANGES")
        for w, n in panel:
            (self.dir / "review" / "pass-1" / f"{self.sets(w, n)['reviewer']}.md"
             ).write_text(r_report("none"))
            self.answer(w, n, "REVIEWED", findings="0", leads="0")
        out = self.next(4)
        self.assertNotIn("Sign off and go on", self.labels(out))
        self.assertIn("planted change", " ".join(out["SUMMARY"]))
        r = self.autodev("override", "signoff", "--text", "fine", "--dir", self.dir)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("can't be signed off", r.stdout + r.stderr)

    def test_talk_records_nothing_and_leave_holds_until_a_new_session(self):
        out, _ = self.red_gate()
        r = self.answer_stop(out, "Let's talk it through")
        self.assertIn("TALK", r.stdout)
        self.assertIn("QUESTION", self.next(4))
        out = self.next(4)
        r = self.answer_stop(out, "Leave it stopped")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        out = self.next(4)
        self.assertNotIn("QUESTION", out)
        self.assertIn("leave the run stopped", " ".join(out["REPORT"]))
        self.resume()
        self.assertIn("QUESTION", self.next(4))

    def test_a_worker_that_failed_twice_is_retried_in_the_same_session(self):
        self.plan_session()
        self.resume()
        for _ in range(2):
            _, jobs = self.expect("coder")
            self.answer(*jobs[0], None, status="failed")
        out = self.next(4)
        self.assertIn("failed twice running", " ".join(out["REPORT"]))
        self.assertNotIn("Sign off and go on", self.labels(out))
        r = self.answer_stop(out, "I fixed it myself", "installed the missing tool")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.expect("coder")

    def test_an_oversized_task_can_be_signed_off_and_a_new_session_resumes_it(self):
        _, jobs = self.expect("planner")
        (self.dir / "PLAN.md").write_text(OVERSIZED_PLAN)
        self.answer(*jobs[0], "OVERSIZED", **PLANNED)
        out = self.next(4)
        self.assertIn("Sign off and go on", self.labels(out))
        r = self.answer_stop(out, "Leave it stopped")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.resume()  # RESUME, not FINISHED: the stop can still be overridden
        out = self.next(4)
        r = self.answer_stop(out, "Sign off and go on", "one PR is fine for this team")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.state()["size"], "FITS")
        _, jobs = self.expect("planner")  # the kept plan gets its steps first
        self.assertEqual(self.mode(*jobs[0]), "revise")

    def test_the_three_spawn_stop_asks_again_after_talk_and_leave(self):
        self.stopped_after_three_spawns()
        r = self.autodev("override", "talk", "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        out = self.next(4)
        shown = json.dumps(out, indent=2)
        self.assertIn("spawned 3 times", " ".join(out["REPORT"]), shown)
        self.assertIn("QUESTION", out, shown)
        self.assertFalse(out.get("ACTION", "").startswith("wait"), shown)
        r = self.autodev("override", "leave", "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        out = self.next(4)
        shown = json.dumps(out, indent=2)
        self.assertIn("The user chose to leave the run stopped here; the worktree stays.",
                      " ".join(out["REPORT"]), shown)
        self.assertFalse(out.get("ACTION", "").startswith("wait"), shown)

    def test_a_fixer_at_the_three_spawn_stop_is_waited_for_alone(self):
        out = self.stopped_after_three_spawns()
        job = self.fix(out, "point the planner at the fixture")
        self.assertEqual(job, ("fixer", 1))
        out = self.next(0)
        self.assert_waits_for(out, "fixer #1")
        self.assertNotIn("planner #1", out["ACTION"])
        self.report(1, proposal="Point the planner at the fixture repo.")
        self.answer("fixer", 1, "NEEDS_CONSENT", fix_report="x", changed="0")
        out = self.next(4)
        self.assertEqual(self.labels(out)[0], "Approve the fixer's proposal")

    def test_the_brief_a_fixed_fixer_sends_again_is_waited_for(self):
        # The fixer's FIXED lifts the stop at the same seq the planner's brief is
        # then sent out again at: that brief is out, not stale.
        (self.dir / "acceptance" / "MANIFEST.md").unlink()  # the plan stage: no checks yet
        out = self.stopped_after_three_spawns()
        self.assertEqual(self.fix(out, "point the planner at the fixture"), ("fixer", 1))
        self.report(1)
        self.answer("fixer", 1, "FIXED", fix_report=str(self.dir / "override" / "fixer-1.md"),
                    changed="0")
        out = self.next(0)
        shown = json.dumps(out, indent=2)
        self.assertEqual(out.get("BRIEF"), [str(self.dir / "briefs" / "planner-1.md")], shown)
        self.assert_waits_for(self.next(0), "planner #1")


class OverrideShipTest(OverrideCase):
    """Overrides in Phase 6: a correction that changed nothing."""

    ship_ready = ShipTest.ship_ready
    to_body = ShipTest.to_body
    draft_pr = ShipTest.draft_pr
    published = ShipTest.published
    refresh_body = ShipTest.refresh_body

    def unchanged_correction(self):
        """Pass 1's must-fix C1, and a correction that changes nothing."""
        self.draft_pr()
        _, jobs = self.reviewers()
        for w, n in jobs:
            (self.dir / "review" / "pass-1" / f"{self.sets(w, n)['reviewer']}.md").write_text(
                r_report("- null due date crashes sort"))
            self.answer(w, n, "REVIEWED", findings="1", leads="0")
        (self.dir / "CODE_REVIEW.md").write_text(OPEN_REVIEW.format(tree=self.tree()))
        (self.dir / "review" / "pass-1" / "corrections.md").write_text(
            "# Required changes\n1. C1: guard the sort in src/sort.ts against a "
            "missing due date\n")
        self.expect("review-judge", "MUST_FIX", must_fix_open="1", revote="0")
        _, jobs = self.expect("coder", "BUILT", blocked="0", test_changes="none")
        r = self.autodev("record", *map(str, jobs[0]), "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        # The correction closed with no change, so no new pass started (as after
        # the commit, where an unchanged correction keeps the verified commit).
        state = self.state()
        state["phase6"]["corrections"][-1]["closed"] = True
        self.write_state(state)
        out = self.next(4)
        self.assertIn("changed nothing", " ".join(out["REPORT"]))
        return out

    def test_retry_reopens_a_correction_that_changed_nothing_at_no_round(self):
        out = self.unchanged_correction()
        left = self.state()["budget"]["remaining"]
        r = self.answer_stop(out, "I fixed it myself", "clarified the finding")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        out, _ = self.expect("coder")
        self.assertIn("already spent", out["BUDGET"])
        self.assertEqual(self.state()["budget"]["remaining"], left)

    def test_signing_off_open_findings_goes_to_the_ready_gate(self):
        out = self.unchanged_correction()
        self.assertIn("Sign off and go on", self.labels(out))
        r = self.answer_stop(out, "Sign off and go on", "C1 can't happen in production")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.refresh_body()
        out = self.next(5)
        self.assertIn("ready gate", out["QUESTION"])
        summary = " ".join(out["SUMMARY"])
        self.assertIn("Signed off by the user", summary)
        self.assertIn("C1 can’t happen in production", summary)
        sys.path.insert(0, str(SCRIPTS))
        head = self.sh("git", "rev-parse", "HEAD", cwd=self.worktree).strip()
        body = import_module("lib.cmd_pr").generate(self.state(), self.dir, head)
        text = body.read_text()
        self.assertIn("## Overrides by the user", text)
        self.assertIn("C1 can’t happen in production", text.split("## Overrides")[1])

    def test_a_fix_before_the_first_commit_is_gated_with_the_build(self):
        self.ship_ready()
        self.lint()
        self.assertIn("commit: run", self.next(0)["ACTION"])
        state = self.state()  # `commit` failed (a hook refused it, say)
        state["phase6"]["commit_attempt"] = {"result": "commit-failed",
                                             "seq": state.get("events", 0) + 5}
        self.write_state(state)
        n = self.fix(self.next(4), "drop the debug line the hook refused")[1]
        (self.worktree / "due.ts").write_text("export const due = 2;\n")
        self.report(n, changed="- `due.ts` — the debug line dropped")
        self.answer("fixer", n, "FIXED", fix_report="x", changed="1")
        self.quality_gate()  # the gate runs on the fix, no worker
        self.assertIn("commit: run", self.next(0)["ACTION"])

    def test_a_fix_before_the_first_review_still_gets_the_whole_change_reviewed(self):
        # Committed, then a stop before the first review pass (the draft's
        # description refused), and a fix that changes the code.
        _sha, _url, _out, body = self.to_body()
        state = self.state()
        state["phase6"]["publish_attempt"] = {"result": "problems", "problems": ["x"],
                                              "seq": state.get("events", 0) + 5}
        self.write_state(state)
        n = self.fix(self.next(4), "rename the helper")[1]
        (self.worktree / "sort.ts").write_text("export const sort = 2;\n")
        self.report(n, changed="- `sort.ts` — the rename the user asked for")
        self.answer("fixer", n, "FIXED", fix_report="x", changed="1")
        self.quality_gate()
        self.assertIn("commit: run", self.next(0)["ACTION"])  # no pass on the fix alone
        self.assertEqual(self.state()["phase6"]["passes"], [])
        r = self.autodev("commit", "--message", "fix: rename", "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        out = self.next(0)
        self.sh("git", "push", "-q", "origin", "HEAD", cwd=self.worktree)
        self.after(out)
        out = self.next(0)  # the draft's description, for the new commit
        body.write_text(re.sub(r"<!-- WRITE: .*?-->", "Todos can carry a due date.",
                               body.read_text()))
        sha = self.state()["phase6"]["verified_sha"]
        gh = json.loads((self.tmp / "gh.json").read_text())
        self.script_gh([{"args": ["pr", "view", "12", "--json", "number,url,body"],
                         "stdout": json.dumps({"number": 12, "url": "https://x/pull/12",
                                               "body": f"Checked at commit {sha}"})}] + gh)
        self.after(out)
        _, jobs = self.reviewers()  # the whole change, the fix with it
        self.assertEqual(self.sets(*jobs[0])["scope"], "first")
        self.assertIn("sort.ts", self.sets(*jobs[0])["files"])
        self.assertEqual([p["scope"] for p in self.state()["phase6"]["passes"]], ["first"])

    def test_a_fix_in_phase_6_is_gated_verified_and_reviewed(self):
        out = self.unchanged_correction()
        n = self.fix(out, "guard the sort against a missing due date")[1]
        (self.worktree / "sort.ts").write_text("export const sort = 2;\n")
        self.report(n, changed="- `sort.ts` — the guard the user asked for")
        self.answer("fixer", n, "FIXED", fix_report="x", changed="1")
        self.quality_gate()
        self.assertEqual(self.state()["phase6"]["corrections"][-1]["entry"], "fix")
        out, jobs = self.reviewers()  # the fix, on top of the commit
        self.assertEqual(self.sets(*jobs[0])["scope"], "after-commit")

    def test_a_fix_inside_an_open_correction_is_reviewed_with_it(self):
        self.draft_pr()
        _, jobs = self.reviewers()
        for w, n in jobs:
            (self.dir / "review" / "pass-1" / f"{self.sets(w, n)['reviewer']}.md").write_text(
                r_report("- null due date crashes sort"))
            self.answer(w, n, "REVIEWED", findings="1", leads="0")
        (self.dir / "CODE_REVIEW.md").write_text(OPEN_REVIEW.format(tree=self.tree()))
        (self.dir / "review" / "pass-1" / "corrections.md").write_text(
            "# Required changes\n1. C1: guard the sort in src/sort.ts\n")
        self.expect("review-judge", "MUST_FIX", must_fix_open="1", revote="0")
        _, jobs = self.expect("coder")
        (self.worktree / "coder.ts").write_text("export const c = 1;\n")
        self.answer(*jobs[0], "BUILT", blocked="0", test_changes="none")
        self.quality_gate(red=True)
        self.expect("coder", "BUILT", blocked="0", test_changes="none")  # the gate's round
        self.quality_gate(red=True)
        n = self.fix(self.next(4), "relax the line length for coder.ts")[1]
        (self.worktree / "fixer.ts").write_text("export const f = 1;\n")
        self.report(n, changed="- `fixer.ts` — what the user asked")
        self.answer("fixer", n, "FIXED", fix_report="x", changed="1")
        self.quality_gate()
        self.assertEqual([k["entry"] for k in self.state()["phase6"]["corrections"]],
                         ["review"])  # no second correction beside the open one
        _, jobs = self.reviewers()  # one pass on both, uncommitted on top of HEAD
        self.assertEqual(self.sets(*jobs[0])["scope"], "after-commit")
        self.assertEqual(sorted(self.sh("git", "diff", "--name-only", "HEAD",
                                        cwd=self.worktree).split() + self.sh(
            "git", "ls-files", "--others", "--exclude-standard",
            cwd=self.worktree).split()), ["coder.ts", "fixer.ts"])


# A saved profile for the setup tests: two gate checks, so a lookup can find
# one of them never adopted.
SAVED_PROFILE = """\
stack: typescript
setup: ["echo ready > setup-ran.txt"]
gate:
  - { kind: test, command: "true", report: "TEST.md" }
  - { kind: lint, command: "npx eslint .", report: "LINT.md" }
"""
BOTH_ADOPTED = "check 1: adopted — package.json:9\ncheck 2: adopted — .eslintrc.json:1\n"
PROFILER_DRAFT = """\
stack: typescript
setup: ["echo ready > setup-ran.txt"]
gate:
  - { kind: test, command: "true", report: "TEST.md" }
"""
PROFILER_REPORT = ("PROFILE\n```yaml\n" + PROFILER_DRAFT + "```\n"
                   "EVIDENCE\n- true: package.json:9\n"
                   "NOT ADOPTED — eslint: no config file or dependency\n"
                   "NOT INSTALLED — jq: not on PATH\n"
                   "QUESTIONS — the e2e suite in CI is left out of the gate; keep it out?\n")
FULL_OVERRIDE = 'setup: ["true"]\ngate:\n  - { kind: test, command: "true", report: "TEST.md" }\n'


class SetupFlowTest(RunCase):
    """`next --repo <repo> --task <task>` sets a run up before it exists: it
    prints the lookup or profiler to spawn and the profile question, then
    creates the run. The origin looks like GitHub (a throwaway git config
    rewrites it to the local bare repo), so profile-path.py names a saved
    profile under AUTO_DEV_PROFILES_DIR; TMPDIR is the test's own folder."""

    TASK = "Add due dates to todos"
    OPTIONS = ("Looks right — save it for this repo", "Looks right — use it for this run only",
               "Change something (tell me what)", "Stop")

    def setUp(self):
        super().setUp()
        self.temp = self.tmp / "tmpdir"
        self.temp.mkdir()
        self.profiles = self.tmp / "profiles"
        gitconfig = self.tmp / "gitconfig"
        gitconfig.write_text(f'[url "file://localhost{self.tmp / "origin.git"}"]\n'
                             "\tinsteadOf = https://github.com/acme/app.git\n")
        self.env.update(TMPDIR=str(self.temp), AUTO_DEV_PROFILES_DIR=str(self.profiles),
                        GIT_CONFIG_GLOBAL=str(gitconfig))
        self.sh("git", "remote", "set-url", "origin", "https://github.com/acme/app.git",
                cwd=self.repo)
        r = subprocess.run([sys.executable, str(SCRIPTS / "profile-path.py"), str(self.repo)],
                           capture_output=True, text=True, env=self.env, check=False)
        self.assertIn(r.returncode, (0, 1), r.stdout + r.stderr)
        self.saved = Path(r.stdout.splitlines()[0].split(": ", 1)[1])
        self.worktree = self.tmp / "app-add-due-dates-to-todos"
        self.dir = self.worktree / ".auto-dev"
        self.outs = []

    # -------------------------------------------------------------- driving

    def setup_next(self, *extra, task=None, wait="5", expect=None):
        r = self.autodev("next", "--repo", self.repo, "--task", task or self.TASK,
                         "--max-wait", wait, *extra, "--json")
        try:
            out = json.loads(r.stdout)
        except ValueError:
            self.fail(f"next --repo printed no JSON (exit {r.returncode}):\n"
                      f"{r.stdout}{r.stderr}")
        self.outs.append(out)
        shown = json.dumps(out, indent=2)
        self.assertEqual(out.get("exit"), r.returncode, shown)
        if expect is not None:
            self.assertEqual(out.get("exit"), expect, shown)
        return out

    def next_dir(self, expect=None):
        r = self.autodev("next", "--dir", self.dir, "--json")
        try:
            out = json.loads(r.stdout)
        except ValueError:
            self.fail(f"next --dir printed no JSON (exit {r.returncode}):\n"
                      f"{r.stdout}{r.stderr}")
        if expect is not None:
            self.assertEqual(out.get("exit"), expect, json.dumps(out, indent=2))
        return out

    def brief(self, out, worker):
        """The slot values of the one `worker` brief `out` spawns."""
        self.assertEqual(out.get("AGENT"), [f"auto-dev:{worker}"], json.dumps(out, indent=2))
        path = Path(out["BRIEF"][0])
        values, name = {"path": str(path)}, None
        for line in path.read_text().splitlines()[1:]:
            if line.startswith("  ") and name:
                values[name] += "\n" + line[2:]
            else:
                name, _, value = line.partition(": ")
                values[name] = value
        return values

    def returns(self, values, worker, status, answer, **data):
        answer_file = values.get("answer_file") or values["result_file"][:-5] + "-answer.md"
        if answer is not None:
            Path(answer_file).write_text(answer)
        Path(values["result_file"]).write_text(json.dumps(
            {"worker": worker, "status": status, **data}))

    def lookup_answers(self, out, answer, status="ok", nxt="ANSWERED"):
        values = self.brief(out, "lookup")
        self.returns(values, "lookup", status, answer, next=nxt,
                     answer_file=values.get("answer_file", "none"))
        return values

    def profiler_returns(self, out, draft=PROFILER_DRAFT, status="ok"):
        values = self.brief(out, "profiler")
        Path(values["draft_path"]).write_text(draft)
        self.returns(values, "profiler", status, PROFILER_REPORT, next="CONFIRM",
                     draft=values["draft_path"], questions="1")
        return values

    def to_question(self, task=None):
        self.profiler_returns(self.setup_next(task=task, expect=0))
        return self.setup_next(task=task, expect=5)

    def with_saved_profile(self, answer, text=SAVED_PROFILE, **kw):
        """A saved profile, its lookup answered with `answer`; the next `next`."""
        self.save_profile(text)
        self.lookup_answers(self.setup_next(expect=0, **kw), answer)
        return self.setup_next(**kw)

    def save_profile(self, text=SAVED_PROFILE):
        self.saved.parent.mkdir(parents=True, exist_ok=True)
        self.saved.write_text(text)

    def commit_override(self, text):
        seed = self.tmp / "seed"
        (seed / ".auto-dev.yml").write_text(text)
        self.sh("git", "add", ".auto-dev.yml", cwd=seed)
        self.sh("git", "commit", "-q", "-m", "override", cwd=seed)
        self.sh("git", "push", "-q", "origin", "main", cwd=seed)
        self.sh("git", "pull", "-q", "--ff-only", "origin", "main", cwd=self.repo)

    def options(self, out):
        return tuple(o["label"]
                     for o in json.loads(out["QUESTION"])["questions"][0]["options"])

    def answer_with(self, out, label, text="drop the lint check"):
        """Run the AFTER line for `label`, its placeholder filled with `text`."""
        line = next((ln.split(" → ", 1)[1] for ln in out.get("AFTER", [])
                     if ln.startswith(f'"{label}"')), None)
        self.assertIsNotNone(line, json.dumps(out, indent=2))
        line = re.sub(r"'<[^']*>'", lambda _: shlex.quote(text), line)
        return subprocess.run(line, shell=True, capture_output=True, text=True,
                              env=self.env, cwd=self.tmp, check=False)

    def answered(self, out, label, text="drop the lint check"):
        r = self.answer_with(out, label, text)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def ready(self, out, worktree=None):
        """`out` is the action to move into a created run's worktree."""
        shown = json.dumps(out, indent=2)
        self.assertEqual(out.get("exit"), 0, shown)
        after = out.get("AFTER", [])
        self.assertEqual(len(after), 1, shown)
        argv = shlex.split(after[0])
        self.assertEqual(argv[:4], ["python3", str(AUTODEV), "next", "--dir"], shown)
        self.assertEqual(len(argv), 5, shown)
        ad = Path(argv[4])
        if worktree is not None:
            self.assertEqual(ad, worktree / ".auto-dev", shown)
        self.worktree, self.dir = ad.parent, ad
        self.assertTrue((ad / "state.json").exists(), shown)
        self.assertIn(str(ad.parent), out.get("ACTION", ""), shown)

    def to_the_planner(self):
        for _ in range(3):
            out = self.next_dir(0)
            if out.get("AGENT"):
                self.assertEqual(out["AGENT"], ["auto-dev:planner"], json.dumps(out, indent=2))
                return out
        self.fail("next --dir never spawned the planner")

    def profile_line(self):
        for line in (self.dir / "profile.md").read_text().splitlines():
            if line.startswith("- **Profile:** "):
                return line[len("- **Profile:** "):]
        self.fail("profile.md has no Profile line")

    def gate(self):
        return [check["command"] for check in self.state()["settings"]["gate"]]

    def work_log(self):
        return (self.dir / "WORK_LOG.md").read_text()

    def summary(self, out):
        return "\n".join(out.get("SUMMARY", []))

    def no_run_made(self):
        self.assertEqual(sorted(p.name for p in self.tmp.glob("app-*")), [])

    def worker_briefs(self):
        return sorted(p.name for p in self.temp.rglob("*.md")
                      if re.match(r"(profiler|lookup)-\d+\.md$", p.name))

    def failed_setup(self):
        """A saved profile whose setup is `false`: the run is made and stops."""
        self.save_profile(SAVED_PROFILE.replace("echo ready > setup-ran.txt", "false"))
        out = self.with_saved_profile(BOTH_ADOPTED, text=self.saved.read_text())
        self.assertEqual(out.get("exit"), 4, json.dumps(out, indent=2))
        report = "\n".join(out.get("REPORT", []))
        for part in ("false", "exited 1", str(self.saved)):
            self.assertIn(part, report)
        self.assertTrue((self.dir / "state.json").exists())
        return out

    # -------------------------------------------------------------- a saved profile

    def test_a_saved_profile_sets_up_the_run_after_one_lookup(self):
        self.save_profile()
        out = self.setup_next(expect=0)
        self.assertIn("npx eslint .", self.lookup_answers(out, BOTH_ADOPTED)["question"])
        out = self.setup_next(expect=0)
        self.ready(out, self.tmp / "app-add-due-dates-to-todos")
        self.assertEqual(self.state()["branch"], "feat/add-due-dates-to-todos")
        self.assertEqual(self.sh("git", "branch", "--show-current", cwd=self.worktree).strip(),
                         "feat/add-due-dates-to-todos")
        self.assertEqual(self.profile_line(), f"saved profile {self.saved}")
        profile_md = (self.dir / "profile.md").read_text()
        self.assertIn("| 1 | test | `true` |", profile_md)
        self.assertIn("| 2 | lint | `npx eslint .` |", profile_md)
        self.assertTrue([ln for ln in out.get("SUMMARY", [])
                         if f"Using the saved profile at {self.saved}" in ln],
                        json.dumps(out, indent=2))
        self.assertEqual([a for o in self.outs for a in o.get("AGENT", [])],
                         ["auto-dev:lookup"])
        self.assertFalse([o for o in self.outs if o.get("exit") == 5 or o.get("QUESTION")])

    def test_a_lookup_with_no_usable_answer_keeps_every_check(self):
        cases = [("failed", "ANSWERED", "check 2: not adopted — no eslint config\n"),
                 ("blocked", "ANSWERED", "check 2: not adopted — no eslint config\n"),
                 ("ok", "OUT_OF_SCOPE", "OUT_OF_SCOPE: whether eslint counts is a verdict\n"),
                 ("ok", "ANSWERED", "Both tools look used to me.\n")]
        self.save_profile()
        for i, (status, nxt, answer) in enumerate(cases, 1):
            with self.subTest(status=status, next=nxt):
                task = f"Add due dates case {i}"
                self.lookup_answers(self.setup_next(task=task, expect=0), answer,
                                    status=status, nxt=nxt)
                out = self.setup_next(task=task)
                self.ready(out)
                self.assertEqual(self.gate(), ["true", "npx eslint ."])
                self.assertNotIn("dropped gate check", self.work_log())

    def test_a_check_the_repo_never_adopted_is_left_out_of_this_run(self):
        out = self.with_saved_profile("check 1: adopted — package.json:9\n"
                                      "check 2: not adopted — no eslint config or dependency\n")
        self.ready(out, self.tmp / "app-add-due-dates-to-todos")
        self.assertEqual(self.gate(), ["true"])
        self.assertEqual(self.profile_line(), f"saved profile {self.saved}, without npx eslint .")
        self.assertIn(f"dropped gate check npx eslint .: the repo never adopted its tool "
                      f"(saved profile {self.saved})", self.work_log())
        self.assertTrue([ln for ln in out.get("SUMMARY", [])
                         if "npx eslint ." in ln and str(self.saved) in ln],
                        json.dumps(out, indent=2))
        self.assertEqual(self.saved.read_text(), SAVED_PROFILE)

    def test_contradicting_or_out_of_range_answer_lines_drop_nothing(self):
        out = self.with_saved_profile("check 1: adopted — package.json:9\n"
                                      "check 2: adopted — package.json:12\n"
                                      "check 2: not adopted — no eslint config\n"
                                      "check 7: not adopted — no such tool\n")
        self.ready(out, self.tmp / "app-add-due-dates-to-todos")
        self.assertEqual(self.gate(), ["true", "npx eslint ."])
        self.assertNotIn("dropped gate check", self.work_log())

    def test_a_lookup_answer_in_doubt_drops_no_check(self):
        out = self.with_saved_profile("I could not tell for check 2\n")
        self.ready(out, self.tmp / "app-add-due-dates-to-todos")
        self.assertEqual(self.gate(), ["true", "npx eslint ."])
        self.assertNotIn("dropped gate check", self.work_log())

    # -------------------------------------------------------------- researching a profile

    def test_with_no_profile_the_profiler_researches_then_the_user_is_asked(self):
        out = self.setup_next(expect=0)
        values = self.brief(out, "profiler")
        self.assertEqual(values["repo"], str(self.repo))
        self.assertEqual(values["base"], "main")
        scratch = self.temp / f"auto-dev-setup-{os.getuid()}"
        self.assertTrue(str(values["draft_path"]).startswith(f"{scratch}{os.sep}"), values)
        self.profiler_returns(out)
        out = self.setup_next(expect=5)
        shown = json.dumps(out, indent=2)
        summary = self.summary(out)
        for line in PROFILER_DRAFT.splitlines():
            self.assertIn(line.strip(), summary)
        questions = summary.find("the e2e suite in CI")
        self.assertNotEqual(questions, -1, shown)
        for later in ("jq: not on PATH", "package.json:9"):
            self.assertGreater(summary.find(later), questions, shown)
        self.assertTrue([ln for ln in out["SUMMARY"] if f"Save path: {self.saved}" in ln], shown)
        self.assertEqual(self.options(out), self.OPTIONS)
        self.assertEqual(len(out["AFTER"]), 4, shown)
        for label, line in zip(self.OPTIONS, out["AFTER"]):
            self.assertTrue(line.startswith(f'"{label}" → '), shown)
        self.no_run_made()
        self.assertEqual(self.sh("git", "status", "--porcelain", cwd=self.repo), "")

    def test_an_origin_with_no_save_path_leaves_out_the_save_option(self):
        self.sh("git", "remote", "set-url", "origin", str(self.tmp / "origin.git"),
                cwd=self.repo)
        out = self.to_question()
        self.assertEqual(self.options(out), self.OPTIONS[1:])
        self.assertEqual(len(out["AFTER"]), 3, json.dumps(out, indent=2))
        self.assertRegex(self.summary(out).lower(), r"can(no|'|’)t be saved")
        self.no_run_made()

    def test_the_save_answer_writes_the_profile_and_creates_the_run(self):
        self.answered(self.to_question(), self.OPTIONS[0])
        out = self.setup_next()
        self.ready(out, self.tmp / "app-add-due-dates-to-todos")
        name = self.saved.relative_to(self.profiles).with_suffix("").as_posix()
        days = {datetime.now().date().isoformat(),
                datetime.now(timezone.utc).date().isoformat()}
        self.assertIn(self.saved.read_text().splitlines()[0],
                      {f"# auto-dev profile for {name}, saved {day}" for day in days})
        r = subprocess.run([sys.executable, str(SCRIPTS / "validate-config.py"), "--profile",
                            str(self.saved)], capture_output=True, text=True, env=self.env,
                           check=False)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.profile_line(), "researched by the profiler, confirmed by the user")

    def test_the_run_only_answer_creates_the_run_without_saving_the_profile(self):
        self.answered(self.to_question(), self.OPTIONS[1])
        self.ready(self.setup_next(), self.tmp / "app-add-due-dates-to-todos")
        self.assertFalse(self.saved.exists())

    def test_the_change_answer_has_the_profiler_redo_the_draft_then_asks_again(self):
        first = self.brief(self.setup_next(expect=0), "profiler")
        self.profiler_returns(self.outs[-1])
        self.answered(self.setup_next(expect=5), self.OPTIONS[2], "drop the lint check")
        out = self.setup_next(expect=0)
        values = self.brief(out, "profiler")
        self.assertNotEqual(values["path"], first["path"])
        self.assertIn("drop the lint check", values["previous_issues"])
        self.profiler_returns(out)
        out = self.setup_next(expect=5)
        self.assertEqual(self.options(out), self.OPTIONS)
        self.no_run_made()

    def test_the_stop_answer_ends_setup_with_nothing_created(self):
        self.answered(self.to_question(), "Stop")
        out = self.setup_next(expect=4)
        report = " ".join(out.get("REPORT", [])).lower()
        self.assertIn("profile question", report)
        self.assertIn("nothing", report)
        self.no_run_made()
        self.brief(self.setup_next(expect=0), "profiler")  # a later call starts over

    def test_a_profile_that_cannot_be_saved_still_sets_up_the_run(self):
        blocker = self.profiles / self.saved.relative_to(self.profiles).parts[0]
        self.profiles.mkdir()
        blocker.write_text("a file where the folder should be\n")
        out = self.to_question()
        self.answered(out, self.OPTIONS[0])
        out = self.setup_next()
        self.ready(out, self.tmp / "app-add-due-dates-to-todos")
        summary = self.summary(out)
        self.assertRegex(summary.lower(), r"not (been )?saved")
        self.assertIn(str(blocker), summary)
        for line in PROFILER_DRAFT.splitlines():
            self.assertIn(line.strip(), summary)
        self.assertFalse(self.saved.exists())

    def test_an_invalid_saved_profile_is_researched_and_offered_for_overwrite(self):
        self.save_profile('stack: typescript\nsetup: ["true"]\n')
        out = self.setup_next(expect=0)
        self.profiler_returns(out)  # the profiler, not a lookup
        out = self.setup_next(expect=5)
        shown = json.dumps(out, indent=2)
        self.assertIn("a saved profile must set `gate`", self.summary(out))
        self.assertIn(self.OPTIONS[0], self.options(out))
        self.assertTrue([ln for ln in out["SUMMARY"] if f"Save path: {self.saved}" in ln], shown)
        self.assertNotIn("auto-dev:lookup", [a for o in self.outs for a in o.get("AGENT", [])])

    def test_an_invalid_draft_is_sent_back_once_then_setup_stops(self):
        bad = 'stack: typescript\nsetup: ["true"]\n'
        first = self.profiler_returns(self.setup_next(expect=0), draft=bad)
        out = self.setup_next(expect=0)
        values = self.brief(out, "profiler")
        self.assertNotEqual(values["path"], first["path"])
        self.assertIn("must set `gate`", values["previous_issues"])
        self.profiler_returns(out, draft=bad)
        out = self.setup_next(expect=4)
        self.assertIn("must set `gate`", "\n".join(out.get("REPORT", [])))
        self.assertNotIn("QUESTION", out)
        self.no_run_made()

    # -------------------------------------------------------------- .auto-dev.yml

    def test_an_override_with_setup_and_gate_needs_no_research(self):
        self.commit_override(FULL_OVERRIDE)
        out = self.setup_next()
        self.ready(out, self.tmp / "app-add-due-dates-to-todos")
        self.assertNotIn("AGENT", out)
        self.assertNotIn("QUESTION", out)
        self.assertEqual(self.worker_briefs(), [])
        self.assertEqual(self.profile_line(), ".auto-dev.yml")

    def test_a_partial_override_is_researched_and_listed_in_the_question(self):
        self.commit_override("iteration_budget: 2\n")
        out = self.to_question()
        self.assertTrue([ln for ln in out["SUMMARY"]
                         if "iteration_budget" in ln and ".auto-dev.yml" in ln],
                        json.dumps(out, indent=2))

    def test_an_override_with_an_unknown_key_stops_before_anything(self):
        self.commit_override("iteration_budgt: 2\n")
        out = self.setup_next(expect=4)
        self.assertIn("did you mean `iteration_budget`", "\n".join(out.get("REPORT", [])))
        self.assertNotIn("AGENT", out)
        self.assertEqual(self.worker_briefs(), [])
        self.no_run_made()

    # -------------------------------------------------------------- setup that can't finish

    def test_a_failed_setup_stops_and_continue_runs_it_again_from_the_fixed_profile(self):
        self.failed_setup()
        self.save_profile()  # the user fixes the saved file
        self.next_dir(4)
        self.assertFalse((self.worktree / "setup-ran.txt").exists())
        r = self.autodev("resume", "--repo", self.repo, "--task", self.TASK)
        self.assertIn("RESUME", r.stdout, r.stdout + r.stderr)
        self.to_the_planner()
        self.assertTrue((self.worktree / "setup-ran.txt").exists())

    def test_a_retry_reads_the_saved_profile_with_the_scratch_folder_gone(self):
        self.failed_setup()
        self.save_profile()
        for path in self.temp.iterdir():
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            else:
                path.unlink()
        r = self.autodev("resume", "--repo", self.repo, "--task", self.TASK)
        self.assertIn("RESUME", r.stdout, r.stdout + r.stderr)
        self.to_the_planner()
        self.assertTrue((self.worktree / "setup-ran.txt").exists())

    def test_a_signed_out_gh_stops_before_any_research(self):
        self.script_gh([{"args": ["auth", "status"], "stderr": "not logged in", "exit": 1}])
        out = self.setup_next(expect=4)
        self.assertIn("not signed in", "\n".join(out.get("REPORT", [])))
        self.assertNotIn("AGENT", out)
        self.assertEqual(self.worker_briefs(), [])
        self.no_run_made()
        self.assertEqual(self.sh("git", "branch", "--list", "feat/*", cwd=self.repo), "")

    def test_setup_still_running_at_the_wait_limit_is_an_action(self):
        self.save_profile(SAVED_PROFILE.replace("echo ready > setup-ran.txt", "sleep 3"))
        self.lookup_answers(self.setup_next(expect=0, wait="1"), BOTH_ADOPTED)
        out = self.setup_next(wait="1")
        self.ready(out, self.tmp / "app-add-due-dates-to-todos")

    # -------------------------------------------------------------- running it again

    def test_a_worker_with_no_result_is_waited_for_and_reissue_sends_it_again(self):
        self.brief(self.setup_next(expect=0), "profiler")
        out = self.setup_next(expect=0)
        shown = json.dumps(out, indent=2)
        self.assertTrue(out.get("ACTION", "").startswith("wait"), shown)
        self.assertIn("profiler #1", out["ACTION"], shown)
        self.assertNotIn("AGENT", out, shown)
        values = self.brief(self.setup_next("--reissue", expect=0), "profiler")
        self.assertEqual(Path(values["path"]).name, "profiler-2.md")

    def test_a_third_spawn_with_no_result_stops_naming_the_retry_command(self):
        self.brief(self.setup_next(expect=0), "profiler")
        for _ in range(2):
            self.brief(self.setup_next("--reissue", expect=0), "profiler")
        out = self.setup_next("--reissue", expect=4)
        report = "\n".join(out.get("REPORT", []))
        self.assertIn("profiler", report)
        self.assertTrue([ln for ln in out.get("REPORT", [])
                         if "next" in ln and "--repo" in ln and "--reissue" in ln], report)

    def test_an_existing_run_for_the_task_is_pointed_to_not_made_again(self):
        r = self.autodev("init", "--repo", self.repo, "--slug", "add-due-dates-to-todos",
                         "--task", self.TASK, "--profile", self.profile, "--max-wait", "30")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        before = self.sh("git", "worktree", "list", cwd=self.repo)
        out = self.setup_next()
        self.ready(out, self.tmp / "app-add-due-dates-to-todos")
        self.assertNotIn("AGENT", out)
        self.assertEqual(self.sh("git", "worktree", "list", cwd=self.repo), before)

    def test_a_folder_at_the_worktree_path_gets_a_numbered_suffix(self):
        self.commit_override(FULL_OVERRIDE)
        taken = self.tmp / "app-add-due-dates-to-todos"
        taken.mkdir()
        out = self.setup_next()
        self.ready(out, self.tmp / "app-add-due-dates-to-todos-2")
        self.assertEqual(self.state()["branch"], "feat/add-due-dates-to-todos-2")
        self.assertEqual(list(taken.iterdir()), [])

    def test_a_leftover_branch_gets_a_numbered_suffix(self):
        self.commit_override(FULL_OVERRIDE)
        self.sh("git", "branch", "feat/add-due-dates-to-todos", cwd=self.repo)
        out = self.setup_next(expect=0)
        self.ready(out, self.tmp / "app-add-due-dates-to-todos-2")
        self.assertEqual(self.state()["branch"], "feat/add-due-dates-to-todos-2")
        self.assertFalse((self.tmp / "app-add-due-dates-to-todos").exists())

    # -------------------------------------------------------------- a Jira ticket

    def test_ticket_details_given_once_reach_the_run(self):
        text = "Add due dates\n\nTodos get an optional due date."
        url = "https://acme.atlassian.net/browse/PROJ-123"
        ticket = self.tmp / "t.txt"
        ticket.write_text(text)
        self.save_profile()
        out = self.setup_next("--ticket", "PROJ-123", "--ticket-url", url,
                              "--ticket-text-file", ticket, "--jira", "available, cloudId abc",
                              task="PROJ-123", expect=0)
        self.lookup_answers(out, BOTH_ADOPTED)
        out = self.setup_next(task="PROJ-123")
        self.ready(out)
        state = self.state()
        self.assertEqual(state["branch"], "feat/proj-123-add-due-dates")
        self.assertEqual(state["task"]["ticket"], "PROJ-123")
        self.assertEqual(state["task"]["ticket_url"], url)
        self.assertEqual(state["task"]["ticket_text"], text)
        self.assertIn("- **Jira:** available, cloudId abc\n",
                      (self.dir / "profile.md").read_text())
        values = self.brief(self.to_the_planner(), "planner")
        self.assertEqual(values["task"], text)

    def test_a_missing_or_empty_ticket_text_file_cannot_run(self):
        self.save_profile()
        empty = self.tmp / "empty.txt"
        empty.write_text("")
        for path in (self.tmp / "missing.txt", empty):
            with self.subTest(file=path.name):
                r = self.autodev("next", "--repo", self.repo, "--task", "PROJ-123",
                                 "--ticket", "PROJ-123", "--ticket-text-file", path, "--json")
                both = r.stdout + r.stderr
                self.assertEqual(r.returncode, 2, both)
                self.assertIn("ERROR", both)
                self.assertIn(str(path), both)
                self.assertEqual(self.worker_briefs(), [])
        # The same call with a readable file goes on: the file was the cause.
        readable = self.tmp / "t.txt"
        readable.write_text("Add due dates\n\nTodos get an optional due date.")
        self.brief(self.setup_next("--ticket", "PROJ-123", "--ticket-text-file", readable,
                                   task="PROJ-123", expect=0), "lookup")

    def test_a_ticket_run_keeps_the_ask_in_the_user_s_words(self):
        ask = "Add due dates to todos"
        self.save_profile()
        out = self.setup_next("--ticket", "PROJ-123", "--ask", ask,
                              "--jira", "unavailable: no Atlassian MCP",
                              task="PROJ-123", expect=0)
        self.lookup_answers(out, BOTH_ADOPTED)
        self.ready(self.setup_next(task="PROJ-123"))
        tree = self.worktree
        self.assertEqual(self.state()["task"]["ask"], ask)
        # With Jira unavailable there is no ticket text: the planner gets the ask.
        values = self.brief(self.to_the_planner(), "planner")
        self.assertEqual(values["task"], ask)
        # The user's own wording finds the run again.
        r = self.autodev("resume", "--repo", self.repo, "--task", ask)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertRegex(r.stdout, r"^(RESUME|ASK)\b", r.stdout)
        before = self.sh("git", "worktree", "list", cwd=self.repo)
        out = self.setup_next(task=ask)
        self.ready(out, tree)
        self.assertNotIn("AGENT", out)
        self.assertEqual(self.sh("git", "worktree", "list", cwd=self.repo), before)

    # -------------------------------------------------------------- safety

    @unittest.skipUnless(hasattr(os, "getuid"), "POSIX folder ownership")
    def test_a_scratch_parent_others_can_write_to_or_a_symlink_is_refused(self):
        parent = self.temp / f"auto-dev-setup-{os.getuid()}"
        theirs = self.tmp / "theirs"
        theirs.mkdir()
        for case in ("writable by others", "a symlink"):
            with self.subTest(case=case):
                if parent.is_symlink():
                    parent.unlink()
                elif parent.exists():
                    shutil.rmtree(parent)
                if case == "a symlink":
                    parent.symlink_to(theirs, target_is_directory=True)
                    watched, why = theirs, r"link"
                else:
                    parent.mkdir()
                    os.chmod(parent, 0o777)
                    watched, why = parent, r"writ"
                r = self.autodev("next", "--repo", self.repo, "--task", self.TASK, "--json")
                both = r.stdout + r.stderr
                self.assertEqual(r.returncode, 2, both)
                self.assertIn("ERROR", both)
                self.assertIn(str(parent), both)
                self.assertRegex(both.lower(), why)
                self.assertEqual(list(watched.iterdir()), [])
                self.no_run_made()

    def test_task_text_in_the_printed_commands_never_runs_as_shell(self):
        task = "Add dates'; touch pwned; echo '"
        question = self.to_question(task=task)
        for line in question["AFTER"]:
            argv = shlex.split(re.sub(r"'<[^']*>'", "'x'", line.split(" → ", 1)[1]))
            self.assertEqual(argv[argv.index("--task") + 1], task, line)
        self.answered(question, self.OPTIONS[1])
        self.ready(self.setup_next(task=task))
        self.assertEqual(self.state()["task"]["text"], task)
        for label in (self.OPTIONS[0], self.OPTIONS[2], "Stop"):
            self.answer_with(question, label)  # the run exists: these may be refused
        self.assertEqual([str(p) for p in self.tmp.rglob("pwned")], [])

    # -------------------------------------------------------------- more of setup (the coder's)

    def scratch_folder(self):
        folders = [p for p in (self.temp / f"auto-dev-setup-{os.getuid()}").iterdir()
                   if p.is_dir()]
        self.assertEqual(len(folders), 1, folders)
        return folders[0]

    def test_the_scratch_folder_goes_once_the_run_is_set_up(self):
        out = self.with_saved_profile(BOTH_ADOPTED)
        self.ready(out)
        self.assertEqual(list((self.temp / f"auto-dev-setup-{os.getuid()}").iterdir()), [])

    def test_retry_keeps_the_checks_dropped_at_creation(self):
        self.save_profile(SAVED_PROFILE.replace("echo ready > setup-ran.txt", "false"))
        out = self.with_saved_profile("check 1: adopted — package.json:9\n"
                                      "check 2: not adopted — no eslint config\n",
                                      text=self.saved.read_text())
        self.assertEqual(out.get("exit"), 4, json.dumps(out, indent=2))
        self.save_profile()  # the user fixes the setup; the lint check is still listed
        self.autodev("resume", "--repo", self.repo, "--task", self.TASK)
        self.to_the_planner()
        self.assertTrue((self.worktree / "setup-ran.txt").exists())
        self.assertEqual(self.gate(), ["true"])

    def test_a_run_without_an_origin_record_retries_with_the_saved_setup(self):
        self.failed_setup()
        (self.dir / "profile-origin.json").unlink()  # as a run made by 5.0
        self.save_profile(SAVED_PROFILE + '  - { kind: build, command: "make", '
                                          'report: "BUILD.md" }\n')
        self.autodev("resume", "--repo", self.repo, "--task", self.TASK)
        self.to_the_planner()
        self.assertTrue((self.worktree / "setup-ran.txt").exists())
        self.assertEqual(self.gate(), ["true", "npx eslint ."])  # the run's own

    def test_a_draft_the_user_kept_for_the_run_is_retried_from_the_run(self):
        self.answered(self.to_question(), self.OPTIONS[1])
        self.ready(self.setup_next())
        self.assertEqual((self.dir / "profile.yml").read_text(), PROFILER_DRAFT)
        self.assertEqual(json.loads((self.dir / "profile-origin.json").read_text()),
                         {"kind": "draft"})

    def test_a_stale_pre_run_brief_is_sent_again(self):
        self.brief(self.setup_next(expect=0), "profiler")
        setup = self.scratch_folder() / "setup.json"
        info = json.loads(setup.read_text())
        info["spawns"][-1]["issued_at"] = (datetime.now(timezone.utc)
                                           - timedelta(hours=4)).isoformat()
        setup.write_text(json.dumps(info))
        values = self.brief(self.setup_next(expect=0), "profiler")
        self.assertEqual(Path(values["path"]).name, "profiler-2.md")

    def test_reissue_after_the_never_returned_stop_spawns_again(self):
        self.brief(self.setup_next(expect=0), "profiler")
        for _ in range(2):
            self.brief(self.setup_next("--reissue", expect=0), "profiler")
        self.setup_next("--reissue", expect=4)
        self.setup_next(expect=4)  # without --reissue it stays stopped
        values = self.brief(self.setup_next("--reissue", expect=0), "profiler")
        self.assertEqual(Path(values["path"]).name, "profiler-4.md")

    def test_a_profiler_that_fails_twice_stops(self):
        out = self.setup_next(expect=0)
        values = self.brief(out, "profiler")
        self.returns(values, "profiler", "failed", None, next="CONFIRM",
                     draft=values["draft_path"], questions="0")
        out = self.setup_next(expect=0)
        values = self.brief(out, "profiler")
        self.assertIn("failed", values["previous_issues"])
        self.returns(values, "profiler", "failed", None, next="CONFIRM",
                     draft=values["draft_path"], questions="0")
        out = self.setup_next(expect=4)
        self.assertTrue([ln for ln in out["REPORT"] if "--reissue" in ln],
                        json.dumps(out, indent=2))
        self.assertNotIn("QUESTION", out)
        self.no_run_made()

    def test_the_question_says_where_the_report_is_when_it_has_no_file(self):
        out = self.setup_next(expect=0)
        values = self.brief(out, "profiler")
        Path(values["draft_path"]).write_text(PROFILER_DRAFT)
        Path(values["result_file"]).write_text(json.dumps(
            {"worker": "profiler", "status": "ok", "next": "CONFIRM",
             "draft": values["draft_path"], "questions": "0"}))
        out = self.setup_next(expect=5)
        self.assertIn("in its reply", self.summary(out))

    def test_explain_and_setup_flags_without_repo_cannot_run(self):
        for args in (("next", "--repo", self.repo, "--task", self.TASK, "--explain"),
                     ("next", "--task", self.TASK)):
            with self.subTest(args=args):
                r = self.autodev(*args)
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                self.assertIn("ERROR", r.stderr)
        self.assertEqual(self.worker_briefs(), [])

    def test_next_dir_waits_for_setup_still_running(self):
        self.save_profile(SAVED_PROFILE.replace("echo ready > setup-ran.txt",
                                                "sleep 2 && echo ready > setup-ran.txt"))
        self.lookup_answers(self.setup_next(expect=0, wait="1"), BOTH_ADOPTED)
        self.ready(self.setup_next(wait="0"))
        self.assertEqual(self.state()["phases"]["1"]["status"], "in-progress")
        self.to_the_planner()
        self.assertTrue((self.worktree / "setup-ran.txt").exists())
        self.assertEqual(self.state()["phases"]["1"]["status"], "done")

    # -------------------------------------------------------------- more of setup (corrections)

    BAD_DRAFT = 'stack: typescript\nsetup: ["true"]\n'
    JEST_PROFILE = SAVED_PROFILE.replace('command: "true"', 'command: "npx jest"')
    NOT_SAVED = r"not (been )?saved"

    def profiler_fails(self, out, status="failed"):
        values = self.brief(out, "profiler")
        self.returns(values, "profiler", status, None, next="CONFIRM",
                     draft=values["draft_path"], questions="0")
        return values

    def unusable(self, out, kind):
        """The profiler `out` spawns returns `kind`: failed, or an invalid draft."""
        if kind == "failed":
            return self.profiler_fails(out)
        return self.profiler_returns(out, draft=self.BAD_DRAFT)

    def next_in(self, repo, *extra, task=None, wait="5"):
        """`next --repo <repo>` from another checkout than self.repo."""
        r = self.autodev("next", "--repo", repo, "--task", task or self.TASK,
                         "--max-wait", wait, *extra, "--json")
        out = json.loads(r.stdout)
        self.assertEqual(out.get("exit"), r.returncode, r.stdout + r.stderr)
        return out

    def next_dir_with(self, *extra):
        r = self.autodev("next", "--dir", self.dir, *extra, "--json")
        try:
            return json.loads(r.stdout)
        except ValueError:
            self.fail(f"next --dir printed no JSON (exit {r.returncode}):\n{r.stdout}{r.stderr}")

    def report(self, out):
        return "\n".join(out.get("REPORT", []))

    def kept_failed_run(self, out):
        """`out` stops on a failed setup with the run kept: move into it."""
        self.assertEqual(out.get("exit"), 4, json.dumps(out, indent=2))
        self.assertIn("The run is kept", self.report(out))
        runs = [p for p in self.tmp.glob("app-*") if (p / ".auto-dev" / "state.json").exists()]
        self.assertEqual(len(runs), 1, runs)
        self.worktree, self.dir = runs[0], runs[0] / ".auto-dev"

    def resume_to_the_planner(self):
        r = self.autodev("resume", "--repo", self.repo, "--task", self.TASK)
        self.assertIn("RESUME", r.stdout, r.stdout + r.stderr)
        self.to_the_planner()
        self.assertTrue((self.worktree / "setup-ran.txt").exists())

    # C1, C2: a profiler that leaves no usable draft

    def test_reissue_at_the_unusable_profiler_stop_spawns_it_again(self):
        for kind in ("failed", "invalid"):
            with self.subTest(kind=kind):
                task = f"Add due dates {kind}"
                for _ in range(2):
                    self.unusable(self.setup_next(task=task, expect=0), kind)
                self.assertIn("--reissue", self.report(self.setup_next(task=task, expect=4)))
                self.setup_next(task=task, expect=4)  # without --reissue it stays stopped
                out = self.setup_next("--reissue", task=task, expect=0)
                self.assertEqual(Path(self.brief(out, "profiler")["path"]).name, "profiler-3.md")
                # A fresh count: one more unusable return is sent back, not a stop.
                self.unusable(out, kind)
                out = self.setup_next(task=task, expect=0)
                self.assertEqual(Path(self.brief(out, "profiler")["path"]).name, "profiler-4.md")

    def test_unusable_returns_of_either_kind_stop_at_the_second(self):
        for order in (("failed", "invalid"), ("invalid", "failed")):
            with self.subTest(order=order):
                task = f"Add due dates {order[0]} first"
                self.unusable(self.setup_next(task=task, expect=0), order[0])
                self.unusable(self.setup_next(task=task, expect=0), order[1])
                report = self.report(self.setup_next(task=task, expect=4))
                self.assertIn("status failed", report)
                self.assertIn("must set `gate`", report)
                self.assertIn("--reissue", report)
                self.assertNotIn("profiler-3.md", self.worker_briefs())
        self.no_run_made()

    # C5: a retry after the user's change keeps the change

    def test_a_retry_after_a_change_keeps_the_user_s_request(self):
        for kind, why in (("failed", "status failed"), ("invalid", "must set `gate`")):
            with self.subTest(kind=kind):
                task = f"Add due dates {kind}"
                self.answered(self.to_question(task=task), self.OPTIONS[2], "drop the lint check")
                self.unusable(self.setup_next(task=task, expect=0), kind)
                values = self.brief(self.setup_next(task=task, expect=0), "profiler")
                for part in ("drop the lint check", "Start from that draft", why):
                    self.assertIn(part, values["previous_issues"])

    # C3, C4: a saved profile that changes, goes, or loses its test check

    def test_a_lookup_that_leaves_no_test_check_stops_naming_the_saved_file(self):
        out = self.with_saved_profile("check 1: not adopted — no jest dependency\n"
                                      "check 2: adopted — .eslintrc.json:1\n",
                                      text=self.JEST_PROFILE)
        self.assertEqual(out.get("exit"), 4, json.dumps(out, indent=2))
        report = out.get("REPORT", [])
        self.assertTrue([ln for ln in report if "npx jest" in ln and "not adopted" in ln], report)
        self.assertTrue([ln for ln in report if str(self.saved) in ln], report)
        self.assertFalse([ln for ln in report if "profile.yml" in ln], report)
        self.no_run_made()

    def test_a_changed_saved_profile_is_looked_up_again(self):
        self.with_saved_profile("check 1: not adopted — no jest dependency\n"
                                "check 2: adopted — .eslintrc.json:1\n", text=self.JEST_PROFILE)
        self.assertEqual(self.outs[-1].get("exit"), 4)
        self.save_profile()  # the user makes check 1 another test command
        values = self.lookup_answers(self.setup_next(expect=0), BOTH_ADOPTED)
        self.assertIn("`true`", values["question"])
        self.ready(self.setup_next())
        self.assertEqual(self.gate(), ["true", "npx eslint ."])

    def test_a_saved_profile_removed_after_its_lookup_is_researched(self):
        self.save_profile()
        self.brief(self.setup_next(expect=0), "lookup")
        self.saved.unlink()
        self.brief(self.setup_next(expect=0), "profiler")

    # C6: a kept run's failed setup says what its profile left out or didn't save

    def test_a_kept_run_s_failed_setup_names_the_dropped_check(self):
        self.save_profile(SAVED_PROFILE.replace("echo ready > setup-ran.txt", "false"))
        out = self.with_saved_profile("check 1: adopted — package.json:9\n"
                                      "check 2: not adopted — no eslint config\n",
                                      text=self.saved.read_text())
        self.kept_failed_run(out)
        self.assertTrue([ln for ln in out["REPORT"] if "npx eslint ." in ln
                         and str(self.saved) in ln], self.report(out))

    def test_a_kept_run_s_failed_setup_shows_a_draft_that_was_not_saved(self):
        blocker = self.profiles / self.saved.relative_to(self.profiles).parts[0]
        self.profiles.mkdir()
        blocker.write_text("a file where the folder should be\n")
        draft = PROFILER_DRAFT.replace("echo ready > setup-ran.txt", "false")
        self.profiler_returns(self.setup_next(expect=0), draft=draft)
        self.answered(self.setup_next(expect=5), self.OPTIONS[0])
        out = self.setup_next(expect=4)
        self.kept_failed_run(out)
        report = self.report(out)
        self.assertRegex(report, self.NOT_SAVED)
        self.assertIn(str(blocker), report)
        self.assertIn('setup: ["false"]', report)

    # C7, C16: Stop, then the start-over command

    def stop_then_start_over(self, *flags):
        """Answer Stop, run the start-over command the REPORT prints, then take
        setup to the run (run-only)."""
        self.profiler_returns(self.setup_next(*flags, task="PROJ-123", expect=0))
        self.answered(self.setup_next(task="PROJ-123", expect=5), "Stop")
        out = self.setup_next(task="PROJ-123", expect=4)
        line = next((ln for ln in out["REPORT"] if "start over" in ln), None)
        self.assertIsNotNone(line, self.report(out))
        argv = shlex.split(re.search(r"`([^`]*)`", line).group(1))
        r = subprocess.run([*argv, "--max-wait", "5", "--json"], capture_output=True,
                           text=True, env=self.env, cwd=self.tmp, check=False)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.profiler_returns(json.loads(r.stdout))
        self.answered(self.setup_next(task="PROJ-123", expect=5), self.OPTIONS[1])
        self.ready(self.setup_next(task="PROJ-123"))

    def test_start_over_after_stop_keeps_the_ticket_details(self):
        text = "Add due dates\n\nTodos get an optional due date."
        url = "https://acme.atlassian.net/browse/PROJ-123"
        ticket = self.tmp / "t.txt"
        ticket.write_text(text)
        self.stop_then_start_over("--ticket", "PROJ-123", "--ticket-url", url,
                                  "--ticket-text-file", ticket,
                                  "--jira", "available, cloudId abc")
        task = self.state()["task"]
        self.assertEqual((task["ticket"], task["ticket_url"], task["ticket_text"]),
                         ("PROJ-123", url, text))
        self.assertIn("- **Jira:** available, cloudId abc\n",
                      (self.dir / "profile.md").read_text())

    def test_start_over_after_stop_keeps_the_ask(self):
        ask = "Add due dates to todos"
        self.stop_then_start_over("--ticket", "PROJ-123", "--ask", ask,
                                  "--jira", "unavailable: no Atlassian MCP")
        self.assertEqual(self.state()["task"]["ask"], ask)
        self.assertEqual(self.brief(self.to_the_planner(), "planner")["task"], ask)
        r = self.autodev("resume", "--repo", self.repo, "--task", ask)
        self.assertNotIn("FRESH", r.stdout, r.stdout + r.stderr)

    # C14: init refuses a confirmed draft before the run exists

    def draft_init_refuses(self, label):
        (self.repo / "notes.txt").write_text("not ignored\n")
        values = self.profiler_returns(self.setup_next(expect=0),
                                       draft=PROFILER_DRAFT + 'worktree_files: ["notes.txt"]\n')
        question = self.setup_next(expect=5)
        self.answered(question, label)
        out = self.setup_next(expect=4)
        self.assertTrue(out["REPORT"][0].startswith("Setup stopped before the run was created"),
                        self.report(out))
        self.assertIn(values["draft_path"], self.report(out))
        self.no_run_made()
        return question

    def test_init_refusing_a_draft_opens_the_profile_question_again(self):
        question = self.draft_init_refuses(self.OPTIONS[1])
        self.answered(question, self.OPTIONS[2], "drop notes.txt from worktree_files")
        values = self.brief(self.setup_next(expect=0), "profiler")
        self.assertIn("drop notes.txt from worktree_files", values["previous_issues"])

    def test_init_refusing_a_saved_draft_runs_from_the_fixed_saved_file(self):
        self.draft_init_refuses(self.OPTIONS[0])
        self.saved.write_text(self.saved.read_text().replace('worktree_files: ["notes.txt"]\n',
                                                             ""))
        self.ready(self.setup_next())
        self.assertEqual(self.state()["settings"].get("worktree_files", []), [])

    # C8: a failed setup retried from where the profile came from

    def test_a_run_only_draft_s_failed_setup_is_retried_from_its_profile_yml(self):
        self.profiler_returns(self.setup_next(expect=0), draft=PROFILER_DRAFT.replace(
            "echo ready > setup-ran.txt", "false"))
        self.answered(self.setup_next(expect=5), self.OPTIONS[1])
        out = self.setup_next(expect=4)
        self.kept_failed_run(out)
        self.assertIn(str(self.dir / "profile.yml"), self.report(out))
        (self.dir / "profile.yml").write_text(PROFILER_DRAFT)
        self.resume_to_the_planner()

    def test_an_override_run_s_failed_setup_is_retried_from_auto_dev_yml(self):
        self.commit_override(FULL_OVERRIDE.replace('setup: ["true"]', 'setup: ["false"]'))
        out = self.setup_next(expect=4)
        self.kept_failed_run(out)
        self.assertIn(str(self.repo / ".auto-dev.yml"), self.report(out))
        (self.repo / ".auto-dev.yml").write_text(FULL_OVERRIDE.replace(
            'setup: ["true"]', 'setup: ["echo ready > setup-ran.txt"]'))
        self.resume_to_the_planner()

    def test_a_profile_saved_at_the_question_is_retried_from_the_saved_file(self):
        self.profiler_returns(self.setup_next(expect=0), draft=PROFILER_DRAFT.replace(
            "echo ready > setup-ran.txt", "false"))
        self.answered(self.setup_next(expect=5), self.OPTIONS[0])
        out = self.setup_next(expect=4)
        self.kept_failed_run(out)
        self.assertIn(str(self.saved), self.report(out))
        self.saved.write_text(self.saved.read_text().replace('"false"',
                                                             '"echo ready > setup-ran.txt"'))
        self.resume_to_the_planner()

    def test_a_run_with_no_origin_and_no_saved_profile_retries_its_own_setup(self):
        flag = ".auto-dev/go.txt"
        self.save_profile(SAVED_PROFILE.replace("echo ready > setup-ran.txt",
                                                f"test -f {flag} && echo ready > setup-ran.txt"))
        self.kept_failed_run(self.with_saved_profile(BOTH_ADOPTED, text=self.saved.read_text()))
        (self.dir / "profile-origin.json").unlink()
        self.saved.unlink()
        (self.worktree / flag).write_text("go\n")
        self.resume_to_the_planner()
        self.assertEqual(self.gate(), ["true", "npx eslint ."])

    def test_a_saved_profile_unreadable_at_retry_stops_with_the_validator_s_errors(self):
        self.save_profile(SAVED_PROFILE.replace("echo ready > setup-ran.txt", "false"))
        self.kept_failed_run(self.with_saved_profile(
            "check 1: adopted — package.json:9\ncheck 2: not adopted — no eslint config\n",
            text=self.saved.read_text()))
        self.saved.write_text("gate: [unclosed\n")
        self.autodev("resume", "--repo", self.repo, "--task", self.TASK)
        out = self.next_dir(4)
        self.assertIn("not valid YAML", self.report(out))

    def test_next_dir_with_setup_still_running_at_its_wait_limit_waits_again(self):
        self.save_profile(SAVED_PROFILE.replace("echo ready > setup-ran.txt", "sleep 6"))
        self.lookup_answers(self.setup_next(expect=0, wait="0"), BOTH_ADOPTED)
        self.ready(self.setup_next(wait="0"))
        out = self.next_dir_with("--max-wait", "1")
        self.assertEqual(out.get("exit"), 0, json.dumps(out, indent=2))
        self.assertNotIn("AGENT", out)
        self.assertTrue([ln for ln in out.get("AFTER", []) if "next --dir" in ln
                         or ("next" in shlex.split(ln) and "--dir" in shlex.split(ln))], out)

    def test_a_retried_setup_that_fails_again_stops_with_phase_1_held(self):
        self.failed_setup()
        self.autodev("resume", "--repo", self.repo, "--task", self.TASK)
        out = self.next_dir(4)
        report = self.report(out)
        self.assertIn("exited 1", report)
        self.assertIn("false", report)
        self.assertEqual(self.state()["phases"]["1"]["status"], "held")

    def test_init_continue_that_cannot_run_is_an_error(self):
        self.profiler_returns(self.setup_next(expect=0), draft=PROFILER_DRAFT.replace(
            "echo ready > setup-ran.txt", "false"))
        self.answered(self.setup_next(expect=5), self.OPTIONS[1])
        self.kept_failed_run(self.setup_next(expect=4))
        (self.dir / "profile.yml").unlink()
        (self.dir / "profile.yml").mkdir()  # validate-config.py can't read it: exit 2
        self.autodev("resume", "--repo", self.repo, "--task", self.TASK)
        r = self.autodev("next", "--dir", self.dir)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("ERROR: init --continue could not run", r.stdout + r.stderr)

    def test_a_held_phase_1_names_the_file_to_fix_and_auto_dev_continue(self):
        self.failed_setup()
        report = self.report(self.next_dir(4))
        self.assertIn(str(self.saved), report)
        self.assertIn("auto-dev continue", report)

    # C9: what the SUMMARY says about the run's profile and worktree

    def test_the_summary_names_a_profile_saved_at_the_question(self):
        self.answered(self.to_question(), self.OPTIONS[0])
        self.assertIn(f"Saved the confirmed profile to {self.saved}",
                      self.summary(self.setup_next(expect=0)))

    def test_the_summary_names_a_profile_kept_for_this_run_only(self):
        self.answered(self.to_question(), self.OPTIONS[1])
        self.assertIn("Using the profile the user confirmed, for this run only",
                      self.summary(self.setup_next(expect=0)))

    def test_the_summary_names_a_full_override(self):
        self.commit_override(FULL_OVERRIDE)
        self.assertIn("Using the setup and quality gate the repo's .auto-dev.yml sets",
                      self.summary(self.setup_next(expect=0)))

    def test_a_worktree_the_user_made_is_adopted_and_named_in_the_summary(self):
        self.commit_override(FULL_OVERRIDE)
        for ahead in (0, 1):
            with self.subTest(ahead=ahead):
                mine = self.tmp / f"mine-{ahead}"
                self.sh("git", "worktree", "add", "-q", str(mine), "-b", f"feat/mine-{ahead}",
                        "origin/main", cwd=self.repo)
                if ahead:
                    (mine / "early.ts").write_text("export const e = 1;\n")
                    self.sh("git", "add", "early.ts", cwd=mine)
                    self.sh("git", "commit", "-q", "-m", "early", cwd=mine)
                task = f"Add due dates in mine {ahead}"
                out = self.next_in(mine, task=task)
                self.ready(out, mine)
                summary = self.summary(out)
                self.assertIn("uses the worktree the user made", summary)
                if ahead:
                    self.assertIn("already holds 1 commit(s)", summary)
                else:
                    self.assertNotIn("already holds", summary)

    def test_the_summary_says_setup_is_still_running(self):
        self.save_profile(SAVED_PROFILE.replace("echo ready > setup-ran.txt", "sleep 3"))
        self.lookup_answers(self.setup_next(expect=0, wait="1"), BOTH_ADOPTED)
        out = self.setup_next(wait="1")
        self.ready(out)
        self.assertIn("Setup is still running", self.summary(out))

    # C10: the branch name

    def test_the_branch_name_takes_at_most_five_words(self):
        self.commit_override(FULL_OVERRIDE)
        cases = [("Add due dates to the todo list", "feat/add-due-dates-to-the"),
                 ("!!! ???", "feat/task")]
        for task, branch in cases:
            with self.subTest(task=task):
                self.ready(self.setup_next(task=task))
                self.assertEqual(self.state()["branch"], branch)

    def test_a_ticket_text_that_starts_with_its_key_does_not_repeat_it(self):
        self.commit_override(FULL_OVERRIDE)
        ticket = self.tmp / "t.txt"
        ticket.write_text("PROJ-123 Add due dates\n\nTodos get an optional due date.")
        self.ready(self.setup_next("--ticket", "PROJ-123", "--ticket-text-file", ticket,
                                   task="PROJ-123"))
        self.assertEqual(self.state()["branch"], "feat/proj-123-add-due-dates")

    # C11: a report line that only starts with a section's word

    def test_a_question_starting_with_a_section_word_stays_a_question(self):
        out = self.setup_next(expect=0)
        values = self.brief(out, "profiler")
        Path(values["draft_path"]).write_text(PROFILER_DRAFT)
        report = ("PROFILE\n```yaml\n" + PROFILER_DRAFT + "```\n"
                  "QUESTIONS — the e2e suite in CI is left out of the gate; keep it out?\n"
                  "Profile assumes Node 20 from .nvmrc; confirm the version.\n"
                  "Evidence for the build step is thin.\n"
                  "NOT INSTALLED — jq: not on PATH\n"
                  "EVIDENCE\n- true: package.json:9\n")
        self.returns(values, "profiler", "ok", report, next="CONFIRM",
                     draft=values["draft_path"], questions="3")
        summary = self.setup_next(expect=5)["SUMMARY"]
        later = min(summary.index("NOT INSTALLED — jq: not on PATH"), summary.index("EVIDENCE"))
        for line in ("Profile assumes Node 20 from .nvmrc; confirm the version.",
                     "Evidence for the build step is thin."):
            self.assertIn(line, summary)
            self.assertLess(summary.index(line), later)

    # C12: init stopping or failing before the run exists

    def test_init_stopping_before_the_run_exists_names_the_command_to_run_again(self):
        (self.repo / "notes.txt").write_text("not ignored\n")
        out = self.with_saved_profile(BOTH_ADOPTED,
                                      text=SAVED_PROFILE + 'worktree_files: ["notes.txt"]\n')
        self.assertEqual(out.get("exit"), 4, json.dumps(out, indent=2))
        self.assertTrue(out["REPORT"][0].startswith("Setup stopped before the run was created"))
        self.assertTrue([ln for ln in out["REPORT"] if "next" in ln and "--repo" in ln],
                        self.report(out))
        self.no_run_made()
        self.assertEqual(self.sh("git", "branch", "--list", "feat/*", cwd=self.repo), "")

    def test_init_that_cannot_run_is_an_error(self):
        self.script_gh([*GH_OK[:2], {"args": ["repo", "view", "--json", "defaultBranchRef"],
                                     "stdout": "{}"}])
        self.save_profile()
        self.lookup_answers(self.setup_next(expect=0), BOTH_ADOPTED)
        r = self.autodev("next", "--repo", self.repo, "--task", self.TASK, "--max-wait", "5")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("ERROR: autodev.py init could not run", r.stdout + r.stderr)
        self.no_run_made()

    # C13: branches.prefix and branches.base

    def test_branches_prefix_names_the_branch_and_its_suffix_check(self):
        self.commit_override(FULL_OVERRIDE + "branches:\n  prefix: fix\n")
        self.sh("git", "branch", "feat/add-due-dates-to-todos", cwd=self.repo)
        self.ready(self.setup_next())
        self.assertEqual(self.state()["branch"], "fix/add-due-dates-to-todos")
        self.sh("git", "branch", "fix/add-due-dates-today", cwd=self.repo)
        self.ready(self.setup_next(task="Add due dates today"))
        self.assertEqual(self.state()["branch"], "fix/add-due-dates-today-2")

    def test_branches_base_is_the_profiler_s_base(self):
        self.commit_override("branches:\n  base: develop\n")
        self.assertEqual(self.brief(self.setup_next(expect=0), "profiler")["base"], "develop")

    # C17: --ask needs --repo

    def test_ask_without_repo_cannot_run(self):
        for args in (("next", "--dir", self.dir, "--ask", self.TASK), ("next", "--ask", self.TASK)):
            with self.subTest(args=args[:2]):
                r = self.autodev(*args)
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                self.assertIn("ERROR: --ask needs --repo (it sets a run up)", r.stderr)
        self.assertEqual(self.worker_briefs(), [])

    # C19: a run whose task text matches comes before one whose ask does

    def test_a_run_whose_task_text_matches_comes_before_one_whose_ask_does(self):
        for task, (first, second) in (("Fix login", ("aaa-fix-login", "zzz-abc-1")),
                                      ("Fix logout", ("zzz-fix-logout", "aaa-abc-2"))):
            with self.subTest(task=task):
                ticket = "ABC-1" if task == "Fix login" else "ABC-2"
                made = {}
                for slug in (first, second):
                    extra = (("--task", task) if "fix" in slug else
                             ("--task", ticket, "--ticket", ticket, "--ask", task))
                    r = self.autodev("init", "--repo", self.repo, "--slug", slug, *extra,
                                     "--profile", self.profile, "--max-wait", "30")
                    self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                    made[slug] = self.tmp / f"app-{slug}"
                before = self.sh("git", "worktree", "list", cwd=self.repo)
                out = self.setup_next(task=task)
                text_run = first if "fix" in first else second
                self.ready(out, made[text_run])
                self.assertNotIn("AGENT", out)
                self.assertEqual(self.sh("git", "worktree", "list", cwd=self.repo), before)
