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

Unmanaged lines are preserved. `CURSOR_API_KEY` is never written.

## Merge policy

When editing `hooks.json`, drop only entries whose `command` contains `chat-compressor`; keep all other hooks. Write via temp-file + rename; create a timestamped `.bak` on first modification of a session.
