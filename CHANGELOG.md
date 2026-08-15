# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-08-14

Public release consolidating the 0.1.x lineage into a sideload-first install path.

### Added

- README hero metrics and comparison table for the 199-prompt inject corpus
  (scoped inject-path `chars/4` claims; not a Cursor billing export).
- [docs/PERFORMANCE.md](docs/PERFORMANCE.md) and manuscript savings cards under
  [docs/assets/](docs/assets/).
- `scripts/verify-ci-push-loop.sh` — bounded local-build → push → GitHub CI watch
  loop for release readiness.

### Changed

- Extension / engine package stamp aligned to **0.2.0** (`extension/package.json`,
  `engine/pyproject.toml`, `hook_cli` fallback `build_stamp`).
- Fork-merged engine lineage (0.1.3+): scrub-safe `HOME_RE`, query-aware ranking,
  design/outcome extractors alongside M3–M6, `chunks.py` pool=`merged_body`.
- Primary install path: **GitHub Release VSIX sideload** while Open VSX listing
  is pending (`docs/PREFLIGHT.md`, README Install, `docs/PUBLISHING.md`).
- `release.yml`: missing `OVSX_TOKEN` soft-skips Open VSX publish with `[SKIP]`
  and exit 0 (CI stays green; sideload remains primary).
- Scrub gate allowlists public hostnames (`rosariocyber.com`, `eni6ma.com`) so
  lab URLs pass without a blanket username exception.
- README Elsewhere: public lab link [`RosarioCyber.com`](https://rosariocyber.com).

## [0.1.4] - 2026-08-14

### Changed

- Extension / engine package stamp aligned to **0.1.4** (`extension/package.json`,
  `engine/pyproject.toml`, `hook_cli` fallback `build_stamp`).
- README Elsewhere: restore public lab link [`RosarioCyber.com`](https://rosariocyber.com).
- Scrub gate (`extension/build/scrub-check.mjs`): allowlist public hostnames
  (`rosariocyber.com`, `eni6ma.com`) so lab URLs pass without a blanket username
  exception.
- Install docs: VSIX sideload remains the primary path while Open VSX listing is
  pending (`docs/PREFLIGHT.md`, README Install, `docs/COMPATIBILITY.md`,
  `docs/PUBLISHING.md`). No false “available on Open VSX now.”

### Added

- README comparison table vs other prompt continuity approaches (claims-gated:
  measured arms only for scores; last-N / summary / RAG as mechanism rows).
- README hero metrics for the 199-prompt inject corpus (scoped “about one sixth”
  / 84% fewer forwarded; not a Cursor billing export).
- README / PERFORMANCE ratio illustration: ~18¢ on the replay dollar (~6× as far
  for the same inject budget) — inject-path token volume only, not a billing export.
- [docs/PERFORMANCE.md](docs/PERFORMANCE.md) — card sequence, locked numerals,
  honesty lines, and the two-probe table.
- Five manuscript savings cards under [docs/assets/](docs/assets/).

## [0.1.3] - 2026-08-14

### Changed

- Synced merged `chat-compressor` engine from CHAT-COMPRESSOR lab (fork merge):
  scrub-safe `HOME_RE`, query-aware ranking, design/outcome extractors alongside
  M3–M6, `chunks.py` pool=`merged_body` (no `restored_fences`), package stamp 0.1.3.
- Extension `package.json` version aligned to **0.1.3** so Reprovision cannot roll
  the live venv back to 0.1.0.

## [Unreleased]

### Added

- Repository scaffold: `LICENSE` (Apache-2.0), `README.md`, `SECURITY.md`,
  `CONTRIBUTING.md`, `CHANGELOG.md`, `.gitignore`, `.github/CODEOWNERS`.
- `docs/COMPATIBILITY.md` — host facts captured from the installed Cursor
  application bundle (application version, bundled VS Code API version, product
  identity, extension gallery endpoint), the recommended `engines.vscode` floor,
  and the runtime signals still to be verified from a live extension host.
- `docs/PUBLISHING.md` — Open VSX only publishing policy and the namespace claim
  checklist.

No engine or extension code is present in this release. Nothing is installable
yet.
