#!/usr/bin/env bash
# Thin Cursor hook wrapper for CHAT-COMPRESSOR.
# Reads stdin JSON, invokes the dedicated venv Python module, fail-open.
set -u

# Load IDE env before resolving python (fail-open if missing/unreadable).
# Do not `source`: values may contain unquoted spaces (e.g. Application Support).
ENV_FILE="${CHAT_COMPRESSOR_ENV_FILE:-$HOME/.cursor/chat-compressor.env}"
if [[ -f "$ENV_FILE" ]]; then
  while IFS= read -r line || [[ -n "$line" ]]; do
    case "$line" in
      ''|\#*) continue ;;
      *=*)
        key="${line%%=*}"
        val="${line#*=}"
        key="${key#"${key%%[![:space:]]*}"}"
        key="${key%"${key##*[![:space:]]}"}"
        [[ -z "$key" || "$key" == *[!A-Za-z0-9_]* ]] && continue
        if [[ ${#val} -ge 2 ]]; then
          first="${val:0:1}"
          last="${val: -1}"
          if [[ ( "$first" == '"' && "$last" == '"' ) || ( "$first" == "'" && "$last" == "'" ) ]]; then
            val="${val:1:${#val}-2}"
          fi
        fi
        # Shell-provided non-empty values win (match Python load_env_file).
        if [[ -z "${!key:-}" ]]; then
          export "${key}=${val}"
        fi
        ;;
    esac
  done <"$ENV_FILE" 2>/dev/null || true
fi

EVENT="${HOOK_EVENT:-}"
VENV_PYTHON="${CHAT_COMPRESSOR_PYTHON:-$HOME/.venvs/chat-compressor/bin/python}"
STATE_ROOT="${CHAT_COMPRESSOR_STATE_DIR:-$HOME/.cursor/context-graphs}"
ERR_LOG="${STATE_ROOT}/logs/hook-errors.log.txt"

mkdir -p "${STATE_ROOT}/logs" 2>/dev/null || true

fail_open() {
  local event="${1:-beforeSubmitPrompt}"
  case "$event" in
    beforeSubmitPrompt) printf '%s' '{"continue":true}' ;;
    sessionStart) printf '%s' '{"additional_context":""}' ;;
    *) printf '%s' '{}' ;;
  esac
}

INPUT="$(cat || true)"

# Prefer event from env (per-event wrapper) else from stdin JSON.
if [[ -z "$EVENT" ]]; then
  EVENT="$(printf '%s' "$INPUT" | "$VENV_PYTHON" -c '
import json,sys
try:
    d=json.load(sys.stdin)
except Exception:
    d={}
print((d.get("hook_event_name") or d.get("hookEventName") or d.get("event") or "beforeSubmitPrompt") if isinstance(d, dict) else "beforeSubmitPrompt")
' 2>/dev/null || echo beforeSubmitPrompt)"
fi

if [[ ! -x "$VENV_PYTHON" ]]; then
  printf '%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ) missing venv python: $VENV_PYTHON" >>"$ERR_LOG" 2>/dev/null || true
  fail_open "$EVENT"
  exit 0
fi

if ! printf '%s' "$INPUT" | "$VENV_PYTHON" -m chat_compressor.hook_cli --event "$EVENT"; then
  printf '%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ) hook_cli failed event=$EVENT" >>"$ERR_LOG" 2>/dev/null || true
  fail_open "$EVENT"
fi
exit 0
