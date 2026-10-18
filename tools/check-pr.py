#!/usr/bin/env python3
"""Check a branch name and PR title against this repo's conventions (CLAUDE.md).

Usage:
    python3 tools/check-pr.py --branch <name> --title "<PR title>"
    python3 tools/check-pr.py --branch "$(git branch --show-current)"

Either flag may be given alone. Exit 0 when everything given is valid, 1 when
something is not (each problem is printed), 2 on bad arguments.

Branch:  <type>/<short-kebab-description>       e.g. fix/mutate-mtime
         claude/<anything> is also accepted: Claude Code cloud sessions are
         assigned that branch name and cannot choose another.
Title:   <type>: <summary>                      e.g. fix: give each mutant its own mtime
         <type>!: <summary> marks a breaking change (a major version bump).
Types:   feat fix docs refactor test chore ci
"""

import argparse
import re
import sys

TYPES = ("feat", "fix", "docs", "refactor", "test", "chore", "ci")
BRANCH = re.compile(rf"^(?:{'|'.join(TYPES)})/[a-z0-9]+(?:-[a-z0-9]+)*$")
CLAUDE_BRANCH = re.compile(r"^claude/[A-Za-z0-9._-]+$")
TITLE = re.compile(rf"^(?:{'|'.join(TYPES)})!?: \S")
TITLE_MAX = 72


def check_branch(name):
    if BRANCH.match(name) or CLAUDE_BRANCH.match(name):
        return []
    return [(f"branch {name!r} is not <type>/<kebab-description> "
             f"(types: {', '.join(TYPES)}), e.g. fix/mutate-mtime")]


def check_title(title):
    problems = []
    if not TITLE.match(title):
        problems.append(f"title {title!r} does not start with '<type>: ' "
                        f"(types: {', '.join(TYPES)}; '<type>!: ' for a breaking change)")
    if len(title) > TITLE_MAX:
        problems.append(f"title is {len(title)} characters; keep it to {TITLE_MAX}")
    if title.endswith("."):
        problems.append("title ends with a period")
    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--branch")
    parser.add_argument("--title")
    args = parser.parse_args()
    if args.branch is None and args.title is None:
        parser.error("give --branch, --title or both")
    problems = []
    if args.branch is not None:
        problems += check_branch(args.branch)
    if args.title is not None:
        problems += check_title(args.title)
    for p in problems:
        print(f"FAIL {p}")
    if problems:
        return 1
    print("OK: follows the branch and PR title conventions.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
