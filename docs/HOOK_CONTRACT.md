# Hook contract

## Events

| Event | Hook JSON default on failure | Side effect |
|-------|------------------------------|-------------|
| `beforeSubmitPrompt` | `{"continue":true}` | `handle.step(prompt)`; may inject `additional_context` |
| `afterAgentResponse` | `{}` | `handle.step(reply, role=assistant)` |
| `preCompact` | `{}` | Always flush graph; freeze snapshot |
| `sessionStart` | `{"additional_context":""}` | Always flush; inject packed forward context |

## Shim

- Path: `~/.cursor/hooks/chat-compressor.sh`
- Registered command: `./hooks/chat-compressor.sh` (relative to `~/.cursor/`)
- Fail-open: missing venv or CLI errors must not block Agent Chat

## Env file

`~/.cursor/chat-compressor.env` managed keys:

- `CHAT_COMPRESSOR_PYTHON`
- `CHAT_COMPRESSOR_STATE_DIR`
- `K_MAX`
- `GRAPH_FLUSH_EVERY`
- `CHAT_COMPRESSOR_FORWARD_BUDGET`
- `CHAT_COMPRESSOR_INJECT_P1`
- `CHAT_COMPRESSOR_ADVISORY_PATH` (optional CC-9 advisory JSON; default `advisory/latest.json` under state root)

Unmanaged lines are preserved. `CURSOR_API_KEY` is never written.

## Merge policy

When editing `hooks.json`, drop only entries whose `command` contains `chat-compressor`; keep all other hooks. Write via temp-file + rename; create a timestamped `.bak` on first modification of a session.

## CC-9 advisory (fail-open)

Optional file-based handoff from an external router (comPASS). When present and **fresh**, `_compose_additional_context` appends a single `COMPASS_ADVISORY:` line to `additional_context`.

- Default path: `$CHAT_COMPRESSOR_STATE_DIR/advisory/latest.json` (override with `CHAT_COMPRESSOR_ADVISORY_PATH`)
- Schema: `compass-advisory/v1` (see comPASS `docs/API.md`)
- Include iff JSON parses, required fields are present, and `expires_at` is in the future
- **Missing, stale, or corrupt advisory MUST NOT block Agent Chat** — hook still returns the event-safe default (`continue: true` / empty context)
- Hook process never loads provider keys to read the advisory file

## Hop legality (CC-7)

`PersistentAgentHandle.hop_legal()` must be consulted before changing
`recipient_id` mid-session. Returns false with pending tool state. Details:
[`HOP_LEGAL.md`](./HOP_LEGAL.md).

## Tensor quantization (CC-10)

Optional env `CHAT_COMPRESSOR_TENSOR_QUANT` (`float32` default, or `float16` /
`int8`). Scheme is recorded on `StateNode.meta.quantization`. Default path is
unchanged float32 mmap behavior.
