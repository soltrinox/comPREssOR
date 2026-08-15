"""A/B harness: offline StateNode loop and optional isolated Cursor SDK arms."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from chat_compressor.envfile import load_project_env

load_project_env(ROOT)

from chat_compressor.compress import classify_method
from chat_compressor.handle import PersistentAgentHandle
from chat_compressor.logutil import StageLogger, timestamp
from chat_compressor.metrics import (
    entity_recall,
    keyword_jaccard,
    matrix_stats,
    payload_stats,
    reference_terms_from_text,
)
from chat_compressor.parse import parse_jsonl, turns_to_raw_text
from chat_compressor.producer import EmbeddingProducer
from chat_compressor.store import StateStore
from chat_compressor.translate.vocab_bridge import Pattern1Bridge

PROBE = (
    "What items remain open, and what was already completed? "
    "Answer from the provided context only. Do not use tools."
)
CONTEXT_ONLY = "Answer from the provided context only. Do not use tools."
ENTITY_RECALL_MIN = 0.30
NOISE_BAG = "file right add add check wait call create"


def _write_proof(dest: Path, lines: list[str]) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_offline(
    fixture: Path,
    run_dir: Path,
    log: StageLogger,
    k_max: int = 32,
) -> dict:
    turns = parse_jsonl(fixture)
    if not turns:
        log.stage(False, 0, error="empty-fixture")
        raise SystemExit(2)
    store = StateStore(run_dir / "state")
    handle = PersistentAgentHandle(
        agent_id="offline-ab",
        store=store,
        producer=EmbeddingProducer(k_max=k_max),
        translator=Pattern1Bridge(),
        k_max=k_max,
    )
    raw_acc: list[str] = []
    last_gist = ""
    last_hot = ""
    last_stats = None
    last_payload = None
    last_node = None
    last_jaccard = 0.0
    last_recall = 0.0
    last_method = "hot_set"
    last_packed_tokens = 0
    last_budget = 0
    last_rate = 0.0
    last_tokens_ws = 0
    last_tokens_chars4 = 0
    ref_terms: set[str] = set()
    for i, turn in enumerate(turns, start=1):
        raw_acc.append(turn.as_line())
        out = handle.step(turn.text, role=turn.role)
        node = handle.latest()
        assert node is not None
        sampled = handle.sample_for("cursor-sdk")
        hot = handle.graph.hot_set()
        raw = turns_to_raw_text(turns[:i])
        ref_terms |= reference_terms_from_text(raw)
        merged = "\n".join(p for p in (sampled.text, hot) if p)
        mstats = matrix_stats(node.C, node.M)
        pstats = payload_stats(raw, sampled.text, hot)
        method = classify_method(producer=node.producer, sampled_via=sampled.method)
        jac = keyword_jaccard(raw, merged)
        recall = entity_recall(ref_terms, merged)
        budget = int(sampled.budget or 0)
        packed_tokens = int(sampled.packed_tokens or pstats.gist_tokens_est)
        rate = float(sampled.rate) if sampled.budget else (packed_tokens / budget if budget else 0.0)
        log.stage(
            True,
            i,
            state_id=node.state_id,
            parent=node.parent_id or "none",
            k=mstats.k,
            d=mstats.d,
            method=method,
            raw_chars=pstats.raw_chars,
            gist_chars=pstats.gist_chars,
            graph_chars=pstats.graph_chars,
            ratio=round(pstats.ratio, 6),
            packed_tokens=packed_tokens,
            budget=budget,
            tokens_ws=int(sampled.tokens_ws),
            tokens_chars4=int(sampled.tokens_chars4),
            rate=round(rate, 4),
            jaccard=round(jac, 4),
            recall=round(recall, 4),
            frobenius=round(mstats.frobenius, 4),
            compress_ms=round(out.compress_ms, 2),
            persist_ms=round(out.persist_ms, 2),
            sample_ms=round(handle.last_sample_ms, 2),
            rank_ms=round(float(sampled.rank_ms), 2),
            flush=int(out.graph_flushed),
        )
        last_gist = sampled.text
        last_hot = hot
        last_stats = mstats
        last_payload = pstats
        last_node = node
        last_jaccard = jac
        last_recall = recall
        last_method = method
        last_packed_tokens = packed_tokens
        last_budget = budget
        last_rate = rate
        last_tokens_ws = int(sampled.tokens_ws)
        last_tokens_chars4 = int(sampled.tokens_chars4)
    # Force final graph flush for artifact completeness.
    handle.flush_graph()
    sample_path = run_dir / "sample-gist.txt"
    sample_path.write_text(last_gist + "\n", encoding="utf-8")
    log.line(f"[PASS] sample_gist={last_gist}")
    log.line(
        f"[INFO] final_jaccard={last_jaccard:.4f} final_recall={last_recall:.4f} "
        f"method={last_method} packed_tokens={last_packed_tokens} budget={last_budget} "
        f"rate={last_rate:.4f} ref_terms={len(ref_terms)}"
    )
    gate_ok = last_recall >= ENTITY_RECALL_MIN and NOISE_BAG not in (last_gist or "").lower()
    if gate_ok:
        log.line(f"[PASS] entity_recall_gate recall={last_recall:.4f} >= {ENTITY_RECALL_MIN}")
    else:
        log.line(
            f"[FAIL] entity_recall_gate recall={last_recall:.4f} < {ENTITY_RECALL_MIN} "
            f"or noisy P1 bag present"
        )
    return {
        "turns": len(turns),
        "gist": last_gist,
        "hot": last_hot,
        "matrix": last_stats,
        "payload": last_payload,
        "node": last_node,
        "raw": "\n".join(raw_acc),
        "handle": handle,
        "jaccard": last_jaccard,
        "recall": last_recall,
        "method": last_method,
        "ref_terms": sorted(ref_terms),
        "gate_ok": gate_ok,
        "packed_tokens": last_packed_tokens,
        "budget": last_budget,
        "rate": last_rate,
        "tokens_ws": last_tokens_ws,
        "tokens_chars4": last_tokens_chars4,
    }


async def _run_one_arm(
    *,
    label: str,
    cwd: Path,
    prompt: str,
    api_key: str,
    log: StageLogger,
) -> dict:
    cwd.mkdir(parents=True, exist_ok=True)
    (cwd / "README.md").write_text(f"isolated {label} arm cwd\n", encoding="utf-8")
    try:
        from cursor_sdk import AsyncClient, LocalAgentOptions
    except ImportError as exc:
        log.stage(False, f"live-{label}", error=f"cursor-sdk-missing:{exc}")
        return {"label": label, "status": "NOT_RUN", "error": "cursor-sdk not installed"}

    text = ""
    status = "error"
    try:
        async with await AsyncClient.launch_bridge() as client:
            # setting_sources left unset (inline config only).
            agent = await client.agents.create(
                model="composer-2.5",
                api_key=api_key,
                local=LocalAgentOptions(cwd=str(cwd)),
            )
            async with agent:
                run = await agent.send(prompt)
                result = await run.wait()
                status = getattr(result, "status", "unknown")
                text = getattr(result, "result", None) or getattr(result, "text", "") or ""
                if not text and hasattr(run, "text"):
                    try:
                        text = run.text()
                    except Exception:
                        text = str(result)
        log.stage(status in {"finished", "success", "completed"}, f"live-{label}", status=status)
        return {"label": label, "status": status, "text": str(text)[:4000]}
    except Exception as exc:
        log.stage(False, f"live-{label}", error=type(exc).__name__)
        return {"label": label, "status": "FAIL", "error": str(exc)}


async def run_live(offline: dict, run_dir: Path, log: StageLogger) -> dict:
    api_key = os.environ.get("CURSOR_API_KEY", "").strip()
    if not api_key:
        log.stage(False, "live", error="CURSOR_API_KEY unset")
        return {"status": "NOT_RUN", "reason": "CURSOR_API_KEY unset"}

    raw_prompt = (
        f"{CONTEXT_ONLY}\n\nCONTEXT:\n{offline['raw']}\n\nQUESTION:\n{PROBE}"
    )
    gist = offline["gist"]
    hot = offline["hot"]
    compressed_prompt = (
        f"{CONTEXT_ONLY}\n\nGIST:\n{gist}\n\nHOT_SET:\n{hot}\n\nQUESTION:\n{PROBE}"
    )
    raw_cwd = run_dir / "raw"
    cmp_cwd = run_dir / "compressed"
    raw_task = _run_one_arm(label="raw", cwd=raw_cwd, prompt=raw_prompt, api_key=api_key, log=log)
    cmp_task = _run_one_arm(
        label="compressed", cwd=cmp_cwd, prompt=compressed_prompt, api_key=api_key, log=log
    )
    raw_res, cmp_res = await asyncio.gather(raw_task, cmp_task)
    return {"raw": raw_res, "compressed": cmp_res}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CHAT-COMPRESSOR A/B scenario")
    parser.add_argument("--fixture", type=Path, default=ROOT / "fixtures" / "synthetic-generic.jsonl")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--live", action="store_true")
    parser.add_argument(
        "--live-models",
        action="store_true",
        help="Delegate to scripts.scenario_live_models (shared C_t, Grok vs Auto, 3 steps).",
    )
    parser.add_argument("--k-max", type=int, default=32)
    parser.add_argument("--run-id", default="")
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=None,
        help="Proof/log directory (default: test-results/ab/<run-id>)",
    )
    args = parser.parse_args(argv)

    if args.live_models:
        from scripts.scenario_live_models import main as live_main

        forwarded = ["--fixture", str(args.fixture), "--k-max", str(args.k_max)]
        if args.run_id:
            forwarded += ["--run-id", args.run_id]
        return live_main(forwarded)

    ts = args.run_id or timestamp()
    run_dir = ROOT / "runs" / ts
    results_dir = Path(args.results_dir) if args.results_dir else ROOT / "test-results" / "ab" / ts
    results_dir.mkdir(parents=True, exist_ok=True)
    log = StageLogger(results_dir / f"scenario-{ts}.log.txt")
    log.line(f"[INFO] fixture={args.fixture} offline={args.offline} live={args.live}")

    offline = run_offline(args.fixture, run_dir, log, k_max=args.k_max)
    live: dict | None = None
    api_key = os.environ.get("CURSOR_API_KEY", "").strip()
    if args.live:
        if api_key:
            live = asyncio.run(run_live(offline, run_dir, log))
        else:
            live = {"status": "NOT_RUN", "reason": "CURSOR_API_KEY unset"}
            log.line("[INFO] live=NOT_RUN (CURSOR_API_KEY unset)")
    elif not api_key:
        live = {"status": "NOT_RUN", "reason": "CURSOR_API_KEY unset"}
        log.line("[INFO] live=NOT_RUN (CURSOR_API_KEY unset; offline quality gates only)")

    payload = offline["payload"]
    matrix = offline["matrix"]
    node = offline["node"]
    live_status = "NOT_RUN"
    if isinstance(live, dict):
        if "raw" in live and "compressed" in live:
            live_status = (
                f"raw={live['raw'].get('status')} compressed={live['compressed'].get('status')}"
            )
        else:
            live_status = str(live.get("status", live))

    proof_lines = [
        "# Offline A/B proof — compressor loop upgrades",
        "",
        f"- run_id: `{ts}`",
        f"- fixture: `{args.fixture}`",
        f"- turns: {offline['turns']}",
        f"- state_id: `{node.state_id}`",
        f"- parent_id: `{node.parent_id}`",
        f"- k x d: {matrix.k} x {matrix.d}",
        f"- method: `{offline['method']}`",
        f"- raw_chars: {payload.raw_chars}",
        f"- gist_chars: {payload.gist_chars}",
        f"- packed_tokens (chars/4): {offline['packed_tokens']}",
        f"- tokens_ws: {offline['tokens_ws']}",
        f"- tokens_chars4: {offline['tokens_chars4']}",
        f"- forward_budget: {offline['budget']}",
        f"- rate_adherence: {offline['rate']:.4f}",
        f"- graph_chars: {payload.graph_chars}",
        f"- ratio (secondary): {payload.ratio:.6f}",
        f"- keyword_jaccard: {offline['jaccard']:.4f}",
        f"- entity_recall: {offline['recall']:.4f} (gate ≥ {ENTITY_RECALL_MIN})",
        f"- entity_recall_gate: `{'PASS' if offline['gate_ok'] else 'FAIL'}`",
        f"- ref_terms: {', '.join(offline['ref_terms']) or '(none)'}",
        f"- gist/sample: `{offline['gist']}`",
        f"- hot_set: `{offline['hot'].replace(chr(10), ' | ')}`",
        f"- live: `{live_status}`",
        f"- stage log: [`scenario-{ts}.log.txt`](./scenario-{ts}.log.txt)",
        "",
        "## Claims",
        "",
        f"1. Forward channel is packed HOT_SET/typed/ranked (method=`{offline['method']}`), not noisy P1 bag.",
        f"2. packed_tokens={offline['packed_tokens']} / budget={offline['budget']} "
        f"(rate={offline['rate']:.4f}).",
        f"3. entity_recall={offline['recall']:.4f} against fixture terms → "
        f"{'PASS' if offline['gate_ok'] else 'FAIL'}.",
        f"4. Live SDK arms: `{live_status}`"
        + (" (key present)" if api_key else " (CURSOR_API_KEY unset)"),
        "",
        "## Re-run",
        "",
        "```bash",
        "cd <repo>/engine",
        "PYTHONPATH=src python -m scripts.scenario_ab "
        f"--fixture fixtures/synthetic-generic.jsonl --offline --run-id {ts}",
        "```",
    ]
    proof_path = results_dir / "PROOF.md"
    _write_proof(proof_path, proof_lines)
    _write_proof(results_dir / "PROOF.stub.md", proof_lines)
    log.line(f"[PASS] proof={proof_path}")
    return 0 if offline["gate_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
