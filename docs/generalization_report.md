# 파이프라인 일반화 검증 — ARM / NVDA / TSLA (2026-06-03)

3개 티커 end-to-end(pipeline.py) 실행. 실 yfinance 데이터 + 가상 기사(docs/samples/{ticker}_article.txt).

## hook_line 비교 (촉매별 톤 분기)
| 티커 | catalyst | durability | hook_line |
|---|---|---|---|
| ARM | product | DURABLE | "ARM ripped after Nvidia's RTX Spark. Too crowded already?" |
| NVDA | guidance_raise | DURABLE | "NVDA's guidance raise says: not early anymore?" |
| TSLA | analyst_action | TEMPORARY | "TSLA price-target cut: demand scare, but volume disagrees?" |

→ 3개 모두 **촉매를 이름으로 명시**(P1.2): RTX Spark / guidance raise / price-target cut. 톤도 분기(제품검증 / 가이던스 / 애널리스트 액션). 인물명 없음(L0.1).

## thumbnail layout 자동선택
| 티커 | catalyst | layout | 근거 |
|---|---|---|---|
| ARM | product | LAYOUT_BIG_NUMBER | 기본 거대 % 임팩트 |
| NVDA | guidance_raise | **LAYOUT_CHART_HERO** | 펀더멘털 발표(beat+raise) → 차트 히어로 |
| TSLA | analyst_action | LAYOUT_BIG_NUMBER | 거대 % 임팩트 |

→ 선택기가 catalyst.type로 정상 분기. NVDA만 CHART_HERO(라인차트+▼%), 나머지 BIG_NUMBER.
주: 초기 NVDA가 earnings_beat 아닌 **guidance_raise**로 분류됨(codex가 beat보다 지속적인 가이던스 상향을 촉매로 선택) → 선택기에 guidance_raise도 CHART_HERO로 추가(펀더멘털 발표 묶음).

## 거래량 verdict (L2.7 임계값 자동)
| 티커 | vol_vs_avg | verdict |
|---|---|---|
| ARM | 0.45× | suspect |
| NVDA | 0.43× | suspect |
| TSLA | 0.40× | suspect |
→ 3개 다 당일 실거래량이 평균 미만(<1.0×)이라 전부 suspect로 자동 판정. 하드코딩 없이 데이터대로.

## 마스코트 표정 매핑
- 현재 표정은 **씬 역할 기반 고정**(hook=thinking, catalyst=shocked, chart/volume/durability/sector=analysis, smart=thinking, risk=warning, payoff/closing=cheer) — 3 티커 동일.
- 즉 **catalyst durability에 따라 바뀌지 않음**. 명세는 "NVDA DURABLE→cheer" 기대했으나, 현 설계는 브랜드 일관성 위해 씬 역할로 고정.
- 판단: 일관성 장점. catalyst 기반 변형 원하면 hook/closing 표정만 durability로 분기하는 소폭 개선 가능(후속 옵션).

## 섹터 sympathy + insight
| 티커 | related[] | 씬8 | sympathy_insight |
|---|---|---|---|
| ARM | 4개(MRVL/MU/TSM/ASML, 전부 동일거래일) | 5-bar "MOVING WITH ARM" | "Mixed reaction — selective AI-PC exposure" |
| NVDA | 0개 | SPX 폴백 "NVDA vs the tape" | (피어 없음) |
| TSLA | 0개 | SPX 폴백 "TSLA vs the tape" | (피어 없음) |
→ ARM 기사만 동종 반도체 피어를 명시 → 5막대. NVDA/TSLA 기사엔 피어 미언급 → trader_lens가 피어를 **지어내지 않고**(L0.4 정신) related=[] → SPX 폴백(P1.1 설계대로 작동).

## 발견된 ARM-specific 하드코딩 (→ 픽스 완료)
1. `s_compare` 제목 "ARM vs the tape" → `"{ticker} vs the tape"` ✅
2. `s_payoff` 제목 "So — already too hot?"(ARM 훅 echo) → `"So — what's the read?"`(중립) ✅
3. 섹터 폴백 제목 "ARM vs the tape" → `"{ticker} vs the tape"` ✅
→ 위 3건은 v4 ARM 영상엔 우연히 맞았으나 NVDA/TSLA에선 오표기 → 코드 수정 후 NVDA/TSLA 영상 재렌더로 검증.

### 남은 sector-specific 표현(경미)
- `sympathy_insight`의 mixed 케이스 문구가 "selective **AI-PC** exposure"로 반도체 한정. 비반도체 섹터엔 부정확 가능 → ctx["sector"] 기반 일반화 후속 권장(현재 반도체 집중이라 영향 없음).
- thumbnail 띠 문구는 pct 부호 기반 일반(티커 무관).

## 결론
- catalyst.type 분기(hook 톤/thumbnail layout), verdict 임계값, 시점일관성, 피어 폴백 모두 **티커 무관 작동**.
- ARM-specific 하드코딩 3건 발견·수정. 비반도체 sympathy 문구 1건 경미(후속).
