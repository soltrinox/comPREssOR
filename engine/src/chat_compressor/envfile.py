"""Stdlib .env loader. Does not overwrite already-set shell environment variables."""

from __future__ import annotations

from pathlib import Path


def load_env_file(path: Path) -> int:
    """Load KEY=VALUE lines from path into os.environ if the key is unset or empty.

    Returns the number of keys newly applied. Missing file is a no-op (returns 0).
    Never prints values. Supports optional surrounding single/double quotes.
    """
    import os

    if not path.is_file():
        return 0
    applied = 0
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        existing = os.environ.get(key)
        if existing is not None and existing.strip() != "":
            continue
        os.environ[key] = value
        applied += 1
    return applied


def load_project_env(project_root: Path) -> int:
    """Load `<project_root>/.env` if present. Shell-set vars win."""
    return load_env_file(project_root / ".env")
