"""autodev.py init — Phase 1's mechanical steps, in one call.

Usage:
    autodev.py init --repo <main checkout> --slug <slug> --task "<text>"
                    [--ticket KEY] [--ticket-url URL] [--ask "<restated ask>"]
                    [--profile <profile.yml>] [--profile-source "<text>"]
                    [--prefix feat] [--security-doc PATH ...] [--jira "<text>"]
                    [--assumption "<text>" ...] [--max-wait SECONDS] [--json]
    autodev.py init --continue <worktree> [--profile <profile.yml>]
                    [--max-wait SECONDS] [--json]

Does, in order, stopping at the first failure:
 1. Preflight: python3 >= 3.9, PyYAML, git, gh installed and signed in, and an
    `origin` that GitHub knows.
 2. Resolve the config: validate the profile (`--profile`, the saved or
    user-confirmed profile) and `<repo>/.auto-dev.yml` with validate-config.py,
    then apply the override over the profile. Without `--profile`, the override
    must set both `setup` and `gate`. The resolved gate must have a `test`
    check.
 3. Branches: base from the override, else the repo's default branch; staging
    from the override, else `staging` when that branch exists on origin; prefix
    from the override, else `--prefix` (default `feat`).
 4. `git fetch origin`, then `git worktree add ../<repo>-<slug> -b
    <prefix>/<slug> origin/<base>`.
 5. Make `.auto-dev/` self-excluding (exclude-artifacts.py).
 6. Copy each `worktree_files` entry from the main checkout and check git ignores
    it. A listed file that isn't there is reported, not fatal.
 7. Write `.auto-dev/profile.md`, `state.json` and `WORK_LOG.md`.
 8. Run the profile's `setup` commands in the background, in order, logging to
    `.auto-dev/setup.log`, and wait up to `--max-wait` seconds (default 540, under
    the Bash tool's 10-minute limit). Still running: exit 3; call
    `init --continue <worktree>` to keep waiting.

If anything fails after step 4 and before setup starts, the worktree and its
branch are removed again, so the same command can run once the cause is fixed.

A failed setup leaves the run open (Phase 1 `held`). `--continue` resumes a run
whose `init` already got to step 8: it keeps waiting while setup runs, and when
setup failed (or its runner died) it reads `setup` and `gate` again from
`.auto-dev.yml` and `--profile` (when given; otherwise the run's own setup and
gate stand in for the profile), then runs setup again. Re-running the first form
for a slug whose worktree already holds the same task's state.json keeps
waiting the same way.

Output: `INIT: <worktree>` with the branch, base, staging and setup result;
`SETUP-RUNNING: …` (exit 3); or `STOP: <reason>` (exit 1).

Exit codes:
    0  ready: worktree created, state written, setup finished green
    1  stop and report: the reason is printed (gh missing or signed out, origin
       not on GitHub, invalid config, no test command in the gate, a staging
       branch .auto-dev.yml names that origin lacks, worktree path taken, the
       slug used by another task's run, a seeded file not gitignored, a setup
       command missing or failing, the setup runner dying)
    2  could not run (bad arguments, a helper script missing) — not a pass
    3  setup is still running; call `init --continue <worktree>`
"""

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import state as st
from .output import CANNOT_RUN, Fail, emit
from .proc import CommandError, git, run

SCRIPTS = Path(__file__).resolve().parent.parent
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SETUP_LOG, SETUP_RESULT = "setup.log", "setup.json"
DEFAULTS = {"ci_timeout_minutes": 30, "iteration_budget": 4, "mutation_max": 20}
EXIT_SETUP_RUNNING = 3
SETUP_HEADING = "## Setup — run in order, verbatim"
TEST_NOTES = "## Test notes"
STILL_ACTIVE = 259  # GetExitCodeProcess's code for a running process (Windows)
MIN_PYTHON = (3, 9)


