"""Append-only ctx-graph/v1 with insert, supersede, prune, and hot-set text."""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from chat_compressor.extractive import (
    PATH_RE as PATH_FACT_RE,
    PROPER_NOUN_RE,
    jaccard,
    keyword_set,
)

SCHEMA_ID = "ctx-graph/v1"
KINDS = ("Turn", "Topic", "Fact", "OpenItem", "Event")
RELS = ("mentions", "contains", "continues", "supersedes", "derived_from")
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
ITEM_RE = re.compile(r"[\"']([^\"']{2,80})[\"']")
OPEN_HINT_RE = re.compile(r"\b(todo|open|add|create|remain|left|item)\b", re.I)
DONE_ITEM_RE = re.compile(
    r"(?:mark(?:ed)?|completed?)\s+[\"']([^\"']+)[\"']"
    r"|[\"']([^\"']+)[\"']\s+(?:done|complete)"
    r"|completed[:\s]+[\"']([^\"']+)[\"']",
    re.I,
)
# Completion verbs that can supersede OpenItems by bare label (no quotes required).
DONE_VERB_RE = re.compile(
    r"\b(?:drafted|implemented|verified|completed|marked)\s+[\"']?([^\"'\n,]{2,80})[\"']?",
    re.I,
)
HEADING_FACT_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.M)
FENCE_RE = re.compile(r"```[^\n]*\n.*?```", re.S)
CHECKBOX_RE = re.compile(r"^[\s]*[-*]\s+\[([ xX])\]\s+(.+)$", re.M)
TODO_LINE_RE = re.compile(r"\bTODO:\s*(.+)$", re.M | re.I)
NEXT_LINE_RE = re.compile(r"^\s*next:\s*(.+)$", re.M | re.I)
BULLET_RE = re.compile(r"^\s*[-*]\s+(?:\[(?: |x|X)\]\s+)?(.+)$")
NUMBERED_RE = re.compile(r"^\s*\d+\.\s+(.+)$")
DEFERRED_HINT_RE = re.compile(
    r"\b(deferred|out of scope|left unresolved|left alone|untouched because)\b",
    re.I,
)
DEFERRED_HEADING_RE = re.compile(
    r"\b(left unresolved|deferred|out of scope|unresolved)\b",
    re.I,
)
ACTION_ITEM_RE = re.compile(
    r"\b(should|must|need to|fix|add|move|keep|treat|impose|defer|todo)\b",
    re.I,
)
DECISION_BOOST_RE = re.compile(
    r"\b(decided|chose|instead of|because|so that|constraint|invariant|"
    r"must not|rather than|the fix is|impose|should not|reveal rule|"
    r"contract|policy)\b",
    re.I,
)
TRADEOFF_RE = re.compile(
    r"\b(vs\.?|versus|trade-?off|rather than|instead of|compared to)\b",
    re.I,
)
NUMERIC_CLAIM_RE = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:pages?|%|percent|tokens?|chars?|hours?|ms|"
    r"kb|mb|lines?|chapters?|turns?)\b",
    re.I,
)
IDENT_RE = re.compile(
    r"\b(phi|φ|part ii|part i|tier-?\d|c\d{2}-\d{2}|eni6ma|unicity|"
    r"hourglass|shannon)\b",
    re.I,
)
DEFINE_RE = re.compile(
    r"\b(is defined as|means that|defines |definition|fix:|replaces|maps? that)\b|"
    r"\b\w+ is a \b",
    re.I,
)
PREAMBLE_RE = re.compile(
    r"^\s*(let me|i'll|i will|i'm going to|i am going to|reading|checking|"
    r"running|thanks|thank you|got it|sure[,.]|looking at|let's see|"
    r"i can |i'm finding|i read )\b",
    re.I,
)
PREAMBLE_LIST = (
    "let me",
    "i'll",
    "i will",
    "reading",
    "checking",
    "running",
    "thanks",
    "thank you",
    "got it",
    "looking at",
    "let's see",
)
TOPIC_LINE_RE = re.compile(r"^[ \t]*(?:topic|goal|workstream|task)[ \t]*:[ \t]*(.+)$", re.I | re.M)
DESIGN_HEADING_RE = re.compile(
    r"\b(?:recommended structure|template|decision|design|glossary design)\b",
    re.I,
)
DESIGN_LINE_RE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:(structure|entry fields|fields|recommendation|decision|design)\s*[=:]\s*)?(.+)$",
    re.I,
)
OPEN_LINE_RE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:open item|todo|remaining|follow-up|next)\s*:\s*(.+)$",
    re.I | re.M,
)
DONE_LINE_RE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:completed|done|fixed|resolved|validation)\s*:\s*(.+)$",
    re.I | re.M,
)
OUTCOME_RE = re.compile(
    r"\b(?:"
    r"\d+\s+(?:entries?\s+standardized|broken\s+links?)"
    r"|0\s+broken\s+links?"
    r"|Ch\d+\s+[A-Z]{1,4}-\d+\s+link\s+fixed"
    r"|validation\s+passed"
    r"|fixed\s+[\w./#-]+"
    r")\b",
    re.I,
)

