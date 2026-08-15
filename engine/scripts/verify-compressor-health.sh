#!/bin/bash
set -euo pipefail

# Non-zero if today's hook-errors.log.txt has entries, or any stage line has ingest_ok=0.
STATE_ROOT="${CHAT_COMPRESSOR_STATE_DIR:-$HOME/.cursor/context-graphs}"
TODAY_UTC="$(date -u +%Y%m%d)"
TODAY_ISO="$(date -u +%Y-%m-%d)"
ERR_LOG="${STATE_ROOT}/logs/hook-errors.log.txt"
STAGES_LOG="${STATE_ROOT}/logs/stages-${TODAY_UTC}.log.txt"
FAIL=0

if [[ -f "$ERR_LOG" ]] && grep -E "^${TODAY_ISO}" "$ERR_LOG" >/dev/null 2>&1; then
  echo "[FAIL] today's hook-errors.log.txt is non-empty path=${ERR_LOG} date=${TODAY_ISO}"
  FAIL=1
else
  echo "[PASS] no hook-error lines for ${TODAY_ISO}"
fi

if [[ -f "$STAGES_LOG" ]] && grep -E '(^|[[:space:]])ingest_ok=0([[:space:]]|$)' "$STAGES_LOG" >/dev/null 2>&1; then
  echo "[FAIL] stage line has ingest_ok=0 path=${STAGES_LOG}"
  FAIL=1
else
  echo "[PASS] no ingest_ok=0 in ${STAGES_LOG}"
fi

exit "${FAIL}"
