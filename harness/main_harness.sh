#!/usr/bin/env bash
# main_harness.sh — shorts_maker 파이프라인 메인 루프 (라우팅 뼈대)
# 단계 ①~⑩ 을 순서대로 라우팅. 각 단계 실제 작업은 TODO(프로젝트 설계 단계).
#
# 게이트 흐름 (사용자 확정):
#   ①~⑧ 처리 → ⑨ publish_prep(before_publish 게이트)에서 **정지** → 사용자가 수동 게시
#   → 게이트 approved → ⑩ lessons_meta(성과회수) 실행.
#
# 자동복귀(③ 상태복원): pipeline_status.json 의 단계 status 를 보고 "done 이 아닌 단계부터" 재개.
#   재부팅/크래시 후 다시 실행돼도 멱등 — 끝난 단계는 건너뛰고 이어서 진행.
#
# 사용법:
#   main_harness.sh start    # 새 런 시작(단계 초기화 + run_id 부여)
#   main_harness.sh          # 재개(done 아닌 단계부터) — 재부팅 후 launchd 가 호출하는 기본형
#   main_harness.sh status   # 현재 상태 출력

set -o pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

LOG_NAME="main_harness"
PIPE="$STATE_DIR/pipeline_status.json"
load_env

require_jq() { command -v jq >/dev/null 2>&1 || { log ERROR "jq 필요"; exit 1; }; }

# ── 상태 헬퍼 ─────────────────────────────────────────
pipe_get()   { jq -r "$1" "$PIPE" 2>/dev/null; }
set_pipeline() { json_set "$PIPE" "$1" "${@:2}"; }

set_stage_status() {
  local id="$1" st="$2"
  set_pipeline '.stages |= map(if .id==($id|tonumber) then .status=$st | .updated_utc=$now else . end)
                | .current_stage=($id|tonumber) | .heartbeat_utc=$now' \
    --arg id "$id" --arg st "$st" --arg now "$(utc_now)"
}

# ── 새 런 시작 ────────────────────────────────────────
start_run() {
  local rid="run-$(date -u +%Y%m%dT%H%M%SZ)"
  set_pipeline '
    .run_id=$rid | .state="running" | .current_stage=1
    | .approval_gates.before_publish="pending" | .last_error=null
    | .updated_utc=$now | .heartbeat_utc=$now
    | .stages |= map(.status="pending" | .updated_utc=null)
  ' --arg rid "$rid" --arg now "$(utc_now)"
  log INFO "새 런 시작: $rid"
}

# 단계 id → 구현된 Python 모듈 매핑(있으면 실제 실행, 없으면 골격 스텁).
stage_module() {
  case "$1" in
    1) echo "src.stages.stage01_collect_verify" ;;
    2) echo "src.stages.stage02_analysis_report" ;;
    3) echo "src.stages.stage03_topic_selection" ;;
    4) echo "src.stages.stage04_script_writing" ;;
    5) echo "src.stages.stage05_qa_script" ;;
    6) echo "src.stages.stage06_chart_render" ;;
    7) echo "src.stages.stage07_video_render" ;;
    8) echo "src.stages.stage08_qa_video" ;;
    *) echo "" ;;   # 9~10: 미구현 → 골격
  esac
}

# ── 단계 실행 ─────────────────────────────────────────
# 구현된 단계는 .venv python 으로 실행하고 종료코드로 게이팅(0=done, !=0=failed→정지).
# 미구현 단계는 기존 골격 스텁(바로 done) 유지 — 파이프라인 end-to-end 흐름 보존.
# 반환: 0=계속, !=0=실패(라우팅 정지).
run_stage() {
  local id="$1" name="$2" agent="$3"
  local module; module="$(stage_module "$id")"
  local py="$ROOT_DIR/.venv/bin/python"
  [ -x "$py" ] || py="python3"

  if [ -n "$module" ]; then
    log INFO "▶ 단계 ${id} [${name}] → agent=${agent}  (impl: ${module})"
    set_stage_status "$id" "running"
    if ( cd "$ROOT_DIR" && "$py" -m "$module" ); then
      set_stage_status "$id" "done"
      log INFO "✔ 단계 ${id} [${name}] 완료"
      return 0
    else
      local rc=$?
      set_pipeline '.stages |= map(if .id==($id|tonumber) then .status="failed" | .updated_utc=$now else . end)
                    | .state="error" | .last_error=$err | .current_stage=($id|tonumber)
                    | .heartbeat_utc=$now | .updated_utc=$now' \
        --arg id "$id" --arg now "$(utc_now)" --arg err "stage${id} ${name} rc=${rc}"
      log ERROR "✖ 단계 ${id} [${name}] 실패 (rc=${rc}) — 라우팅 정지"
      return "$rc"
    fi
  fi

  # 미구현 단계: 골격 스텁
  log INFO "▶ 단계 ${id} [${name}] → agent=${agent}  (골격 스텁 — 미구현)"
  set_stage_status "$id" "done"
  log INFO "✔ 단계 ${id} [${name}] 완료(골격)"
  return 0
}

