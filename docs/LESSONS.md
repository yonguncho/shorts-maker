# TRADER CHO — Operating Lessons

Claude Code는 매 작업 시작 시 이 파일을 가장 먼저 읽어야 한다.
규칙은 추가만 한다 — 삭제 시 reason 코멘트 필수.

## L0. 절대 금지 (위반 시 빌드 실패)
- L0.1 실존 인물 사진/얼굴 합성 일절 금지
- L0.2 외부 영상·이미지의 원본 복제·재사용 금지 (관찰·추상화만 허용)
- L0.3 단정 표현 금지: "will rise", "guaranteed", "must buy", "100%", "easy money"
- L0.4 임의 숫자 생성 금지 (yfinance 실데이터만). **한 파이프라인 실행은 단일 price 스냅샷을 공유하고 재페치 금지** — 모든 단계(trader_lens/hook/thumbnail/compose)가 동일 snapshot(fetched_at_utc 포함) 사용, intraday drift로 썸네일·영상 숫자 불일치 방지
- L0.5 모든 영상·썸네일에 면책 고정: "Not financial advice. Educational purposes."
- L0.6 hook 시제·부호 일치: 동사의 등락 함의는 오늘 % 부호와 일치 필수(상승동사 ripped/popped/surged → 오늘 ≥+1%, 하락동사 slid/dropped/tumbled → 오늘 ≤−1%, ±1% 이내는 상태묘사 stretched/cooling/resting/extended 강제). catalyst 사건은 시점 명시(과거)로 분리 언급. 예 가능: "Two days after the RTX Spark rip — ARM cooling already?" / 예 불가: "ARM ripped after RTX Spark. Too crowded already?"(ripped+−0.94% 충돌)

## L1. 디자인 (학습된 함정)
- L1.1 이모지 사용 금지 — 단색 SVG 아이콘만
- L1.2 외곽선은 자막에만, 본문/카드 텍스트엔 금지
- L1.3 한 화면 액센트 컬러 최대 2개
- L1.4 그라데이션 배경 금지
- L1.5 본문 좌측 정렬 기본, 헤드라인만 중앙 허용
- L1.6 마스코트 누끼 시 그림자/테두리 잔재 0 (rembg 검증 필수)
- L1.7 자막 safe-zone MarginV ≥ 250

## L2. 정보 신뢰성
- L2.1 데이터 칩 [RSI/Vol/52w] 상시 노출
- L2.2 출처 워터마크 좌하단 고정
- L2.3 시점 명시 "As of {date, time ET}"
- L2.4 비교 기준 명시 "+15% vs SPX +0.3%"
- L2.5 리스크 씬(씬10) 의무 — 누락 시 빌드 실패
- L2.6 헤징 언어 유지 "likely/appears/could/may"
- L2.7 데이터 판정은 임계값 기반 자동 — 라벨 하드코딩 금지 (예: vol 1.5×↑=conviction / 1.0~1.5×=neutral / 1.0×↓=suspect). 약한 데이터에 강한 라벨 금지(신뢰성 정체성 핵심)

## L3. 역동성 (집중력)
- L3.1 정지 화면 0.5초 이상 금지
- L3.2 BGM 비트 싱크 필수 (±0.15s 이내)
- L3.3 컷 평균 2~2.5초 (60초당 25~30컷)
- L3.4 핵심 숫자·키워드는 pop_in (scale 0.3→1.3→0.95→1.0)
- L3.5 켄번즈 5종 순환 (같은 패턴 연속 금지)
- L3.6 shake/glitch는 양념 (영상당 각 3회/2회 한계)

## L4. 훅 (리텐션)
- L4.1 첫 1초에 움직임·숫자·마스코트 중 최소 1개
- L4.2 첫 3초에 결론 일부 노출 (curiosity gap)
- L4.3 hook_line 12 단어 이내 영어
- L4.4 의문형 또는 패턴 인터럽트 우선
- L4.5 payoff는 마지막 3초에 (오픈 루프 회수)
- L4.6 마스코트 quip(말풍선)은 ≤4 단어 구어체(캐릭터 반응). 분석 문장·단정·인물 금지. 풀자막(사실)과 역할 분리. 말풍선은 씬1·6·11만(씬3·10 등 신뢰 중심 씬 금지)

## L5. 운영
- L5.1 한 번에 전체 코드 생성 금지 — Phase별로 끊고 결과 검증
- L5.2 모든 다운로드 에셋은 assets_manifest.json에 출처/라이선스 기록
- L5.3 외부 영상 관찰 노트는 docs/knowledge/observed_*.md에 출처(채널/날짜) 명시
- L5.4 영상 완료 시 회고 단계 실행 (새 lesson 후보 제안)

## 변경 이력
- 2026-06-02 초기 작성 (Phase 0)
