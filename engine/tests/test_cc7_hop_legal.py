"""CC-7: hop_legal() false with pending tool state."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from chat_compressor.handle import PersistentAgentHandle
from chat_compressor.producer import EmbeddingProducer
from chat_compressor.store import StateStore


def _handle(tmp_path: Path) -> PersistentAgentHandle:
    store = StateStore(tmp_path / "state")
    return PersistentAgentHandle(
        agent_id="hop-legal",
        store=store,
        producer=EmbeddingProducer(d=32, k_max=4),
        k_max=4,
    )


def test_hop_legal_true_at_clean_boundary(tmp_path: Path) -> None:
    h = _handle(tmp_path)
    assert h.hop_legal() is True
    h.step("hello", recipient_id="model-a")
    assert h.hop_legal() is True  # stub tool_status, no pending


def test_hop_legal_false_when_pending_flag_set(tmp_path: Path) -> None:
    h = _handle(tmp_path)
    h.step("hello")
    h.set_pending_tool(True)
    assert h.hop_legal() is False
    h.clear_pending_tool()
    assert h.hop_legal() is True


def test_hop_legal_false_when_meta_pending_tool(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state")
    c = np.eye(2, 4, dtype=np.float32)
    store.save(
        agent_id="m",
        C=c,
        producer="embed",
        meta={"tool_status": "stub", "pending_tool": True},
        k_max=4,
    )
    h = PersistentAgentHandle(
        agent_id="m",
        store=store,
        producer=EmbeddingProducer(d=4, k_max=4),
        k_max=4,
    )
    assert h.hop_legal() is False


def test_hop_legal_false_when_tool_status_pending(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state")
    store.save(
        agent_id="m2",
        C=np.ones((2, 4), dtype=np.float32),
        producer="embed",
        meta={"tool_status": "pending"},
        k_max=4,
    )
    h = PersistentAgentHandle(
        agent_id="m2",
        store=store,
        producer=EmbeddingProducer(d=4, k_max=4),
        k_max=4,
    )
    assert h.hop_legal() is False