# ── 게이트: ⑨ publish_prep ────────────────────────────
# approved 면 통과(⑩로), 아니면 awaiting 으로 정지.
handle_gate_stage() {
  local id="$1" name="$2" agent="$3"
  local gate; gate="$(pipe_get '.approval_gates.before_publish')"
  if [ "$gate" = "approved" ]; then
    log INFO "▶ 단계 ${id} [${name}] 게이트 approved → 통과"
    set_stage_status "$id" "done"
    return 0
  fi
  # 정지: 사용자 수동 게시 대기
  set_pipeline '.approval_gates.before_publish="awaiting" | .state="blocked"
                | .current_stage=($id|tonumber) | .heartbeat_utc=$now | .updated_utc=$now
                | .stages |= map(if .id==($id|tonumber) then .status="awaiting" | .updated_utc=$now else . end)' \
    --arg id "$id" --arg now "$(utc_now)"
  log INFO "⏸ 단계 ${id} [${name}] — before_publish 게이트에서 정지. 사용자 수동 게시 대기."
  log INFO "   게시 완료 후 게이트를 approved 로 바꾸면(명령/직접) ⑩ 성과회수가 진행됨."
  return 10   # 정지 신호
}

# ── 메인 라우팅 루프 ──────────────────────────────────
route() {
  require_jq
  acquire_singleton "main_harness" || exit 0
  log INFO "main_harness 라우팅 시작 (run_id=$(pipe_get '.run_id'), pid=$$)"
  set_pipeline '.state=(if .state=="blocked" then .state else "running" end) | .heartbeat_utc=$now' --arg now "$(utc_now)"

  # 단계 목록을 id 순으로 순회
  local count; count="$(pipe_get '.stages | length')"
  local i
  for ((i=0; i<count; i++)); do
    local id name agent status
    id="$(pipe_get ".stages[$i].id")"
    name="$(pipe_get ".stages[$i].name")"
    agent="$(pipe_get ".stages[$i].agent")"
    status="$(pipe_get ".stages[$i].status")"

    # 멱등 재개: 이미 done 이면 건너뜀
    if [ "$status" = "done" ]; then
      log INFO "↷ 단계 ${id} [${name}] 이미 done — 건너뜀"
      continue
    fi

    if [ "$id" = "9" ]; then
      handle_gate_stage "$id" "$name" "$agent"
      if [ $? -eq 10 ]; then
        return 0   # 게이트 정지 → 라우팅 종료(여기서 멈춤)
      fi
    else
      if ! run_stage "$id" "$name" "$agent"; then
        log ERROR "라우팅 정지: 단계 ${id} [${name}] 실패 (재실행 시 멱등 재개)"
        return 1   # 단계 실패 → 라우팅 정지(다음 실행 때 failed 단계부터 재개)
      fi
    fi
  done

  # 전 단계 완료
  set_pipeline '.state="done" | .current_stage=null | .updated_utc=$now | .heartbeat_utc=$now' --arg now "$(utc_now)"
  log INFO "✅ 파이프라인 전 단계 완료 (state=done)"
}

show_status() {
  require_jq
  jq '{run_id, state, current_stage, before_publish: .approval_gates.before_publish,
       stages: [.stages[] | {id, name, status}]}' "$PIPE"
}

case "${1:-resume}" in
  start)  start_run; route ;;
  resume) route ;;
  status) show_status ;;
  *) echo "usage: $0 [start|resume|status]"; exit 2 ;;
esac
