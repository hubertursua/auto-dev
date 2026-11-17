"""autodev.py setup-answer — record the user's answer to the profile question.

Usage:
    autodev.py setup-answer <save|run-only|change|stop> --repo <repo>
                            --task "<task>" [--text "<what to change>"] [--json]

Before a run exists, `autodev.py next --repo <repo> --task "<task>"` sets it
up (Phase 1): it finds the repo's saved profile (or a `.auto-dev.yml` that sets
both `setup` and `gate`), asks a lookup whether each saved gate check's tool is
adopted, or has the profiler research a draft and asks the user about it (the
profile question, exit 5). Each answer's AFTER line runs this command, which
only records the answer; the next `next --repo` acts on it:

    save      write the draft to the repo's saved-profile path (the one
              profile-path.py prints), with a first-line comment naming the
              repo and today's date, and validate it there; then the run is
              created with it. A write that fails is recorded, not a stop:
              the run is created anyway and its summary holds the YAML
    run-only  create the run with the draft, saving nothing
    change    the profiler redoes its draft with --text (the user's words),
              and the question is asked again
    stop      setup ends: nothing is created

Files before the run exists live in a private scratch folder,
`<temp>/auto-dev-setup-<uid>/<repo>-<hash of the repo and the task>`; the run
never depends on it once created (`.auto-dev/profile-origin.json` records
where its profile came from, and a failed setup is retried from that).

Output: `RECORDED: <answer>`, or `REFUSED: <why>`.

Exit codes:
    0  recorded
    1  refused: no profile question is open for this task (no researched
       draft awaiting an answer), or `save` for a repo with no save path
    2  could not run (bad arguments, the scratch folder unsafe)
"""

import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from . import cmd_init, cmd_resume, cmd_work
from . import state as st
from .output import CANNOT_RUN, FAILED, Fail, emit
from .proc import git, run

SCRIPTS = Path(__file__).resolve().parent.parent
AUTODEV = SCRIPTS / "autodev.py"
SKILL_DIR = SCRIPTS.parent
SCRATCH = "auto-dev-setup"
SETUP_FILE = "setup.json"
ANSWERS = ("save", "run-only", "change", "stop")
OPTIONS = {"save": ("Looks right — save it for this repo",
                    "Save the draft as this repo's profile, then set up the run with it."),
           "run-only": ("Looks right — use it for this run only",
                        "Set up the run with the draft; nothing is saved."),
           "change": ("Change something (tell me what)",
                      "The profiler redoes the draft as you say, and you are asked again."),
           "stop": ("Stop", "End setup here; nothing is created.")}
CHANGE_TEXT = "<what the user wants changed>"
REPORT_SECTIONS = ("PROFILE", "EVIDENCE", "NOT ADOPTED", "NOT INSTALLED", "QUESTIONS")
# A lookup's line about gate check <n>; "not adopted" is tried first.
CHECK_LINE_RE = re.compile(r"^\W*check\s+(\d+)\s*:\s*(not adopted|adopted)\b", re.IGNORECASE)
SLUG_WORDS = 5


def add_arguments(parser):
    parser.add_argument("choice", choices=ANSWERS, help="the user's answer")
    parser.add_argument("--repo", default=".", help="the checkout setup runs from")
    parser.add_argument("--task", default="", help="the task, as given to `next --repo`")
    parser.add_argument("--text", default="", help="for `change`: what the user wants changed")


def q(value):
    from .cmd_next import q as quote
    return quote(value)


def command(*words):
    return " ".join(q(w) for w in ("python3", AUTODEV, *words))


# ---------------------------------------------------------------- the decision

def checks_to_drop(gate, answer_text):
    """The 1-based numbers of the saved profile's gate checks to leave out of
    this run, from the lookup's answer: the one place that decides it.

    A check is dropped only when some line says `check <n>: not adopted` and
    none says `check <n>: adopted`; a number outside the gate, or an answer in
    any other form, drops nothing (no check is dropped on doubt)."""
    said = {}
    for line in (answer_text or "").splitlines():
        m = CHECK_LINE_RE.match(line)
        if m:
            said.setdefault(int(m.group(1)), set()).add(m.group(2).lower())
    return sorted(n for n, words in said.items()
                  if 1 <= n <= len(gate) and words == {"not adopted"})


# ---------------------------------------------------------------- the scratch folder

def scratch_base():
    uid = getattr(os, "getuid", None)
    name = f"{SCRATCH}-{uid()}" if uid else SCRATCH
    return Path(tempfile.gettempdir()).resolve() / name


