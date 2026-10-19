"""Match the task the user names against a run's recorded task.

A Jira key (it matches `^[A-Z][A-Z0-9_]+-\\d+$`, ignoring case) must appear as
a whole token in the key/link part of the Ticket line (before the first ` — `),
unless that part is a bare "none", when the restated ask's keys count. A Jira
issue URL matches by its key. Any other text is compared word by word, ignoring
case, punctuation and markdown, against the Task line and the restated ask: it
matches when it is that line, or the line with a few words left out (at least
80% kept, in order, no negation dropped). When one side's words all appear in
the other but that is not a match, the answer is NEAR_MISS: possibly the same
task worded differently, for the user to confirm.
"""

import re

# How many of the Task line's (or restated ask's) words free --task text keeps.
MIN_COVERAGE = 0.8
# Words an abbreviation may never drop: without them the line means the opposite.
NEGATIONS = {"not", "no", "never", "without", "dont", "doesnt", "isnt", "except",
             "nor"}
# task_matches()'s third answer: not a match, but the words overlap wholly.
NEAR_MISS = "near-miss"
# Free text is compared as words: runs of letters and digits, case folded.
WORD_RE = re.compile(r"[a-z0-9]+")
# Apostrophes are dropped first, so `isn't` and `isnt` are the same word.
APOSTROPHE_RE = re.compile("['\u2019]")
# A bare Jira key passed to --task (e.g. PROJ-123); matched as a whole token.
JIRA_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]+-\d+$", re.IGNORECASE)
# What separates tokens on the Ticket line: anything that can't be in a key,
# so `PROJ-123` is a token in `PROJ-123`, `…/browse/PROJ-123` and `[PROJ-123]`.
TOKEN_SPLIT_RE = re.compile(r"[^A-Za-z0-9_-]+")
# What ends the Ticket line's key/link part and starts the restated ask: the
# template's ` — `, tolerating extra whitespace. Not an en dash: one can sit
# inside a link title (`[Login – broken](…/browse/PROJ-12)`).
TICKET_ASK_SEP_RE = re.compile(r"\s+—\s+")
# A Jira issue URL passed to --task (`…/browse/PROJ-123`); its key is matched.
BROWSE_KEY_RE = re.compile(r"/browse/([A-Za-z][A-Za-z0-9_]+-\d+)(?:[^A-Za-z0-9_-]|$)")


def words(text):
    return WORD_RE.findall(APOSTROPHE_RE.sub("", text.lower()))


def task_matches(wanted, fields):
    """True if the --task value names this ledger's task (see the docstring),
    NEAR_MISS if it may be the same task worded differently, else False."""
    wanted = wanted.strip()
    ticket = fields["Ticket"]
    sep = TICKET_ASK_SEP_RE.search(ticket)
    head, ask = (ticket[:sep.start()], ticket[sep.end():]) if sep else (ticket, "")
    url_key = BROWSE_KEY_RE.search(wanted)
    if url_key:  # a Jira issue URL matches as its key, never as a substring
        wanted = url_key.group(1)
    if JIRA_KEY_RE.match(wanted):
        # Only the key/link part counts: a key the restated ask mentions
        # (`— follow-up to PROJ-11`) is not this ledger's ticket. Strip `_`
        # from token ends so a markdown-italic `_PROJ-12_` still counts.
        # With no ticket (`none — JIRA-1234 (Jira unreadable)…`) the ask is
        # where a key could be, so its tokens count instead.
        keyed = ask if head.strip().lower() == "none" else head
        tokens = {t.strip("_") for t in TOKEN_SPLIT_RE.split(keyed.lower())}
        return wanted.lower() in tokens
    wanted = words(wanted)
    if not wanted:
        return False
    # Free text matches the Task line or the ask the Ticket line restates
    # (after ` — `) — never the key, link or a bare "none" before it.
    lines = [have for have in (words(fields["Task"]), words(ask)) if have]
    if any(abbreviates(wanted, have) for have in lines):
        return True
    # Not the same task as far as the words go, but one side's words all appear
    # in the other: a fragment, or a longer request that contains the line.
    if any(set(wanted) <= set(have) or set(have) <= set(wanted)
           for have in lines):
        return NEAR_MISS
    return False


def abbreviates(wanted, have):
    """Whether `wanted` is `have`, or `have` with a few words left out.

    The kept words must appear in order, cover at least MIN_COVERAGE of
    `have`, and the dropped ones must include no negation. A longer request
    that merely contains the line, or a fragment, is not it.
    """
    if len(wanted) < MIN_COVERAGE * len(have):
        return False
    dropped, i = [], 0
    for word in have:
        if i < len(wanted) and wanted[i] == word:
            i += 1
        else:
            dropped.append(word)
    return i == len(wanted) and not NEGATIONS & set(dropped)


# `- **Repo:** x   **Base:** y` holds several fields on one ledger line.
FIELD_RE = re.compile(r"\*\*([^*]+?):\*\*\s*(.*?)(?=\s+\*\*[^*]+?:\*\*|$)")
