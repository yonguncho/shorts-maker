"""trader_analysis.py — '트레이더 관점' 행동가능 포인트 추출 (사용자 제공 프롬프트, R14).

기사 텍스트 + 가격지표(RSI/거래량/52주고저/변동)를 codex/claude 에 던져,
catalyst(durability)·surprise·volume·chart(too_late)·smart_money·related(tag+lagged)·risk
·hook_line·payoff_line 를 strict JSON 으로 추출한다. 이 JSON 이 영상 씬(훅/왜올랐나/리스크/관계태그/페이오프)을 구동.
LLM 불가/파싱실패 시 보유 데이터로 최소 분석을 구성(fail-soft) — 영상은 계속 만들어진다.
"""
from __future__ import annotations
import json
import re

from .common import log
from .theme_graph import _llm   # codex→claude 폴백 호출기

# 사용자 제공 프롬프트(원문 유지). {{TICKER}}/{{ARTICLE}}/{{PRICE}} 만 치환.
PROMPT = """You are a sharp equity trader, not a news summarizer. Extract ONLY the points
that a trader would actually act on. Skip generic facts (e.g. "the stock rose").

INPUT:
- Ticker: {{TICKER}}
- Article text: {{ARTICLE}}
- Price data (from yfinance/Finnhub): {{PRICE}}
  (last close, % change, volume vs avg, 52w high/low, RSI)

EXTRACT these, in priority order. Omit any field with no real signal:

1. CATALYST TYPE — why it moved, and classify durability:
   - "earnings_beat" / "guidance_raise" -> fundamental, trend-capable
   - "analyst_action" (upgrade/PT raise — name the firm + new target)
   - "product_news" / "deal" / "contract"
   - "macro" / "sector_sympathy" / "momentum" -> often temporary, fade risk
   Label each as DURABLE or TEMPORARY with a one-line reason.

2. THE SURPRISE — what's counterintuitive or what consensus missed:
   - Beat on EPS but guided down? Rallied but on weak volume?
   - Any conflicting signal (e.g. stock up, insiders selling).
   This is the most valuable point. Always look for it.

3. VOLUME CONFIRMATION — did it move on real volume?
   - Volume vs 30d avg. High volume = conviction; low = suspect.

4. POSITION ON THE CHART:
   - Near/above 52w high (breakout) or recovering off lows?
   - RSI overbought (>70)? How many up days in a row?
   - Answer the viewer's real question: "Am I too late?"

5. WHO'S BETTING — institutional / options signals if present.

6. RELATED PLAYS — same value chain, NOT yet moved (highest viewer value):
   - For each: ticker + one-word relationship tag
     (e.g. ASML="equipment", TSM="foundry", AMD="competitor",
      MRVL="custom_silicon", MU="memory").
   - Flag which ones lagged today (catch-up candidates).

7. RISK — one honest caution (overheated, guidance unconfirmed,
   single-customer concentration, etc.). Always include one.

OUTPUT strict JSON only, no prose, on the final line after the marker ===JSON===:
{
  "ticker": "",
  "catalyst": {"type": "", "durability": "DURABLE|TEMPORARY", "why": ""},
  "surprise": "",
  "volume": {"vs_avg": "", "verdict": "conviction|suspect"},
  "chart": {"position": "", "rsi_note": "", "too_late_read": ""},
  "smart_money": "",
  "related": [{"ticker": "", "tag": "", "lagged": true}],
  "risk": "",
  "hook_line": "",
  "payoff_line": ""
}
Rules: hook_line < 12 words, scroll-stopping. payoff_line = the "real" takeaway revealed at the end.
Use ONLY the provided article/price data; do not invent numbers. Output valid single-line JSON after ===JSON===."""


