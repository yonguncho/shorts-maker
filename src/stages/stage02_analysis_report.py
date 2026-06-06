"""stage02 — ② 시장 리포트 작성 (Analyst).

입력 : state/verified_market_data.json  (stage01 산출, 검증 통과 데이터)
산출물: state/market_report.md          (데이터·해설형 동향 리포트)
        state/market_report.meta.json    (출처/공방/가드레일 메타)

설계 원칙(stage01 과 동일 계열):
  - **환각 차단**: 모든 문장은 verified_market_data.json 의 항목에 직접 근거하고 출처(url)를 단다.
    LLM 자유생성이 아니라 검증된 사실에서 결정론적으로 조립한다(출처 없는 주장 0).
  - **투자권유 금지 가드레일**: 매수/매도/목표가/예측성 표현이 새어나오면 단계 실패.
  - **Codex 적대적 공방**: 리포트의 해석/과장/인과비약을 공격받고, 방어자가 약한 해석 문장을
    깎아낸다(라운드마다 강화). PASS & 최소 2R. codex 불가 시 claude 폴백(codex_bridge).
  - adversarial 비활성(manifest.adversarial.enabled=false 또는 SHORTS_DEBATE=0)이면 공방을 건너뛴다
    — 리포트는 결정론적 사실 기반이라 게이트는 통과로 본다(사유 기록).

실행: .venv/bin/python -m src.stages.stage02_analysis_report
"""
from __future__ import annotations
import os
import re

from ..common import (
    read_json, write_json_atomic, log, utc_now, today_utc,
    STATE_DIR, ROOT, adversarial_gate_mode,
)
from ..codex_bridge import debate

IN_PATH = STATE_DIR / "verified_market_data.json"
OUT_MD = STATE_DIR / "market_report.md"
OUT_META = STATE_DIR / "market_report.meta.json"

# 해설에 쓰는 신뢰도(이 이상만 서술 근거로 사용; low 는 각주로만)
NARRATIVE_CONF = ("high", "medium")

# 투자권유/예측성 표현 — 새어나오면 단계 실패(데이터·해설형만 허용)
ADVICE_PATTERNS = [
    r"\bbuy\b", r"\bsell\b", r"\bshort\b(?!\s*interest)", r"\bgo long\b",
    r"\bprice target\b", r"\btarget price\b", r"\bupgrade\b", r"\bdowngrade\b",
    r"\brecommend", r"\bshould (buy|sell|invest|hold)\b",
    r"\bwill (rise|fall|go up|go down|surge|crash|rally)\b",
    r"\bguaranteed?\b", r"매수", r"매도", r"목표가", r"추천", r"투자\s*권유",
]
ADVICE_RE = re.compile("|".join(ADVICE_PATTERNS), re.IGNORECASE)

INDEX_PROXY = {"SPY": "S&P 500", "QQQ": "Nasdaq 100", "DIA": "Dow 30", "IWM": "Russell 2000"}


# ── 항목에서 수치 뽑기 ────────────────────────────────
def _pct(item: dict):
    """quote content('... pct=1.23% ...') 또는 extra_json 에서 일중 변동률(%) 추출."""
    m = re.search(r"pct=(-?\d+(?:\.\d+)?)%", item.get("content") or "")
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
    return None


def _price(item: dict):
    m = re.search(r"price=(-?\d+(?:\.\d+)?)", item.get("content") or "")
    return float(m.group(1)) if m else None


def _cite(item: dict) -> str:
    url = item.get("url") or ""
    return f"[{item.get('source','?')}]({url})" if url else f"{item.get('source','?')}"