def add_arguments(parser):
    parser.add_argument("--repo", default=".", help="the main checkout (default: .)")
    parser.add_argument("--slug", help="kebab-case name for the branch and worktree")
    parser.add_argument("--task", help="the task, one line")
    parser.add_argument("--ticket", help="Jira key, when there is a ticket")
    parser.add_argument("--ticket-url", help="the ticket's link")
    parser.add_argument("--ask", help="the task restated in 1-2 sentences")
    parser.add_argument("--profile", help="the saved or confirmed profile (YAML)")
    parser.add_argument("--profile-source", default="",
                        help="where the profile came from, for profile.md")
    parser.add_argument("--prefix", default="feat", help="branch prefix default")
    parser.add_argument("--security-doc", action="append", default=[],
                        help="a resolved security-directive path (repeatable)")
    parser.add_argument("--jira", default="", help="Jira availability, for profile.md")
    parser.add_argument("--assumption", action="append", default=[],
                        help="an assumption for profile.md (repeatable)")
    parser.add_argument("--max-wait", type=int, default=540,
                        help="seconds to wait for setup (default 540)")
    parser.add_argument("--continue", dest="cont", metavar="WORKTREE",
                        help="keep waiting on setup for this worktree, or run "
                             "it again after it failed")


def main(args):
    if args.cont:
        artifact_dir = Path(args.cont).resolve() / ".auto-dev"
        state = st.load(artifact_dir)
        if state["init"].get("setup") == "failed":
            # The user fixed the cause: read setup and gate again, then rerun.
            refresh_setup(artifact_dir, state, args.profile)
            state["init"]["setup"] = "pending"
            st.set_phase(state, 1, "in-progress", "")
            st.save(artifact_dir, state)
            return wait_for_setup(artifact_dir, state, args,
                                  start_setup(artifact_dir, state))
        return wait_for_setup(artifact_dir, state, args)
    for name in ("slug", "task"):
        if not getattr(args, name):
            raise Fail(f"--{name} is required (or pass --continue <worktree>)",
                       CANNOT_RUN, "ERROR")
    if not SLUG_RE.match(args.slug):
        raise Fail(f"--slug {args.slug!r} must be lowercase words joined by "
                   "single hyphens", CANNOT_RUN, "ERROR")
    repo = repo_root(args.repo)
    name = Path(repo).name
    worktree = Path(repo).parent / f"{name}-{args.slug}"
    if (worktree / ".auto-dev" / st.STATE_FILE).exists():
        artifact_dir = worktree / ".auto-dev"
        state = st.load(artifact_dir)
        if not same_task(state["task"], args):
            raise Fail(f"slug {args.slug} is already used by another run "
                       f"({state['task'].get('text', '')}); pick another slug")
        return wait_for_setup(artifact_dir, state, args)
    if worktree.exists():
        raise Fail(f"{worktree} already exists and holds no 4.x run; pick another "
                   "slug, or remove it")

    preflight(repo)
    config = resolve_config(repo, args.profile)
    default_branch = gh_default_branch(repo)
    branches = config.get("branches", {})
    base = branches.get("base") or default_branch
    prefix = branches.get("prefix") or args.prefix
    git(repo, "fetch", "origin")
    staging = branches.get("staging") or "staging"
    if not remote_branch_exists(repo, staging):
        if branches.get("staging"):
            raise Fail(f".auto-dev.yml names staging branch {staging!r}, which is "
                       "not on origin")
        staging = None
    branch = f"{prefix}/{args.slug}"
    code, _, err = git(repo, "worktree", "add", str(worktree), "-b", branch,
                       f"origin/{base}", check=False)
    if code != 0:
        raise Fail(f"could not create the worktree: {err.strip()}")
    try:
        state = create_run(repo, worktree, branch, config, args, staging=staging,
                           base=base, prefix=prefix)
        runner = start_setup(worktree / ".auto-dev", state)
    except BaseException:
        remove_worktree(repo, worktree, branch)
        raise
    return wait_for_setup(worktree / ".auto-dev", state, args, runner)


def same_task(task, args):
    """Whether --task (and --ticket, when given) name the run `task` holds."""
    if task.get("text", "").strip() != args.task.strip():
        return False
    return not args.ticket or task.get("ticket") == args.ticket


