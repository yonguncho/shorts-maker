"""stage04 — ④ 대본/자막 작성 (Producer).

입력 : state/topic.json                 (stage03 산출 — 선정 소재)
       state/verified_market_data.json  (stage01 — 가격 등 보조 사실)
산출물: state/script.json                (타임코드 자막 비트 + 차트큐 + 출처)
        state/script.md                  (사람 검토용)

사양(사용자 확정 2026-06-01):
  - 길이 45초 표준 · 톤 중립·사실형(뉴스 자막체) · 구성 훅→데이터→맥락→클로저
  - 무음 + BGM + 영어자막 + 차트중심 → '대본'은 곧 화면 자막 비트(나레이션 없음).

설계 원칙(stage01~03 동일 계열):
  - **결정론적 조립**: topic/claim 의 사실에서 비트를 구성하고 가중치로 타임코드를 배분(재현 가능).
  - **출처 필수**: 모든 데이터 비트에 cite 를 단다(무출처 사실 진술 0).
  - **환각/권유 차단**: 자막 텍스트(파이프라인 조립)에 투자권유·예측 표현 누출 시 단계 실패
    (stage02 ADVICE_RE 재사용). 면책 클로저는 정적 문구.

실행: .venv/bin/python -m src.stages.stage04_script_writing
"""
from __future__ import annotations

from ..common import read_json, write_json_atomic, log, utc_now, today_utc, STATE_DIR
from .stage02_analysis_report import ADVICE_RE, INDEX_PROXY, _price, _pct

TOPIC_PATH = STATE_DIR / "topic.json"
DATA_PATH = STATE_DIR / "verified_market_data.json"
OUT_JSON = STATE_DIR / "script.json"
OUT_MD = STATE_DIR / "script.md"

TARGET_SEC = 45.0
SUBTITLE_MAX_CHARS = 90          # 세로 쇼츠 가독성 상한(초과 시 경고)
DISCLAIMER = "Source-verified market data. Educational commentary, not investment advice."


def _by_ticker(data: dict) -> dict:
    return {q["ticker"]: q for q in data.get("market_snapshot", []) if q.get("ticker")}


def _ctx_phrase(tp: dict) -> str:
    """맥락 토킹포인트 → 자막 문구(중립). 지수 해설은 그대로, 단일 종목 수치는 'Also:' 접두."""
    text = (tp.get("text") or "").strip()
    if tp.get("from") == "movers":
        return f"Also: {text}"
    return text


def _ctx_chart(tp: dict, by_ticker: dict) -> dict:
    if tp.get("from") == "movers":
        sym = (tp.get("text") or "").split()[:1]
        return {"type": "single_quote", "symbols": sym}
    # themes(지수) → 지수 패널
    return {"type": "index_panel", "symbols": [s for s in INDEX_PROXY if s in by_ticker]}


MAX_BEAT_SEC = 3.0   # 슬라이드당 상한(사용자 요청). 45s 안에 ≥15비트 → 각 ≤3s.


def _focus_history(data: dict, sym: str) -> dict:
    for h in data.get("price_history", []):
        if h.get("ticker") == sym:
            return h
    return {}


