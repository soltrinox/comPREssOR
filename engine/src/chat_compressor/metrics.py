"""Payload and matrix metrics for stage logs and proof reports."""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass
from typing import Iterable, Sequence

import numpy as np

from chat_compressor.extractive import HEADING_RE, PATH_RE, QUOTED_RE, jaccard, keyword_set

TOKEN_RE = re.compile(r"[A-Za-z0-9_./#-]+")
# Keep in lockstep with graph.PREAMBLE_LIST (M3).
PREAMBLE_LIST = (
    "let me",
    "i'll",
    "i will",
    "reading",
    "checking",
    "running",
    "thanks",
    "thank you",
    "got it",
    "looking at",
    "let's see",
)
HOT_LINE_KIND_RE = re.compile(r"^(OpenItem|Fact|Topic|Event|Turn)\s*:?\s+", re.I)
PATH_LIKE_RE = re.compile(
    r"(?:^|\s)(?:Fact\s+)?(?:[\w.-]+/)+[\w.-]+|"
    r"heading:|"
    r"\b[\w.-]+\.(?:md|py|json|sh|tex|png|jpg)\b",
    re.I,
)


@dataclass(frozen=True)
class PayloadStats:
    raw_chars: int
    gist_chars: int
    graph_chars: int
    ratio: float
    raw_tokens_est: int
    gist_tokens_est: int

    def to_dict(self) -> dict[str, int | float]:
        return asdict(self)


@dataclass(frozen=True)
class MatrixStats:
    k: int
    d: int
    frobenius: float
    mean: float
    std: float
    live_slots: int

    def to_dict(self) -> dict[str, int | float]:
        return asdict(self)


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


def payload_stats(raw: str, gist: str, graph: str) -> PayloadStats:
    raw_chars = len(raw)
    gist_chars = len(gist)
    graph_chars = len(graph)
    ratio = (gist_chars / raw_chars) if raw_chars else 0.0
    return PayloadStats(
        raw_chars=raw_chars,
        gist_chars=gist_chars,
        graph_chars=graph_chars,
        ratio=ratio,
        raw_tokens_est=estimate_tokens(raw),
        gist_tokens_est=estimate_tokens(gist),
    )


def matrix_stats(c: np.ndarray, mask: np.ndarray | None = None) -> MatrixStats:
    arr = np.asarray(c, dtype=np.float32)
    if arr.ndim == 1:
        arr = arr[None, :]
    k, d = arr.shape
    live = int(k if mask is None else np.count_nonzero(mask))
    return MatrixStats(
        k=int(k),
        d=int(d),
        frobenius=float(np.linalg.norm(arr)),
        mean=float(arr.mean()) if arr.size else 0.0,
        std=float(arr.std()) if arr.size else 0.0,
        live_slots=live,
    )


def keyword_jaccard(a: str, b: str) -> float:
    """Token Jaccard between two strings."""
    return jaccard(keyword_set(a), keyword_set(b))


def entity_recall(reference_terms: set[str] | list[str], payload: str) -> float:
    """Fraction of reference terms whose lowercase form appears in payload keywords."""
    refs = {t.lower().strip() for t in reference_terms if t and t.strip()}
    if not refs:
        return 1.0
    payload_kw = keyword_set(payload)
    payload_lower = payload.lower()
    hits = 0
    for term in refs:
        if term in payload_kw or term in payload_lower:
            hits += 1
            continue
        # multi-word / path fragments
        parts = [p for p in TOKEN_RE.findall(term) if len(p) > 1]
        if parts and all(p.lower() in payload_kw or p.lower() in payload_lower for p in parts):
            hits += 1
    return hits / len(refs)


def reference_terms_from_text(text: str) -> set[str]:
    """Fixture-derived reference terms: paths, headings, quoted OpenItem-like labels."""
    terms: set[str] = set()
    for m in PATH_RE.finditer(text):
        terms.add(m.group(0))
    for m in HEADING_RE.finditer(text):
        terms.add(m.group(1).strip())
    for m in QUOTED_RE.finditer(text):
        terms.add(m.group(1).strip())
    return {t for t in terms if len(t) >= 2}


def harmonic_f1(precision: float, recall: float) -> float:
    """Harmonic mean of precision and recall; 0 when either side is 0."""
    p = float(precision)
    r = float(recall)
    if p <= 0.0 or r <= 0.0:
        return 0.0
    return 2.0 * p * r / (p + r)


