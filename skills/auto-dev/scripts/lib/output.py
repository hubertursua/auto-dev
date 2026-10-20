"""Exit codes and printing shared by every subcommand.

Every subcommand exits 0 on success, 1 when it failed and printed why, and 2
when it could not run (never a pass). Codes 3 and up mean what each
subcommand's help says. `next` (and every command that prints an action) uses
the action lines below, so the orchestrator reads one shape everywhere.
"""

import json
import sys

OK, FAILED, CANNOT_RUN = 0, 1, 2

# `next`'s exit codes, fixed now so later subcommands print in the same shape.
NEXT_ACTION, NEXT_COMPLETE, NEXT_STOP, NEXT_ASK, NEXT_BOUNDARY = 0, 3, 4, 5, 6

# The lines an action is printed as, in this order; empty ones are left out.
ACTION_KEYS = ("ACTION", "AGENT", "BRIEF", "BUDGET", "AFTER")


class Fail(Exception):
    """Stop the subcommand: print `message` and exit with `code`."""

    def __init__(self, message, code=FAILED, token="STOP"):
        super().__init__(message)
        self.code, self.token = code, token


def emit(as_json, token, message="", **fields):
    """Print a result: `TOKEN: message` plus `key: value` lines, or JSON."""
    if as_json:
        print(json.dumps({"result": token, "message": message, **fields},
                         indent=2, sort_keys=True))
        return
    print(f"{token}: {message}" if message else token)
    for key, value in fields.items():
        if value is None or value == "" or value == []:
            continue
        if isinstance(value, (list, tuple)):
            for item in value:
                print(f"  {key}: {item}")
        else:
            print(f"  {key}: {value}")


def action_lines(action):
    """Format an action dict as the ACTION / AGENT / BRIEF / BUDGET / AFTER lines."""
    return "\n".join(f"{key}: {action[key]}" for key in ACTION_KEYS
                     if action.get(key))


def report_failure(exc, as_json):
    stream = sys.stdout if as_json else sys.stderr
    if as_json:
        print(json.dumps({"result": exc.token, "message": str(exc)}, indent=2),
              file=stream)
    else:
        print(f"{exc.token}: {exc}", file=stream)
    return exc.code