def _dense_issue_beats(topic: dict, data: dict) -> list[dict]:
    """이슈무버 전용 고밀도 비트(~15+). 각 균등 가중치 → 슬라이드당 ≤3초.
    fact_match 안전: 부호 %는 해당 종목 당일 변동에만, $는 종가에만. 3개월 변동 등은 부호 없는 %/텍스트."""
    by_ticker = _by_ticker(data)
    sym = topic.get("focus_symbol")
    primary_chart = topic.get("chart", {"type": "price_line", "symbols": [sym]})
    primary_cite = (topic.get("primary_fact") or {}).get("cite", "")
    th = topic.get("theme") or {}
    co = topic.get("co_movers") or []
    rel = topic.get("related") or {}
    vol = topic.get("volatility") or {}
    why = topic.get("why_now") or {}
    ph = _focus_history(data, sym)

    co_syms = [sym] + [c["ticker"] for c in co[:5]]
    co_chart = {"type": "co_movers", "symbols": co_syms} if co else primary_chart
    theme_chart = ({"type": "co_movers", "symbols": [m["ticker"] for m in th.get("top_movers", [])[:5]]}
                   if th.get("top_movers") else primary_chart)
    corr_chart = ({"type": "correlation", "symbols": [sym] + [p["peer"] for p in rel.get("peers", [])[:4]]}
                  if rel.get("peers") else primary_chart)

    B = []   # (section, subtitle, chart_cue, source, quote)
    # 1) 뉴스(이슈) 먼저 — 실제 기사 화면 캡처를 배경으로(신뢰성↑), 헤드라인은 verbatim 인용
    article_cue = ({"type": "article_shot", "url": why["url"], "symbols": [sym]}
                   if (why.get("url") and why.get("scraped")) else primary_chart)
    if why.get("headline"):
        B.append(("hook", f"“{why['headline']}” — {why.get('source', 'source')}",
                  article_cue, why.get("cite", ""), True))
    else:
        B.append(("hook", f"Why {sym} is on the move today.", primary_chart, primary_cite, False))
    # 2) 기사 발췌(실제 publisher 스크랩, 실패 시 Finnhub 요약) — verbatim 인용
    if why.get("summary"):
        B.append(("context", why["summary"], primary_chart, why.get("cite", ""), True))
    # 3) 오늘 가장 뜨거운 테마
    if th.get("name"):
        B.append(("context", f"Today's hottest theme: {th['name']} — "
                  f"{th.get('up')} of {th.get('n_present')} names higher.",
                  theme_chart, th.get("cite", ""), False))
    # 4) 관련 종목 변동(사실)
    B.append(("data", topic.get("angle", ""), primary_chart, primary_cite, False))
    price = _price(by_ticker.get(sym, {})) if sym in by_ticker else None
    if price is not None:
        B.append(("data", f"{sym} last traded near ${price:g}.", primary_chart, primary_cite, False))
    chg3m = ph.get("period_change_pct")
    if chg3m is not None:
        B.append(("context", f"{sym} is {'up' if chg3m >= 0 else 'down'} about "
                  f"{abs(chg3m):.0f}% over the past three months.",   # 부호없는 % → fact_match 안전
                  primary_chart, "[computed] yfinance 3-month price history", False))
    if vol.get("realized_vol_pct") is not None:
        B.append(("context", f"{sym}'s 3-month realized volatility is about "
                  f"{vol['realized_vol_pct']:.0f}% annualized.", primary_chart, vol.get("cite", ""), False))
    # 동반상승 — 종목별 개별 슬라이드(빠른 플래시). 부호% = 해당 종목 당일변동 → 안전.
    for c in co[:5]:
        B.append(("context", f"{c['ticker']} moved with it, {c['pct']:+.2f}%.",
                  co_chart, c.get("cite", ""), False))
    # 레버리지 ETF(있으면)
    for lv in (topic.get("leveraged") or [])[:2]:
        B.append(("context", f"{lv['ticker']}, a 2x {sym} ETF, moved {lv['pct']:+.2f}% today.",
                  primary_chart, lv.get("cite", ""), False))
    # 테마 내 역행 종목(대비) — 가장 큰 하락
    downs = sorted([m for m in th.get("top_movers", []) if m.get("pct", 0) < 0],
                   key=lambda m: m["pct"])
    if downs:
        lg = downs[0]
        B.append(("context", f"Not all higher — {lg['ticker']} {lg['pct']:+.2f}%.",
                  theme_chart, th.get("cite", ""), False))
    if rel.get("peers"):
        peers = rel["peers"][:4]
        names = (", ".join(p["peer"] for p in peers[:-1]) + f" and {peers[-1]['peer']}"
                 if len(peers) > 1 else peers[0]["peer"])
        B.append(("related", f"{sym} has historically tracked {names}.", corr_chart, rel.get("cite", ""), False))
    if th.get("others"):
        B.append(("context", f"Also active today: {', '.join(th['others'][:2])}.",
                  primary_chart, th.get("cite", ""), False))
    # 시장 전반(지수) 토킹포인트
    for tp in (topic.get("talking_points") or []):
        if tp.get("from") == "themes":
            B.append(("context", _ctx_phrase(tp), _ctx_chart(tp, by_ticker), tp.get("cite", ""), False))
            break
    B.append(("closer", DISCLAIMER, None, "", False))

    return [{"section": s, "weight": 1.0, "subtitle": sub, "chart_cue": cue,
             "source": src, "quote": q} for (s, sub, cue, src, q) in B]


