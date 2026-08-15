"""Query-aware hashed-cosine ranker and structure-aware chunks."""

from __future__ import annotations

from chat_compressor.chunks import chunk_text
from chat_compressor.graph import CtxGraph, GraphNode, new_id
from chat_compressor.rank import collect_candidates, rank_chunks, rank_relevant_chunks


def test_chunk_keeps_fence_and_def_signature() -> None:
    text = (
        "# Setup\n"
        "Intro sentence about the module.\n"
        "```python\n"
        "def helper(x):\n"
        "    return x\n"
        "```\n"
        "def pack_forward(hot_set, budget):\n"
        "More prose after the signature. See src/app.py for details.\n"
    )
    chunks = chunk_text(text, max_chunks=16)
    assert chunks[0].startswith("#")
    joined = "\n".join(chunks)
    assert "```python" in joined
    assert any("def pack_forward(hot_set, budget):" in c for c in chunks)
    assert "src/app.py" in joined
    # path not split into 'src/app' + 'py'
    assert "src/app.py" in joined


def test_query_a_vs_query_b_different_top_chunks() -> None:
    chunks = [
        "SQL inner join customers table on customer_id for the reporting query.",
        "Python def encode_rows(text) hashes n-gram embeddings offline.",
        "Grocery list remains open: milk, bread, and buy groceries.",
        "Cloud Run health check returned 200 from /api/health.",
    ]
    q_sql = "How does the SQL join on customers work?"
    q_groc = "What grocery items are still open on the list?"
    top_sql = [r.text for r in rank_chunks(q_sql, chunks)[:2]]
    top_groc = [r.text for r in rank_chunks(q_groc, chunks)[:2]]
    assert top_sql[0] != top_groc[0]
    assert "SQL" in top_sql[0] or "join" in top_sql[0].lower()
    assert "grocery" in top_groc[0].lower() or "milk" in top_groc[0].lower()


def test_typed_projection_openitem_fact_path_event() -> None:
    graph = CtxGraph()
    graph.ingest_turn("user", 'Create todo "buy groceries". See docs/README.md and fixtures/x.jsonl.', 0)
    graph.insert(
        GraphNode(
            id=new_id("event"),
            kind="Event",
            label="tool-error",
            summary="tool error: pytest missing safetensors",
            attrs={"tool_status": "error"},
        )
    )
    lines = graph.typed_projection("groceries readme", hot_set="")
    joined = "\n".join(lines)
    assert "OpenItem:" in joined
    assert "Path:" in joined or "Fact:" in joined
    assert "Event:" in joined
    assert "pytest missing safetensors" in joined


def test_collect_candidates_includes_durable_facts() -> None:
    graph = CtxGraph()
    graph.ingest_turn("user", "Please update fixtures/synthetic-generic.jsonl after the grocery pass.", 0)
    cands = collect_candidates(graph)
    blob = " ".join(cands).lower()
    assert "synthetic-generic.jsonl" in blob or "grocery" in blob


def test_query_prefers_decision_fact_over_path() -> None:
    graph = CtxGraph()
    graph.insert(
        GraphNode(
            id=new_id("fact"),
            kind="Fact",
            label="src/app.py",
            summary="path: src/app.py",
            attrs={"durable": True, "kind_hint": "path"},
        )
    )
    graph.insert(
        GraphNode(
            id=new_id("fact"),
            kind="Fact",
            label="decision: use hashed n-gram rank",
            summary="decision: use hashed n-gram rank for query-aware packing",
            attrs={"durable": True, "kind_hint": "decision"},
        )
    )
    query = "what decision did we make about ranking?"
    cands = collect_candidates(graph, query=query)
    blob = " ".join(cands).lower()
    assert "decision" in blob
    assert "hashed n-gram" in blob
    ranked = rank_relevant_chunks(query, cands)
    assert ranked
    top = ranked[0].text.lower()
    assert "decision" in top or "rank" in top
