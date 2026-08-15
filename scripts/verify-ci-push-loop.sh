#!/usr/bin/env bash
# verify-ci-push-loop.sh — bounded local-build → push → GitHub CI watch loop.
#
# Automates: preflight, local CI-mirror build, push (no force), watch workflow,
# capture failed logs, apply ONLY documented known fixes (optional), retry ≤5.
#
# Does NOT invent arbitrary CI fixes. Unknown failures exit non-zero with logs
# for a human/agent; re-run after the fix is committed.
#
# Discoverable name: verify-*.sh (workspace script menu / pattern discovery).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

MAX_ITERATIONS=5
ALLOW_DIRTY=0
AUTO_COMMIT_FIXES=0
DRY_RUN=0
AGENT_HINT=0
SKIP_LOCAL=0
SKIP_ENGINE=0
SKIP_PUSH=0
REQUIRE_BRANCH="main"
WORKFLOW_NAME="CI"
LOG_DIR="${LOG_DIR:-${REPO_ROOT}/test-results/ci-loop}"
TS="$(date -u +%Y%m%d-%H%M%S)"
RUN_LOG="${LOG_DIR}/verify-ci-push-loop-${TS}.log.txt"
FAILED_LOG_PATH=""
LAST_SHA=""
LAST_RUN_ID=""
LAST_RUN_URL=""
LAST_CONCLUSION=""

usage() {
  cat <<'EOF'
Usage: scripts/verify-ci-push-loop.sh [options]

Bounded loop (max 5): local CI-mirror build → git push origin HEAD → gh run watch
→ on failure capture logs → optional known-pattern auto-fix → retry or fail closed.

Options:
  --help                 Show this help
  --dry-run              Print planned steps; skip push/watch/commit
  --allow-dirty          Allow uncommitted local changes (still will not auto-commit
                         unless --auto-commit-fixes applies a known fix)
  --branch NAME          Required branch (default: main)
  --workflow NAME        Workflow name to watch (default: CI)
  --max-iterations N     Cap retries (default 5, hard max 5)
  --skip-local-build     Skip local mirror of CI steps (push/watch only)
  --skip-engine          Skip local engine pytest (extension steps still run)
  --skip-push            Local build + classify only; do not push
  --auto-commit-fixes    If a known fixable CI pattern matches, apply fix in-repo,
                         commit (safe paths only), and re-push. Default: off.
  --agent-hint           On unknown failure, print a ready Cursor/agent fix prompt

Environment:
  LOG_DIR overrides default test-results/ci-loop/

Exit codes:
  0  CI green for pushed SHA (or dry-run preflight+local build OK)
  1  Failure / unknown CI error / dirty tree / auth / iteration exhausted

What this WILL auto-fix (only with --auto-commit-fixes):
  - vsce --packagePath (removed in @vscode/vsce 3.x) → rewrite to vsce package --no-dependencies
    and/or CI assert via unzip -l (see .github/workflows/ci.yml)

What this will NOT auto-fix:
  - scrub-check / gitleaks / pytest / typecheck / arbitrary test failures
  - Anything requiring secrets, force-push, or hook skip
EOF
}

log() {
  # shellcheck disable=SC2034
  local line="$*"
  printf '%s\n' "$line" | tee -a "$RUN_LOG"
}

pass() { log "[PASS] $*"; }
fail() { log "[FAIL] $*"; }

die() {
  fail "$*"
  exit 1
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --help|-h) usage; exit 0 ;;
      --dry-run) DRY_RUN=1; shift ;;
      --allow-dirty) ALLOW_DIRTY=1; shift ;;
      --branch)
        REQUIRE_BRANCH="${2:?--branch requires NAME}"
        shift 2
        ;;
      --workflow)
        WORKFLOW_NAME="${2:?--workflow requires NAME}"
        shift 2
        ;;
      --max-iterations)
        MAX_ITERATIONS="${2:?--max-iterations requires N}"
        shift 2
        ;;
      --skip-local-build) SKIP_LOCAL=1; shift ;;
      --skip-engine) SKIP_ENGINE=1; shift ;;
      --skip-push) SKIP_PUSH=1; shift ;;
      --auto-commit-fixes) AUTO_COMMIT_FIXES=1; shift ;;
      --agent-hint) AGENT_HINT=1; shift ;;
      *)
        die "Unknown option: $1 (try --help)"
        ;;
    esac
  done
  if [[ "$MAX_ITERATIONS" =~ ^[0-9]+$ ]] && (( MAX_ITERATIONS > 0 )); then
    if (( MAX_ITERATIONS > 5 )); then
      MAX_ITERATIONS=5
      log "[INFO] --max-iterations capped at 5 (focused-fix bound)"
    fi
  else
    die "--max-iterations must be a positive integer"
  fi
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Required command not found: $1"
}

