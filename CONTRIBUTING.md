# Contributing

## Ground rules

**Never commit session data.** `state/`, `runs/`, `test-results/`,
`fixtures/imported/`, and `.env` are excluded by `.gitignore` because they hold
real transcript content and, in the case of `.env`, live credentials. Do not
add exceptions, do not `git add -f` them, and do not paste their contents into an
issue or a pull request.

**Never commit an absolute path from a developer machine.** Use `$HOME`,
`os.homedir()`, or a repository-relative path. CI fails the build on any
occurrence of an absolute home-directory path prefix, a personal gmail
domain, or a Cursor API key assignment line. You can run the same check locally:

```bash
node extension/build/scrub-check.mjs
```

**Fixtures must be synthetic.** `engine/fixtures/synthetic-generic.jsonl` is
generated, not captured. Any new fixture must be too.

## Layout

- `engine/` — the Python engine, published as a wheel and installed into a
  virtual environment the extension provisions.
- `extension/` — the Cursor extension (TypeScript), packaged as a VSIX.
- `docs/` — architecture, hook contract, and the host compatibility facts that
  the activation gate asserts against.

## Development

Engine:

```bash
cd engine
python3 -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
python -m pytest tests
```

Python 3.11 is the floor. Tests must pass on 3.11 and 3.12.

Extension:

```bash
cd extension
npm install
npm run compile
npm test
npx vsce package
```

## Host policy

The extension targets Cursor and only Cursor. Two rules follow, and a pull
request that weakens either will be rejected:

1. `detectHost()` runs as the first statement of `activate()`, and a denied host
   results in no filesystem writes of any kind. The `strictHostGate` setting can
   only downgrade the severity of the warning; it can never enable writes.
2. The publish target is Open VSX. `vsce publish` to the Microsoft Marketplace is
   prohibited and the build asserts against it.

If you change any literal the gate compares against, update
[docs/COMPATIBILITY.md](docs/COMPATIBILITY.md) in the same pull request with the
observed value and its source, and say how you observed it.

## Changes that touch the user's machine

The extension writes to a small, fixed set of paths under `$HOME/.cursor`. Any
change to that set needs to state, in the pull request description, what is
written, whether an existing file is modified in place, and what uninstall does
with it.

`hooks.json` edits are merge-only: drop exactly the entries whose command
references this project, preserve everything else, write through a temporary file
and rename, and take a timestamped backup on first modification. A pull request
that rewrites `hooks.json` wholesale will be rejected.

Hooks stay fail-open. If the engine, the interpreter, or the state directory is
unavailable, the shim exits successfully and the user's turn proceeds without
injected context.

## Pull requests

- One concern per pull request.
- Include the evidence: the command you ran and its output, not an assertion that
  it works.
- Update `CHANGELOG.md` under `Unreleased` for any user-visible change.
- Update the docs in the same pull request when behaviour changes.

## Licence

Contributions are accepted under Apache-2.0, matching [LICENSE](LICENSE).
