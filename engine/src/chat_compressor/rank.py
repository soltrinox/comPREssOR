"""Query-aware extractive ranking via hashed n-gram cosine (offline default)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from chat_compressor.chunks import chunk_text
from chat_compressor.producer import hashed_ngram_embed

MIN_RANK_SCORE = 0.03
RANK_FALLBACK_TOP_K = 3


@dataclass(frozen=True)
class RankedChunk:
    text: str
    score: float


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    va = np.asarray(a, dtype=np.float32).reshape(-1)
    vb = np.asarray(b, dtype=np.float32).reshape(-1)
    na = float(np.linalg.norm(va))
    nb = float(np.linalg.norm(vb))
    if na < 1e-12 or nb < 1e-12:
        return 0.0
    return float(np.dot(va, vb) / (na * nb))


def rank_chunks(
    query: str,
    chunks: list[str],
    *,
    d: int = 256,
    seed: int = 0,
) -> list[RankedChunk]:
    """Score chunks with cosine(hashed_ngram(query), hashed_ngram(chunk)). Preserve wording."""
    q = (query or "").strip()
    if not q:
        return []
    qv = hashed_ngram_embed(q, d=d, seed=seed)
    scored: list[RankedChunk] = []
    seen: set[str] = set()
    for raw in chunks:
        text = (raw or "").strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        cv = hashed_ngram_embed(text, d=d, seed=seed)
        scored.append(RankedChunk(text=text, score=cosine(qv, cv)))
    scored.sort(key=lambda r: (-r.score, -len(r.text)))
    return scored


def collect_candidates(
    graph: object,
    *,
    max_chunks: int = 32,
    query: str | None = None,
) -> list[str]:
    """Chunks from window text, typed graph nodes, and selected durable facts."""
    out: list[str] = []
    seen: set[str] = set()

    def _add(text: str) -> None:
        t = (text or "").strip()
        if not t:
            return
        key = t.lower()
        if key in seen:
            return
        seen.add(key)
        out.append(t)

    query_terms = _terms(query or "")
    window = ""
    window_fn = getattr(graph, "window_text", None)
    if callable(window_fn):
        window = str(window_fn() or "")
    for piece in chunk_text(window, max_chunks=max_chunks):
        _add(piece)

    active_fn = getattr(graph, "active_nodes", None)
    nodes = list(active_fn()) if callable(active_fn) else []
    turns = [n for n in nodes if getattr(n, "kind", "") == "Turn"]
    turns.sort(key=lambda n: (getattr(n, "valid_start", ""), (getattr(n, "attrs", {}) or {}).get("index", 0)))
    for node in turns[-8:]:
        _add(getattr(node, "summary", "") or getattr(node, "label", ""))

    typed_fn = getattr(graph, "typed_projection", None)
    if callable(typed_fn):
        try:
            for line in typed_fn(query or None, top_k=16):
                _add(str(line))
        except TypeError:
            for line in typed_fn(query or None):
                _add(str(line))

    for node in nodes:
        kind = getattr(node, "kind", "")
        attrs = getattr(node, "attrs", {}) or {}
        hint = str(attrs.get("kind_hint") or "")
        label = getattr(node, "label", "")
        summary = getattr(node, "summary", "") or label
        relevant = _relevant(f"{label} {summary}", query_terms)
        high_value = hint in {"design", "decision", "outcome"}
        pathish = hint in {"path", "heading"}
        if kind == "Topic":
            _add(summary or label)
        if kind == "Event":
            _add(summary or label)
        if kind == "Fact" and attrs.get("durable") and (high_value or relevant or not pathish):
            _add(getattr(node, "summary", "") or getattr(node, "label", ""))
            if high_value or relevant:
                _add(getattr(node, "label", ""))
        if kind == "OpenItem" and attrs.get("state", "open") != "done":
            _add(getattr(node, "label", ""))
    return out


def rank_relevant_chunks(
    query: str,
    chunks: list[str],
    *,
    min_score: float = MIN_RANK_SCORE,
    fallback_top_k: int = RANK_FALLBACK_TOP_K,
) -> list[RankedChunk]:
    """Rank chunks, keeping signal above a floor with a bounded fallback."""
    ranked = rank_chunks(query, chunks)
    if not ranked:
        return []
    filtered = [r for r in ranked if r.score >= min_score]
    if filtered:
        return filtered
    return ranked[: max(0, fallback_top_k)]


def _terms(text: str) -> set[str]:
    terms = {t.lower() for t in text.replace("/", " ").replace("-", " ").replace(".", " ").split()}
    return {t for t in terms if len(t) >= 3}


def _relevant(text: str, terms: set[str]) -> bool:
    if not terms:
        return False
    return bool(terms & _terms(text))
