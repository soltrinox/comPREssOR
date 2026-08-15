"""Unit tests for chat_compressor.hook_cli (stdin fixtures, fail-open)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from chat_compressor import hook_cli


@pytest.fixture()
def state_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "context-graphs"
    root.mkdir()
    (root / "logs").mkdir()
    monkeypatch.setenv("CHAT_COMPRESSOR_STATE_DIR", str(root))
    monkeypatch.delenv("K_MAX", raising=False)
    monkeypatch.setenv("K_MAX", "8")
    # Avoid accidental HF / ST loads on the hook path.
    monkeypatch.delenv("EMBED_MODEL_PATH", raising=False)
    monkeypatch.delenv("GIST_MODEL_PATH", raising=False)
    return root


def _run(payload: dict, event: str, state_root: Path) -> dict:
    return hook_cli.process_payload(payload, event=event)


def test_before_submit_continue_and_state_advances(state_root: Path) -> None:
    payload = {
        "hook_event_name": "beforeSubmitPrompt",
        "conversation_id": "conv-test-1",
        "prompt": "add 'milk' and 'bread' to the open list for grocery planning.",
    }
    out = _run(payload, "beforeSubmitPrompt", state_root)
    assert out.get("continue") is True
    ctx = out.get("additional_context") or ""
    assert "OpenItem:" in ctx
    assert "milk" in ctx.lower() or "bread" in ctx.lower()
    store = hook_cli.StateStore(state_root)
    latest = store.load_latest("conv-test-1")
    assert latest is not None
    assert latest.t == 1
    assert latest.state_id.startswith("st_")

    out2 = _run(
        {
            "conversation_id": "conv-test-1",
            "prompt": "mark 'milk' done after purchase.",
        },
        "beforeSubmitPrompt",
        state_root,
    )
    assert out2["continue"] is True
    assert "additional_context" in out2
    latest2 = store.load_latest("conv-test-1")
    assert latest2 is not None
    assert latest2.t == 2
    assert latest2.parent_id == latest.state_id
    today = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%Y%m%d")
    stages = (state_root / "logs" / f"stages-{today}.log.txt").read_text(encoding="utf-8")
    assert "novel_tokens=" in stages
    assert "dup_suppressed_tokens=" in stages
    assert "facts_by_kind=" in stages
    assert "durable_facts=" in stages
    assert "build=" in stages
    assert "ingest_ok=1" in stages


def test_after_agent_response_persists_assistant(state_root: Path) -> None:
    _run(
        {"conversation_id": "conv-ar", "prompt": "plan the next three steps."},
        "beforeSubmitPrompt",
        state_root,
    )
    out = _run(
        {
            "conversation_id": "conv-ar",
            "text": "Step one is gather requirements. Step two is implement. Step three is test.",
        },
        "afterAgentResponse",
        state_root,
    )
    assert out == {}
    store = hook_cli.StateStore(state_root)
    latest = store.load_latest("conv-ar")
    assert latest is not None
    assert latest.t == 2


def test_session_start_additional_context_bounded(state_root: Path) -> None:
    _run(
        {
            "conversation_id": "conv-ss",
            "prompt": "add todo 'wire hooks' and note that context graphs store StateNodes.",
        },
        "beforeSubmitPrompt",
        state_root,
    )
    out = _run({"conversation_id": "conv-ss"}, "sessionStart", state_root)
    assert "additional_context" in out
    ctx = out["additional_context"]
    assert isinstance(ctx, str)
    assert len(ctx) <= hook_cli._MAX_CONTEXT_CHARS
    assert "CHAT-COMPRESSOR" in ctx
    assert "conv-ss" in ctx or "STATE" in ctx
    assert "HOT_SET" in ctx or "FORWARD_GIST" in ctx
    assert "file right add add check wait call create" not in ctx.lower()


def test_session_start_prefers_extractive_hot(state_root: Path) -> None:
    _run(
        {
            "conversation_id": "conv-ext",
            "prompt": (
                "Create todo 'buy groceries'. See fixtures/synthetic-generic.jsonl. "
                "Add 'milk' and 'bread'."
            ),
        },
        "beforeSubmitPrompt",
        state_root,
    )
    out = _run({"conversation_id": "conv-ext"}, "sessionStart", state_root)
    ctx = out["additional_context"].lower()
    assert "hot_set" in ctx
    assert "bread" in ctx or "groceries" in ctx or "milk" in ctx
    assert "file right add add" not in ctx


def test_pre_compact_writes_snapshot(state_root: Path) -> None:
    _run(
        {"conversation_id": "conv-pc", "prompt": "snapshot me please with open item 'freeze'."},
        "beforeSubmitPrompt",
        state_root,
    )
    out = _run({"conversation_id": "conv-pc"}, "preCompact", state_root)
    assert "user_message" in out
    assert "CHAT-COMPRESSOR" in out["user_message"]
    snap_dir = state_root / "conv-pc" / "precompact"
    assert snap_dir.is_dir()
    assert any(snap_dir.glob("graph-*.json"))
    assert any(snap_dir.glob("meta-*.json"))


def test_fail_open_on_bad_payload(state_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a, **_k):
        raise RuntimeError("forced")

    monkeypatch.setattr(hook_cli, "build_handle", boom)
    out = _run(
        {"conversation_id": "x", "prompt": "hi"},
        "beforeSubmitPrompt",
        state_root,
    )
    assert out == {"continue": True}
    err = state_root / "logs" / "hook-errors.log.txt"
    assert err.is_file()
    assert "forced" in err.read_text(encoding="utf-8")


def test_before_submit_sample_fail_open(state_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from chat_compressor.handle import PersistentAgentHandle

    orig_sample = PersistentAgentHandle.sample_for

    def boom(self, target: str, query: str | None = None):
        raise RuntimeError("sample-boom")

    monkeypatch.setattr(PersistentAgentHandle, "sample_for", boom)
    out = _run(
        {"conversation_id": "conv-fo", "prompt": "add 'milk' to the list."},
        "beforeSubmitPrompt",
        state_root,
    )
    assert out == {"continue": True}
    err = (state_root / "logs" / "hook-errors.log.txt").read_text(encoding="utf-8")
    assert "sample-boom" in err
    store = hook_cli.StateStore(state_root)
    assert store.load_latest("conv-fo") is not None
    monkeypatch.setattr(PersistentAgentHandle, "sample_for", orig_sample)


def test_agent_id_from_workspace_hash(state_root: Path) -> None:
    payload = {
        "workspace_roots": ["/tmp/proj-a", "/tmp/proj-b"],
        "session_id": "sess-9",
        "prompt": "hello from hashed workspace",
    }
    out = _run(payload, "beforeSubmitPrompt", state_root)
    assert out["continue"] is True
    agent_id = hook_cli.resolve_agent_id(payload)
    assert agent_id.startswith("ws-")
    store = hook_cli.StateStore(state_root)
    assert store.load_latest(agent_id) is not None


def test_main_exit_zero_and_stdout_json(state_root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    payload = json.dumps(
        {
            "hook_event_name": "beforeSubmitPrompt",
            "conversation_id": "conv-main",
            "prompt": "main entry smoke",
        }
    )
    # Simulate stdin
    import io

    old = hook_cli.sys.stdin
    try:
        hook_cli.sys.stdin = io.StringIO(payload)
        code = hook_cli.main(["--event", "beforeSubmitPrompt"])
    finally:
        hook_cli.sys.stdin = old
    assert code == 0
    captured = capsys.readouterr().out
    data = json.loads(captured)
    assert data.get("continue") is True
    assert "additional_context" in data


def test_step_raise_emits_fail_ingest_ok_zero(state_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from chat_compressor.handle import PersistentAgentHandle

    def boom(self, new_input: str, role: str = "user", *, flush_graph: bool | None = None):
        raise RuntimeError("forced-ingest")

    monkeypatch.setattr(PersistentAgentHandle, "step", boom)
    out = _run(
        {"conversation_id": "conv-fail-ingest", "prompt": "this should fail ingest"},
        "beforeSubmitPrompt",
        state_root,
    )
    assert out == {"continue": True}
    today = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%Y%m%d")
    stages = (state_root / "logs" / f"stages-{today}.log.txt").read_text(encoding="utf-8")
    assert "[FAIL]" in stages
    assert "ingest_ok=0" in stages
    assert "error_class=RuntimeError" in stages


def test_verify_compressor_health_nonzero_on_ingest_fail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import os
    import stat
    import subprocess
    from datetime import datetime, timezone

    root = tmp_path / "graphs"
    logs = root / "logs"
    logs.mkdir(parents=True)
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    (logs / "hook-errors.log.txt").write_text(
        f"{iso}T00:00:00+00:00 boom\n", encoding="utf-8"
    )
    (logs / f"stages-{today}.log.txt").write_text(
        "[FAIL] beforeSubmitPrompt agent=x ingest_ok=0 error_class=RuntimeError\n",
        encoding="utf-8",
    )
    script = Path(__file__).resolve().parents[1] / "scripts" / "verify-compressor-health.sh"
    assert script.is_file()
    env = os.environ.copy()
    env["CHAT_COMPRESSOR_STATE_DIR"] = str(root)
    proc = subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True)
    assert proc.returncode != 0
    assert "[FAIL]" in proc.stdout
    # executable bit for SDLC §9
    mode = script.stat().st_mode
    assert mode & stat.S_IXUSR


def test_no_cursor_api_key_required(state_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    assert "CURSOR_API_KEY" not in os.environ
    out = _run(
        {"conversation_id": "no-key", "prompt": "works without api key"},
        "beforeSubmitPrompt",
        state_root,
    )
    assert out.get("continue") is True
    assert "CURSOR_API_KEY" not in os.environ
