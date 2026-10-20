"""autodev.py pr publish — open the PR, or refresh its description, exactly once.

Usage:
    autodev.py pr publish [--dir <artifact-dir>] [--title TEXT] [--json]

Publishes the PR description `next` generated (`<artifact-dir>/pr-body.md`,
from templates/pr-body.md and the run's artifacts) for the verified commit:

 - It refuses while the description still holds a `<!-- WRITE: ... -->` line
   (the Summary and Assumptions are yours to write), or while
   `pr-body --check` finds a problem.
 - No PR yet: it looks for an open PR from this branch first and uses that one;
   otherwise it opens a draft PR to the base branch, titled with the commit's
   subject (or --title). There is never a second PR.
 - A PR already open: it reads the live description and replaces only the
   sections the pipeline writes (Acceptance conditions, Quality gate, Review),
   so the Summary, the Assumptions and any edit made on GitHub survive, and a
   box someone ticked under "Checks for a person" stays ticked.
 - Output too long for the description goes to one PR comment, edited in place
   on every refresh (never a second one), and is marked superseded once the
   description fits again.
 - Then it reads the PR back and checks it names the verified commit.

Exit codes:
    0  published; the PR number and URL are printed
    1  refused: a WRITE line is left, the lint failed, or GitHub did not take it
    2  could not run (no state, no description generated yet, gh missing)
"""

import json
import os
import re
import tempfile
from pathlib import Path

from . import artifacts as art
from . import state as st
from .output import CANNOT_RUN, FAILED, Fail, emit
from .proc import git, run

BODY_LIMIT = 60000
TAIL = 10
WRITE_RE = re.compile(r"<!-- WRITE: .*?-->")
STRICT = ("Acceptance conditions", "Quality gate", "Review")
COMMENT_HEAD = "Command output for commit"
SECRET_RE = re.compile(r"(gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*"
                       r"PRIVATE KEY|xox[baprs]-[A-Za-z0-9-]{10,}|"
                       r"(?:password|passwd|secret|token)\s*[=:]\s*\S{6,})",
                       re.IGNORECASE)
ATTRIBUTION = "Generated with [Claude Code](https://claude.com/claude-code)"


def add_arguments(parser, name):
    parser.add_argument("--dir", default=".auto-dev", help="the run's .auto-dev/")
    parser.add_argument("action", choices=("publish",))
    parser.add_argument("--title", help="the PR title (default: the commit's subject)")


# ---------------------------------------------------------------- generating

class Body:
    """The description being built: text, plus output blocks that can be cut."""

    def __init__(self):
        self.parts, self.blocks = [], []

    def text(self, line=""):
        self.parts.append(line)

    def block(self, label, runs):
        """runs: [(the line introducing a run, [its output lines])]."""
        self.parts.append(len(self.blocks))
        self.blocks.append((label, runs))

    def render(self, tail=None, moved=False):
        out, comment = [], []
        for part in self.parts:
            if isinstance(part, str):
                out.append(part)
                continue
            label, lines = self.blocks[part]
            if tail:
                lines = [(intro, output[-tail:]) for intro, output in lines]
            details = ["  <details><summary>Command and output</summary>", ""]
            for intro, output in lines:
                details += [f"  {intro}", "  ```", *[f"  {ln}" for ln in output], "  ```"]
            details.append("  </details>")
            if moved:
                comment += [f"**{label}**", *[d[2:] for d in details], ""]
                out.append("  (output in the comment \"Command output for commit "
                           "<short>\")")
            else:
                out += details
        return "\n".join(out) + "\n", "\n".join(comment)


