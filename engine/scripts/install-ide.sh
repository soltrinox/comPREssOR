#!/usr/bin/env bash
# Install CHAT-COMPRESSOR into Cursor IDE hooks (user-global or system-wide).
# Default: --user. Idempotent. Merges hooks.json; never wipes unrelated hooks.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODE="user"
DRY_RUN=0
UNINSTALL_USER=0

USER_CURSOR="${HOME}/.cursor"
USER_VENV="${HOME}/.venvs/chat-compressor"
USER_STATE="${HOME}/.cursor/context-graphs"

SYSTEM_CURSOR="/Library/Application Support/Cursor"
SYSTEM_VENV="/Library/Application Support/CHAT-COMPRESSOR/venv"
SYSTEM_STATE="/Library/Application Support/CHAT-COMPRESSOR/state"

usage() {
  cat <<'EOF'
Usage: scripts/install-ide.sh [--user|--system|--uninstall-user] [--dry-run]

  --user            Install for this OS user (default): venv, hooks, rule, skill
  --system          Machine-wide under /Library/Application Support/Cursor (needs sudo)
  --uninstall-user  Remove compressor hook entries, rule, skill (keep other hooks)
  --dry-run         Print actions without writing
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --user) MODE="user"; shift ;;
    --system) MODE="system"; shift ;;
    --uninstall-user) UNINSTALL_USER=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; usage; exit 2 ;;
  esac
done

run() {
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "[dry-run] $*"
  else
    "$@"
  fi
}

write_file() {
  local dest="$1"
  local content="$2"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "[dry-run] write $dest"
    return 0
  fi
  mkdir -p "$(dirname "$dest")"
  printf '%s' "$content" >"$dest"
}

copy_file() {
  local src="$1"
  local dest="$2"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "[dry-run] cp $src -> $dest"
    return 0
  fi
  mkdir -p "$(dirname "$dest")"
  cp "$src" "$dest"
}

ensure_executable() {
  local path="$1"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "[dry-run] chmod +x $path"
    return 0
  fi
  chmod +x "$path"
}

