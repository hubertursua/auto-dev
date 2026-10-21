"""autodev.py pr publish — open the PR, or refresh its description, exactly once.

Usage:
    autodev.py pr publish [--dir <artifact-dir>] [--title TEXT] [--json]

Publishes the PR description `next` generated (`<artifact-dir>/pr-body.md`,
from templates/pr-body.md and the run's artifacts) for the verified commit:

 - It refuses while the description still holds a `<!-- WRITE: ... -->` line
   (the Summary, the Assumptions, any section the repo's PR template adds and
   the boxes of its checklist are yours to write), or while `pr-body --check`
   finds a problem. Once the PR has a description, the template's checklist
   is the live one: its boxes and items stand, and are not checked again.
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
 - Everything it posts ends with the line `<!-- auto-dev -->`, so the triager
   knows the pipeline wrote it.
 - Then it reads the PR back and checks it names the verified commit.
 - A refusal (exit 1) is recorded in state.json as `publish_attempt`, so `next`
   stops and shows what was wrong instead of asking to publish again (a
   `resume` lifts that stop). gh failing before GitHub answered (signed out,
   offline, a 5xx) is exit 2 and is not recorded: run it again once gh works.

 - With `pr_review.inline_comments: true` in .auto-dev.yml, the first publish
   also posts the review findings still open or advisory, once: inline at
   their line when it is in the PR's diff, the rest in one general comment.
   A pre-existing security finding is posted only when the user sent it to a
   separate PR at the gate. A failure to post is printed, never fatal.

Exit codes:
    0  published; the PR number and URL are printed (and how the findings
       were posted, when inline comments are on)
    1  refused: a WRITE line is left, the lint failed, or GitHub did not take it
    2  could not run (no state, no description generated yet, gh missing, signed
       out or offline, or the PR could not be read back)
"""

import json
import os
import re
import tempfile
from pathlib import Path

from . import artifacts as art
from . import state as st
from .cmd_ship import SECRET_RE, gh_cannot_run  # shared with the ship steps
from .output import CANNOT_RUN, FAILED, Fail, emit
from .proc import git, run

BODY_LIMIT = 60000
TAIL = 10
WRITE_RE = re.compile(r"<!-- WRITE: .*?-->")
STRICT = ("Acceptance conditions", "Quality gate", "Review")
COMMENT_HEAD = "Command output for commit"
ATTRIBUTION = "Generated with [Claude Code](https://claude.com/claude-code)"
# The last line of every body and comment the pipeline posts: the triager
# skips a comment that carries it.
MARKER = "<!-- auto-dev -->"
# Around what a description quotes word for word (test names, commands, their
# output, the verifier's Expected line): those may carry a condition ID, which
# the lint skips inside a region generate() wrote (QUOTED_RE is in cmd_ship).
QUOTED = ("  <!-- auto-dev:quoted -->", "  <!-- /auto-dev:quoted -->")


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
    ticket = ticket_link(state["task"])
    if ticket:
        body.text("")
        body.text(ticket)
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
    for line in review_lines(ad, state):
        body.text(line)
    body.text("")
    for line in template_sections(find_template(wt)):
        body.text(line)
    body.text("## Assumptions")
    body.text("<!-- WRITE: the unresolved assumptions from SPEC.md a reviewer should "
              "sanity-check -->")
    body.text("")
    body.text(ATTRIBUTION)
    body.text(MARKER)
    text, comment = fit(body, sha)
    text, comment = clean(text, wt), clean(comment, wt)
    from .cmd_ship import quoted_digests
    state.setdefault("phase6", {})["quoted"] = sorted(quoted_digests(text))
    path = ad / "pr-body.md"
    path.write_text(text, encoding="utf-8")
    comment_path = ad / "pr-output-comment.md"
    if comment:
        comment_path.write_text(f"{COMMENT_HEAD} {sha[:12]}\n\n{comment.rstrip()}\n\n"
                                f"{MARKER}\n", encoding="utf-8")
    elif comment_path.exists():
        comment_path.unlink()
    return path


def ticket_link(task):
    """`Ticket: [KEY](link)` for a run started from a ticket, else ''."""
    key = (task.get("ticket") or "").strip()
    if not key or key == "none":
        return ""
    url = (task.get("ticket_url") or "").strip()
    return f"Ticket: [{key}]({url})" if url else f"Ticket: {key}"


