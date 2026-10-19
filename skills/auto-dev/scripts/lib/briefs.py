"""Briefs and results: what a worker is told, and what it must say back.

A worker's fixed instructions live in agents/<worker>.md, which is its system
prompt. Each `{{slot}}` there is filled by `autodev.py brief`, which writes the
values to briefs/<worker>-<n>.md; the Agent call's prompt only names that file.
Slots inside a `## Mode: <name>` section are needed only in that mode.

Every slot is one of:
  AUTO      filled from state.json and the run's artifacts;
  CALLER    passed with `--set name=value`; the brief refuses without it;
  OPTIONAL  passed with `--set` when it applies; `none` otherwise.

Each worker ends its reply with an `auto-dev-result` block and writes the same
keys to returns/<worker>-<n>.json. RESULTS lists the `next` tokens each may
return; `autodev.py record` checks the return against the artifacts.
"""

import re
from pathlib import Path

AGENTS_DIR = Path(__file__).resolve().parents[4] / "agents"
SLOT_RE = re.compile(r"\{\{([a-z_]+)\}\}")
MODE_RE = re.compile(r"^## Mode: ([a-z-]+)\s*$", re.MULTILINE)

AUTO = {"worktree", "artifact_dir", "skill_dir", "base", "branch", "task", "ticket",
        "binding_rules", "test_command", "test_notes", "mutation_cap",
        "gate_commands", "acceptance_paths", "survivors", "result_file",
        "symbol_lookup", "pass", "tree", "run", "pr", "triage_file", "answer_file"}
CALLER = {"repo", "draft_path", "scope", "mode", "reviewer", "findings", "reviewers",
          "report", "blocked", "failing", "question", "corrections_file", "leads"}
OPTIONAL = {"fix_file", "ambiguous", "direction", "files", "since", "what_changed"}
# fix_file is AUTO for the reviewers, who write it; OPTIONAL for the authors.
AUTO_FOR = {"fix_file": {"define-reviewer", "plan-reviewer"}}

RESULTS = {
    "profiler": {"CONFIRM"},
    "define": {"FITS", "OVERSIZED", "REVISED"},
    "define-reviewer": {"CLEAN", "BLOCKERS"},
    "planner": {"WRITTEN", "REVISED", "PLAN_REVISED", "UPDATE_OLD_TEST", "SPEC_IMPOSSIBLE"},
    "plan-reviewer": {"CLEAN", "BLOCKERS"},
    "acceptance-tester": {"SEALED", "REPAIRED", "STANDS"},
    "coder": {"BUILT", "BLOCKED"},
    "verifier": {"ALL_MET", "CORRECT", "REPAIR", "INSTALL_CONFLICT",
                 "MUTATION_LEFT_CHANGES"},
    "cleanup": {"GREEN", "RED", "ACCEPTANCE_CHECK_FAILS_GATE"},
    "code-reviewer": {"REVIEWED", "VOTED"},
    "review-judge": {"CLEAN", "MUST_FIX", "REVOTE", "VERIFIED"},
    "security-reviewer": {"CLEAN", "MUST_FIX"},
    "security-reviewer-sensitive": {"CLEAN", "MUST_FIX"},
    "triager": {"CODE", "INFRA", "FLAKY", "SECRET", "UNKNOWN", "TRIAGED"},
    "lookup": {"ANSWERED", "OUT_OF_SCOPE"},
}
STATUSES = {"ok", "blocked", "failed"}


class BriefError(Exception):
    """A brief can't be written; the message says what is missing."""


def agent_text(worker):
    path = AGENTS_DIR / f"{worker}.md"
    if not path.exists():
        raise BriefError(f"no agent file {path}: unknown worker {worker!r}")
    return path.read_text(encoding="utf-8")


def modes(worker):
    return MODE_RE.findall(agent_text(worker))


def slots(worker, mode=None):
    """The slots the worker's agent file uses in `mode` (outside any mode
    section, plus inside that mode's section)."""
    text = agent_text(worker)
    pieces = MODE_RE.split(text)
    # pieces: [before, mode1, body1, mode2, body2, ...]; a body runs to the next
    # mode heading, so the text after the last mode (Result, Scopes) is shared.
    shared = [pieces[0]]
    per_mode = {}
    for i in range(1, len(pieces), 2):
        body = pieces[i + 1]
        tail = re.split(r"^## (?!Mode: )", body, maxsplit=1, flags=re.MULTILINE)
        per_mode[pieces[i]] = tail[0]
        if len(tail) > 1:
            shared.append(tail[1])
    found = set(SLOT_RE.findall("\n".join(shared)))
    if mode:
        found |= set(SLOT_RE.findall(per_mode.get(mode, "")))
    return found


def kind(worker, slot):
    if slot in AUTO_FOR and worker in AUTO_FOR[slot]:
        return "auto"
    if slot in AUTO:
        return "auto"
    if slot in CALLER:
        return "caller"
    if slot in OPTIONAL:
        return "optional"
    return None


def render(worker, n, mode, values):
    lines = [f"# Brief — {worker} #{n}", f"mode: {mode or 'none'}"]
    for name in sorted(values):
        value = str(values[name]).rstrip()
        first, *rest = value.split("\n") if value else ["none"]
        lines.append(f"{name}: {first}")
        lines += [f"  {line}" for line in rest]
    return "\n".join(lines) + "\n"