def generate(state, ad, sha):
    """Write <ad>/pr-body.md (and pr-output-comment.md when needed); return its path."""
    ad = Path(ad)
    wt = state["worktree"]
    url = repo_url(wt)
    conditions = art.spec_conditions(ad / "SPEC.md")
    ev = art.spec_eval(ad / "SPEC_EVAL.md")
    verdicts = {r["#"].strip(): r for r in ev["rows"]}
    rows, na_rows = art.manifest(ad / "acceptance" / "MANIFEST.md")
    cut = cut_sha(ad, wt)
    old = old_sha(ad, cut)
    body = Body()
    body.text("## Summary")
    body.text("<!-- WRITE: what changed and why, 2–4 sentences, drawn from SPEC.md's "
              "Context -->")
    body.text("")
    body.text("## Acceptance conditions")
    checked = [r for r in rows if r["#"].strip() in verdicts]
    files = sorted({p for r in checked if (p := art.check_path(
        r["Check (path :: test name)"]))})
    if files:
        body.text("**How this was checked.** Before any code was written, a test was "
                  "written from")
        body.text("the requirements alone for each requirement below that a test could "
                  "check, and")
        body.text(f"run on the old code (`{state['repo']['base']}` at {old}), where the "
                  "tests for new behavior")
        body.text("failed. The code was first written without those tests in view; then "
                  "they were")
        body.text("added back, and any later fix had to make them pass without changing "
                  "them.")
        body.text(f"Checked at commit {sha}: every result below was produced on this code.")
        body.text("")
        body.text("**Start review with** the tests written before the code. They state "
                  "what this")
        body.text("change must do: " + ", ".join(
            f"[`{p}`]({link(url, sha, p)})" for p in files))
    else:
        body.text("No requirement here could be checked by an automated test, so each "
                  "one")
        body.text(f"is under _Checks for a person_. Checked at commit {sha}.")
    body.text("")
    manual = []
    for cond in conditions:
        row = verdicts.get(cond["id"])
        verdict = row["Verdict"].strip().lower() if row else "unmet"
        if verdict == "manual":
            manual.append((cond, row))
            continue
        condition_entry(body, cond, row, verdict, rows, ad, wt, url, sha)
    body.text("")
    body.text("### Checks for a person")
    person = person_checks(manual, na_rows, ev, conditions)
    if person:
        for line in person:
            body.text(line)
    else:
        body.text("None: every requirement was checked automatically.")
    body.text("")
    body.text("### Changes to tests")
    for line in test_changes(ev, url, sha, cut, wt):
        body.text(line)
    body.text("")
    body.text("### Test strength")
    for line in test_strength(ev, state):
        body.text(line)
    body.text("")
    body.text("## Quality gate")
    body.text(f"The repo's own checks, run on commit {sha[:12]}:")
    quality_gate(body, ad, state)
    body.text("")
    body.text("## Review")
    for line in review_lines(ad):
        body.text(line)
    body.text("")
    body.text("## Assumptions")
    body.text("<!-- WRITE: the unresolved assumptions from SPEC.md a reviewer should "
              "sanity-check -->")
    body.text("")
    body.text(ATTRIBUTION)
    text, comment = fit(body, sha)
    text, comment = clean(text, wt), clean(comment, wt)
    path = ad / "pr-body.md"
    path.write_text(text, encoding="utf-8")
    comment_path = ad / "pr-output-comment.md"
    if comment:
        comment_path.write_text(f"{COMMENT_HEAD} {sha[:12]}\n\n{comment}", encoding="utf-8")
    elif comment_path.exists():
        comment_path.unlink()
    return path


def fit(body, sha):
    """The description and the comment its output moved to, under the limit."""
    for tail, moved in ((None, False), (TAIL, False), (TAIL, True), (3, True)):
        text, comment = body.render(tail, moved)
        text = text.replace("<short>", sha[:12])
        if len(text) <= BODY_LIMIT and len(comment) <= BODY_LIMIT:
            return text, comment
    raise Fail(f"the description is over {BODY_LIMIT} characters even with every output "
               "block moved to a comment: report it at the gate", FAILED, "TOO-LONG")


def clean(text, worktree):
    """Hide the worktree and home paths, and drop lines that look like secrets."""
    home = os.path.expanduser("~")
    if worktree:
        text = text.replace(str(worktree), ".")
    if home and home != "/":
        text = text.replace(home, "~")
    return "\n".join(ln for ln in text.split("\n") if not SECRET_RE.search(ln))


