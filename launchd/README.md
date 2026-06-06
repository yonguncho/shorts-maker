# 재부팅 자동복귀 설치 안내 (①②③)

iMac이 꺼졌다 켜져도 에이전트가 알아서 다시 돌게 만드는 3개 층. **모두 사용자 승인/실행 필요(sudo 포함).**
지금은 설치하지 않음 — STEP 3 완료 후 프로젝트 설계 진입 직전에 적용.

## ① 전원/OS — 정전·재부팅 후 자동 기동 + sleep 방지
```bash
# 정전 복구 후 자동 부팅
sudo pmset -a autorestart 1
# 시스템 sleep 끄기(디스플레이는 꺼도 무방)
sudo pmset -a sleep 0
sudo pmset -a disksleep 0
# (선택) 정전 후 자동 시작
sudo systemsetup -setrestartpowerfailure on
# 확인
pmset -g | grep -iE "autorestart|sleep"
```
> 현재값: `autorestart=0`, `sleep=1` → 위 설정으로 바꿔야 무인 운영 가능.

### 자동 로그인 (LaunchAgent 무인 기동 전제)
LaunchAgent는 **사용자 세션**에서 도므로, 재부팅 후 아무도 로그인 안 하면 시작되지 않음.
무인 운영하려면 자동 로그인 활성 필요(보안 트레이드오프):
`시스템 설정 > 사용자 및 그룹 > 자동 로그인`. (전용 자동화 머신이면 권장)
※ Claude CLI 인증·keychain·ffmpeg가 사용자 컨텍스트라 LaunchDaemon(root)보다 LaunchAgent가 맞음.

## ② 프로세스 — launchd 등록 (부팅 자동 기동 + 죽으면 재시작)
LaunchAgent로 설치 (사용자 세션):
```bash
mkdir -p ~/Library/LaunchAgents
cp /Users/abcd/ai_workplace_mac/shorts_maker/launchd/com.shortsmaker.*.plist ~/Library/LaunchAgents/

# 등록(bootstrap). gui/$(id -u) = 현재 사용자 GUI 세션
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.shortsmaker.cto.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.shortsmaker.watchdog.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.shortsmaker.harness.plist

# 상태 확인 / 로그
launchctl print gui/$(id -u)/com.shortsmaker.cto | grep -E "state|pid"
tail -f /Users/abcd/ai_workplace_mac/shorts_maker/logs/cto_mac_node.log

# 해제(중지)
launchctl bootout gui/$(id -u)/com.shortsmaker.cto
```
- `com.shortsmaker.cto` / `.watchdog`: RunAtLoad+KeepAlive = 부팅 자동 기동 + 상시 재시작.
- `com.shortsmaker.harness`: RunAtLoad=true(재부팅 시 중단 런 1회 resume), 주기 실행은 plist의 `StartCalendarInterval`(TODO).

## ③ 상태 복원 — 멱등 재개 (코드에 이미 반영)
- `main_harness.sh`는 `pipeline_status.json`의 단계 status를 보고 **done이 아닌 단계부터 재개**. 재부팅/크래시 후 다시 실행돼도 끝난 단계는 건너뛰고 이어감.
- 영속 루프(`cto_mac_node`, `watchdog`)는 `run/*.pid` 단일인스턴스 락으로 **중복 기동 방지** → launchd와 watchdog가 동시에 살려도 프로세스 1개만 유지.

## ④ Jarvis 원격제어 세션 무중단 (설치·가동 완료 2026-05-31)
외부 접속 = Jarvis = `claude --remote-control "Jarvis"`. 이건 **터미널/로그인 세션에 묶인 인터랙티브
포그라운드 프로세스**라 감시자가 없으면 터미널 종료·연결끊김·Ctrl-C·부모셸 종료·크래시 한 번에 죽고
자동복구가 안 된다 → `com.shortsmaker.jarvis` LaunchAgent + `harness/jarvis_remote.sh` 래퍼로 감시.

동작:
- **죽으면 자동 재기동**(KeepAlive) → 래퍼가 `--continue`로 **직전 대화를 이어받아** 새 Jarvis 세션 기동(기존 작업 자동 로드).
- **로그인 시 자동 기동**(RunAtLoad). PTY는 `script -q /dev/null`로 부여(launchd엔 tty 없음).
- **핸드오프 가드**: 이미 떠 있는 Jarvis가 있으면 죽을 때까지 대기 후 이어받음 → 원격제어 이름 중복 충돌 방지(무중단 교체).
- **잔존물 정리(리소스 회수)**: 새 세션을 띄우기 직전, 죽은 기존 세션의 (1) 좀비/행 claude(RSS 600MB+)와 (2) 빈 터미널 셸을 종료한다. 안전장치 = 자기 조상·launchd(PID 1)·내가 소유하지 않은 프로세스·셸이 아닌 부모는 **절대 안 죽임**. 터미널 정리는 `JARVIS_KILL_OLD_TTY=0` 으로 끌 수 있음(기본 1).
- thrash 방지: ThrottleInterval 15s + 래퍼 MIN_RUNTIME 10s. 래퍼가 죽으면 자기 자식(script/claude)도 같이 정리해 고아 프로세스 없음.

```bash
# 설치(이미 적용됨). 재적용/갱신 시:
cp /Users/abcd/ai_workplace_mac/shorts_maker/launchd/com.shortsmaker.jarvis.plist ~/Library/LaunchAgents/
launchctl bootout   gui/$(id -u)/com.shortsmaker.jarvis 2>/dev/null   # 기존 해제(멱등)
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.shortsmaker.jarvis.plist

# 상태 / 로그
launchctl print gui/$(id -u)/com.shortsmaker.jarvis | grep -E "state|pid|runs"
tail -f /Users/abcd/ai_workplace_mac/shorts_maker/logs/jarvis_remote.log

# 중지
launchctl bootout gui/$(id -u)/com.shortsmaker.jarvis
```

> ⚠️ **재부팅 생존은 별도다.** RunAtLoad는 *로그인 후* 기동이다. 전원이 나갔다 들어오거나 재부팅 시
> 무인 복귀하려면 위 ①(pmset autorestart/sleep, **sudo 필요**) + **자동 로그인 활성**이 함께 있어야 한다(미적용).
> 설정 = `.env`의 `JARVIS_RC_NAME`(이름), `JARVIS_CWD`(이어받을 프로젝트), `JARVIS_EXTRA_ARGS`(예: 무인시 `--dangerously-skip-permissions` 검토).