# Where GitHub looks for a PR template, in its order; matched ignoring case.
# GitHub also accepts a .txt template and doesn't say which wins when a folder
# has both, so the .md one is taken first.
TEMPLATE_PLACES = tuple(f"{folder}pull_request_template{ext}"
                        for folder in (".github/", "", "docs/") for ext in (".md", ".txt"))
# Template headings the generated sections already answer.
OURS = {"summary", "acceptance conditions", "quality gate", "review", "assumptions",
        "description", "what", "why", "what and why", "what changed", "changes",
        "overview", "summary of changes", "what does this pr do", "context",
        "motivation", "details"}
TESTING = {"testing", "tests", "test", "test plan", "testing done", "how to test",
           "how has this been tested", "how was this tested", "how is this tested",
           "verification"}
HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$")
BOX_RE = re.compile(r"^\s*[-*] \[[ xX]\]\s+")
COMMENT_RE = re.compile(r"<!--(.*?)-->", re.DOTALL)
FENCE_RE = re.compile(r"^\s{0,3}(```|~~~)")
HINT_LIMIT = 200


def find_template(wt):
    """The repo's default PR template, the one GitHub puts in a new PR, or None.
    A template in a PULL_REQUEST_TEMPLATE/ folder is used only when a PR asks
    for it by name, never by default, so none from there is used."""
    root = Path(wt)
    for rel in TEMPLATE_PLACES:
        found = _ci_path(root, rel)
        if found and found.is_file():
            return found
    return None


def _ci_path(root, rel):
    here = root
    for part in rel.split("/"):
        try:
            here = next(c for c in here.iterdir() if c.name.lower() == part)
        except (StopIteration, OSError):
            return None
    return here


def norm(heading):
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", heading.lower()).split())


def template_sections(path):
    """Lines for the template's sections the generated description lacks.

    A section the description already answers is left out; a testing section
    points at the checks; a checklist is copied with every box unticked and a
    WRITE line asking for the boxes the run shows are true to be ticked; any
    other section gets a WRITE line carrying what the template asks there (its
    comments and plain text), so the orchestrator answers it from SPEC.md.
    """
    out = []
    for heading, lines in _sections(path):
        key = norm(heading)
        if not key or key in OURS:
            continue
        raw = "\n".join(lines)
        plain = COMMENT_RE.sub("", raw)
        boxes = ["- [ ] " + item for item in _items(plain)]
        asks = [" ".join(m.split()) for m in COMMENT_RE.findall(raw)]
        asks += [" ".join(ln.split()) for ln in plain.splitlines()
                 if ln.strip() and not BOX_RE.match(ln)]
        hint = " ".join(a for a in asks if a)
        if len(hint) > HINT_LIMIT:
            hint = hint[:HINT_LIMIT - 1].rstrip() + "…"
        out.append(f"## {heading}")
        if key in TESTING:
            out.append("See _Acceptance conditions_ and _Quality gate_ above.")
        elif boxes:
            out += boxes
            out.append("<!-- WRITE: tick each box SPEC.md, HANDOFF.md or this description "
                       "shows is true, and leave unticked any only a person can confirm. "
                       "Keep every item's words as they are -->")
        else:
            hint = re.sub(r"-{2,}", "-", hint)  # it can't end the WRITE comment
            out.append("<!-- WRITE: the repo's PR template asks for this section"
                       + (f" ({hint})" if hint else "") + ". Answer it in plain words "
                       "from SPEC.md, or write N/A -->")
        out.append("")
    return out


def checklist_problems(text, wt):
    """A template checklist in `text` that is missing, or whose items differ
    from the template's: the boxes may be ticked, never reworded, added to,
    dropped or reordered. Two sections under one heading pair up in order."""
    problems, body = [], split_sections(text)
    seen = {}
    for heading, lines in _sections(find_template(wt)):
        key = norm(heading)
        items = _items(COMMENT_RE.sub("", "\n".join(lines)))
        if not key or key in OURS or key in TESTING or not items:
            continue
        nth = seen[heading] = seen.get(heading, -1) + 1
        found = [b for h, b in body if h[3:].strip() == heading]
        if len(found) <= nth:
            problems.append(f"missing the PR template's checklist `## {heading}`")
        elif _items(COMMENT_RE.sub("", found[nth])) != items:
            problems.append(f"the checklist under `## {heading}` must keep the PR "
                            "template's items, word for word and in order: only tick them")
    return problems


def _items(text):
    """A checklist's items, without their boxes. An item that looks like a
    secret is left out, as the generated description drops it."""
    return [BOX_RE.sub("", ln.rstrip()) for ln in text.splitlines()
            if BOX_RE.match(ln) and not SECRET_RE.search(ln)]


