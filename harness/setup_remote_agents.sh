#!/usr/bin/env bash
# setup_remote_agents.sh — 파이프라인 에이전트 전체를 원격제어(remote-control) 세션으로 연결.
#   각 에이전트마다 LaunchAgent plist 생성 → ~/Library/LaunchAgents 에 설치 → bootstrap.
#   래퍼 = agent_remote.sh (RunAtLoad+KeepAlive, --continue 로 직전 작업 이어받음).
#
# 사용법:
#   bash harness/setup_remote_agents.sh install   # 생성+설치+기동
#   bash harness/setup_remote_agents.sh status     # 상태
#   bash harness/setup_remote_agents.sh uninstall  # 전부 해제
#
# Codex 는 claude 가 아니라 codex CLI(adversary)라 여기 포함 안 함(codex_bridge 로 호출).

set -o pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LA_DIR="$HOME/Library/LaunchAgents"
WRAPPER="$ROOT_DIR/harness/agent_remote.sh"

# 원격 연결할 claude 기반 파이프라인 에이전트
AGENTS="CTO_mac Analyst Producer Editor QA_mac Director_mac"

PATH_VAL="/usr/local/bin:/opt/homebrew/bin:$HOME/.local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

gen_plist() {
  local name="$1" label="com.shortsmaker.agent.$1" out="$2"
  cat > "$out" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<!-- 파이프라인 에이전트 '$name' 원격제어 세션. agent_remote.sh 가 감시·자동재기동. -->
<plist version="1.0">
<dict>
  <key>Label</key><string>$label</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$WRAPPER</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>15</integer>
  <key>WorkingDirectory</key><string>$ROOT_DIR</string>
  <key>StandardOutPath</key><string>$ROOT_DIR/logs/agent_$name.out</string>
  <key>StandardErrorPath</key><string>$ROOT_DIR/logs/agent_$name.err</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>$PATH_VAL</string>
    <key>HOME</key><string>$HOME</string>
    <key>AGENT_NAME</key><string>$name</string>
    <key>AGENT_CWD</key><string>$ROOT_DIR/agents/$name</string>
  </dict>
</dict>
</plist>
PLIST
}

cmd_install() {
  mkdir -p "$LA_DIR" "$ROOT_DIR/logs"
  chmod +x "$WRAPPER"
  local uid; uid="$(id -u)"
  for a in $AGENTS; do
    local label="com.shortsmaker.agent.$a"
    local tmpl="$ROOT_DIR/launchd/$label.plist"
    local dst="$LA_DIR/$label.plist"
    gen_plist "$a" "$tmpl"          # 형상관리용 템플릿
    cp "$tmpl" "$dst"
    launchctl bootout "gui/$uid/$label" 2>/dev/null   # 멱등 재설치
    if launchctl bootstrap "gui/$uid" "$dst" 2>/dev/null; then
      echo "✅ $a 연결됨 ($label)"
    else
      echo "⚠️  $a bootstrap 실패 — 로그 확인: logs/agent_$a.err"
    fi
  done
}

cmd_status() {
  local uid; uid="$(id -u)"
  for a in $AGENTS; do
    local label="com.shortsmaker.agent.$a"
    local pid; pid="$(launchctl print "gui/$uid/$label" 2>/dev/null | awk '/[^a-z]pid =/{print $3; exit}')"
    printf "%-14s %s\n" "$a" "${pid:+pid=$pid}${pid:-(미실행/미등록)}"
  done
}

cmd_uninstall() {
  local uid; uid="$(id -u)"
  for a in $AGENTS; do
    local label="com.shortsmaker.agent.$a"
    launchctl bootout "gui/$uid/$label" 2>/dev/null && echo "해제: $a" || echo "이미 없음: $a"
    rm -f "$LA_DIR/$label.plist"
  done
}

case "${1:-status}" in
  install)   cmd_install ;;
  status)    cmd_status ;;
  uninstall) cmd_uninstall ;;
  *) echo "usage: $0 [install|status|uninstall]"; exit 2 ;;
esac
