"""In-process PersistentAgentHandle: load C_{t-1}, step, persist C_t."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from chat_compressor.chunks import chunk_text
from chat_compressor.graph import CtxGraph
from chat_compressor.producer import make_producer
from chat_compressor.rank import rank_chunks
from chat_compressor.pack import (
    WARMUP_TURNS,
    adaptive_budget,
    cross_turn_dedup_enabled,
    forward_budget,
)
from chat_compressor.store import (
    StateNode,
    StateStore,
    append_inject_history,
    load_inject_history,
    recent_line_hashes,
    rolling_novelty,
    write_span_sidecar,
)
from chat_compressor.translate.adapter import GatedMLPAdapter
from chat_compressor.translate.vocab_bridge import Pattern1Bridge, SampledPayload


def graph_flush_every() -> int:
    raw = os.environ.get("GRAPH_FLUSH_EVERY", "").strip()
    if not raw:
        return 5
    try:
        return max(1, int(raw))
    except ValueError:
        return 5


@dataclass
class AgentOutput:
    state_id: str
    C: np.ndarray
    t: int
    parent_id: str | None
    graph_path: str | None = None
    compress_ms: float = 0.0
    persist_ms: float = 0.0
    graph_flushed: bool = False


class PersistentAgentHandle:
    def __init__(
        self,
        agent_id: str,
        store: StateStore,
        producer: Any | None = None,
        translator: Pattern1Bridge | None = None,
        adapter: GatedMLPAdapter | None = None,
        graph: CtxGraph | None = None,
        k_max: int = 32,
    ) -> None:
        self.agent_id = agent_id
        self.store = store
        self.producer = producer or make_producer(k_max=k_max)
        if translator is not None:
            self.translator = translator
        else:
            d = int(getattr(self.producer, "d", 256) or 256)
            self.translator = Pattern1Bridge(d=d)
        self.adapter = adapter
        self.graph = graph if graph is not None else CtxGraph()
        self.k_max = k_max
        self._turn_index = 0
        self._last_graph_path: str | None = None
        self.last_sample_ms: float = 0.0

    def _agent_dir(self) -> Path:
        return Path(self.store.root) / self.agent_id

    def _latest_graph_path(self) -> Path:
        return self._agent_dir() / "graph.json"

    def step(
        self,
        new_input: str,
        role: str = "user",
        *,
        flush_graph: bool | None = None,
    ) -> AgentOutput:
        prev = self.store.load_latest(self.agent_id)
        t_next = (prev.t + 1) if prev else 1

        t0 = time.perf_counter()
        result = self.producer.compress(prev.C if prev is not None else None, new_input)
        compress_ms = (time.perf_counter() - t0) * 1000.0

        self.graph.ingest_turn(role, new_input, self._turn_index)
        self._turn_index += 1

        every = graph_flush_every()
        versioned = flush_graph if flush_graph is not None else (t_next % every == 0)

        # Always write compact working graph so cross-process hooks can reload.
        latest = self._latest_graph_path()
        self.graph.save(latest)
        self._last_graph_path = str(latest)
        graph_path: Path = latest

        if versioned:
            snap = self._agent_dir() / f"graph_t{t_next}.json"
            self.graph.save(snap)
            graph_path = snap
            self._last_graph_path = str(snap)

        t1 = time.perf_counter()
        node = self.store.save(
            agent_id=self.agent_id,
            C=result.C,
            M=result.M,
            parent=prev,
            producer=result.producer,
            graph_path=graph_path,
            KV=result.KV,
            meta={"tool_status": "stub", "tokenizer_id": "hashed-ngram"},
            k_max=self.k_max,
        )
        persist_ms = (time.perf_counter() - t1) * 1000.0
        spans = [
            {"text": c, "row": i}
            for i, c in enumerate(chunk_text(new_input, max_chunks=32))
            if (c or "").strip()
        ]
        write_span_sidecar(node.blob_path, spans)
        return AgentOutput(
            state_id=node.state_id,
            C=node.C,
            t=node.t,
            parent_id=node.parent_id,
            graph_path=node.graph_path,
            compress_ms=compress_ms,
            persist_ms=persist_ms,
            graph_flushed=bool(versioned),
        )

    def latest(self) -> StateNode | None:
        return self.store.load_latest(self.agent_id)

    def flush_graph(self) -> str | None:
        """Force-write working + versioned graph beside the latest state."""
        prev = self.latest()
        t = prev.t if prev is not None else max(1, self._turn_index)
        latest = self._latest_graph_path()
        self.graph.save(latest)
        snap = self._agent_dir() / f"graph_t{t}.json"
        self.graph.save(snap)
        self._last_graph_path = str(snap)
        return self._last_graph_path

    def sample_for(self, target: str, query: str | None = None) -> SampledPayload:
        """cursor-sdk => packed HOT_SET/typed/ranked text. local:<id> may return C_B floats."""
        node = self.latest()
        q = (query or "").strip() or self._last_user_query()
        hot = self.graph.hot_set(query=q or None)
        window = self.graph.window_text()
        typed = self.graph.typed_projection(q or None, hot_set=hot)
        history = load_inject_history(self._agent_dir())
        t = int(node.t) if node is not None else 0
        novelty = rolling_novelty(history, k=3)
        budget = adaptive_budget(t, novelty, cap=forward_budget())
        if not cross_turn_dedup_enabled():
            budget = forward_budget()
        last = history[-1] if history else {}
        openitem_changed = True
        node_superseded = False
        recent: set[str] = set()
        if cross_turn_dedup_enabled() and history:
            prev_sig = str(last.get("openitem_sig") or "")
            openitem_changed = self.graph.openitem_signature() != prev_sig
            node_superseded = self.graph.supersede_count() > int(last.get("supersede_count") or 0)
            recent = recent_line_hashes(history, k=3)
        allow_skip = bool(cross_turn_dedup_enabled() and t > WARMUP_TURNS)
        pack_kwargs = {
            "hot_set": hot,
            "window_text": window,
            "query": q or None,
            "typed_lines": typed,
            "graph": self.graph,
            "budget": budget,
            "recent_hashes": recent,
            "openitem_changed": openitem_changed,
            "node_superseded": node_superseded,
            "allow_skip": allow_skip,
        }
        t0 = time.perf_counter()
        try:
            if node is None or target == "cursor-sdk":
                sampled = self.translator.sample_text(
                    None if node is None else node.C,
                    max_extractive_tokens=self.k_max,
                    **pack_kwargs,
                )
                if sampled.method != "skip" and sampled.line_hashes:
                    append_inject_history(
                        self._agent_dir(),
                        {
                            "state_id": None if node is None else node.state_id,
                            "t": t,
                            "hashes": list(sampled.line_hashes),
                            "text": (sampled.text or "")[:8000],
                            "openitem_sig": self.graph.openitem_signature(),
                            "supersede_count": self.graph.supersede_count(),
                            "packed_tokens": int(sampled.packed_tokens),
                            "novel_tokens": int(sampled.novel_tokens),
                            "dup_suppressed_tokens": int(sampled.dup_suppressed_tokens),
                        },
                    )
                return sampled
            if target.startswith("local:"):
                if self.adapter is not None:
                    c_b = self.adapter.forward(node.C)
                    return SampledPayload(kind="latent", text="", C=c_b, method="p2")
                c_b = self.translator.expectation_embed(node.C)
                return SampledPayload(kind="latent", text="", C=c_b, method="p1")
            raise ValueError(f"unknown sample target {target}")
        finally:
            self.last_sample_ms = (time.perf_counter() - t0) * 1000.0

    def _last_user_query(self) -> str:
        turns = [
            n
            for n in self.graph.active_nodes()
            if n.kind == "Turn" and (n.attrs or {}).get("role") == "user"
        ]
        if not turns:
            return ""
        turns.sort(key=lambda n: (n.valid_start, n.attrs.get("index", 0)))
        return (turns[-1].summary or "").strip()

    def expand_spans(self, query: str, k: int = 4) -> list[str]:
        """Local-only: nearest verbatim chunks from tNNNN.spans.json sidecars."""
        texts: list[str] = []
        agent_dir = self._agent_dir()
        if not agent_dir.is_dir():
            return []
        for path in sorted(agent_dir.glob("t*.spans.json")):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(raw, list):
                continue
            for item in raw:
                if isinstance(item, dict) and str(item.get("text") or "").strip():
                    texts.append(str(item["text"]).strip())
        ranked = rank_chunks(query, texts)
        seen: set[str] = set()
        out: list[str] = []
        for row in ranked:
            key = row.text.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(row.text)
            if len(out) >= max(1, int(k)):
                break
        return out
