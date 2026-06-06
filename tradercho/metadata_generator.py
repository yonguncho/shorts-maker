"""metadata_generator.py — YouTube Shorts 게시용 메타데이터 (텍스트 전용).

입력: outputs/{ticker}_{date}/ (trader_lens.json + hook.json + price.json)
출력: 같은 폴더에 metadata.md (제목3 / 설명 / 해시태그 / 태그 / 엔드스크린 / 고정댓글).
규칙: 제목 ≤100자·ALL CAPS 금지·이모지 0, 설명 첫 줄 검색 키워드, #shorts 필수,
      거래량 verdict 등 정직성 수치 노출(L2 신뢰성). 게시는 하지 않음(안전 정지점).
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import assets as A

ROOT = Path(__file__).resolve().parent.parent

# 기사 출처(샘플). 실제 게시 시 기사 메타로 교체.
NEWS_SOURCE = {"ARM": "247wallst.com"}
SECTOR_TAGS = {"semiconductor": ["#semiconductor", "#aichips", "#chipstocks", "#ai"],
               "automotive": ["#EV", "#electricvehicles", "#autostocks"],
               "tech": ["#tech", "#technology", "#bigtech"]}
CATALYST_TAG = {"earnings_beat": "#earnings", "guidance_raise": "#guidance",
                "analyst_action": "#analystratings", "product": "#productlaunch",
                "macro": "#macro", "sympathy": "#sectorrotation"}


def _company(tk):
    return A.TICKER_WIKI.get(tk, (tk, None))[0]


def _company_tag(tk):
    return "#" + _company(tk).replace(",", "").replace(".", "").replace(" ", "")


def _dir_word(pct):
    return ("popped" if pct >= 5 else "rose") if pct >= 0 else ("slid" if pct > -5 else "tumbled")


# 채널 시그니처: 제목 3후보 모두 의문형(P1.1). 이벤트/데이터/대비 앵커.
T2_PHRASE = {"guidance_raise": "a beat-and-raise", "earnings_beat": "the earnings beat",
             "analyst_action": "an analyst call", "product": "the product news",
             "macro": "the macro move", "sympathy": "the sector move"}
T3_LEAD = {"guidance_raise": "Raised guidance", "earnings_beat": "An earnings beat",
           "analyst_action": "An analyst PT move", "product": "A product catalyst",
           "macro": "A macro move", "sympathy": "A sector move"}
ADVISORY_SUB = [
    (r"(?i)\bpossibly tradable,?\s*but\b", "The setup looks mixed —"),
    (r"(?i)\btradable\b", "worth watching"),
    (r"(?i)\bmakes the (\w+) signal look suspect\b", r"weakens the \1 signal"),
    (r"(?i)\b(must|should)\s+(buy|sell)\b", "is one to watch"),
    (r"(?i)\bbuy the dip\b", "the pullback"),
]


def _sanitize(text):
    """매수/매도 함의어 → 관찰 톤(P1.2). L0.3 단정 금지 보완."""
    import re
    t = text or ""
    for pat, rep in ADVISORY_SUB:
        t = re.sub(pat, rep, t)
    return t.strip()


def _titles(tk, pct, cat, hook_line):
    """3 후보 모두 의문형(채널 시그니처). ≤100자, ALL CAPS·이모지 없음."""
    p = f"{abs(pct):.1f}%"
    d = _dir_word(pct)
    ct = (cat.get("type") or "").lower()
    bullish_cat = ct in ("earnings_beat", "guidance_raise", "product")
    t1 = hook_line.strip()                                                   # 이벤트 앵커(hook)
    t2 = f"{tk} {d} {p} on {T2_PHRASE.get(ct, 'the news')} — what does the tape know?"
    conflict = (bullish_cat and pct < 0) or (not bullish_cat and pct > 0)    # 촉매 함의 ↔ 오늘 부호
    if conflict:
        t3 = f"{T3_LEAD.get(ct, 'The catalyst')}, but {tk} {d} {p} — what's the disconnect?"
    else:
        t3 = f"{tk} {d} {p} on {T2_PHRASE.get(ct, 'the news')} — too late, or just starting?"
    out = []
    for t in (t1, t2, t3):
        if not t.rstrip().endswith("?"):
            t = t.rstrip(" .") + "?"
        out.append(t if len(t) <= 100 else t[:96].rstrip() + "...?")
    return out


def _first_line(tk, pct, cat, vol_verdict, spx):
    p = f"{abs(pct):.1f}%"
    d = _dir_word(pct)
    why = (cat.get("why") or "").split(".")[0].strip()
    twist = {"suspect": "but volume was below average",
             "neutral": "on average volume",
             "conviction": "on heavy volume"}.get(vol_verdict, "")
    base = f"{tk} {d} {p} vs SPX {spx:+.1f}% — {twist}".strip(" —")
    return base[:95]


def _hashtags(tk, sector, cat):
    tags = ["#stocks", "#investing", f"#{tk}"]              # 노출 희망 주제(처음 3)
    tags += SECTOR_TAGS.get(sector, ["#stockmarket"])       # 섹터/구체
    ctag = CATALYST_TAG.get((cat.get("type") or "").lower())
    if ctag:
        tags.append(ctag)
    tags.append(_company_tag(tk))                           # 회사명
    tags += ["#stockmarket", "#shorts", "#youtubeshorts"]   # 일반(끝, #shorts 필수)
    seen, out = set(), []
    for h in tags:
        k = h.lower()
        if k not in seen:
            seen.add(k); out.append(h)
    return out[:15]


def _yt_tags(tk, sector, cat):
    """YouTube 내부검색 태그: 큰→작은 카테고리, ≤500자 콤마구분."""
    company = _company(tk)
    base = ["stocks", "stock market", "investing", "US stocks", "stock analysis",
            f"{sector} stocks", f"{tk} stock", f"{tk} {(cat.get('type') or '').replace('_',' ')}",
            f"{company}", f"{tk} analysis", "trading", "finance"]
    s, out = 0, []
    for t in base:
        if s + len(t) + 2 > 500:
            break
        out.append(t); s += len(t) + 2
    return out


def generate(ticker, out_dir=None):
    tk = ticker.upper()
    out_dir = Path(out_dir) if out_dir else sorted((ROOT / "outputs").glob(f"{tk}_*"))[-1]
    price = json.loads((out_dir / "price.json").read_text())
    trader = json.loads((out_dir / "trader_lens.json").read_text())
    hook = json.loads((out_dir / "hook.json").read_text())
    cat = trader.get("catalyst", {})
    pct = price.get("pct_change", 0.0)
    spx = price.get("spx_pct_change", 0.0)
    vv = trader.get("volume", {}).get("verdict", "neutral")
    sector = A.sector_for_ticker(tk)
    date = out_dir.name.split("_")[-1]
    src = NEWS_SOURCE.get(tk, "financial news coverage")
    company = _company(tk)

    titles = _titles(tk, pct, cat, hook.get("hook_line", f"{tk} on the move?"))
    first = _first_line(tk, pct, cat, vv, spx)
    tags = _hashtags(tk, sector, cat)
    yt = _yt_tags(tk, sector, cat)

    rsi = price.get("rsi"); pos = price.get("position_52w", ""); volx = price.get("vol_vs_avg")
    payoff = _sanitize(hook.get("payoff_line", ""))   # P1.2 매수/매도 함의어 제거
    risk = _sanitize(trader.get("risk", ""))

    md = f"""# YouTube Shorts Metadata — {tk} {date}