def remove_worktree(repo, worktree, branch):
    """Undo `git worktree add` after a later step failed (best effort)."""
    git(repo, "worktree", "remove", "--force", str(worktree), check=False)
    if worktree.exists():
        shutil.rmtree(worktree, ignore_errors=True)
        git(repo, "worktree", "prune", check=False)
    git(repo, "branch", "-D", branch, check=False)


def create_run(repo, worktree, branch, config, args, staging, base, prefix):
    """Steps 5-7: exclude .auto-dev/, seed files, write profile.md and state."""
    name = Path(repo).name
    artifact_dir = worktree / ".auto-dev"
    code, out, err = run([sys.executable, str(SCRIPTS / "exclude-artifacts.py"),
                          str(worktree)], check=False)
    if code != 0:
        raise Fail(f"exclude-artifacts.py exited {code}: {(err or out).strip()}",
                   CANNOT_RUN if code == 2 else 1)
    seeded, missing = seed_files(repo, worktree, config.get("worktree_files", []))

    settings = {
        "stack": config.get("stack", ""),
        "ci": config.get("ci") or detect_ci(worktree),
        "ci_timeout": config.get("ci_timeout_minutes", DEFAULTS["ci_timeout_minutes"]),
        "mutation_max": config.get("mutation", {}).get("max", DEFAULTS["mutation_max"]),
        "post_plan_gate": bool(config.get("gates", {}).get("post_plan", False)),
        "inline_comments": bool(config.get("pr_review", {}).get("inline_comments",
                                                                False)),
        "jira_states": config.get("jira", {}).get("states", {}),
        "setup": config.get("setup", []),
        "gate": config.get("gate", []),
    }
    task = {"text": args.task, "ticket": args.ticket or "none",
            "ticket_url": args.ticket_url or "", "ask": args.ask or args.task}
    repo_info = {"name": name, "main_checkout": repo, "base": base,
                 "staging": staging, "prefix": prefix}
    state = st.new_state(task, repo_info, worktree, branch, settings,
                         config.get("iteration_budget", DEFAULTS["iteration_budget"]))
    st.set_phase(state, 1, "in-progress")
    if not staging:
        state["phases"]["6"]["notes"] = "staging gate: n/a (no staging branch)"
    if missing:
        st.add_note(state, "worktree_files not found in the main checkout: "
                    + ", ".join(missing))
    (artifact_dir / "profile.md").write_text(
        render_profile(state, config, args, seeded, missing), encoding="utf-8")
    st.save(artifact_dir, state)
    return state


def repo_root(path):
    try:
        return git(str(Path(path).resolve()), "rev-parse", "--show-toplevel").strip()
    except CommandError as exc:
        raise Fail(f"{path} is not a git checkout: {exc}", CANNOT_RUN, "ERROR") from None


def preflight(repo):
    if sys.version_info[:2] < MIN_PYTHON:
        raise Fail("python3 3.9 or newer is required")
    try:
        import yaml  # noqa: F401
    except ImportError:
        raise Fail("PyYAML is not installed for this python3; install it (for "
                   "example `python3 -m pip install pyyaml`) and run again") from None
    if not shutil.which("gh"):
        raise Fail("gh is not installed; Phase 6 needs it to open and merge the PR")
    code, _, err = run(["gh", "auth", "status"], cwd=repo, check=False)
    if code != 0:
        raise Fail(f"gh is not signed in (`gh auth login`): {err.strip()[-300:]}")
    code, _, err = run(["gh", "repo", "view", "--json", "nameWithOwner"], cwd=repo,
                       check=False)
    if code != 0:
        raise Fail(f"origin is not a GitHub repo gh can see: {err.strip()[-300:]}")


def gh_default_branch(repo):
    _, out, _ = run(["gh", "repo", "view", "--json", "defaultBranchRef"], cwd=repo)
    try:
        return json.loads(out)["defaultBranchRef"]["name"]
    except (ValueError, KeyError, TypeError):
        raise Fail(f"gh did not return a default branch: {out[:200]}",
                   CANNOT_RUN, "ERROR") from None


