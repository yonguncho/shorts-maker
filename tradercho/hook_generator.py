"""hook_generator.py — RAG 컨텍스트로 hook_line/payoff_line 정제 (Phase 3-3).

catalyst.type 기반으로 hook_formulas 검색 → 그 프레임워크 예시 + 트레이더 컨텍스트로
Claude가 최종 의문형 훅 생성. similar_past(channel_history)가 있으면 가중치(초기엔 빈 리스트).
rag_retrieve.py 실제 import(모킹 금지).
"""
from __future__ import annotations
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import llm
import rag_retrieve


def _parse_date(s):
    """'YYYY-MM-DD...' → date or None."""
    if not s:
        return None
    try:
        return date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


def _time_context(article_date, data_date):
    """기사일·데이터일 시점 관계 → (LLM 지시문, meta dict). 결정2: 시점-앵커 훅."""
    ad, dd = _parse_date(article_date), _parse_date(data_date)
    if not ad or not dd or ad == dd:
        return ("The catalyst news and the price data are from the same session — "
                "no temporal gap. A present-tense framing is fine.",
                {"article_date": str(ad) if ad else None, "data_date": str(dd) if dd else None,
                 "time_anchored": False, "days_stale": 0})
    gap = (dd - ad).days
    if gap > 0:
        instr = (f"TEMPORAL GAP: the catalyst was reported on {ad} but the latest price data is "
                 f"as of {dd} ({gap} day(s) later). The move is NOT happening right now — do NOT imply "
                 f"'today' or live action. Anchor the hook to when it happened (e.g. 'after this week's "
                 f"move', 'days after the news') and frame the data as the follow-through since then.")
    else:
        instr = (f"The price data ({dd}) predates the catalyst news ({ad}). Make clear the numbers are "
                 f"as of the earlier {dd} close and the news is still developing; avoid stale-data implications.")
    return (instr, {"article_date": str(ad), "data_date": str(dd),
                    "time_anchored": True, "days_stale": gap})

# catalyst.type → hook framework 탐색 쿼리
_CAT_QUERY = {
    "earnings_beat": "earnings beat durable catalyst curiosity gap hook",
    "guidance_raise": "guidance raise durable authority hook",
    "analyst_action": "analyst price target authority reference hook",
    "product": "product launch validation indirect catalyst curiosity hook",
    "macro": "macro market wide negation contrarian hook",
    "sympathy": "sector sympathy temporary pattern interrupt hook",
}

PROMPT = """You write scroll-stopping hooks for a US-stock Short. Keep the channel's hedged, no-advice posture.

CONTEXT (from trader analysis):
- ticker: {{TICKER}}
- catalyst: {{CATALYST}}
- surprise: {{SURPRISE}}
- hook_seed (raw): {{SEED}}
- payoff candidate: {{PAYOFF}}

PROVEN HOOK FRAMEWORKS (retrieved from knowledge base):
{{EXAMPLES}}

TIMING (anchor the hook truthfully to this):
{{TIME_CONTEXT}}

Write the final hook_line and payoff_line:
- hook_line: < 12 words, English, QUESTION form or PATTERN INTERRUPT. Reveal part of the conclusion (curiosity gap). No buy/sell, no "will rise".
- When a SPECIFIC catalyst is known (e.g. "Nvidia announcement", "RTX Spark platform", "earnings beat"), the hook_line MUST name it. Catalyst-anchored phrasing ("ARM ripped after Nvidia's news…") beats vague time anchors ("after this week's move"). Pull the concrete proper noun from the catalyst. Never name a real person.
- payoff_line: the answer to the hook, revealed at the end. Hedged. MAX 18 words, one punchy sentence (it is shown as on-screen caption word-by-word — keep it tight).
- Respect the TIMING note above — never imply a move is live if there is a temporal gap.
- pick the single best framework name from the retrieved set.

Output strict JSON after ===JSON===:
{"hook_line": "", "payoff_line": "", "hook_framework": ""}"""


import re as _re
# L0.6 동사 등락 함의 사전
BULL_VERBS = {"ripped", "popped", "surged", "skyrocketed", "jumped", "soared",
              "rallied", "spiked", "exploded", "ripping", "popping", "surging", "soaring"}
BEAR_VERBS = {"slid", "dropped", "sank", "tumbled", "plunged", "crashed", "fell",
              "slumped", "sliding", "dropping", "tumbling", "plunging", "cratered"}
STATE_WORDS = {"stretched", "cooling", "consolidating", "resting", "extended",
               "stalling", "fading", "steady", "quiet", "overheated"}


def _hook_consistent(hook_line, pct):
    """L0.6: hook의 현재상태 동사 함의가 오늘 % 부호와 일치하나. (ok, reason)."""
    if pct is None:
        return True, ""
    words = set(_re.findall(r"[a-z]+", (hook_line or "").lower()))
    bull, bear = words & BULL_VERBS, words & BEAR_VERBS
    if bull and pct < 1.0:
        return False, f"상승동사 {bull} 사용했으나 오늘 {pct:+.2f}% (≥+1% 아님)"
    if bear and pct > -1.0:
        return False, f"하락동사 {bear} 사용했으나 오늘 {pct:+.2f}% (≤−1% 아님)"
    return True, ""


