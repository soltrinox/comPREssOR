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


def test_recipient_changed_clears_suppression_and_blocks_skip() -> None:
    """CC-3/CC-4: recipient change resets suppress; never skip on hop."""
    from chat_compressor.pack import line_hash, pack_forward

    line = "OpenItem: open: milk"
    h = line_hash(line)
    # Same hashes would suppress without recipient_changed.
    suppressed = pack_forward(
        hot_set="",
        typed_lines=[line],
        budget=1024,
        recent_hashes={h},
        openitem_changed=False,
        node_superseded=False,
        recipient_changed=False,
        allow_skip=True,
        skip_floor_tokens=64,
    )
    # With typed content suppressed and packed small, skip is allowed.
    assert suppressed.method == "skip" or h not in suppressed.line_hashes

    hopped = pack_forward(
        hot_set="",
        typed_lines=[line],
        budget=1024,
        recent_hashes={h},
        openitem_changed=False,
        node_superseded=False,
        recipient_changed=True,
        allow_skip=True,
        skip_floor_tokens=64,
    )
    assert hopped.method != "skip"
    assert line.lower() in hopped.text.lower() or any(
        line_hash(x) == h for x in hopped.text.splitlines() if x.strip()
    )
    assert h in hopped.line_hashes


def test_first_recipient_turn_never_skips() -> None:
    """CC-4: allow_skip false / recipient_changed true ⇒ no skip even under floor."""
    from chat_compressor.pack import pack_forward

    packed = pack_forward(
        hot_set="x",
        typed_lines=[],
        budget=1024,
        recent_hashes=set(),
        openitem_changed=False,
        node_superseded=False,
        recipient_changed=True,
        allow_skip=True,
        skip_floor_tokens=10_000,
    )
    assert packed.method != "skip"
    assert packed.text
