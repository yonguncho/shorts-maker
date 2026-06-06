#!/usr/bin/env bash
# cto_mac_node.sh — CTO_mac 노드 지휘관 (독립 루프)
# 책임: ① 상태보고(node_status.json heartbeat)  ② 명령수신(격리 함수)  ③ 30초 폴링
# 설계 원칙(CTO_win 동일): 명령수신 로직을 별도 함수로 격리.
#   - 지금: 로컬 파일(state/cto_mac_cmd.json) 폴링
#   - 추후: _fetch_commands / _ack_command 두 함수만 교체하면 중앙 명령버스로 전환
# launchd LaunchAgent 로 RunAtLoad+KeepAlive 등록 예정(STEP 3).

set -o pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

LOG_NAME="cto_mac_node"
NODE_STATUS="$STATE_DIR/node_status.json"
CMD_FILE="$STATE_DIR/cto_mac_cmd.json"
POLL_INTERVAL="${CTO_POLL_INTERVAL:-30}"
RUNNING=1

load_env

# ══════════════════════════════════════════════════════
# ① 상태 보고
# ══════════════════════════════════════════════════════
report_status() {
  local status="${1:-online}"
  json_set "$NODE_STATUS" '
    .status = $st
    | .heartbeat_utc = $now
    | .processes.cto_mac_node = "running"
    | .watchdog.alive = (.watchdog.alive // false)
  ' --arg st "$status" --arg now "$(utc_now)" \
    || log ERROR "report_status 실패"
}

mark_started() {
  json_set "$NODE_STATUS" '.started_utc = (.started_utc // $now) | .status="starting"' \
    --arg now "$(utc_now)" || true
}

# ══════════════════════════════════════════════════════
# ② 명령 수신 — 격리 계층
#    transport(어디서 명령을 읽고/응답하나)와 dispatch(무엇을 하나)를 분리.
#    중앙버스 전환 시 _fetch_commands / _ack_command 만 교체.
# ══════════════════════════════════════════════════════

# --- transport: 대기 중 명령 id 목록을 줄단위로 반환 (target=mac & status=pending) ---
_fetch_commands() {
  [ -f "$CMD_FILE" ] || return 0
  command -v jq >/dev/null 2>&1 || return 0
  jq -r '.commands[]? | select(.target_node=="mac" and .status=="pending") | .id' "$CMD_FILE" 2>/dev/null
}

# --- transport: 명령 1건의 필드 추출 ---
_get_cmd_field() {
  local id="$1" field="$2"
  jq -r --arg id "$id" --arg f "$field" \
    '.commands[]? | select(.id==$id) | .[$f] // empty' "$CMD_FILE" 2>/dev/null
}

# --- transport: 명령 처리 결과 기록(ack) ---
_ack_command() {
  local id="$1" status="$2" result="$3"
  json_set "$CMD_FILE" '
    .commands |= map(
      if .id==$id then .status=$st | .ack_utc=$now | .result=$res else . end
    )' --arg id "$id" --arg st "$status" --arg res "$result" --arg now "$(utc_now)" \
    || log ERROR "_ack_command 실패 ($id)"
}

# --- dispatch: 명령 종류별 처리 (지금은 골격/스텁) ---
handle_command() {
  local id="$1"
  local type; type="$(_get_cmd_field "$id" type)"
  log INFO "명령 처리: id=$id type=$type"
  case "$type" in
    ping)
      _ack_command "$id" done "pong"
      ;;
    status)
      report_status online
      _ack_command "$id" done "status reported"
      ;;
    stop)
      _ack_command "$id" done "stopping node"
      RUNNING=0
      ;;
    pause|resume|restart_harness)
      # TODO: 설계 단계에서 구현 (harness 제어)
      _ack_command "$id" done "TODO: $type 미구현(골격)"
      ;;
    *)
      log WARN "알 수 없는 명령 type=$type (id=$id)"
      _ack_command "$id" error "unknown command type: $type"
      ;;
  esac
}

# --- 명령 수신 루프 1회분 (격리된 진입점) ---
receive_commands() {
  local ids; ids="$(_fetch_commands)"
  [ -z "$ids" ] && return 0
  while IFS= read -r id; do
    [ -z "$id" ] && continue
    handle_command "$id"
  done <<< "$ids"
}

# ══════════════════════════════════════════════════════
# 종료 처리
# ══════════════════════════════════════════════════════
on_exit() {
  log INFO "CTO_mac 노드 종료 중..."
  json_set "$NODE_STATUS" '.status="offline" | .processes.cto_mac_node="stopped" | .heartbeat_utc=$now' \
    --arg now "$(utc_now)" 2>/dev/null || true
  release_singleton
  log INFO "종료 완료."
}
trap 'RUNNING=0' SIGTERM SIGINT
trap on_exit EXIT

# ══════════════════════════════════════════════════════
# 메인 루프
# ══════════════════════════════════════════════════════
main() {
  acquire_singleton "cto_mac_node" || exit 0
  log INFO "CTO_mac 노드 기동 (poll=${POLL_INTERVAL}s, pid=$$)"
  mark_started
  report_status online

  while [ "$RUNNING" -eq 1 ]; do
    report_status online
    receive_commands
    # 종료 명령(stop)이 RUNNING=0 으로 만들면 즉시 탈출
    [ "$RUNNING" -eq 1 ] || break
    sleep "$POLL_INTERVAL"
  done
}

main "$@"