def remote_branch_exists(repo, branch):
    """Whether origin has exactly `branch` (ls-remote's pattern also matches
    `release/<branch>`, so compare the full ref)."""
    code, out, _ = git(repo, "ls-remote", "--heads", "origin", branch, check=False)
    want = f"refs/heads/{branch}"
    return code == 0 and any(line.split("\t")[-1].strip() == want
                             for line in out.splitlines())


def validate(path, profile):
    cmd = [sys.executable, str(SCRIPTS / "validate-config.py")]
    cmd += ["--profile", str(path)] if profile else [str(path)]
    code, out, err = run(cmd, check=False)
    if code == 1:
        raise Fail(f"{path} is invalid:\n{(err or out).strip()}")
    if code != 0:
        raise Fail(f"validate-config.py could not check {path} (exit {code}): "
                   f"{(err or out).strip()}", CANNOT_RUN, "ERROR")


def load_yaml(path):
    import yaml
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def resolve_config(repo, profile_path, fallback=None):
    """The profile (or `fallback`, a run's own setup and gate) under the
    override, key by key."""
    override_path = Path(repo) / ".auto-dev.yml"
    override = {}
    if override_path.exists():
        validate(override_path, profile=False)
        override = load_yaml(override_path)
    config = {}
    if profile_path:
        validate(Path(profile_path), profile=True)
        config.update(load_yaml(profile_path))
    elif fallback is not None:
        config.update(fallback)
    elif not (override.get("setup") and override.get("gate")):
        raise Fail("no profile: pass --profile <file> (the saved or confirmed "
                   "profile), or commit a .auto-dev.yml that sets setup and gate",
                   CANNOT_RUN, "ERROR")
    config.update(override)  # the override wins, key by key
    if not any(check.get("kind") == "test" for check in config.get("gate", [])):
        raise Fail("the resolved quality gate has no test command; an empty gate "
                   "would pass by checking nothing")
    return config


def detect_ci(worktree):
    if (worktree / ".github" / "workflows").is_dir():
        return "github-actions"
    if (worktree / ".circleci" / "config.yml").exists():
        return "circleci"
    if (worktree / ".gitlab-ci.yml").exists():
        return "gitlab"
    return "none"


def seed_files(repo, worktree, files):
    seeded, missing = [], []
    for rel in files:
        source, target = Path(repo) / rel, worktree / rel
        if not source.is_file():
            missing.append(rel)
            continue
        # Check before copying, so a tracked file is never overwritten.
        code, _, _ = git(str(worktree), "check-ignore", "-q", "--", rel, check=False)
        if code != 0:
            raise Fail(f"worktree file {rel} is not gitignored; it would show in "
                       "the PR and could leak a secret. Ignore it, or drop it from "
                       "worktree_files")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        seeded.append(rel)
    return seeded, missing


def symbol_lookup(config):
    lookup = config.get("symbol_lookup") or {}
    definition = lookup.get("definition", "")
    if not definition:
        return "`grep -n` — none in profile"
    tool = definition.split()[0]
    if not shutil.which(tool):
        return f"`grep -n` — `{tool}` not on PATH"
    return f"`{definition}` / `{lookup.get('references', '')}`"


def render_profile(state, config, args, seeded, missing):
    s, repo = state["settings"], state["repo"]
    mutation = f"{s['mutation_max']} mutants per verifier pass" if s["mutation_max"] \
        else "off (`mutation.max: 0`)"
    states = s["jira_states"]
    jira_map = " · ".join(f"{k} `{states.get(k, d)}`" for k, d in (
        ("in_progress", "In Progress"), ("in_review", "In Review"), ("done", "Done")))
    override = "validated" if (Path(repo["main_checkout"]) / ".auto-dev.yml").exists() \
        else "none"
    seeded_text = ", ".join(seeded) or "none"
    if missing:
        seeded_text += f" (not found: {', '.join(missing)})"
    lines = [
        "# Project profile", "",
        f"- **Stack:** {s['stack'] or '—'}",
        f"- **Profile:** {args.profile_source or (args.profile or '.auto-dev.yml')}",
        (f"- **Repo:** {repo['name']}   **CI:** {s['ci']}   **CI timeout:** "
         f"{s['ci_timeout']} min"),
        (f"- **Base:** {repo['base']}   **Staging:** "
         f"{repo['staging'] or 'n/a — no staging branch'}   **Prefix:** {repo['prefix']}"),
        f"- **Iteration budget:** {state['budget']['total']} per task",
        f"- **Mutation cap:** {mutation}",
        f"- **Worktree files seeded:** {seeded_text}",
        f"- **Symbol lookup:** {symbol_lookup(config)}",
        f"- **`.auto-dev.yml`:** {override}",
        f"- **Post-plan gate:** {'on — gates.post_plan' if s['post_plan_gate'] else 'off'}",
        "- **Security directives:** " + (", ".join(args.security_doc)
                                         or "none found — repo coding rules only"),
        f"- **Jira:** {args.jira or 'unavailable — no ticket'}",
        f"  {jira_map}", "",
        *setup_and_gate_lines(s),
        "", TEST_NOTES, config.get("test_notes", "") or "none", "",
        "## Assumptions",
    ]
    lines += [f"- {a}" for a in args.assumption] or ["none"]
    return "\n".join(lines) + "\n"


