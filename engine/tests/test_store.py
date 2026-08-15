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
