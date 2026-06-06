#!/usr/bin/env bash
# common.sh — shorts_maker 공통 라이브러리 (경로/PATH/로그/JSON/락)
# 모든 하네스 스크립트가 맨 위에서 source 한다.
#   SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; source "$SCRIPT_DIR/lib/common.sh"
# macOS(Intel) 기준. flock 미존재 → PID 기반 단일인스턴스 락 사용.

set -o pipefail

# ── 경로 ──────────────────────────────────────────────
# common.sh 는 harness/lib/ 에 있으므로 ROOT = ../../
LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$LIB_DIR/../.." && pwd)"
HARNESS_DIR="$ROOT_DIR/harness"
STATE_DIR="$ROOT_DIR/state"
RUN_DIR="$ROOT_DIR/run"
LOG_DIR="$ROOT_DIR/logs"
AGENTS_DIR="$ROOT_DIR/agents"
OUTPUT_DIR="$ROOT_DIR/output"
SHARED_DIR="$ROOT_DIR/shared"
export ROOT_DIR HARNESS_DIR STATE_DIR RUN_DIR LOG_DIR AGENTS_DIR OUTPUT_DIR SHARED_DIR

mkdir -p "$STATE_DIR" "$RUN_DIR" "$LOG_DIR" "$OUTPUT_DIR" "$SHARED_DIR"

# ── PATH (launchd 환경은 PATH가 빈약 → 명시 주입) ──────
# Intel Homebrew=/usr/local, Apple Silicon=/opt/homebrew, claude=~/.local/bin
export PATH="/usr/local/bin:/opt/homebrew/bin:$HOME/.local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

# ── .env 로더 (시크릿은 .env 에만) ────────────────────
load_env() {
  local envf="$ROOT_DIR/.env"
  [ -f "$envf" ] || return 0
  # 줄 단위 read 로 export (process substitution `source <(...)` 는 macOS/bash3.2 에서
  # 변수를 못 만드는 경우가 있어 사용하지 않음). 주석/빈줄 무시, 앞뒤 공백 허용.
  local line key val
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      ''|'#'*) continue ;;
    esac
    [ "${line#*=}" = "$line" ] && continue   # '=' 없는 줄 무시
    key="${line%%=*}"
    val="${line#*=}"
    # 키 앞뒤 공백 제거
    key="$(printf '%s' "$key" | tr -d '[:space:]')"
    [ -z "$key" ] && continue
    export "$key=$val"
  done < "$envf"
}

# ── 시각 (전부 UTC ISO8601) ──────────────────────────
utc_now() { date -u +%Y-%m-%dT%H:%M:%SZ; }

# ── 로그 ──────────────────────────────────────────────
# 사용: log INFO "메시지"   (LOG_NAME 환경변수로 로그파일명 결정, 없으면 common)
log() {
  local level="$1"; shift
  local name="${LOG_NAME:-common}"
  local line="[$(utc_now)] [$level] [$name] $*"
  echo "$line"
  echo "$line" >> "$LOG_DIR/$name.log"
}

# ── JSON 원자적 쓰기 (temp→mv, 대시보드가 반쪽 파일 읽는 것 방지) ──
# 사용: json_atomic_write "$STATE_DIR/node_status.json" '<json문자열>'
json_atomic_write() {
  local target="$1"; local content="$2"
  local tmp; tmp="$(mktemp "${target}.XXXXXX")"
  if command -v jq >/dev/null 2>&1; then
    if printf '%s' "$content" | jq . > "$tmp" 2>/dev/null; then
      mv -f "$tmp" "$target"; return 0
    else
      rm -f "$tmp"; log ERROR "json_atomic_write: invalid JSON for $target"; return 1
    fi
  else
    printf '%s' "$content" > "$tmp" && mv -f "$tmp" "$target"
  fi
}

# JSON 일부 갱신 (jq 필요). 사용: json_set file '.heartbeat_utc=$v' --arg v "$(utc_now)"
json_set() {
  local file="$1"; shift
  local filter="$1"; shift
  command -v jq >/dev/null 2>&1 || { log ERROR "json_set: jq 필요"; return 1; }
  [ -f "$file" ] || { log ERROR "json_set: 파일 없음 $file"; return 1; }
  local tmp; tmp="$(mktemp "${file}.XXXXXX")"
  if jq "$@" "$filter" "$file" > "$tmp" 2>/dev/null; then
    mv -f "$tmp" "$file"
  else
    rm -f "$tmp"; log ERROR "json_set 실패: $file ($filter)"; return 1
  fi
}

# ── 단일 인스턴스 락 (PID 파일 기반, flock 대체) ──────
# 사용: acquire_singleton "cto_mac_node" || exit 0
acquire_singleton() {
  local name="$1"
  local pidfile="$RUN_DIR/$name.pid"
  if [ -f "$pidfile" ]; then
    local old; old="$(cat "$pidfile" 2>/dev/null)"
    if [ -n "$old" ] && kill -0 "$old" 2>/dev/null; then
      log WARN "이미 실행 중 ($name pid=$old) — 종료"
      return 1
    fi
    log INFO "오래된 pidfile 회수 ($name, 죽은 pid=$old)"
  fi
  echo "$$" > "$pidfile"
  _SINGLETON_PIDFILE="$pidfile"
  return 0
}

release_singleton() {
  [ -n "${_SINGLETON_PIDFILE:-}" ] && rm -f "$_SINGLETON_PIDFILE"
}

# 프로세스 생존 확인 (watchdog/대시보드용). 사용: is_alive cto_mac_node
is_alive() {
  local name="$1"; local pidfile="$RUN_DIR/$name.pid"
  [ -f "$pidfile" ] || return 1
  local p; p="$(cat "$pidfile" 2>/dev/null)"
  [ -n "$p" ] && kill -0 "$p" 2>/dev/null
}
