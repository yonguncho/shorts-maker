# ENVIRONMENT — shorts_maker (iMac 노드)

> 이 파일은 환경정보의 단일 진실(single source of truth)입니다.
> **자동 유지 규칙:** 사용자가 환경 관련 정보(설치/제거, 버전 변경, 키 보유 여부, 경로, 결정 사항 등)를
> 알려주면 Claude가 이 파일을 즉시 갱신합니다. 수동으로 점검한 항목은 `[점검]`, 사용자가 알려준 항목은 `[보고]`로 표기.

- 노드 식별자: `mac` / machine=`mac`
- 루트: `/Users/abcd/ai_workplace_mac/shorts_maker/`
- 최종 갱신: 2026-05-31 (STEP 1 환경 점검 + 원격/전원 점검)

---

## 시스템 [점검 2026-05-31]
| 항목 | 값 |
|---|---|
| macOS | 26.5 (Tahoe, Build 25F71) |
| CPU | Intel Core i5-10600 (x86_64) — **Apple Silicon 아님** |
| Homebrew 경로(예정) | `/usr/local/bin` (Intel 기준, `/opt/homebrew` 아님) |
| launchd | 사용 가능 |

## 설치된 도구 [점검 2026-05-31, 갱신]
| 도구 | 상태 | 버전/경로 |
|---|---|---|
| Homebrew | ✅ | 5.1.14 (`/usr/local`, Intel) |
| **Python** | ✅ | **3.13.13** (brew `python@3.13`, OpenSSL 3.6.2). 파이프라인은 **`.venv`** 사용(`shorts_maker/.venv`). 시스템 3.9.6도 잔존하나 미사용 |
| venv 패키지 | ✅ | requests 2.34.2 / matplotlib 3.10.9 / numpy 2.4.6 / Pillow 12.2.0 / **yfinance 1.4.1 / pandas 3.0.3 / pytrends 4.9.2 / praw 7.8.1** (멀티소스 재개발용, 2026-06-01 추가) |
| ffmpeg / ffprobe | ✅ | 설치됨 |
| codex | ✅ | codex-cli 0.135.0, 인증됨(gpt-5.5). `codex exec --skip-git-repo-check` 동작 확인 |
| claude CLI | ✅ | 2.1.159 (`/Users/abcd/.local/bin/claude`) — Codex 폴백용 |
| git | ✅ | 2.50.1 |
| jq | ✅ | 1.7.1 |

## 미설치 도구 [점검 2026-05-31]
| 도구 | 용도 | 권장도 | 상태 |
|---|---|---|---|
| node / npm | 차트 렌더 후보(Remotion/Puppeteer 등) | 🟢 불필요(matplotlib 채택) | 미설치 |

## 원격 접속 / 무중단 운영 [점검 2026-05-31]
> 요구사항: iMac 재부팅 후 에이전트 자동 복귀 + 외부에서 원격 세션 재접속.
| 항목 | 현재 값 | 무중단 운영에 필요한 값 | 상태 |
|---|---|---|---|
| **외부 원격 접속** | **Jarvis = `claude --remote-control "Jarvis"`** | — | ✅ 채택 (사용자 지정 2026-05-31) |
| **Jarvis 자동 재시작** | **launchd `com.shortsmaker.jarvis` (RunAtLoad+KeepAlive)** | 죽으면 자동 재기동+`--continue` 이어받기 | ✅ 설치·가동 (2026-05-31) |
| tmux/Tailscale/SSH 직접구성 | 불필요 | Jarvis가 원격-접속 층(④) 담당 | ⛔ 설계서 제외 |
| screen | 있음(`/usr/bin/screen`) | (로컬 detach 필요 시 fallback) | 🟡 |
| pmset autorestart | **0** | **1** (정전 후 자동 부팅) | ⚠️ 변경 필요 |
| 시스템 sleep | 허용(`sleep 1`) | sleep 0 권장 | ⚠️ 변경 필요 |
| 자동 로그인 | **비활성** | LaunchAgent 무인 기동 위해 활성 권장(보안 트레이드오프) | ⚠️ 결정 필요 |
| womp (Wake on LAN) | 1 | 1 유지 OK | ✅ |

## 결정 사항 (확정) [보고 2026-05-31]
- 구조 보완 5가지(`.env.example`, `harness/lib/common.sh`, `logs/`, `run/` PID, `.gitkeep`) **모두 반영**.
- 상태파일: 로컬은 Windows와 동일 파일명(`pipeline_status.json`, `node_status.json`) 유지(스키마 패리티). 충돌 방지용 **네임스페이스는 내부 식별자(node_id, machine, pipeline_id)로 처리**하고, 추후 중앙 집계 시 `*.mac.json`으로 push.
- 타임스탬프는 전부 UTC ISO8601.
- 두 파이프라인 폴더 **양방향 동기화 금지**.

