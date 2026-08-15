"""Fork-merge extractors: design/decision facts and labeled OpenItems."""

from __future__ import annotations

from chat_compressor.graph import CtxGraph


def test_decision_and_recommended_structure_yield_durable_facts() -> None:
    graph = CtxGraph()
    graph.ingest_turn(
        "assistant",
        "Recommended structure\n"
        "- structure: term -> definition -> example\n"
        "decision: keep hashed n-gram ranking as the offline default\n",
        0,
    )
    durable = [
        n
        for n in graph.active_nodes()
        if n.kind == "Fact" and n.attrs.get("durable")
    ]
    hints = {str(n.attrs.get("kind_hint")) for n in durable}
    bodies = " ".join(f"{n.label} {n.summary}".lower() for n in durable)
    assert "decision" in hints
    assert "design" in hints
    assert "hashed n-gram" in bodies
    assert "term" in bodies or "structure" in bodies


def test_todo_line_yields_openitem() -> None:
    graph = CtxGraph()
    graph.ingest_turn("user", "todo: restore ADC before terraform apply", 0)
    items = [n for n in graph.active_nodes() if n.kind == "OpenItem"]
    assert items
    assert any("adc" in n.label.lower() for n in items)
    assert all(n.attrs.get("state", "open") != "done" for n in items)


def test_topic_line_is_additional_topic_source() -> None:
    graph = CtxGraph()
    graph.ingest_turn("user", "Topic: glossary rewrite\ngoal: standardize entry fields", 0)
    topics = [n for n in graph.active_nodes() if n.kind == "Topic"]
    labels = " ".join(n.label.lower() for n in topics)
    assert "glossary" in labels or "entry fields" in labels
