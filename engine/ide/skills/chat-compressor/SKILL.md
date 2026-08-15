---
name: chat-compressor
description: >-
  Use when the user or session mentions compressed chat memory, context graphs,
  FORWARD_GIST, hot_set, StateNode lineage, or CHAT-COMPRESSOR IDE hooks.
  Progressive disclosure for schema/ontology — not every Agent turn.
---

# CHAT-COMPRESSOR skill

## When to load

Only when compression, context-graph, or latent state persistence is relevant.
Do not load this skill for unrelated coding tasks.

## What the hooks do

User-global Cursor hooks call `python -m chat_compressor.hook_cli` (fail-open):

| Event | Side effect |
|-------|-------------|
| `beforeSubmitPrompt` | `handle.step(prompt)` → persist `C_t`; inject query-conditioned `additional_context` (fail-open `{continue: true}`) |
| `afterAgentResponse` | `handle.step(reply, role=assistant)` |
| `preCompact` | Always flush graph; freeze snapshot under state root |
| `sessionStart` | Always flush; inject ≤2k-token `additional_context` (HOT_SET + typed + ranked chunks) |

State root: `~/.cursor/context-graphs/` (or `CHAT_COMPRESSOR_STATE_DIR`).

Env knobs (`~/.cursor/chat-compressor.env`): `K_MAX`, `GRAPH_FLUSH_EVERY` (default 5), `CHAT_COMPRESSOR_FORWARD_BUDGET` (default 1024), `CHAT_COMPRESSOR_INJECT_P1` (default off — P1 decode debug-only).

## Schema pointers (progressive)

- Graph schema: repo `schema/ctx-graph.v1.json` — kinds Turn/Topic/Fact/OpenItem/Event.
- State node: repo `schema/state-node.v1.json` — `state_id`, `parent_id`, `t`, blob path.
- Sampling: `sample_for("cursor-sdk", query=prompt)` packs **HOT_SET → typed lines → ranked chunks** under the forward budget. Pattern-1 vocab string is opt-in via `CHAT_COMPRESSOR_INJECT_P1=1` and Jaccard ≥ 0.15. `C_t` span sidecars are local (`expand_spans`); not sent to Cursor.

## Constraints

- Fail-open: hooks never block Agent Chat.
- No `CURSOR_API_KEY` in the hook path.
- Cloud agents do not load user `~/.cursor/hooks`; copy `ide/project-hooks.template.json` into a project `.cursor/` for cloud parity.
