# Phase 0 Preflight — Host and Gallery Facts

Captured on the build machine against **Cursor 2.app** (product version `3.2.16`, quality `stable`).

## Current install path (primary)

**Open VSX listing is pending.** Until the `soltrinox` namespace is claimed and the
extension is published, most users install by **sideloading a VSIX** into Cursor.
Do not treat Extensions search / Open VSX as the default install path yet.

### Download a release VSIX (recommended)

Public GitHub Releases ship a ready-to-sideload asset:

- Latest: https://github.com/soltrinox/comPREssOR/releases/latest
- v0.1.3: https://github.com/soltrinox/comPREssOR/releases/tag/v0.1.3 — asset `compressor-0.1.3.vsix`

### Build a VSIX from this repo

Alternatively, package from source:

```bash
cd extension && npm ci && npm run package
```

That runs `vsce package` (via the `package` script) and writes
`compressor-*.vsix` under `extension/`.

### Install in Cursor

1. Open **Extensions**.
2. Open the view menu (**⋯**) → **Install from VSIX…**  
   Or Command Palette: **Extensions: Install from VSIX**.
3. Choose the downloaded or locally built `.vsix`.
4. Reload when Cursor prompts.

### First activation

On an allowlisted Cursor desktop host:

- Python **3.11+** must be discoverable (or set `chatCompressor.pythonPath`).
- The extension provisions a private venv, writes the env file, installs the
  hook shim, merges hook entries, and deploys its user rule and skill.
- Non-Cursor hosts may accept the VSIX, but the host gate refuses side effects
  and writes nothing under the Cursor data directory.

Deeper detail: [SYSTEM.md](SYSTEM.md) (lifecycle, settings, hooks) and
[COMPATIBILITY.md](COMPATIBILITY.md) (host gate, sideload boundary). Publishing
when Open VSX is ready: [PUBLISHING.md](PUBLISHING.md).

## Bundled VS Code API

| Signal | Value | Source |
|--------|-------|--------|
| `product.json` `vscodeVersion` | `1.105.1` | Cursor app `product.json` |
| Draft `engines.vscode` | `^1.93.0` | At or below bundled API (plan default retained) |

## Host identity signals (REQ-HOST-01)

Literal values asserted by `detectHost()` (not guessed):

| Signal | Expected allow value | Source |
|--------|----------------------|--------|
| `vscode.env.uriScheme` | `cursor` | `product.json` `urlProtocol` |
| `vscode.env.appName` | contains `Cursor` | `product.json` `nameLong` / `nameShort` = `Cursor` |
| `vscode.env.appHost` | `desktop` (local UI) | Cursor desktop host; Remote-SSH is deny |
| `vscode.env.remoteName` | empty / undefined | Local only; any set remote name is deny |

Additional product facts (informational):

| Field | Value |
|-------|-------|
| `applicationName` | `cursor` |
| `dataFolderName` | `.cursor` |
| `darwinBundleIdentifier` | `com.todesktop.230313mzl4w4u92` |
| Cursor app `version` | `3.2.16` |

Extension-host verification: run **comPREssOR: Compatibility Report** after install; the output channel logs the live `uriScheme`, `appName`, `appHost`, and `remoteName`.

## Extension gallery / Open VSX (pending)

- Cursor's extension panel resolves third-party packages from **Open VSX**. There
  is no Microsoft Marketplace submission for this Cursor-only extension.
- **Status:** listing and namespace claim are **not yet** the install path for most
  users. Sideload a VSIX (above) until publish completes.
- Intended publish path (when ready): **Open VSX only** (`ovsx publish`).
  Microsoft Marketplace publish is blocked by `assert-cursor-target.mjs`
  (REQ-HOST-05).
- Namespace: `soltrinox` (human action: Eclipse Open VSX Publisher Agreement +
  `ovsx create-namespace soltrinox`).

## CI push / validate loop

To push `main` and wait for GitHub Actions with a bounded retry (max 5), use the
pattern-discoverable script:

```bash
./scripts/verify-ci-push-loop.sh
# help / dry-run (no push):
./scripts/verify-ci-push-loop.sh --help
./scripts/verify-ci-push-loop.sh --dry-run --skip-local-build
```

It mirrors critical steps from `.github/workflows/ci.yml` locally, pushes without
`--force`, watches the `CI` workflow for that SHA, and captures failed logs under
`test-results/ci-loop/`. It only auto-applies a small table of known fixes when
you pass `--auto-commit-fixes`; otherwise it fail-closes with logs for an agent
or human (`--agent-hint` prints a ready prompt).

## License decision

- **Apache-2.0** for the public repo and VSIX.
- Whitepaper PDF / lab `PROOF.md` / personal transcript fixtures are **not** shipped publicly (excluded from allowlist and `.gitignore`).

## Open VSX namespace claim (human latency)

Status: **pending human**. Required before gallery install works:

1. Sign the Eclipse Foundation Open VSX Publisher Agreement at https://open-vsx.org/
2. Authenticate and run `ovsx create-namespace soltrinox`
3. Store `OVSX_TOKEN` as a GitHub Actions secret on `soltrinox/comPREssOR`

See `docs/PUBLISHING.md`.