MAX_ACTIVE_TURNS = 32
MAX_ACTIVE_NON_DURABLE_FACTS = 48
MAX_ACTIVE_DURABLE_FACTS = 32
PER_TURN_PATH_CAP = 8
HOT_SET_OPEN_SHARE = 0.40
HOT_SET_DECISION_SHARE = 0.40
HOT_SET_PATH_HEADING_SHARE = 0.20


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"urn:ctx:{prefix}:{uuid.uuid4()}"


@dataclass
class GraphNode:
    id: str
    kind: str
    label: str
    summary: str = ""
    status: str = "active"
    valid_start: str = ""
    valid_end: str | None = None
    attrs: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "label": self.label,
            "summary": self.summary,
            "status": self.status,
            "valid_start": self.valid_start,
            "valid_end": self.valid_end,
            "attrs": dict(self.attrs),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GraphNode:
        return cls(
            id=str(data["id"]),
            kind=str(data["kind"]),
            label=str(data.get("label", "")),
            summary=str(data.get("summary", "")),
            status=str(data.get("status", "active")),
            valid_start=str(data.get("valid_start", "")),
            valid_end=data.get("valid_end"),
            attrs=dict(data.get("attrs") or {}),
        )


@dataclass
class GraphEdge:
    id: str
    src: str
    dst: str
    rel: str
    valid_start: str = ""
    valid_end: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "src": self.src,
            "dst": self.dst,
            "rel": self.rel,
            "valid_start": self.valid_start,
            "valid_end": self.valid_end,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GraphEdge:
        return cls(
            id=str(data["id"]),
            src=str(data["src"]),
            dst=str(data["dst"]),
            rel=str(data["rel"]),
            valid_start=str(data.get("valid_start", "")),
            valid_end=data.get("valid_end"),
        )


