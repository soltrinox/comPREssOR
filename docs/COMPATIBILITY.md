# Compatibility policy

## Allow

Local Cursor desktop where:

- `vscode.env.uriScheme === "cursor"`
- `vscode.env.appName` contains `Cursor`
- `vscode.env.appHost === "desktop"`
- `vscode.env.remoteName` is empty / undefined

## Deny (fail-closed)

Any other host (VS Code stable/Insiders, VSCodium, Remote-SSH, web, etc.). On deny:

1. Set context `chatCompressor.hostSupported` = `false`
2. Log every host signal
3. Show a once-per-fingerprint warning with **Uninstall** and **Details**
4. Perform **no** writes under `~/.cursor/`

`chatCompressor.strictHostGate: false` may downgrade the warning UI only. It never enables hook/runtime writes (REQ-CFG-02).

## Sideload gap (REQ-HOST-06)

Nothing in the VSIX format prevents installation into VS Code. Activation refuses side effects. Stated in the README and gallery description.

## Marketplace / install

**Install today:** sideload a VSIX (build with `cd extension && npm run package`,
then Cursor **Extensions: Install from VSIX**). See [PREFLIGHT.md](PREFLIGHT.md).

**Publish target (when ready):** **Open VSX only**. Microsoft Marketplace publish
is blocked at build time. The Open VSX listing is **pending** (namespace claim /
human publish); do not treat gallery search as the current default install path.
