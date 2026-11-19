#!/usr/bin/env python3
"""Test-only entry to library steps that `next` runs in-process, with no
subcommand of their own: the PR body's generate and lint, and a gate's
summary. The tests run it as a subprocess, as they run autodev.py, so a test's
PATH (a stub git, the fake gh) applies.

Usage:
    lib_cli.py pr-body [--check FILE] --dir <artifact-dir> [--json]
    lib_cli.py gate-summary <post-plan|pr|ready|main> --dir <artifact-dir> [--json]
    lib_cli.py metrics --dir <artifact-dir> [--json]

Prints and exits as autodev.py would: `WRITTEN`, `CLEAN` or `PROBLEMS` (exit
1) for pr-body; the summary and the question for gate-summary, exit 1 when a
precondition fails; `WRITTEN <metrics.json>` and `COPIED <its copy>` for
metrics (what `next` writes at exits 3 and 4); exit 2 when it could not run.
"""

import argparse
import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "skills" / "auto-dev" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from lib import artifacts as art  # noqa: E402
from lib import cmd_review, cmd_ship, metrics  # noqa: E402
from lib import state as st  # noqa: E402
from lib.output import CANNOT_RUN, FAILED, Fail, emit, report_failure  # noqa: E402


def pr_body(args):
    state = st.load(args.dir)
    if not args.check:
        from lib.cmd_pr import generate
        sha = state.get("phase6", {}).get("verified_sha")
        if not sha:
            raise Fail("no verified commit yet: commit first", FAILED, "NO-COMMIT")
        ad = Path(state["artifact_dir"])
        path = generate(state, ad, sha, reviewed=bool(state["phase6"].get("passes"))
                        or (ad / "CODE_REVIEW.md").exists())
        state["phase6"]["body"] = {"sha": sha, "path": str(path), "seq": st.seq(state)}
        st.save(args.dir, state)
        emit(args.json, "WRITTEN", str(path), commit=sha,
             then="replace the WRITE lines in pr-write.md beside it, then "
                  "`autodev.py pr publish`")
        return 0
    text = Path(args.check).read_text(encoding="utf-8")
    problems = cmd_ship.lint_body(text, state)
    if problems:
        emit(args.json, "PROBLEMS", f"{len(problems)} problem(s) in {args.check}",
             problem=problems)
        return FAILED
    emit(args.json, "CLEAN", f"{args.check}: {len(text)} characters")
    return 0


def gate_summary(args):
    state = st.load(args.dir)
    builder = {"post-plan": cmd_review.post_plan_summary,
               "pr": cmd_review.open_pr_summary, "ready": cmd_review.ready_summary,
               "main": cmd_review.main_summary}[args.gate]
    try:
        lines, extra = builder(state, Path(args.dir), args)
    except art.ArtifactError as exc:
        raise Fail(str(exc), FAILED, "MALFORMED") from None
    questions = [cmd_review.question("Gate", f"{args.gate} gate: how do you want to proceed?",
                                     cmd_review.GATE_OPTIONS[args.gate])] + extra
    if args.json:
        print(json.dumps({"result": "SUMMARY", "summary": lines, "questions": questions},
                         indent=2))
    else:
        print("SUMMARY:")
        print("\n".join(f"  {ln}" for ln in lines))
        print("QUESTION:")
        print(json.dumps({"questions": questions}))
    return 0


def write_metrics(args):
    errors = metrics.write(args.dir)
    if errors:
        raise Fail("; ".join(errors), CANNOT_RUN, "ERROR")
    emit(args.json, "WRITTEN", str(Path(args.dir) / metrics.FILE),
         copied=str(metrics.saved_path(st.load(args.dir))))
    return 0


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    body = sub.add_parser("pr-body")
    body.add_argument("--check")
    gate = sub.add_parser("gate-summary")
    gate.add_argument("gate", choices=sorted(cmd_review.GATE_OPTIONS))
    gate.add_argument("--pr")
    metrics_ = sub.add_parser("metrics")
    for p in (body, gate, metrics_):
        p.add_argument("--dir", required=True)
        p.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        return {"pr-body": pr_body, "gate-summary": gate_summary,
                "metrics": write_metrics}[args.command](args)
    except Fail as exc:
        return report_failure(exc, args.json)
    except st.StateError as exc:
        return report_failure(Fail(str(exc), CANNOT_RUN, "ERROR"), args.json)


if __name__ == "__main__":
    sys.exit(main())
