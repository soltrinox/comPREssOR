# CC-9 fail-open proof

From `engine/tests/test_cc9_advisory.py`:

1. **Missing file** — `_load_advisory_context_line` returns None; `beforeSubmitPrompt` still returns `continue: true`.
2. **Stale `expires_at`** — ignored; no `COMPASS_ADVISORY:` line; `continue: true`.
3. **Corrupt JSON** — ignored; no advisory line; `continue: true`.
4. **Fresh file** — `COMPASS_ADVISORY:` appears in `additional_context`.
