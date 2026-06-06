#!/usr/bin/env bash
# jarvis_remote.sh — Jarvis 원격제어 세션 감시 래퍼 (자동 재시작 층 ④-supervisor)
#
# 문제: `claude --remote-control "Jarvis"` 는 터미널/로그인 세션에 묶인 인터랙티브
#   포그라운드 프로세스다. 감시자가 없어 터미널 종료·연결끊김·Ctrl-C·부모 셸 종료·
#   크래시·재부팅 중 하나라도 발생하면 그대로 죽고 자동 복구되지 않는다(원인: 2026-05-31).
#
# 해결: 이 래퍼를 launchd LaunchAgent(RunAtLoad+KeepAlive)로 돌린다.
#   - claude 가 어떤 이유로든 종료되면 → 래퍼도 종료 → launchd 가 래퍼를 재기동 →
#     래퍼가 `--continue` 로 직전 대화를 이어받아 새 Jarvis 세션을 띄운다(기존 작업 내용 자동 로드).
#   - 무인 운영을 위해 PTY(`script`)를 할당한다(인터랙티브 세션은 tty 필요, launchd엔 tty 없음).
#   - 이미 떠 있는 미관리 Jarvis(예: 사람이 수동 실행한 세션)가 있으면 죽을 때까지 기다렸다가
#     이어받는다 → 원격제어 이름 중복 충돌 없이 무중단 핸드오프.
#   - 새 세션을 띄우기 직전, 죽은 기존 세션의 "잔존물"(빈 터미널 셸 + 좀비 claude)을 정리한다
#     → PC 리소스 회수(claude 1세션이 RSS 600MB+ 차지). 안전장치로 자기 조상/launchd/비소유
#     프로세스는 절대 건드리지 않는다.
#
# bash 3.2(macOS 기본) 호환. 시크릿은 .env 에만.

set -o pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

LOG_NAME="jarvis_remote"
load_env

# ── 설정 (필요시 .env 또는 환경변수로 덮어쓰기) ─────────────────
RC_NAME="${JARVIS_RC_NAME:-Jarvis}"                 # 원격제어 세션 이름
RC_CWD="${JARVIS_CWD:-/Users/abcd}"                 # --continue/--resume 가 이어받을 프로젝트 디렉터리(최신 Jarvis 세션은 홈에 있음)
CLAUDE_BIN="${CLAUDE_BIN:-$HOME/.local/bin/claude}"
[ -x "$CLAUDE_BIN" ] || CLAUDE_BIN="$(command -v claude || echo claude)"
JARVIS_EXTRA_ARGS="${JARVIS_EXTRA_ARGS:-}"          # 예: --dangerously-skip-permissions (무인 운영시 검토)
MIN_RUNTIME="${JARVIS_MIN_RUNTIME:-10}"             # 이보다 빨리 죽으면 thrash 방지 대기
KILL_OLD_TTY="${JARVIS_KILL_OLD_TTY:-1}"            # 1=기존 세션의 빈 터미널 셸도 종료(리소스 회수)

OLD_JARVIS_PIDS=""     # 인계 직전 감지된 기존 Jarvis claude PID 들
OLD_TTY_PIDS=""        # 그 기존 Jarvis 들의 부모(터미널/로그인 셸) PID 들
SELF_GUARD_PIDS=""     # 절대 죽이면 안 되는 PID(나 자신 + 조상 체인 + launchd)
CHILD_PID=""           # 우리가 띄운 script(+claude) 자식 PID

# 외부에 떠 있는 (이 래퍼가 안 띄운) Jarvis 원격제어 프로세스 PID 목록.
# 주의: macOS sandbox 환경에서 `pgrep -f` 가 명령줄을 못 잡는 경우가 있어 ps 로 직접 매칭.
foreign_jarvis_pids() {
  ps -axo pid=,command= 2>/dev/null \
    | grep -- "--remote-control" \
    | grep -w "$RC_NAME" \
    | grep -v "grep" \
    | grep -v "jarvis_remote.sh" \
    | awk '{print $1}'
}

