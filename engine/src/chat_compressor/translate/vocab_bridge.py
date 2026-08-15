"""Pattern 1 — vocabulary-space bridge (zero-train). Debug-only by default."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from chat_compressor.chunks import chunk_text
from chat_compressor.compress import DEFAULT_D, l2_normalize
from chat_compressor.extractive import extractive_gist, jaccard, keyword_set
from chat_compressor.pack import PackResult, forward_budget, pack_forward
from chat_compressor.producer import hashed_ngram_embed
from chat_compressor.rank import collect_candidates, rank_relevant_chunks

# Compact frozen decode table so Cursor SDK always receives discrete text.
DEFAULT_VOCAB = [
    "add", "agent", "answer", "ask", "build", "call", "check", "close",
    "code", "complete", "context", "create", "data", "done", "error", "file",
    "fix", "graph", "item", "list", "load", "mark", "next", "open",
    "plan", "read", "remain", "run", "save", "set", "state", "step",
    "task", "test", "text", "todo", "turn", "update", "user", "wait",
    "write", "yes", "no", "left", "right", "start", "stop", "ok",
    "milk", "bread", "grocery", "note", "query", "status", "active", "bound",
]

P1_JACCARD_MIN = 0.15


@dataclass
class SampledPayload:
    kind: str  # "text" | "latent"
    text: str
    C: np.ndarray | None
    method: str
    packed_tokens: int = 0
    budget: int = 0
    rank_ms: float = 0.0
    tokens_ws: int = 0
    tokens_chars4: int = 0
    rate: float = 0.0
    novel_tokens: int = 0
    dup_suppressed_tokens: int = 0
    line_hashes: tuple[str, ...] = ()


def inject_p1_enabled() -> bool:
    raw = os.environ.get("CHAT_COMPRESSOR_INJECT_P1", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def softmax(logits: np.ndarray, tau: float = 1.0) -> np.ndarray:
    scaled = logits / max(tau, 1e-6)
    shifted = scaled - scaled.max(axis=-1, keepdims=True)
    exp = np.exp(shifted)
    return exp / np.maximum(exp.sum(axis=-1, keepdims=True), 1e-12)


def vocab_embed_table(vocab: list[str], d: int = DEFAULT_D, seed: int = 1) -> np.ndarray:
    return np.stack([hashed_ngram_embed(tok, d=d, seed=seed) for tok in vocab]).astype(np.float32)


def align_vocab_map(vocab_a: list[str], vocab_b: list[str]) -> np.ndarray:
    """Token-string / byte alignment matrix (cached conceptually as M_vocab)."""
    index_b = {tok: i for i, tok in enumerate(vocab_b)}
    m = np.zeros((len(vocab_a), len(vocab_b)), dtype=np.float32)
    for i, tok in enumerate(vocab_a):
        if tok in index_b:
            m[i, index_b[tok]] = 1.0
        else:
            # byte-overlap fallback: distribute mass over shared prefixes
            hits = [j for j, other in enumerate(vocab_b) if other[:2] == tok[:2]]
            if hits:
                mass = 1.0 / len(hits)
                for j in hits:
                    m[i, j] = mass
            else:
                m[i, i % len(vocab_b)] = 1.0
    return m


def save_vocab_map(path: str | Path, matrix: np.ndarray, vocab_a: list[str], vocab_b: list[str]) -> None:
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        json.dumps(
            {"vocab_a": vocab_a, "vocab_b": vocab_b, "shape": list(matrix.shape)},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    np.save(dest.with_suffix(".npy"), matrix)


def _collapse_consecutive(tokens: list[str]) -> list[str]:
    if not tokens:
        return []
    out = [tokens[0]]
    for tok in tokens[1:]:
        if tok != out[-1]:
            out.append(tok)
    return out


def merge_forward_text(
    *,
    hot_set: str = "",
    extractive: str = "",
    p1_text: str = "",
    max_extractive_tokens: int = 32,
    allow_p1: bool | None = None,
) -> SampledPayload:
    """HOT_SET first; append ≤k deduped extractive tokens; optional P1 debug."""
    p1_ok = inject_p1_enabled() if allow_p1 is None else allow_p1
    ext_tokens: list[str] = []
    seen_tok: set[str] = set()
    for tok in extractive.split():
        key = tok.lower()
        if key in seen_tok:
            continue
        seen_tok.add(key)
        ext_tokens.append(tok)
        if len(ext_tokens) >= max_extractive_tokens:
            break

    if hot_set.strip():
        body_parts: list[str] = [hot_set.strip()]
        hot_words = {w.lower() for w in re_findall_words(hot_set)}
        ext_extra: list[str] = []
        for tok in ext_tokens:
            if tok.lower() in hot_words:
                continue
            if len(ext_extra) >= max_extractive_tokens:
                break
            ext_extra.append(tok)
        method = "hot_set"
        if ext_extra:
            body_parts.append(" ".join(ext_extra))
            method = "extractive+hot"
        if p1_ok and p1_text.strip():
            hot_kw = keyword_set(hot_set) | keyword_set(" ".join(ext_extra))
            p1_kw = keyword_set(p1_text)
            if jaccard(p1_kw, hot_kw) >= P1_JACCARD_MIN:
                body_parts.append(p1_text.strip())
                method = "p1-debug"
        return SampledPayload(kind="text", text="\n".join(body_parts).strip(), C=None, method=method)

    if ext_tokens:
        text = " ".join(ext_tokens)
        method = "extractive"
        if p1_ok and p1_text.strip():
            if jaccard(keyword_set(p1_text), keyword_set(text)) >= P1_JACCARD_MIN:
                text = (text + "\n" + p1_text.strip()).strip()
                method = "p1-debug"
        return SampledPayload(kind="text", text=text, C=None, method=method)

    if p1_ok and p1_text.strip():
        return SampledPayload(kind="text", text=p1_text.strip(), C=None, method="p1-debug")

    return SampledPayload(kind="text", text="", C=None, method="hot_set")


def re_findall_words(text: str) -> list[str]:
    import re

    return re.findall(r"[A-Za-z0-9_./#-]+", text)


class Pattern1Bridge:
    """Zero-train vocab bridge. Decode uses nearest frozen embeddings when no LM head."""

    def __init__(
        self,
        vocab: list[str] | None = None,
        d: int = DEFAULT_D,
        tau: float = 1.0,
        w_lm: np.ndarray | None = None,
        vocab_b: list[str] | None = None,
        w_embed_b: np.ndarray | None = None,
    ) -> None:
        self.vocab = list(vocab or DEFAULT_VOCAB)
        self.d = d
        self.tau = tau
        self.w_embed = vocab_embed_table(self.vocab, d=d, seed=1)
        self.w_lm = w_lm
        self.vocab_b = list(vocab_b or self.vocab)
        self.w_embed_b = w_embed_b if w_embed_b is not None else vocab_embed_table(self.vocab_b, d=d, seed=2)
        self.m_vocab = align_vocab_map(self.vocab, self.vocab_b)

    def logits_a(self, c_a: np.ndarray) -> np.ndarray:
        w = self.w_lm if self.w_lm is not None else self.w_embed
        return np.asarray(c_a, dtype=np.float32) @ np.asarray(w, dtype=np.float32).T

    def translate_logits(self, l_a: np.ndarray) -> np.ndarray:
        return np.asarray(l_a, dtype=np.float32) @ self.m_vocab

    def expectation_embed(self, c_a: np.ndarray) -> np.ndarray:
        l_a = self.logits_a(c_a)
        l_b = self.translate_logits(l_a)
        p_b = softmax(l_b, tau=self.tau)
        return l2_normalize(p_b @ self.w_embed_b)

    def decode_tokens(self, c_a: np.ndarray) -> list[str]:
        """Greedy argmax with used-token mask; collapse consecutive duplicates."""
        l_a = self.logits_a(c_a)
        l_b = self.translate_logits(l_a)
        p_b = softmax(l_b, tau=self.tau)
        rows = np.asarray(p_b, dtype=np.float32)
        if rows.ndim == 1:
            rows = rows[None, :]
        used = np.zeros((rows.shape[1],), dtype=bool)
        tokens: list[str] = []
        for i in range(rows.shape[0]):
            masked = rows[i].copy()
            masked[used] = -1.0
            if np.all(used):
                idx = int(rows[i].argmax())
            else:
                idx = int(masked.argmax())
                used[idx] = True
            tokens.append(self.vocab_b[idx])
        return _collapse_consecutive(tokens)

    def sample_text(
        self,
        c_a: np.ndarray | None,
        hot_set: str = "",
        *,
        window_text: str = "",
        query: str | None = None,
        typed_lines: list[str] | None = None,
        ranked_chunks: list[str] | None = None,
        graph: object | None = None,
        max_extractive_tokens: int = 32,
        budget: int | None = None,
        recent_hashes: set[str] | None = None,
        openitem_changed: bool = True,
        node_superseded: bool = False,
        allow_skip: bool = False,
    ) -> SampledPayload:
        """Primary forward channel: HOT_SET → typed → ranked chunks; P1 debug-only."""
        import time

        cap = budget if budget is not None else forward_budget()
        t0 = time.perf_counter()
        chunks = list(ranked_chunks) if ranked_chunks is not None else None
        if chunks is None:
            if graph is not None:
                cands = collect_candidates(graph, query=query)
            else:
                cands = chunk_text(window_text.strip() or hot_set, max_chunks=32)
            ranked = rank_relevant_chunks(query or "", cands) if (query or "").strip() else []
            chunks = [r.text for r in ranked]
        rank_ms = (time.perf_counter() - t0) * 1000.0
        fallback = False
        if not chunks:
            source = window_text.strip() or hot_set
            ext = extractive_gist(source, max_tokens=max_extractive_tokens)
            chunks = [ext] if ext.strip() else []
            fallback = bool(chunks)

        typed = list(typed_lines) if typed_lines is not None else []
        packed: PackResult = pack_forward(
            hot_set=hot_set,
            typed_lines=typed,
            ranked_chunks=chunks,
            budget=cap,
            recent_hashes=recent_hashes,
            openitem_changed=openitem_changed,
            node_superseded=node_superseded,
            allow_skip=allow_skip,
        )
        method = packed.method
        if method != "skip":
            if fallback and method == "hot_set" and packed.text and hot_set.strip():
                method = "extractive+hot"
            elif fallback and not hot_set.strip():
                method = "extractive"

        p1_text = ""
        c_embed = None
        if c_a is not None and np.asarray(c_a).size > 0:
            tokens = self.decode_tokens(c_a)
            p1_text = " ".join(tokens)
            c_embed = self.expectation_embed(c_a)

        text = packed.text
        if method != "skip" and inject_p1_enabled() and p1_text.strip():
            leftover = cap - packed.packed_tokens
            hot_kw = keyword_set(hot_set) | keyword_set(text)
            if leftover > 0 and jaccard(keyword_set(p1_text), hot_kw) >= P1_JACCARD_MIN:
                extra = p1_text.strip()
                from chat_compressor.metrics import estimate_tokens

                if estimate_tokens(extra) <= leftover:
                    text = (text + "\n" + extra).strip()
                    method = "p1-debug"

        packed_tokens = packed.packed_tokens
        if inject_p1_enabled() and method == "p1-debug":
            from chat_compressor.metrics import estimate_tokens as _est

            packed_tokens = _est(text) if text else 0
        return SampledPayload(
            kind="text",
            text=text,
            C=c_embed,
            method=method,
            packed_tokens=packed_tokens,
            budget=packed.budget,
            rank_ms=rank_ms,
            tokens_ws=packed.tokens_ws,
            tokens_chars4=packed.tokens_chars4,
            rate=packed.rate,
            novel_tokens=packed.novel_tokens,
            dup_suppressed_tokens=packed.dup_suppressed_tokens,
            line_hashes=packed.line_hashes,
        )
