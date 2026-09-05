"""M1 exit: hop at turn 20 delivers full unsuppressed full-budget payload; no-hop matches 0.2.0."""

from __future__ import annotations

from pathlib import Path

import pytest

from chat_compressor.handle import PersistentAgentHandle
from chat_compressor.pack import WARMUP_TURNS, adaptive_budget, forward_budget
from chat_compressor.producer import EmbeddingProducer
from chat_compressor.store import (
    load_inject_history,
    recent_line_hashes,
    StateStore,
)


def _handle(tmp_path: Path, agent_id: str) -> PersistentAgentHandle:
    store = StateStore(tmp_path / "state")
    return PersistentAgentHandle(
        agent_id=agent_id,
        store=store,
        producer=EmbeddingProducer(d=64, k_max=8),
        k_max=8,
    )


def _turn_text(i: int) -> str:
    # Stable open items early, then distinctive content in late turns for hash checks.
    return (
        f'Turn {i}: Create todo "buy groceries" and add "milk" and "bread". '
        f'Also note unique-marker-turn-{i} for dedup tracking with substance.'
    )


def test_m1_hop_at_turn_20_full_unsuppressed_full_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Scripted hop: 19 turns model-a, turn 20 model-b ⇒ full / unsuppressed / full budget."""
    monkeypatch.setenv("CHAT_COMPRESSOR_CROSS_TURN_DEDUP", "1")
    monkeypatch.delenv("CHAT_COMPRESSOR_INJECT_P1", raising=False)
    monkeypatch.setenv("CHAT_COMPRESSOR_FORWARD_BUDGET", "1024")

    handle = _handle(tmp_path, "hop-session")
    model_a = "model-a"
    model_b = "model-b"

    late_a_hashes: set[str] = set()
    for i in range(1, 20):
        handle.step(_turn_text(i), recipient_id=model_a, recipient_version="v1")
        payload = handle.sample_for("cursor-sdk")
        assert payload.kind == "text"
        if i >= 17 and payload.line_hashes:
            late_a_hashes.update(payload.line_hashes)

    assert late_a_hashes, "expected inject hashes from late model-a turns"

    # Confirm model-a ledger would suppress those hashes on a continued turn.
    hist_a = load_inject_history(handle._agent_dir(), recipient_id=model_a)
    suppress_a = recent_line_hashes(hist_a, k=3)
    assert late_a_hashes & suppress_a, "late A hashes should sit in A's recent suppress set"

    # Turn 20: hop to model-b.
    handle.step(_turn_text(20), recipient_id=model_b, recipient_version="v1")
    hop = handle.sample_for("cursor-sdk")

    assert hop.method != "skip", "CC-4: first turn for recipient must not skip"
    assert hop.text, "hop payload must be non-empty"
    assert hop.budget == forward_budget(), "CC-5: late joiner gets full (warmup) budget"
    assert hop.packed_tokens > 0

    # CC-2/CC-3: B's ledger was empty / suppress cleared ⇒ content not hole-punched.
    # Markers from recent A turns should still be packable for B.
    body = hop.text.lower()
    assert (
        "unique-marker-turn-17" in body
        or "unique-marker-turn-18" in body
        or "unique-marker-turn-19" in body
        or "groceries" in body
        or "bread" in body
    ), "hop payload should include context A had already injected"

    # B partition is independent of A.
    hist_b = load_inject_history(handle._agent_dir(), recipient_id=model_b)
    assert hist_b, "model-b should have its own inject rows after hop sample"
    assert load_inject_history(handle._agent_dir(), recipient_id=model_a), "model-a ledger preserved"

    # recipient_t for B is 1 ⇒ adaptive_budget equals full cap.
    assert adaptive_budget(1, 0.0, cap=1024) == 1024
    assert handle._recipient_turn_count(model_b) == 1
    assert handle._recipient_turn_count(model_a) == 19


def test_m1_no_hop_matches_legacy_token_accounting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No-hop with recipient_id tracks same budgets/tokens as absent-recipient (0.2.0) path."""
    monkeypatch.setenv("CHAT_COMPRESSOR_CROSS_TURN_DEDUP", "1")
    monkeypatch.delenv("CHAT_COMPRESSOR_INJECT_P1", raising=False)
    monkeypatch.setenv("CHAT_COMPRESSOR_FORWARD_BUDGET", "1024")

    legacy = _handle(tmp_path, "legacy")
    tagged = _handle(tmp_path, "tagged")

    legacy_rows: list[dict] = []
    tagged_rows: list[dict] = []

    for i in range(1, 21):
        text = _turn_text(i)
        legacy.step(text)
        tagged.step(text, recipient_id="model-a", recipient_version="v1")

        lp = legacy.sample_for("cursor-sdk")
        tp = tagged.sample_for("cursor-sdk")

        legacy_rows.append(
            {
                "t": i,
                "method": lp.method,
                "budget": lp.budget,
                "packed_tokens": lp.packed_tokens,
                "novel_tokens": lp.novel_tokens,
                "dup_suppressed_tokens": lp.dup_suppressed_tokens,
            }
        )
        tagged_rows.append(
            {
                "t": i,
                "method": tp.method,
                "budget": tp.budget,
                "packed_tokens": tp.packed_tokens,
                "novel_tokens": tp.novel_tokens,
                "dup_suppressed_tokens": tp.dup_suppressed_tokens,
            }
        )

    # Budget schedule must match (session t == per-recipient t when single recipient).
    assert [r["budget"] for r in legacy_rows] == [r["budget"] for r in tagged_rows]
    # Token accounting within tight equality for identical inputs.
    assert [r["packed_tokens"] for r in legacy_rows] == [r["packed_tokens"] for r in tagged_rows]
    assert [r["method"] for r in legacy_rows] == [r["method"] for r in tagged_rows]

    # After warmup, budgets may decay; first WARMUP_TURNS stay at full cap.
    for r in legacy_rows[:WARMUP_TURNS]:
        assert r["budget"] == forward_budget()


def test_cc4_first_recipient_sample_never_skip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CHAT_COMPRESSOR_CROSS_TURN_DEDUP", "1")
    handle = _handle(tmp_path, "first")
    # Build a session that would be skip-eligible for a continued recipient.
    for i in range(1, 6):
        handle.step(_turn_text(i), recipient_id="model-a")
        handle.sample_for("cursor-sdk")
    handle.step(_turn_text(6), recipient_id="model-b")
    payload = handle.sample_for("cursor-sdk")
    assert payload.method != "skip"
    assert payload.budget == forward_budget()


def test_absent_recipient_keeps_session_ledger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Absent recipient_id ⇒ 0.2.0 session-scoped inject_history.turns."""
    monkeypatch.setenv("CHAT_COMPRESSOR_CROSS_TURN_DEDUP", "1")
    handle = _handle(tmp_path, "legacy-ledger")
    handle.step(_turn_text(1))
    handle.sample_for("cursor-sdk")
    handle.step(_turn_text(2))
    handle.sample_for("cursor-sdk")
    legacy = load_inject_history(handle._agent_dir())
    assert len(legacy) >= 1
    assert load_inject_history(handle._agent_dir(), recipient_id="nope") == []