def check_private(base):
    """Refuse a scratch parent someone else could have planted or can write
    to: the draft profile's commands written there later run verbatim."""
    try:
        info = os.lstat(base)
    except OSError as exc:
        raise Fail(f"cannot use the setup scratch folder {base}: {exc}", CANNOT_RUN,
                   "ERROR") from None
    if stat.S_ISLNK(info.st_mode):
        raise Fail(f"the setup scratch folder {base} is a symbolic link; remove it, then "
                   "run again", CANNOT_RUN, "ERROR")
    if not stat.S_ISDIR(info.st_mode):
        raise Fail(f"the setup scratch folder {base} is not a folder; remove it, then run "
                   "again", CANNOT_RUN, "ERROR")
    if hasattr(os, "getuid") and info.st_uid != os.getuid():
        raise Fail(f"the setup scratch folder {base} belongs to another user; remove it, "
                   "then run again", CANNOT_RUN, "ERROR")
    if os.name != "nt" and info.st_mode & 0o022:
        raise Fail(f"the setup scratch folder {base} is writable by other users; remove "
                   "it, then run again", CANNOT_RUN, "ERROR")


def scratch_path(repo, task):
    """Where this repo's and task's setup files go (not created)."""
    common = git(repo, "rev-parse", "--git-common-dir").strip()
    common_dir = Path(repo, common).resolve()
    key = hashlib.sha256(f"{common_dir}\n{task.strip()}".encode()).hexdigest()[:12]
    return scratch_base() / f"{Path(repo).name}-{key}"


def open_scratch(repo, task):
    """The scratch folder for this repo and task, created private."""
    folder = scratch_path(repo, task)
    base = folder.parent
    if not os.path.lexists(base):
        try:
            base.mkdir(mode=0o700)
        except FileExistsError:
            pass
        except OSError as exc:
            raise Fail(f"cannot create the setup scratch folder {base}: {exc}", CANNOT_RUN,
                       "ERROR") from None
    check_private(base)
    folder.mkdir(mode=0o700, exist_ok=True)
    return folder


def existing_scratch(repo, task):
    """The scratch folder when it exists (its parent checked), else None."""
    folder = scratch_path(repo, task)
    if not os.path.lexists(folder.parent):
        return None
    check_private(folder.parent)
    return folder if folder.is_dir() else None


def remove_scratch(repo, task):
    """Remove the scratch folder once setup is over (best effort)."""
    try:
        folder = existing_scratch(repo, task)
    except Exception:  # a cleanup never fails the step
        return
    if folder is not None:
        shutil.rmtree(folder, ignore_errors=True)