def _sections(path):
    """[(heading, lines)] of a PR template. A heading inside an HTML comment or
    a code fence is not a section."""
    if path is None:
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    # Each comment on one line, so a heading inside one isn't read as a section.
    text = COMMENT_RE.sub(lambda m: "<!-- " + " ".join(m.group(1).split()) + " -->", text)
    sections, current, fence = [], None, None
    for line in text.splitlines():
        mark = FENCE_RE.match(line)
        if mark and fence in (None, mark.group(1)):
            fence = None if fence else mark.group(1)
            continue
        if fence:  # an example in a code block, not the template's own text
            continue
        match = HEADING_RE.match(line)
        if match:
            current = [match.group(1).strip(), []]
            sections.append(current)
        elif current is not None:
            current[1].append(line)
    return sections


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
    if verdict == "met" and plain and not checks:
        body.text(f"  Checked by running {plain}.")
    body.text(QUOTED[0])
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
    if body.parts[-1] == QUOTED[0]:
        body.parts.pop()  # nothing was quoted
    else:
        body.text(QUOTED[1])


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


def review_lines(ad, state):
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
        if name == "SECURITY_REVIEW.md":
            out += follow_ups(text, separate_pr(state))
    return out


def plain_words(text, fid):
    """The `In plain words:` line of finding `fid`'s own `### <id>` block, or None.

    The match stops at the next `##`/`###` heading and takes one line, so it
    never runs into another finding's block."""
    match = re.search(rf"^### {re.escape(fid)}\b(?:(?!^###? ).)*?^In plain words:[ \t]*"
                      r"([^\n]+)", text, re.MULTILINE | re.DOTALL)
    return match.group(1).strip() if match else None


def separate_pr(state):
    """The pre-existing security findings the user sent to a separate PR at the
    PR gate (`mark triage-<id> --value separate`); `*` stands for the ones the
    gate grouped under "Others"."""
    ids = set()
    for step, mark in (state.get("marks") or {}).items():
        if step.startswith("triage-") and (mark or {}).get("value") == "separate":
            fid = step[len("triage-"):]
            ids.add("*" if fid.lower() == "others" else fid)
    return ids


def sent_to_separate_pr(text, ids):
    """SECURITY_REVIEW.md's pre-existing findings the user sent to a separate PR."""
    from .cmd_review import for_the_user
    if not ids:
        return []
    try:
        pre = for_the_user(text)
    except art.ArtifactError:
        return []
    asked = pre if len(pre) <= 3 else pre[:2]  # the gate asked these one by one
    return [row for row in pre
            if row.get("ID", "").strip() in ids or ("*" in ids and row not in asked)]


def follow_ups(text, ids):
    """One line per pre-existing security finding sent to a separate PR."""
    lines = []
    for row in sent_to_separate_pr(text, ids):
        what = plain_words(text, row.get("ID", "").strip()) or row.get("Finding", "").strip()
        lines.append(f"  - Follow-up for a separate PR: {what} "
                     f"({row.get('Location', '').strip()}); it predates this change")
    return lines


def open_findings(text):
    lines = []
    for _, rows in art.tables(art.find_section(text, "Must-fix") or
                              art.find_section(text, "Findings") or ""):
        for row in rows:
            if row.get("Status", "").strip().lower().startswith("open") and (
                    "Verdict" not in row or row["Verdict"].strip().lower() == "must-fix"):
                fid = row.get("ID", "").strip()
                where = row.get("Location", "").strip()
                what = plain_words(text, fid) or row.get("Finding", "").strip()
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
    state = load(args)
    try:
        return publish_body(args, state)
    except Fail as exc:
        if exc.code != CANNOT_RUN:  # could not run is not an attempt
            note_attempt(args, state, exc.token, [str(exc)])
        raise


def note_attempt(args, state, token, problems):
    """Record a refused publish, for `next` (it stops on it)."""
    state.setdefault("phase6", {})["publish_attempt"] = {
        "result": token.lower(), "problems": problems, "seq": st.seq(state)}
    st.save(args.dir, state)


