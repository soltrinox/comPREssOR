"""CC-9: fail-open advisory inclusion in additional_context."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from chat_compressor import hook_cli
from chat_compressor.handle import PersistentAgentHandle
from chat_compressor.producer import EmbeddingProducer
from chat_compressor.store import StateStore


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _fresh_payload(*, expires_in: int = 300, model_id: str = "cursor-grok-test") -> dict:
    now = datetime.now(timezone.utc)
    return {
        "schema": "compass-advisory/v1",
        "written_at": _iso(now),
        "expires_at": _iso(now + timedelta(seconds=expires_in)),
        "task_class": "multi_file_refactor",
        "recommendation": {
            "model_id": model_id,
            "provider": "cursor",
            "model_version_id": "urn:mg:modelversion:test",
        },
        "rationale": "Across your last 40 tasks of this class, X scored 0.82 at $0.11/task.",
        "route_decision_id": "urn:mg:routedecision:test",
        "scores_summary": [
            {"model_id": "X", "quality_mean": 0.82, "n": 40, "est_cost_per_task": 0.11}
        ],
    }


@pytest.fixture()
def state_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "context-graphs"
    root.mkdir()
    (root / "logs").mkdir()
    monkeypatch.setenv("CHAT_COMPRESSOR_STATE_DIR", str(root))
    monkeypatch.setenv("K_MAX", "8")
    monkeypatch.delenv("CHAT_COMPRESSOR_ADVISORY_PATH", raising=False)
    monkeypatch.delenv("EMBED_MODEL_PATH", raising=False)
    monkeypatch.delenv("GIST_MODEL_PATH", raising=False)
    return root


def _write_advisory(state_root: Path, payload: dict | str, *, name: str = "latest.json") -> Path:
    dest = state_root / "advisory" / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, str):
        dest.write_text(payload, encoding="utf-8")
    else:
        dest.write_text(json.dumps(payload), encoding="utf-8")
    return dest


def _handle(state_root: Path) -> PersistentAgentHandle:
    return PersistentAgentHandle(
        agent_id="cc9-agent",
        store=StateStore(state_root),
        producer=EmbeddingProducer(d=64, k_max=8),
        k_max=8,
    )


def test_fresh_advisory_appears_in_additional_context(state_root: Path) -> None:
    _write_advisory(state_root, _fresh_payload(model_id="cursor-grok-fresh"))
    handle = _handle(state_root)
    handle.step("refactor the auth module across packages", role="user")
    ctx = hook_cli._compose_additional_context(
        handle, "packed-forward", "cc9-agent", method="pack", state_root=state_root
    )
    assert "COMPASS_ADVISORY:" in ctx
    assert "recommended_model=cursor-grok-fresh" in ctx
    assert "multi_file_refactor" in ctx


def test_missing_advisory_fail_open(state_root: Path) -> None:
    handle = _handle(state_root)
    handle.step("hello world note", role="user")
    ctx = hook_cli._compose_additional_context(
        handle, "packed-forward", "cc9-agent", method="pack", state_root=state_root
    )
    assert "COMPASS_ADVISORY:" not in ctx
    assert "CHAT-COMPRESSOR session memory" in ctx
    # Event-safe beforeSubmit still continues.
    out = hook_cli.process_payload(
        {
            "hook_event_name": "beforeSubmitPrompt",
            "conversation_id": "cc9-missing",
            "prompt": "add todo milk to the list",
        },
        event="beforeSubmitPrompt",
    )
    assert out.get("continue") is True


def test_stale_advisory_ignored(state_root: Path) -> None:
    payload = _fresh_payload(expires_in=-60)  # already expired
    _write_advisory(state_root, payload)
    assert hook_cli._load_advisory_context_line(state_root) is None
    handle = _handle(state_root)
    ctx = hook_cli._compose_additional_context(
        handle, "gist", "cc9-agent", method="pack", state_root=state_root
    )
    assert "COMPASS_ADVISORY:" not in ctx
    out = hook_cli.process_payload(
        {
            "conversation_id": "cc9-stale",
            "prompt": "plan the grocery list with milk and bread",
        },
        event="beforeSubmitPrompt",
    )
    assert out.get("continue") is True


def test_corrupt_advisory_ignored(state_root: Path) -> None:
    _write_advisory(state_root, "{not-json")
    assert hook_cli._load_advisory_context_line(state_root) is None
    out = hook_cli.process_payload(
        {
            "conversation_id": "cc9-corrupt",
            "prompt": "note that context graphs store StateNodes for sessions",
        },
        event="beforeSubmitPrompt",
    )
    assert out.get("continue") is True
    ctx = out.get("additional_context") or ""
    assert "COMPASS_ADVISORY:" not in ctx


def test_malformed_schema_ignored(state_root: Path) -> None:
    payload = _fresh_payload()
    payload["schema"] = "other/v0"
    _write_advisory(state_root, payload)
    assert hook_cli._load_advisory_context_line(state_root) is None


def test_advisory_path_env_override(state_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    custom = state_root / "custom" / "adv.json"
    custom.parent.mkdir(parents=True)
    custom.write_text(json.dumps(_fresh_payload(model_id="override-model")), encoding="utf-8")
    monkeypatch.setenv("CHAT_COMPRESSOR_ADVISORY_PATH", str(custom))
    line = hook_cli._load_advisory_context_line(state_root)
    assert line is not None
    assert "override-model" in line