def build_beats(topic: dict, data: dict) -> list[dict]:
    """가중치 부여한 비트(섹션·자막·차트큐·출처) 목록. 타임코드는 이후 배분.
    이슈무버는 고밀도(≤3s/슬라이드) 전용 빌더 사용."""
    if topic.get("kind") == "issue_mover" and topic.get("focus_symbol"):
        return _dense_issue_beats(topic, data)
    by_ticker = _by_ticker(data)
    primary_chart = topic.get("chart", {"type": "index_panel", "symbols": list(INDEX_PROXY)})
    primary_cite = (topic.get("primary_fact") or {}).get("cite", "")
    sym = topic.get("focus_symbol")
    kind = topic.get("kind")

    raw = []
    # 페이싱: 이슈무버는 비트를 많이·짧게(슬라이드 빠르게). 가중치를 낮게 균등 배분.
    # ── HOOK ──
    if kind == "issue_mover" and sym:
        hook = f"Why {sym} is on the move today."
    elif kind == "single_mover" and sym:
        hook = f"Today's standout megacap move: {sym}."
    else:
        hook = "Where US markets landed today."
    raw.append({"section": "hook", "weight": 0.9, "subtitle": hook,
                "chart_cue": primary_chart, "source": primary_cite})

    # ── THEME (오늘 가장 뜨거운 섹터 — 최신 트렌드 반영, 사실: 뉴스건수+상승종목수) ──
    th = topic.get("theme") if kind == "issue_mover" else None
    if th and th.get("top_movers"):
        tm = th["top_movers"][:5]
        raw.append({"section": "context", "weight": 1.2,
                    "subtitle": f"Today's hottest theme: {th['name']} — "
                                f"{th['up']} of {th['n_present']} names higher.",
                    "chart_cue": {"type": "co_movers", "symbols": [m["ticker"] for m in tm]},
                    "source": th.get("cite", "")})

    # ── DATA (변동 사실) ──
    raw.append({"section": "data", "weight": 1.3, "subtitle": topic.get("angle", ""),
                "chart_cue": primary_chart, "source": primary_cite})

    # ── WHY NOW (이슈무버: 변동을 설명하는 뉴스 헤드라인 verbatim 인용) ──
    why = topic.get("why_now") if kind == "issue_mover" else None
    if why and why.get("headline"):
        raw.append({"section": "why_now", "weight": 1.5, "quote": True,
                    "subtitle": f"“{why['headline']}” — {why.get('source', 'source')}",
                    "chart_cue": primary_chart, "source": why.get("cite", "")})

    # ── CO-MOVERS (오늘 같이 움직인 생태계 종목 — 눈길끄는 당일 데이터) ──
    co = topic.get("co_movers") if kind == "issue_mover" else None
    if co:
        cm = co[:4]
        names = ", ".join(f"{c['ticker']} {c['pct']:+.2f}%" for c in cm)
        # 포커스 티커({sym})를 자막에 넣지 않는다 — fact_match 가 맨 앞 티커를 첫 수치에 오결속함.
        # NVDA 와의 연결 맥락은 co_movers 차트 제목("Moving with NVDA today")이 제공.
        raw.append({"section": "context", "weight": 1.5,
                    "subtitle": f"Co-movers today: {names}.",
                    "chart_cue": {"type": "co_movers",
                                  "symbols": [sym] + [c["ticker"] for c in cm]},
                    "source": cm[0].get("cite", "")})

    # ── LEVERAGED ETF (해당 종목 ±2배 추종 — 증폭된 당일 변동) ──
    lev = topic.get("leveraged") if kind == "issue_mover" else None
    if lev:
        if len(lev) == 1:
            lev_txt = f"{lev[0]['ticker']}, a 2x {sym} ETF, moved {lev[0]['pct']:+.2f}% today."
        else:
            lev_txt = (f"{lev[0]['ticker']} {lev[0]['pct']:+.2f}% and "
                       f"{lev[1]['ticker']} {lev[1]['pct']:+.2f}% — 2x {sym} ETFs today.")
        raw.append({"section": "context", "weight": 1.1, "subtitle": lev_txt,
                    "chart_cue": primary_chart, "source": lev[0].get("cite", "")})

    # ── RELATED (연관종목: 계산된 상관관계 사실 — 생태계 기준) ──
    rel = topic.get("related") if kind == "issue_mover" else None
    if rel and rel.get("peers"):
        peers = rel["peers"][:4]
        if len(peers) > 1:
            peer_names = ", ".join(p["peer"] for p in peers[:-1]) + f" and {peers[-1]['peer']}"
        else:
            peer_names = peers[0]["peer"]
        raw.append({"section": "related", "weight": 1.2,
                    "subtitle": f"{sym} has historically tracked {peer_names}.",
                    "chart_cue": {"type": "correlation",
                                  "symbols": [sym] + [p["peer"] for p in peers]},
                    "source": rel.get("cite", "")})

    # ── THEME (P4: 뉴스에서 명시·검증된 연관기업, 공급망/경쟁 관계) ──
    theme = topic.get("theme_links") if kind == "issue_mover" else None
    if theme:
        tl = theme[:2]
        names = ", ".join(f"{t['ticker']} ({t['relation']})" for t in tl)
        raw.append({"section": "context", "weight": 1.2,
                    "subtitle": f"Names tied to {sym} in today's coverage: {names}.",
                    "chart_cue": primary_chart, "source": tl[0].get("cite", "")})

    # ── VOLATILITY (이슈무버: 연율 실현변동성, 계산된 사실) ──
    vol = topic.get("volatility") if kind == "issue_mover" else None
    if vol and vol.get("realized_vol_pct") is not None:
        raw.append({"section": "context", "weight": 0.9,
                    "subtitle": f"{sym}'s 3-month realized volatility is about "
                                f"{vol['realized_vol_pct']:.0f}% annualized.",
                    "chart_cue": primary_chart, "source": vol.get("cite", "")})
    elif sym and sym in by_ticker:
        price = _price(by_ticker[sym])
        if price is not None:
            raw.append({"section": "data", "weight": 1.0,
                        "subtitle": f"{sym} last traded near ${price:g}.",
                        "chart_cue": primary_chart, "source": primary_cite})

    # ── CONTEXT (토킹포인트) — 이슈무버는 데이터가 풍부하므로 생략, 그 외 2개 ──
    ctx_max = 0 if (kind == "issue_mover" and co) else (1 if kind == "issue_mover" else 2)
    for tp in (topic.get("talking_points") or [])[:ctx_max]:
        raw.append({"section": "context", "weight": 1.1, "subtitle": _ctx_phrase(tp),
                    "chart_cue": _ctx_chart(tp, by_ticker), "source": tp.get("cite", "")})

    # ── CLOSER (정적 면책) ──
    raw.append({"section": "closer", "weight": 1.0, "subtitle": DISCLAIMER,
                "chart_cue": None, "source": ""})
    return raw


