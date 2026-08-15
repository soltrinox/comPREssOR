# Phase 0 Preflight — Host and Gallery Facts

Captured on the build machine against **Cursor 2.app** (product version `3.2.16`, quality `stable`).

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

## Extension gallery / Open VSX

- Cursor's extension panel resolves packages from **Open VSX** (Open VSX is the gallery source for third-party Cursor extensions; there is no separate Microsoft Marketplace submission for this Cursor-only extension).
- Publish path: **Open VSX only** (`ovsx publish`). Microsoft Marketplace publish is blocked by `assert-cursor-target.mjs` (REQ-HOST-05).
- Namespace: `soltrinox` (human action: Eclipse Open VSX Publisher Agreement + `ovsx create-namespace soltrinox`).

## License decision

- **Apache-2.0** for the public repo and VSIX.
- Whitepaper PDF / lab `PROOF.md` / personal transcript fixtures are **not** shipped publicly (excluded from allowlist and `.gitignore`).

## Open VSX namespace claim (human latency)

Status: **pending human**. Start before Phase 9:

1. Sign the Eclipse Foundation Open VSX Publisher Agreement at https://open-vsx.org/
2. Authenticate and run `ovsx create-namespace soltrinox`
3. Store `OVSX_TOKEN` as a GitHub Actions secret on `soltrinox/comPREssOR`

See `docs/PUBLISHING.md`.
