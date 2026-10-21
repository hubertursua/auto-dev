#!/usr/bin/env python3
"""Give each pipeline eval its own branch of one fixture repo, and clean up after.

The evals in skills/auto-dev/evals/evals.json need a GitHub-hosted repo: a run
opens a PR and watches its CI. Rather than a throwaway repo per eval (deleting
one needs a token that can delete any repo), every eval runs on its own branches
of one long-lived fixture repo, under `eval/<run>/e<id>/`:

    eval/<run>/e<id>/base         the eval's base branch, pushed by `setup`
    eval/<run>/e<id>/work/<slug>  the run's feature branch; its PR targets base

`setup` clones the fixture repo into the run's work directory, commits an
`.auto-dev.yml` that points `branches.base` and `branches.prefix` there, and
pushes the base branch. The fixture's own branches are never changed. `cleanup`
closes the run's open PRs, deletes every remote branch under `eval/<run>/` and
every repository secret named exactly `EVAL_<RUN>_E<id>` (the run id in upper
case, `-` as `_`; an eval whose CI needs a secret names it so), and removes the
run's work directory. Nothing here needs more than push access and
`gh` with the `repo` scope. A base branch that changes `.github/workflows/`
(evals that change the fixture's CI) needs the `workflow` scope to push, unless
`--from` names a ref that already holds the change.

The fixture's CI must run on `pull_request` to any branch, and on `push` to
`eval/**` (the main gate's merge lands on the eval's base branch, and the run
checks CI there). Put any other clone an eval needs (a second checkout, a
clone to push from as an outsider) under <workdir>/<run>/e<id>/, and push only
to branches under `eval/<run>/`, so cleanup finds everything.

Usage:
    python3 tools/eval-run.py setup --repo <owner>/<name> --run <run> --eval <id>
        [--from <ref>] [--profile <file>] [--yml <file>] [--no-config]
        [--workdir <dir>]
    python3 tools/eval-run.py cleanup --repo <owner>/<name> --run <run>
        [--dry-run] [--workdir <dir>]
    python3 tools/eval-run.py list --repo <owner>/<name>

--repo defaults to $AUTODEV_EVAL_REPO. <run> names one eval run (lowercase
letters, digits and hyphens, e.g. 20261021-a); every eval of the run shares it.
--from is the commit the base branch starts at (default: origin's default
branch). --profile copies a saved profile to where the run will look for it,
in the eval's own AUTO_DEV_PROFILES_DIR. --yml appends more `.auto-dev.yml` keys
(not `branches`). --no-config pushes nothing and writes no `.auto-dev.yml`, for
an eval that must run without one (13, 14). The run then cuts its branch from
the fixture's default branch and would open its PR there, so end it before the
PR gate (both score S1 only). --workdir defaults to
$TMPDIR/auto-dev-evals; the run's clones live in <workdir>/<run>/e<id>/.
The fixture is cloned from https://github.com/<repo>.git.

setup prints, one per line: `EVAL: e<id>`, `BASE: <branch>` (or `BASE: none`),
`CLONE: <path>`, `PROFILES: <dir>` and `RUN: <command>`, the command that
starts the eval's session.
cleanup prints one line per PR closed, branch or secret deleted and directory removed
(`would …` with --dry-run), then `DONE`.
list prints `<run>: <n> branches` per run that has branches left.

Exit codes:
    0  done
    1  cleanup: something could not be closed or deleted (each one printed)
    2  could not run (bad arguments, the eval is already set up, a git or gh
       command failed) — the reason is on stderr
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROFILE_PATH = ROOT / "skills" / "auto-dev" / "scripts" / "profile-path.py"
RUN_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
MARKER = ".eval-run"
PR_LIMIT = 1000


class Fail(Exception):
    pass


def run(cmd, cwd=None, check=True):
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                              errors="replace", check=False)
    except OSError as exc:
        raise Fail(f"could not run {cmd[0]}: {exc}") from exc
    if check and proc.returncode != 0:
        raise Fail(f"`{' '.join(cmd)}` failed: {proc.stderr.strip() or proc.stdout.strip()}")
    return proc


def remote_url(args):
    return f"https://github.com/{args.repo}.git"


def remote_branches(url):
    out = run(["git", "ls-remote", "--heads", url]).stdout
    return [line.split("refs/heads/", 1)[1] for line in out.splitlines()
            if "refs/heads/" in line]


def run_dir(args):
    base = args.workdir or os.path.join(tempfile.gettempdir(), "auto-dev-evals")
    return Path(os.path.realpath(base)) / args.run


def read_input(path, flag):
    try:
        return Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise Fail(f"could not read {flag} {path}: {exc}") from exc


def config_text(args, base, prefix, extra):
    lines = [f"# Written by tools/eval-run.py for eval {args.eval} of run {args.run}.",
             "branches:", f"  base: {base}", f"  prefix: {prefix}"]
    if extra:
        lines.append(extra.rstrip("\n"))
    return "\n".join(lines) + "\n"


def place_profile(clone, profiles, text):
    env = dict(os.environ, AUTO_DEV_PROFILES_DIR=str(profiles))
    proc = subprocess.run([sys.executable, str(PROFILE_PATH), str(clone)],
                          capture_output=True, text=True, env=env, check=False)
    first = (proc.stdout.splitlines() or [""])[0]
    if proc.returncode not in (0, 1) or ": " not in first:
        raise Fail(f"profile-path.py failed: {proc.stderr.strip() or first}")
    target = Path(first.split(": ", 1)[1])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def setup(args):
    if args.no_config and args.yml:
        raise Fail("--no-config and --yml can't be used together")
    extra = read_input(args.yml, "--yml") if args.yml else ""
    if re.search(r"^branches\s*:", extra, re.M):
        raise Fail("--yml must not set branches: setup sets them")
    profile = read_input(args.profile, "--profile") if args.profile else None
    rdir = run_dir(args)
    edir = rdir / f"e{args.eval}"
    if edir.exists():
        raise Fail(f"{edir} already exists: eval {args.eval} of run {args.run} "
                   "is set up; run cleanup first or pick another run")
    url = remote_url(args)
    base = f"eval/{args.run}/e{args.eval}/base"
    if not args.no_config and base in remote_branches(url):
        raise Fail(f"{base} already exists on the remote; run cleanup first")
    marker = rdir / MARKER
    if marker.exists() and marker.read_text(encoding="utf-8").strip() != args.repo:
        raise Fail(f"run {args.run} in {rdir} belongs to another fixture repo")
    clone = edir / args.repo.rsplit("/", 1)[-1]
    profiles = edir / "profiles"
    try:
        profiles.mkdir(parents=True)
        marker.write_text(f"{args.repo}\n", encoding="utf-8")
        run(["git", "clone", "-q", url, str(clone)])
        if args.from_ref:
            run(["git", "fetch", "-q", "origin", args.from_ref], cwd=clone)
            start = "FETCH_HEAD"
        else:
            start = "HEAD"
        if args.no_config:
            run(["git", "switch", "-q", "--detach", start], cwd=clone)
        else:
            if run(["git", "cat-file", "-e", f"{start}:.auto-dev.yml"], cwd=clone,
                   check=False).returncode == 0:
                raise Fail("the fixture already has an .auto-dev.yml at that ref; "
                           "pass its keys with --yml from a ref without one")
            run(["git", "switch", "-q", "-c", base, start], cwd=clone)
            prefix = f"eval/{args.run}/e{args.eval}/work"
            (clone / ".auto-dev.yml").write_text(config_text(args, base, prefix, extra),
                                                 encoding="utf-8")
            run(["git", "add", ".auto-dev.yml"], cwd=clone)
            run(["git", "commit", "-q", "-m",
                 f"Set up eval {args.eval} of run {args.run}"], cwd=clone)
        if profile is not None:
            place_profile(clone, profiles, profile)
        # The push comes last, so a step that fails leaves nothing on the remote.
        if not args.no_config:
            run(["git", "push", "-q", "-u", "origin", base], cwd=clone)
    except Fail:
        shutil.rmtree(edir, ignore_errors=True)
        raise
    except OSError as exc:
        shutil.rmtree(edir, ignore_errors=True)
        raise Fail(str(exc)) from exc
    (edir / "eval.json").write_text(json.dumps({
        "run": args.run, "eval": args.eval, "repo": args.repo,
        "base": None if args.no_config else base, "clone": str(clone),
        "profiles": str(profiles)}, indent=2) + "\n", encoding="utf-8")
    print(f"EVAL: e{args.eval}")
    print(f"BASE: {'none' if args.no_config else base}")
    print(f"CLONE: {clone}")
    print(f"PROFILES: {profiles}")
    print(f"RUN: cd {clone} && AUTO_DEV_PROFILES_DIR={profiles} "
          f"claude --plugin-dir {ROOT}")
    return 0


def cleanup(args):
    prefix = f"eval/{args.run}/"
    url = remote_url(args)
    branches = [b for b in remote_branches(url) if b.startswith(prefix)]
    proc = run(["gh", "pr", "list", "-R", args.repo, "--state", "open",
                "--limit", str(PR_LIMIT), "--json", "number,headRefName,baseRefName"])
    try:
        prs = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise Fail(f"gh pr list printed something that isn't JSON: {exc}") from exc
    if len(prs) >= PR_LIMIT:
        print(f"WARNING: the repo has {PR_LIMIT} or more open PRs; some may be missed")
    prs = [p for p in prs if p["headRefName"].startswith(prefix)
           or p["baseRefName"].startswith(prefix)]
    secret_re = re.compile(rf"EVAL_{args.run.upper().replace('-', '_')}_E\d+")
    proc = run(["gh", "secret", "list", "-R", args.repo, "--json", "name"])
    try:
        secrets = [x["name"] for x in json.loads(proc.stdout or "[]")]
    except (json.JSONDecodeError, TypeError, KeyError) as exc:
        raise Fail(f"gh secret list printed something unexpected: {exc}") from exc
    failed = False
    verb = "would " if args.dry_run else ""
    for pr in prs:
        if not args.dry_run:
            res = run(["gh", "pr", "close", str(pr["number"]), "-R", args.repo,
                       "--comment", "Closed by tools/eval-run.py cleanup."], check=False)
            if res.returncode != 0:
                failed = True
                print(f"FAILED to close PR #{pr['number']}: {res.stderr.strip()}")
                continue
        print(f"{verb}close PR #{pr['number']} ({pr['headRefName']})")
    # `git push` needs a repository to run in, even to a URL. Push from an
    # empty one, so cleanup works from any directory and never runs the hooks
    # or config of whatever repo it was started in.
    with tempfile.TemporaryDirectory() as scratch:
        if branches and not args.dry_run:
            run(["git", "init", "-q", scratch])
        # Work branches first, so no PR is left pointing at a deleted base.
        for branch in sorted(branches, key=lambda b: b.endswith("/base")):
            if not args.dry_run:
                res = run(["git", "push", "-q", url, "--delete", branch],
                          cwd=scratch, check=False)
                if res.returncode != 0:
                    failed = True
                    print(f"FAILED to delete {branch}: {res.stderr.strip()}")
                    continue
            print(f"{verb}delete branch {branch}")
    for name in sorted(n for n in secrets if secret_re.fullmatch(n)):
        if not args.dry_run:
            res = run(["gh", "secret", "delete", name, "-R", args.repo], check=False)
            if res.returncode != 0:
                failed = True
                print(f"FAILED to delete secret {name}: {res.stderr.strip()}")
                continue
        print(f"{verb}delete secret {name}")
    rdir = run_dir(args)
    if rdir.exists():
        marker = rdir / MARKER
        owner = marker.read_text(encoding="utf-8").strip() if marker.exists() else None
        if owner != args.repo:
            failed = True
            why = (f"it has no {MARKER} marker, so eval-run.py didn't make it"
                   if owner is None else f"it belongs to {owner}")
            print(f"FAILED to remove {rdir}: {why}")
        else:
            try:
                if not args.dry_run:
                    shutil.rmtree(rdir)
                print(f"{verb}remove {rdir}")
            except OSError as exc:
                failed = True
                print(f"FAILED to remove {rdir}: {exc}")
    print("DONE")
    return 1 if failed else 0


def list_runs(args):
    runs = {}
    for branch in remote_branches(remote_url(args)):
        parts = branch.split("/")
        if parts[0] == "eval" and len(parts) > 2:
            runs[parts[1]] = runs.get(parts[1], 0) + 1
    for name, count in sorted(runs.items()):
        print(f"{name}: {count} branches")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("setup", "cleanup", "list"):
        p = sub.add_parser(name)
        p.add_argument("--repo", default=os.environ.get("AUTODEV_EVAL_REPO"))
        if name != "list":
            p.add_argument("--run", required=True)
            p.add_argument("--workdir")
    s = sub.choices["setup"]
    s.add_argument("--eval", type=int, required=True)
    s.add_argument("--from", dest="from_ref")
    s.add_argument("--profile")
    s.add_argument("--yml")
    s.add_argument("--no-config", action="store_true")
    sub.choices["cleanup"].add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.repo or not re.fullmatch(r"[\w.-]+/[\w.-]+", args.repo):
        print("eval-run.py: --repo <owner>/<name> (or $AUTODEV_EVAL_REPO) is required",
              file=sys.stderr)
        return 2
    if getattr(args, "run", None) is not None and not RUN_RE.match(args.run):
        print("eval-run.py: --run must be lowercase letters, digits and hyphens",
              file=sys.stderr)
        return 2
    try:
        return {"setup": setup, "cleanup": cleanup, "list": list_runs}[args.cmd](args)
    except Fail as exc:
        print(f"eval-run.py: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