is_secretish_path() {
  local p="$1"
  case "$p" in
    *.env|*/.env|*.env.local|*/credentials.json|*/secrets/*|*/.npmrc)
      return 0
      ;;
  esac
  return 1
}

preflight() {
  mkdir -p "$LOG_DIR"
  : >"$RUN_LOG"
  log "=== verify-ci-push-loop ==="
  log "ts_utc=${TS} repo=${REPO_ROOT} max_iterations=${MAX_ITERATIONS}"
  log "dry_run=${DRY_RUN} allow_dirty=${ALLOW_DIRTY} auto_commit_fixes=${AUTO_COMMIT_FIXES}"

  require_cmd git
  require_cmd gh
  require_cmd node
  require_cmd npm

  if ! gh auth status >/dev/null 2>&1; then
    die "gh is not authenticated. Run: gh auth login"
  fi
  pass "gh auth OK"

  local branch
  branch="$(git rev-parse --abbrev-ref HEAD)"
  if [[ "$branch" != "$REQUIRE_BRANCH" ]]; then
    die "On branch '${branch}', required '${REQUIRE_BRANCH}' (pass --branch ${branch} to override)"
  fi
  pass "branch=${branch}"

  if [[ -n "$(git status --porcelain)" ]]; then
    if (( ALLOW_DIRTY == 0 )) && (( AUTO_COMMIT_FIXES == 0 )); then
      fail "Working tree is dirty. Commit intentional changes first, or pass --allow-dirty,"
      fail "or --auto-commit-fixes (only applies documented known patterns)."
      git status --porcelain | tee -a "$RUN_LOG"
      exit 1
    fi
    log "[WARN] dirty working tree allowed (allow_dirty=${ALLOW_DIRTY} auto_commit_fixes=${AUTO_COMMIT_FIXES})"
  else
    pass "working tree clean"
  fi

  if (( DRY_RUN == 1 )); then
    log "[INFO] dry-run: will not push, watch, or commit"
  fi
}

local_extension_build() {
  log "--- local extension (mirrors .github/workflows/ci.yml job: extension) ---"
  pushd "${REPO_ROOT}/extension" >/dev/null
  node build/scrub-check.mjs
  npm ci
  npm run compile
  npm test
  npm run package
  # Mirror CI VSIX content assert (@vscode/vsce 3.x: no --packagePath)
  vsix="$(ls -1 *.vsix | head -1)"
  [[ -n "$vsix" ]] || { popd >/dev/null || true; die "No .vsix produced by npm run package"; }
  listing="$(mktemp)"
  unzip -l "$vsix" >"$listing"
  if grep -E 'test-results/|runs/|/state/|fixtures/imported/|\.env$|WHITEOB.*\.pdf' "$listing"; then
    rm -f "$listing"
    popd >/dev/null || true
    die "VSIX contains scrub-forbidden paths"
  fi
  rm -f "$listing"
  pass "vsix content scrub (${vsix})"
  popd >/dev/null
  pass "local extension build"
}

local_engine_build() {
  if (( SKIP_ENGINE == 1 )); then
    log "[INFO] skipping engine pytest (--skip-engine)"
    return 0
  fi
  require_cmd python3
  log "--- local engine (mirrors ci.yml job: engine; single local Python) ---"
  pushd "${REPO_ROOT}/engine" >/dev/null
  python3 -m pip install -U pip
  python3 -m pip install -e ".[dev]"
  python3 -m pytest tests
  popd >/dev/null
  pass "local engine pytest"
}

local_build() {
  if (( SKIP_LOCAL == 1 )); then
    log "[INFO] skipping local build (--skip-local-build)"
    return 0
  fi
  local_extension_build
  local_engine_build
}

push_head() {
  if (( SKIP_PUSH == 1 )); then
    log "[INFO] skipping push (--skip-push)"
    return 0
  fi
  if (( DRY_RUN == 1 )); then
    log "[INFO] dry-run: would run: git push origin HEAD"
    return 0
  fi
  local sha
  sha="$(git rev-parse HEAD)"
  log "Pushing SHA=${sha} to origin (no force)..."
  git push origin HEAD
  pass "pushed SHA=${sha}"
}