def assign_timecodes(raw: list[dict], target: float = TARGET_SEC) -> list[dict]:
    """누적 경계 반올림으로 duration 배분 — 각 비트가 가중치 몫에 가깝고(잔여를 마지막에 몰지 않음),
    합계는 정확히 target. 균등 가중치 + 충분한 비트수면 각 슬라이드가 ≤ target/N 초가 된다."""
    total_w = sum(b["weight"] for b in raw) or 1.0
    beats, prev_end, cum_w = [], 0.0, 0.0
    for i, b in enumerate(raw):
        cum_w += b["weight"]
        t_end = round(target, 1) if i == len(raw) - 1 else round(cum_w / total_w * target, 1)
        dur = round(t_end - prev_end, 1)
        beats.append({"idx": i + 1, "section": b["section"],
                      "t_start": round(prev_end, 1), "t_end": t_end,
                      "duration_sec": dur, "subtitle": b["subtitle"],
                      "chart_cue": b["chart_cue"], "source": b["source"],
                      "quote": bool(b.get("quote"))})
        prev_end = t_end
    return beats


def guardrail_violations(beats: list[dict]) -> list[str]:
    """파이프라인이 조립한 자막 텍스트의 투자권유/예측 표현 검출.
    정적 면책 클로저(DISCLAIMER)와 제3자 verbatim 인용(quote=True, 출처표기된 헤드라인)은 제외 —
    인용은 '보도'이지 파이프라인의 주장이 아니며, stage02/03 와 동일한 인용 제외 원칙."""
    bad = []
    for b in beats:
        text = b.get("subtitle", "") or ""
        if text == DISCLAIMER or b.get("quote"):
            continue
        for m in ADVICE_RE.finditer(text):
            bad.append(f"{m.group(0)!r} :: [beat{b['idx']}/{b['section']}] {text[:80]}")
    return bad


