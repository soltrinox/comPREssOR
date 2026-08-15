# Security policy

## Reporting a vulnerability

Report suspected vulnerabilities privately through GitHub Security Advisories:

<https://github.com/soltrinox/comPREssOR/security/advisories/new>

Do not open a public issue for a suspected vulnerability.

Please include the extension version, the Cursor version, your operating system,
and the smallest reproduction you can produce. If the report involves data that
was captured from a real session, redact it before sending — see "Do not send us
session data" below.

Expect an acknowledgement within 5 business days and an assessment within 15.
Fixes ship as a patch release to Open VSX, with the advisory published once a
release is available.

## Scope

In scope:

- The activation-time host gate and any path by which a non-Cursor host could
  cause the extension to write to the filesystem.
- The `hooks.json` merge: any input that could cause the extension to drop,
  corrupt, or duplicate hook entries it does not own.
- The environment-file projection: any path by which a secret could be written
  into `$HOME/.cursor/chat-compressor.env`.
- The uninstall path: any path by which uninstall could delete files outside the
  set it manages.
- The engine's handling of untrusted transcript content, including path traversal
  through anything derived from a session payload.

Out of scope:

- Vulnerabilities in Cursor itself. Report those to Anysphere.
- The quality, relevance, or correctness of the context the compressor selects.
  That is a functional issue, not a security issue.
- Sideloading the VSIX into VS Code. The extension installs and then refuses to
  activate; this is documented behaviour, not a vulnerability. See the README.

## Data handling

The extension and the engine operate entirely on the local machine. State is
written under `$HOME/.cursor/context-graphs/`. Nothing is transmitted to a remote
service by this project. The only network access in normal operation is the
package download performed once when provisioning the Python environment.

`CURSOR_API_KEY` is never read by the engine and never written by the extension
into any file it manages.

## Do not send us session data

Compressed state and captured runs can contain the full content of your working
sessions, including source code, file paths, and anything you pasted into a chat.
When reporting a bug or a vulnerability, send the log output and a synthetic
reproduction, not the contents of `$HOME/.cursor/context-graphs/`.

The repository's `.gitignore` excludes `state/`, `runs/`, `test-results/`, and
`fixtures/imported/` for the same reason. Do not defeat those exclusions in a
pull request.
