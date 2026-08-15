"""Token-budget packer tests."""

from __future__ import annotations

from chat_compressor.pack import pack_forward


def test_hot_set_always_prefix_and_budget_respected() -> None:
    hot = "OpenItem bread: open: bread\nFact docs/README.md: path: docs/README.md"
    typed = ["OpenItem: open: bread", "Fact: grocery planning sentence here"]
    chunks = ["SQL join customers table " * 20, "Python hashed n-gram embed " * 20]
    packed = pack_forward(hot_set=hot, typed_lines=typed, ranked_chunks=chunks, budget=64)
    assert packed.text.startswith("HOT_SET:")
    assert packed.packed_tokens <= packed.budget
    assert packed.budget == 64
    assert packed.rate <= 1.0 + 1e-9
    assert "bread" in packed.text.lower()


def test_typed_then_chunks_order() -> None:
    packed = pack_forward(
        hot_set="OpenItem milk: open: milk",
        typed_lines=["OpenItem: open: milk", "Path: docs/README.md"],
        ranked_chunks=["ranked chunk about SQL joins"],
        budget=1024,
    )
    assert packed.text.startswith("HOT_SET:")
    hot_idx = packed.text.index("HOT_SET:")
    path_idx = packed.text.index("Path: docs/README.md")
    chunk_idx = packed.text.index("ranked chunk about SQL joins")
    assert hot_idx < path_idx < chunk_idx
    assert packed.method == "query-pack"
