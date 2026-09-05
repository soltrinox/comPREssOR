import numpy as np

from chat_compressor.store import StateStore


def test_roundtrip_mmap_and_parent_chain(tmp_path) -> None:
    store = StateStore(tmp_path / "state")
    c1 = np.eye(4, 8, dtype=np.float32)
    n1 = store.save(agent_id="a1", C=c1, producer="embed")
    assert n1.t == 1
    assert n1.parent_id is None
    assert n1.C.shape == (4, 8)

    c2 = np.ones((3, 8), dtype=np.float32)
    n2 = store.save(agent_id="a1", C=c2, parent=n1, producer="embed")
    assert n2.t == 2
    assert n2.parent_id == n1.state_id

    latest = store.load_latest("a1")
    assert latest is not None
    assert latest.state_id == n2.state_id
    np.testing.assert_allclose(latest.C, n2.C, atol=1e-5)

    reloaded = store.load(n1.state_id)
    np.testing.assert_allclose(reloaded.C, c1, atol=1e-5)
    chain = store.lineage("a1")
    assert [n.t for n in chain] == [1, 2]
    assert chain[1].parent_id == chain[0].state_id

def test_recipient_meta_roundtrip_and_lineage(tmp_path) -> None:
    """CC-1/M0: recipient fields survive StateStore save/load/lineage; absent ⇒ prior."""
    store = StateStore(tmp_path / "state")
    c1 = np.eye(2, 4, dtype=np.float32)
    n1 = store.save(
        agent_id="r1",
        C=c1,
        producer="embed",
        meta={
            "tool_status": "stub",
            "tokenizer_id": "hashed-ngram",
            "recipient_id": "cursor-grok-4.6-high-fast",
            "recipient_version": "cn_4a91f0",
            "route_decision_id": "urn:mg:routedecision:a1b2c3",
        },
    )
    reloaded = store.load(n1.state_id)
    assert reloaded.meta["recipient_id"] == "cursor-grok-4.6-high-fast"
    assert reloaded.meta["recipient_version"] == "cn_4a91f0"
    assert reloaded.meta["route_decision_id"] == "urn:mg:routedecision:a1b2c3"
    assert reloaded.meta["tool_status"] == "stub"
    assert reloaded.meta["tokenizer_id"] == "hashed-ngram"

    c2 = np.ones((2, 4), dtype=np.float32)
    n2 = store.save(
        agent_id="r1",
        C=c2,
        parent=n1,
        producer="embed",
        meta={
            "tool_status": "stub",
            "tokenizer_id": "hashed-ngram",
            "recipient_id": "other-model",
            "recipient_version": "v2",
            "route_decision_id": "urn:mg:routedecision:zzzz",
        },
    )
    # Absent recipient fields keep prior (empty-meta) behavior.
    c3 = np.zeros((2, 4), dtype=np.float32)
    n3 = store.save(agent_id="r1", C=c3, parent=n2, producer="embed")
    assert n3.meta == {}

    chain = store.lineage("r1")
    assert [n.t for n in chain] == [1, 2, 3]
    assert chain[0].meta["recipient_id"] == "cursor-grok-4.6-high-fast"
    assert chain[1].meta["recipient_id"] == "other-model"
    assert "recipient_id" not in chain[2].meta
    assert chain[0].meta["route_decision_id"] == "urn:mg:routedecision:a1b2c3"
    assert chain[1].meta["recipient_version"] == "v2"



def test_per_recipient_inject_ledger_partitions(tmp_path) -> None:
    """CC-2: inject ledger partitions by recipient_id; absent ⇒ session ledger."""
    from chat_compressor.store import (
        append_inject_history,
        load_inject_history,
        recent_line_hashes,
    )

    agent = tmp_path / "agent"
    agent.mkdir()

    # Legacy / no-recipient path (0.2.0).
    append_inject_history(agent, {"t": 1, "hashes": ["aaaa"], "packed_tokens": 10, "novel_tokens": 10})
    append_inject_history(agent, {"t": 2, "hashes": ["bbbb"], "packed_tokens": 8, "novel_tokens": 4})
    legacy = load_inject_history(agent)
    assert len(legacy) == 2
    assert recent_line_hashes(legacy, k=3) == {"aaaa", "bbbb"}

    # Recipient A and B are isolated.
    append_inject_history(
        agent,
        {"t": 3, "hashes": ["hashA1", "hashA2"], "packed_tokens": 12, "novel_tokens": 12},
        recipient_id="model-a",
    )
    append_inject_history(
        agent,
        {"t": 4, "hashes": ["hashA3"], "packed_tokens": 6, "novel_tokens": 2},
        recipient_id="model-a",
    )
    append_inject_history(
        agent,
        {"t": 5, "hashes": ["hashB1"], "packed_tokens": 9, "novel_tokens": 9},
        recipient_id="model-b",
    )

    hist_a = load_inject_history(agent, recipient_id="model-a")
    hist_b = load_inject_history(agent, recipient_id="model-b")
    assert [h for row in hist_a for h in row["hashes"]] == ["hashA1", "hashA2", "hashA3"]
    assert [h for row in hist_b for h in row["hashes"]] == ["hashB1"]
    # Legacy session ledger untouched by recipient partitions.
    assert len(load_inject_history(agent)) == 2
    # New recipient starts empty.
    assert load_inject_history(agent, recipient_id="model-c") == []