def mascot_quips(trader_json, price_json):
    """씬1/6/11 말풍선용 ≤4단어 구어체 반응(L4.6). 분석문장·단정·인물 금지."""
    cat = trader_json.get("catalyst", {})
    surprise = bool(trader_json.get("surprise"))
    pct = abs(price_json.get("pct_change", 0.0))
    verdict = (trader_json.get("volume", {}).get("verdict") or "neutral")
    # 씬1: 카탈리스트/변동 강도
    if pct >= 5 or surprise:
        q1 = "Whoa."
    elif (cat.get("durability") or "").upper() == "DURABLE":
        q1 = "Look at this."
    else:
        q1 = "Huh?"
    # 씬6: 거래량 판정
    q6 = {"suspect": "Suspect.", "conviction": "Conviction!", "neutral": "Mixed."}.get(verdict, "Mixed.")
    # 씬11: payoff 톤
    payoff = (trader_json.get("payoff_line") or "").lower()
    if "yes" in payoff or "likely" in payoff:
        q11 = "Maybe."
    elif "risk" in payoff or "caution" in payoff or "stretch" in payoff:
        q11 = "Stay sharp."
    else:
        q11 = "Watch this."
    return {1: q1, 6: q6, 11: q11}


def _fallback_hook(ticker, pct, cat, rsi=None):
    """가드 통과 실패 시 상태묘사 기반 안전 hook(±1% 이내/충돌 시)."""
    if rsi is not None and rsi >= 70:
        state = "stretched near its highs"
    elif pct is not None and pct < 0:
        state = "cooling"
    elif pct is not None and pct >= 1:
        state = "running hot"
    else:
        state = "consolidating"
    return f"{ticker.upper()} {state} after the catalyst — losing steam already?"


def generate(ticker: str, trader_json: dict, top_k: int = 3,
             article_date: str = None, data_date: str = None, price_pct=None, rsi=None) -> tuple[dict, str]:
    cat = (trader_json.get("catalyst") or {})
    ctype = cat.get("type", "product")
    q = _CAT_QUERY.get(ctype, "curiosity gap hook stock")
    examples = rag_retrieve.retrieve(q, category="hook_formulas", top_k=top_k)
    # 출처 로그(강제 제약 11)
    rag_sources = [{"category": e.get("category"), "chunk_id": e.get("chunk_id"),
                    "section": e.get("section"), "score": e.get("score")} for e in examples]
    ex_text = "\n".join(f"- [{e.get('section')}] " +
                        (e["text"].split("\n", 1)[1] if "\n" in e["text"] else e["text"])[:200]
                        for e in examples)
    time_instr, time_meta = _time_context(article_date, data_date)   # 결정2
    prompt = (PROMPT.replace("{{TICKER}}", ticker.upper())
                    .replace("{{CATALYST}}", json.dumps(cat))
                    .replace("{{SURPRISE}}", str(trader_json.get("surprise") or ""))
                    .replace("{{SEED}}", str(trader_json.get("hook_seed") or ""))
                    .replace("{{PAYOFF}}", str(trader_json.get("payoff_line") or ""))
                    .replace("{{EXAMPLES}}", ex_text or "(none)")
                    .replace("{{TIME_CONTEXT}}", time_instr))
    data, engine = llm.call_json(prompt)
    if not data or not data.get("hook_line"):
        # 폴백: trader hook_seed 사용
        data = {"hook_line": trader_json.get("hook_seed") or f"What's really moving {ticker}?",
                "payoff_line": trader_json.get("payoff_line") or "", "hook_framework": "curiosity_gap"}
        engine = engine + "+fallback"
    # L0.6 정직성 가드: hook 동사 함의 ↔ 오늘 % 부호 일치. 위반 시 재생성(최대 2회).
    ok, reason = _hook_consistent(data.get("hook_line", ""), price_pct)
    tries = 0
    while not ok and tries < 2:
        tries += 1
        guard = (f"\n\nREJECTED ({reason}). The stock is {price_pct:+.2f}% TODAY. "
                 f"Do NOT use a verb implying a rise (ripped/popped/surged) unless today is up ≥1%, "
                 f"nor a fall verb unless today is down ≤−1%. Since today is near-flat/opposite, describe the "
                 f"CURRENT STATE (stretched/cooling/resting/extended/overheated). You MAY mention the past "
                 f"catalyst as a dated event. Rewrite hook_line accordingly.")
        d2, e2 = llm.call_json(prompt + guard)
        if d2 and d2.get("hook_line"):
            data["hook_line"] = d2["hook_line"]
            if d2.get("payoff_line"):
                data["payoff_line"] = d2["payoff_line"]
            engine = f"{e2}+guard{tries}"
        ok, reason = _hook_consistent(data.get("hook_line", ""), price_pct)
    if not ok:   # 재시도 실패 → 결정적 상태묘사 폴백
        data["hook_line"] = _fallback_hook(ticker, price_pct, cat, rsi)
        engine = engine + "+guardfallback"
        ok, _ = True, ""
    data["hook_honesty_guard"] = {"checked_pct": price_pct, "passed": True, "retries": tries}
    # 안전 트림: payoff ≤25 단어(P0.3) — 마지막 단어 경계에서 자르고 마침표 보존
    pl = (data.get("payoff_line") or "").split()
    if len(pl) > 25:
        data["payoff_line"] = " ".join(pl[:25]).rstrip(",;:") + "…"
    data["rag_sources"] = rag_sources
    data.update(time_meta)   # article_date/data_date/time_anchored/days_stale → hook.json
    return data, engine


if __name__ == "__main__":
    import data_fetch
    import trader_lens
    tk = sys.argv[1] if len(sys.argv) > 1 else "ARM"
    art = Path(sys.argv[2]).read_text() if len(sys.argv) > 2 else "Sample."
    pj = data_fetch.fetch(tk)
    tj, _ = trader_lens.extract(tk, art, pj)
    hj, eng = generate(tk, tj)
    print(f"engine={eng}")
    print(json.dumps(hj, indent=2, ensure_ascii=False))
