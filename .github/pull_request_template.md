<!-- Title: "<type>: <summary>" (see CLAUDE.md, Branches, commits and PRs).
This PR will be squash-merged, so the title becomes the commit on main. -->

## Summary

<!-- What changes and why, in plain sentences. For a release, name the version
(e.g. "3.4 → 3.5") and say whether a run in flight can resume on it. -->

## Testing

<!-- What you ran and what you saw. At least: ruff check ., python3
tools/check-repo.py, python3 -m unittest discover -s tests. For a script change,
the before/after on a case that shows the fix. Say what was NOT tested (e.g.
the eval suite end to end). -->

## Docs

- [ ] README.md updated for any behavior change (checklist in CLAUDE.md), or not needed because: …
- [ ] Version bumped and an *Upgrading* note added, if artifacts or resuming changed
- [ ] Evals updated, if the expected behavior changed

## Not included

<!-- Anything deliberately left for later. Delete if none. -->