def condition_entry(body, cond, row, verdict, rows, ad, wt, url, sha):
    checks = [r for r in rows if r["#"].strip() == cond["id"]]
    plain = (row or {}).get("In plain words", "").strip() if row else ""
    if verdict == "met":
        body.text(f"- [x] **{cond['text']}**")
    else:
        what = "partly met" if verdict == "partial" else "not met"
        body.text(f"- [ ] **{cond['text']}** — {what}: {plain or 'see the output below'}")
    base_run = parse_runs(ad / "acceptance" / "base-run" / f"C{cond['id']}.txt")
    for check in checks:
        cell = check["Check (path :: test name)"]
        path = art.check_path(cell) or ""
        name = cell.split("::", 1)[-1].strip().strip('"')
        line = test_line(wt, path, name)
        base = check.get("Base run", "").strip()
        if base.startswith("not re-run"):
            old = "it was wrong and was corrected, so it never ran on the old code"
        elif check.get("Kind", "").strip() == "pass-to-pass":
            old = "old code: passed: it guards behavior that must not change"
        else:
            old = f"old code: {base}"
        now = "passes" if verdict == "met" else "see below"
        body.text(f"  Test written before the code: [`{path}` › {name}]"
                  f"({link(url, sha, path, line)}) — {old} · now: {now}")
    if verdict == "met" and plain and not checks:
        body.text(f"  Checked by running {plain}.")
    runs = []
    if base_run and base_run[0].get("Command") and not base_run[0]["Command"].startswith(
            "none"):
        names = [c["Check (path :: test name)"].split("::", 1)[-1].strip().strip('"')
                 for c in checks]
        output = [ln for ln in base_run[0].get("Output", []) if any(n in ln for n in names)]
        runs.append((f"On the old code, ran `{base_run[0]['Command']}`:",
                     output or base_run[0].get("Output", [])[-TAIL:]))
    for i, evidence in enumerate(parse_runs(ad / "evidence" / f"C{cond['id']}.txt")):
        lead = "Now, ran" if i == 0 else "Also ran"
        expect = evidence.get("Expected", "")
        runs.append((f"{lead} `{evidence.get('Command', '')}`"
                     + (f", expecting {expect}." if expect else "."),
                     evidence.get("Output", [])))
    if runs:
        body.block(cond["text"], runs)


