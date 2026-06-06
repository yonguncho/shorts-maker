#!/usr/bin/env bash
# agent_remote.sh — 파이프라인 에이전트 원격제어 세션 감시 래퍼 (jarvis_remote.sh 일반화)
#
# Jarvis 와 동일 원리. 차이점: 에이전트 이름/작업디렉터리를 환경변수로 받아 N개 에이전트에 재사용.
#   AGENT_NAME (필수)  — 원격제어 세션 이름 (예: Analyst). launchd plist 에서 주입.
#   AGENT_CWD          — 이어받기/CLAUDE.md 컨텍스트 디렉터리. 기본 $ROOT/agents/$AGENT_NAME.
#
# 각 에이전트는 자기 이름으로만 감시·핸드오프하므로 서로 간섭 없음(이름별 격리).
# 자기 디렉터리가 곧 claude 프로젝트 슬러그 → 세션 히스토리도 에이전트별로 분리(--continue 충돌 없음).
#
# bash 3.2 호환. 시크릿은 .env 에만.

set -o pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"
load_env

RC_NAME="${AGENT_NAME:?AGENT_NAME 환경변수 필요}"
LOG_NAME="agent_${RC_NAME}"
RC_CWD="${AGENT_CWD:-$ROOT_DIR/agents/$RC_NAME}"
[ -d "$RC_CWD" ] || RC_CWD="$ROOT_DIR"
CLAUDE_BIN="${CLAUDE_BIN:-$HOME/.local/bin/claude}"
[ -x "$CLAUDE_BIN" ] || CLAUDE_BIN="$(command -v claude || echo claude)"
EXTRA_ARGS="${AGENT_EXTRA_ARGS:-}"
MIN_RUNTIME="${AGENT_MIN_RUNTIME:-10}"
KILL_OLD_TTY="${AGENT_KILL_OLD_TTY:-1}"

OLD_PIDS=""; OLD_TTY_PIDS=""; SELF_GUARD_PIDS=""; CHILD_PID=""

# 이 래퍼가 안 띄운, 같은 이름의 원격제어 프로세스 PID (ps 직접 매칭).
foreign_pids() {
  ps -axo pid=,command= 2>/dev/null \
    | grep -- "--remote-control" \
    | grep -w "$RC_NAME" \
    | grep -v "grep" \
    | grep -v "agent_remote.sh" \
    | awk '{print $1}'
}

compute_self_guard() {
  local p=$$ chain=""
  while [ -n "$p" ] && [ "$p" -gt 1 ] 2>/dev/null; do
    chain="$chain $p"; p="$(ps -o ppid= -p "$p" 2>/dev/null | tr -d ' ')"
  done
  SELF_GUARD_PIDS=" $chain 1 0 "
}
_is_guarded() { case "$SELF_GUARD_PIDS" in *" $1 "*) return 0;; *) return 1;; esac; }

_safe_kill() {
  local pid="$1" why="$2" comm owner
  [ -n "$pid" ] || return 0
  [ "$pid" -gt 1 ] 2>/dev/null || return 0
  _is_guarded "$pid" && return 0
  kill -0 "$pid" 2>/dev/null || return 0
  owner="$(ps -o user= -p "$pid" 2>/dev/null | tr -d ' ')"
  [ "$owner" = "$(id -un)" ] || { log INFO "정리 건너뜀(pid=$pid, 소유자=$owner ≠ 나)"; return 0; }
  comm="$(ps -o comm= -p "$pid" 2>/dev/null)"
  log WARN "잔존 정리: $why (pid=$pid comm=$comm)"
  kill -HUP "$pid" 2>/dev/null; sleep 2
  kill -0 "$pid" 2>/dev/null && { kill -TERM "$pid" 2>/dev/null; sleep 1; }
  kill -0 "$pid" 2>/dev/null && kill -KILL "$pid" 2>/dev/null
}
_kill_if_terminal() {
  local pid="$1" comm
  [ -n "$pid" ] || return 0
  _is_guarded "$pid" && return 0
  kill -0 "$pid" 2>/dev/null || return 0
  comm="$(ps -o comm= -p "$pid" 2>/dev/null)"
  case "$comm" in
    *zsh|*bash|*sh|*-zsh|*-bash|*login|*tmux*|*screen*) _safe_kill "$pid" "빈 터미널 셸" ;;
    *) log INFO "부모(pid=$pid comm=$comm) 셸 아님 — 정리 생략" ;;
  esac
}
reap_old_session() {
  local p
  for p in $OLD_PIDS; do kill -0 "$p" 2>/dev/null && _safe_kill "$p" "잔존 $RC_NAME claude"; done
  [ "$KILL_OLD_TTY" = "1" ] || { log INFO "AGENT_KILL_OLD_TTY=0 — 터미널 정리 생략"; return 0; }
  for p in $OLD_TTY_PIDS; do _kill_if_terminal "$p"; done
}
guard_until_free() {
  OLD_PIDS="$(foreign_pids | tr '\n' ' ')"
  [ -z "$(echo $OLD_PIDS)" ] && return 0
  local p
  for p in $OLD_PIDS; do OLD_TTY_PIDS="$OLD_TTY_PIDS $(ps -o ppid= -p "$p" 2>/dev/null | tr -d ' ')"; done
  log INFO "기존 $RC_NAME 감지(claude=$OLD_PIDS) — 종료 대기 후 이어받기"
  while [ -n "$(foreign_pids)" ]; do sleep 5; done
  reap_old_session
}

cleanup_on_exit() {
  if [ -n "$CHILD_PID" ] && kill -0 "$CHILD_PID" 2>/dev/null; then
    pkill -TERM -P "$CHILD_PID" 2>/dev/null; kill -TERM "$CHILD_PID" 2>/dev/null
  fi
  release_singleton
}
acquire_singleton "agent_${RC_NAME}" || { log WARN "이미 실행 중($RC_NAME) — 종료"; exit 0; }
compute_self_guard
trap 'cleanup_on_exit' EXIT INT TERM

decide_continue() {
  local slug; slug="$(printf '%s' "$RC_CWD" | sed 's#[/_]#-#g')"
  local proj="$HOME/.claude/projects/$slug"
  local pin="$RUN_DIR/agent_${RC_NAME}_resume.id"
  if [ -s "$pin" ]; then
    local sid; sid="$(head -n1 "$pin" | tr -d '[:space:]')"
    [ -n "$sid" ] && [ -f "$proj/$sid.jsonl" ] && { echo "--resume $sid"; return; }
  fi
  ls "$proj"/*.jsonl >/dev/null 2>&1 && echo "--continue" || echo ""
}

run_agent() {
  cd "$RC_CWD" 2>/dev/null || cd "$ROOT_DIR"
  local cont; cont="$(decide_continue)"
  log INFO "에이전트 기동: name=$RC_NAME cwd=$RC_CWD continue='${cont:-(none)}'"
  script -q /dev/null "$CLAUDE_BIN" $cont --remote-control "$RC_NAME" $EXTRA_ARGS &
  CHILD_PID=$!
  wait "$CHILD_PID"
  return $?
}

guard_until_free
start_ts="$(date +%s)"
run_agent; rc=$?
CHILD_PID=""
ran=$(( $(date +%s) - start_ts ))
log WARN "$RC_NAME 종료 (exit=$rc, 가동 ${ran}s) — launchd 재기동 예정"
[ "$ran" -lt "$MIN_RUNTIME" ] && { log WARN "thrash 방지 ${MIN_RUNTIME}s 대기"; sleep "$MIN_RUNTIME"; }
exit "$rc"