merge_hooks_json() {
  local hooks_json="$1"
  local command="$2"
  local python_bin="$3"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "[dry-run] merge hooks into $hooks_json command=$command"
    return 0
  fi
  "$python_bin" - "$hooks_json" "$command" <<'PY'
import json
import sys
from pathlib import Path

dest = Path(sys.argv[1])
command = sys.argv[2]
events = (
    "beforeSubmitPrompt",
    "afterAgentResponse",
    "preCompact",
    "sessionStart",
)
entry = {"command": command}

if dest.is_file():
    try:
        data = json.loads(dest.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        data = {}
else:
    data = {}

if not isinstance(data, dict):
    data = {}
data.setdefault("version", 1)
hooks = data.get("hooks")
if not isinstance(hooks, dict):
    hooks = {}
    data["hooks"] = hooks

for event in events:
    lst = hooks.get(event)
    if not isinstance(lst, list):
        lst = []
    # Drop prior compressor entries (same command path or chat-compressor.sh).
    kept = []
    for item in lst:
        if not isinstance(item, dict):
            kept.append(item)
            continue
        cmd = str(item.get("command", ""))
        if "chat-compressor" in cmd:
            continue
        kept.append(item)
    kept.append(dict(entry))
    hooks[event] = kept

dest.parent.mkdir(parents=True, exist_ok=True)
dest.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
print(f"[PASS] merged hooks -> {dest}")
PY
}

uninstall_user_hooks() {
  local hooks_json="$1"
  local python_bin="$2"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "[dry-run] uninstall compressor hooks from $hooks_json"
    return 0
  fi
  if [[ ! -f "$hooks_json" ]]; then
    echo "[PASS] no hooks.json to clean"
    return 0
  fi
  "$python_bin" - "$hooks_json" <<'PY'
import json
import sys
from pathlib import Path

dest = Path(sys.argv[1])
data = json.loads(dest.read_text(encoding="utf-8"))
hooks = data.get("hooks")
if isinstance(hooks, dict):
    for event, lst in list(hooks.items()):
        if not isinstance(lst, list):
            continue
        hooks[event] = [
            item
            for item in lst
            if not (
                isinstance(item, dict)
                and "chat-compressor" in str(item.get("command", ""))
            )
        ]
dest.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
print(f"[PASS] removed compressor hooks from {dest}")
PY
}

install_venv() {
  local venv_dir="$1"
  local python_bin="$2"
  echo "==> Creating venv at $venv_dir"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "[dry-run] python3 -m venv $venv_dir"
    echo "[dry-run] $venv_dir/bin/pip install -e $REPO_ROOT"
    return 0
  fi
  if [[ ! -x "$venv_dir/bin/python" ]]; then
    mkdir -p "$(dirname "$venv_dir")"
    python3 -m venv "$venv_dir"
  fi
  "$venv_dir/bin/pip" install -U pip -q
  "$venv_dir/bin/pip" install -e "$REPO_ROOT" -q
  echo "[PASS] editable install into $venv_dir"
}

print_validation() {
  local cursor_root="$1"
  local state_root="$2"
  cat <<EOF

Install complete.

Paths:
  hooks.json:  ${cursor_root}/hooks.json
  hook script: ${cursor_root}/hooks/chat-compressor.sh
  rule:        ${cursor_root}/rules/chat-compressor.mdc
  skill:       ${cursor_root}/skills/chat-compressor/SKILL.md
  state:       ${state_root}/
  logs:        ${state_root}/logs/

Validate in Cursor:
  1. Open Settings → Hooks (or the Hooks output channel).
  2. Confirm beforeSubmitPrompt / afterAgentResponse / preCompact / sessionStart
     list ./hooks/chat-compressor.sh (user scope).
  3. Open a folder that is NOT CHAT-COMPRESSOR, send one Agent Chat prompt.
  4. Confirm a new StateNode under ${state_root}/<agent_id>/ and a stages line in logs/.

Cloud gap: user ~/.cursor hooks do not load on cloud agents. For cloud parity,
copy ${REPO_ROOT}/ide/project-hooks.template.json into a project .cursor/hooks.json
and ensure the project has hooks/chat-compressor.sh + a reachable venv python.

EOF
}

if [[ "$UNINSTALL_USER" -eq 1 ]]; then
  echo "==> Uninstalling user-global CHAT-COMPRESSOR hooks"
  PY="${USER_VENV}/bin/python"
  if [[ ! -x "$PY" ]]; then
    PY="$(command -v python3)"
  fi
  uninstall_user_hooks "${USER_CURSOR}/hooks.json" "$PY"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "[dry-run] rm -f ${USER_CURSOR}/hooks/chat-compressor.sh"
    echo "[dry-run] rm -f ${USER_CURSOR}/rules/chat-compressor.mdc"
    echo "[dry-run] rm -rf ${USER_CURSOR}/skills/chat-compressor"
  else
    rm -f "${USER_CURSOR}/hooks/chat-compressor.sh"
    rm -f "${USER_CURSOR}/rules/chat-compressor.mdc"
    rm -rf "${USER_CURSOR}/skills/chat-compressor"
  fi
  echo "[PASS] uninstall-user complete (venv and state left intact)"
  exit 0
fi

if [[ "$MODE" == "system" ]]; then
  if [[ "$(id -u)" -ne 0 && "$DRY_RUN" -eq 0 ]]; then
    echo "[FAIL] --system requires root (re-run with sudo)" >&2
    exit 1
  fi
  CURSOR_ROOT="$SYSTEM_CURSOR"
  VENV_DIR="$SYSTEM_VENV"
  STATE_ROOT="$SYSTEM_STATE"
  HOOK_CMD="./hooks/chat-compressor.sh"
else
  CURSOR_ROOT="$USER_CURSOR"
  VENV_DIR="$USER_VENV"
  STATE_ROOT="$USER_STATE"
  HOOK_CMD="./hooks/chat-compressor.sh"
fi

echo "==> Installing CHAT-COMPRESSOR IDE hooks ($MODE)"
echo "    repo:   $REPO_ROOT"
echo "    cursor: $CURSOR_ROOT"
echo "    venv:   $VENV_DIR"
echo "    state:  $STATE_ROOT"

install_venv "$VENV_DIR" "$VENV_DIR/bin/python"

# State + logs
if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "[dry-run] mkdir -p $STATE_ROOT/logs"
else
  mkdir -p "$STATE_ROOT/logs"
fi

# Hook script: rewrite CHAT_COMPRESSOR_PYTHON default for system installs
HOOK_SRC="${REPO_ROOT}/hooks/chat-compressor.sh"
HOOK_DEST="${CURSOR_ROOT}/hooks/chat-compressor.sh"
if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "[dry-run] install hook script -> $HOOK_DEST"
else
  mkdir -p "${CURSOR_ROOT}/hooks"
  if [[ "$MODE" == "system" ]]; then
    sed "s|CHAT_COMPRESSOR_PYTHON:-\\\$HOME/.venvs/chat-compressor/bin/python|CHAT_COMPRESSOR_PYTHON:-${VENV_DIR}/bin/python|" \
      "$HOOK_SRC" >"$HOOK_DEST"
    # Also default state for system
    # shellcheck disable=SC2016
    if ! grep -q 'CHAT-COMPRESSOR system' "$HOOK_DEST"; then
      :
    fi
  else
    cp "$HOOK_SRC" "$HOOK_DEST"
  fi
  chmod +x "$HOOK_DEST"
fi

# Env stub (do not overwrite existing)
ENV_DEST="${CURSOR_ROOT}/chat-compressor.env"
if [[ "$MODE" == "system" ]]; then
  ENV_DEST="/Library/Application Support/CHAT-COMPRESSOR/chat-compressor.env"
fi
if [[ ! -f "$ENV_DEST" ]]; then
  write_file "$ENV_DEST" "# CHAT-COMPRESSOR IDE hooks (no CURSOR_API_KEY here)
CHAT_COMPRESSOR_STATE_DIR=${STATE_ROOT}
K_MAX=32
GRAPH_FLUSH_EVERY=5
# CHAT_COMPRESSOR_INJECT_P1=0
"
else
  echo "[PASS] keep existing env $ENV_DEST"
fi

# For user install, also place env at ~/.cursor/chat-compressor.env if missing
if [[ "$MODE" == "user" && ! -f "${USER_CURSOR}/chat-compressor.env" ]]; then
  write_file "${USER_CURSOR}/chat-compressor.env" "# CHAT-COMPRESSOR IDE hooks (no CURSOR_API_KEY here)
CHAT_COMPRESSOR_STATE_DIR=${STATE_ROOT}
K_MAX=32
GRAPH_FLUSH_EVERY=5
# CHAT_COMPRESSOR_INJECT_P1=0
"
fi

# Merge hooks.json
PY_FOR_MERGE="$VENV_DIR/bin/python"
if [[ "$DRY_RUN" -eq 1 || ! -x "$PY_FOR_MERGE" ]]; then
  PY_FOR_MERGE="$(command -v python3)"
fi
merge_hooks_json "${CURSOR_ROOT}/hooks.json" "$HOOK_CMD" "$PY_FOR_MERGE"

# Rule + skill
copy_file "${REPO_ROOT}/ide/rules/chat-compressor.mdc" "${CURSOR_ROOT}/rules/chat-compressor.mdc"
copy_file "${REPO_ROOT}/ide/skills/chat-compressor/SKILL.md" "${CURSOR_ROOT}/skills/chat-compressor/SKILL.md"

print_validation "$CURSOR_ROOT" "$STATE_ROOT"
echo "[PASS] install-ide.sh ($MODE) complete"
