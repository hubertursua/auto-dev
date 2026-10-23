#!/usr/bin/env python3
"""Check that no repo file names the person committing.

Usage: python3 tools/check-identity.py [--staged] [repo]

The pre-commit hook in .githooks/ runs it with --staged; turn the hook on once
per clone with `git config core.hooksPath .githooks`.

It reads who you are from your machine: git's user.name and user.email, the
email's local part, your login name, and the GitHub username gh is logged in
as (`gh config get -h github.com user`, skipped when gh is missing). Then it
looks for each one, as a whole word and ignoring case, in the path and text of
each file. A name split across a line break still matches. A one-word term
that is a common account name (root, dev, runner, Claude, noreply, …) is
skipped, since it would match ordinary text. Two mentions are allowed: the
repo's own `<owner>/<repo>` slug from the origin remote, and the plugin's
author or owner name in .claude-plugin/*.json.

Without --staged it reads every file git tracks or would add, as they are on
disk (ignored files are skipped). With --staged it reads the staged version of
each tracked file, which is what the commit will hold.

This is a local check, not a CI one: on a CI runner the identity is the
runner's own.

Exit codes:
  0  no file names you
  1  a file names you (each mention is printed)
  2  could not run (not a git repo, or git is missing)
"""

import argparse
import getpass
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MIN_LENGTH = 3  # a shorter term matches too much ordinary text to mean you
# One-word account names shared by many machines and bots, not one person.
GENERIC = {"admin", "administrator", "app", "build", "ci", "claude", "default",
           "dev", "developer", "docker", "git", "github", "guest", "jenkins",
           "node", "noreply", "no-reply", "root", "runner", "test", "ubuntu",
           "user", "vagrant", "ec2-user"}
REMOTE = re.compile(r"[:/]([\w.-]+)/([\w.-]+?)(?:\.git)?/?$")


def git(root, *args):
    result = subprocess.run(["git", "-C", str(root), *args],
                            capture_output=True, text=True, check=False)
    return result.returncode, result.stdout.strip()


def gh_user():
    try:
        result = subprocess.run(["gh", "config", "get", "-h", "github.com", "user"],
                                capture_output=True, text=True, check=False)
    except OSError:
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def identity(root):
    """Return (terms, slug): what names you, and the repo's owner/repo slug."""
    terms = [git(root, "config", "user.name")[1], git(root, "config", "user.email")[1]]
    terms.append(terms[1].partition("@")[0] if "@" in terms[1] else "")
    try:
        terms.append(getpass.getuser())
    except (KeyError, OSError):
        pass
    terms.append(gh_user())
    match = REMOTE.search(git(root, "remote", "get-url", "origin")[1])
    slug = f"{match.group(1)}/{match.group(2)}" if match else None
    unique = {}
    for term in terms:
        term = " ".join(term.split())
        if len(term) < MIN_LENGTH or term.lower() in GENERIC:
            continue
        unique.setdefault(term.lower(), term)
    return sorted(unique.values(), key=len, reverse=True), slug


def pattern(term):
    words = r"\s+".join(re.escape(word) for word in term.split())
    return re.compile(rf"(?<![A-Za-z0-9]){words}(?![A-Za-z0-9])", re.IGNORECASE)


AUTHOR_LINE = re.compile(r'^\s*"name":\s*"[^"]*",?\s*$')


def allowed(name, line, slug):
    """Blank out the mentions this check allows."""
    if slug:
        line = re.sub(re.escape(slug), "", line, flags=re.IGNORECASE)
    if name.startswith(".claude-plugin/") and name.endswith(".json") \
            and AUTHOR_LINE.match(line):
        return ""
    return line


def files_on_disk(root):
    listed = subprocess.run(["git", "-C", str(root), "ls-files", "-z", "--cached",
                             "--others", "--exclude-standard"],
                            capture_output=True, check=False)
    if listed.returncode != 0:
        return None
    files = []
    for name in sorted(set(filter(None, listed.stdout.decode().split("\0")))):
        try:
            files.append((name, (root / name).read_bytes()))
        except OSError:
            files.append((name, b""))
    return files


def files_staged(root):
    listed = subprocess.run(["git", "-C", str(root), "ls-files", "-z", "--cached"],
                            capture_output=True, check=False)
    if listed.returncode != 0:
        return None
    names = sorted(n for n in set(listed.stdout.decode().split("\0")) if n and "\n" not in n)
    batch = subprocess.run(["git", "-C", str(root), "cat-file", "--batch"],
                           input="".join(f":{n}\n" for n in names).encode(),
                           capture_output=True, check=False)
    if batch.returncode != 0:
        return None
    out, pos, files = batch.stdout, 0, []
    for name in names:
        end = out.index(b"\n", pos)
        header = out[pos:end].split()
        pos = end + 1
        if len(header) != 3:  # "missing": a submodule, or a path git can't resolve
            files.append((name, b""))
            continue
        size = int(header[2])
        files.append((name, out[pos:pos + size]))
        pos += size + 1
    return files


def mentions(name, data, slug, patterns):
    found = {}
    for regex in patterns:
        match = regex.search(name)
        if match:
            found.setdefault(0, match.group())
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        lines = []
    text = "\n".join(allowed(name, line, slug) for line in lines)
    for regex in patterns:
        for match in regex.finditer(text):
            found.setdefault(text.count("\n", 0, match.start()) + 1, match.group())
    for n in sorted(found):
        where = f"{name}:{n}" if n else f"{name} (path)"
        yield f"{where}: names {' '.join(found[n].split())!r}"


def check(root, staged):
    code, out = git(root, "rev-parse", "--is-inside-work-tree")
    if code != 0 or out != "true":
        print(f"could not run: {root} is not a git work tree")
        return 2
    terms, slug = identity(root)
    patterns = [pattern(term) for term in terms]
    files = files_staged(root) if staged else files_on_disk(root)
    if files is None:
        print("could not run: git could not list the repo's files")
        return 2
    found = [msg for name, data in files for msg in mentions(name, data, slug, patterns)]
    for msg in found:
        print(f"FAIL {msg}")
    if found:
        print(f"{len(found)} mention(s) of you; use a placeholder or a role instead.")
        return 1
    print("OK: no file names you.")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--staged", action="store_true",
                        help="read the staged version of each file")
    parser.add_argument("repo", nargs="?", default=str(ROOT))
    args = parser.parse_args()
    return check(Path(args.repo).resolve(), args.staged)


if __name__ == "__main__":
    sys.exit(main())
