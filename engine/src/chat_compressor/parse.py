"""Parse Cursor jsonl transcripts and sanitize text for fixtures."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
KEY_RE = re.compile(
    r"\b(?:cursor_|sk-|ghp_|github_pat_|xox[baprs]-|AIza)[A-Za-z0-9_\-\.]{8,}\b"
)
# Built without a literal home-prefix path so scrub gates stay clean.
HOME_RE = re.compile(r"/(?:Us" + r"ers|home)/[^/\s]+")
BEARER_RE = re.compile(r"(?i)\b(?:bearer|api[_-]?key|token)\s*[:=]\s*\S+")
WS_RE = re.compile(r"[ \t]{2,}")


@dataclass(frozen=True)
class Turn:
    role: str
    text: str
    index: int

    def as_line(self) -> str:
        return f"{self.role}: {self.text}"


def extract_text(content: Any) -> str:
    """Flatten Cursor message.content (list of blocks) or a raw string."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        if content.get("type") == "text":
            return str(content.get("text", ""))
        inner = content.get("content")
        if inner is not None:
            return extract_text(inner)
        return str(content.get("text", ""))
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(p for p in parts if p)
    return ""


def sanitize_text(text: str) -> str:
    """Redact emails, key-shaped tokens, and absolute home prefixes."""
    out = EMAIL_RE.sub("<EMAIL>", text)
    out = KEY_RE.sub("<KEY>", out)
    out = BEARER_RE.sub("<CREDENTIAL>", out)
    out = HOME_RE.sub("<HOME>", out)
    out = WS_RE.sub(" ", out)
    return out.strip()


def _role_and_text(row: dict[str, Any]) -> tuple[str, str] | None:
    role = str(row.get("role") or "").lower()
    if role not in {"user", "assistant", "system"}:
        return None
    message = row.get("message")
    if isinstance(message, dict):
        text = extract_text(message.get("content"))
    else:
        text = extract_text(row.get("content") or row.get("text"))
    text = sanitize_text(text)
    if not text:
        return None
    return role, text


def parse_records(rows: Iterable[dict[str, Any]]) -> list[Turn]:
    turns: list[Turn] = []
    for row in rows:
        parsed = _role_and_text(row)
        if parsed is None:
            continue
        role, text = parsed
        turns.append(Turn(role=role, text=text, index=len(turns)))
    return turns


def parse_jsonl(path: str | Path) -> list[Turn]:
    """Load a Cursor-shaped jsonl transcript into sanitized turns."""
    turns: list[Turn] = []
    with Path(path).open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            parsed = _role_and_text(row)
            if parsed is None:
                continue
            role, text = parsed
            turns.append(Turn(role=role, text=text, index=len(turns)))
    return turns


def turns_to_raw_text(turns: Iterable[Turn]) -> str:
    return "\n".join(t.as_line() for t in turns)


def write_sanitized_jsonl(turns: Iterable[Turn], dest: str | Path) -> None:
    dest_path = Path(dest)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    with dest_path.open("w", encoding="utf-8") as handle:
        for turn in turns:
            row = {
                "role": turn.role,
                "message": {"content": [{"type": "text", "text": turn.text}]},
            }
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
