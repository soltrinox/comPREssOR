# Architecture Index

This page is the short navigation entry for comPREssOR architecture and release
docs.

## Start Here

- [PERFORMANCE.md](PERFORMANCE.md): 199-prompt inject corpus, manuscript card
  sequence, locked numerals, honesty lines, and the two-probe table.
- [WHY.md](WHY.md): explains why bounded forward context can be preferable to
  raw transcript replay, the lab/live SDK probe, and where the evidence stops.
- [SYSTEM.md](SYSTEM.md): explains the implemented system: host gate, runtime
  provisioning, env file projection, shim install, hook merge, local state,
  settings, utilization patterns, debugging, and non-goals.

## Reference Docs

- [HOOK_CONTRACT.md](HOOK_CONTRACT.md): Cursor hook events, fail-open defaults,
  env keys, and merge policy.
- [PREFLIGHT.md](PREFLIGHT.md): host facts, current VSIX sideload install path,
  and Open VSX pending status.
- [COMPATIBILITY.md](COMPATIBILITY.md): Cursor-only host gate, unsupported-host
  behavior, sideload boundary, and Open VSX policy.
- [PUBLISHING.md](PUBLISHING.md): human publishing checklist for Open VSX
  (gallery not yet the default install path).

## Repo Shape

comPREssOR is a monorepo with a Cursor extension and a vendored Python engine:

- `extension/`: TypeScript extension that gates activation, provisions runtime,
  installs hooks, and deploys Cursor rule/skill assets.
- `engine/`: Python package and hook CLI that maintains local compressed state
  and assembles bounded forward context.
- `docs/`: public documentation for measurement, theory, system behavior,
  compatibility, hook contracts, and publishing. Manuscript savings cards live
  under `docs/assets/`.
