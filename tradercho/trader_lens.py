"""trader_lens.py — 트레이더 렌즈 추출 (Phase 3-2).

기사 + price_json → catalyst/surprise/volume/chart/smart_money/related/risk/hook_seed/payoff JSON.
헤징 언어 강제, 단정 표현 금지, risk 필수(L2.5), 실존 인물명 추출 금지.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import llm

PROMPT = """You are a sharp US-equity trader, not a news summarizer. Extract ONLY what a trader would act on.

TICKER: {{TICKER}}
PRICE DATA (yfinance, real): {{PRICE}}
ARTICLE: {{ARTICLE}}
{{ANALYST_BLOCK}}{{SEC_BLOCK}}{{FINVIZ_BLOCK}}
Rules:
- Use ONLY the article and price data. Do not invent numbers.
- Use hedged language ("likely", "appears", "could", "may"). NEVER assert "will rise", "guaranteed", "must buy".
- Do NOT name real people (no CEO/executive/politician names). Refer to companies, not individuals.
- "risk" is MANDATORY — always include one honest caution.
- hook_seed must be a QUESTION in English (raw; it will be refined later).

Output strict JSON only, on the final line after the marker ===JSON===:
{
  "ticker": "",
  "catalyst": {"type": "earnings_beat|guidance_raise|analyst_action|product|macro|sympathy", "durability": "DURABLE|TEMPORARY", "why": ""},
  "surprise": "",
  "volume": {"vs_avg": "", "verdict": "conviction|suspect"},
  "chart": {"position": "", "rsi_note": "", "too_late_read": ""},
  "smart_money": "",
  "related": [{"ticker": "", "tag": "", "lagged": true}],
  "risk": "",
  "hook_seed": "",
  "payoff_line": ""
}
hook_seed < 12 words, question form. payoff_line answers it. Valid single-line JSON after ===JSON===."""


def _analyst_block(analyst: dict | None) -> str:
    """analyst dict → 프롬프트 삽입용 텍스트 블록."""
    if not analyst:
        return ""
    lines = ["ANALYST CONSENSUS (yfinance):"]
    cons = analyst.get("consensus", {})
    if cons:
        total = sum(cons.get(k, 0) for k in ("strong_buy", "buy", "hold", "sell", "strong_sell"))
        lines.append(
            f"  Ratings: StrongBuy={cons.get('strong_buy',0)} Buy={cons.get('buy',0)} "
            f"Hold={cons.get('hold',0)} Sell={cons.get('sell',0)} StrongSell={cons.get('strong_sell',0)} "
            f"(total={total})"
        )
    pt = analyst.get("price_targets", {})
    if pt:
        lines.append(f"  Price targets: " + "  ".join(f"{k}={v}" for k, v in pt.items()))
    ne = analyst.get("next_earnings")
    if ne:
        lines.append(f"  Next earnings: {ne}")
    return "\n".join(lines) + "\n"


def _sec_block(sec: dict | None) -> str:
    """sec_8k dict → 프롬프트 삽입용 텍스트 블록."""
    if not sec or not sec.get("has_8k"):
        return ""
    filings = sec.get("filings", [])
    if not filings:
        return ""
    lines = [f"SEC 8-K FILINGS TODAY ({sec.get('as_of', '')}):"]
    for f in filings[:3]:
        lines.append(f"  - {f.get('title','')} ({f.get('filed_at','')})")
        if f.get("description"):
            lines.append(f"    {f['description'][:120]}")
    return "\n".join(lines) + "\n"


def _finviz_block(headlines: list | None) -> str:
    """Finviz 헤드라인 리스트 → 프롬프트 삽입용 텍스트 블록."""
    if not headlines:
        return ""
    lines = ["FINVIZ RECENT HEADLINES:"]
    for h in headlines[:5]:
        lines.append(f"  - [{h.get('date','')}] {h.get('title','')} ({h.get('source','')})")
    return "\n".join(lines) + "\n"


def extract(ticker: str, article_text: str, price_json: dict,
            analyst: dict | None = None,
            sec8k: dict | None = None,
            finviz_headlines: list | None = None) -> tuple[dict, str]:
    pj = {k: v for k, v in price_json.items() if k not in ("series_3m", "warnings")}
    analyst_b = _analyst_block(analyst or price_json.get("analyst"))
    sec_b = _sec_block(sec8k)
    finviz_b = _finviz_block(finviz_headlines)
    prompt = (PROMPT.replace("{{TICKER}}", ticker.upper())
                    .replace("{{PRICE}}", json.dumps(pj))
                    .replace("{{ARTICLE}}", (article_text or "")[:2500])
                    .replace("{{ANALYST_BLOCK}}", analyst_b)
                    .replace("{{SEC_BLOCK}}", sec_b)
                    .replace("{{FINVIZ_BLOCK}}", finviz_b))
    data, engine = llm.call_json(prompt)
    if not data:
        raise RuntimeError(f"trader_lens: LLM 추출 실패(engine={engine})")
    data.setdefault("ticker", ticker.upper())
    if not (data.get("risk") or "").strip():
        raise ValueError("trader_lens: risk 필드 비어있음 — L2.5 위반(리스크 의무)")
    # L2.7: 거래량 판정은 임계값 기반 자동 — LLM 라벨 신뢰 금지(하드코딩/환각 방지).
    data["volume"] = volume_verdict(price_json.get("vol_vs_avg"), data.get("volume"))
    return data, engine


def fetch_related_changes(related, data_date, limit=5):
    """related[] 각 티커의 당일 등락% + as_of 조회(실데이터). ARM 거래일(data_date)과
    같은 날만 same_day=True. 시점 섞임 방지(P0.2). 반환 list[dict]."""
    import data_fetch
    out = []
    for r in (related or [])[:limit]:
        tk = r.get("ticker")
        if not tk:
            continue
        try:
            pj = data_fetch.fetch(tk)
            asof = str(pj.get("as_of", ""))[:10]
            out.append({"ticker": tk, "pct_change": pj.get("pct_change"), "as_of": asof,
                        "same_day": bool(asof == data_date), "tag": r.get("tag"),
                        "lagged": r.get("lagged")})
        except Exception as e:
            out.append({"ticker": tk, "pct_change": None, "as_of": None,
                        "same_day": False, "error": str(e)})
    return out


def sympathy_insight(arm_pct, peer_pcts):
    """섹터 동조 패턴 1줄 해석(≤12단어, 사실 관찰·매수매도 없음). peer_pcts: list[float]."""
    import statistics
    peers = [p for p in (peer_pcts or []) if p is not None]
    if not peers:
        return ""
    n = len(peers)
    peer_up = [p for p in peers if p > 0]
    same_dir = sum(1 for p in peers if (p > 0) == (arm_pct > 0))
    if same_dir / n >= 0.7:
        return "Sector moving in sync — broad AI bid" if arm_pct > 0 \
            else "Sector-wide pullback, not ARM-specific"
    if arm_pct < 0 and len(peer_up) >= n * 0.6:
        return "ARM lagging peers despite shared catalyst"
    if arm_pct > 0 and peers and arm_pct < statistics.median([abs(p) for p in peers]) * 0.6:
        return "ARM trailing the sector sympathy move"
    return "Mixed reaction — selective AI-PC exposure"


def volume_verdict(vs_avg, existing=None):
    """vol_vs_avg → {vs_avg, verdict} 임계값 판정. 1.5×↑=conviction / 1.0~1.5×=neutral / <1.0×=suspect."""
    out = dict(existing or {})
    if vs_avg is None:
        out.setdefault("verdict", "neutral")
        return out
    v = float(vs_avg)
    out["vs_avg"] = f"{v:.2f}x"
    out["verdict"] = "conviction" if v >= 1.5 else ("neutral" if v >= 1.0 else "suspect")
    return out


if __name__ == "__main__":
    import data_fetch
    tk = sys.argv[1] if len(sys.argv) > 1 else "ARM"
    art = Path(sys.argv[2]).read_text() if len(sys.argv) > 2 else "Sample article."
    pj = data_fetch.fetch(tk)
    d, eng = extract(tk, art, pj)
    print(f"engine={eng}")
    print(json.dumps(d, indent=2, ensure_ascii=False))