# Wait for a workflow run for HEAD SHA; print conclusion.
# Sets globals: LAST_RUN_ID LAST_RUN_URL LAST_CONCLUSION LAST_SHA
watch_ci() {
  LAST_SHA="$(git rev-parse HEAD)"
  LAST_RUN_ID=""
  LAST_RUN_URL=""
  LAST_CONCLUSION=""

  if (( SKIP_PUSH == 1 )) || (( DRY_RUN == 1 )); then
    log "[INFO] dry-run/skip-push: not watching GitHub Actions"
    LAST_CONCLUSION="skipped"
    return 0
  fi

  log "Waiting for workflow '${WORKFLOW_NAME}' on SHA=${LAST_SHA}..."
  local attempts=0
  local run_json=""
  while (( attempts < 30 )); do
    run_json="$(
      gh run list --workflow "$WORKFLOW_NAME" --limit 20 \
        --json databaseId,headSha,status,conclusion,url,displayTitle,createdAt \
        --jq "[.[] | select(.headSha == \"${LAST_SHA}\")][0] // empty"
    )"
    if [[ -n "$run_json" && "$run_json" != "null" ]]; then
      break
    fi
    attempts=$((attempts + 1))
    sleep 4
  done

  if [[ -z "$run_json" || "$run_json" == "null" ]]; then
    die "No '${WORKFLOW_NAME}' run found for SHA=${LAST_SHA} after waiting"
  fi

  LAST_RUN_ID="$(printf '%s' "$run_json" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["databaseId"])')"
  LAST_RUN_URL="$(printf '%s' "$run_json" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["url"])')"
  log "Found run id=${LAST_RUN_ID} url=${LAST_RUN_URL}"

  gh run watch "$LAST_RUN_ID" --exit-status && LAST_CONCLUSION="success" || {
    local st
    st="$(gh run view "$LAST_RUN_ID" --json conclusion,status --jq '.conclusion // .status')"
    LAST_CONCLUSION="$st"
    return 1
  }
  return 0
}

capture_failed_logs() {
  FAILED_LOG_PATH="${LOG_DIR}/ci-failed-${LAST_SHA:-unknown}-${TS}.log.txt"
  log "Capturing failed logs → ${FAILED_LOG_PATH}"
  {
    echo "=== gh run view ${LAST_RUN_ID} ==="
    gh run view "$LAST_RUN_ID" || true
    echo
    echo "=== gh run view --log-failed ==="
    gh run view "$LAST_RUN_ID" --log-failed || true
  } >"$FAILED_LOG_PATH" 2>&1 || true
  fail "CI conclusion=${LAST_CONCLUSION} run=${LAST_RUN_URL}"
  log "Failed log path: ${FAILED_LOG_PATH}"
}

# Classify failure log. Prints: KNOWN:<id> or UNKNOWN
# Known patterns are documented only — see table in --help.
classify_failure() {
  local log_path="$1"
  if grep -E -- '--packagePath' "$log_path" >/dev/null 2>&1; then
    echo "KNOWN:packagePath"
    return 0
  fi
  if grep -Eiq 'unknown option.*package[-]?path|packagePath.*not.*valid|error: unknown option' "$log_path" >/dev/null 2>&1; then
    # Some runners phrase vsce flag errors without the flag string surviving; keep narrow.
    if grep -Eiq 'vsce|@vscode/vsce' "$log_path"; then
      echo "KNOWN:packagePath"
      return 0
    fi
  fi
  echo "UNKNOWN"
}

print_known_fix_table() {
  log "Known pattern → hint (auto-fix only with --auto-commit-fixes):"
  log "  packagePath | @vscode/vsce 3.x dropped --packagePath; use 'vsce package --no-dependencies' and unzip -l asserts"
  log "  (scrub|gitleaks|pytest|compile) | NOT auto-fixed — agent/human must edit, then re-run this script"
}

apply_known_fix() {
  local kind="$1"
  case "$kind" in
    KNOWN:packagePath)
      log "Applying known fix: remove --packagePath usages"
      # package.json scripts
      if grep -R --line-number --fixed-strings -- '--packagePath' \
        extension/package.json .github/workflows >/dev/null 2>&1; then
        # Replace common script form with vsce 3.x-safe packaging.
        if grep -q -- '--packagePath' extension/package.json 2>/dev/null; then
          # Prefer rewriting package script to the known-good form used in-repo.
          python3 - <<'PY'
from pathlib import Path
p = Path("extension/package.json")
text = p.read_text()
old = text
# Strip --packagePath and any following arg token if present as separate words.
import re
text = re.sub(r"\s*--packagePath(\s+\S+)?", "", text)
if text != old:
    p.write_text(text)
    print("[PASS] stripped --packagePath from extension/package.json")
