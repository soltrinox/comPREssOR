"""CC-6: pluggable token counters.

Keep ``metrics.estimate_tokens`` (chars/4) for internal packing budgets.
Use ``count_tokens`` for cost decisions — resolved per recipient tokenizer_id
when a counter is registered, otherwise the cheap estimate as fallback.
"""

from __future__ import annotations

from typing import Callable

from chat_compressor.metrics import estimate_tokens

TokenCounter = Callable[[str], int]

_REGISTRY: dict[str, TokenCounter] = {}


def register_counter(tokenizer_id: str, counter: TokenCounter) -> None:
    """Register an accurate counter for a tokenizer identity."""
    tid = str(tokenizer_id).strip()
    if not tid:
        raise ValueError("tokenizer_id must be non-empty")
    _REGISTRY[tid] = counter


def unregister_counter(tokenizer_id: str) -> None:
    _REGISTRY.pop(str(tokenizer_id).strip(), None)


def clear_counters() -> None:
    _REGISTRY.clear()


def resolve_counter(tokenizer_id: str | None = None) -> TokenCounter:
    """Return registered counter for tokenizer_id, else cheap estimate."""
    if tokenizer_id is not None:
        tid = str(tokenizer_id).strip()
        if tid and tid in _REGISTRY:
            return _REGISTRY[tid]
    return estimate_tokens


def count_tokens(text: str, tokenizer_id: str | None = None) -> int:
    """Accurate-when-available token count for cost; never raises on empty text."""
    if not text:
        return 0
    counter = resolve_counter(tokenizer_id)
    try:
        n = int(counter(text))
    except Exception:  # noqa: BLE001 — cost path must fail-open to estimate
        return estimate_tokens(text)
    return max(0, n)


def packing_tokens(text: str) -> int:
    """Always the cheap chars/4 estimate used by pack.py budgets."""
    return estimate_tokens(text)


def try_hf_counter(tokenizer_id: str) -> TokenCounter | None:
    """Best-effort HuggingFace AutoTokenizer counter when [hf] extra is installed.

    Returns None when transformers is unavailable or load fails (NOT_RUN path).
    """
    tid = str(tokenizer_id).strip()
    if not tid:
        return None
    try:
        from transformers import AutoTokenizer  # type: ignore[import-not-found]
    except Exception:
        return None
    try:
        tok = AutoTokenizer.from_pretrained(tid, use_fast=True)
    except Exception:
        return None

    def _count(text: str) -> int:
        if not text:
            return 0
        ids = tok.encode(text, add_special_tokens=False)
        return len(ids)

    return _count
