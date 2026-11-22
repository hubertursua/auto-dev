<!-- auto-dev template: lint.md (strict). Copy everything below this comment, filling in every <...>. -->
# <CHECK> — <pass | fail | skipped>

- **Command:** `<the exact command from profile.md, run verbatim, or its scoped form as run>`
- **Final status:** <pass | fail | skipped>
- **Scope:** <whole | the change's tests (<k> files); CI runs the whole check | not run: <why>; CI runs it>
- **Runs:** <n>
- **Tree:** <hash from check-fresh.py --print-tree, once every check's final run is done>

## Fixed to get here
- `path:line` — <what the check flagged, and the change that cleared it>

## Output tail (final run)
<the last lines of output, fenced>

**Suppressions:** <none | the narrowest suppression applied, and why it was needed>
