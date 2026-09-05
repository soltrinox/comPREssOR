"""CC-10: optional tensor quantization with reconstruction budget."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from chat_compressor.store import (
    DEFAULT_RECON_COSINE_BUDGET,
    StateStore,
    dequantize_C,
    quantize_C,
    reconstruction_cosine,
    tensor_quantization_scheme,
)


def _l2_rows(arr: np.ndarray) -> np.ndarray:
    a = np.asarray(arr, dtype=np.float32)
    n = np.linalg.norm(a, axis=1, keepdims=True)
    n = np.where(n < 1e-12, 1.0, n)
    return a / n


def test_default_scheme_float32(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CHAT_COMPRESSOR_TENSOR_QUANT", raising=False)
    assert tensor_quantization_scheme() == "float32"


def test_int8_reconstruction_within_budget(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHAT_COMPRESSOR_TENSOR_QUANT", "int8")
    rng = np.random.default_rng(0)
    original = _l2_rows(rng.normal(size=(8, 32)).astype(np.float32))
    store = StateStore(tmp_path / "state")
    node = store.save(agent_id="q", C=original, producer="embed", k_max=8)
    assert node.meta.get("quantization") == "int8"
    cos = reconstruction_cosine(original, node.C)
    assert cos >= DEFAULT_RECON_COSINE_BUDGET


def test_float16_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHAT_COMPRESSOR_TENSOR_QUANT", "float16")
    original = _l2_rows(np.eye(4, 16, dtype=np.float32))
    store = StateStore(tmp_path / "state")
    node = store.save(agent_id="f16", C=original, producer="embed", k_max=4)
    assert node.meta.get("quantization") == "float16"
    assert reconstruction_cosine(original, node.C) >= DEFAULT_RECON_COSINE_BUDGET


def test_float32_unchanged_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CHAT_COMPRESSOR_TENSOR_QUANT", raising=False)
    original = np.eye(3, 8, dtype=np.float32)
    store = StateStore(tmp_path / "state")
    node = store.save(agent_id="f32", C=original, producer="embed", k_max=3)
    # Default float32 omits quantization key for 0.2.0 meta parity.
    assert "quantization" not in node.meta
    np.testing.assert_allclose(node.C, original, atol=1e-6)


def test_quantize_dequantize_helpers() -> None:
    original = _l2_rows(np.ones((4, 8), dtype=np.float32))
    tensors, meta = quantize_C(original, "int8")
    assert meta["quantization"] == "int8"
    recon = dequantize_C(tensors, meta)
    assert reconstruction_cosine(original, recon) >= DEFAULT_RECON_COSINE_BUDGET