# ── 클레임(문장) 빌더 — 각 클레임은 사실 1개 + 출처 ──
def build_claims(data: dict) -> dict:
    quotes = [q for q in data.get("market_snapshot", []) if q.get("confidence") in NARRATIVE_CONF]
    news = [n for n in data.get("news", []) if n.get("confidence") in NARRATIVE_CONF]
    filings = data.get("filings", [])  # SEC=grade1, 그대로 사용
    low_notes = [x for x in data.get("market_snapshot", []) + data.get("news", [])
                 if x.get("confidence") == "low"]

    by_ticker = {}
    for q in quotes:
        if q.get("ticker"):
            by_ticker[q["ticker"]] = q

    claims = {"indices": [], "movers": [], "themes": [], "news": [], "filings": [],
              "low_footnotes": low_notes}

    # 1) 지수 프록시 스냅샷 (사실)
    for sym, label in INDEX_PROXY.items():
        q = by_ticker.get(sym)
        if not q:
            continue
        p, pc = _price(q), _pct(q)
        if pc is None:
            continue
        arrow = "▲" if pc > 0 else ("▼" if pc < 0 else "■")
        claims["indices"].append({
            "kind": "fact", "tag": "index",
            "text": f"{label} ({sym}) {arrow} {pc:+.2f}%"
                    + (f", last {p:g}" if p is not None else ""),
            "cite": _cite(q), "fresh": q.get("fresh"),
        })

    # 2) 메가캡 무버 (사실: 상승/하락 상위)
    megacaps = [by_ticker[t] for t in ("AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA")
                if t in by_ticker]
    movers = [(q, _pct(q)) for q in megacaps if _pct(q) is not None]
    gainers = sorted([m for m in movers if m[1] > 0], key=lambda x: x[1], reverse=True)[:3]
    losers = sorted([m for m in movers if m[1] < 0], key=lambda x: x[1])[:3]  # 가장 큰 하락 우선
    for q, pc in gainers:
        claims["movers"].append({"kind": "fact", "tag": "gainer",
                                 "text": f"{q['ticker']} {pc:+.2f}%", "cite": _cite(q)})
    for q, pc in losers:
        claims["movers"].append({"kind": "fact", "tag": "loser",
                                 "text": f"{q['ticker']} {pc:+.2f}%", "cite": _cite(q)})

    # 3) 테마(해설) — 검증된 지수 사실에서만 보수적으로 도출. Codex 공격 대상.
    idx_pcts = [(_pct(by_ticker[s]), s) for s in INDEX_PROXY if s in by_ticker and _pct(by_ticker[s]) is not None]
    if idx_pcts:
        ups = [s for pc, s in idx_pcts if pc > 0]
        downs = [s for pc, s in idx_pcts if pc < 0]
        if len(ups) == len(idx_pcts) and ups:
            claims["themes"].append({"kind": "interp", "tag": "breadth",
                "text": "Major index proxies closed broadly higher on the session.",
                "cite": "; ".join(_cite(by_ticker[s]) for s in ups)})
        elif len(downs) == len(idx_pcts) and downs:
            claims["themes"].append({"kind": "interp", "tag": "breadth",
                "text": "Major index proxies closed broadly lower on the session.",
                "cite": "; ".join(_cite(by_ticker[s]) for s in downs)})
        else:
            claims["themes"].append({"kind": "interp", "tag": "breadth",
                "text": "Index proxies were mixed on the session.",
                "cite": "; ".join(_cite(by_ticker[s]) for _, s in idx_pcts)})

    # 4) 뉴스 헤드라인(사실: 헤드라인 + 출처, 편집 해석 없음)
    for n in news[:5]:
        title = (n.get("title") or n.get("content") or "").strip()
        if title:
            claims["news"].append({"kind": "fact", "tag": "news",
                                   "text": title[:160], "cite": _cite(n)})

    # 5) SEC 공시(1차 출처)
    for f in filings[:5]:
        title = (f.get("title") or f.get("content") or "").strip()
        if title:
            claims["filings"].append({"kind": "fact", "tag": "filing",
                                      "text": title[:160], "cite": _cite(f)})
    return claims