def load_info(folder):
    try:
        info = json.loads((folder / SETUP_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        info = {}
    if not isinstance(info, dict):
        info = {}
    info.setdefault("spawns", [])
    info.setdefault("answers", [])
    return info


def save_info(folder, info):
    tmp = folder / (SETUP_FILE + ".tmp")
    tmp.write_text(json.dumps(info, indent=2), encoding="utf-8")
    os.replace(tmp, folder / SETUP_FILE)


# ---------------------------------------------------------------- helpers

def profile_path(repo):
    """(save path, profiles dir, why there is none): profile-path.py's answer."""
    code, out, err = run([sys.executable, str(SCRIPTS / "profile-path.py"), str(repo)],
                         check=False)
    lines = out.splitlines()
    if code in (0, 1) and lines:
        path = lines[0].split(": ", 1)[1]
        root = next((ln[len("DIR: "):] for ln in lines if ln.startswith("DIR: ")), None)
        return {"found": code == 0, "save_path": path, "profiles_dir": root}
    why = (err or out).strip().replace("ERROR: ", "", 1) or f"profile-path.py exited {code}"
    return {"found": False, "save_path": None, "profiles_dir": None, "no_save": why}


def validate(path, profile):
    """(exit code, output lines) of validate-config.py on `path`."""
    cmd = [sys.executable, str(SCRIPTS / "validate-config.py")]
    cmd += ["--profile", str(path)] if profile else [str(path)]
    code, out, err = run(cmd, check=False)
    lines = [ln.rstrip() for ln in (out + "\n" + err).splitlines() if ln.strip()]
    return code, lines


def read_text(path):
    try:
        return Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def read_result(folder, spawn):
    path = folder / f"{spawn['worker']}-{spawn['n']}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        data = None
    if not isinstance(data, dict):
        return {"status": "failed", "next": "", "unreadable": str(path)}
    return data


def answer_file(folder, spawn):
    return folder / f"{spawn['worker']}-{spawn['n']}-answer.md"


def fresh(spawn):
    """Whether a brief with no result may still be out: sent out less than
    IN_FLIGHT_HOURS ago."""
    from .cmd_next import IN_FLIGHT_HOURS
    try:
        age = datetime.now(timezone.utc) - datetime.fromisoformat(spawn["issued_at"])
    except (KeyError, ValueError, TypeError):
        return False
    return age.total_seconds() < IN_FLIGHT_HOURS * 3600


def report_sections(text):
    """The profiler's report split into its sections, by heading word."""
    sections, name, fenced = {}, None, False
    for line in (text or "").splitlines():
        if line.strip().startswith("```"):
            fenced = not fenced
        head = line.lstrip("#*_ ").upper()
        found = None if fenced else next(
            (s for s in REPORT_SECTIONS if head.startswith(s)), None)
        if found:
            name = found
        if name:
            sections.setdefault(name, []).append(line)
    return sections


def slug_words(text):
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def derive_slug(task, ticket, ticket_text):
    """The ticket key (one word), then the first words of the ticket text's
    first line (else the task), at most SLUG_WORDS words in all."""
    words, source = [], (ticket_text.splitlines()[0] if ticket_text else task)
    if ticket:
        key = "-".join(slug_words(ticket))
        if key:
            words.append(key)
            source = re.sub(re.escape(ticket), " ", source, flags=re.IGNORECASE)
    for word in slug_words(source):
        if len(words) >= SLUG_WORDS:
            break
        words.append(word)
    return "-".join(words) or "task"


def free_slug(repo, slug, prefix):
    """`slug`, or `slug-2`, `slug-3`, … while its worktree path or its branch
    is taken."""
    candidate, n = slug, 1
    while cmd_init.sibling(repo, candidate).exists() or git(
            repo, "rev-parse", "-q", "--verify", f"refs/heads/{prefix}/{candidate}",
            check=False)[0] == 0:
        n += 1
        candidate = f"{slug}-{n}"
    return candidate


def find_run(repo, task, ticket):
    """(worktree, state) of this task's open run, or None."""
    for kind, tree, _, state in cmd_resume.candidates(repo):
        if kind != "run" or not st.resumable(state):
            continue
        if state["task"].get("text", "").strip() != task:
            continue
        if ticket and state["task"].get("ticket") != ticket:
            continue
        return tree, state
    return None


def read_origin(artifact_dir):
    try:
        origin = json.loads((Path(artifact_dir) / cmd_init.ORIGIN_FILE).read_text(
            encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    return origin if isinstance(origin, dict) else None


def dump_yaml(data, path):
    import yaml
    Path(path).write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True,
                                         width=1000), encoding="utf-8")


def origin_summary(artifact_dir, state):
    """What the user is told about the run's profile once it exists."""
    origin = read_origin(artifact_dir) or {}
    kind, lines = origin.get("kind"), []
    if kind == "saved":
        path = origin.get("path")
        lines.append(f"Saved the confirmed profile to {path}; the run uses it."
                     if origin.get("saved_now") else f"Using the saved profile at {path}.")
        for check in origin.get("dropped") or []:
            lines.append(f"Left out of this run: gate check {check.get('command')} (check "
                         f"{check.get('n')} of the saved profile), whose tool the lookup "
                         "found the repo never adopted. The saved file is unchanged: fix "
                         f"the saved profile {path} (drop the check, or keep it if the "
                         "repo does use the tool).")
    elif kind == "draft" and origin.get("save_error"):
        lines.append(f"The profile was not saved to {origin.get('save_path')}: "
                     f"{origin['save_error']}. The run uses it anyway. To keep it for this "
                     "repo, save this YAML there yourself (see the permissions guidance in "
                     "references/profiles.md, _Permissions_):")
        text = read_text(Path(artifact_dir) / cmd_init.RUN_PROFILE) or ""
        lines += [f"    {ln}" for ln in text.splitlines()]
    elif kind == "draft":
        lines.append("Using the profile the user confirmed, for this run only (not saved).")
    elif kind == "override":
        lines.append("Using the setup and quality gate the repo's .auto-dev.yml sets.")
    repo = state.get("repo", {})
    if repo.get("adopted"):
        lines.append(f"The run uses the worktree the user made ({state['worktree']}) and its "
                     f"branch {state['branch']}.")
    if repo.get("ahead"):
        lines.append(f"{state['branch']} already holds {repo['ahead']} commit(s) not on the "
                     "base branch; they will be part of the PR.")
    return lines


# ---------------------------------------------------------------- next --repo

class Setup:
    """One `next --repo` call: the one step that sets the run up."""

    def __init__(self, args, repo, task, folder, info):
        self.args, self.repo, self.task = args, repo, task
        self.folder, self.info = folder, info
        self.reissue = bool(getattr(args, "reissue", False))
        self.override = None  # .auto-dev.yml's keys, when it exists and is valid

    def again(self, reissue=False):
        return command("next", "--repo", self.repo, "--task", self.task,
                       *(["--reissue"] if reissue else []))

    def save(self):
        save_info(self.folder, self.info)

    # ------------------------------------------------------------ the step

    def decide(self):
        from .cmd_next import stop
        found = find_run(self.repo, self.task, self.info.get("ticket"))
        if found is not None:
            return self.ready(*found)
        last = self.info["answers"][-1] if self.info["answers"] else None
        if last and last.get("answer") == "stop":
            shutil.rmtree(self.folder, ignore_errors=True)
            return stop([("Setup stopped at the profile question: the user chose Stop. "
                          "Nothing was created (no worktree, branch or run)."),
                         f"To start over, run `{self.again()}`."],
                        "the user stopped setup at the profile question")
        try:
            cmd_init.preflight(self.repo)
        except Fail as exc:
            if exc.code == CANNOT_RUN:
                raise
            return stop([f"Setup can't start: {exc}",
                         f"Nothing was created. Once it is fixed, run `{self.again()}`."],
                        "the preflight failed")
        profile = self.resolve()
        if "code" in profile:
            return profile
        if profile["kind"] == "saved":
            result = self.lookup_step(profile)
        elif profile["kind"] == "research":
            result = self.research_step(profile)
        else:
            result = None
        return result or self.create(profile)

    # ------------------------------------------------------------ the profile

    def read_override(self):
        """Validate .auto-dev.yml when it exists: a stop when it is invalid."""
        from .cmd_next import stop
        path = Path(self.repo) / ".auto-dev.yml"
        if not path.exists():
            return None
        code, lines = validate(path, profile=False)
        if code != 0:
            what = "is invalid" if code == 1 else f"could not be checked (exit {code})"
            return stop([f"{path} {what}:", *lines,
                         f"Nothing was created. Fix it, then run `{self.again()}`."],
                        ".auto-dev.yml is invalid")
        self.override = cmd_init.load_yaml(path)
        if not isinstance(self.override, dict):
            self.override = {}
        return None

    def resolve(self):
        """Which profile the run gets: {kind: saved | research | override, …},
        or a stop. Decided once and kept in setup.json."""
        from .cmd_next import stop
        bad = self.read_override()
        if bad:
            return bad
        profile = self.info.get("profile")
        if profile:
            return profile
        profile = profile_path(self.repo)
        override = self.override or {}
        profile["override_keys"] = sorted(override)
        full = bool(override.get("setup") and override.get("gate"))
        if profile["found"]:
            code, lines = validate(profile["save_path"], profile=True)
            if code == 0:
                profile["kind"] = "saved"
            elif code == 1:
                profile["kind"] = "research"
                profile["saved_errors"] = lines
            else:
                return stop([(f"validate-config.py could not check the saved profile "
                              f"{profile['save_path']} (exit {code}):"), *lines,
                             ("python3 3.9+ and PyYAML are required (`python3 -m pip install "
                              f"pyyaml`). Nothing was created; then run `{self.again()}`.")],
                            "the saved profile could not be checked")
        else:
            profile["kind"] = "override" if full else "research"
        self.info["profile"] = profile
        self.save()
        return profile

    def branches(self):
        return (self.override or {}).get("branches") or {}

    def base(self):
        return self.branches().get("base") or cmd_init.gh_default_branch(self.repo)

    # ------------------------------------------------------------ workers

    def spawns(self, job):
        return [s for s in self.info["spawns"] if s["job"] == job]

    def spawn(self, job, worker, sets, emitted=1, reason="first", rule=""):
        from .cmd_next import spawn_lines
        sets = dict(sets)
        if worker == "profiler":
            n = cmd_work.next_number(self.folder, worker)
            sets["draft_path"] = str(self.folder / f"draft-{n}.yml")
        path, _ = cmd_work.write_brief(None, self.folder, worker, None, dict(sets))
        n = int(path.stem.rsplit("-", 1)[1])
        self.info["spawns"].append({"job": job, "worker": worker, "n": n, "sets": sets,
                                    "emitted": emitted, "reason": reason,
                                    "issued_at": st.now()})
        self.save()
        result = spawn_lines([f"auto-dev:{worker}"], [str(path)], [cmd_work.prompt_for(path)],
                             rule or f"setup needs the {worker}")
        result["ACTION"] = (f"spawn auto-dev:{worker} with the PROMPT, in the foreground (the "
                            "Agent tool's `run_in_background: false`); once it returned, run "
                            "AFTER (it reads the result)")
        result["AFTER"] = [self.again()]
        return result

    def never_returned(self, spawn):
        from .cmd_next import MAX_EMITS, stop
        result_file = self.folder / f"{spawn['worker']}-{spawn['n']}.json"
        return stop([(f"{spawn['worker']} #{spawn['n']} was spawned {MAX_EMITS} times and "
                      f"never left a result file ({result_file}). Tell the user; nothing was "
                      "created."),
                     (f"Once the cause is fixed, run `{self.again(reissue=True)}`: it spawns "
                      f"the {spawn['worker']} again.")],
                    f"the {spawn['worker']} never returned a result")

    def job(self, job, worker, sets, rule=""):
        """(the latest result, None), or (None, the action: spawn, wait or stop)."""
        from .cmd_next import MAX_EMITS, action
        spawns = self.spawns(job)
        if not spawns:
            return None, self.spawn(job, worker, sets, rule=rule)
        latest = spawns[-1]
        data = read_result(self.folder, latest)
        if data is not None:
            return data, None
        if latest.get("stopped"):
            if not self.reissue:
                return None, self.never_returned(latest)
            return None, self.spawn(job, worker, latest["sets"], reason=latest["reason"],
                                    rule="the user asked to spawn it again (--reissue)")
        if not self.reissue and fresh(latest):
            return None, action(
                f"wait: {worker} #{latest['n']} (sent out {latest['issued_at']}) has not "
                "returned yet and may still be running. Spawn nothing; once it has returned, "
                f"run `{self.again()}`. Run `{self.again(reissue=True)}` only once it has "
                "returned without writing its result file, or now if no agent this session "
                "spawned is still out (a new session): it sends the brief out again",
                "a setup brief has no result yet: its worker may still be running")
        if latest.get("emitted", 1) >= MAX_EMITS:
            latest["stopped"] = True
            self.save()
            return None, self.never_returned(latest)
        return None, self.spawn(job, worker, latest["sets"],
                                emitted=latest.get("emitted", 1) + 1, reason=latest["reason"],
                                rule="a setup brief has no result: spawn it again")

    # ------------------------------------------------------------ a saved profile

    def lookup_step(self, profile):
        import yaml
        try:
            gate = (cmd_init.load_yaml(profile["save_path"]) or {}).get("gate") or []
        except (OSError, yaml.YAMLError) as exc:
            raise Fail(f"cannot read the saved profile {profile['save_path']}: {exc}",
                       CANNOT_RUN, "ERROR") from None
        checks = "; ".join(f"check {i}: `{c.get('command')}` ({c.get('kind')})"
                           for i, c in enumerate(gate, 1))
        question = ("for each quality-gate check below, has the repo adopted its tool (a "
                    "declared dependency or a config file)? Answer one line per check, "
                    "exactly `check <n>: adopted — <file:line evidence>` or `check <n>: not "
                    f"adopted — <what you looked for>`. The checks: {checks}")
        data, act = self.job("lookup", "lookup", {"worktree": self.repo, "question": question},
                             rule="a saved profile: ask whether each gate check's tool is "
                                  "adopted")
        if act:
            return act
        dropped = []
        if data.get("status") == "ok" and data.get("next") == "ANSWERED":
            spawn = self.spawns("lookup")[-1]
            dropped = checks_to_drop(gate, read_text(answer_file(self.folder, spawn)) or "")
        profile["dropped"] = [{"n": n, "command": gate[n - 1].get("command")} for n in dropped]
        return None

    # ------------------------------------------------------------ research

    def respawn(self, latest, reason, issues, rule):
        sets = {k: v for k, v in latest["sets"].items() if k != "draft_path"}
        sets["previous_issues"] = issues
        return self.spawn("profiler", "profiler", sets, reason=reason, rule=rule)

    def research_step(self, profile):
        from .cmd_next import stop
        spawns = self.spawns("profiler")
        sets = spawns[-1]["sets"] if spawns else None
        if sets is None:
            base = self.base()
            git(self.repo, "fetch", "origin", base, check=False)
            sets = {"repo": self.repo, "base": base}
        data, act = self.job("profiler", "profiler", sets,
                             rule="no usable profile: the profiler researches one")
        if act:
            return act
        latest = self.spawns("profiler")[-1]
        name = f"profiler #{latest['n']}"
        if data.get("status") != "ok" or data.get("next") != "CONFIRM":
            said = f"status {data.get('status')} {data.get('next') or ''}".rstrip()
            if latest["reason"] == "not-ok":
                return stop([(f"{name} did not return ok twice running ({said}). Tell the "
                              "user what it said above its result block; nothing was created."),
                             (f"Once the cause is fixed, run `{self.again(reissue=True)}`: "
                              "it spawns the profiler again.")],
                            "the profiler did not return ok twice")
            return self.respawn(latest, "not-ok",
                                f"Your last spawn for this job returned {said}. Do the job "
                                "again: write the draft and return status ok with CONFIRM.",
                                "the profiler did not return ok: spawn it again")
        draft = latest["sets"]["draft_path"]
        code, lines = validate(draft, profile=True)
        if code != 0:
            if latest["reason"] == "invalid":
                return stop([f"{name}'s draft {draft} is invalid again; validate-config.py says:",
                             *lines, "Nothing was created. Tell the user.",
                             f"To have the profiler try again, run `{self.again(reissue=True)}`."],
                            "the profiler's draft is invalid twice")
            return self.respawn(latest, "invalid",
                                f"Your draft at {draft} is not a valid saved profile. "
                                "`validate-config.py --profile` says:\n" + "\n".join(lines)
                                + "\nFix each error and write the whole draft again.",
                                "the profiler's draft is invalid: spawn it again once")
        answer = next((a for a in self.info["answers"] if a.get("after") == latest["n"]), None)
        if answer is None:
            return self.question(profile, latest, draft)
        if answer["answer"] == "change":
            return self.respawn(
                latest, "change",
                f"The user reviewed your draft at {draft} and asked for this change: "
                f"{answer.get('text', '')}\nStart from that draft, make this change and "
                "nothing else, and write the result to your draft_path.",
                "the user asked to change the draft: the profiler redoes it")
        profile["draft"] = draft
        profile["answer"] = answer
        return None

    def question(self, profile, latest, draft):
        from .cmd_next import FILL, ask
        summary = []
        if profile.get("saved_errors"):
            summary.append(f"The saved profile at {profile['save_path']} is invalid; "
                           "validate-config.py says:")
            summary += [f"    {ln}" for ln in profile["saved_errors"]]
        report = read_text(answer_file(self.folder, latest))
        if report is None:
            summary.append("The profiler's report is in its reply: show the user its "
                           "QUESTIONS, NOT INSTALLED and EVIDENCE sections.")
        else:
            sections = report_sections(report)
            for name in ("QUESTIONS", "NOT INSTALLED", "NOT ADOPTED", "EVIDENCE"):
                summary += sections.get(name, [])
        summary.append(f"The draft profile ({draft}):")
        summary += [f"    {ln}" for ln in (read_text(draft) or "").splitlines()]
        if profile.get("override_keys"):
            summary.append("Keys the repo's .auto-dev.yml sets, which override this profile: "
                           + ", ".join(profile["override_keys"]))
        if profile.get("save_path"):
            summary.append(f"Save path: {profile['save_path']}")
        else:
            summary.append("This profile can't be saved for this repo "
                           f"({profile.get('no_save') or 'no save path'}): use it for this "
                           "run only, or commit it as the repo's .auto-dev.yml.")
        summary.append("Paths for the permissions guidance: profiles folder "
                       f"{profile.get('profiles_dir') or 'none'}; skill folder {SKILL_DIR}; "
                       f"the run's worktree goes in {Path(self.repo).parent}")
        keys = [k for k in ANSWERS if k != "save" or profile.get("save_path")]
        commands = {k: command("setup-answer", k, "--repo", self.repo, "--task", self.task)
                    for k in keys}
        if "change" in commands:
            commands["change"] = command("setup-answer", "change", "--text", CHANGE_TEXT,
                                         "--repo", self.repo, "--task", self.task)
        question = {"question": ("The profiler drafted how this repo installs its "
                                 "dependencies and which checks define done (above). Use it?"),
                    "header": "Profile", "multiSelect": False,
                    "options": [{"label": OPTIONS[k][0], "description": OPTIONS[k][1]}
                                for k in keys]}
        result = ask(None, "the profile question", summary, [question],
                     [(OPTIONS[k][0], commands[k]) for k in keys],
                     "a researched profile is confirmed by the user")
        result["ACTION"] = (
            "show the user SUMMARY, with the permissions guidance from "
            "references/profiles.md, _Permissions_, filled in with SUMMARY's paths and the "
            "draft's commands; then ask QUESTION with AskUserQuestion and run the AFTER line "
            f"for their answer ({FILL}); then run `{self.again()}`")
        return result

    # ------------------------------------------------------------ the run

    def origin(self, profile):
        kind = profile["kind"]
        if kind == "saved":
            return {"kind": "saved", "path": profile["save_path"],
                    "dropped": profile.get("dropped") or []}
        if kind == "override":
            return {"kind": "override"}
        answer = profile.get("answer") or {}
        if answer.get("answer") == "save" and not answer.get("save_error"):
            return {"kind": "saved", "path": answer.get("save_path"), "dropped": [],
                    "saved_now": True}
        record = {"kind": "draft"}
        if answer.get("answer") == "save":
            record.update(save_error=answer["save_error"], save_path=answer.get("save_path"))
        return record

    def profile_args(self, profile):
        """--profile and --profile-source for init, and the --note lines."""
        if profile["kind"] == "override":
            return [], []
        if profile["kind"] == "research":
            return ["--profile", profile["draft"], "--profile-source",
                    "researched by the profiler, confirmed by the user"], []
        saved, dropped = profile["save_path"], profile.get("dropped") or []
        if not dropped:
            return ["--profile", saved, "--profile-source", f"saved profile {saved}"], []
        data = cmd_init.load_yaml(saved)
        gone = {d["n"] for d in dropped}
        data["gate"] = [c for i, c in enumerate(data.get("gate") or [], 1) if i not in gone]
        filtered = self.folder / "profile.yml"
        dump_yaml(data, filtered)
        commands = [d["command"] for d in dropped]
        notes = [f"dropped gate check {cmd}: the repo never adopted its tool (saved profile "
                 f"{saved})" for cmd in commands]
        return ["--profile", filtered, "--profile-source",
                f"saved profile {saved}, without {', '.join(commands)}"], notes

    def create(self, profile):
        from .cmd_next import stop
        prefix = self.branches().get("prefix") or "feat"
        info = self.info
        ticket_text = read_text(self.folder / "ticket.txt") if info.get("ticket_text") else ""
        slug = free_slug(self.repo, derive_slug(self.task, info.get("ticket"), ticket_text),
                         prefix)
        origin_file = self.folder / "origin.json"
        origin_file.write_text(json.dumps(self.origin(profile)), encoding="utf-8")
        profile_args, notes = self.profile_args(profile)
        cmd = [sys.executable, str(AUTODEV), "init", "--repo", self.repo, "--slug", slug,
               "--task", self.task, "--prefix", prefix]
        for flag, key in (("--ticket", "ticket"), ("--ticket-url", "ticket_url"),
                          ("--jira", "jira")):
            if info.get(key):
                cmd += [flag, info[key]]
        if ticket_text:
            cmd += ["--ticket-text-file", self.folder / "ticket.txt"]
        cmd += [*profile_args, "--profile-origin", origin_file]
        for note in notes:
            cmd += ["--note", note]
        cmd += ["--max-wait", str(max(int(self.args.max_wait), 0)), "--json"]
        code, out, err = run([str(w) for w in cmd], check=False)
        message = init_message(out, err)
        found = find_run(self.repo, self.task, info.get("ticket"))
        if code in (0, 3) and found is not None:
            return self.ready(*found, running=code == 3)
        if code == 2 or (found is None and code in (0, 3)):
            raise Fail(f"autodev.py init could not run (exit {code}): {message}", CANNOT_RUN,
                       "ERROR")
        if found is None:
            return stop([f"Setup stopped before the run was created: {message}",
                         f"Nothing was created. Once the cause is fixed, run `{self.again()}`."],
                        "init stopped")
        tree, state = found
        source = cmd_init.setup_source(Path(tree) / ".auto-dev", state)
        return stop([f"Setup failed: {message}",
                     (f"The run is kept in {tree}. Fix the setup in {source}, then say "
                      "`auto-dev continue`: `next` runs setup again from that file.")],
                    "Phase 1's setup failed")

    def ready(self, tree, state, running=False):
        from .cmd_next import action
        ad = Path(tree) / ".auto-dev"
        summary = origin_summary(ad, state)
        if running:
            summary.append("Setup is still running; `next --dir` waits for it.")
        if st.phase(state, 1)["status"] == "done":
            remove_scratch(self.repo, self.task)
        return action(f"tell the user the SUMMARY lines; then move into the run's worktree "
                      f"{tree} (`cd {q(tree)}`): every later step runs there. Then run AFTER",
                      "the run for this task exists", SUMMARY=summary,
                      AFTER=[command("next", "--dir", ad)])


def init_message(out, err):
    try:
        data = json.loads(out)
        if isinstance(data, dict) and data.get("message"):
            return str(data["message"])
    except ValueError:
        pass
    return (err or out).strip()


def run_setup(args):
    """`next --repo <repo> --task <task>`: the one step that sets the run up."""
    if getattr(args, "explain", False):
        raise Fail("--explain needs a run (--dir): `next --repo` writes as it decides",
                   CANNOT_RUN, "ERROR")
    task = (args.task or "").strip()
    if not task:
        raise Fail("--repo needs --task \"<task>\"", CANNOT_RUN, "ERROR")
    ticket_text = cmd_init.read_ticket_text(args.ticket_text_file)
    repo = cmd_init.repo_root(args.repo)
    folder = open_scratch(repo, task)
    info = load_info(folder)
    for key in ("ticket", "ticket_url", "jira"):
        value = getattr(args, key, None)
        if value:
            info[key] = value
    if ticket_text:
        (folder / "ticket.txt").write_text(ticket_text, encoding="utf-8")
        info["ticket_text"] = True
    save_info(folder, info)
    return Setup(args, repo, task, folder, info).decide()


# ---------------------------------------------------------------- next --dir

def retry_profile(artifact_dir, state):
    """The --profile `init --continue` re-reads after a failed setup, from the
    run's own record of where its profile came from (never the scratch
    folder), or None to keep the run's setup and gate (and .auto-dev.yml)."""
    artifact_dir = Path(artifact_dir)
    retry = artifact_dir / "profile-retry.yml"
    origin = read_origin(artifact_dir)
    if origin is None:  # a run made without one (5.0, or init called directly)
        found = profile_path(state["repo"]["main_checkout"])
        if not found["found"] or validate(found["save_path"], profile=True)[0] != 0:
            return None
        data = cmd_init.load_yaml(found["save_path"])
        # Its dropped checks were never recorded: keep the run's own gate.
        data["gate"] = state["settings"].get("gate", [])
        dump_yaml(data, retry)
        return retry
    kind = origin.get("kind")
    if kind == "draft":
        return artifact_dir / cmd_init.RUN_PROFILE
    if kind != "saved" or not origin.get("path"):
        return None
    path = origin["path"]
    dropped = {d.get("command") for d in origin.get("dropped") or []}
    if not dropped:
        return path
    try:
        data = cmd_init.load_yaml(path)
    except Exception:  # init reports the validator's errors
        return path
    if not isinstance(data, dict) or not isinstance(data.get("gate"), list):
        return path
    data["gate"] = [c for c in data["gate"]
                    if not (isinstance(c, dict) and c.get("command") in dropped)]
    dump_yaml(data, retry)
    return retry


def finish_run(artifact_dir, state, max_wait):
    """Run `init --continue` for a run whose setup is not done: wait on it, or
    (after a failed setup) run it again. (exit code, init's message)."""
    cmd = [sys.executable, str(AUTODEV), "init", "--continue", state["worktree"],
           "--max-wait", str(max(int(max_wait), 0)), "--json"]
    if state["init"].get("setup") == "failed":
        profile = retry_profile(artifact_dir, state)
        if profile is not None:
            cmd += ["--profile", str(profile)]
    code, out, err = run(cmd, check=False)
    return code, init_message(out, err)


# ---------------------------------------------------------------- setup-answer

def open_question(folder, info):
    """(profiler n, draft) when a valid draft awaits an answer, else None."""
    spawns = [s for s in info["spawns"] if s["job"] == "profiler"]
    if not spawns:
        return None
    latest = spawns[-1]
    data = read_result(folder, latest)
    if not data or data.get("status") != "ok" or data.get("next") != "CONFIRM":
        return None
    if any(a.get("after") == latest["n"] for a in info["answers"]):
        return None
    draft = latest["sets"].get("draft_path")
    if not draft or validate(draft, profile=True)[0] != 0:
        return None
    return latest["n"], draft


def save_profile(repo, draft):
    """Write the draft to the repo's saved-profile path; (path, error)."""
    found = profile_path(repo)
    path = found["save_path"]
    if not path:
        raise Fail(f"this repo's profile can't be saved ({found.get('no_save')}); answer "
                   "run-only instead", FAILED, "REFUSED")
    root = found.get("profiles_dir")
    try:
        name = Path(path).relative_to(root).with_suffix("").as_posix() if root else Path(path).stem
    except ValueError:
        name = Path(path).stem
    header = f"# auto-dev profile for {name}, saved {datetime.now().date().isoformat()}\n"
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(header + Path(draft).read_text(encoding="utf-8"),
                              encoding="utf-8")
    except OSError as exc:
        return path, str(exc)
    code, lines = validate(path, profile=True)
    if code != 0:
        return path, "validate-config.py says: " + " ".join(lines)
    return path, None


def answer(args):
    task = (args.task or "").strip()
    if not task:
        raise Fail("--task is required", CANNOT_RUN, "ERROR")
    text = (args.text or "").strip()
    if args.choice == "change" and not text:
        raise Fail("change needs --text \"<what the user wants changed>\"", CANNOT_RUN,
                   "ERROR")
    repo = cmd_init.repo_root(args.repo)
    folder = existing_scratch(repo, task)
    info = load_info(folder) if folder else None
    found = open_question(folder, info) if info else None
    if found is None:
        raise Fail("no profile question is open for this task (no researched profile awaits "
                   "an answer); run `next --repo … --task …` and answer the question it asks",
                   FAILED, "REFUSED")
    n, draft = found
    entry = {"answer": args.choice, "text": text, "after": n, "at": st.now()}
    if args.choice == "save":
        path, error = save_profile(repo, draft)
        entry["save_path"] = path
        if error:
            entry["save_error"] = error
    info["answers"].append(entry)
    save_info(folder, info)
    emit(args.json, "RECORDED", args.choice, saved=entry.get("save_path") if
         args.choice == "save" and not entry.get("save_error") else None,
         not_saved=entry.get("save_error"))
    return 0