def setup_and_gate_lines(settings):
    """profile.md's Setup and Quality gate sections."""
    lines = [SETUP_HEADING]
    lines += [f"{i}. `{cmd}`" for i, cmd in enumerate(settings["setup"], 1)] or ["none"]
    lines += ["", "## Quality gate — run in order, verbatim (the Definition of Done)",
              "| # | kind | command | report |", "|---|------|---------|--------|"]
    lines += [f"| {i} | {c.get('kind', '')} | `{c.get('command', '')}` | "
              f"`{c.get('report', '')}` |" for i, c in enumerate(settings["gate"], 1)]
    return lines


def refresh_setup(artifact_dir, state, profile_path):
    """Before setup runs again: read setup and gate again from `.auto-dev.yml`
    and `--profile`, so the fix the failure message asked for takes effect."""
    settings = state["settings"]
    fallback = None if profile_path else {"setup": settings["setup"],
                                          "gate": settings["gate"]}
    config = resolve_config(state["repo"]["main_checkout"], profile_path, fallback)
    settings["setup"], settings["gate"] = config.get("setup", []), config.get("gate", [])
    profile_md = artifact_dir / "profile.md"
    try:
        text = profile_md.read_text(encoding="utf-8")
    except OSError:
        return
    start, end = text.find(SETUP_HEADING), text.find("\n" + TEST_NOTES)
    if start != -1 and end > start:
        text = text[:start] + "\n".join(setup_and_gate_lines(settings)) + "\n" + text[end:]
        profile_md.write_text(text, encoding="utf-8")


def start_setup(artifact_dir, state):
    """Run the setup commands detached, so a slow install outlives one Bash call.

    Records the runner's PID in state, so a later `--continue` can tell a
    runner that died from one still working. Returns the Popen object.
    """
    (artifact_dir / SETUP_RESULT).unlink(missing_ok=True)
    runner = [sys.executable, str(SCRIPTS / "autodev.py"), "_run-setup",
              str(artifact_dir)]
    with open(artifact_dir / SETUP_LOG, "w", encoding="utf-8") as log:
        proc = subprocess.Popen(runner, cwd=state["worktree"], stdout=log,
                                stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                start_new_session=True)
    state["init"]["setup_pid"] = proc.pid
    st.save(artifact_dir, state)
    return proc


def run_setup(artifact_dir):
    """The detached runner: each setup command in order, then setup.json.

    setup.json is written however the runner ends, so init never waits on a
    result that will not come.
    """
    artifact_dir = Path(artifact_dir)
    result = {"status": "failed", "failed_command": None, "exit_code": None}
    try:
        state = st.load(artifact_dir)
        result = {"status": "done", "failed_command": None, "exit_code": 0}
        for cmd in state["settings"]["setup"]:
            print(f"$ {cmd}", flush=True)
            code = subprocess.call(cmd, shell=True, cwd=state["worktree"])
            if code != 0:
                result = {"status": "failed", "failed_command": cmd, "exit_code": code}
                break
    except BaseException as exc:  # record it, whatever it is
        print(f"setup runner error: {exc!r}", flush=True)
        result = {"status": "failed", "failed_command": result.get("failed_command"),
                  "exit_code": None, "error": repr(exc)}
    finally:
        result["finished"] = st.now()
        tmp = artifact_dir / (SETUP_RESULT + ".tmp")
        tmp.write_text(json.dumps(result), encoding="utf-8")
        os.replace(tmp, artifact_dir / SETUP_RESULT)
    return 0 if result["status"] == "done" else 1