def publish_body(args, state):
    from .cmd_ship import lint_body
    p6 = state.setdefault("phase6", {})
    wt, ad = state["worktree"], Path(state["artifact_dir"])
    sha, body = p6.get("verified_sha"), p6.get("body") or {}
    if not sha or body.get("sha") != sha:
        raise Fail("no description generated for the verified commit: run "
                   "`autodev.py next`", CANNOT_RUN, "ERROR")
    path = Path(body["path"])
    text = path.read_text(encoding="utf-8")
    pr = p6.get("pr") or existing_pr(wt, state["branch"])
    live = ""
    if pr:
        code, out, err = gh(wt, "pr", "view", str(pr), "--json", "body")
        if code != 0:
            raise Fail(f"gh pr view {pr} failed: {(err or out).strip()}", CANNOT_RUN, "ERROR")
        live = json.loads(out).get("body", "")
        text = merge_live(live, text)
    if WRITE_RE.search(text):
        raise Fail(f"{path} still holds a `<!-- WRITE: ... -->` line: replace each one "
                   "(the Summary, the Assumptions, a section or checklist the repo's PR "
                   "template adds) first", FAILED, "UNWRITTEN")
    # Once the PR has a description, its checklist is the live one: edits stand.
    problems = lint_body(text, state, checklist=not live.strip())
    if problems:
        note_attempt(args, state, "PROBLEMS", problems)
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
        gh_cannot_run(code, err + out, "gh pr create/edit")  # gh broken: not a refusal
        raise Fail(f"GitHub did not take the PR: {(err or out).strip()}", FAILED, "REFUSED")
    comment_id = output_comment(wt, ad, pr, p6.get("output_comment"), sha)
    code, out, err = gh(wt, "pr", "view", str(pr), "--json", "number,url,body")
    try:
        live = json.loads(out) if code == 0 else None
    except ValueError:
        live = None
    if not isinstance(live, dict):
        raise Fail(f"PR #{pr} was published, but `gh pr view {pr}` could not read it back "
                   f"(exit {code}): {(err or out).strip()[-300:]}. Run `pr publish` again "
                   "once gh works; it updates the same PR.", CANNOT_RUN, "ERROR")
    if f"Checked at commit {sha}" not in live.get("body", ""):
        raise Fail(f"PR #{pr} does not name commit {sha} after publishing: read it with "
                   f"`gh pr view {pr}`", FAILED, "NOT-PUBLISHED")
    p6.update({"pr": int(pr), "pr_url": live.get("url", ""), "published_sha": sha,
               "output_comment": comment_id})
    p6["body"]["published_seq"] = st.seq(state)
    p6.pop("publish_attempt", None)
    st.add_note(state, f"PR #{pr} description published for {sha}")
    inline = ""
    if state["settings"].get("inline_comments") and not p6.get("inline"):
        p6["inline"] = post_findings(state, ad, pr, sha)
        inline = describe_inline(p6["inline"])
        st.add_note(state, f"review findings on PR #{pr}: {inline}")
    st.save(args.dir, state)
    emit(args.json, "PUBLISHED", f"PR #{pr}", url=live.get("url", ""), commit=sha,
         inline_comments=inline)
    return 0


# ---------------------------------------------------------------- inline findings

def post_findings(state, ad, pr, sha):
    """Post the review findings still open or advisory on the PR, once.

    Each goes inline at its `path:line` when that line is in the PR's diff
    (GitHub refuses any other line); the rest go in one general comment.
    A failure is reported, never fatal: the findings are still on disk.
    """
    wt = state["worktree"]
    # Each text is cleaned on its own: the review payload is one JSON line, so
    # cleaning it whole would blank every comment for one secret-looking line.
    findings = [dict(f, text=text) for f in review_findings(ad, state)
                if (text := clean(f["text"], wt).strip())]
    if not findings:
        return {"sha": sha, "inline": 0, "general": 0, "error": ""}
    in_diff = diff_lines(wt, state["repo"]["base"], sha)
    inline = [f for f in findings if f["line"] and f["line"] in in_diff.get(f["path"], ())]
    general = [f for f in findings if f not in inline]
    error = ""
    if inline:
        payload = {"commit_id": sha, "event": "COMMENT",
                   "body": "Findings from the automated code and security review that "
                           f"were not fixed in this PR, for reference.\n\n{MARKER}",
                   "comments": [{"path": f["path"], "line": f["line"], "side": "RIGHT",
                                 "body": f"{f['text']}\n\n{MARKER}"} for f in inline]}
        code, out, err = gh_with_file(wt, json.dumps(payload), "api", "--method", "POST",
                                      f"repos/{{owner}}/{{repo}}/pulls/{pr}/reviews",
                                      "--input", raw=True)
        if code != 0:
            error = f"inline review comments: {(err or out).strip()[:200]}"
            general, inline = findings, []
    if general:
        lines = [("Findings from the automated code and security review that were not "
                  "fixed in this PR, outside its diff:"), ""]
        lines += [f"- `{f['where']}`: {f['text']}" for f in general] + ["", MARKER]
        code, out, err = gh_with_file(wt, "\n".join(lines) + "\n", "pr", "comment",
                                      str(pr), "--body-file")
        if code != 0:
            error = (error + "; " if error else "") + \
                f"general comment: {(err or out).strip()[:200]}"
            general = []
    return {"sha": sha, "inline": len(inline), "general": len(general), "error": error}


