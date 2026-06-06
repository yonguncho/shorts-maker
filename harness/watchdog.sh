#!/usr/bin/env bash
# watchdog.sh — 영속 서비스 생존 감시 + 자동 재시작 + 에이전트 hang 감지
# launchd KeepAlive 와 이중 안전망. launchd 가 프로세스 부재를 못 잡는 경우(행/좀비)까지 커버.
#
# 감시 대상 ①: 영속 루프 서비스(SERVICES) — 미실행 시 재시작
# 감시 대상 ②: remote-control 에이전트 hang — 세션 파일 waitingFor 비어있지 않으면 TERM
#   hang 정의: status=waiting AND waitingFor != "" AND HANG_TIMEOUT 초 이상 경과
#   launchd KeepAlive 에이전트는 TERM 후 자동 재기동. 비등록(Jarvis) 은 로그만 남김.
#   busy 에이전트(실제 작업 중)는 건드리지 않음.
#
# 환경변수 재정의:
#   WATCHDOG_INTERVAL  — 서비스 체크 주기(초, 기본 15)
#   AGENT_HANG_TIMEOUT — hang 판정 대기 시간(초, 기본 300 = 5분)

set -o pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

LOG_NAME="watchdog"
NODE_STATUS="$STATE_DIR/node_status.json"
WATCH_INTERVAL="${WATCHDOG_INTERVAL:-15}"
HANG_TIMEOUT="${AGENT_HANG_TIMEOUT:-300}"
RUNNING=1
load_env

# ── 서비스 감시 대상 ────────────────────────────────
SERVICES=(
  "cto_mac_node:$HARNESS_DIR/cto_mac_node.sh"
)

# ── 에이전트 hang 감시 대상 (remote-control 이름 : cwd 마지막 경로 컴포넌트) ──
# "rc_name:cwd_suffix"  cwd_suffix=HOME 은 /Users/abcd 를 의미
AGENT_WATCHES=(
  "Jarvis:HOME"
  "CTO_mac:CTO_mac"
  "Analyst:Analyst"
  "Producer:Producer"
  "Editor:Editor"
  "QA_mac:QA_mac"
  "Director_mac:Director_mac"
)

# ── 서비스 재시작 ────────────────────────────────────
restart_service() {
  local name="$1" script="$2"
  log WARN "재시작: $name ($script)"
  nohup bash "$script" >> "$LOG_DIR/$name.out" 2>&1 &
  disown 2>/dev/null || true
  json_set "$NODE_STATUS" '.watchdog.restarts = ((.watchdog.restarts // 0) + 1)
                           | .watchdog.last_restart_utc=$now | .watchdog.alive=true' \
    --arg now "$(utc_now)" 2>/dev/null || true
}

# ── 에이전트 hang 감지 ────────────────────────────────
# 세션 파일에서 status/waitingFor/updatedAt 을 읽어 hang 여부 판정.
# hang 이면 claude 프로세스에 TERM → launchd 가 있으면 자동 재기동.
check_agent_hang() {
  local rc_name="$1" cwd_suffix="$2"
  local session_dir="$HOME/.claude/sessions"
  local now_ms; now_ms=$(python3 -c "import time; print(int(time.time()*1000))")

  # 세션 파일 탐색: cwd 마지막 컴포넌트로 매칭
  local sf=""
  for f in "$session_dir"/*.json; do
    [ -f "$f" ] || continue
    local cwd; cwd=$(python3 -c "import json; print(json.load(open('$f')).get('cwd',''))" 2>/dev/null)
    if [ "$cwd_suffix" = "HOME" ]; then
      [ "$cwd" = "$HOME" ] && { sf="$f"; break; }
    else
      [ "${cwd##*/}" = "$cwd_suffix" ] && { sf="$f"; break; }
    fi
  done

  [ -z "$sf" ] && return 0  # 세션 없음 — 에이전트 미기동, 건너뜀

  local status waiting_for updated_at pid
  status=$(python3 -c "import json; d=json.load(open('$sf')); print(d.get('status',''))" 2>/dev/null)
  waiting_for=$(python3 -c "import json; d=json.load(open('$sf')); print(d.get('waitingFor',''))" 2>/dev/null)
  updated_at=$(python3 -c "import json; d=json.load(open('$sf')); print(d.get('updatedAt',0))" 2>/dev/null)
  pid=$(python3 -c "import json; d=json.load(open('$sf')); print(d.get('pid',''))" 2>/dev/null)

  # hang 조건: waiting 상태 + waitingFor 비어있지 않음 + HANG_TIMEOUT 초 초과
  if [ "$status" = "waiting" ] && [ -n "$waiting_for" ] && [ "$waiting_for" != "None" ]; then
    local elapsed_s=$(( (now_ms - updated_at) / 1000 ))
    if [ "$elapsed_s" -ge "$HANG_TIMEOUT" ] 2>/dev/null; then
      log WARN "[hang] $rc_name: status=waiting waitingFor=$waiting_for elapsed=${elapsed_s}s pid=$pid — TERM 전송"
      kill -TERM "$pid" 2>/dev/null || true
      json_set "$NODE_STATUS" ".watchdog.agent_hang_kills = ((.watchdog.agent_hang_kills // 0) + 1)
                               | .watchdog.last_hang_agent = \"$rc_name\"
                               | .watchdog.last_hang_utc = \$now" \
        --arg now "$(utc_now)" 2>/dev/null || true
    else
      log INFO "[hang-watch] $rc_name: waiting=$waiting_for elapsed=${elapsed_s}s (한계 ${HANG_TIMEOUT}s)"
    fi
  fi
}

# ── 메인 체크 루프 ────────────────────────────────────
check_once() {
  # ① 서비스 생존 체크
  local svc name script
  for svc in "${SERVICES[@]}"; do
    name="${svc%%:*}"; script="${svc#*:}"
    if is_alive "$name"; then
      : # 정상
    else
      log WARN "$name 미동작 감지"
      restart_service "$name" "$script"
    fi
  done

  # ② 에이전트 hang 체크
  local entry rc_name cwd_suffix
  for entry in "${AGENT_WATCHES[@]}"; do
    rc_name="${entry%%:*}"; cwd_suffix="${entry#*:}"
    check_agent_hang "$rc_name" "$cwd_suffix"
  done

  json_set "$NODE_STATUS" '.watchdog.alive=true | .processes.watchdog="running" | .heartbeat_utc=$now' \
    --arg now "$(utc_now)" 2>/dev/null || true
}

on_exit() {
  log INFO "watchdog 종료."
  json_set "$NODE_STATUS" '.watchdog.alive=false | .processes.watchdog="stopped"' 2>/dev/null || true
  release_singleton
}
trap 'RUNNING=0' SIGTERM SIGINT
trap on_exit EXIT

main() {
  acquire_singleton "watchdog" || exit 0
  log INFO "watchdog 기동 (interval=${WATCH_INTERVAL}s hang_timeout=${HANG_TIMEOUT}s pid=$$)"
  while [ "$RUNNING" -eq 1 ]; do
    check_once
    [ "$RUNNING" -eq 1 ] || break
    sleep "$WATCH_INTERVAL"
  done
}

main "$@"
