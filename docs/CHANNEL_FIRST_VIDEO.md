# Channel First Video — Posting Guide (Trader Cho)

대상: `outputs/ARM_20260603/short_full_v4.mp4` (+ `thumbnail_v4.png`, `metadata.md`)
업로드는 **사용자가 직접** 수행 — 이 문서는 운영 가이드입니다(안전 정지점).

## 게시 전 체크리스트
- [ ] `short_full_v4.mp4` 최종 확인 (41.4s, 1080×1920, 세로)
- [ ] `thumbnail_v4.png` 최종 확인 (1080×1920)
- [ ] `metadata.md` 검토 — 제목 3후보 중 1개 선택(의문형 권장: 첫 영상 호기심 유발)
- [ ] 면책 문구 영상(전 씬 하단) + 설명 + 고정댓글 3곳 모두 포함 확인
- [ ] Sources 명시 확인 (Yahoo Finance · 247wallst.com · Pexels · Wikimedia)
- [ ] 실데이터 일치 확인: 썸네일 % == 영상 % (−0.94%, 단일 스냅샷)

## 게시 시 설정
- 카테고리: **Science & Technology** 또는 **Education**
- 언어: English / 자막: 영어(영상 내 번인, CC 별도 불필요)
- 댓글: 허용 (검토 모드 권장 — 첫 영상 스팸 필터)
- 어린이용 콘텐츠(Made for Kids): **No** (성인 대상 금융 정보)
- 라이선스: Standard YouTube License
- Shorts 식별: 자동 (60초 이하 + 세로 9:16) — 제목/설명에 #shorts 포함됨
- 공개 범위: Public (또는 첫 영상 Unlisted로 내부 점검 후 Public 전환)

## 게시 직후 (첫 24시간)
- [ ] Pinned comment 고정 (metadata.md의 Pinned Comment 블록)
- [ ] 첫 댓글 응답 모니터링 (15분 내 — 초기 인게이지먼트 신호)
- [ ] 시청 지속률(APV) 6시간 후 첫 체크:
  - < 60% → 훅 약함 → 다음 영상 hook 톤 조정(촉매 명시 강화 / 첫 1초 숫자 노출)
  - 60–75% → 정상
  - > 75% → 알고리즘 진입 신호 → 게시 빈도 유지
- [ ] CTR(노출 클릭률) 체크: < 4% → 썸네일 카피/레이아웃 A/B (LAYOUT_BIG_NUMBER ↔ CHART_HERO)

## 첫 주 데이터 수집 (Phase 5 준비)
- 매일 `outputs/{ticker}/{date}/performance.json` 수기 업데이트:
  - views / impressions / CTR / APV(평균 시청 지속률) / avg_view_duration / likes / comments
- 수집 항목이 Phase 5 `performance_tracker`로 `channel_history`(RAG) 자동 적재의 입력이 됨
- 3편(ARM/NVDA/TSLA) 비교로 catalyst.type별 리텐션 차이 첫 관찰

## A/B 메모 (첫 배치)
- ARM: LAYOUT_BIG_NUMBER · 의문형 제목 · product 촉매
- NVDA: LAYOUT_CHART_HERO · guidance_raise · (차트형 썸네일 CTR 비교용)
- TSLA: LAYOUT_BIG_NUMBER · analyst_action · (suspect 볼륨 + 상승 = 역행 내러티브 테스트)

## 안전·정직성 불변 규칙 (게시해도 유지)
- 실존 인물 사진/얼굴 없음, 단정 표현 없음, 임의 숫자 없음(실데이터만)
- 데이터 판정은 임계값 자동(예: 볼륨 suspect) — 약한 데이터에 강한 라벨 금지
- 모든 영상·썸네일·설명에 "Not financial advice. Educational purposes."
