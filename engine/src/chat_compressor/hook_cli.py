"""Cursor IDE hook entrypoint: fail-open JSON I/O for chat compression side-process.

Never requires CURSOR_API_KEY. Always exits 0. Errors log to state logs and
emit the event-safe default JSON so Agent Chat is never blocked.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from chat_compressor.envfile import load_env_file
from chat_compressor.graph import KINDS, CtxGraph
from chat_compressor.handle import PersistentAgentHandle
from chat_compressor.pack import forward_budget
from chat_compressor.producer import make_producer
from chat_compressor.store import StateStore

# ~2k tokens ≈ 8k chars hard cap for sessionStart injection.
_MAX_CONTEXT_CHARS = 8000
_SAFE_AGENT_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def default_state_root() -> Path:
    return Path.home() / ".cursor" / "context-graphs"


def default_env_path() -> Path:
    return Path.home() / ".cursor" / "chat-compressor.env"


def load_hook_env() -> None:
    """Load ~/.cursor/chat-compressor.env then honor CHAT_COMPRESSOR_STATE_DIR / K_MAX."""
    load_env_file(default_env_path())


def resolve_state_root() -> Path:
    load_hook_env()
    raw = os.environ.get("CHAT_COMPRESSOR_STATE_DIR", "").strip()
    if raw:
        return Path(raw).expanduser()
    return default_state_root()


def resolve_k_max() -> int:
    load_hook_env()
    raw = os.environ.get("K_MAX", "").strip()
    if not raw:
        return 32
    try:
        return max(1, int(raw))
    except ValueError:
        return 32


def logs_dir(state_root: Path) -> Path:
    path = state_root / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_error(state_root: Path, message: str) -> None:
    try:
        dest = logs_dir(state_root) / "hook-errors.log.txt"
        with dest.open("a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now(timezone.utc).isoformat()} {message}\n")
    except OSError:
        pass


def log_stage(state_root: Path, line: str) -> None:
    try:
        dest = logs_dir(state_root) / f"stages-{_now_stamp()[:8]}.log.txt"
        with dest.open("a", encoding="utf-8") as fh:
            fh.write(line.rstrip() + "\n")
    except OSError:
        pass


def _stage_tag(*, ingest_ok: int, method: str, error_class: str) -> str:
    if ingest_ok == 0 or error_class or method == "none":
        return "FAIL"
    return "PASS"


def build_stamp() -> str:
    try:
        from importlib.metadata import version

        return version("chat-compressor")
    except Exception:  # noqa: BLE001
        return "0.1.4"


def _roi_fields(handle: PersistentAgentHandle, sampled: Any | None) -> str:
    mix = handle.graph.kind_counts()
    facts_by_kind = ",".join(f"{k}:{mix.get(k, 0)}" for k in KINDS)
    novel = 0 if sampled is None else int(getattr(sampled, "novel_tokens", 0) or 0)
    dup = 0 if sampled is None else int(getattr(sampled, "dup_suppressed_tokens", 0) or 0)
    return (
        f"novel_tokens={novel} dup_suppressed_tokens={dup} "
        f"facts_by_kind={facts_by_kind} durable_facts={handle.graph.durable_fact_count()} "
        f"build={build_stamp()}"
    )


def _format_stage(
    event: str,
    agent_id: str,
    extra: str,
    *,
    ingest_ok: int,
    error_class: str = "",
    method: str = "",
) -> str:
    tag = _stage_tag(ingest_ok=ingest_ok, method=method, error_class=error_class)
    body = extra.strip()
    return (
        f"[{tag}] {event} agent={agent_id} ingest_ok={ingest_ok} "
        f"error_class={error_class} {body}"
    ).rstrip()


def sanitize_agent_id(raw: str) -> str:
    cleaned = _SAFE_AGENT_RE.sub("-", raw.strip())[:120]
    return cleaned or "default"


def resolve_agent_id(payload: dict[str, Any]) -> str:
    for key in ("conversation_id", "conversationId", "agent_id", "agentId"):
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            return sanitize_agent_id(val)
    roots = payload.get("workspace_roots") or payload.get("workspaceRoots") or []
    if isinstance(roots, str):
        roots = [roots]
    session = (
        payload.get("session_id")
        or payload.get("sessionId")
        or payload.get("generation_id")
        or payload.get("generationId")
        or ""
    )
    blob = "|".join(str(r) for r in roots) + "|" + str(session)
    digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]
    return f"ws-{digest}"


def extract_prompt(payload: dict[str, Any]) -> str:
    for key in ("prompt", "user_prompt", "userPrompt", "message", "text", "input"):
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            return val
    return ""


def extract_assistant_text(payload: dict[str, Any]) -> str:
    for key in ("text", "response", "assistant_text", "assistantText", "output", "message"):
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            return val
    return ""


def detect_event(payload: dict[str, Any], cli_event: str | None) -> str:
    if cli_event:
        return cli_event
    for key in ("hook_event_name", "hookEventName", "event"):
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return "beforeSubmitPrompt"


def fail_open_default(event: str) -> dict[str, Any]:
    if event == "beforeSubmitPrompt":
        return {"continue": True}
    if event == "sessionStart":
        return {"additional_context": ""}
    if event == "preCompact":
        return {}
    return {}


def _load_graph_for_agent(store: StateStore, agent_id: str) -> tuple[CtxGraph, int]:
    latest = store.load_latest(agent_id)
    agent_dir = Path(store.root) / agent_id
    working = agent_dir / "graph.json"
    if working.is_file():
        try:
            t = int(latest.t) if latest is not None else 0
            return CtxGraph.load(working), t
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            pass
    if latest is None:
        return CtxGraph(), 0
    if latest.graph_path and Path(latest.graph_path).is_file():
        try:
            return CtxGraph.load(latest.graph_path), int(latest.t)
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            pass
    return CtxGraph(), int(latest.t)


def build_handle(agent_id: str, store: StateStore, k_max: int) -> PersistentAgentHandle:
    graph, turn_index = _load_graph_for_agent(store, agent_id)
    # Use make_producer as designed (hashed when EMBED/GIST unset; no force override).
    producer = make_producer(k_max=k_max)
    handle = PersistentAgentHandle(
        agent_id=agent_id,
        store=store,
        producer=producer,
        graph=graph,
        k_max=k_max,
    )
    handle._turn_index = turn_index
    if latest := store.load_latest(agent_id):
        if latest.graph_path:
            handle._last_graph_path = latest.graph_path
    return handle


def _truncate_context(text: str, max_chars: int = _MAX_CONTEXT_CHARS) -> str:
    text = text.strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def _compose_additional_context(
    handle: PersistentAgentHandle,
    sampled_text: str,
    agent_id: str,
    *,
    method: str = "",
) -> str:
    parts: list[str] = [
        "CHAT-COMPRESSOR session memory (prefer HOT_SET / typed / ranked FORWARD_GIST; do not restate full history).",
    ]
    packed = (sampled_text or "").strip()
    if packed:
        parts.append(packed)
    elif method != "skip":
        hot = handle.graph.hot_set()
        if hot:
            parts.append("HOT_SET:\n" + hot)
    latest = handle.latest()
    if latest is not None:
        parts.append(f"STATE: agent_id={agent_id} t={latest.t} state_id={latest.state_id}")
    return _truncate_context("\n\n".join(parts))


def handle_before_submit(
    payload: dict[str, Any], store: StateStore, state_root: Path, k_max: int
) -> dict[str, Any]:
    agent_id = resolve_agent_id(payload)
    prompt = extract_prompt(payload)
    if not prompt:
        return {"continue": True}
    budget = forward_budget()
    method = "none"
    packed_tokens = 0
    rank_ms = 0.0
    rate = 0.0
    t = 0
    state_id = ""
    flush = 0
    compress_ms = 0.0
    persist_ms = 0.0
    handle: PersistentAgentHandle | None = None
    try:
        handle = build_handle(agent_id, store, k_max)
        out = handle.step(prompt, role="user")
        t = out.t
        state_id = out.state_id
        flush = int(out.graph_flushed)
        compress_ms = out.compress_ms
        persist_ms = out.persist_ms
    except Exception as exc:  # noqa: BLE001 — fail-open: ingest crashed
        log_error(state_root, f"beforeSubmitPrompt ingest error={exc!r}\n{traceback.format_exc()}")
        log_stage(
            state_root,
            _format_stage(
                "beforeSubmitPrompt",
                agent_id,
                f"t={t} state_id={state_id} flush={flush} compress_ms={compress_ms:.2f} "
                f"persist_ms={persist_ms:.2f} method={method} packed_tokens={packed_tokens} "
                f"budget={budget} rank_ms={rank_ms:.2f}",
                ingest_ok=0,
                error_class=type(exc).__name__,
                method=method,
            ),
        )
        return {"continue": True}

    try:
        sampled = handle.sample_for("cursor-sdk", query=prompt)
        method = sampled.method
        packed_tokens = int(sampled.packed_tokens)
        rank_ms = float(sampled.rank_ms)
        rate = float(sampled.rate)
        budget = int(sampled.budget or budget)
        context = _compose_additional_context(handle, sampled.text, agent_id, method=method)
        log_stage(
            state_root,
            _format_stage(
                "beforeSubmitPrompt",
                agent_id,
                f"t={t} state_id={state_id} flush={flush} compress_ms={compress_ms:.2f} "
                f"persist_ms={persist_ms:.2f} method={method} packed_tokens={packed_tokens} "
                f"budget={budget} rank_ms={rank_ms:.2f} rate={rate:.4f} {_roi_fields(handle, sampled)}",
                ingest_ok=1,
                method=method,
            ),
        )
        return {"continue": True, "additional_context": context}
    except Exception as exc:  # noqa: BLE001 — fail-open: persist already done
        log_error(state_root, f"beforeSubmitPrompt sample error={exc!r}\n{traceback.format_exc()}")
        log_stage(
            state_root,
            _format_stage(
                "beforeSubmitPrompt",
                agent_id,
                f"t={t} state_id={state_id} flush={flush} compress_ms={compress_ms:.2f} "
                f"persist_ms={persist_ms:.2f} method={method} packed_tokens={packed_tokens} "
                f"budget={budget} rank_ms={rank_ms:.2f}",
                ingest_ok=1,
                error_class=type(exc).__name__,
                method=method,
            ),
        )
        return {"continue": True}


def handle_after_response(
    payload: dict[str, Any], store: StateStore, state_root: Path, k_max: int
) -> dict[str, Any]:
    agent_id = resolve_agent_id(payload)
    text = extract_assistant_text(payload)
    if not text:
        return {}
    try:
        handle = build_handle(agent_id, store, k_max)
        out = handle.step(text, role="assistant")
        log_stage(
            state_root,
            _format_stage(
                "afterAgentResponse",
                agent_id,
                f"t={out.t} state_id={out.state_id} flush={int(out.graph_flushed)} "
                f"compress_ms={out.compress_ms:.2f} persist_ms={out.persist_ms:.2f} "
                f"{_roi_fields(handle, None)}",
                ingest_ok=1,
            ),
        )
    except Exception as exc:  # noqa: BLE001 — fail-open
        log_error(state_root, f"afterAgentResponse ingest error={exc!r}\n{traceback.format_exc()}")
        log_stage(
            state_root,
            _format_stage(
                "afterAgentResponse",
                agent_id,
                "t=0 state_id= flush=0 compress_ms=0.00 persist_ms=0.00",
                ingest_ok=0,
                error_class=type(exc).__name__,
            ),
        )
    return {}


def handle_pre_compact(
    payload: dict[str, Any], store: StateStore, state_root: Path, k_max: int
) -> dict[str, Any]:
    agent_id = resolve_agent_id(payload)
    try:
        handle = build_handle(agent_id, store, k_max)
        # Always flush graph on preCompact.
        flushed = handle.flush_graph()
        latest = handle.latest()
        snap_dir = state_root / agent_id / "precompact"
        snap_dir.mkdir(parents=True, exist_ok=True)
        stamp = _now_stamp()
        graph_snap = snap_dir / f"graph-{stamp}.json"
        handle.graph.save(graph_snap)
        meta = {
            "agent_id": agent_id,
            "state_id": None if latest is None else latest.state_id,
            "t": None if latest is None else latest.t,
            "graph_path": str(graph_snap),
            "flushed_graph": flushed,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        (snap_dir / f"meta-{stamp}.json").write_text(
            json.dumps(meta, separators=(",", ":")) + "\n", encoding="utf-8"
        )
        log_stage(
            state_root,
            _format_stage(
                "preCompact",
                agent_id,
                f"snapshot={graph_snap.name} flush=1",
                ingest_ok=1,
            ),
        )
        notice = (
            f"CHAT-COMPRESSOR: frozen context graph snapshot for {agent_id} "
            f"(t={meta['t']}, state_id={meta['state_id']})."
        )
        return {"user_message": notice}
    except Exception as exc:  # noqa: BLE001 — fail-open
        log_error(state_root, f"preCompact error={exc!r}\n{traceback.format_exc()}")
        log_stage(
            state_root,
            _format_stage(
                "preCompact",
                agent_id,
                "snapshot= flush=0",
                ingest_ok=0,
                error_class=type(exc).__name__,
            ),
        )
        return {}


def handle_session_start(
    payload: dict[str, Any], store: StateStore, state_root: Path, k_max: int
) -> dict[str, Any]:
    agent_id = resolve_agent_id(payload)
    method = "hot_set"
    packed_tokens = 0
    budget = forward_budget()
    rank_ms = 0.0
    rate = 0.0
    gist = ""
    sample_ms = 0.0
    error_class = ""
    ingest_ok = 1
    handle: PersistentAgentHandle | None = None
    try:
        handle = build_handle(agent_id, store, k_max)
        # Always flush graph on sessionStart.
        handle.flush_graph()
    except Exception as exc:  # noqa: BLE001 — fail-open
        ingest_ok = 0
        error_class = type(exc).__name__
        log_error(state_root, f"sessionStart ingest error={exc!r}\n{traceback.format_exc()}")
        log_stage(
            state_root,
            _format_stage(
                "sessionStart",
                agent_id,
                f"context_chars=0 method={method} packed_tokens={packed_tokens} "
                f"budget={budget} rank_ms={rank_ms:.2f} rate={rate:.4f} sample_ms=0.00 flush=0",
                ingest_ok=0,
                error_class=error_class,
                method=method,
            ),
        )
        return {"additional_context": ""}

    sampled = None
    try:
        sampled = handle.sample_for("cursor-sdk")
        gist = (sampled.text or "").strip()
        method = sampled.method
        packed_tokens = int(sampled.packed_tokens)
        rank_ms = float(sampled.rank_ms)
        rate = float(sampled.rate)
        sample_ms = handle.last_sample_ms
    except Exception as exc:  # noqa: BLE001 — fail-open path
        error_class = type(exc).__name__
        log_error(state_root, f"sessionStart sample error={exc!r}\n{traceback.format_exc()}")
    context = _compose_additional_context(handle, gist, agent_id, method=method)
    log_stage(
        state_root,
        _format_stage(
            "sessionStart",
            agent_id,
            f"context_chars={len(context)} method={method} packed_tokens={packed_tokens} "
            f"budget={budget} rank_ms={rank_ms:.2f} rate={rate:.4f} "
            f"sample_ms={sample_ms:.2f} flush=1 {_roi_fields(handle, sampled)}",
            ingest_ok=ingest_ok,
            error_class=error_class,
            method=method,
        ),
    )
    return {"additional_context": context}


HANDLERS = {
    "beforeSubmitPrompt": handle_before_submit,
    "afterAgentResponse": handle_after_response,
    "preCompact": handle_pre_compact,
    "sessionStart": handle_session_start,
}


def process_payload(payload: dict[str, Any], event: str | None = None) -> dict[str, Any]:
    state_root = resolve_state_root()
    state_root.mkdir(parents=True, exist_ok=True)
    logs_dir(state_root)
    resolved = detect_event(payload, event)
    k_max = resolve_k_max()
    handler = HANDLERS.get(resolved)
    if handler is None:
        log_error(state_root, f"unknown event={resolved}")
        return fail_open_default(resolved)
    try:
        store = StateStore(state_root)
        return handler(payload, store, state_root, k_max)
    except Exception as exc:  # noqa: BLE001 — fail-open invariant
        log_error(state_root, f"event={resolved} error={exc!r}\n{traceback.format_exc()}")
        return fail_open_default(resolved)


def read_stdin_json() -> dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def emit(obj: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False))
    sys.stdout.flush()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CHAT-COMPRESSOR Cursor hook CLI (fail-open)")
    parser.add_argument(
        "--event",
        default=None,
        help="Hook event name (or read hook_event_name from stdin JSON)",
    )
    args = parser.parse_args(argv)
    # Fail-open wrapper around the entire process.
    try:
        payload = read_stdin_json()
        result = process_payload(payload, event=args.event)
        emit(result)
    except Exception as exc:  # noqa: BLE001
        try:
            root = resolve_state_root()
            log_error(root, f"fatal={exc!r}\n{traceback.format_exc()}")
        except Exception:  # noqa: BLE001
            pass
        event = args.event or "beforeSubmitPrompt"
        emit(fail_open_default(event))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