def build_price_json(focus: str, data: dict) -> dict:
    """market_snapshot + price_history 에서 트레이더 가격입력 구성."""
    snap = {q["ticker"]: q for q in data.get("market_snapshot", []) if q.get("ticker")}
    hist = {h["ticker"]: h for h in data.get("price_history", []) if h.get("ticker")}
    q = snap.get(focus, {}); h = hist.get(focus, {})
    c = q.get("content", "") or ""
    def num(field):
        m = re.search(field + r"=([-\d.]+)", c)
        return float(m.group(1)) if m else None
    return {
        "last_close": num("price"), "pct_change_today": num("pct"),
        "rsi14": h.get("rsi14"), "vol_vs_30d_avg": h.get("vol_vs_30d_avg"),
        "high_52w": h.get("high_52w"), "low_52w": h.get("low_52w"),
        "pct_off_52w_high": h.get("pct_off_52w_high"),
        "change_3m_pct": h.get("period_change_pct"),
        "realized_vol_pct": h.get("realized_vol_pct"),
    }


def _parse_json(out: str) -> dict | None:
    if not out:
        return None
    tail = out.split("===JSON===", 1)[1] if "===JSON===" in out else out
    # 가장 바깥 균형 중괄호 추출
    start = tail.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(tail)):
        if tail[i] == "{":
            depth += 1
        elif tail[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(tail[start:i+1])
                except json.JSONDecodeError:
                    return None
    return None


def _fallback(focus: str, data: dict, why: dict, related_peers: list, price_json: dict) -> dict:
    """LLM 불가 시 보유 데이터로 최소 분석(영상 비차단)."""
    rsi = price_json.get("rsi14")
    pct = price_json.get("pct_change_today")
    off_high = price_json.get("pct_off_52w_high")
    too_late = "Near 52-week highs — extended." if (off_high is not None and off_high > -5) \
        else "Off its highs — not at the top yet."
    return {
        "ticker": focus,
        "catalyst": {"type": "product_news", "durability": "TEMPORARY",
                     "why": (why.get("headline") or "news-driven move")[:120]},
        "surprise": "",
        "volume": {"vs_avg": (f"{price_json.get('vol_vs_30d_avg')}x" if price_json.get("vol_vs_30d_avg") else ""),
                   "verdict": "conviction" if (price_json.get("vol_vs_30d_avg") or 0) >= 1.3 else "suspect"},
        "chart": {"position": (f"{off_high:+.0f}% from 52w high" if off_high is not None else ""),
                  "rsi_note": (f"RSI {rsi}{' (overbought)' if rsi and rsi>70 else ''}" if rsi else ""),
                  "too_late_read": too_late},
        "smart_money": "",
        "related": [{"ticker": p.get("peer"), "tag": "peer", "lagged": False} for p in related_peers[:4]],
        "risk": ("Sharp single-day spike — short-term overextension risk; catalyst may already be priced in."),
        "hook_line": (f"{focus} just ripped {pct:+.0f}% — here's the real read" if pct else f"What's really moving {focus}"),
        "payoff_line": "The move is news-driven — watch whether volume and follow-through confirm it.",
        "_source": "fallback(no-LLM)",
    }


def analyze(focus: str, data: dict, why: dict, related_peers: list) -> dict:
    """트레이더 분석 JSON 추출. why=topic.why_now, related_peers=topic.related.peers."""
    price_json = build_price_json(focus, data)
    article_text = ((why.get("headline") or "") + ". " + (why.get("summary") or "")).strip()[:1200]
    if not article_text:
        article_text = f"{focus} made a notable move today."
    prompt = (PROMPT.replace("{{TICKER}}", focus)
                    .replace("{{ARTICLE}}", article_text)
                    .replace("{{PRICE}}", json.dumps(price_json)))
    out, engine = _llm(prompt)
    parsed = _parse_json(out or "")
    if not parsed:
        log("WARN", f"trader_analysis: LLM 추출 실패({engine}) → fallback", "trader")
        return _fallback(focus, data, why, related_peers, price_json)
    parsed["_source"] = engine
    parsed.setdefault("ticker", focus)
    log("INFO", f"trader_analysis[{focus}]: hook=\"{parsed.get('hook_line','')[:50]}\" "
                f"catalyst={parsed.get('catalyst',{}).get('type')} engine={engine}", "trader")
    return parsed
