"""CC-8: export_bundle / import_bundle round-trip."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from chat_compressor.bundle import export_bundle, import_bundle
from chat_compressor.handle import PersistentAgentHandle
from chat_compressor.producer import EmbeddingProducer
from chat_compressor.store import (
    StateStore,
    append_inject_history,
    load_inject_history,
)


def test_bundle_round_trip_full(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state")
    h = PersistentAgentHandle(
        agent_id="agent-a",
        store=store,
        producer=EmbeddingProducer(d=32, k_max=4),
        k_max=4,
    )
    h.step("Create todo buy milk", recipient_id="model-a", recipient_version="v1")
    h.step("Add bread to list", recipient_id="model-a", recipient_version="v1")
    append_inject_history(
        h._agent_dir(),
        {"t": 1, "hashes": ["abc"], "packed_tokens": 10, "novel_tokens": 10},
        recipient_id="model-a",
    )
    # Capture pre-export graph hot_set / typed for behavioral check.
    hot_before = h.graph.hot_set()
    typed_before = h.graph.typed_projection(None)

    dest = tmp_path / "bundle.v1"
    export_bundle(store, "agent-a", dest)
    assert (dest / "manifest.json").is_file()
    assert (dest / "graph.json").is_file()
    assert (dest / "lineage.json").is_file()
    assert (dest / "inject_ledger.json").is_file()
    assert list((dest / "states").glob("t*.safetensors"))

    store2 = StateStore(tmp_path / "state2")
    result = import_bundle(
        dest,
        store2,
        expected_producer="embed",
        expected_d=32,
    )
    assert result.mode == "full"
    assert result.producer_matched is True
    assert result.states_imported == 2
    assert result.graph_imported is True
    assert result.ledger_imported is True

    chain = store2.lineage("agent-a")
    assert len(chain) == 2
    assert chain[0].meta.get("recipient_id") == "model-a"
    ledger = load_inject_history(Path(store2.root) / "agent-a", recipient_id="model-a")
    assert ledger and ledger[0].get("hashes") == ["abc"]

    # Reload graph and check projections unchanged.
    from chat_compressor.graph import CtxGraph

    g2 = CtxGraph.load(Path(store2.root) / "agent-a" / "graph.json")
    assert g2.hot_set() == hot_before
    assert g2.typed_projection(None) == typed_before


def test_bundle_producer_mismatch_graph_only(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state")
    c = np.eye(2, 8, dtype=np.float32)
    store.save(agent_id="x", C=c, producer="embed", k_max=8)
    (Path(store.root) / "x" / "graph.json").write_text(
        json.dumps({"schema": "ctx-graph/v1", "nodes": [], "edges": []}) + "\n",
        encoding="utf-8",
    )
    dest = tmp_path / "b"
    export_bundle(store, "x", dest)
    store2 = StateStore(tmp_path / "other")
    result = import_bundle(
        dest, store2, expected_producer="other-producer", expected_d=8
    )
    assert result.mode == "graph_only"
    assert result.producer_matched is False
    assert result.states_imported == 0
    assert result.graph_imported is True
    assert "mismatch" in result.notes.lower()