def parse_runs(path):
    """`Key: value` runs from a base-run or evidence file; Output keeps its lines."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return []
    runs, current, key = [], None, None
    for line in text.splitlines():
        match = re.match(r"^(Expected|Commit|Command|Result|Output)(?: \(last lines\))?:"
                         r"\s*(.*)$", line)
        if match:
            key, value = match.group(1), match.group(2)
            if key in ("Expected", "Commit") or current is None or (
                    key == "Command" and "Command" in current):
                current = {}
                runs.append(current)
            current[key] = [] if key == "Output" else value.strip()
            if key == "Output" and value.strip():
                current[key].append(value)
            continue
        if current is not None and key == "Output":
            current["Output"].append(line.strip("\n"))
        elif current is not None and key and key != "Output" and line.startswith(" "):
            current[key] = (current[key] + " " + line.strip()).strip()
    for r in runs:
        if "Output" in r:
            while r["Output"] and not r["Output"][-1].strip():
                r["Output"].pop()
    return runs


def person_checks(manual, na_rows, ev, conditions):
    lines = []
    by_id = {c["id"]: c for c in conditions}
    for cond, row in manual:
        evidence = re.sub(r"^a human must check:\s*", "", row.get("Evidence", "").strip(),
                          flags=re.IGNORECASE)
        lines += [f"- [ ] **{cond['text']}**", f"  1. {evidence or 'check it by hand'}", ""]
    for row in na_rows:
        rid = row.get("#", "").strip()
        if not rid.endswith("(Edge)"):
            continue
        cond = by_id.get(rid.split()[0])
        if cond and cond["edge"]:
            proxy = row.get("Proxy a verifier can run", "").strip()
            lines += [f"- [ ] **{cond['edge']}**",
                      f"  1. {row.get('Why no check can drive it', 'check it by hand')}",
                      "",
                      "  Already checked automatically: " + (
                          f"`{proxy}`" if proxy and proxy.lower() != "none" else
                          "nothing could be, because no test can drive it"), ""]
    return lines


def test_changes(ev, url, sha, cut, wt):
    if not ev["integrity"]:
        return [("No existing test was deleted, skipped or weakened, and every new test "
                "checks something.")]
    lines = []
    for row in ev["integrity"]:
        loc = row.get("Location", "").strip("` ")
        path, _, line = loc.partition(":")
        old = line.startswith("-")
        target = link(url, cut if old else sha, path, line.lstrip("-") or None)
        what = row.get("Finding", "").replace("_", " ").lower()
        reason = row.get("Reason", "").strip()
        why = (f"because {reason}" if row.get("Judgment", "").strip().lower() == "justified"
               else f"not justified: {reason}")
        lines.append(f"- [`{path}`]({target}): {what} — {why}")
    return lines


def test_strength(ev, state):
    line = ev.get("mutation_line", "")
    if not state["settings"].get("mutation_max") or "off" in line.split(":")[0]:
        return ["Not run: the check was off."]
    counts = {k: int(v) for v, k in re.findall(
        r"(\d+)\s+(killed|timeout|survived|invalid)", line)}
    ran = counts.get("killed", 0) + counts.get("timeout", 0) + counts.get("survived", 0)
    caught = counts.get("killed", 0) + counts.get("timeout", 0)
    if not ran:
        return ["Not run: no change could be checked this way."]
    out = [f"We put {ran} small deliberate bugs into the changed code (for example, a",
           "comparison flipped or a boundary moved by one) and ran the tests against "
           f"each. They caught {caught}." + (" Every one was caught." if caught == ran
                                              else "")]
    for row in ev["survivors"]:
        judgment = row.get("Judgment", "")
        reason = judgment.split("—", 1)[-1].strip()
        if judgment.lower().startswith("equivalent"):
            kind = f"harmless: no input can tell the two apart, because {reason}"
        else:
            kind = f"not caught: {reason}"
        out.append(f"- `{row.get('Location', '').strip('` ')}`, "
                   f"{row.get('Change', '')}: {kind}")
    return out


def quality_gate(body, ad, state):
    for check in state["settings"].get("gate", []):
        path = ad / "lint" / check.get("report", "")
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
        first = text.splitlines()[0] if text else ""
        status = "passed" if first.rstrip().endswith("pass") else "failed"
        body.text(f"- `{check['command']}`: {status}")
        tail = art.find_section(text, "Output tail") or ""
        output = [ln for ln in tail.splitlines() if not ln.startswith("```")
                  and not ln.startswith("**Suppressions")]
        while output and not output[-1].strip():
            output.pop()
        while output and not output[0].strip():
            output.pop(0)
        if output:
            body.block(check["command"], [("Output:", output)])


def review_lines(ad):
    out = []
    for name, label in (("CODE_REVIEW.md", "Code review (3 independent reviewers)"),
                        ("SECURITY_REVIEW.md", "Security review")):
        try:
            text = art.read(ad / name)
        except art.ArtifactError:
            out.append(f"- {label}: not run")
            continue
        head = art.header_line(text, "**Overall confidence")
        level = re.search(r"Overall confidence:\s*([A-Za-z]+)", head)
        reason = head.split("—", 1)[-1].strip() if "—" in head else ""
        counts = re.search(r"Must-fix:\s*(\d+) open · (\d+) fixed", text)
        opened, fixed = (counts.groups() if counts else ("0", "0"))
        total = int(opened) + int(fixed)
        out.append(f"- {label} — confidence {level.group(1) if level else 'unknown'}: "
                   f"{reason}. {total} problems that had to be fixed: {fixed} fixed, "
                   f"{opened} open")
        out += open_findings(text)
    return out


def open_findings(text):
    lines = []
    for _, rows in art.tables(art.find_section(text, "Must-fix") or
                              art.find_section(text, "Findings") or ""):
        for row in rows:
            if row.get("Status", "").strip().lower().startswith("open") and (
                    "Verdict" not in row or row["Verdict"].strip().lower() == "must-fix"):
                fid = row.get("ID", "").strip()
                plain = re.search(rf"^### {re.escape(fid)}\b.*?^In plain words:\s*(.+)$",
                                  text, re.MULTILINE | re.DOTALL)
                where = row.get("Location", "").strip()
                what = plain.group(1).strip() if plain else row.get("Finding", "").strip()
                lines.append(f"  - Still open: {what} ({where}); shipped at the user's "
                             "call at the PR gate")
    return lines


def cut_sha(ad, wt):
    try:
        text = art.read(ad / "SPEC_EVAL.md")
    except art.ArtifactError:
        text = ""
    match = re.search(r"cut from \(`([0-9a-f]{7,40})`\)", text)
    sha = match.group(1) if match else ""
    if sha:
        code, out, _ = git(wt, "rev-parse", sha, check=False)
        if code == 0:
            return out.strip()
    return sha or "HEAD"


def old_sha(ad, cut):
    for path in sorted((ad / "acceptance" / "base-run").glob("C*.txt")):
        runs = parse_runs(path)
        if runs and re.fullmatch(r"[0-9a-f]{7,64}", runs[0].get("Commit", "")):
            return runs[0]["Commit"]
    return cut


def test_line(wt, path, name):
    try:
        lines = Path(wt, path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    return next((i for i, ln in enumerate(lines, 1) if name and name in ln), None)


def repo_url(wt):
    code, out, _ = run(["gh", "repo", "view", "--json", "url"], cwd=wt, check=False)
    try:
        return json.loads(out)["url"] if code == 0 else ""
    except (ValueError, KeyError):
        return ""


def link(url, sha, path, line=None):
    if not url:
        return path
    return f"{url}/blob/{sha}/{path}" + (f"#L{line}" if line else "")


# ---------------------------------------------------------------- publishing

def load(args):
    try:
        return st.load(args.dir)
    except st.StateError as exc:
        raise Fail(str(exc), CANNOT_RUN, "ERROR") from None


def gh(wt, *args):
    code, out, err = run(["gh", *args], cwd=wt, check=False)
    if code == 127:
        raise Fail("gh is not installed", CANNOT_RUN, "ERROR")
    return code, out, err


def publish(args):
    from .cmd_ship import lint_body
    state = load(args)
    p6 = state.setdefault("phase6", {})
    wt, ad = state["worktree"], Path(state["artifact_dir"])
    sha, body = p6.get("verified_sha"), p6.get("body") or {}
    if not sha or body.get("sha") != sha:
        raise Fail("no description generated for the verified commit: run "
                   "`autodev.py next`", CANNOT_RUN, "ERROR")
    path = Path(body["path"])
    text = path.read_text(encoding="utf-8")
    pr = p6.get("pr") or existing_pr(wt, state["branch"])
    if pr:
        code, out, err = gh(wt, "pr", "view", str(pr), "--json", "body")
        if code != 0:
            raise Fail(f"gh pr view {pr} failed: {(err or out).strip()}", CANNOT_RUN, "ERROR")
        text = merge_live(json.loads(out).get("body", ""), text)
    if WRITE_RE.search(text):
        raise Fail(f"{path} still holds a `<!-- WRITE: ... -->` line: write the Summary "
                   "and Assumptions there first", FAILED, "UNWRITTEN")
    problems = lint_body(text, state)
    if problems:
        emit(args.json, "PROBLEMS", f"{len(problems)} problem(s); nothing published",
             problem=problems)
        return FAILED
    with tempfile.NamedTemporaryFile("w", suffix=".md", dir=str(ad), delete=False,
                                     encoding="utf-8") as fh:
        fh.write(text)
        final = fh.name
    try:
        if pr:
            code, out, err = gh(wt, "pr", "edit", str(pr), "--body-file", final)
        else:
            title = args.title or git(wt, "log", "-1", "--format=%s").strip()
            code, out, err = gh(wt, "pr", "create", "--draft", "--base",
                                state["repo"]["base"], "--head", state["branch"],
                                "--title", title, "--body-file", final)
            match = re.search(r"/pull/(\d+)", out)
            pr = match.group(1) if match else None
    finally:
        os.unlink(final)
    if code != 0 or not pr:
        raise Fail(f"GitHub did not take the PR: {(err or out).strip()}", FAILED, "REFUSED")
    comment_id = output_comment(wt, ad, pr, p6.get("output_comment"), sha)
    code, out, err = gh(wt, "pr", "view", str(pr), "--json", "number,url,body")
    try:
        live = json.loads(out)
    except ValueError:
        live = {}
    if f"Checked at commit {sha}" not in live.get("body", ""):
        raise Fail(f"PR #{pr} does not name commit {sha} after publishing: read it with "
                   f"`gh pr view {pr}`", FAILED, "NOT-PUBLISHED")
    p6.update({"pr": int(pr), "pr_url": live.get("url", ""), "published_sha": sha,
               "output_comment": comment_id})
    p6["body"]["published_seq"] = st.seq(state)
    st.add_note(state, f"PR #{pr} description published for {sha}")
    st.save(args.dir, state)
    emit(args.json, "PUBLISHED", f"PR #{pr}", url=live.get("url", ""), commit=sha)
    return 0


def existing_pr(wt, branch):
    code, out, _ = gh(wt, "pr", "list", "--head", branch, "--state", "open", "--json",
                      "number")
    try:
        found = json.loads(out) if code == 0 else []
    except ValueError:
        found = []
    return found[0]["number"] if found else None


def merge_live(live, new):
    """The live description with the pipeline's sections replaced from `new`."""
    if not live.strip():
        return new
    new_sections = split_sections(new)
    ticked = set(re.findall(r"^- \[x\] \*\*(.+?)\*\*", section_of(live, "Acceptance "
                                                                     "conditions"),
                            re.MULTILINE))
    out = []
    for heading, body in split_sections(live):
        name = heading[3:].strip() if heading else ""
        if name in STRICT:
            body = dict(new_sections).get(heading, body)
            if name == "Acceptance conditions":
                body = keep_ticks(body, ticked)
        out.append((heading, body))
    present = {h for h, _ in out}
    for heading, body in new_sections:
        if heading and heading[3:].strip() in STRICT and heading not in present:
            out.append((heading, body))
    text = "\n".join((f"{h}\n" if h else "") + b for h, b in out)
    if ATTRIBUTION not in text:
        text = text.rstrip() + f"\n\n{ATTRIBUTION}\n"
    return text