def render_markdown(claims: dict, data: dict, debate_meta: dict | None) -> str:
    date = data.get("date") or today_utc()
    L = []
    L.append(f"# US Market Commentary — {date}")
    L.append("")
    L.append("> Educational market commentary built only from source-verified data. "
             "Not investment advice; no buy/sell/price-target guidance.")
    L.append("")

    L.append("## Index ETF proxies")
    L.append("_Values are ETF share prices used as index proxies — not the underlying index levels._")
    if claims["indices"]:
        for c in claims["indices"]:
            stale = "" if c.get("fresh", True) else " _(dated)_"
            L.append(f"- {c['text']}{stale}  — {c['cite']}")
    else:
        L.append("- (no source-verified index data)")
    L.append("")

    if claims["movers"]:
        L.append("## Notable megacaps")
        L.append("_Largest intraday moves within a fixed megacap set "
                 "(AAPL, MSFT, NVDA, AMZN, GOOGL, META, TSLA); not a ranking of the whole market._")
        for c in claims["movers"]:
            L.append(f"- {c['text']}  — {c['cite']}")
        L.append("")

    if claims["themes"]:
        L.append("## What the data shows")
        for c in claims["themes"]:
            L.append(f"- {c['text']}  — {c['cite']}")
        L.append("")

    if claims["news"]:
        L.append("## Headlines (verified sources)")
        for c in claims["news"]:
            L.append(f"- {c['text']}  — {c['cite']}")
        L.append("")

    if claims["filings"]:
        L.append("## SEC filings (primary source)")
        for c in claims["filings"]:
            L.append(f"- {c['text']}  — {c['cite']}")
        L.append("")

    if claims["low_footnotes"]:
        L.append("## Unconfirmed (low confidence — excluded from narrative)")
        for x in claims["low_footnotes"][:8]:
            t = (x.get("title") or x.get("content") or "")[:120]
            L.append(f"- {t}  — {_cite(x)}")
        L.append("")

    # 출처/검증 푸터
    v = data.get("verification", {})
    snap = len(data.get("market_snapshot", []))
    nnews = len(data.get("news", []))
    nfil = len(data.get("filings", []))
    L.append("---")
    L.append(f"_Data date {date} · generated {utc_now()} · "
             f"verified items: {snap} quotes / {nnews} news / {nfil} filings · "
             f"rules: {', '.join(v.get('rules', []))}_")
    L.append("")
    L.append("_Quotes are the last available values from Finnhub as of the generation time above; "
             "they may be delayed and are not guaranteed real-time. Percent changes are intraday "
             "from the same source. Some news links route via the Google News aggregator to the "
             "original publisher rather than a direct link._")
    if debate_meta:
        L.append(f"_Adversarial review: {debate_meta.get('status')} "
                 f"({debate_meta.get('total_rounds', 0)}R, engine={debate_meta.get('engine','-')})_")
    L.append("")
    return "\n".join(L)


def guardrail_violations(claims: dict) -> list[str]:
    """투자권유/예측성 표현 검출. 파이프라인이 '직접 조립·서술'한 클레임만 검사한다.

    indices/movers/themes 는 파이프라인이 수치·해설로 생성한 문장이므로 권유가 새어나오면 안 된다.
    반면 news/filings/low_footnotes 는 출처를 단 **제3자 원문 헤드라인/제목의 verbatim 인용**이라,
    그 안의 'buy/sell' 등은 파이프라인의 권유가 아니다 → 검사 제외(인용을 권유로 오탐 방지)."""
    bad = []
    for sec in ("indices", "movers", "themes"):
        for c in claims.get(sec, []):
            text = c.get("text", "")
            for m in ADVICE_RE.finditer(text):
                bad.append(f"{m.group(0)!r} :: [{sec}] {text[:80]}")
    return bad


def _claims_to_payload(claims: dict) -> str:
    parts = []
    for sec in ("indices", "movers", "themes", "news", "filings"):
        if claims[sec]:
            parts.append(sec.upper() + ":")
            for c in claims[sec]:
                parts.append(f"  - ({c['kind']}/{c['tag']}) {c['text']}  src={c['cite']}")
    return "\n".join(parts) if parts else "(empty report)"


def make_defender(claims: dict, data: dict):
    """Codex 공격 시 해석(interp) 문장을 약화/제거. 사실(fact) 문장은 출처가 있으므로 유지.

    공방 payload 는 실제 렌더된 리포트(render_markdown) — 라벨/고지/푸터가 모두 보여야
    codex 의 라벨링·고지 지적이 올바르게 해소된다(클레임 평문 덤프가 아님)."""
    state = {"claims": claims}

    def defender(attack: dict, round_no: int):
        cl = state["claims"]
        issues = " ".join(attack.get("issues", [])).lower()
        notes = []
        attack_interp = any(k in issues for k in
                            ("overstat", "leap", "causal", "speculat", "interpret", "unsupported", "broad"))
        # 1라운드부터 해석 문장이 공격받으면 가장 약한 것부터 제거, 2R+ 이후엔 해석 전부 제거 가능
        if cl["themes"] and (attack_interp or round_no >= 2):
            before = len(cl["themes"])
            if round_no >= 2:
                cl["themes"] = []
            else:
                cl["themes"] = cl["themes"][:-1]
            notes.append(f"themes: {before}→{len(cl['themes'])} (해석 문장 약화/제거)")
        # 출처 없는 문장(있을 수 없지만 방어적으로) 제거
        for sec in ("indices", "movers", "news", "filings", "themes"):
            kept = [c for c in cl[sec] if c.get("cite")]
            if len(kept) != len(cl[sec]):
                notes.append(f"{sec}: 무출처 문장 제거")
            cl[sec] = kept
        if not notes:
            notes.append("제거 없음(사실+출처 기반이라 방어 가능)")
        state["claims"] = cl
        return render_markdown(cl, data, None), "; ".join(notes)

    return defender, state


