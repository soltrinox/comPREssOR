"""CC-6: pluggable token counter; packing stays on cheap estimate."""

from __future__ import annotations

import pytest

from chat_compressor import metrics
from chat_compressor.tokens import (
    clear_counters,
    count_tokens,
    packing_tokens,
    register_counter,
    resolve_counter,
    try_hf_counter,
    unregister_counter,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    clear_counters()
    yield
    clear_counters()


def test_packing_tokens_matches_estimate():
    text = "hello world " * 20
    assert packing_tokens(text) == metrics.estimate_tokens(text)


def test_count_tokens_falls_back_to_estimate():
    text = "abcdefghi"
    assert count_tokens(text) == metrics.estimate_tokens(text)
    assert count_tokens("") == 0


def test_registered_counter_used_for_cost_not_packing():
    register_counter("unit-tok", lambda t: 42 if t else 0)
    assert count_tokens("anything", tokenizer_id="unit-tok") == 42
    # Packing path ignores registry.
    assert packing_tokens("anything") == metrics.estimate_tokens("anything")
    assert resolve_counter("unit-tok")("x") == 42
    unregister_counter("unit-tok")
    assert count_tokens("anything", tokenizer_id="unit-tok") == metrics.estimate_tokens(
        "anything"
    )


def test_counter_exception_fails_open_to_estimate():
    def boom(_t: str) -> int:
        raise RuntimeError("tok fail")

    register_counter("bad", boom)
    text = "zzzz"
    assert count_tokens(text, tokenizer_id="bad") == metrics.estimate_tokens(text)


def test_hf_counter_optional():
    """When transformers unavailable, try_hf_counter returns None (NOT_RUN)."""
    counter = try_hf_counter("gpt2")
    if counter is None:
        pytest.skip("transformers/HF tokenizer not available (NOT_RUN)")
    n = counter("Hello world")
    assert isinstance(n, int) and n > 0