def dedup_yield(dup_suppressed: int, novel: int) -> float | None:
    """dup / (dup + novel); None when denominator is 0."""
    dup = max(0, int(dup_suppressed))
    nov = max(0, int(novel))
    denom = dup + nov
    if denom <= 0:
        return None
    return dup / denom


def percentile(values: Sequence[float], p: float) -> float | None:
    """Nearest-rank percentile in [0, 100]. None on empty input."""
    xs = [float(v) for v in values]
    if not xs:
        return None
    if p <= 0:
        return min(xs)
    if p >= 100:
        return max(xs)
    ordered = sorted(xs)
    # nearest-rank (1-indexed)
    k = max(1, int(math.ceil(p / 100.0 * len(ordered))))
    return ordered[min(len(ordered), k) - 1]


def is_preamble_text(text: str) -> bool:
    """True when the line starts with an M3 preamble cue."""
    blob = (text or "").strip().lower()
    if not blob:
        return False
    # Strip typed prefixes before checking.
    stripped = HOT_LINE_KIND_RE.sub("", blob).lstrip(": ").strip()
    head = stripped[:40]
    return any(head.startswith(p) for p in PREAMBLE_LIST)


def split_retained_lines(*blobs: str) -> list[str]:
    """Deduped non-empty lines from HOT_SET / Fact / typed inject text."""
    out: list[str] = []
    seen: set[str] = set()
    for blob in blobs:
        for raw in (blob or "").splitlines():
            line = raw.strip()
            if not line:
                continue
            key = line.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(line)
    return out


def design_precision(
    retained_lines: Sequence[str],
    *,
    decision_matchers: Iterable,
    match_fn=None,
) -> float:
    """Fraction of retained lines that match a labeled decision or are non-preamble.

    A line scores as a true positive when:
      - match_fn(decision, line) hits any labeled decision, OR
      - the line is not preamble (M3 PREAMBLE_LIST).
    Empty retained set → 0.0.
    """
    lines = [ln for ln in retained_lines if (ln or "").strip()]
    if not lines:
        return 0.0
    decisions = list(decision_matchers)
    good = 0
    for line in lines:
        matched = False
        if match_fn is not None and decisions:
            for dec in decisions:
                try:
                    if match_fn(dec, line):
                        matched = True
                        break
                except Exception:  # noqa: BLE001 — scoring must not crash harness
                    continue
        if matched or not is_preamble_text(line):
            good += 1
    return good / len(lines)


def tokens_per_decision(inject_tokens: int, labeled_present: int) -> float | None:
    """Cumulative inject ÷ # labeled decisions present at t; None if none present."""
    n = int(labeled_present)
    if n <= 0:
        return None
    return float(inject_tokens) / float(n)


def hot_set_pollution(hot_set_text: str) -> dict[str, float | int]:
    """Share of HOT_SET tokens that are path/heading vs decision/OpenItem.

    Classification is line-level; token weight ≈ estimate_tokens(line).
    """
    path_tok = 0
    decision_tok = 0
    other_tok = 0
    for line in split_retained_lines(hot_set_text):
        tok = estimate_tokens(line)
        lower = line.lower()
        if lower.startswith("openitem ") or "openitem " in lower[:20]:
            decision_tok += tok
            continue
        if PATH_LIKE_RE.search(line) or "heading:" in lower:
            path_tok += tok
            continue
        # Fact lines without path cues count as decision/content.
        if lower.startswith("fact ") or HOT_LINE_KIND_RE.match(line):
            decision_tok += tok
        else:
            other_tok += tok
    total = path_tok + decision_tok + other_tok
    pollution = (path_tok / total) if total else 0.0
    return {
        "path_heading_tokens": path_tok,
        "decision_openitem_tokens": decision_tok,
        "other_tokens": other_tok,
        "total_tokens": total,
        "pollution": pollution,
    }


def budget_fill_ratio(packed_tokens: int, budget: int) -> float | None:
    """packed_tokens / budget; None when budget <= 0."""
    b = int(budget)
    if b <= 0:
        return None
    return float(packed_tokens) / float(b)


def skip_rate(methods: Sequence[str]) -> float:
    """Fraction of turns with method=skip."""
    if not methods:
        return 0.0
    skips = sum(1 for m in methods if str(m) == "skip")
    return skips / len(methods)