# 나 자신과 모든 조상(→launchd)을 보호 목록에 등록. 이 PID 들은 정리 대상에서 제외.
compute_self_guard() {
  local p=$$ chain=""
  while [ -n "$p" ] && [ "$p" -gt 1 ] 2>/dev/null; do
    chain="$chain $p"
    p="$(ps -o ppid= -p "$p" 2>/dev/null | tr -d ' ')"
  done
  SELF_GUARD_PIDS=" $chain 1 0 "
}

_is_guarded() { case "$SELF_GUARD_PIDS" in *" $1 "*) return 0;; *) return 1;; esac; }

# 한 PID 를 안전하게 종료(SIGHUP→TERM→KILL). 다중 안전장치 통과 시에만.
_safe_kill() {
  local pid="$1" why="$2" comm owner
  [ -n "$pid" ] || return 0
  [ "$pid" -gt 1 ] 2>/dev/null || return 0          # PID 0/1(launchd) 금지
  _is_guarded "$pid" && return 0                     # 나/조상 금지
  kill -0 "$pid" 2>/dev/null || return 0             # 이미 죽음
  owner="$(ps -o user= -p "$pid" 2>/dev/null | tr -d ' ')"
  [ "$owner" = "$(id -un)" ] || { log INFO "정리 건너뜀(pid=$pid, 소유자=$owner ≠ 나)"; return 0; }
  comm="$(ps -o comm= -p "$pid" 2>/dev/null)"
  log WARN "기존 세션 잔존 정리: $why (pid=$pid comm=$comm)"
  kill -HUP  "$pid" 2>/dev/null; sleep 2
  kill -0 "$pid" 2>/dev/null && { kill -TERM "$pid" 2>/dev/null; sleep 1; }
  kill -0 "$pid" 2>/dev/null && kill -KILL "$pid" 2>/dev/null
}

# 부모 PID 가 "인터랙티브 셸/로그인" 일 때만 터미널로 간주하고 종료.
_kill_if_terminal() {
  local pid="$1" comm
  [ -n "$pid" ] || return 0
  _is_guarded "$pid" && return 0
  kill -0 "$pid" 2>/dev/null || return 0
  comm="$(ps -o comm= -p "$pid" 2>/dev/null)"
  case "$comm" in
    *zsh|*bash|*sh|*-zsh|*-bash|*login|*tmux*|*screen*) _safe_kill "$pid" "빈 터미널 셸" ;;
    *) log INFO "부모(pid=$pid comm=$comm)는 셸 아님 — 터미널 정리 건너뜀" ;;
  esac
}

# 인계 직전: 죽은 기존 세션의 잔존물 회수
#   1) 혹시 아직 살아있는 기존 Jarvis claude(좀비/행) 강제 종료 — 리소스 최우선 회수
#   2) 그 세션을 호스팅하던 빈 터미널 셸 종료(옵션 KILL_OLD_TTY)
reap_old_session() {
  local p
  for p in $OLD_JARVIS_PIDS; do
    if kill -0 "$p" 2>/dev/null; then
      _safe_kill "$p" "잔존 Jarvis claude(좀비/행)"
    fi
  done
  [ "$KILL_OLD_TTY" = "1" ] || { log INFO "JARVIS_KILL_OLD_TTY=0 — 터미널 정리 생략"; return 0; }
  for p in $OLD_TTY_PIDS; do
    _kill_if_terminal "$p"
  done
}

# ── 1) 핸드오프 가드: 이미 떠 있는 Jarvis 가 있으면 사라질 때까지 대기 ──
#    대기 시작 시 기존 Jarvis 와 그 부모(터미널) PID 를 미리 채집해 둔다(죽은 뒤엔 못 찾으므로).
guard_until_free() {
  OLD_JARVIS_PIDS="$(foreign_jarvis_pids | tr '\n' ' ')"
  [ -z "$(echo $OLD_JARVIS_PIDS)" ] && return 0
  local p
  for p in $OLD_JARVIS_PIDS; do
    OLD_TTY_PIDS="$OLD_TTY_PIDS $(ps -o ppid= -p "$p" 2>/dev/null | tr -d ' ')"
  done
  log INFO "기존 Jarvis 감지(claude=$OLD_JARVIS_PIDS / 터미널=$OLD_TTY_PIDS) — 종료 대기 후 잔존정리·이어받기"
  while [ -n "$(foreign_jarvis_pids)" ]; do sleep 5; done
  log INFO "기존 Jarvis 종료 확인 — 잔존물 정리 시작"
  reap_old_session
}

