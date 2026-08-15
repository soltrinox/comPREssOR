"""SQLite metadata + file-backed mmap safetensors for StateNode lineage."""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from safetensors import safe_open
from safetensors.numpy import save_file

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS agents (
    agent_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    producer TEXT NOT NULL,
    d INTEGER NOT NULL,
    k_max INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS states (
    state_id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    parent_id TEXT,
    t INTEGER NOT NULL,
    blob_path TEXT NOT NULL,
    k INTEGER NOT NULL,
    d INTEGER NOT NULL,
    producer TEXT NOT NULL,
    graph_path TEXT,
    created_at TEXT NOT NULL,
    meta_json TEXT,
    FOREIGN KEY (agent_id) REFERENCES agents(agent_id)
);

CREATE INDEX IF NOT EXISTS lineage ON states (agent_id, t);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_state_id() -> str:
    return f"st_{uuid.uuid4().hex}"


@dataclass
class StateNode:
    state_id: str
    agent_id: str
    t: int
    C: np.ndarray
    M: np.ndarray
    producer: str
    d: int
    k: int
    parent_id: str | None = None
    blob_path: str = ""
    graph_path: str | None = None
    created_at: str = ""
    KV: np.ndarray | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def lineage_tuple(self) -> tuple[str, str | None, int]:
        return self.state_id, self.parent_id, self.t


class StateStore:
    """Two-tier store: SQLite Meta_t + mmap .safetensors under state/<agent_id>/."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "meta.sqlite"
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA_SQL)

    def ensure_agent(self, agent_id: str, producer: str, d: int, k_max: int) -> None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT agent_id FROM agents WHERE agent_id = ?", (agent_id,)
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO agents (agent_id, created_at, producer, d, k_max) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (agent_id, _now(), producer, int(d), int(k_max)),
                )

    def save(
        self,
        *,
        agent_id: str,
        C: np.ndarray,
        M: np.ndarray | None = None,
        parent: StateNode | None = None,
        producer: str = "embed",
        graph_path: str | Path | None = None,
        KV: np.ndarray | None = None,
        meta: dict[str, Any] | None = None,
        k_max: int = 32,
    ) -> StateNode:
        arr = np.asarray(C, dtype=np.float32)
        if arr.ndim == 1:
            arr = arr[None, :]
        k, d = int(arr.shape[0]), int(arr.shape[1])
        mask = np.asarray(M if M is not None else np.ones((k,), dtype=np.float32), dtype=np.float32)
        t = 1 if parent is None else int(parent.t) + 1
        parent_id = None if parent is None else parent.state_id
        state_id = _new_state_id()
        created = _now()
        agent_dir = self.root / agent_id
        agent_dir.mkdir(parents=True, exist_ok=True)
        blob_path = agent_dir / f"t{t:04d}.safetensors"
        tensors: dict[str, np.ndarray] = {"C": arr, "M": mask}
        if KV is not None:
            tensors["KV"] = np.asarray(KV, dtype=np.float32)
        save_file(tensors, str(blob_path))
        graph_str = str(graph_path) if graph_path is not None else None
        self.ensure_agent(agent_id, producer, d, k_max)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO states (state_id, agent_id, parent_id, t, blob_path, "
                "k, d, producer, graph_path, created_at, meta_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    state_id,
                    agent_id,
                    parent_id,
                    t,
                    str(blob_path),
                    k,
                    d,
                    producer,
                    graph_str,
                    created,
                    json.dumps(meta or {}),
                ),
            )
        return self.load(state_id)

    def load(self, state_id: str) -> StateNode:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM states WHERE state_id = ?", (state_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown state_id {state_id}")
        return self._row_to_node(row)

    def load_latest(self, agent_id: str) -> StateNode | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM states WHERE agent_id = ? ORDER BY t DESC LIMIT 1",
                (agent_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_node(row)

    def lineage(self, agent_id: str) -> list[StateNode]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM states WHERE agent_id = ? ORDER BY t ASC",
                (agent_id,),
            ).fetchall()
        return [self._row_to_node(row) for row in rows]

    def _row_to_node(self, row: sqlite3.Row) -> StateNode:
        blob = Path(row["blob_path"])
        tensors = _mmap_tensors(blob)
        meta_raw = row["meta_json"]
        meta = json.loads(meta_raw) if meta_raw else {}
        return StateNode(
            state_id=row["state_id"],
            agent_id=row["agent_id"],
            t=int(row["t"]),
            C=tensors["C"],
            M=tensors["M"],
            producer=row["producer"],
            d=int(row["d"]),
            k=int(row["k"]),
            parent_id=row["parent_id"],
            blob_path=row["blob_path"],
            graph_path=row["graph_path"],
            created_at=row["created_at"],
            KV=tensors.get("KV"),
            meta=meta,
        )


def _mmap_tensors(path: Path) -> dict[str, np.ndarray]:
    """Open safetensors via file-backed mmap (Darwin-safe; not /dev/shm)."""
    out: dict[str, np.ndarray] = {}
    with safe_open(str(path), framework="np") as handle:
        for key in handle.keys():
            out[key] = handle.get_tensor(key)
    return out


INJECT_HISTORY_NAME = "inject_history.json"
INJECT_HISTORY_KEEP = 32


def inject_history_path(agent_dir: str | Path) -> Path:
    return Path(agent_dir) / INJECT_HISTORY_NAME


def load_inject_history(agent_dir: str | Path) -> list[dict[str, Any]]:
    path = inject_history_path(agent_dir)
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(raw, dict):
        rows = raw.get("turns")
        return list(rows) if isinstance(rows, list) else []
    if isinstance(raw, list):
        return raw
    return []


def save_inject_history(agent_dir: str | Path, turns: list[dict[str, Any]]) -> Path:
    dest = inject_history_path(agent_dir)
    dest.parent.mkdir(parents=True, exist_ok=True)
    kept = turns[-INJECT_HISTORY_KEEP:]
    dest.write_text(
        json.dumps({"turns": kept}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return dest


def append_inject_history(
    agent_dir: str | Path,
    row: dict[str, Any],
) -> list[dict[str, Any]]:
    turns = load_inject_history(agent_dir)
    turns.append(row)
    save_inject_history(agent_dir, turns)
    return turns


def recent_line_hashes(history: list[dict[str, Any]], k: int = 3) -> set[str]:
    out: set[str] = set()
    for row in history[-max(1, int(k)) :]:
        hashes = row.get("hashes") if isinstance(row, dict) else None
        if not isinstance(hashes, list):
            continue
        for item in hashes:
            if item:
                out.add(str(item))
    return out


def rolling_novelty(history: list[dict[str, Any]], k: int = 3) -> float:
    packed = 0
    novel = 0
    for row in history[-max(1, int(k)) :]:
        if not isinstance(row, dict):
            continue
        packed += int(row.get("packed_tokens") or 0)
        novel += int(row.get("novel_tokens") or 0)
    if packed <= 0:
        return 1.0
    return max(0.0, min(1.0, novel / packed))


def write_span_sidecar(blob_path: str | Path, spans: list[dict[str, Any]]) -> Path:
    """Write tNNNN.spans.json beside the safetensor. Local retrieval only."""
    blob = Path(blob_path)
    dest = blob.with_name(blob.stem + ".spans.json")
    dest.write_text(json.dumps(spans, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return dest
