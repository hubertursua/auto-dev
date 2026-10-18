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
- every file path SKILL.md and README.md name under references/, profiles/ or
  scripts/ exists, and README.md names every helper script.
"""

import json
import os
import re
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


PATH_REF = re.compile(r"(?:skills/auto-dev/)?((?:references|profiles|scripts)/[\w.-]+\.(?:md|py))")


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


def main():
    check_json()
    check_plugin_metadata()
    check_scripts()
    check_agents()
    check_paths()
    for msg in errors:
        print(f"FAIL {msg}")
    if errors:
        print(f"{len(errors)} problem(s).")
        return 1
    print("OK: repo files agree.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