## 시크릿 / API 키 [보고 — 비어있음]
> 값은 여기 기록하지 않음. `.env`에만 저장. 여기엔 "보유 여부"만 추적.
| 키 이름 | 용도 | 보유 |
|---|---|---|
| FINNHUB_API_KEY | 증시 데이터(Finnhub) | ✅ 보유 (.env, 2026-05-31) |
| FINNHUB_WEBHOOK_SECRET | Finnhub 웹훅 검증 | ✅ 보유 (.env, 2026-05-31) |

## 결정 / 메모 로그
- 2026-05-31: STEP 1 완료. 도구 설치는 사용자 승인 후 진행(현재 아무것도 설치 안 함).
- 2026-05-31: 무중단/원격 요구 추가. 재부팅 자동복귀 + 외부 원격 재접속을 1급 요구로 설계 반영.
- 2026-05-31: 구조 보완 5종 + 네임스페이스 방식 확정. 폴더 골격 생성.
- 2026-05-31: 외부 원격 접속은 **Jarvis remote agent** 채택. Tailscale/tmux/SSH 직접구성은 설계 제외. 무인 자동복귀(전원/launchd/상태복원 ①②③)는 여전히 자체 구축 대상.
- 2026-05-31: STEP 2 OK. A~D 재실측: Intel i5-10600 / ffmpeg=없음 / Codex=없음(미인증). adversarial(codex) 비활성 이유 = Codex CLI 미설치 + 계획상 의도적 골격(설치·인증 후 enabled:true 전환).
- 2026-05-31: 라우팅 순서 확정 — ⑨ before_publish 게이트에서 정지 → 사용자 수동 게시 → ⑩ 성과회수는 게시 후 실행. STEP 3 반영 예정.
- 2026-05-31: Finnhub API 키/웹훅시크릿 .env 저장(chmod 600, gitignore 제외). load_env가 `source <(...)`에서 변수 미로딩 버그 발견 → read 루프로 수정·검증.
- 2026-05-31: 전체 구현 위임 시작(PHASE 0). brew/ffmpeg/codex 설치 확인. RAG=출처중심 저장소(SQLite, 임베딩 없음) 확정. 시스템 Python 3.9.6 → **brew python@3.13(3.13.13)으로 업그레이드**, .venv 재생성. 데이터 소스=Finnhub.
- 2026-05-31: STEP 3 완료. main_harness(라우팅 뼈대, ⑨게이트 정지, 멱등 재개)+watchdog+launchd plist 3종+에이전트 CLAUDE.md 7종 골격 구축. bash 3.2.57(시스템 기본)에서 전 스크립트 동작 확인 — 스크립트는 bash 3.2 호환으로 작성. 라우팅 흐름(①~⑧→⑨정지→승인→⑩→done→멱등재개) 전부 검증 통과. 재부팅 자동복귀 ①(pmset)②(launchd)③(멱등재개)는 launchd/README.md에 설치안내(미적용, 설계 진입 직전 적용).
- 2026-05-31: **Jarvis 세션 무중단화 완료.** 원인규명 = `claude --remote-control "Jarvis"`는 터미널/로그인 세션에 묶인 인터랙티브 포그라운드 프로세스인데 감시자가 없어, 터미널 종료·연결끊김·Ctrl-C·부모셸 종료·크래시·재부팅 중 하나만 나도 죽고 자동복구 안 됨(크래시리포트·OOM·재부팅 흔적 전무 → 코드 크래시 아님, uptime 14일). 조치 = `harness/jarvis_remote.sh`(PTY 할당 `script` + 단일락 + 기존세션 핸드오프 가드 + 직전대화 `--continue` 이어받기 + thrash 방지) + `launchd/com.shortsmaker.jarvis.plist`(RunAtLoad+KeepAlive) 설치·bootstrap 완료. 현재 가동 중 Jarvis(28280)는 가드가 대기 중이라 중복 안 띄움 — 그 세션 종료 시 자동으로 새 세션이 직전 작업 이어받아 기동. **단, 완전한 재부팅 생존은 ①(pmset autorestart/sleep, sudo) + 자동로그인이 추가로 필요(미적용, 사용자 결정 대기).**
- 2026-05-31: **리소스 누수 방지 보강(사용자 요청).** 새 세션 인계 직전 죽은 기존 세션의 잔존물(좀비/행 claude RSS 600MB+ + 빈 터미널 셸)을 정리하도록 `jarvis_remote.sh` 보강 — 자기 조상/launchd(PID1)/비소유/비셸 부모는 절대 안 죽이는 다중 안전장치, `JARVIS_KILL_OLD_TTY`(기본1)로 토글. 래퍼 사망 시 자기 자식(script/claude)도 정리해 고아 없음. 감시자 재로드(pid 34647), 인계 대상 캡처 확인(claude=28280/터미널=28266). 사용자가 그 이전(9a127e03) 죽은 세션의 빈 터미널은 수동으로 닫음 — 앞으로는 자동 정리됨.
- 2026-06-01: **Jarvis 세션 작업 — 본구현 ②~⑤ + 인프라 통일 + Codex enable.**
  - **launchd 통일**: CTO_mac 에이전트(그간 login 셸 직속이던 것)를 `com.shortsmaker.agent.CTO_mac` 로 편입. + `com.shortsmaker.cto`(노드)·`com.shortsmaker.watchdog`(2차 안전망) `~/Library/LaunchAgents` 설치·bootstrap → 노드 status=online. (jarvis=경쟁세션 위험·harness=스케줄 미확정 으로 이번엔 제외). takeover 함정: `agent_remote.sh guard_until_free()` 가 기존 세션을 능동 kill 안 하고 자발종료 무한대기 → login 세션은 수동 SIGTERM 필요.
  - **stage② 가드레일 버그수정**: 투자권유 검사가 뉴스 헤드라인 원문("buy")을 오탐 → 클레임단위 검사로 변경(파이프라인 자체서술 indices/movers/themes 만, 제3자 인용 news/filings 제외).
  - **stage②~⑤ 본구현 완료**(stage03 소재선정 / stage04 대본·자막 / stage05 대본QA). 대본 사양 사용자확정: **45초·중립사실형·훅→데이터→맥락→클로저**. 전부 결정론·출처필수·가드레일. stage05 fact_match 가 자막 수치를 verified_market_data 와 대조(환각차단), 음성테스트로 검증. main_harness stage_module 에 3·4·5 배선.
  - **Codex 어드버서리얼 ON**: `manifest.adversarial.enabled=true`. codex-cli 0.135.0 동작확인. **공방이 클레임 평문덤프가 아니라 실제 렌더 리포트(render_markdown)를 검토하도록 수정** + ETF프록시·무버유니버스·as-of/지연/애그리게이터 고지 4건 추가 → stage② 공방 PASS(R2). 잔여 지적(Finnhub cite가 401 비공개 링크)은 비차단 향후개선.
  - **비디오 계층 완료(⑥⑦⑧)**: 사용자확정 차트=다크미니멀·BGM=일단무음. stage06 차트렌더(matplotlib, % 변동 막대, 포커스 강조, 1080×1920, 하단 자막여백), stage07 영상합성(PIL 자막 번인 → ffmpeg concat, 무음 AAC, 30fps CFR), stage08 영상QA(ffprobe: 해상도/길이/코덱h264-yuv420p/무결성). 실산출 `output/ready_for_review/short_<date>.mp4` 45.0s 검증 통과. main_harness 6·7·8 배선.
  - **상태(2026-06-01 세션 종료시점)**: **①~⑧ 전부 구현·실데이터 검증 완료** (end-to-end로 실제 쇼츠 MP4 산출). 미구현=⑩교훈/메타개선. **⑨ before_publish 게이트=설계대로 정지점 — 사용자 수동 게시 대기**(자동 게시 금지). ⑨ 게시준비(제목/설명/태그/썸네일 메타 생성)와 ⑩은 미구현이며, ⑨ 메타생성은 게이트 정지 전까지만 자동, 실제 업로드는 수동.
