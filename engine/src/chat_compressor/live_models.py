"""Prompt templates, reply-merge, and model-id helpers for live Grok vs Auto.

Import-safe without cursor_sdk. Live I/O stays in scripts/scenario_live_models.py.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

CONTEXT_ONLY = "Answer from the provided context only. Do not use tools."
MERGE_HINT = (
    "Answer using this merged payload. Prefer the gist and hot-set over restating history."
)

GROK_FALLBACK = "cursor-grok-4.6-high-fast"
AUTO_FALLBACK = "auto"

STEP_ORDER: tuple[str, ...] = ("analyze", "plan", "collapse")

STEP_PROMPTS: dict[str, str] = {
    "analyze": (
        "Identify crosswalks among fixture turns, workspace inventory, and graph nodes. "
        "Emit a token-forward payload (relations, open items, artifacts) to merge into step 2."
    ),
    "plan": (
        "Link that payload to workspace modules (store, handle, translate). "
        "Structure goals / tasks / actions plus pattern, architecture, protocol, "
        "algorithm to execute."
    ),
    "collapse": (
        "Execute/consider the plan against the compressed matrix history "
        "(gist + k×d + parent_id) and support structures; collapse the plan to a "
        "short outcome list. Do not re-expand discarded raw turns."
    ),
}

TOKEN_RE = re.compile(r"[a-z0-9]+", re.I)


def merge_forward_payload(
    *,
    gist: str,
    hot_set: str,
    prior_reply: str,
    next_task: str,
    extra_context: str = "",
) -> str:
    """Build the forward prompt: gist + hot_set + prior reply + next task."""
    prior = prior_reply.strip() or "(none)"
    parts = [
        CONTEXT_ONLY,
        "",
        f"FORWARD_GIST: {gist}",
        f"HOT_SET: {hot_set}",
        f"PRIOR_STEP_REPLY: {prior}",
        f"NEXT_TASK: {next_task}",
    ]
    extra = extra_context.strip()
    if extra:
        parts.extend(["", "WORKSPACE_INVENTORY:", extra])
    parts.extend(["", MERGE_HINT])
    return "\n".join(parts)


def build_three_step_payloads(
    *,
    gist: str,
    hot_set: str,
    prior_replies: Sequence[str] | None = None,
    inventory: str = "",
    gists: Sequence[str] | None = None,
    hot_sets: Sequence[str] | None = None,
) -> list[str]:
    """Build analyze → plan → collapse prompts without calling an LLM.

    ``prior_replies[i]`` is the model text from step i+1, used as PRIOR_STEP_REPLY
    for the following step. Optional ``gists`` / ``hot_sets`` override the shared
    snapshot per step (per-arm matrix after reply-merge).
    """
    priors = list(prior_replies or [])
    out: list[str] = []
    for i, name in enumerate(STEP_ORDER):
        prior = priors[i - 1] if i > 0 and (i - 1) < len(priors) else ""
        step_gist = gists[i] if gists is not None and i < len(gists) else gist
        step_hot = hot_sets[i] if hot_sets is not None and i < len(hot_sets) else hot_set
        extra = inventory if i == 0 else ""
        out.append(
            merge_forward_payload(
                gist=step_gist,
                hot_set=step_hot,
                prior_reply=prior,
                next_task=STEP_PROMPTS[name],
                extra_context=extra,
            )
        )
    return out


def tokenize(text: str) -> set[str]:
    return {m.group(0).lower() for m in TOKEN_RE.finditer(text or "")}


def gist_keywords(gist: str) -> set[str]:
    return tokenize(gist)


def token_jaccard(a: str, b: str) -> float:
    sa, sb = tokenize(a), tokenize(b)
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def workspace_inventory(root: Path) -> str:
    """Compact listing of CHAT-COMPRESSOR files only — never walks the parent work tree."""
    root = root.resolve()
    lines = [f"project={root.name}"]
    readme = root / "README.md"
    if readme.is_file():
        headline = next(
            (ln.strip("# ").strip() for ln in readme.read_text(encoding="utf-8").splitlines() if ln.strip()),
            "",
        )
        lines.append(f"- README.md{(': ' + headline) if headline else ''}")
    schema = root / "schema"
    if schema.is_dir():
        for path in sorted(schema.glob("*.json")):
            lines.append(f"- schema/{path.name}")
    src = root / "src" / "chat_compressor"
    if src.is_dir():
        for path in sorted(src.rglob("*.py")):
            if path.name == "__init__.py":
                continue
            rel = path.relative_to(root)
            lines.append(f"- {rel.as_posix()}")
    return "\n".join(lines)


def assert_isolated_cwd(cwd: Path, project_root: Path) -> Path:
    """Refuse project root and anything outside project runs/."""
    resolved = cwd.resolve()
    root = project_root.resolve()
    if resolved == root:
        raise ValueError(f"SDK cwd must not be project root {root}")
    runs = (root / "runs").resolve()
    try:
        resolved.relative_to(runs)
    except ValueError as exc:
        raise ValueError(f"SDK cwd must be under {runs}, got {resolved}") from exc
    return resolved


def _pick_model_id(available: Sequence[str], want: str, aliases: Sequence[str] = ()) -> str | None:
    lower_map = {item.lower(): item for item in available if item}
    if want.lower() in lower_map:
        return lower_map[want.lower()]
    for alias in aliases:
        if alias.lower() in lower_map:
            return lower_map[alias.lower()]
    for item in available:
        blob = item.lower()
        if want.lower() in blob or any(alias.lower() in blob for alias in aliases):
            return item
    return None


def resolve_model_ids(
    available_ids: Sequence[str],
    *,
    grok_want: str = GROK_FALLBACK,
    auto_want: str = AUTO_FALLBACK,
) -> dict[str, Any]:
    """Map requested arms onto Cursor.models.list() ids with documented fallbacks."""
    ids = [str(x) for x in available_ids]
    grok = _pick_model_id(ids, grok_want, aliases=("grok-4.6-high-fast", "grok-4.6"))
    auto = _pick_model_id(ids, auto_want, aliases=("auto", "auto-smart"))
    missing: list[str] = []
    if grok is None:
        missing.append(grok_want)
    if auto is None:
        missing.append(auto_want)
    return {
        "grok": grok,
        "auto": auto,
        "missing": missing,
        "available": ids,
        "grok_want": grok_want,
        "auto_want": auto_want,
    }


def extract_model_ids(models: Any) -> list[str]:
    """Normalize Cursor.models.list() / ListResult / iterable of SDKModel."""
    if models is None:
        return []
    seq: Iterable[Any]
    items = getattr(models, "items", None)
    if items is not None and not isinstance(models, (str, bytes)):
        seq = items
    elif isinstance(models, dict):
        seq = models.get("items") or models.get("models") or models.values()
    else:
        seq = models
    ids: list[str] = []
    for model in seq:
        if model is None:
            continue
        mid = getattr(model, "id", None)
        if mid is None and isinstance(model, dict):
            mid = model.get("id")
        if mid is None and isinstance(model, str):
            mid = model
        if mid:
            ids.append(str(mid))
    return ids


def grade_arm(step_ok: Sequence[bool], attempted: bool) -> str:
    if not attempted:
        return "NOT_RUN"
    if not step_ok:
        return "FAIL"
    if all(step_ok):
        return "FULL"
    if any(step_ok):
        return "PARTIAL"
    return "FAIL"


def render_proof(payload: dict[str, Any]) -> str:
    """Side-by-side live-models proof markdown."""
    ts = payload.get("ts", "")
    live_status = payload.get("live_status", "NOT_RUN")
    gap = payload.get("gap", "")
    shared = payload.get("shared") or {}
    grok = payload.get("grok") or {}
    auto = payload.get("auto") or {}
    resolved = payload.get("resolved") or {}
    rerun = payload.get("rerun", "")
    log_name = payload.get("log_name", f"stages-{ts}.log.txt")

    def _cell(arm: dict[str, Any], key: str, default: str = "—") -> str:
        val = arm.get(key, default)
        return default if val in (None, "") else str(val)

    lines = [
        "# Live Grok vs Auto — log proof",
        "",
        f"**Run id:** `{ts}`",
        f"**Date:** {payload.get('date', ts)}",
        f"**Project:** `{payload.get('project', '')}`",
        f"**live_status:** {live_status}",
        f"**convergence_status:** {payload.get('convergence_status', 'NOT_CONVERGED')}",
        "",
        "## Claims (log-backed)",
        "",
        "| Claim | Evidence |",
        "|-------|----------|",
        f"| Shared C_t compress (once) | [{log_name}]({log_name}) — agent_id=`shared-compress` k={shared.get('k')} d={shared.get('d')} |",
        f"| Isolated cwds | {payload.get('cwd_note', f'`runs/{ts}/{{grok,auto}}/` (never project root)')} |",
        f"| Grok model id | `{resolved.get('grok') or GROK_FALLBACK}` |",
        f"| Auto model id | `{resolved.get('auto') or AUTO_FALLBACK}` |",
        f"| Live 3-step pipelines | {live_status}" + (f" — {gap}" if gap else "") + " |",
        f"| Unit tests (no SDK) | {payload.get('pytest_grade', 'see tests/test_live_models.py')} |",
        f"| Grok grade | {_cell(grok, 'grade')} |",
        f"| Auto grade | {_cell(auto, 'grade')} |",
        "",
        "## Shared compression snapshot",
        "",
        "| Field | Value |",
        "|-------|-------|",
        f"| agent_id | `shared-compress` |",
        f"| state_id | `{shared.get('state_id', '')}` |",
        f"| parent_id | `{shared.get('parent_id', 'none')}` |",
        f"| k × d | {shared.get('k')} × {shared.get('d')} |",
        f"| raw_chars | {shared.get('raw_chars')} |",
        f"| gist_chars | {shared.get('gist_chars')} |",
        f"| graph_chars | {shared.get('graph_chars')} |",
        f"| gist | `{shared.get('gist', '')}` |",
        "",
        "## Side-by-side",
        "",
        "| Metric | grok | auto |",
        "|--------|------|------|",
        f"| model_id | {_cell(grok, 'model_id')} | {_cell(auto, 'model_id')} |",
        f"| compressor agent_id | `{_cell(grok, 'handle_agent_id', 'live-grok')}` | `{_cell(auto, 'handle_agent_id', 'live-auto')}` |",
        f"| sdk agent_id | {_cell(grok, 'sdk_agent_id')} | {_cell(auto, 'sdk_agent_id')} |",
        f"| step1 latency_ms | {_cell(grok, 'latency_1')} | {_cell(auto, 'latency_1')} |",
        f"| step2 latency_ms | {_cell(grok, 'latency_2')} | {_cell(auto, 'latency_2')} |",
        f"| step3 latency_ms | {_cell(grok, 'latency_3')} | {_cell(auto, 'latency_3')} |",
        f"| total latency_ms | {_cell(grok, 'latency_total')} | {_cell(auto, 'latency_total')} |",
        f"| step3 gist_chars | {_cell(grok, 'gist_chars')} | {_cell(auto, 'gist_chars')} |",
        f"| step3 k × d | {_cell(grok, 'shape')} | {_cell(auto, 'shape')} |",
        f"| step3 parent_id | {_cell(grok, 'parent_id')} | {_cell(auto, 'parent_id')} |",
        f"| Jaccard(step3, shared gist) | {_cell(grok, 'jaccard')} | {_cell(auto, 'jaccard')} |",
        f"| grade | {_cell(grok, 'grade')} | {_cell(auto, 'grade')} |",
        "",
        "No winner is declared from these metrics alone.",
        "",
        "## Reply dumps",
        "",
        f"- [grok-step1.txt](grok-step1.txt) · [grok-step2.txt](grok-step2.txt) · [grok-step3.txt](grok-step3.txt)",
        f"- [auto-step1.txt](auto-step1.txt) · [auto-step2.txt](auto-step2.txt) · [auto-step3.txt](auto-step3.txt)",
        "",
        "## Environment grades",
        "",
        "| Environment | Build | Test | Deploy | Lifecycle | Grade |",
        "|-------------|-------|------|--------|-----------|-------|",
        f"| Unit tests (no SDK) | n/a | {payload.get('pytest_grade', 'see pytest')} | n/a | n/a | {payload.get('pytest_grade', 'n/a')} |",
        f"| Shared offline compress | n/a | PASS | n/a | StateNode persist | FULL |",
        f"| Live Grok 3-step | n/a | {live_status} | n/a | durable send+wait | {_cell(grok, 'grade')} |",
        f"| Live Auto 3-step | n/a | {live_status} | n/a | durable send+wait | {_cell(auto, 'grade')} |",
        f"| Docker | n/a | n/a | n/a | no Dockerfile | NOT_RUN |",
        "",
    ]
    if gap or live_status == "NOT_RUN":
        lines.extend(
            [
                "## Live SDK gap",
                "",
                "Phase 0 did not start both durable agents. Gap:",
                "",
                "```text",
                gap or "unspecified",
                "```",
                "",
            ]
        )
    lines.extend(
        [
            "## Re-run",
            "",
            "```bash",
            rerun.strip(),
            "```",
            "",
            "## Provenance",
            "",
            "| Section | Source | Type |",
            "|---------|--------|------|",
            f"| Stages | {log_name} | Live capture |",
            "| Merge helper | src/chat_compressor/live_models.py | Unit-tested |",
            "",
        ]
    )
    return "\n".join(lines)
