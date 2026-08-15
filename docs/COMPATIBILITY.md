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

## Marketplace

Publish target is **Open VSX only**. Microsoft Marketplace publish is blocked at build time.