else:
    print("[INFO] no --packagePath left in extension/package.json")
PY
        fi
        if grep -q -- '--packagePath' .github/workflows/ci.yml 2>/dev/null; then
          log "[INFO] ci.yml still mentions --packagePath in comments or steps — review manually if steps fail"
        fi
      else
        log "[INFO] no --packagePath occurrences found to rewrite; check CI assert uses unzip -l"
      fi
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

safe_commit_fixes() {
  if (( DRY_RUN == 1 )); then
    log "[INFO] dry-run: would stage and commit known-fix files"
    return 0
  fi
  local -a candidates=()
  local f
  while IFS= read -r f; do
    [[ -z "$f" ]] && continue
    if is_secretish_path "$f"; then
      die "Refusing to commit secretish path: $f"
    fi
    case "$f" in
      extension/package.json|.github/workflows/*|docs/*|CONTRIBUTING.md|scripts/*)
        candidates+=("$f")
        ;;
      *)
        log "[WARN] skipping unexpected path from known-fix (not auto-committed): $f"
        ;;
    esac
  done < <(git status --porcelain | awk '{print $2}')

  if ((${#candidates[@]} == 0)); then
    die "Known pattern matched but no safe files to commit"
  fi

  git add -- "${candidates[@]}"
  # Do not skip hooks; do not amend; HEREDOC message.
  git commit -m "$(cat <<'EOF'
fix(ci): apply known vsce packagePath remediation

Recursive SDLC: verify-ci-push-loop known-pattern auto-fix.
EOF
)"
  pass "committed known-fix files: ${candidates[*]}"
}

print_agent_hint() {
  local log_path="$1"
  cat <<EOF

--- agent-hint (paste into Cursor) ---
CI failed for SHA=${LAST_SHA}.
Run URL: ${LAST_RUN_URL}
Failed log: ${log_path}
Master log: ${RUN_LOG}

Task: read the failed log, fix the root cause in-repo (do not force-push, do not skip hooks,
do not commit secrets). Then re-run:

  ./scripts/verify-ci-push-loop.sh

Known auto-fixable patterns are limited (see script --help). Do not pretend bash can LLM-fix this.
--- end agent-hint ---
EOF
}

success_summary() {
  pass "CI green"
  log "SHA=${LAST_SHA}"
  log "URL=${LAST_RUN_URL}"
  log "Master log: ${RUN_LOG}"
}

main_loop() {
  local iteration=1
  local failed_log classification

  while (( iteration <= MAX_ITERATIONS )); do
    log "=== iteration ${iteration}/${MAX_ITERATIONS} ==="

    local_build

    if (( SKIP_PUSH == 1 )); then
      pass "local build complete (--skip-push); not pushing"
      print_known_fix_table
      return 0
    fi

    if (( DRY_RUN == 1 )); then
      push_head
      pass "dry-run complete (no remote CI watch)"
      print_known_fix_table
      return 0
    fi

    # If dirty without auto-commit, refuse to push (safer default).
    if [[ -n "$(git status --porcelain)" ]] && (( AUTO_COMMIT_FIXES == 0 )); then
      if (( ALLOW_DIRTY == 1 )); then
        log "[WARN] pushing with dirty tree (--allow-dirty); uncommitted fixes will NOT be on remote"
      else
        die "Dirty tree before push. Commit first, or use --allow-dirty / --auto-commit-fixes"
      fi
    fi

    push_head

    if watch_ci; then
      success_summary
      return 0
    fi

    capture_failed_logs
    failed_log="$FAILED_LOG_PATH"
    classification="$(classify_failure "$failed_log")"
    log "Classification: ${classification}"
    print_known_fix_table

    if [[ "$classification" == KNOWN:* ]]; then
      if (( AUTO_COMMIT_FIXES == 1 )); then
        apply_known_fix "$classification"
        safe_commit_fixes
        iteration=$((iteration + 1))
        continue
      else
        fail "Known fixable pattern '${classification}' detected, but --auto-commit-fixes not set."
        fail "Apply the hint, commit, then re-run. Log: ${failed_log}"
        if (( AGENT_HINT == 1 )); then
          print_agent_hint "$failed_log"
        fi
        exit 1
      fi
    fi

    fail "Unknown CI failure — fail closed (no arbitrary bash auto-fix)."
    fail "Log: ${failed_log}"
    if (( AGENT_HINT == 1 )); then
      print_agent_hint "$failed_log"
    fi
    exit 1
  done

  die "Exhausted max iterations (${MAX_ITERATIONS}) without green CI"
}

parse_args "$@"
preflight
main_loop