def split_sections(text):
    """[(heading line or '', body)] split at `## ` headings."""
    parts, heading, body = [], "", []
    for line in text.split("\n"):
        if line.startswith("## "):
            parts.append((heading, "\n".join(body)))
            heading, body = line.rstrip(), []
        else:
            body.append(line)
    parts.append((heading, "\n".join(body)))
    return [(h, b) for h, b in parts if h or b.strip()]


def section_of(text, name):
    return next((b for h, b in split_sections(text) if h[3:].strip() == name), "")


def keep_ticks(body, ticked):
    """A person's ticked box under Checks for a person stays ticked."""
    head, sep, rest = body.partition("### Checks for a person")
    for title in ticked:
        rest = rest.replace(f"- [ ] **{title}**", f"- [x] **{title}**")
    return head + sep + rest


def output_comment(wt, ad, pr, comment_id, sha):
    path = ad / "pr-output-comment.md"
    if not path.exists() and not comment_id:
        return None
    if not path.exists():
        body = f"Superseded: the description holds the output for commit {sha[:12]}."
    else:
        body = path.read_text(encoding="utf-8")
    if not comment_id:
        comment_id = find_comment(wt, pr)
    with tempfile.NamedTemporaryFile("w", suffix=".md", dir=str(ad), delete=False,
                                     encoding="utf-8") as fh:
        fh.write(body)
        name = fh.name
    try:
        if comment_id:
            code, out, err = gh(wt, "api", "-X", "PATCH",
                                f"repos/{{owner}}/{{repo}}/issues/comments/{comment_id}",
                                "-F", f"body=@{name}")
        else:
            code, out, err = gh(wt, "pr", "comment", str(pr), "--body-file", name)
            match = re.search(r"issuecomment-(\d+)", out)
            comment_id = match.group(1) if match else None
    finally:
        os.unlink(name)
    if code != 0:
        raise Fail(f"could not write the output comment: {(err or out).strip()}", FAILED,
                   "REFUSED")
    return comment_id


def find_comment(wt, pr):
    code, out, _ = gh(wt, "pr", "view", str(pr), "--json", "comments")
    try:
        comments = json.loads(out).get("comments", []) if code == 0 else []
    except ValueError:
        comments = []
    for comment in comments:
        if comment.get("body", "").startswith(COMMENT_HEAD):
            match = re.search(r"(\d+)$", comment.get("url", ""))
            if match:
                return match.group(1)
    return None


def main(args):
    return publish(args)