def describe_inline(result):
    text = f"{result['inline']} posted inline, {result['general']} in a general comment"
    return text + (f"; failed: {result['error']}" if result["error"] else "")


def gh_with_file(wt, text, *args, raw=False):
    """Run gh with `text` in a file, its path last; `raw`: text already cleaned."""
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False,
                                     encoding="utf-8") as fh:
        fh.write(text if raw else clean(text, wt))
        name = fh.name
    try:
        return gh(wt, *args, name)
    finally:
        os.unlink(name)


def review_findings(ad, state):
    """[{path, line, where, text}] for each finding to post: open must-fix and
    advisory ones from both reviews, and a pre-existing security finding only
    when the user sent it to a separate PR at the gate."""
    found = []
    code = _read(ad / "CODE_REVIEW.md")
    for section, label in (("Must-fix", "Must-fix, left open at the PR gate"),
                           ("Advisory", "Advisory")):
        for _, rows in art.tables(art.find_section(code, section) or ""):
            for row in rows:
                if section == "Must-fix" and not row.get("Status", "").strip().lower(
                        ).startswith("open"):
                    continue
                found.append(finding(code, row, label))
    sec = _read(ad / "SECURITY_REVIEW.md")
    for _, rows in art.tables(art.find_section(sec, "Findings") or ""):
        for row in rows:
            verdict = row.get("Verdict", "").strip().lower()
            if verdict == "must-fix" and row.get("Status", "").strip().lower().startswith(
                    "open"):
                found.append(finding(sec, row, "Security must-fix, left open at the PR gate"))
            elif verdict == "advisory":
                found.append(finding(sec, row, "Security advisory"))
    found += [finding(sec, row, "Pre-existing security finding, left for a separate PR")
              for row in sent_to_separate_pr(sec, separate_pr(state))]
    return found


def finding(text, row, label):
    fid = row.get("ID", "").strip()
    what = (plain_words(text, fid) if fid else None) or row.get("Finding", "").strip()
    where = row.get("Location", "").strip().strip("`")
    path, _, rest = where.rpartition(":")
    number = re.match(r"\d+", rest)
    confidence = row.get("Confidence", "").strip()
    return {"path": path if number else where, "line": int(number.group(0)) if number
            else None, "where": where,
            "text": f"**{label}**" + (f" (confidence {confidence})" if confidence else "")
                    + f": {what}"}


def diff_lines(wt, base, sha):
    """{path: set of new-side line numbers} the PR's diff shows (hunks with context)."""
    code, merge_base, _ = git(wt, "merge-base", f"origin/{base}", sha, check=False)
    if code != 0:
        return {}
    # Fixed prefixes and no colour: the user's git config must not change what
    # is parsed (diff.noprefix, color.diff=always, an external diff tool).
    code, out, _ = git(wt, "-c", "core.quotePath=false", "diff", "--no-color",
                       "--no-ext-diff", "--src-prefix=a/", "--dst-prefix=b/", "-U3",
                       merge_base.strip(), sha, check=False)
    lines, path = {}, None
    for line in out.splitlines() if code == 0 else []:
        if line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else None
        match = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", line)
        if match and path:
            start, count = int(match.group(1)), int(match.group(2) or 1)
            lines.setdefault(path, set()).update(range(start, start + count))
    return lines


def _read(path):
    try:
        return art.read(path)
    except art.ArtifactError:
        return ""


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
    # The attribution and the marker close the description, whatever moved.
    kept = [ln for ln in text.split("\n") if ln.strip() not in (ATTRIBUTION, MARKER)]
    return "\n".join(kept).rstrip() + f"\n\n{ATTRIBUTION}\n{MARKER}\n"


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
        body = (f"{COMMENT_HEAD} {sha[:12]}: superseded, the PR description holds "
                f"this commit's output.\n\n{MARKER}\n")
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
        gh_cannot_run(code, err + out, "the output comment")
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
