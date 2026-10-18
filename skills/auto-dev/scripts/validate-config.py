#!/usr/bin/env python3
"""Validate a repo-local .auto-dev.yml, or a saved profile, against references/profiles.md.

An unrecognized key in .auto-dev.yml is silently ignored by the pipeline, so a typo
reads as "the override did nothing" rather than as an error. This script names the
key and suggests the one it probably meant.

Usage:
    python3 <skill-dir>/scripts/validate-config.py [path/to/.auto-dev.yml]
    python3 <skill-dir>/scripts/validate-config.py --profile <saved-profile.yml>
    python3 <skill-dir>/scripts/validate-config.py --help

--profile checks a saved profile (the file scripts/profile-path.py names)
instead: only the profile keys are allowed (stack, setup, gate, test_notes,
worktree_files, symbol_lookup, ci), and `setup` and `gate` are required. A
missing or empty saved profile is invalid (exit 1), not a pass.

<skill-dir> is the auto-dev skill's own directory, not the target repo. The config
path defaults to ./.auto-dev.yml relative to the current directory, so pass the
target repo's file as an absolute path.

Output:
    stdout  `VALID: <path> overrides <keys>.` (`VALID: <path> is a profile with
            <keys>.` with --profile), `warning  <msg>` lines, or a note
            that the file is missing/empty
    stderr  `ERROR    <msg>` lines then `INVALID: ...`, or `SKIPPED: ...`

Exit codes:
    0  valid, or no file / empty file (warnings may still be printed); with
       --profile, a missing or empty file is exit 1
    1  invalid — errors printed; Phase 1 should stop and report
    2  could not validate (PyYAML missing, file unreadable) — NOT a pass
"""

import difflib
import sys
from pathlib import Path

# The schema doc, located from this script so the path is right from any cwd.
SCHEMA = Path(__file__).resolve().parent.parent / "references" / "profiles.md"

# Allowed values mirror references/profiles.md — keep the two in sync.
# CI providers Phase 6 knows how to watch (references/gates-and-jira.md).
CI_PROVIDERS = {"github-actions", "circleci", "gitlab", "none"}
# The advisory `kind` labels the profile schema lists; an unknown one only warns.
GATE_KINDS = {"compile", "format", "lint", "typecheck", "test", "build"}
# The pipeline milestones that trigger a Jira transition.
JIRA_STATES = {"in_progress", "in_review", "done"}
# Every key a gate check may carry; anything else is flagged as unknown.
GATE_FIELDS = {"kind", "command", "report"}
# The subset of GATE_FIELDS each check must set. Kept separate so a new
# optional field can join GATE_FIELDS without becoming required.
GATE_REQUIRED = ("kind", "command", "report")
assert set(GATE_REQUIRED) <= GATE_FIELDS, "GATE_REQUIRED must be a subset of GATE_FIELDS"

# difflib's own default: close enough to catch a dropped/swapped letter
# (`iteration_budgt`, `bse`) without suggesting an unrelated key.
SUGGEST_CUTOFF = 0.6
# 0 revise rounds or 0 minutes of CI watching would make that step a no-op.
MIN_POSITIVE = 1

# Plain-language names for the schema's types, used in error messages.
TYPE_NAMES = {str: "a string", list: "a list", dict: "a mapping",
              int: "an integer", bool: "true or false"}

# key -> (type, human description). `type` is checked with isinstance.
TOP_LEVEL = {
    "stack": (str, "the stack's name, recorded in profile.md"),
    "setup": (list, "ordered install/activation commands"),
    "gate": (list, "ordered quality-gate checks"),
    "test_notes": (str, "how tests are scoped"),
    "symbol_lookup": (dict, "definition / references commands"),
    "worktree_files": (list, "gitignored files to seed each worktree with"),
    "branches": (dict, "base / staging / prefix"),
    "ci": (str, "CI provider"),
    "ci_timeout_minutes": (int, "bound on CI watching"),
    "iteration_budget": (int, "revise rounds per task"),
    "security_docs": (list, "paths to the security directives"),
    "pr_review": (dict, "inline_comments"),
    "gates": (dict, "post_plan"),
    "mutation": (dict, "max"),
    "jira": (dict, "states"),
}
# The keys a saved profile may hold (--profile): how the stack installs and
# checks itself. Repo policy (branches, budget, gates, Jira) stays in .auto-dev.yml.
PROFILE_KEYS = ("stack", "setup", "gate", "test_notes", "worktree_files",
                "symbol_lookup", "ci")