def adversarial_enabled() -> tuple[bool, str]:
    env = os.environ.get("SHORTS_DEBATE")
    if env is not None:
        return (env not in ("0", "false", "no", ""), f"env SHORTS_DEBATE={env}")
    mani = read_json(ROOT / "manifest.json", default={}) or {}
    en = bool(mani.get("adversarial", {}).get("enabled", False))
    return en, "manifest.adversarial.enabled"


def main() -> int:
    log("INFO", "=== STAGE ② 시장 리포트 시작 ===", "stage02")
    data = read_json(IN_PATH, default=None)
    if not data:
        log("ERROR", f"입력 없음: {IN_PATH} (stage01 먼저 실행 필요)", "stage02")
        return 2

    claims = build_claims(data)
    n_fact = sum(len(claims[s]) for s in ("indices", "movers", "news", "filings"))
    n_interp = len(claims["themes"])
    log("INFO", f"클레임 빌드: 사실={n_fact} 해석={n_interp}", "stage02")

    # 적대적 공방
    debate_meta = None
    en, why = adversarial_enabled()
    if en:
        defender, state = make_defender(claims, data)
        log("INFO", f"Codex 리포트 공방 시작 (min 2R, {why})", "stage02")
        result = debate(subject="Analyst market report (US market, commentary-only)",
                        payload_text=render_markdown(claims, data, None), defender=defender,
                        min_rounds=2, max_rounds=4)
        claims = state["claims"]
        eng = result["rounds"][-1]["attack"]["engine"] if result.get("rounds") else "-"
        debate_meta = {"status": result["status"], "total_rounds": result["total_rounds"],
                       "engine": eng,
                       "rounds": [{"round": r["round"], "engine": r["attack"]["engine"],
                                   "verdict": r["attack"]["verdict"],
                                   "issues": r["attack"].get("issues", []),
                                   "defense": r["defense_notes"]} for r in result["rounds"]]}
    else:
        debate_meta = {"status": "skipped", "total_rounds": 0, "engine": "-",
                       "reason": f"adversarial disabled ({why})"}
        log("INFO", f"적대적 공방 건너뜀 ({why}) — 결정론적 사실 리포트로 진행", "stage02")

    md = render_markdown(claims, data, debate_meta)

    # 가드레일: 투자권유/예측성 표현 검출 시 실패
    violations = guardrail_violations(claims)
    if violations:
        log("ERROR", f"가드레일 위반(투자권유/예측 표현) {len(violations)}건 — 단계 실패: "
                     f"{violations[:3]}", "stage02")
        return 4

    OUT_MD.write_text(md, encoding="utf-8")
    meta = {
        "schema_version": "1.0", "pipeline_id": "shorts_maker", "machine": "mac",
        "stage": 2, "agent": "Analyst", "generated_utc": utc_now(),
        "date": data.get("date"), "source_file": str(IN_PATH.name),
        "counts": {"facts": sum(len(claims[s]) for s in ("indices", "movers", "news", "filings")),
                   "themes": len(claims["themes"]),
                   "low_footnotes": len(claims["low_footnotes"])},
        "guardrail": {"advice_violations": 0, "patterns_checked": len(ADVICE_PATTERNS)},
        "adversarial": debate_meta,
        "output_md": str(OUT_MD.name),
    }
    write_json_atomic(OUT_META, meta)

    status = debate_meta.get("status")
    log("INFO", f"=== STAGE ② 완료: report={OUT_MD.name} facts={meta['counts']['facts']} "
                f"themes={meta['counts']['themes']} debate={status} ===", "stage02")

    # 게이트: skipped/passed 는 통과. max_rounds_reached 는 모드에 따라 —
    # blocking=정지(rc3), advisory=경고+진행(지적은 meta.adversarial 에 기록).
    if status == "max_rounds_reached":
        if adversarial_gate_mode() == "blocking":
            log("ERROR", "공방 PASS 실패(max_rounds) — blocking 모드 → 단계 실패", "stage02")
            return 3
        log("WARN", "공방 PASS 실패(max_rounds) — advisory 모드: 지적은 meta.adversarial 에 기록, "
                    "진행. (blocking 복원: ADVERSARIAL_GATE_MODE=blocking)", "stage02")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
