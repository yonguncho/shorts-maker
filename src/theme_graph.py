"""theme_graph.py — ④계열 P4: LLM 테마/공급망 '연관 기업' 추출 + 2중 게이트.

🔴 최고위험(환각/추천 경계) 기능이므로 fail-closed 다중 게이트로 방어한다:
  1) LLM 추출: 포커스 종목의 *제공된 뉴스 헤드라인에서만* 명시적으로 연결된 기업을 뽑게 한다
     (외부지식·추론 금지, 근거 헤드라인 verbatim 동봉 요구).
  2) 프로그램 게이트(결정론): ① 근거가 실제 제공 헤드라인의 substring 인가(날조 증거 차단)
     ② 그 헤드라인에 해당 기업명이 실제로 등장하는가 ③ 기업명이 화이트리스트 티커로 매핑되는가
     (환각 티커 차단). 셋 다 통과해야 생존.
  3) codex 적대검증: 생존 링크를 공격받아 투기·과장으로 지목된 것을 제거하고 PASS 받아야 방영.
LLM(codex/claude) 불가 시 빈 목록 반환(fail-closed — 미검증 링크는 절대 방영 안 함).
"""
from __future__ import annotations
import json
import re

from .common import log
from .codex_bridge import _run_codex, _run_claude_fallback, _parse_verdict, DONE_MARKER

# 화이트리스트: 뉴스에 등장할 법한 미국 상장 기업명 → 티커 (환각 티커 차단용 단일 진실)
NAME2TICKER = {
    "nvidia": "NVDA", "apple": "AAPL", "microsoft": "MSFT", "amazon": "AMZN",
    "alphabet": "GOOGL", "google": "GOOGL", "meta": "META", "facebook": "META",
    "tesla": "TSLA", "amd": "AMD", "advanced micro devices": "AMD", "intel": "INTC",
    "broadcom": "AVGO", "qualcomm": "QCOM", "micron": "MU", "arm": "ARM",
    "super micro": "SMCI", "supermicro": "SMCI", "taiwan semiconductor": "TSM",
    "tsmc": "TSM", "oracle": "ORCL", "palantir": "PLTR", "dell": "DELL",
    "marvell": "MRVL", "asml": "ASML", "netflix": "NFLX", "salesforce": "CRM",
    "openai": None, "anthropic": None,  # 비상장 → 매핑 없음(드롭)
}

RELATIONS = {"supplier", "customer", "partner", "competitor", "peer",
             "subsidiary", "supply-chain", "vendor", "rival"}

EXTRACT_TEMPLATE = """You extract ONLY explicitly-stated company links from news headlines.

FOCUS COMPANY: {focus_name} ({focus})

NEWS HEADLINES (the ONLY allowed evidence — do not use any outside knowledge):
{headlines}

TASK: List other companies that THESE HEADLINES explicitly connect to {focus}
(as supplier, customer, partner, competitor/peer, or supply-chain link).
STRICT RULES:
- Use ONLY the headlines above. No outside knowledge. No inference beyond what the text states.
- The company MUST be named in the SAME headline that states the relationship.
- Copy the supporting headline VERBATIM into "evidence".
- If a relationship is not explicitly in the text, DO NOT include it.
- If none qualify, output an empty list.

Output your reasoning, then on the FINAL lines output EXACTLY:
{marker}
{{"links": [{{"company": "<name as in headline>", "relation": "<supplier|customer|partner|competitor|peer|supply-chain>", "evidence": "<exact headline text>"}}]}}
The JSON must be valid and on a single line after the marker."""

VERIFY_TEMPLATE = """You are an adversarial fact-checker for a financial shorts pipeline.
For EACH claimed company link below, decide if it is DIRECTLY and EXPLICITLY supported by
its evidence headline — the linked company must be NAMED in the evidence and the stated
relationship must be evident from that text alone (no outside knowledge, no speculation).

FOCUS: {focus}
CLAIMED LINKS:
{links}

Reject (keep=false) any link that relies on inference, market speculation, or a relationship
not literally present in the evidence text. Be strict: when in doubt, reject.

Output your reasoning, then on the FINAL lines output EXACTLY:
{marker}
{{"verified": [{{"company": "<name>", "keep": true_or_false}}, ...]}}
The JSON must be valid and on a single line after the marker."""


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower()).strip()


def _llm(prompt: str):
    out = _run_codex(prompt)
    engine = "codex"
    if out is None:
        out = _run_claude_fallback(prompt)
        engine = "claude_fallback"
    return out, engine