PROFILE_REQUIRED = ("setup", "gate")
assert set(PROFILE_KEYS) <= set(TOP_LEVEL), "PROFILE_KEYS must be TOP_LEVEL keys"
BRANCHES = {"base": str, "staging": str, "prefix": str}
PR_REVIEW = {"inline_comments": bool}
GATES = {"post_plan": bool}
MUTATION = {"max": int}
MUTATION_MAX = 50
# Each symbol-lookup command is run with <symbol> replaced by the name sought.
SYMBOL_LOOKUP = {"definition": str, "references": str}
SYMBOL_PLACEHOLDER = "<symbol>"

errors: list[str] = []
warnings: list[str] = []


def unknown_key(key, known, where):
    near = difflib.get_close_matches(str(key), sorted(known), n=1,
                                     cutoff=SUGGEST_CUTOFF)
    hint = f" — did you mean `{near[0]}`?" if near else ""
    errors.append(f"{where}: unknown key `{key}`{hint}")


def check_type(value, expected, where):
    # bool is a subclass of int; keep them distinct.
    if expected is int and isinstance(value, bool):
        errors.append(f"{where}: expected an integer, got a boolean")
        return False
    if not isinstance(value, expected):
        want = TYPE_NAMES.get(expected, expected.__name__)
        got = TYPE_NAMES.get(type(value), type(value).__name__)
        errors.append(f"{where}: expected {want}, got {got} ({value!r})")
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