- 2026-06-01: **콘텐츠 품질 재개발 결정 (사용자 확정).** 기존 산출물이 순수 시세 무버("MSFT +5.45%")라 "왜 지금 이 종목인가" 앵글이 없어 부실 → 사용자가 멀티소스 전략(yfinance/Finnhub뉴스/Reddit/pytrends/상관관계·연관종목/LLM공급망그래프)을 지시. **이 전략은 직전 세션(403f26f3, 15:39)에서 P1~P4 로드맵으로 합의됐으나 2가지 질의 미응답 + 세션인계로 P1(Finnhub 뉴스/실적/VIXY 수집·검증)만 반영되고 P2~P4 미착수 상태로 유실**됐었음. 재확정 결정:
  - **범위 = P2~P4 전체 진행**: P2 yfinance + 상관관계 '연관종목' 엔진 + 라인/캔들 차트, P3 pytrends + Reddit "왜 화제", P4 LLM 테마/공급망 그래프(codex 적대검증 게이트 필수).
  - **소재선정 기준 변경 = "이슈+변동성 결합"**: 단순 % 무버가 아니라 뉴스/실적 이벤트가 있는 종목 중 변동성 큰 것 우선. stage03 재설계.
  - 어댑터 패턴 + `state/source_budget.json` 일일 콜 카운트로 무료티어 한도 자동 준수.
  - 리스크 등급: 🟢 yfinance/상관관계 = 계산된 사실(안전) / 🟡 Reddit·Trends = 사실귀속 표현으로만 / 🔴 LLM 그래프 = 환각·추천경계 → 뉴스원문에서만 추출·엣지마다 인용·codex 통과해야 방영.
  - **Reddit은 OAuth 앱 등록(외부 크리덴셜) 필요** → 자율해결 불가, 미보유 시 graceful skip + 사용자 요청. yfinance·pytrends는 키 불필요.