def runner_alive(pid, proc=None):
    """Whether the setup runner is still running; True when it can't be told."""
    if proc is not None:  # started by this process: poll() also reaps it
        return proc.poll() is None
    if not pid:
        return True
    if os.name == "nt":
        # os.kill(pid, 0) would terminate the process on Windows; ask instead.
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
        if not handle:
            return kernel32.GetLastError() != 87  # ERROR_INVALID_PARAMETER: no such pid
        code = ctypes.c_ulong()
        ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        kernel32.CloseHandle(handle)
        return not ok or code.value == STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:  # it exists but belongs to someone else
        return True
    return True


def setup_failed(artifact_dir, state, reason, message):
    """Record a failed setup and stop. The run stays open (Phase 1 held), so
    `resume` finds it and `init --continue` runs setup again."""
    state["init"]["setup"] = "failed"
    st.set_phase(state, 1, "held", f"{reason}; fix it, then run `autodev.py init "
                                   f"--continue {state['worktree']}`")
    st.save(artifact_dir, state)
    raise Fail(message)


def wait_for_setup(artifact_dir, state, args, proc=None):
    result_path = artifact_dir / SETUP_RESULT
    log = artifact_dir / SETUP_LOG
    cont = f"`autodev.py init --continue {state['worktree']}`"
    if state["init"].get("setup") == "done":
        return report_ready(state, args)
    pid = state["init"].get("setup_pid")
    deadline = time.monotonic() + max(args.max_wait, 0)
    alive = True
    while not result_path.exists() and time.monotonic() < deadline:
        alive = runner_alive(pid, proc)
        if not alive:
            break
        time.sleep(1)
    if not result_path.exists():
        if not alive or not runner_alive(pid, proc):
            if not result_path.exists():  # it may have finished just now
                setup_failed(artifact_dir, state, "setup runner died",
                             f"the setup runner stopped without a result; see {log}. "
                             f"Run {cont} to start setup again")
        else:
            emit(args.json, "SETUP-RUNNING",
                 f"setup is still running (log: {log}); run {cont}",
                 worktree=state["worktree"])
            return EXIT_SETUP_RUNNING
    result = json.loads(result_path.read_text(encoding="utf-8"))
    if result["status"] != "done":
        cmd, code = result.get("failed_command"), result.get("exit_code")
        fix = ("Fix the cause (a setup command comes from the profile or "
               f"{Path(state['repo']['main_checkout']) / '.auto-dev.yml'}; pass "
               f"--profile <file> to use an edited profile), then run {cont}")
        if result.get("error"):
            setup_failed(artifact_dir, state, "setup runner failed",
                         f"the setup runner failed: {result['error']}; see {log}. "
                         f"Run {cont} to start setup again")
        if code == 127:
            setup_failed(artifact_dir, state, f"setup failed: `{cmd}` not found",
                         f"setup command `{cmd}` was not found (exit 127): the "
                         "stack's toolchain is not installed. Install it, then run "
                         f"{cont}; do not drop gate checks")
        setup_failed(artifact_dir, state, f"setup failed: `{cmd}` exited {code}",
                     f"setup command `{cmd}` exited {code}; see {log}. {fix}")
    state["init"]["setup"] = "done"
    st.set_phase(state, 1, "done", "")
    st.save(artifact_dir, state)
    return report_ready(state, args)


def report_ready(state, args):
    emit(args.json, "INIT", state["worktree"], branch=state["branch"],
         base=state["repo"]["base"], staging=state["repo"]["staging"] or "n/a",
         artifact_dir=state["artifact_dir"], setup="done",
         ci=state["settings"]["ci"])
    return 0
