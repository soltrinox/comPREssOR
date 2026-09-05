"""CC-8: portable state bundle export/import (prototype §15).

Format (bundle.v1/):
  manifest.json, graph.json, states/*.safetensors,
  inject_ledger.json, lineage.json

Producer mismatch is reported explicitly — never silent embedding reuse.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import numpy as np
from safetensors import safe_open

from chat_compressor.store import (
    StateNode,
    StateStore,
    _read_inject_doc,
    _write_inject_doc,
)

BUNDLE_SCHEMA = "bundle.v1"
ImportMode = Literal["full", "graph_only", "reproject_required"]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class BundleManifest:
    schema: str = BUNDLE_SCHEMA
    version: str = "1"
    producer: str = ""
    d: int = 0
    k_max: int = 0
    tokenizer_id: str = "hashed-ngram"
    quantization: str = "float32"
    agent_id: str = ""
    lineage_head: str | None = None
    created_at: str = ""
    checksums: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "version": self.version,
            "producer": self.producer,
            "d": self.d,
            "k_max": self.k_max,
            "tokenizer_id": self.tokenizer_id,
            "quantization": self.quantization,
            "agent_id": self.agent_id,
            "lineage_head": self.lineage_head,
            "created_at": self.created_at,
            "checksums": dict(self.checksums),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BundleManifest:
        return cls(
            schema=str(data.get("schema") or BUNDLE_SCHEMA),
            version=str(data.get("version") or "1"),
            producer=str(data.get("producer") or ""),
            d=int(data.get("d") or 0),
            k_max=int(data.get("k_max") or 0),
            tokenizer_id=str(data.get("tokenizer_id") or "hashed-ngram"),
            quantization=str(data.get("quantization") or "float32"),
            agent_id=str(data.get("agent_id") or ""),
            lineage_head=data.get("lineage_head"),
            created_at=str(data.get("created_at") or ""),
            checksums=dict(data.get("checksums") or {}),
        )


@dataclass
class ImportResult:
    mode: ImportMode
    agent_id: str
    states_imported: int
    graph_imported: bool
    ledger_imported: bool
    producer_matched: bool
    notes: str = ""


def export_bundle(
    store: StateStore,
    agent_id: str,
    dest: str | Path,
    *,
    tokenizer_id: str | None = None,
) -> Path:
    """Export agent state into a bundle.v1 directory. Returns dest path."""
    out = Path(dest)
    if out.exists():
        shutil.rmtree(out)
    states_dir = out / "states"
    states_dir.mkdir(parents=True, exist_ok=True)

    lineage = store.lineage(agent_id)
    if not lineage:
        raise ValueError(f"no states for agent_id={agent_id!r}")

    agent_dir = Path(store.root) / agent_id
    head = lineage[-1]
    tokenizer = tokenizer_id or str((head.meta or {}).get("tokenizer_id") or "hashed-ngram")
    quant = str((head.meta or {}).get("quantization") or "float32")

    k_max = head.k
    with store._connect() as conn:
        row = conn.execute(
            "SELECT producer, d, k_max FROM agents WHERE agent_id = ?", (agent_id,)
        ).fetchone()
    producer = head.producer
    d = head.d
    if row is not None:
        producer = row["producer"] or producer
        d = int(row["d"])
        k_max = int(row["k_max"])

    checksums: dict[str, str] = {}
    lineage_rows: list[dict[str, Any]] = []

    for node in lineage:
        src = Path(node.blob_path)
        name = f"t{node.t:04d}.safetensors"
        dst = states_dir / name
        if src.is_file():
            shutil.copy2(src, dst)
            checksums[f"states/{name}"] = _sha256_file(dst)
        spans = src.with_name(src.stem + ".spans.json")
        if spans.is_file():
            spans_dst = states_dir / spans.name
            shutil.copy2(spans, spans_dst)
            checksums[f"states/{spans.name}"] = _sha256_file(spans_dst)
        lineage_rows.append(
            {
                "state_id": node.state_id,
                "parent_id": node.parent_id,
                "t": node.t,
                "producer": node.producer,
                "d": node.d,
                "k": node.k,
                "blob": name,
                "meta": dict(node.meta or {}),
                "created_at": node.created_at,
            }
        )

    graph_src = agent_dir / "graph.json"
    if graph_src.is_file():
        graph_dst = out / "graph.json"
        shutil.copy2(graph_src, graph_dst)
        checksums["graph.json"] = _sha256_file(graph_dst)
    else:
        (out / "graph.json").write_text("{}\n", encoding="utf-8")
        checksums["graph.json"] = _sha256_file(out / "graph.json")

    ledger_doc = _read_inject_doc(agent_dir)
    ledger_path = out / "inject_ledger.json"
    ledger_path.write_text(
        json.dumps(ledger_doc, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    checksums["inject_ledger.json"] = _sha256_file(ledger_path)

    lineage_path = out / "lineage.json"
    lineage_path.write_text(
        json.dumps({"agent_id": agent_id, "states": lineage_rows}, indent=2) + "\n",
        encoding="utf-8",
    )
    checksums["lineage.json"] = _sha256_file(lineage_path)

    manifest = BundleManifest(
        producer=str(producer),
        d=int(d),
        k_max=int(k_max),
        tokenizer_id=tokenizer,
        quantization=quant,
        agent_id=agent_id,
        lineage_head=head.state_id,
        created_at=_now(),
        checksums=checksums,
    )
    (out / "manifest.json").write_text(
        json.dumps(manifest.to_dict(), indent=2) + "\n", encoding="utf-8"
    )
    return out


def import_bundle(
    src: str | Path,
    store: StateStore,
    *,
    agent_id: str | None = None,
    expected_producer: str | None = None,
    expected_d: int | None = None,
) -> ImportResult:
    """Import a bundle.v1 directory into store.

    When producer/d mismatch, imports graph + ledger but skips tensor blobs
    (mode=graph_only) and reports the mismatch.
    """
    root = Path(src)
    man_path = root / "manifest.json"
    if not man_path.is_file():
        raise FileNotFoundError(f"missing manifest.json in {root}")
    manifest = BundleManifest.from_dict(json.loads(man_path.read_text(encoding="utf-8")))
    aid = agent_id or manifest.agent_id
    if not aid:
        raise ValueError("agent_id required")

    producer_ok = True
    notes: list[str] = []
    if expected_producer is not None and expected_producer != manifest.producer:
        producer_ok = False
        notes.append(
            f"producer mismatch: bundle={manifest.producer!r} expected={expected_producer!r}"
        )
    if expected_d is not None and int(expected_d) != int(manifest.d):
        producer_ok = False
        notes.append(f"d mismatch: bundle={manifest.d} expected={expected_d}")

    lineage_path = root / "lineage.json"
    lineage_doc = json.loads(lineage_path.read_text(encoding="utf-8"))
    states_meta = list(lineage_doc.get("states") or [])

    agent_dir = Path(store.root) / aid
    agent_dir.mkdir(parents=True, exist_ok=True)

    graph_imported = False
    graph_src = root / "graph.json"
    if graph_src.is_file():
        shutil.copy2(graph_src, agent_dir / "graph.json")
        graph_imported = True

    ledger_imported = False
    ledger_src = root / "inject_ledger.json"
    if ledger_src.is_file():
        try:
            doc = json.loads(ledger_src.read_text(encoding="utf-8"))
            if isinstance(doc, dict):
                _write_inject_doc(agent_dir, doc)
                ledger_imported = True
            elif isinstance(doc, list):
                _write_inject_doc(agent_dir, {"turns": doc, "recipients": {}})
                ledger_imported = True
        except (OSError, json.JSONDecodeError) as exc:
            notes.append(f"ledger import skipped: {exc}")

    states_imported = 0
    store.ensure_agent(aid, manifest.producer, manifest.d, manifest.k_max)
    if not producer_ok:
        notes.append("tensors skipped due to producer mismatch; reproject_required")
        return ImportResult(
            mode="graph_only",
            agent_id=aid,
            states_imported=0,
            graph_imported=graph_imported,
            ledger_imported=ledger_imported,
            producer_matched=False,
            notes="; ".join(notes),
        )

    parent: StateNode | None = None
    states_dir = root / "states"
    for row in states_meta:
        blob_name = str(row.get("blob") or f"t{int(row['t']):04d}.safetensors")
        blob_src = states_dir / blob_name
        if not blob_src.is_file():
            notes.append(f"missing blob {blob_name}")
            continue
        tensors: dict[str, Any] = {}
        with safe_open(str(blob_src), framework="np") as handle:
            for key in handle.keys():
                tensors[key] = handle.get_tensor(key)
        C = np.asarray(tensors["C"])
        M = tensors.get("M")
        KV = tensors.get("KV")
        meta = dict(row.get("meta") or {})
        node = store.save(
            agent_id=aid,
            C=C,
            M=M,
            parent=parent,
            producer=str(row.get("producer") or manifest.producer),
            graph_path=agent_dir / "graph.json",
            KV=KV,
            meta=meta,
            k_max=manifest.k_max,
        )
        spans_src = states_dir / (Path(blob_name).stem + ".spans.json")
        if spans_src.is_file():
            shutil.copy2(
                spans_src,
                Path(node.blob_path).with_name(Path(node.blob_path).stem + ".spans.json"),
            )
        parent = node
        states_imported += 1

    return ImportResult(
        mode="full",
        agent_id=aid,
        states_imported=states_imported,
        graph_imported=graph_imported,
        ledger_imported=ledger_imported,
        producer_matched=True,
        notes="; ".join(notes),
    )
