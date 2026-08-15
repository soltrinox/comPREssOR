# Publishing checklist (Open VSX only)

Identity: GitHub `soltrinox/comPREssOR`, Open VSX namespace/publisher `soltrinox`, extension id `soltrinox.compressor`.

**Until Open VSX publish completes,** end users install by sideloading a VSIX
built from this repo — not via Extensions gallery search. Step-by-step:
[PREFLIGHT.md](PREFLIGHT.md) and the README Install section.

## Human blockers (Phase 9)

Complete these before the first **gallery** release (Open VSX listing):

1. **Create GitHub repo** `soltrinox/comPREssOR` (if missing) and grant push credentials.
2. **Claim Open VSX namespace** `soltrinox`:
   - Sign the Eclipse Foundation Open VSX Publisher Agreement
   - `npx ovsx create-namespace soltrinox`
3. **Store secrets** on the GitHub repo (optional until gallery publish):
   - `OVSX_TOKEN` — Open VSX personal access token. When unset, `release.yml`
     **skips** `ovsx publish` with `[SKIP]` and exits 0; GitHub Release VSIX
     sideload remains the primary path and CI stays green.
4. **Authorize** a human to run the first push + tag (agents must not push or `ovsx publish` without prior authorization and a present token).

## Ready-for-human publish sequence

```bash
# From a clean main with CI green:
git remote add origin git@github.com:soltrinox/comPREssOR.git   # once
git push -u origin main
git tag v0.1.0
git push origin v0.1.0
# release.yml always builds the VSIX and attaches it to the GitHub Release.
# If OVSX_TOKEN is set, it also runs:
#   npx ovsx publish *.vsix -p $OVSX_TOKEN
# If OVSX_TOKEN is missing, Open VSX publish is skipped (exit 0); use the
# Release VSIX for sideload until the namespace/token are ready.
```

## Verify after publish

Only after `ovsx publish` succeeds (listing is not available before that):

1. Open VSX listing: `https://open-vsx.org/extension/soltrinox/compressor`
2. In Cursor → Extensions, search **comPREssOR** / `soltrinox.compressor`
3. Fresh install: Compatibility Report ALLOW, hooks merge (V-01 / V-08 / V-10)

Until then, verify via VSIX sideload per [PREFLIGHT.md](PREFLIGHT.md).

## Hard rules

- **Never** `vsce publish` to Microsoft Marketplace (`assert-cursor-target.mjs` blocks it)
- Never commit `.env`, absolute home paths, `runs/`, `test-results/`, or imported fixtures