## Title (≤100 chars · 3후보 모두 의문형=채널 시그니처, ALL CAPS·이모지 없음)
1. (이벤트 앵커) {titles[0]}
2. (데이터 앵커) {titles[1]}
3. (대비 앵커) {titles[2]}

## Description (≤5000 chars)
### 첫 줄 (검색 노출 — 가장 중요)
{first}

### 본문
{tk} ({company}) {_dir_word(pct)} {abs(pct):.2f}% — {(cat.get('why') or '').split('.')[0].strip()}.
Data check: RSI {rsi} ({pos}) · Volume {volx}× of 30-day avg ({vv}) · vs S&P 500 {spx:+.2f}%.
The read: {payoff}
Risk: {risk}

Not financial advice. Educational purposes only.

### Sources
- Price/volume data: Yahoo Finance (yfinance)
- Catalyst/article: {src}
- Stock imagery: Pexels (royalty-free)
- Company logo: Wikimedia Commons (CC-BY-SA)

### Hashtags ({len(tags)}개)
{' '.join(tags)}

## Tags (YouTube 내부검색 · ≤500 chars · 큰→작은)
{', '.join(yt)}

## End Screen 카드
- 다음 영상: 같은 {sector} 섹터 종목 분석 (예: 관련 피어)
- Subscribe CTA: "Daily US-market setups — follow Trader Cho"

## Pinned Comment (게시 직후 고정)
{tk} {_dir_word(pct)} {abs(pct):.2f}% today. Volume was {vv} ({volx}× avg) and RSI sits at {rsi}.
The honest read: {payoff}
Data: Yahoo Finance · Catalyst: {src}
This is educational analysis, not investment advice. Always do your own research.
"""
    (out_dir / "metadata.md").write_text(md)
    print(f"metadata: {out_dir/'metadata.md'} | titles={len(titles)} hashtags={len(tags)} #shorts={'#shorts' in tags}")
    return out_dir / "metadata.md", titles, tags


if __name__ == "__main__":
    for t in (sys.argv[1:] or ["ARM"]):
        generate(t)