def _parse_json_after_marker(out: str, key: str):
    if not out or DONE_MARKER not in out:
        return None
    tail = out.split(DONE_MARKER, 1)[1].strip()
    m = re.search(r"\{.*\}", tail, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0)).get(key)
    except json.JSONDecodeError:
        return None


def extract_links(focus: str, focus_name: str, news_items: list) -> tuple[list, str]:
    """LLM 추출. (raw_links, engine) 반환. news_items: [{title, source, url, cite}]."""
    headlines = "\n".join(f"- {n.get('title') or n.get('content') or ''}" for n in news_items[:12])
    if not headlines.strip():
        return [], "none"
    prompt = EXTRACT_TEMPLATE.format(focus=focus, focus_name=focus_name,
                                     headlines=headlines, marker=DONE_MARKER)
    out, engine = _llm(prompt)
    links = _parse_json_after_marker(out or "", "links") or []
    return (links if isinstance(links, list) else []), engine


def programmatic_gate(focus: str, raw_links: list, news_items: list) -> list:
    """결정론 게이트: 근거 substring 실재 + 기업명 등장 + 화이트리스트 매핑 + 자기참조 제외."""
    hl_norm = [( _norm(n.get("title") or n.get("content") or ""), n) for n in news_items]
    survived, seen = [], set()
    for lk in raw_links:
        if not isinstance(lk, dict):
            continue
        name = _norm(lk.get("company"))
        relation = _norm(lk.get("relation"))
        evidence = _norm(lk.get("evidence"))
        ticker = NAME2TICKER.get(name)
        if not name or ticker is None:            # 비상장/미지의 기업 → 드롭(환각 티커 차단)
            continue
        if ticker == focus or ticker in seen:     # 자기참조/중복 제외
            continue
        if relation not in RELATIONS:
            continue
        # 근거가 실제 제공 헤드라인의 substring 인가 + 그 헤드라인에 기업명이 실재하는가
        match = next((src for h, src in hl_norm if evidence and evidence in h and name in h), None)
        if not match:
            continue
        seen.add(ticker)
        survived.append({
            "ticker": ticker, "company": lk.get("company"), "relation": relation,
            "evidence": match.get("title") or match.get("content"),
            "cite": match.get("cite") or (f"[{match.get('source')}]({match.get('url')})"
                                          if match.get("url") else match.get("source")),
        })
    return survived


def codex_verify(focus: str, links: list) -> tuple[list, dict]:
    """codex 적대검증: keep=true 만 통과. LLM 불가 시 빈 목록(fail-closed)."""
    if not links:
        return [], {"engine": "skip", "verdict": "n/a"}
    listing = "\n".join(
        f"{i+1}. {focus} —[{lk['relation']}]→ {lk['ticker']} ({lk['company']}); "
        f"evidence: \"{lk['evidence']}\"" for i, lk in enumerate(links))
    prompt = VERIFY_TEMPLATE.format(focus=focus, links=listing, marker=DONE_MARKER)
    out, engine = _llm(prompt)
    verified = _parse_json_after_marker(out or "", "verified")
    if verified is None:                          # LLM 불가/파싱불가 → fail-closed
        log("WARN", "theme_graph: codex 검증 불가 → 링크 전부 보류(fail-closed)", "theme")
        return [], {"engine": engine, "verdict": "ERROR"}
    keep_names = {_norm(v.get("company")) for v in verified
                  if isinstance(v, dict) and v.get("keep") is True}
    kept = [lk for lk in links if _norm(lk["company"]) in keep_names]
    return kept, {"engine": engine, "verdict": "PASS" if kept else "FAIL",
                  "reviewed": len(links), "kept": len(kept)}


def build_theme_links(focus: str, focus_name: str, news_items: list) -> dict:
    """전체 파이프라인: 추출 → 결정론 게이트 → codex 검증. 방영 가능한 링크만 반환."""
    raw, eng = extract_links(focus, focus_name, news_items)
    gated = programmatic_gate(focus, raw, news_items)
    verified, vmeta = codex_verify(focus, gated)
    log("INFO", f"theme_graph[{focus}]: 추출 {len(raw)} → 결정론게이트 {len(gated)} → "
                f"codex검증 {len(verified)} (engine={eng}/{vmeta.get('engine')})", "theme")
    return {"links": verified,
            "audit": {"extracted": len(raw), "gated": len(gated), "verified": len(verified),
                      "extract_engine": eng, "verify": vmeta}}
