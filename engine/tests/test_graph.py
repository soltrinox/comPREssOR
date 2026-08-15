from pathlib import Path

from chat_compressor.graph import CtxGraph
from chat_compressor.parse import parse_jsonl, turns_to_raw_text

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "synthetic-generic.jsonl"


def test_ingest_and_hot_set_ratio() -> None:
    graph = CtxGraph()
    turns = parse_jsonl(FIXTURE)
    raw = turns_to_raw_text(turns)
    for turn in turns:
        graph.ingest_turn(turn.role, turn.text, turn.index)
    hot = graph.hot_set()
    assert hot
    assert len(hot) < len(raw)
    assert any(n.kind == "Turn" for n in graph.active_nodes())
    assert graph.to_dict()["schema"] == "ctx-graph/v1"


def test_supersede_closes_old_node() -> None:
    graph = CtxGraph()
    first = graph.ingest_turn("user", 'Create todo "alpha"', 0)
    old = next(n for n in graph.nodes if n.kind == "OpenItem" and n.label == "alpha")
    graph.ingest_turn("user", 'Mark "alpha" done', 1)
    old_after = next(n for n in graph.nodes if n.id == old.id)
    assert old_after.status == "superseded"
    assert old_after.valid_end is not None
    assert any(e.rel == "supersedes" for e in graph.edges)
    assert first.id


def test_heading_fact_durable() -> None:
    graph = CtxGraph()
    graph.ingest_turn("user", "## Inventory Clerk\nTrack household items.", 0)
    durable = [n for n in graph.active_nodes() if n.kind == "Fact" and n.attrs.get("durable")]
    assert any("Inventory" in n.label for n in durable)


def test_completion_verb_supersedes_without_quotes() -> None:
    graph = CtxGraph()
    graph.ingest_turn("user", 'Create todo "wire hooks"', 0)
    graph.ingest_turn("assistant", "Implemented wire hooks in the install script.", 1)
    items = [n for n in graph.nodes if n.kind == "OpenItem" and n.label.lower() == "wire hooks"]
    assert items
    # latest supersession should mark done
    assert any(n.attrs.get("state") == "done" for n in items)
