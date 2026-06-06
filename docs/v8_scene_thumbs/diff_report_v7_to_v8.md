# v7 (Bright News 초안) → v8 (Bright News 확정) diff 리포트

## 1. 영상 메타
| | v7 brightnews | v8 brightnews |
|---|---|---|
| 파일 | short_full_v7_brightnews.mp4 | short_full_v8.mp4 |
| 길이 | 53.67s | 54.43s (+0.76s, opening 추가) |
| 크기 | 22.8MB | 30.9MB |
| 컷 수 | 18 | 19 (+1 opening 세그먼트) |
| 코덱 | h264/aac | h264/aac |

---

## 2. FIX1 — Pexels 다크블러 배경 제거 (Bright News 전용)

**문제**: v7에서 섹터 스톡 사진(반도체 반도체 배경)을 노랑(#FFE94A) 위에 alpha=0.25로 블렌드하면 어둡게 합성돼 탁한 인상.

**수정**: `compose_short.py`:
```python
if scene in BG_SCENES and T.ACTIVE_THEME != "brightnews":
    scene_background(img, ...)   # Bright에서는 완전 skip
```
**결과**: v8 배경 = 순수 #FFE94A 솔리드. 카드·칩이 흰/연노랑 위에 클린하게 떠 있음.

→ 비교: `compare_hook_v7.jpg` vs `compare_hook_v8.jpg`

---

## 3. FIX2 — text_muted 대비 강화

**문제**: v7 text_muted `#7A7A7A` → 노랑 위 대비 3.0:1(WCAG AA 4.5:1 미달).

**수정**: `theme_brightnews.py`:
```python
"text_muted": "#444444",   # was #7A7A7A
"text_secondary": "#222222",
```
WCAG 대비비: 노랑(#FFE94A) 위 #444444 = 5.6:1 ✓

**적용 씬**: 씬5(볼륨 면책·날짜 칩), 씬8(related as_of), 씬13(closing 출처).

---

## 4. STEP3 — mixed_text 키워드 색 분류 (씬1·3·11)

v7까지는 자막 전부 단일 text_primary(#111111). v8부터 단어별 색 자동 분류:

| 패턴 | 색 | 예시 |
|---|---|---|
| 2~5자 대문자 티커 | accent_data (#1E40AF 진파랑) | ARM, NVDA, RTX |
| +X.X% | accent_bull (#0EA853 녹색) | +2.26% |
| −X.X% | accent_bear (#E63946 빨강) | −0.3% |
| 위험 단어 | accent_alert (#FF6B00 주황) | risk, suspect, extended, stretched |

구현: `_word_color()` + `_mixed_subtitle()` (PIL word-by-word draw, 흰 외곽선 14px 유지).
적용: hook 자막, catalyst 자막, payoff 자막.

→ 씬1 스크린샷: `v8_01_hook.jpg` (ARM=파랑, % 색구분, 위험어=주황)

---

## 5. STEP4 — catalyst 마이크로이벤트 (기존 STEP2 세그먼트 체계 확인)

catalyst 씬은 3 서브세그먼트(intro 0.891s / card / highlight)로 이미 비트스냅:
- **intro**: 배경 글로우 펄스
- **card**: 뉴스카드 슬라이드인 + 헤드라인 word-by-word
- **highlight**: 키워드 형광펜 sweep + 마스코트 shocked 리액션

chart 씬: draw(라인 그리기) / pulse(RSI칩 출현) / chips(볼륨 칩).
related 씬: stagger(피어 바 순차) / pulse(sympathy_insight typewriter).
8개 이벤트 총 합산 = 비트스냅 112 BPM 구간 내 타이밍.

---

## 6. STEP5 — Opening 0.8s 블라스트 (신규 씬)

v7에 없던 **오프닝 세그먼트** 추가 (SCENES[0]):

| 타임스탬프 | 이벤트 |
|---|---|
| t=0.00~0.15 | 흰 플래시 (a=255→0) |
| t=0.15~0.45 | 대형 % 팝인 (pop_in 애니메이션, 280px) |
| t=0.50~0.80 | 마스코트 shocked + shock_jump 리액션 |

색: + → accent_bull(#0EA853), − → accent_bear(#E63946).
ARM 당일 +2.26% → 녹색 표시.

→ 프레임: `v8_opening_opening_flash.jpg` / `_number.jpg` / `_mascot.jpg`

---

## 7. v7 vs v8 씬별 비교 요약

| 씬 | v7 | v8 변경 |
|---|---|---|
| 없음 | 없음 | **오프닝 0.8s 추가** (STEP5) |
| hook | 단색 자막 | mixed_text 색분류 (STEP3) + 솔리드 노랑BG (FIX1) |
| result | 동일 | 솔리드 노랑BG (FIX1) |
| catalyst | 동일 | 솔리드 노랑BG (FIX1) |
| volume | text_muted 회색약함 | text_muted #444444 (FIX2) + 솔리드 노랑 |
| payoff | 단색 자막 | mixed_text (STEP3) |
| closing | text_muted 약함 | text_muted 강화 (FIX2) |

→ 비교 이미지: `compare_v7_v8.jpg`

---

## 8. 새로 발견된 이슈

| # | 이슈 | 심각도 | 비고 |
|---|---|---|---|
| i1 | 씬13~18 레이블이 숫자(13~18) — 세그먼트-씬 매핑 정보 없음 | 낮음 | 썸네일 파일명만, 영상 무관 |
| i2 | risk 씬 말풍선 꼬리 약간 프레임 경계 접근 | 낮음 | v6.5부터 지속(4줄 텍스트 높이) |
| i3 | BGM 루프 파일(test_track.mp3 16s) 실 로열티프리 교체 미완 | 중간 | 게시 전 실 BGM 필요 |
| i4 | 차트 matplotlib 프레임별 렌더 ~13분 병목 (v8 전체 ~25min) | 중간 | 캐시/벡터화 최적화 후보 |

---

## 정직성·구조 불변 확인

- L0.6 hook verb+sign guard ✓ (ARM +2.26% → "ripped" 유효)
- L0.4 단일 price 스냅샷 ✓ (price.json 재사용, related_dates.json 동결)
- L2.7 verdict 하드코딩 금지 ✓ (1.5× threshold 자동)
- L4.6 quip ≤4단어 ✓
- L3.1 정지<0.5s ✓ (0.133s)
