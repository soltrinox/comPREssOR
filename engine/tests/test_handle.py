from chat_compressor.handle import PersistentAgentHandle
from chat_compressor.producer import EmbeddingProducer
from chat_compressor.store import StateStore


def test_three_steps_bound_k_and_latest_t(tmp_path) -> None:
    store = StateStore(tmp_path / "state")
    handle = PersistentAgentHandle(
        agent_id="h1",
        store=store,
        producer=EmbeddingProducer(d=256, k_max=8),
        k_max=8,
    )
    for i in range(3):
        handle.step(f"turn {i} add item note {i} " * 20)
    latest = handle.latest()
    assert latest is not None
    assert latest.t == 3
    assert latest.k <= 8
    assert latest.C.shape[1] == 256
    chain = store.lineage("h1")
    assert chain[0].parent_id is None
    assert chain[1].parent_id == chain[0].state_id
    assert chain[2].parent_id == chain[1].state_id

    payload = handle.sample_for("cursor-sdk")
    assert payload.kind == "text"
    assert payload.method in {"hot_set", "extractive+hot", "extractive", "query-pack"}
    assert payload.packed_tokens <= payload.budget
    span_path = tmp_path / "state" / "h1" / "t0001.spans.json"
    assert span_path.is_file()
    expanded = handle.expand_spans("item note", k=2)
    assert isinstance(expanded, list)
    assert len(expanded) <= 2
    # Graph flush deferred: not every step writes graph_tN.json when GRAPH_FLUSH_EVERY>1
    assert latest.t == 3


def test_deferred_graph_flush(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GRAPH_FLUSH_EVERY", "5")
    store = StateStore(tmp_path / "state")
    handle = PersistentAgentHandle(
        agent_id="flush",
        store=store,
        producer=EmbeddingProducer(d=64, k_max=8),
        k_max=8,
    )
    out1 = handle.step("first turn with enough content for embedding rows here.")
    assert out1.graph_flushed is False  # t=1 % 5 != 0
    out5 = None
    for i in range(2, 6):
        out5 = handle.step(f"turn {i} continue the conversation with substance.")
    assert out5 is not None
    assert out5.t == 5
    assert out5.graph_flushed is True
    forced = handle.step("force", flush_graph=True)
    assert forced.graph_flushed is True
