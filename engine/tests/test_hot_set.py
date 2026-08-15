from pathlib import Path

from chat_compressor.graph import CtxGraph, ingest_turns
from chat_compressor.parse import parse_jsonl, turns_to_raw_text

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "synthetic-generic.jsonl"


def test_hot_set_shorter_than_raw() -> None:
    turns = parse_jsonl(FIXTURE)
    graph = ingest_turns(CtxGraph(), turns)
    raw = turns_to_raw_text(turns)
    hot = graph.hot_set(max_chars=400)
    assert hot
    assert len(hot) < len(raw)
    assert "OpenItem" in hot or "Fact" in hot or "Turn" in hot