# ── 2) 단일 인스턴스 락 + 종료 시 우리 자식까지 정리 ─────────────
cleanup_on_exit() {
  # 래퍼가 죽을 때 우리가 띄운 script/claude 자식이 고아로 남아 리소스 먹지 않게 정리
  if [ -n "$CHILD_PID" ] && kill -0 "$CHILD_PID" 2>/dev/null; then
    pkill -TERM -P "$CHILD_PID" 2>/dev/null   # script 아래 claude
    kill  -TERM "$CHILD_PID" 2>/dev/null
  fi
  release_singleton
}

acquire_singleton "jarvis" || { log WARN "다른 jarvis 래퍼가 이미 실행 중 — 종료"; exit 0; }
compute_self_guard
trap 'cleanup_on_exit' EXIT INT TERM

# ── 3) --continue 사용 여부 결정 (직전 대화가 있으면 이어받기) ──
decide_continue() {
  # claude 의 프로젝트 디렉터리 인코딩은 '/' 와 '_' 를 모두 '-' 로 바꾼다.
  #   /Users/abcd -> -Users-abcd
  local slug; slug="$(printf '%s' "$RC_CWD" | sed 's#[/_]#-#g')"
  local proj="$HOME/.claude/projects/$slug"
  # 1) 세션 핀이 있으면 그 세션을 결정론적으로 이어받는다(--resume).
  #    $RUN_DIR/jarvis_resume.id 에 세션 UUID 한 줄. 해당 transcript 가 실제 있을 때만 사용.
  #    --continue 는 "프로젝트 최신 세션"을 잡으므로, 다른 세션(예: 사람이 띄운 조사 세션)이
  #    더 최근이면 엉뚱하게 잡힌다 → 특정 작업 세션을 핀으로 고정.
  local pin="$RUN_DIR/jarvis_resume.id"
  if [ -s "$pin" ]; then
    local sid; sid="$(head -n1 "$pin" | tr -d '[:space:]')"
    if [ -n "$sid" ] && [ -f "$proj/$sid.jsonl" ]; then
      echo "--resume $sid"
      return
    fi
  fi
  # 2) 핀이 없으면 cwd 프로젝트의 직전 대화를 --continue.
  if ls "$proj"/*.jsonl >/dev/null 2>&1; then
    echo "--continue"
  else
    echo ""
  fi
}

# ── 4) Jarvis 기동 (PTY 할당, 직전 작업 이어받기) ──────────────
run_jarvis() {
  cd "$RC_CWD" 2>/dev/null || cd "$ROOT_DIR"
  local cont; cont="$(decide_continue)"
  log INFO "Jarvis 기동: name=$RC_NAME cwd=$RC_CWD continue='${cont:-(none)}' extra='${JARVIS_EXTRA_ARGS:-}'"

  # macOS BSD script 로 PTY 부여, typescript 는 버림(/dev/null).
  #   script -q /dev/null <command...>
  # remote-control 입력은 원격 브리지에서 오므로 stdin 유휴 상태여도 안전.
  # 백그라운드로 띄워 PID 를 잡고 wait → 래퍼 종료 시 자식까지 정리 가능.
  script -q /dev/null "$CLAUDE_BIN" $cont --remote-control "$RC_NAME" $JARVIS_EXTRA_ARGS &
  CHILD_PID=$!
  wait "$CHILD_PID"
  return $?
}

# ── 메인 ────────────────────────────────────────────────────
guard_until_free

start_ts="$(date +%s)"
run_jarvis
rc=$?
CHILD_PID=""
end_ts="$(date +%s)"
ran=$(( end_ts - start_ts ))
log WARN "Jarvis 종료 (exit=$rc, 가동 ${ran}s) — launchd 가 재기동 예정"

# 너무 빨리 죽으면(설정/인증 오류 등) 재기동 폭주 방지
if [ "$ran" -lt "$MIN_RUNTIME" ]; then
  log WARN "가동시간 ${ran}s < ${MIN_RUNTIME}s — thrash 방지 위해 ${MIN_RUNTIME}s 대기"
  sleep "$MIN_RUNTIME"
fi

exit "$rc"
