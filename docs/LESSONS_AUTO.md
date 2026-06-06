# TRADER CHO — 자동화 운영 규칙 (LESSONS_AUTO)

LESSONS.md의 절대 규칙(L0~L5)을 전제로, 자동화 파이프라인 전용 운영 규칙을 추가한다.

---

## A0. 종목 선정 (stage00_news_scan)

- A0.1 stage00는 피드 우선순위: Yahoo Finance → CNBC → MarketWatch → Benzinga → Motley Fool (순서대로 폴백)
- A0.2 KNOWN_TICKERS 화이트리스트에 없는 종목은 자동 제외 — 페니스톡·미검증 티커 차단
- A0.3 confidence=high 없으면 medium 포함, medium도 없으면 --auto 중단 (빈 picks 게시 금지)
- A0.4 오늘 선정 종목은 `state/today_picks.json`에 저장. 다음 날 재실행 전까지 재사용 금지
- A0.5 article_url은 반드시 실제 기사 페이지. 홈·목록 페이지 차단. is_valid_article_url() 통과 여부를 url_valid 필드에 기록. url_valid=False 종목은 --auto 파이프라인에서 자동 스킵. 검증: 경로 깊이 ≥4 + 무효 패턴 없음 + HTTP HEAD 200(timeout 3s). 네트워크 실패 시 URL 날짜 지시자(/2025/ /2026/ 등) 있으면 허용.
- A0.6 기사 본문 100자 미만이면 파이프라인 즉시 중단(ValueError). "No article catalyst was provided..." 텍스트 영상 노출 절대 금지. --auto 모드는 article_url에서 본문 자동 취득 후 100자 체크(article_fetch.py). 수동 모드는 --article 파일 미지정 시 동일 체크 적용.

## A1. 로고 취득 (logo_fetch)

- A1.1 취득 우선순위: 로컬캐시 → Wikidata P154(CC-BY-SA) → Logo.dev(API키 필요) → graceful skip
- A1.2 Logo.dev는 LOGODEV_API_KEY 없으면 요청 자체 생략 (불필요한 401 방지)
- A1.3 upload.wikimedia.org 429 시 최대 2회 backoff retry (3s, 8s). 그래도 실패하면 skip
- A1.4 취득 성공 시 assets_manifest.json에 출처/라이선스 기록 필수 (L5.2)
- A1.5 로고 없어도 썸네일·영상 제작 중단 금지 (graceful skip — 워터마크로 채널 식별)

## A2. 회사 사진 취득 (company_photo_fetch)

- A2.1 L0.1 절대 준수: 건물·제품·그래픽만, 인물·얼굴·직원 사진 자동 차단 (person blacklist 필터)
- A2.2 라이선스 필터: CC-BY-SA / CC-BY / CC0 / Public Domain만 허용. NC·ND 자동 제외
- A2.3 Commons API 429 시 5s backoff + 최대 2회 재시도. 그래도 실패하면 graceful skip
- A2.4 사진 있으면 씬1·3·11에 보조 카드로 사용. 없으면 현재처럼 배경만(컷 구조 변경 금지)
- A2.5 캐싱: assets/company_photos/{TICKER}_HQ.jpg / {TICKER}_product.jpg. 재취득은 파일 삭제 후 재실행

## A3. --auto 모드 (pipeline.py)

- A3.1 --auto 실행 순서: stage00(뉴스 수집+선정) → picks 순서대로 각 티커 run()
- A3.2 runs/{RUN_ID}/ 폴더에 run_summary.json + 티커별 심볼릭 링크 생성
- A3.3 한 티커 실패해도 다음 티커 계속 처리 (배치 중단 금지)
- A3.4 --auto 기본 theme=brightnews (채택 확정 2026-06-04)
- A3.5 --auto는 게시 게이트(⑨) 유지 — 자동 YouTube 업로드 금지. 파일 생성까지만.

## A4. 스케줄링

- A4.1 권장 실행 시간: 미국 동부 장 마감(오후 4시) + 1시간 후 (오후 5시 ET = 다음날 오전 6시 KST)
  - 장 중 실행 시 intraday 가격이 변동해 훅 부호가 바뀔 수 있음 (L0.6 위반 위험)
- A4.2 cron 예시: `0 5 * * * cd /path/to/shorts_maker && .venv/bin/python tradercho/pipeline.py --auto`
  - 또는 launchd com.shortsmaker.pipeline_auto (harness/README.md 참조)
- A4.3 장 폐장일(미국 공휴일)에는 stage00이 당일 기사 없어도 picks를 생성할 수 있음 — 날짜 확인 권장

## A5. 피드 관리

- A5.1 피드 0건 반환 시 다음 피드로 폴백 (에러 아님). 전체 19건 미만이면 로그 출력
- A5.2 피드 URL 변경은 stage00_news_scan.py FEEDS 리스트 직접 수정
- A5.3 Seeking Alpha / WSJ feedburner는 인증 필요 → 기본 비활성. 키 있으면 FEEDS에 추가

## 변경 이력

- 2026-06-04 초기 작성 (자동화 3모듈 추가 시점)