class CtxGraph:
    """In-memory ctx-graph. Writes are append-only; supersede closes intervals."""

    def __init__(self) -> None:
        self.nodes: list[GraphNode] = []
        self.edges: list[GraphEdge] = []
        self._by_id: dict[str, GraphNode] = {}
        self._last_turn_id: str | None = None
        self._last_user_text: str = ""
        self._path_mentions: dict[str, int] = {}

    def insert(self, node: GraphNode) -> GraphNode:
        if not node.valid_start:
            node.valid_start = _now()
        self.nodes.append(node)
        self._by_id[node.id] = node
        return node

    def add_edge(self, src: str, dst: str, rel: str, at: str | None = None) -> GraphEdge:
        if rel not in RELS:
            raise ValueError(f"unknown rel {rel}")
        edge = GraphEdge(
            id=new_id("edge"),
            src=src,
            dst=dst,
            rel=rel,
            valid_start=at or _now(),
        )
        self.edges.append(edge)
        return edge

    def supersede(
        self,
        old: GraphNode,
        new: GraphNode,
        *,
        at: str | None = None,
        reason: str = "superseded",
    ) -> tuple[GraphNode, GraphNode, GraphEdge]:
        stamp = at or _now()
        old.status = "superseded"
        old.valid_end = stamp
        old.attrs["supersede_reason"] = reason
        if not new.valid_start:
            new.valid_start = stamp
        new.status = "active"
        self.insert(new)
        edge = self.add_edge(new.id, old.id, "supersedes", at=stamp)
        return old, new, edge

    def active_nodes(self) -> list[GraphNode]:
        return [n for n in self.nodes if n.status == "active" and n.valid_end is None]

    def prune(
        self,
        *,
        max_turns: int = MAX_ACTIVE_TURNS,
        max_non_durable_facts: int = MAX_ACTIVE_NON_DURABLE_FACTS,
        max_durable_facts: int | None = None,
        at: str | None = None,
    ) -> int:
        """Drop oldest active Turns / non-durable Facts beyond caps. Returns prune count."""
        stamp = at or _now()
        pruned = 0
        durable_cap = (
            MAX_ACTIVE_DURABLE_FACTS if max_durable_facts is None else max_durable_facts
        )

        turns = sorted(
            [n for n in self.active_nodes() if n.kind == "Turn"],
            key=lambda n: (n.valid_start, n.attrs.get("index", 0)),
        )
        while len(turns) > max_turns:
            old = turns.pop(0)
            old.status = "pruned"
            old.valid_end = stamp
            old.attrs["prune_reason"] = "max_turns"
            pruned += 1

        facts = sorted(
            [
                n
                for n in self.active_nodes()
                if n.kind == "Fact" and not bool(n.attrs.get("durable"))
            ],
            key=lambda n: n.valid_start,
        )
        while len(facts) > max_non_durable_facts:
            old = facts.pop(0)
            old.status = "pruned"
            old.valid_end = stamp
            old.attrs["prune_reason"] = "max_facts"
            pruned += 1

        durable = sorted(
            [
                n
                for n in self.active_nodes()
                if n.kind == "Fact" and bool(n.attrs.get("durable"))
            ],
            key=lambda n: (float(n.attrs.get("salience", 0.0)), n.valid_start),
        )
        while len(durable) > durable_cap:
            old = durable.pop(0)
            old.status = "pruned"
            old.valid_end = stamp
            old.attrs["prune_reason"] = "max_durable_facts"
            pruned += 1
        return pruned

    def ingest_turn(self, role: str, text: str, index: int, at: str | None = None) -> GraphNode:
        stamp = at or _now()
        summary = text.strip().replace("\n", " ")
        if len(summary) > 240:
            summary = summary[:237] + "..."
        turn = GraphNode(
            id=new_id("turn"),
            kind="Turn",
            label=f"{role}:{index}",
            summary=summary,
            valid_start=stamp,
            attrs={"role": role, "index": index},
        )
        self.insert(turn)
        if self._last_turn_id:
            self.add_edge(turn.id, self._last_turn_id, "continues", at=stamp)
        self._last_turn_id = turn.id

        new_facts: list[GraphNode] = []
        for sentence, salience, kind_hint in _fact_sentences(text, prior_user=self._last_user_text):
            fact = GraphNode(
                id=new_id("fact"),
                kind="Fact",
                label=sentence[:80],
                summary=sentence,
                valid_start=stamp,
                attrs={
                    "from_turn": turn.id,
                    "salience": salience,
                    "kind_hint": kind_hint,
                },
            )
            self.insert(fact)
            self.add_edge(turn.id, fact.id, "contains", at=stamp)
            new_facts.append(fact)

        for path, salience in _path_facts(text, mention_counts=self._path_mentions):
            existing = self._active_fact_label(path)
            if existing is not None:
                existing.attrs["salience"] = max(
                    float(existing.attrs.get("salience", 0.0)), salience
                )
                continue
            fact = GraphNode(
                id=new_id("fact"),
                kind="Fact",
                label=path,
                summary=f"path: {path}",
                valid_start=stamp,
                attrs={
                    "from_turn": turn.id,
                    "durable": True,
                    "kind_hint": "path",
                    "salience": salience,
                },
            )
            self.insert(fact)
            self.add_edge(turn.id, fact.id, "contains", at=stamp)
            new_facts.append(fact)

        for heading, level in _heading_facts(text):
            salience = 0.7 if level <= 1 else (0.55 if level == 2 else 0.4)
            existing = self._active_fact_label(heading)
            if existing is not None:
                existing.attrs["salience"] = max(
                    float(existing.attrs.get("salience", 0.0)), salience
                )
                continue
            fact = GraphNode(
                id=new_id("fact"),
                kind="Fact",
                label=heading[:80],
                summary=f"heading: {heading}",
                valid_start=stamp,
                attrs={
                    "from_turn": turn.id,
                    "durable": True,
                    "kind_hint": "heading",
                    "salience": salience,
                },
            )
            self.insert(fact)
            self.add_edge(turn.id, fact.id, "contains", at=stamp)
            new_facts.append(fact)

        for summary, hint in _design_facts(text):
            if self._active_fact_summary(summary) is not None:
                continue
            salience = 2.5 if hint == "decision" else 2.0
            fact = GraphNode(
                id=new_id("fact"),
                kind="Fact",
                label=_label(summary),
                summary=summary,
                valid_start=stamp,
                attrs={
                    "from_turn": turn.id,
                    "durable": True,
                    "kind_hint": hint,
                    "salience": salience,
                },
            )
            self.insert(fact)
            self.add_edge(turn.id, fact.id, "contains", at=stamp)
            new_facts.append(fact)

        for outcome in _outcome_items(text):
            if self._active_fact_summary(outcome) is not None:
                continue
            event = GraphNode(
                id=new_id("event"),
                kind="Event",
                label=_label(outcome),
                summary=outcome,
                valid_start=stamp,
                attrs={"from_turn": turn.id, "kind_hint": "outcome"},
            )
            self.insert(event)
            self.add_edge(turn.id, event.id, "contains", at=stamp)
            fact = GraphNode(
                id=new_id("fact"),
                kind="Fact",
                label=_label(outcome),
                summary=outcome,
                valid_start=stamp,
                attrs={
                    "from_turn": turn.id,
                    "durable": True,
                    "kind_hint": "outcome",
                    "salience": 1.8,
                },
            )
            self.insert(fact)
            self.add_edge(turn.id, fact.id, "contains", at=stamp)
            new_facts.append(fact)

        self._ingest_topics(text, turn.id, stamp, new_facts)

        done_items = _done_items(text)
        done_items.extend(_done_lines(text))
        done_items.extend(_done_items_verb(text))
        done_items.extend(item for item, state in _checkbox_items(text) if state == "done")
        # unique preserve order
        seen_done: set[str] = set()
        uniq_done: list[str] = []
        for item in done_items:
            key = item.lower()
            if key in seen_done:
                continue
            seen_done.add(key)
            uniq_done.append(item)

        for item in uniq_done:
            existing = self._active_open_item(item)
            if existing is None:
                existing = self._active_open_item_fuzzy(item)
            if existing is None:
                continue
            replacement = GraphNode(
                id=new_id("item"),
                kind="OpenItem",
                label=existing.label,
                summary=f"completed: {existing.label}",
                valid_start=stamp,
                attrs={"state": "done"},
            )
            self.supersede(existing, replacement, at=stamp, reason="completed")
            self.add_edge(turn.id, replacement.id, "mentions", at=stamp)

        done_keys = {d.lower() for d in uniq_done}
        for item, state in _open_items_from_text(text):
            if item.lower() in done_keys:
                continue
            if self._active_open_item(item) is not None:
                continue
            opened = GraphNode(
                id=new_id("item"),
                kind="OpenItem",
                label=item[:80],
                summary=f"{state}: {item}",
                valid_start=stamp,
                attrs={"state": state},
            )
            self.insert(opened)
            self.add_edge(turn.id, opened.id, "mentions", at=stamp)

        if role == "user":
            self._last_user_text = text
        self.prune(at=stamp)
        return turn

    def _active_open_item(self, label: str) -> GraphNode | None:
        key = label.lower().strip()
        for node in reversed(self.nodes):
            if (
                node.kind == "OpenItem"
                and node.status == "active"
                and node.label.lower() == key
                and node.attrs.get("state", "open") != "done"
            ):
                return node
        return None

    def _active_open_item_fuzzy(self, label: str) -> GraphNode | None:
        key = label.lower().strip()
        for node in reversed(self.nodes):
            if node.kind != "OpenItem" or node.status != "active":
                continue
            if node.attrs.get("state", "open") == "done":
                continue
            lab = node.label.lower()
            if key == lab or key in lab or lab in key:
                return node
        return None

    def _active_fact_label(self, label: str) -> GraphNode | None:
        key = label.lower().strip()
        for node in reversed(self.nodes):
            if node.kind == "Fact" and node.status == "active" and node.label.lower() == key:
                return node
        return None

    def _active_fact_summary(self, summary: str) -> GraphNode | None:
        key = summary.lower().strip()
        for node in reversed(self.nodes):
            if node.kind == "Fact" and node.status == "active" and node.summary.lower() == key:
                return node
        return None

    def _active_topic(self, label: str) -> GraphNode | None:
        key = label.lower().strip()
        for node in reversed(self.nodes):
            if node.kind == "Topic" and node.status == "active" and node.label.lower() == key:
                return node
        return None

    def _ingest_topics(
        self,
        text: str,
        turn_id: str,
        stamp: str,
        new_facts: list[GraphNode],
    ) -> None:
        labels: list[str] = []
        for match in TOPIC_LINE_RE.finditer(text):
            cleaned = _strip_item(match.group(1))
            if cleaned:
                labels.append(cleaned)
        for _level, heading in _h1_h2_headings(text):
            cleaned = heading.strip()
            if cleaned:
                labels.append(cleaned)
        noun_counts: dict[str, int] = {}
        for match in PROPER_NOUN_RE.finditer(text):
            noun = match.group(1).strip()
            if len(noun) < 3:
                continue
            noun_counts[noun] = noun_counts.get(noun, 0) + 1
        for noun, count in noun_counts.items():
            if count >= 2 or self._active_topic(noun) is not None:
                labels.append(noun)

        seen: set[str] = set()
        unique: list[str] = []
        for label in labels:
            key = label.lower()
            if key in seen or len(label) < 2:
                continue
            seen.add(key)
            unique.append(label)

        for label in unique[:8]:
            topic = self._upsert_topic(label, stamp, turn_id)
            blob = label.lower()
            for fact in new_facts:
                hay = f"{fact.label} {fact.summary}".lower()
                if blob in hay or any(tok in hay for tok in blob.split() if len(tok) > 4):
                    self.add_edge(topic.id, fact.id, "contains", at=stamp)

    def _upsert_topic(self, label: str, stamp: str, turn_id: str) -> GraphNode:
        existing = self._active_topic(label)
        if existing is not None:
            return existing
        for old in list(self.active_nodes()):
            if old.kind != "Topic":
                continue
            if _topic_subsumes(label, old.label):
                replacement = GraphNode(
                    id=new_id("topic"),
                    kind="Topic",
                    label=label[:80] if len(label) >= len(old.label) else old.label[:80],
                    summary=label if len(label) >= len(old.label) else old.label,
                    valid_start=stamp,
                    attrs={"salience": 0.8},
                )
                self.supersede(old, replacement, at=stamp, reason="subsumed")
                self.add_edge(turn_id, replacement.id, "mentions", at=stamp)
                return replacement
        topic = GraphNode(
            id=new_id("topic"),
            kind="Topic",
            label=label[:80],
            summary=label,
            valid_start=stamp,
            attrs={"salience": 0.8},
        )
        self.insert(topic)
        self.add_edge(turn_id, topic.id, "mentions", at=stamp)
        return topic

    def window_text(self, max_turns: int = 8) -> str:
        """Recent turn summaries + open labels for extractive gist."""
        turns = sorted(
            [n for n in self.active_nodes() if n.kind == "Turn"],
            key=lambda n: (n.valid_start, n.attrs.get("index", 0)),
        )[-max_turns:]
        parts = [n.summary for n in turns if n.summary]
        for n in self.active_nodes():
            if n.kind == "OpenItem" and n.attrs.get("state", "open") != "done":
                parts.append(n.label)
            if n.kind == "Fact" and n.attrs.get("durable"):
                parts.append(n.label)
        return "\n".join(parts)

    def typed_projection(
        self,
        query: str | None = None,
        *,
        hot_set: str = "",
        top_k: int = 12,
    ) -> list[str]:
        """Verbatim OpenItem/Fact/Path/Event lines, query-filtered; no new kinds."""
        from chat_compressor.rank import rank_chunks

        hot = hot_set if hot_set else self.hot_set(query=query)
        lines: list[str] = []
        events: list[GraphNode] = []
        for node in self.active_nodes():
            if node.kind == "OpenItem" and node.attrs.get("state", "open") != "done":
                body = (node.summary or node.label).strip()
                lines.append(f"OpenItem: {body}")
            elif node.kind == "Fact":
                label = (node.label or "").strip()
                summary = (node.summary or label).strip()
                pathish = bool(node.attrs.get("kind_hint") == "path") or bool(PATH_FACT_RE.search(label))
                if pathish:
                    lines.append(f"Path: {label}")
                else:
                    lines.append(f"Fact: {summary}")
            elif node.kind == "Event":
                events.append(node)
        if events:
            events.sort(key=lambda n: n.valid_start)
            last = events[-1]
            body = (last.summary or last.label).strip()
            lines.append(f"Event: {body}")

        deduped: list[str] = []
        seen: set[str] = set()
        hot_l = hot.lower()
        for line in lines:
            key = line.lower()
            if key in seen:
                continue
            rest = line.split(":", 1)[1].strip().lower() if ":" in line else key
            if key in hot_l or (rest and rest in hot_l):
                # Still emit typed form if HOT_SET used a different prefix shape.
                if any(key == s.lower() for s in deduped):
                    continue
            seen.add(key)
            deduped.append(line)

        if query and query.strip() and deduped:
            ranked = rank_chunks(query, deduped)
            ordered = [r.text for r in ranked]
            # lexical overlap boost already implicit in hashed cosine
            return ordered[:top_k]
        return deduped[:top_k]

    def hot_set(self, max_chars: int = 400, query: str | None = None) -> str:
        """Compact symbolic extract with role quotas; query-conditioned when given."""
        query_kw = keyword_set(query or "")

        def _rank(node: GraphNode) -> tuple[float, str]:
            body = f"{node.label} {node.summary}"
            sal = float(node.attrs.get("salience", 0.0))
            overlap = jaccard(keyword_set(body), query_kw) if query_kw else 0.0
            return (sal + 0.5 * overlap, node.valid_start)

        open_items = [
            n
            for n in self.active_nodes()
            if n.kind == "OpenItem" and n.attrs.get("state", "open") != "done"
        ]
        decisions = [
            n
            for n in self.active_nodes()
            if n.kind == "Fact" and _is_decision_fact(n)
        ]
        path_heading = [
            n
            for n in self.active_nodes()
            if n.kind == "Fact" and _is_path_or_heading(n)
        ]
        other_facts = [
            n
            for n in self.active_nodes()
            if n.kind == "Fact" and not _is_decision_fact(n) and not _is_path_or_heading(n)
        ]
        open_items.sort(key=_rank, reverse=True)
        decisions.sort(key=_rank, reverse=True)
        path_heading.sort(key=_rank, reverse=True)
        other_facts.sort(key=_rank, reverse=True)

        n_slots = max(5, max_chars // 64)
        caps = {
            "open": max(1, int(n_slots * HOT_SET_OPEN_SHARE)),
            "decision": max(1, int(n_slots * HOT_SET_DECISION_SHARE)),
            "path": max(1, int(n_slots * HOT_SET_PATH_HEADING_SHARE)),
            "other": n_slots,
        }
        buckets = [
            ("decision", decisions),
            ("open", open_items),
            ("path", path_heading),
            ("other", other_facts),
        ]
        parts: list[str] = []
        used = 0
        seen: set[str] = set()
        taken = {"open": 0, "decision": 0, "path": 0, "other": 0}

        def _emit(node: GraphNode, bucket: str) -> bool:
            nonlocal used
            if taken[bucket] >= caps[bucket]:
                return False
            key = f"{node.kind}:{node.label.lower()}"
            if key in seen:
                return False
            summary = (node.summary or node.label).strip()
            if len(summary) > 64:
                summary = summary[:61] + "..."
            line = f"{node.kind} {node.label}: {summary}"
            if used + len(line) + 1 > max_chars:
                return False
            seen.add(key)
            parts.append(line)
            used += len(line) + 1
            taken[bucket] += 1
            return True

        for bucket, nodes in buckets:
            for node in nodes:
                if used >= max_chars:
                    break
                _emit(node, bucket)
        return "\n".join(parts)

    def kind_counts(self) -> dict[str, int]:
        counts = {k: 0 for k in KINDS}
        for node in self.active_nodes():
            if node.kind in counts:
                counts[node.kind] += 1
        return counts

    def durable_fact_count(self) -> int:
        return sum(
            1
            for n in self.active_nodes()
            if n.kind == "Fact" and bool((n.attrs or {}).get("durable"))
        )

    def openitem_signature(self) -> str:
        rows = []
        for node in self.active_nodes():
            if node.kind != "OpenItem":
                continue
            state = str((node.attrs or {}).get("state", "open"))
            rows.append(f"{node.id}|{state}|{node.summary}|{node.label}")
        rows.sort()
        blob = "\n".join(rows).encode("utf-8")
        return hashlib.sha1(blob).hexdigest()[:16] if blob else "empty"

    def supersede_count(self) -> int:
        return sum(1 for n in self.nodes if n.status == "superseded")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA_ID,
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
        }

    def dumps(self) -> str:
        return json.dumps(self.to_dict(), separators=(",", ":"), sort_keys=True)

    def save(self, path: str | Path) -> Path:
        dest = Path(path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(self.dumps() + "\n", encoding="utf-8")
        return dest

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CtxGraph:
        graph = cls()
        for raw in data.get("nodes") or []:
            node = GraphNode.from_dict(raw)
            graph.nodes.append(node)
            graph._by_id[node.id] = node
            if node.kind == "Turn" and node.status == "active":
                graph._last_turn_id = node.id
                if (node.attrs or {}).get("role") == "user":
                    graph._last_user_text = node.summary
        for raw in data.get("edges") or []:
            graph.edges.append(GraphEdge.from_dict(raw))
        return graph

    @classmethod
    def load(cls, path: str | Path) -> CtxGraph:
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def facts_per_turn() -> int:
    raw = os.environ.get("CHAT_COMPRESSOR_FACTS_PER_TURN", "").strip()
    if not raw:
        return 3
    try:
        return max(1, min(12, int(raw)))
    except ValueError:
        return 3


def _score_fact_sentence(sentence: str, prior_user: str = "") -> float:
    score = 0.0
    if DECISION_BOOST_RE.search(sentence):
        score += 3.0
    if TRADEOFF_RE.search(sentence):
        score += 1.5
    if NUMERIC_CLAIM_RE.search(sentence):
        score += 1.0
    idents = IDENT_RE.findall(sentence)
    if idents:
        score += 1.5 * min(len(idents), 4)
    if DEFINE_RE.search(sentence):
        score += 2.0
    if PREAMBLE_RE.search(sentence):
        score -= 3.0
    if prior_user:
        if jaccard(keyword_set(sentence), keyword_set(prior_user)) >= 0.6:
            score -= 4.0
    return score


def _fact_sentences(text: str, prior_user: str = "") -> list[tuple[str, float, str]]:
    chunks = [c.strip() for c in SENTENCE_RE.split(text) if c.strip()]
    scored: list[tuple[float, str, str]] = []
    for chunk in chunks:
        if len(chunk) < 20:
            continue
        if len(chunk) > 240:
            chunk = chunk[:237] + "..."
        salience = _score_fact_sentence(chunk, prior_user=prior_user)
        kind_hint = "decision" if salience >= 2.0 else "sentence"
        scored.append((salience, chunk, kind_hint))
    scored.sort(key=lambda row: row[0], reverse=True)
    positive = [row for row in scored if row[0] > 0]
    ranked = positive if positive else scored
    top_n = facts_per_turn()
    return [(chunk, sal, hint) for sal, chunk, hint in ranked[:top_n]]


def _path_facts(
    text: str,
    mention_counts: dict[str, int] | None = None,
) -> list[tuple[str, float]]:
    unfenced = FENCE_RE.sub("\n", text)
    fences = "\n".join(FENCE_RE.findall(text))
    outside = [m.group(0) for m in PATH_FACT_RE.finditer(unfenced)]
    inside = [m.group(0) for m in PATH_FACT_RE.finditer(fences)]
    counts = mention_counts if mention_counts is not None else {}
    ordered: list[str] = []
    seen: set[str] = set()
    for p in outside + inside:
        key = p.lower()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(p)

    scored: list[tuple[float, str]] = []
    for p in ordered:
        key = p.lower()
        in_out = sum(1 for x in outside if x.lower() == key)
        in_fence = sum(1 for x in inside if x.lower() == key)
        counts[key] = counts.get(key, 0) + in_out + in_fence
        fence_only = in_out == 0 and in_fence > 0
        if fence_only and counts[key] < 2:
            continue
        salience = 0.45 + 0.1 * min(counts[key], 3)
        if in_out:
            salience += 0.15
        low = p.lower()
        if "/scripts/" in f"/{low}" or low.startswith("scripts/"):
            salience += 0.5
        if "/figures/" in f"/{low}" or low.startswith("figures/"):
            salience += 0.5
        if low.endswith((".py", ".json", ".sh", ".tex", ".png")):
            salience += 0.25
        if low.endswith(".log.txt") or "test-results/" in low or ".cursor/" in low:
            salience -= 0.4
        if low.startswith("/users/"):
            salience -= 0.2
        scored.append((salience, p))
    scored.sort(key=lambda row: row[0], reverse=True)
    return [(p, sal) for sal, p in scored[:PER_TURN_PATH_CAP]]


def _heading_facts(text: str) -> list[tuple[str, int]]:
    unfenced = FENCE_RE.sub("\n", text)
    found = [(len(m.group(1)), m.group(2).strip()) for m in HEADING_FACT_RE.finditer(unfenced)]
    seen: set[str] = set()
    out: list[tuple[str, int]] = []
    for level, heading in found:
        key = heading.lower()
        if key in seen or len(heading) < 2:
            continue
        seen.add(key)
        out.append((heading, level))
        if len(out) >= 8:
            break
    return out


def _h1_h2_headings(text: str) -> list[tuple[int, str]]:
    return [(level, heading) for heading, level in _heading_facts(text) if level <= 2]


def _topic_subsumes(a: str, b: str) -> bool:
    left = a.lower().strip()
    right = b.lower().strip()
    if left == right:
        return False
    return left in right or right in left


def _is_path_or_heading(node: GraphNode) -> bool:
    hint = str(node.attrs.get("kind_hint") or "")
    if hint in {"path", "heading"}:
        return True
    label = node.label or ""
    return bool(PATH_FACT_RE.search(label)) or (node.summary or "").startswith("heading:")


def _is_decision_fact(node: GraphNode) -> bool:
    if node.kind != "Fact":
        return False
    if _is_path_or_heading(node):
        return False
    if str(node.attrs.get("kind_hint") or "") in {"decision", "design", "outcome"}:
        return True
    return float(node.attrs.get("salience", 0.0)) >= 2.0


def _clean_item_label(raw: str) -> str:
    text = re.sub(r"[*`]+", "", raw).strip()
    text = re.sub(r"\s+", " ", text)
    if len(text) > 80:
        text = text[:77] + "..."
    return text.strip(" .")


def _checkbox_items(text: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for match in CHECKBOX_RE.finditer(text):
        mark, label = match.group(1), _clean_item_label(match.group(2))
        if not label:
            continue
        state = "done" if mark.lower() == "x" else "open"
        found.append((label, state))
    return found


def _deferred_section_items(text: str) -> list[str]:
    items: list[str] = []
    in_deferred = False
    deferred_level = 0
    for line in text.splitlines():
        hm = re.match(r"^(#{1,6})\s+(.+)$", line)
        if hm:
            level = len(hm.group(1))
            title = hm.group(2)
            if DEFERRED_HEADING_RE.search(title):
                in_deferred = True
                deferred_level = level
                continue
            if in_deferred and level <= deferred_level:
                in_deferred = False
        if not in_deferred:
            continue
        bm = BULLET_RE.match(line)
        if bm:
            label = _clean_item_label(bm.group(1))
            if label:
                items.append(label)
    return items


def _open_items_from_text(text: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    seen: set[str] = set()

    def _add(label: str, state: str) -> None:
        cleaned = _clean_item_label(label)
        key = cleaned.lower()
        if not cleaned or key in seen or len(cleaned) < 2:
            return
        seen.add(key)
        found.append((cleaned, state))

    for label, state in _checkbox_items(text):
        if state != "done":
            _add(label, state)
    for match in TODO_LINE_RE.finditer(text):
        _add(match.group(1), "open")
    for match in NEXT_LINE_RE.finditer(text):
        _add(match.group(1), "open")
    for match in OPEN_LINE_RE.finditer(text):
        _add(match.group(1), "open")
    for label in _deferred_section_items(text):
        _add(label, "deferred")
    for line in text.splitlines():
        if DEFERRED_HINT_RE.search(line):
            bm = BULLET_RE.match(line)
            if bm:
                _add(bm.group(1), "deferred")
            elif not re.match(r"^#{1,6}\s+", line):
                _add(line, "deferred")
        nm = NUMBERED_RE.match(line)
        if nm and ACTION_ITEM_RE.search(line):
            _add(nm.group(1), "open")
    if OPEN_HINT_RE.search(text):
        for item in _quoted_items(text):
            _add(item, "open")
    return found[:16]


def _done_items(text: str) -> list[str]:
    found: list[str] = []
    for match in DONE_ITEM_RE.finditer(text):
        item = next((g for g in match.groups() if g), "")
        if item:
            found.append(item.strip())
    return found


def _done_items_verb(text: str) -> list[str]:
    found: list[str] = []
    for match in DONE_VERB_RE.finditer(text):
        item = (match.group(1) or "").strip(" .")
        if item and 2 <= len(item) <= 80:
            found.append(item)
    return found


def _done_lines(text: str) -> list[str]:
    found: list[str] = []
    for match in DONE_LINE_RE.finditer(text):
        body = _strip_item(match.group(1))
        if body:
            found.append(body)
    return found


def _label(text: str, max_len: int = 96) -> str:
    clean = " ".join((text or "").strip().split())
    if len(clean) <= max_len:
        return clean
    cut = clean[: max_len - 3].rstrip()
    space = cut.rfind(" ")
    if space >= max_len // 2:
        cut = cut[:space]
    return cut.rstrip(" ,;:-") + "..."


def _strip_item(text: str) -> str:
    return (text or "").strip().strip("-*[]() \t`\"'.")


def _sentence_fragment(text: str) -> str:
    clean = (text or "").strip()
    for sep in ("\n", ". "):
        if sep in clean:
            clean = clean.split(sep, 1)[0]
    clean = " ".join(clean.split())
    clean = clean.strip("-*[]() \t`\"'")
    if not clean:
        return ""
    for sep in (". ", "\n"):
        if sep in clean:
            clean = clean.split(sep, 1)[0]
    return _label(clean, max_len=140)


def _dedupe_limited(items: list[str], *, limit: int, max_len: int) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        clean = _label(item, max_len=max_len).strip()
        key = clean.lower()
        if not clean or key in seen:
            continue
        seen.add(key)
        out.append(clean)
        if len(out) >= limit:
            break
    return out


def _design_facts(text: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    in_design_block = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            in_design_block = False
            continue
        heading = line.lstrip("#").strip()
        heading_like = line.startswith("#") or (
            not line.startswith(("-", "*"))
            and DESIGN_HEADING_RE.search(heading)
            and not re.search(r"[=:]", line)
        )
        if heading_like:
            in_design_block = True
            continue
        match = DESIGN_LINE_RE.match(line)
        if not match:
            continue
        marker = (match.group(1) or "").lower()
        body = _strip_item(match.group(2))
        if not body or len(body) < 8:
            continue
        is_design = in_design_block or bool(marker) or "->" in body
        if not is_design:
            continue
        hint = "decision" if marker == "decision" or line.lower().startswith("decision") else "design"
        if marker in {"structure", "entry fields", "fields"}:
            body = f"{marker}: {body}"
        elif marker == "recommendation":
            body = f"recommendation: {body}"
        elif marker in {"decision", "design"}:
            body = f"{marker}: {body}"
        found.append((_sentence_fragment(body), hint))
    deduped: list[tuple[str, str]] = []
    seen: set[str] = set()
    for summary, hint in found:
        key = summary.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append((summary, hint))
        if len(deduped) >= 8:
            break
    return deduped


def _outcome_items(text: str) -> list[str]:
    found = [_sentence_fragment(m.group(0)) for m in OUTCOME_RE.finditer(text)]
    return _dedupe_limited(found, limit=8, max_len=120)


def _quoted_items(text: str) -> list[str]:
    found = [m.group(1).strip() for m in ITEM_RE.finditer(text)]
    # also split simple comma lists after "add"
    extra: list[str] = []
    for match in re.finditer(r"\badd\b[:\s]+(.+)", text, flags=re.I):
        extra.extend(
            p.strip(" .")
            for p in match.group(1).split(",")
            if 2 <= len(p.strip(" .")) <= 40 and " " not in p.strip(" .")[1:]
        )
    seen: set[str] = set()
    items: list[str] = []
    for item in found + extra:
        key = item.lower()
        if key and key not in seen and 2 <= len(item) <= 80:
            seen.add(key)
            items.append(item)
    return items[:8]


def ingest_turns(graph: CtxGraph, turns: Iterable[Any]) -> CtxGraph:
    for turn in turns:
        graph.ingest_turn(turn.role, turn.text, turn.index)
    return graph
