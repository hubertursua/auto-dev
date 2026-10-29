#!/usr/bin/env python3
"""Check that the files in this repo agree with each other.

Run from anywhere: python3 tools/check-repo.py
Exit 0 when every check passes, 1 when any fails (each failure is printed).

Checks:
- every JSON file parses;
- plugin.json and marketplace.json agree on the plugin's name and description;
- every helper script is executable and starts with a python3 shebang;
- every agent file has name, model, effort and tools in its frontmatter, and its
  model and effort match the worker tables in SKILL.md and README.md;
- every file path SKILL.md and README.md name under references/, scripts/ or
  templates/ exists, and README.md names every helper script;
- every agent file's {{slots}} are slots `autodev.py brief` knows (AUTO, CALLER
  or OPTIONAL in scripts/lib/briefs.py), its Result block lists exactly the
  `next` tokens briefs.RESULTS allows, and every templates/<file> it names
  exists; every worker in briefs.RESULTS has an agent file and vice versa;
- no agent file tells a worker to run `cd … && git`, a `$(…)`
  substitution or a shell variable, which a headless permission check refuses;
- every template a script parses exists in templates/;
- every evals/files/ path a string in evals/evals.json names exists (the
  setup and expectations as well as each eval's `files`);
- SKILL.md's description fits Claude Code's 1024-character limit;
- no file names a path from one person's machine: a home directory such as
  /Users/<name>, /home/<name> or C:\\Users\\<name>, or a folder of their own
  under ~ or $HOME (such a path must start with a dot directory, like
  ~/.claude or ~/.config, or be ~/…).
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL_DIR = ROOT / "skills" / "auto-dev"
SKILL = SKILL_DIR / "SKILL.md"
README = ROOT / "README.md"

errors = []


def fail(msg):
    errors.append(msg)


def check_json():
    for path in sorted(ROOT.rglob("*.json")):
        if ".git" in path.parts:
            continue
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            fail(f"{path.relative_to(ROOT)}: does not parse: {exc}")


def check_plugin_metadata():
    try:
        plugin = json.loads((ROOT / ".claude-plugin/plugin.json").read_text("utf-8"))
        market = json.loads((ROOT / ".claude-plugin/marketplace.json").read_text("utf-8"))
    except (OSError, ValueError) as exc:
        fail(f"plugin metadata unreadable: {exc}")
        return
    entries = [p for p in market.get("plugins", []) if p.get("name") == plugin.get("name")]
    if not entries:
        fail(f"marketplace.json has no plugin named {plugin.get('name')!r}")
    elif entries[0].get("description") != plugin.get("description"):
        fail("plugin.json and marketplace.json have different plugin descriptions")
    if not re.fullmatch(r"\d+\.\d+\.\d+", str(plugin.get("version", ""))):
        fail(f"plugin.json version {plugin.get('version')!r} is not X.Y.Z")


def check_scripts():
    for path in sorted((SKILL_DIR / "scripts").glob("*.py")):
        rel = path.relative_to(ROOT)
        if not os.access(path, os.X_OK):
            fail(f"{rel}: not executable (chmod +x)")
        with path.open(encoding="utf-8") as fh:
            if fh.readline().strip() != "#!/usr/bin/env python3":
                fail(f"{rel}: first line is not #!/usr/bin/env python3")


def frontmatter(path):
    text = path.read_text(encoding="utf-8")
    m = re.match(r"---\n(.*?)\n---\n", text, re.DOTALL)
    if not m:
        return None
    fields = {}
    for line in m.group(1).splitlines():
        key, sep, value = line.partition(":")
        if sep and not line.startswith(" "):
            fields[key.strip()] = value.strip()
    return fields


# A worker-table row: | ... | `auto-dev:<x>` | `<model>` · <effort> |
ROW = re.compile(r"\|\s*`auto-dev:([a-z-]+)`\s*\|\s*`([a-z]+)`\s*·\s*([a-z]+)\s*\|")


def table_rows(path):
    return {m.group(1): (m.group(2), m.group(3))
            for m in ROW.finditer(path.read_text(encoding="utf-8"))}


def check_agents():
    tables = {SKILL.relative_to(ROOT): table_rows(SKILL),
              README.relative_to(ROOT): table_rows(README)}
    agents = {}
    for path in sorted((ROOT / "agents").glob("*.md")):
        rel = path.relative_to(ROOT)
        fm = frontmatter(path)
        if fm is None:
            fail(f"{rel}: no frontmatter")
            continue
        missing = [k for k in ("name", "model", "effort", "tools") if not fm.get(k)]
        if missing:
            fail(f"{rel}: frontmatter is missing {', '.join(missing)}")
            continue
        if fm["name"] != f"auto-dev-{path.stem}":
            fail(f"{rel}: name is {fm['name']!r}, expected 'auto-dev-{path.stem}'")
        agents[path.stem] = (fm["model"], fm["effort"])
    for table, rows in tables.items():
        for agent, setting in agents.items():
            if agent not in rows:
                fail(f"{table}: worker table has no row for auto-dev:{agent}")
            elif rows[agent] != setting:
                fail(f"{table}: auto-dev:{agent} is {rows[agent][0]} · {rows[agent][1]}, "
                     f"but agents/{agent}.md says {setting[0]} · {setting[1]}")
        for agent in rows.keys() - agents.keys():
            fail(f"{table}: worker table names auto-dev:{agent}, which has no agents/ file")


# A headless run refuses these forms even when the command is allowed, and a
# worker that copies one from its instructions can stop on the refusal.
REFUSED_FORMS = [(re.compile(r"\$\((?!…\))"), "a `$(…)` substitution"),
                 (re.compile(r"\bcd (?!<path>)[^`\n]*&&\s*git\b"), "a `cd … && git` prefix"),
                 (re.compile(r"\$(?:[A-Za-z_?@#*]|\{|\d)"), "a shell variable")]


def check_agent_commands(agents_dir=ROOT / "agents"):
    for path in sorted(agents_dir.glob("*.md")):
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for pattern, what in REFUSED_FORMS:
                if pattern.search(line):
                    fail(f"{path.name}:{n}: gives {what}; write the command plainly "
                         "(`git -C <path>`, a literal value from the brief)")


PATH_REF = re.compile(r"(?:skills/auto-dev/)?((?:references|scripts|templates)/[\w.-]+\.(?:md|py))")


def check_paths():
    for doc in (SKILL, README):
        text = doc.read_text(encoding="utf-8")
        for ref in sorted(set(PATH_REF.findall(text))):
            if "<" in ref or not (SKILL_DIR / ref).exists():
                fail(f"{doc.relative_to(ROOT)}: names {ref}, which does not exist")
    readme = README.read_text(encoding="utf-8")
    for path in sorted((SKILL_DIR / "scripts").glob("*.py")):
        if path.name not in readme:
            fail(f"README.md: does not mention scripts/{path.name} (see Dependencies)")


# Templates a script reads by name (scripts/lib/artifacts.py and cmd_*.py).
PARSED_TEMPLATES = ("SPEC.md", "IMPLEMENTATION.md", "MANIFEST.md", "SPEC_EVAL.md",
                    "R.md", "VOTES.md", "CODE_REVIEW.md", "SECURITY_REVIEW.md", "lint.md",
                    "corrections.md", "fix.md", "pr-body.md", "rubric.md", "PROPOSAL.md",
                    "RULINGS.md", "CODER_PROPOSAL.md")
TEMPLATE_REF = re.compile(r"templates/([\w.-]+\.md)")
NEXT_LINE = re.compile(r"^next: (.+)$", re.MULTILINE)


def load_briefs():
    sys.path.insert(0, str(SKILL_DIR / "scripts"))
    from lib import briefs  # the scripts dir is only on sys.path from here
    return briefs


def check_briefs(agents_dir=ROOT / "agents"):
    briefs = load_briefs()
    agents = {p.stem: p.read_text(encoding="utf-8") for p in Path(agents_dir).glob("*.md")}
    for worker in sorted(set(briefs.RESULTS) - set(agents)):
        fail(f"scripts/lib/briefs.py: RESULTS names {worker}, which has no agents/ file")
    for worker, text in sorted(agents.items()):
        rel = f"agents/{worker}.md"
        if worker not in briefs.RESULTS:
            fail(f"{rel}: no entry in scripts/lib/briefs.py RESULTS")
            continue
        for slot in sorted(set(briefs.SLOT_RE.findall(text))):
            if briefs.kind(worker, slot) is None:
                fail(f"{rel}: slot {{{{{slot}}}}} is not AUTO, CALLER or OPTIONAL in "
                     "scripts/lib/briefs.py")
        block = re.search(r"```auto-dev-result\n(.*?)```", text, re.DOTALL)
        if not block:
            fail(f"{rel}: no ```auto-dev-result block in its Result section")
        else:
            line = NEXT_LINE.search(block.group(1))
            tokens = {t.strip() for t in line.group(1).split("|")} if line else set()
            if tokens != briefs.RESULTS[worker]:
                fail(f"{rel}: Result block's next tokens {sorted(tokens)} differ from "
                     f"briefs.RESULTS {sorted(briefs.RESULTS[worker])}")
        for name in sorted(set(TEMPLATE_REF.findall(text))):
            if not (SKILL_DIR / "templates" / name).exists():
                fail(f"{rel}: names templates/{name}, which does not exist")
    for name in PARSED_TEMPLATES:
        if not (SKILL_DIR / "templates" / name).exists():
            fail(f"templates/{name} is missing: a script parses it")


# An eval fixture path, wherever it appears in evals.json. It ends on a name
# character, so a sentence's closing period isn't part of it. A path with a
# placeholder or glob (`<slug>`, `*`) is checked only up to that character.
EVAL_PATH = re.compile(r"(?<![\w./-])(?:skills/auto-dev/)?(evals/files/[\w./-]*[\w-])")


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


def check_eval_paths(evals=SKILL_DIR / "evals" / "evals.json"):
    try:
        data = json.loads(evals.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return  # check_json reports it
    rel = evals.relative_to(ROOT) if evals.is_relative_to(ROOT) else evals
    for ref in sorted({r for text in strings(data) for r in EVAL_PATH.findall(text)}):
        if not (SKILL_DIR / ref).exists():
            fail(f"{rel}: names {ref}, which does not exist")


DESCRIPTION_LIMIT = 1024


def skill_description(path):
    """The frontmatter description as YAML reads it, or None when it is missing
    or written in a style this check doesn't parse (so the check fails rather
    than measure the wrong string). Handles a `>-` or `>` folded block and a
    one-line plain or quoted value."""
    m = re.match(r"---\n(.*?)\n---\n", path.read_text(encoding="utf-8"), re.DOTALL)
    lines = m.group(1).splitlines() if m else []
    for i, line in enumerate(lines):
        key, _, value = line.partition(":")
        if key != "description":
            continue
        value = value.strip()
        rest = lines[i + 1:]
        body = []
        for more in rest:
            if more.strip() and not more.startswith(" "):
                break
            body.append(more)
        while body and not body[-1].strip():
            body.pop()
        if value in (">", ">-"):
            # Fold: lines in a paragraph join with a space; each blank line
            # between paragraphs is one newline.
            out, blanks = "", 0
            for more in body:
                if not more.strip():
                    blanks += 1
                    continue
                if out:
                    out += "\n" * blanks if blanks else " "
                out += more.strip()
                blanks = 0
            return out + ("\n" if value == ">" else "")
        if not value or body or value[0] in ">|&*!%@`#":
            return None
        if value[0] in "'\"":
            if len(value) < 2 or value[-1] != value[0]:
                return None
            inner = value[1:-1]
            return inner.replace("''", "'") if value[0] == "'" else inner
        return value.split(" #")[0].rstrip()
    return None


def check_skill_description(path=SKILL):
    description = skill_description(path)
    if not description:
        fail(f"{path.name} has no description this check can read: write it as "
             "a `>-` block or a one-line value")
    elif len(description) > DESCRIPTION_LIMIT:
        fail(f"{path.name}'s description is {len(description)} characters; "
             f"the limit is {DESCRIPTION_LIMIT}")


# A path only one person's machine has. ~/.claude, ~/.config and ~/… are fine:
# a tool fixes those, not the user's own folder layout.
PERSONAL_PATH = re.compile(r"(?<![\w.-])(?:/(?:Users|home)/|[A-Za-z]:[\\/]Users[\\/]"
                           r"|(?:~|\$HOME|\$\{HOME\})/(?=[\w-]))[\w.-]+")


def check_personal_paths(root=ROOT):
    listed = subprocess.run(["git", "-C", str(root), "ls-files", "-z", "--cached",
                             "--others", "--exclude-standard"],
                            capture_output=True, text=True, check=False)
    if listed.returncode != 0:
        fail(f"could not list the repo's files: {listed.stderr.strip()}")
        return
    for name in sorted(set(filter(None, listed.stdout.split("\0")))):
        try:
            text = (root / name).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for n, line in enumerate(text.splitlines(), 1):
            match = PERSONAL_PATH.search(line)
            if match:
                fail(f"{name}:{n}: names {match.group()}, a path from one person's "
                     "machine; write a placeholder such as /path/to/auto-dev")


def main():
    check_json()
    check_plugin_metadata()
    check_scripts()
    check_agents()
    check_agent_commands()
    check_paths()
    check_briefs()
    check_eval_paths()
    check_skill_description()
    check_personal_paths()
    for msg in errors:
        print(f"FAIL {msg}")
    if errors:
        print(f"{len(errors)} problem(s).")
        return 1
    print("OK: repo files agree.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
