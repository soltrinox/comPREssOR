import numpy as np
import pytest

from chat_compressor.translate.vocab_bridge import Pattern1Bridge


def test_p1_decode_length_and_dedup() -> None:
    bridge = Pattern1Bridge(d=256)
    rng = np.random.default_rng(0)
    c_a = rng.normal(size=(7, 256)).astype(np.float32)
    tokens = bridge.decode_tokens(c_a)
    assert 1 <= len(tokens) <= 7
    for a, b in zip(tokens, tokens[1:]):
        assert a != b


def test_sample_text_defaults_to_extractive_or_hot(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CHAT_COMPRESSOR_INJECT_P1", raising=False)
    bridge = Pattern1Bridge(d=256)
    rng = np.random.default_rng(0)
    c_a = rng.normal(size=(7, 256)).astype(np.float32)
    payload = bridge.sample_text(
        c_a,
        hot_set="OpenItem bread: open: bread",
        window_text='Add "milk" under buy groceries.',
    )
    assert payload.method in {"hot_set", "extractive+hot", "query-pack"}
    assert "bread" in payload.text.lower()
    assert payload.C is not None
    assert payload.method != "p1-debug"


def test_p1_fallback_hot_set_when_no_matrix() -> None:
    bridge = Pattern1Bridge()
    payload = bridge.sample_text(None, hot_set="OpenItem bread: open")
    assert payload.method in {"hot_set", "extractive+hot", "query-pack"}
    assert "bread" in payload.text
