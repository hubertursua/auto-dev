#!/usr/bin/env python3
"""Name where a repo's saved auto-dev profile lives, and say whether it exists.

A saved profile lives outside every checkout, so each new clone or worktree of
the same repo finds it. The file is named after the repo's `origin` remote:

    <profiles-dir>/<host>/<owner>/<repo>.yml

`git@github.com:Acme/Web-App.git` and `https://github.com/acme/web-app` both
map to `<profiles-dir>/github.com/acme/web-app.yml` (lowercased, `.git`
dropped). Nested paths, such as a GitLab subgroup, keep every segment. Two
repos whose paths differ only in case share one file.

<profiles-dir> is the first of these that is set:
    $AUTO_DEV_PROFILES_DIR
    $XDG_CONFIG_HOME/auto-dev/profiles
    ~/.config/auto-dev/profiles

Usage:
    python3 <skill-dir>/scripts/profile-path.py <repo>
    python3 <skill-dir>/scripts/profile-path.py --help

<repo> is any checkout or worktree of the repo; pass it as an absolute path.
The script only reads: it never creates the directory or the file.

Output (stdout, one line):
    FOUND: <path>        a saved profile exists at <path>
    NOT FOUND: <path>    none yet; <path> is where to save one
    then `DIR: <profiles-dir>` on a second line, the directory to allow in
    Claude Code's permissions.

Exit codes:
    0  a saved profile exists
    1  no saved profile (not an error: research one)
    2  could not run (not a git repo, no `origin` remote, or a URL it cannot
       turn into a safe path) — the reason is on stderr; NOT the same as 1
"""

import os
import re
import subprocess
import sys
from pathlib import Path

# One path segment of the saved file's location. Anything else (spaces, `..`,
# a stray `:`) could escape the profiles directory, so it is refused.
SEGMENT = re.compile(r"[a-z0-9][a-z0-9._-]*")


def profiles_dir():
    explicit = os.environ.get("AUTO_DEV_PROFILES_DIR")
    if explicit:
        return Path(explicit).expanduser()
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return base / "auto-dev" / "profiles"


def origin_url(repo):
    try:
        out = subprocess.run(["git", "-C", str(repo), "remote", "get-url", "origin"],
                             capture_output=True, text=True, check=False)
    except OSError as exc:
        raise ValueError(f"could not run git: {exc}") from exc
    if out.returncode != 0:
        detail = out.stderr.strip() or "no `origin` remote"
        raise ValueError(f"{repo}: {detail}")
    return out.stdout.strip()


def url_segments(url):
    """`git@host:a/b.git`, `ssh://user@host:22/a/b`, `https://host/a/b` -> [host, a, b]."""
    m = re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://(?P<rest>.*)$", url)
    if m:
        rest = m.group("rest")
        host, _, path = rest.partition("/")
        host = host.rsplit("@", 1)[-1]          # drop user or user:token
        host = host.split(":", 1)[0]            # drop a port
    else:
        m = re.match(r"^(?:[^@/]+@)?(?P<host>[^:/]+):(?P<path>.+)$", url)
        if not m:
            raise ValueError(f"cannot read a host and path from origin URL {url!r}")
        host, path = m.group("host"), m.group("path")
    path = path.strip("/")
    if path.endswith(".git"):
        path = path[: -len(".git")]
    segments = [host] + [s for s in path.split("/") if s]
    segments = [s.lower() for s in segments]
    if len(segments) < 3:
        raise ValueError(f"origin URL {url!r} has no <owner>/<repo> path")
    for seg in segments:
        if not SEGMENT.fullmatch(seg) or seg in (".", ".."):
            raise ValueError(f"origin URL {url!r} has a segment that is not safe in a "
                             f"file path: {seg!r}")
    return segments


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return 0 if args else 2
    repo = Path(args[0])
    try:
        segments = url_segments(origin_url(repo))
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    root = profiles_dir()
    path = root.joinpath(*segments[:-1], segments[-1] + ".yml")
    found = path.is_file()
    print(f"{'FOUND' if found else 'NOT FOUND'}: {path}")
    print(f"DIR: {root}")
    return 0 if found else 1


if __name__ == "__main__":
    sys.exit(main())