def check_gate(gate, profile=False):
    what = ("A saved profile's gate is the whole gate" if profile
            else "This override replaces the resolved gate")
    if not check_type(gate, list, "gate"):
        return
    if not gate:
        errors.append("gate: is an empty list — an empty gate makes Phase 5 pass by "
                      "having nothing to check. List real checks"
                      + ("." if profile
                         else ", or omit the key to keep the profile's gate."))
        return
    kinds = set()
    for i, check in enumerate(gate):
        where = f"gate[{i}]"
        if not check_type(check, dict, where):
            continue
        for required in GATE_REQUIRED:
            if required not in check:
                errors.append(f"{where}: missing `{required}`")
        for key, val in check.items():
            if key not in GATE_FIELDS:
                unknown_key(key, GATE_FIELDS, where)
            else:
                check_type(val, str, f"{where}.{key}")
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
            f"gate: no check with `kind: test`. {what}, so Phase 5 would run no "
            "tests and pass by default. Add the test check back.")


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help"):
        # Without this, `--help` is taken as a missing config path and exits 0.
        print(__doc__)
        return 0
    args = sys.argv[1:]
    profile = bool(args) and args[0] == "--profile"
    if profile:
        args = args[1:]
        if not args:
            print("SKIPPED: --profile needs the saved profile's path.", file=sys.stderr)
            return 2
    path = args[0] if args else ".auto-dev.yml"

    try:
        import yaml
    except ImportError:
        print("SKIPPED: PyYAML is required to validate .auto-dev.yml and is not "
              "installed.\n  Exit 2 is not a pass. The user can install it with "
              "`pip install pyyaml`;\n  until then, review the file by hand "
              f"against {SCHEMA}.",
              file=sys.stderr)
        return 2

    try:
        # Binary mode: PyYAML then decodes UTF-8 itself (or UTF-16 when the file
        # starts with a BOM) instead of the locale's encoding, and reports a bad
        # byte at its offset in the whole file.
        with open(path, "rb") as f:
            config = yaml.safe_load(f)
    except FileNotFoundError:
        if profile:
            print(f"INVALID: no saved profile at {path}.", file=sys.stderr)
            return 1
        print(f"No {path} — nothing to validate (the pipeline runs without one).")
        return 0
    except yaml.reader.ReaderError as exc:
        print(f"INVALID: {path} has a byte or character YAML cannot read — "
              f"re-save it as UTF-8 text.\n  {exc}", file=sys.stderr)
        return 1
    except yaml.YAMLError as exc:
        print(f"INVALID: {path} is not valid YAML — fix the syntax at the line "
              f"below.\n  {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"SKIPPED: could not read {path}: {exc}", file=sys.stderr)
        return 2

    if config is None:
        if profile:
            print(f"INVALID: the saved profile {path} is empty.", file=sys.stderr)
            return 1
        print(f"{path} is empty — nothing to override.")
        return 0
    if not isinstance(config, dict):
        print(f"INVALID: {path} must be a mapping of keys at the top level, "
              f"got {type(config).__name__}.", file=sys.stderr)
        return 1

    if (not profile and "stack" in config
            and not all(k in config for k in PROFILE_REQUIRED)):
        warnings.append("stack: names the stack only; it no longer selects a shipped "
                        "profile (removed in 3.6). Set `setup` and `gate` here, or "
                        "let Phase 1 research and confirm the profile.")
    if profile:
        for required in PROFILE_REQUIRED:
            if required not in config:
                errors.append(f"top level: a saved profile must set `{required}`")
    for key, value in config.items():
        if profile and key in TOP_LEVEL and key not in PROFILE_KEYS:
            errors.append(f"top level: `{key}` is repo policy, not a profile key — "
                          f"set it in the repo's .auto-dev.yml instead")
            continue
        if key not in TOP_LEVEL:
            unknown_key(key, PROFILE_KEYS if profile else TOP_LEVEL, "top level")
            continue
        expected, _ = TOP_LEVEL[key]
        if key == "gate":
            check_gate(value, profile)
        elif key in ("setup", "security_docs", "worktree_files"):
            check_str_list(value, key)
        elif key == "branches":
            check_mapping(value, BRANCHES, "branches")
        elif key == "pr_review":
            check_mapping(value, PR_REVIEW, "pr_review")
        elif key == "gates":
            check_mapping(value, GATES, "gates")
        elif key == "mutation":
            check_mapping(value, MUTATION, "mutation")
            cap = value.get("max") if isinstance(value, dict) else None
            if (isinstance(cap, int) and not isinstance(cap, bool)
                    and not 0 <= cap <= MUTATION_MAX):
                errors.append(f"mutation.max: must be 0 (off) to {MUTATION_MAX}, "
                              f"got {cap}")
        elif key == "symbol_lookup":
            check_mapping(value, SYMBOL_LOOKUP, "symbol_lookup")
            for field, cmd in (value.items() if isinstance(value, dict) else ()):
                if (field in SYMBOL_LOOKUP and isinstance(cmd, str)
                        and SYMBOL_PLACEHOLDER not in cmd):
                    errors.append(f"symbol_lookup.{field}: the command must contain "
                                  f"{SYMBOL_PLACEHOLDER}, which is replaced by the "
                                  f"name looked up")
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
            if (key in ("iteration_budget", "ci_timeout_minutes")
                    and value < MIN_POSITIVE):
                errors.append(f"{key}: must be at least {MIN_POSITIVE}, got "
                              f"{value} — 0 would skip the step it bounds")

    for warning in warnings:
        print(f"warning  {warning}")
    for error in errors:
        print(f"ERROR    {error}", file=sys.stderr)

    if errors:
        print(f"\nINVALID: {path} has {len(errors)} error(s). "
              f"Schema: {SCHEMA}", file=sys.stderr)
        return 1

    keys = ", ".join(sorted(config)) or "nothing"
    verb = "is a profile with" if profile else "overrides"
    print(f"VALID: {path} {verb} {keys}."
          + (f" {len(warnings)} warning(s)." if warnings else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
