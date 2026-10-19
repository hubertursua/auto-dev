#!/usr/bin/env python3
"""auto-dev's one entry point: autodev.py <subcommand> [options].

Every mechanical step of the pipeline is a subcommand, so a user allows one
command (`python3 <skill-dir>/scripts/autodev.py *`) instead of many. Only these
subcommands write `.auto-dev/state.json`; `WORK_LOG.md` is generated from it.

Usage:
    python3 <skill-dir>/scripts/autodev.py <subcommand> --help

Subcommands:
    init      Phase 1: preflight, config, worktree, seeded files, setup, state
    resume    find the run to continue: FRESH, RESUME, ASK, FINISHED, OLD-VERSION
    show      print the run's state
    phase     set a phase's status
    note      record a decision or assumption
    size      record the Define agent's size check (FITS or OVERSIZED)
    budget    show the iteration budget, or spend one round before a correction
    gate      record a gate decision
    handoff   write HANDOFF.md and print the message that ends the session
    commit    stage by name, check, commit, and verify the commit (Phase 6)
    ci-watch  poll the PR's checks, bounded; green, red, pending or unavailable
    merge-staging   merge the branch into staging directly, never forced
    merge-pr  merge the PR locked to the checked commit, never --admin
    pr-body   --check: lint a PR description before it is published
    cleanup-worktree   remove the worktree after the final report

Every subcommand takes --json. Exit codes, the same for all:
    0  success
    1  failed, or stop and report: the reason is printed
    2  could not run (bad arguments, missing state) — never a pass
    3+ as the subcommand's --help says
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import cmd_handoff, cmd_init, cmd_resume, cmd_ship, cmd_state
from lib.output import CANNOT_RUN, Fail, report_failure
from lib.proc import CommandError
from lib.state import StateError

COMMANDS = {
    "init": (cmd_init, cmd_init.main),
    "resume": (cmd_resume, cmd_resume.main),
    "show": (cmd_state, cmd_state.show),
    "phase": (cmd_state, cmd_state.phase),
    "note": (cmd_state, cmd_state.note),
    "size": (cmd_state, cmd_state.size),
    "budget": (cmd_state, cmd_state.budget),
    "gate": (cmd_state, cmd_state.gate),
    "handoff": (cmd_handoff, cmd_handoff.main),
    "commit": (cmd_ship, cmd_ship.commit),
    "ci-watch": (cmd_ship, cmd_ship.ci_watch),
    "merge-staging": (cmd_ship, cmd_ship.merge_staging),
    "merge-pr": (cmd_ship, cmd_ship.merge_pr),
    "pr-body": (cmd_ship, cmd_ship.pr_body),
    "cleanup-worktree": (cmd_ship, cmd_ship.cleanup_worktree),
}
# Modules whose add_arguments() also takes the subcommand's name.
NAMED = (cmd_state, cmd_ship)


class Parser(argparse.ArgumentParser):
    """argparse, but a usage error exits 2 with an `ERROR:` line."""

    def error(self, message):
        self.print_usage(sys.stderr)
        print(f"ERROR: {message}", file=sys.stderr)
        sys.exit(CANNOT_RUN)


def build_parser():
    parser = Parser(prog="autodev.py", description=__doc__,
                    formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", parser_class=Parser)
    for name, (module, _) in COMMANDS.items():
        doc = module.__doc__
        child = sub.add_parser(name, description=doc, help=doc.splitlines()[0],
                               formatter_class=argparse.RawDescriptionHelpFormatter)
        if module in NAMED:
            module.add_arguments(child, name)
        else:
            module.add_arguments(child)
        child.add_argument("--json", action="store_true", help="print JSON")
    # The detached setup runner init starts; not for direct use.
    runner = sub.add_parser("_run-setup")
    runner.add_argument("artifact_dir")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return CANNOT_RUN
    if args.command == "_run-setup":
        return cmd_init.run_setup(args.artifact_dir)
    _, handler = COMMANDS[args.command]
    try:
        return handler(args)
    except Fail as exc:
        return report_failure(exc, args.json)
    except StateError as exc:
        return report_failure(Fail(str(exc), CANNOT_RUN, "ERROR"), args.json)
    except CommandError as exc:
        return report_failure(Fail(str(exc), CANNOT_RUN, "ERROR"), args.json)


if __name__ == "__main__":
    sys.exit(main())