def render_md(beats: list[dict], topic: dict, date: str) -> str:
    L = [f"# Shorts script — {date}  ({TARGET_SEC:g}s, neutral-factual)",
         f"_Topic: {topic.get('id')} ({topic.get('kind')}) · focus={topic.get('focus_symbol') or '-'}_", ""]
    for b in beats:
        cue = b["chart_cue"]
        cue_s = f"{cue['type']}:{','.join(cue['symbols'])}" if cue else "(none)"
        L.append(f"### [{b['t_start']:.1f}–{b['t_end']:.1f}s] {b['section'].upper()}")
        L.append(f"> {b['subtitle']}")
        L.append(f"_chart: {cue_s}_" + (f" · _src: {b['source']}_" if b["source"] else ""))
        L.append("")
    return "\n".join(L)


def main() -> int:
    log("INFO", "=== STAGE ④ 대본/자막 작성 시작 ===", "stage04")
    topic_doc = read_json(TOPIC_PATH, default=None)
    if not topic_doc or not topic_doc.get("topic"):
        log("ERROR", f"입력 없음/소재 없음: {TOPIC_PATH} (stage03 먼저 실행 필요)", "stage04")
        return 2
    data = read_json(DATA_PATH, default={}) or {}
    topic = topic_doc["topic"]

    raw = build_beats(topic, data)
    beats = assign_timecodes(raw)

    # 가독성 경고(실패 아님)
    longs = [b["idx"] for b in beats if len(b["subtitle"]) > SUBTITLE_MAX_CHARS]
    if longs:
        log("WARN", f"자막 길이 {SUBTITLE_MAX_CHARS}자 초과 비트 {longs} — 렌더 시 줄바꿈 필요", "stage04")

    violations = guardrail_violations(beats)
    if violations:
        log("ERROR", f"가드레일 위반(투자권유/예측 표현) {len(violations)}건 — 단계 실패: "
                     f"{violations[:3]}", "stage04")
        return 4

    date = topic_doc.get("date") or today_utc()
    total = round(sum(b["duration_sec"] for b in beats), 1)
    # Editor 가 쓸 차트 계획 요약(중복 제거)
    chart_plan = []
    for b in beats:
        c = b["chart_cue"]
        if c and c not in chart_plan:
            chart_plan.append(c)

    out = {
        "schema_version": "1.0", "pipeline_id": "shorts_maker", "machine": "mac",
        "stage": 4, "agent": "Producer", "generated_utc": utc_now(), "date": date,
        "source_files": [TOPIC_PATH.name, DATA_PATH.name],
        "spec": {"duration_sec": TARGET_SEC, "tone": "neutral_factual",
                 "template": "hook-data-context-closer", "subtitle_max_chars": SUBTITLE_MAX_CHARS,
                 "audio": "silent+bgm", "subtitle_lang": "en"},
        "topic_id": topic.get("id"), "focus_symbol": topic.get("focus_symbol"),
        "chart_plan": chart_plan, "beats": beats, "total_duration_sec": total,
        "guardrail": {"advice_violations": 0},
    }
    write_json_atomic(OUT_JSON, out)
    OUT_MD.write_text(render_md(beats, topic, date), encoding="utf-8")
    log("INFO", f"=== STAGE ④ 완료: beats={len(beats)} total={total}s "
                f"charts={len(chart_plan)} script=script.json/.md ===", "stage04")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
