#!/usr/bin/env python3
"""Validate a repo-local .auto-dev.yml against the schema in references/profiles.md.

An unrecognized key in .auto-dev.yml is silently ignored by the pipeline, so a typo
reads as "the override did nothing" rather than as an error. This script names the
key and suggests the one it probably meant.

Usage:
    python3 validate-config.py [path/to/.auto-dev.yml]

Defaults to ./.auto-dev.yml. Exit codes:
    0  valid (warnings may still be printed)
    1  invalid — errors printed; Phase 1 should stop and report
    2  could not validate (PyYAML missing, file unreadable) — NOT a pass
"""

import difflib
import sys

CI_PROVIDERS = {"github-actions", "circleci", "gitlab", "none"}
GATE_KINDS = {"compile", "format", "lint", "typecheck", "test", "build"}
JIRA_STATES = {"in_progress", "in_review", "done"}

# key -> (type, human description). `type` is checked with isinstance.
TOP_LEVEL = {
    "stack": (str, "profile id to force instead of auto-detecting"),
    "setup": (list, "ordered install/activation commands"),
    "gate": (list, "ordered quality-gate checks"),
    "test_notes": (str, "how tests are scoped"),
    "worktree_files": (list, "gitignored files to seed each worktree with"),
    "branches": (dict, "base / staging / prefix"),
    "ci": (str, "CI provider"),
    "ci_timeout_minutes": (int, "bound on CI watching"),
    "iteration_budget": (int, "revise rounds per task"),
    "security_docs": (list, "paths to the security directives"),
    "pr_review": (dict, "inline_comments"),
    "gates": (dict, "post_plan"),
    "jira": (dict, "states"),
}
BRANCHES = {"base": str, "staging": str, "prefix": str}
PR_REVIEW = {"inline_comments": bool}
GATES = {"post_plan": bool}

errors: list[str] = []
warnings: list[str] = []


def unknown_key(key, known, where):
    near = difflib.get_close_matches(str(key), sorted(known), n=1, cutoff=0.6)
    hint = f" — did you mean `{near[0]}`?" if near else ""
    errors.append(f"{where}: unknown key `{key}`{hint}")


def check_type(value, expected, where):
    # bool is a subclass of int; keep them distinct.
    if expected is int and isinstance(value, bool):
        errors.append(f"{where}: expected an integer, got a boolean")
        return False
    if not isinstance(value, expected):
        got = type(value).__name__
        errors.append(f"{where}: expected {expected.__name__}, got {got}")
        return False
    return True


def check_str_list(value, where):
    if not check_type(value, list, where):
        return
    for i, item in enumerate(value):
        check_type(item, str, f"{where}[{i}]")


def check_mapping(value, schema, where):
    if not check_type(value, dict, where):
        return
    for key, val in value.items():
        if key not in schema:
            unknown_key(key, schema, where)
            continue
        check_type(val, schema[key], f"{where}.{key}")


def check_gate(gate):
    if not check_type(gate, list, "gate"):
        return
    if not gate:
        errors.append("gate: is an empty list — an empty gate makes Phase 5 pass by "
                      "having nothing to check. Omit the key to keep the profile's "
                      "gate, or list real checks.")
        return
    kinds = set()
    for i, check in enumerate(gate):
        where = f"gate[{i}]"
        if not check_type(check, dict, where):
            continue
        for required in ("kind", "command", "report"):
            if required not in check:
                errors.append(f"{where}: missing `{required}`")
        for key in check:
            if key not in {"kind", "command", "report"}:
                unknown_key(key, {"kind", "command", "report"}, where)
        kind = check.get("kind")
        if isinstance(kind, str):
            kinds.add(kind)
            if kind not in GATE_KINDS:
                warnings.append(
                    f"{where}: kind `{kind}` is not one of "
                    f"{', '.join(sorted(GATE_KINDS))} (kind is advisory, so this "
                    f"still runs)")
        report = check.get("report")
        if isinstance(report, str) and not report.endswith(".md"):
            warnings.append(f"{where}: report `{report}` should be a .md filename")
    if "test" not in kinds:
        errors.append(
            "gate: no check with `kind: test`. This override replaces the resolved "
            "gate, so Phase 5 would run no tests and pass by default. Add the test "
            "check back.")


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else ".auto-dev.yml"

    try:
        import yaml
    except ImportError:
        print("SKIPPED: PyYAML is not installed, so .auto-dev.yml cannot be "
              "validated.\n  This is not a pass — install it (`pip install pyyaml`) "
              "or review the file by hand\n  against references/profiles.md.",
              file=sys.stderr)
        return 2

    try:
        with open(path) as f:
            config = yaml.safe_load(f)
    except FileNotFoundError:
        print(f"No {path} — nothing to validate (the pipeline runs without one).")
        return 0
    except yaml.YAMLError as exc:
        print(f"INVALID: {path} is not valid YAML.\n  {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"SKIPPED: could not read {path}: {exc}", file=sys.stderr)
        return 2

    if config is None:
        print(f"{path} is empty — nothing to override.")
        return 0
    if not isinstance(config, dict):
        print(f"INVALID: {path} must be a mapping of keys at the top level, "
              f"got {type(config).__name__}.", file=sys.stderr)
        return 1

    for key, value in config.items():
        if key not in TOP_LEVEL:
            unknown_key(key, TOP_LEVEL, "top level")
            continue
        expected, _ = TOP_LEVEL[key]
        if key == "gate":
            check_gate(value)
        elif key in ("setup", "security_docs", "worktree_files"):
            check_str_list(value, key)
        elif key == "branches":
            check_mapping(value, BRANCHES, "branches")
        elif key == "pr_review":
            check_mapping(value, PR_REVIEW, "pr_review")
        elif key == "gates":
            check_mapping(value, GATES, "gates")
        elif key == "jira":
            if check_type(value, dict, "jira"):
                for jkey, jval in value.items():
                    if jkey != "states":
                        unknown_key(jkey, {"states"}, "jira")
                    elif check_type(jval, dict, "jira.states"):
                        for state, name in jval.items():
                            if state not in JIRA_STATES:
                                unknown_key(state, JIRA_STATES, "jira.states")
                            else:
                                check_type(name, str, f"jira.states.{state}")
        elif check_type(value, expected, key):
            if key == "ci" and value not in CI_PROVIDERS:
                errors.append(
                    f"ci: `{value}` is not one of {', '.join(sorted(CI_PROVIDERS))}")
            if key in ("iteration_budget", "ci_timeout_minutes") and value < 1:
                errors.append(f"{key}: must be at least 1, got {value}")

    for warning in warnings:
        print(f"warning  {warning}")
    for error in errors:
        print(f"ERROR    {error}", file=sys.stderr)

    if errors:
        print(f"\nINVALID: {path} has {len(errors)} error(s). "
              f"Schema: skills/auto-dev/references/profiles.md", file=sys.stderr)
        return 1

    keys = ", ".join(sorted(config)) or "nothing"
    print(f"VALID: {path} overrides {keys}."
          + (f" {len(warnings)} warning(s)." if warnings else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
