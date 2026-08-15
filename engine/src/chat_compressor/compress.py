"""Compression taxonomy and C_t merge (append-then-pool / slot-wise EMA)."""

from __future__ import annotations

from typing import Literal

import numpy as np

Method = Literal[
    "digest",
    "hot_set",
    "p1",
    "p2",
    "extractive+hot",
    "extractive",
    "p1-debug",
    "query-pack",
]
DEFAULT_K_MAX = 32
DEFAULT_D = 256
DEFAULT_EMA = 0.7


def classify_method(*, producer: str, sampled_via: str) -> str:
    if sampled_via == "p2":
        return "p2"
    if sampled_via in {"extractive+hot", "extractive", "hot_set", "p1-debug", "query-pack"}:
        return sampled_via
    if sampled_via == "p1":
        return "digest+p1" if producer == "embed" else "gist-hf+p1"
    return "digest"


def l2_normalize(rows: np.ndarray, eps: float = 1e-8) -> np.ndarray:
    norms = np.linalg.norm(rows, axis=-1, keepdims=True)
    return rows / np.maximum(norms, eps)


def _cosine_adjacent(a: np.ndarray, b: np.ndarray) -> float:
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na < 1e-12 or nb < 1e-12:
        return -1.0
    return float(np.dot(a, b) / (na * nb))


def append_then_pool(
    prev_c: np.ndarray | None,
    new_rows: np.ndarray,
    k_max: int = DEFAULT_K_MAX,
    ema: float = DEFAULT_EMA,
) -> np.ndarray:
    """Append new gist rows, then EMA-merge highest-cosine adjacent pair until k <= k_max."""
    if new_rows.ndim == 1:
        new_rows = new_rows[None, :]
    if prev_c is None or prev_c.size == 0:
        stacked = np.asarray(new_rows, dtype=np.float32)
    else:
        stacked = np.vstack(
            [np.asarray(prev_c, dtype=np.float32), np.asarray(new_rows, dtype=np.float32)]
        )
    while stacked.shape[0] > k_max:
        best_i = 0
        best_sim = -2.0
        for i in range(stacked.shape[0] - 1):
            sim = _cosine_adjacent(stacked[i], stacked[i + 1])
            if sim > best_sim:
                best_sim = sim
                best_i = i
        merged = ema * stacked[best_i] + (1.0 - ema) * stacked[best_i + 1]
        stacked = np.vstack(
            [stacked[:best_i], merged[None, :], stacked[best_i + 2 :]]
        )
    return l2_normalize(stacked.astype(np.float32))


def live_mask(k: int, k_max: int | None = None) -> np.ndarray:
    if k_max is None or k_max == k:
        return np.ones((k,), dtype=np.float32)
    mask = np.zeros((k_max,), dtype=np.float32)
    mask[:k] = 1.0
    return mask
