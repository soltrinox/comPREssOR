"""Structure-aware chunker: headings, sentences, fenced code, def/class units."""

from __future__ import annotations

import re

from chat_compressor.extractive import PATH_RE

_HEADING_SPLIT_RE = re.compile(r"(?=^#{1,6}\s+)", re.M)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")
_FENCE_RE = re.compile(r"```[^\n]*\n.*?```", re.S)
_DEF_CLASS_RE = re.compile(r"^(?:async\s+def|def|class)\s+\S[^\n]*", re.M)
_HEADING_LINE_RE = re.compile(r"^#{1,6}\s+")
_PLACEHOLDER_FENCE = re.compile(r"__FENCE_(\d+)__")
_PLACEHOLDER_PATH = re.compile(r"__PATH_(\d+)__")

# ~64–128 tok midpoint; packing still uses chars/4 elsewhere.
_TARGET_TOKENS = 96
_MIN_TOKENS = 64
_MAX_TOKENS = 128


def estimate_ws_tokens(text: str) -> int:
    return len(text.split()) if text.strip() else 0


def chunk_text(text: str, max_chunks: int = 8) -> list[str]:
    """Heading/sentence/code split; never split a path or def/class signature mid-token."""
    raw = text or ""
    if not raw.strip():
        return [""]

    stripped, fences = _extract_fences(raw)
    protected, paths = _protect_paths(stripped)

    units: list[str] = []
    sections = [s.strip() for s in _HEADING_SPLIT_RE.split(protected) if s.strip()]
    if len(sections) <= 1:
        sections = [protected.strip()]

    headings: list[str] = []
    body: list[str] = []
    for sec in sections:
        lines = sec.splitlines()
        if lines and _HEADING_LINE_RE.match(lines[0]):
            headings.append(lines[0].strip())
            rest = "\n".join(lines[1:]).strip()
            if rest:
                body.extend(_split_code_and_sentences(rest))
        else:
            body.extend(_split_code_and_sentences(sec))

    restored_head = [_restore(h, fences, paths) for h in headings]
    restored_body = [_restore(b, fences, paths) for b in body]
    # Fenced placeholders restore to atomic units; do not append fences twice.
    merged_body = _merge_to_target(restored_body)
    chunks = restored_head + merged_body
    chunks = [c.strip() for c in chunks if c and c.strip()]
    if not chunks:
        return [raw.strip()]
    if len(chunks) <= max_chunks:
        return chunks

    keep_head = min(len(restored_head), max_chunks)
    selected = restored_head[:keep_head]
    remaining = max_chunks - keep_head
    pool = merged_body  # was: restored_fences + merged_body
    fence_pool = [c for c in pool if _is_complete_fence(c)]
    if remaining <= 0:
        if fence_pool and max_chunks >= 1:
            selected = selected[: max_chunks - 1] + [fence_pool[0]]
        return selected[:max_chunks]
    if len(pool) <= remaining:
        return (selected + pool)[:max_chunks]
    # Evenly spaced remainder (stable, no numpy).
    if remaining == 1:
        selected.append(fence_pool[0] if fence_pool else pool[0])
        return selected[:max_chunks]
    step = (len(pool) - 1) / (remaining - 1)
    idxs = sorted({int(round(i * step)) for i in range(remaining)})
    selected.extend(pool[i] for i in idxs if i < len(pool))
    if fence_pool and not any(_is_complete_fence(c) for c in selected):
        selected[-1] = fence_pool[0]
    return selected[:max_chunks]


def _is_complete_fence(text: str) -> bool:
    s = (text or "").strip()
    if not (s.startswith("```") and s.endswith("```")):
        return False
    return s.count("```") >= 2 and s.count("```") % 2 == 0


def _extract_fences(text: str) -> tuple[str, list[str]]:
    fences: list[str] = []

    def repl(match: re.Match[str]) -> str:
        fences.append(match.group(0).strip())
        return f"\n\n__FENCE_{len(fences) - 1}__\n\n"

    return _FENCE_RE.sub(repl, text), fences


def _protect_paths(text: str) -> tuple[str, list[str]]:
    paths: list[str] = []

    def repl(match: re.Match[str]) -> str:
        paths.append(match.group(0))
        return f" __PATH_{len(paths) - 1}__ "

    return PATH_RE.sub(repl, text), paths


def _restore(text: str, fences: list[str], paths: list[str]) -> str:
    def fence_repl(match: re.Match[str]) -> str:
        idx = int(match.group(1))
        if 0 <= idx < len(fences):
            return fences[idx]
        return match.group(0)

    def path_repl(match: re.Match[str]) -> str:
        idx = int(match.group(1))
        if 0 <= idx < len(paths):
            return paths[idx]
        return match.group(0)

    out = _PLACEHOLDER_FENCE.sub(fence_repl, text)
    return _PLACEHOLDER_PATH.sub(path_repl, out)


def _split_code_and_sentences(text: str) -> list[str]:
    parts: list[str] = []
    cursor = 0
    for match in _DEF_CLASS_RE.finditer(text):
        before = text[cursor : match.start()].strip()
        if before:
            parts.extend(p.strip() for p in _SENTENCE_SPLIT_RE.split(before) if p.strip())
        sig = match.group(0).strip()
        if sig:
            parts.append(sig)
        cursor = match.end()
    rest = text[cursor:].strip()
    if rest:
        parts.extend(p.strip() for p in _SENTENCE_SPLIT_RE.split(rest) if p.strip())
    return parts


def _merge_to_target(pieces: list[str]) -> list[str]:
    if not pieces:
        return []
    out: list[str] = []
    buf = ""
    buf_tok = 0
    for piece in pieces:
        tok = estimate_ws_tokens(piece)
        atomic = tok >= _MIN_TOKENS or _is_complete_fence(piece)
        if atomic:
            if buf:
                out.append(buf.strip())
                buf, buf_tok = "", 0
            out.append(piece.strip())
            continue
        if buf and buf_tok + tok > _MAX_TOKENS:
            out.append(buf.strip())
            buf, buf_tok = piece, tok
            continue
        buf = (buf + " " + piece).strip() if buf else piece
        buf_tok = estimate_ws_tokens(buf)
        if buf_tok >= _TARGET_TOKENS:
            out.append(buf.strip())
            buf, buf_tok = "", 0
    if buf:
        out.append(buf.strip())
    return out
