"""stage03 — ③ 소재 선정 (Producer).

입력 : state/verified_market_data.json  (stage01 산출, 검증 통과 데이터)
       state/market_report.meta.json    (stage02 산출 — 존재 시 일관성 참고용, 없어도 동작)
산출물: state/topic.json                 (쇼츠 1편의 소재: 초점/차트대상/토킹포인트/출처/선정근거)

설계 원칙(stage01·02 와 동일 계열):
  - **결정론적 선정**: 검증된 claim(사실)에서 객관적 신호(변동률 크기·시장 방향)로 점수화해 1건 선정.
    LLM 자유생성 아님 — 선정 사유와 후보 점수를 전부 기록(재현 가능).
  - **출처 필수**: 토킹포인트는 stage02 claim 의 text+cite 를 그대로 인용(무출처 0).
  - **환각/권유 차단**: 파이프라인이 직접 조립한 문장(angle/headline)에 투자권유·예측 표현이
    새어나오면 단계 실패(stage02 와 동일 ADVICE_RE 재사용). 제3자 헤드라인 verbatim 은 인용이라 제외.
  - claim 구성은 stage02.build_claims 를 재사용 — claim 로직의 단일 진실 유지.

실행: .venv/bin/python -m src.stages.stage03_topic_selection
"""
from __future__ import annotations
import re

from ..common import read_json, write_json_atomic, log, utc_now, today_utc, STATE_DIR
from .stage02_analysis_report import build_claims, ADVICE_RE, INDEX_PROXY
from ..collect import SECTOR_PEERS, LEVERAGED_ETF, HERO_UNIVERSE, THEMES
from ..themes import score_themes

IN_PATH = STATE_DIR / "verified_market_data.json"
REPORT_META = STATE_DIR / "market_report.meta.json"
OUT_PATH = STATE_DIR / "topic.json"

MEGACAP_SYMS = ("AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA")

# 메가캡 단일 종목 변동이 이 |%| 이상이면 '그날의 주인공'으로 단독 리드. 미만이면 시장 전반(breadth) 리드.
MOVER_LEAD_THRESHOLD = 4.0
TALKING_POINTS_MAX = 4

# 이슈+변동성 결합 스코어링 가중치 (사용자 확정 방향: 뉴스/실적 이벤트 종목 중 변동성 큰 것 우선)
W_NEWS = 0.4          # 뉴스 1건당 변동성 배수 가산 (multiplicative, 최대 5건)
W_EARNINGS = 2.0      # 임박 실적(카탈리스트) 가산점
W_TREND = 1.0         # 검색 급증 신호 보너스
W_SOCIAL = 0.2        # reddit 언급 1건당 보너스(최대 5)
TREND_SURGE_MIN = 30  # 검색관심 급증으로 볼 임계(%)

_PCT_RE = re.compile(r"([+-]?\d+(?:\.\d+)?)%")
_SYM_RE = re.compile(r"\(([A-Z]{1,6})\)")
_QUOTE_PCT_RE = re.compile(r"pct=([-+]?\d+(?:\.\d+)?)")


# ── 멀티소스 신호 인덱싱 (verified_market_data.json) ───────
def _samedaypct_by_ticker(data: dict) -> dict:
    """market_snapshot quote content 의 pct= 를 종목별로 파싱."""
    out = {}
    for q in data.get("market_snapshot", []):
        t = q.get("ticker")
        m = _QUOTE_PCT_RE.search(q.get("content", "") or "")
        if t and m:
            try:
                out[t] = float(m.group(1))
            except ValueError:
                pass
    return out


def _news_by_ticker(data: dict) -> dict:
    out: dict[str, list] = {}
    for n in data.get("news", []):
        t = n.get("ticker")
        if t:
            out.setdefault(t, []).append(n)
    return out


def _earnings_tickers(data: dict) -> set:
    return {e.get("ticker") for e in data.get("earnings", []) if e.get("ticker")}


def _vol_by_ticker(data: dict) -> dict:
    return {h.get("ticker"): h.get("realized_vol_pct")
            for h in data.get("price_history", []) if h.get("ticker")}


def _trend_by_ticker(data: dict) -> dict:
    return {t.get("ticker"): t for t in data.get("trends", []) if t.get("ticker")}


def _social_by_ticker(data: dict) -> dict:
    return {s.get("ticker"): s for s in data.get("social", []) if s.get("ticker")}


# 종목명(헤드라인이 회사를 실제 언급하는지 확인용)
COMPANY_NAMES = {
    "AAPL": ["apple"], "MSFT": ["microsoft"], "NVDA": ["nvidia"],
    "AMZN": ["amazon"], "GOOGL": ["google", "alphabet"], "META": ["meta", "facebook"],
    "TSLA": ["tesla"],
}
# 주가 '변동을 설명'하는 신호어 (이게 있어야 '왜 지금'으로 적합)
_MOVE_WORDS = ["surge", "soar", "jump", "rally", "rise", "rose", "gain", "climb", "spike",
               "fall", "fell", "drop", "plunge", "slump", "sink", "tumble", "slide", "sell-off",
               "selloff", "beat", "miss", "guidance", "upgrade", "downgrade", "earnings",
               "revenue", "profit", "deal", "launch", "lawsuit", "ban", "chip", "ai", "%"]
# '왜 지금'으로 부적합한 일반/리스티클/조언성 (변동 설명 아님)
_OFFTOPIC_WORDS = ["retirement", "how to", "you're probably", "best stocks", "should you buy",
                   "things to know", "what to know", "personal finance", "savings", "401(k)",
                   "credit card", "mortgage", "dividend aristocrat", "millionaire"]
# '왜 지금' 적합으로 채택할 최소 관련성 점수
WHY_NOW_MIN_SCORE = 3


def _why_now_score(sym: str, item: dict) -> int:
    title = (item.get("title") or item.get("content") or "").lower()
    if not title:
        return -99
    score = 0
    names = COMPANY_NAMES.get(sym, []) + [sym.lower()]
    if any(nm in title for nm in names):       # 회사를 실제 언급
        score += 3
    if any(w in title for w in _MOVE_WORDS):   # 변동을 설명하는 어휘
        score += 2
    if item.get("confidence") == "medium":
        score += 1
    if any(w in title for w in _OFFTOPIC_WORDS):  # 리스티클/조언성 → 강한 감점
        score -= 5
    return score


_CLAUSE_SPLIT = re.compile(r"\s*[;:|–—]\s+|\s+-\s+")
_PAREN = re.compile(r"\s*\([^)]*\)\s*$")


def _focus_clause(sym: str, headline: str) -> str:
    """헤드라인에서 포커스 종목을 언급하는 절만 추출(쇼츠 자막 길이 최적화).
    예: 'Stock Market Today: Dow Falls...; Nvidia Rallies On New Chip (Live)' → 'Nvidia Rallies On New Chip'.
    여러 절 중 회사명/티커 포함 절 우선, 없으면 원문 유지. 절단 시 verbatim 보존(말줄임 안 함)."""
    names = COMPANY_NAMES.get(sym, []) + [sym.lower()]
    clauses = [c.strip() for c in _CLAUSE_SPLIT.split(headline) if c.strip()]
    if len(clauses) <= 1:
        return headline.strip()
    for c in clauses:
        if any(nm in c.lower() for nm in names):
            return _PAREN.sub("", c).strip()   # 끝의 (…) 메타만 제거
    return headline.strip()


def _best_why_now(sym: str, news_items: list) -> dict | None:
    """'왜 지금' = 그 종목의 *변동을 설명하는* 뉴스. 관련성 임계 미달이면 None(틀린 이유 금지)."""
    if not news_items:
        return None
    ranked = sorted(news_items,
                    key=lambda n: (_why_now_score(sym, n), -(n.get("age_days") or 1e9)),
                    reverse=True)
    best = ranked[0]
    return best if _why_now_score(sym, best) >= WHY_NOW_MIN_SCORE else None


def _mover_parse(text: str):
    """movers claim text 'TICKER +5.45%' → (ticker, pct)."""
    parts = text.split()
    if not parts:
        return None
    sym = parts[0]
    m = _PCT_RE.search(text)
    if not m:
        return None
    try:
        return sym, float(m.group(1))
    except ValueError:
        return None


def _index_pct(text: str):
    """indices claim text 'S&P 500 (SPY) ▲ +0.25%, last 756.48' → (sym, pct)."""
    sm, pm = _SYM_RE.search(text), _PCT_RE.search(text)
    if not sm or not pm:
        return None
    try:
        return sm.group(1), float(pm.group(1))
    except ValueError:
        return None


def _score_symbol(sym, data, samedaypct, news_by, earn, vol_by, trend_by, social_by):
    """이슈+변동성 결합 점수 + 구성요소. issue_present 가 False 면 리드 후보에서 제외."""
    move_mag = abs(samedaypct.get(sym, 0.0))
    news_items = news_by.get(sym, [])
    news_count = len(news_items)
    has_earnings = sym in earn
    rv = vol_by.get(sym)
    tr = trend_by.get(sym)
    surge = (tr or {}).get("surge_pct")
    mentions = (social_by.get(sym) or {}).get("mentions") or 0

    # 변동성 기반(당일 변동) × 이슈 배수 + 카탈리스트/관심 보너스
    vol_term = move_mag
    issue_mult = 1.0 + W_NEWS * min(news_count, 5)
    attention = (W_TREND if (surge is not None and surge >= TREND_SURGE_MIN) else 0.0) \
        + W_SOCIAL * min(mentions, 5)
    composite = vol_term * issue_mult + (W_EARNINGS if has_earnings else 0.0) + attention

    issue_present = news_count > 0 or has_earnings
    return {
        "symbol": sym, "score": round(composite, 4), "issue_present": issue_present,
        "components": {"move_mag": round(move_mag, 4), "news_count": news_count,
                       "earnings_soon": has_earnings, "realized_vol_pct": rv,
                       "search_surge_pct": surge, "reddit_mentions": mentions},
    }


def select_topic(claims: dict, data: dict) -> dict:
    """이슈+변동성 결합 스코어링으로 소재 1건 선정. 후보·사유·구성요소를 함께 반환."""
    samedaypct = _samedaypct_by_ticker(data)
    news_by = _news_by_ticker(data)
    earn = _earnings_tickers(data)
    vol_by = _vol_by_ticker(data)
    trend_by = _trend_by_ticker(data)
    social_by = _social_by_ticker(data)

    # 주인공 후보(HERO_UNIVERSE = 메가캡 + 핵심 반도체/대표주, company-news 보유)별 결합 점수
    scored = [_score_symbol(s, data, samedaypct, news_by, earn, vol_by, trend_by, social_by)
              for s in HERO_UNIVERSE if s in samedaypct]
    scored.sort(key=lambda x: x["score"], reverse=True)
    candidates = [{"id": f"issue-{x['symbol']}", "kind": "issue_mover",
                   "symbol": x["symbol"], "score": x["score"],
                   "issue_present": x["issue_present"], "components": x["components"]}
                  for x in scored]

    # 오늘 가장 뜨거운 테마 탐지(뉴스 화제성 + 종목 움직임)
    theme_rank = score_themes(data)
    hottest = theme_rank[0] if theme_rank else None
    theme_summary = _theme_summary(hottest, samedaypct) if hottest else None

    # 후보 B: 시장 전반 방향(breadth) — 이슈 종목이 전무할 때 폴백
    idx = [r for r in (_index_pct(c.get("text", "")) for c in claims.get("indices", [])) if r]
    breadth = None
    if idx:
        ups = [s for s, p in idx if p > 0]
        downs = [s for s, p in idx if p < 0]
        avg_abs = sum(abs(p) for _, p in idx) / len(idx)
        consensus = max(len(ups), len(downs)) / len(idx)
        theme_txt = next((c["text"] for c in claims.get("themes", [])), None)
        breadth = {"symbols": [s for s, _ in idx], "theme": theme_txt,
                   "cite": "; ".join(c.get("cite", "") for c in claims.get("indices", [])),
                   "direction": ("higher" if len(ups) > len(downs) and consensus == 1.0
                                 else "lower" if len(downs) > len(ups) and consensus == 1.0
                                 else "mixed")}
        candidates.append({"id": "breadth", "kind": "market_breadth",
                           "score": round(avg_abs * consensus, 4)})

    # 선정 규칙(결정론):
    # 1) '오늘 가장 뜨거운 테마'의 주인공(이슈 보유) 우선 → 최신 트렌드 반영(사용자 지정 방향)
    # 2) 없으면 전체 이슈무버 1위
    issue_movers = [x for x in scored if x["issue_present"]]
    theme_present = set(hottest["present"]) if hottest else set()
    theme_issue = [x for x in scored if x["issue_present"] and x["symbol"] in theme_present]
    top_pure = max(scored, key=lambda x: x["components"]["move_mag"], default=None)

    win = theme_issue[0] if theme_issue else (issue_movers[0] if issue_movers else None)

    if win:
        chosen = _build_issue_mover_topic(win, samedaypct, news_by, vol_by, trend_by,
                                          social_by, data, claims)
        if theme_summary is not None:
            theme_summary["others"] = [r["name"] for r in theme_rank[1:3] if r["score"] > 0]
        chosen["theme"] = theme_summary
        comp = win["components"]
        led_by_theme = bool(theme_issue) and win["symbol"] in theme_present
        rationale = (
            (f"오늘 1위 테마 '{hottest['name']}'(뉴스{hottest['news_hits']}건·"
             f"{hottest['up']}/{hottest['n_present']}↑) 주인공 " if led_by_theme
             else "이슈+변동성 결합 1위 ")
            + f"{win['symbol']} (score={win['score']}; move={comp['move_mag']:+}% × news={comp['news_count']}"
            + (f", earnings_soon" if comp["earnings_soon"] else "")
            + (f", search+{comp['search_surge_pct']:.0f}%" if comp.get("search_surge_pct") else "")
            + ") → 이슈무버 리드")
    elif top_pure and top_pure["components"]["move_mag"] >= MOVER_LEAD_THRESHOLD:
        chosen = _build_mover_topic(
            {"symbol": top_pure["symbol"], "pct": samedaypct[top_pure["symbol"]],
             "cite": _first_mover_cite(top_pure["symbol"], claims)}, claims, breadth)
        rationale = (f"이슈 보유 종목 없음 → 최대 무버 {top_pure['symbol']} "
                     f"|{top_pure['components']['move_mag']}%| ≥ 임계 {MOVER_LEAD_THRESHOLD}% 단독 리드")
    elif breadth:
        chosen = _build_breadth_topic(breadth, None, claims)
        rationale = "이슈 보유 종목·임계 무버 없음 → 시장 전반(breadth) 리드"
    else:
        chosen = None
        rationale = "선정 가능한 검증 데이터 없음"

    return {"topic": chosen, "rationale": rationale, "candidates": candidates}


def _theme_summary(hottest: dict, samedaypct: dict) -> dict:
    """1위 테마 요약 — 이름·뉴스화제·상승종목수 + 당일 상위 무버(사실)."""
    movers = sorted(
        [{"ticker": t, "pct": round(samedaypct[t], 2)} for t in hottest["present"] if t in samedaypct],
        key=lambda m: abs(m["pct"]), reverse=True)[:5]
    lead = movers[0]["ticker"] if movers else None
    return {
        "name": hottest["name"], "news_hits": hottest["news_hits"],
        "up": hottest["up"], "n_present": hottest["n_present"],
        "avg_abs_pct": hottest["avg_abs_pct"], "top_movers": movers,
        "cite": (f"[finnhub](https://finnhub.io/api/v1/quote?symbol={lead})" if lead else ""),
    }


def _first_mover_cite(sym: str, claims: dict) -> str:
    for c in claims.get("movers", []):
        if (c.get("text", "").split()[:1] or [None])[0] == sym:
            return c.get("cite", "")
    return ""


def _talking_points(claims: dict, exclude_symbol: str | None) -> list[dict]:
    """토킹포인트 = 검증 claim 의 text+cite verbatim 인용(무출처 0). 보조 사실 위주."""
    pts = []
    theme = next((c for c in claims.get("themes", [])), None)
    if theme:
        pts.append({"text": theme["text"], "cite": theme.get("cite", ""), "from": "themes"})
    for c in claims.get("movers", []):
        if exclude_symbol and c.get("text", "").split()[:1] == [exclude_symbol]:
            continue
        pts.append({"text": c["text"], "cite": c.get("cite", ""), "from": "movers"})
        if len(pts) >= TALKING_POINTS_MAX:
            break
    return pts[:TALKING_POINTS_MAX]


def _co_universe(sym: str) -> list:
    """동반상승 후보 종목군 = sym 이 속한 테마 바스켓 + 섹터 피어(메가캡 아니어도 항상 채워짐)."""
    uni = []
    for th in THEMES.values():
        if sym in th["tickers"]:
            uni += th["tickers"]
    uni += SECTOR_PEERS.get(sym, [])
    return [t for t in dict.fromkeys(uni) if t != sym]


def _build_issue_mover_topic(win: dict, samedaypct, news_by, vol_by, trend_by,
                             social_by, data: dict, claims: dict) -> dict:
    """이슈무버 소재: 변동(사실) + '왜 지금'(뉴스 verbatim) + 연관종목(계산된 사실) + 변동성."""
    sym = win["symbol"]
    pct = samedaypct.get(sym, 0.0)
    verb = "advances" if pct > 0 else ("declines" if pct < 0 else "is flat")

    # '왜 지금' = 변동을 설명하는 뉴스 헤드라인(제3자 verbatim 인용 → 가드레일 advice 검사 제외 대상)
    bn = _best_why_now(sym, news_by.get(sym, []))
    why_now = None
    if bn:
        full = (bn.get("title") or bn.get("content") or "").strip()[:200]
        # Finnhub content = "headline. summary" → 헤드라인 제거분이 기사 요약(fallback)
        fh_title = (bn.get("title") or "").strip()
        content = (bn.get("content") or "").strip()
        fb_summary = content[len(fh_title):].lstrip(". ").strip() if content.startswith(fh_title) else ""
        # 실제 publisher 해석 + 본문 발췌 스크랩(네트워크, graceful)
        art = {}
        try:
            from ..article import enrich
            art = enrich(bn.get("url", ""), fb_summary)
        except Exception as e:
            log("WARN", f"기사 보강 실패(비차단): {type(e).__name__}", "stage03")
        publisher = art.get("publisher") or bn.get("source") or "source"
        canonical = art.get("canonical_url") or bn.get("url")
        why_now = {
            "headline": _focus_clause(sym, full), "full_headline": full,
            "summary": art.get("excerpt") or fb_summary or None,
            "scraped": art.get("scraped", False),
            "cite": (f"[{publisher}]({canonical})" if canonical else publisher),
            "url": canonical, "source": publisher, "confidence": bn.get("confidence"),
            "url_note": ("publisher-canonical" if art.get("scraped") else bn.get("url_note")),
        }

    # 연관종목 = 상관관계(계산된 사실). 강한 동행(strong) 우선 최대 2.
    corr = (data.get("correlations") or {})
    peers = (corr.get("pairs") or {}).get(sym, [])
    strong_first = sorted(peers, key=lambda p: (not p.get("strong"), -abs(p.get("corr", 0))))[:4]
    related = None
    if strong_first:
        related = {"peers": strong_first,
                   "cite": (f"[computed] Pearson correlation of daily returns "
                            f"(yfinance, n={corr.get('n_obs')}, {corr.get('period')})"),
                   "method": corr.get("method"), "n_obs": corr.get("n_obs"),
                   "period": corr.get("period")}

    # 동반상승(오늘 같이 움직인 생태계 종목) — 포커스 변동과 같은 방향, 변동폭 큰 순.
    same_dir = (lambda p: p > 0) if pct >= 0 else (lambda p: p < 0)
    co = []
    for peer in _co_universe(sym):
        ppct = samedaypct.get(peer)
        if ppct is not None and same_dir(ppct):
            co.append({"ticker": peer, "pct": round(ppct, 2),
                       "cite": f"[finnhub](https://finnhub.io/api/v1/quote?symbol={peer})"})
    co.sort(key=lambda x: abs(x["pct"]), reverse=True)
    co_movers = co[:6] if co else None

    # 레버리지 ETF(해당 종목 ±2배 추종) — 오늘 증폭된 변동.
    lev = []
    for etf in LEVERAGED_ETF.get(sym, []):
        epct = samedaypct.get(etf)
        if epct is not None:
            lev.append({"ticker": etf, "pct": round(epct, 2),
                        "cite": f"[finnhub](https://finnhub.io/api/v1/quote?symbol={etf})"})
    lev.sort(key=lambda x: abs(x["pct"]), reverse=True)
    leveraged = lev[:2] if lev else None

    rv = vol_by.get(sym)
    volatility = ({"realized_vol_pct": round(rv, 1),
                   "cite": f"[computed] annualized realized volatility (yfinance, {corr.get('period') or '3mo'})"}
                  if rv is not None else None)

    primary_cite = _first_mover_cite(sym, claims) or f"[finnhub](https://finnhub.io/api/v1/quote?symbol={sym})"

    return {
        "id": f"issue-{sym}", "kind": "issue_mover", "focus_symbol": sym,
        "angle": f"{sym} {verb} {pct:+.2f}% — here's what's driving the move.",
        "headline": f"Why {sym} is moving today",
        "chart": {"type": "price_line", "symbols": [sym]},
        "primary_fact": {"text": f"{sym} {pct:+.2f}%", "cite": primary_cite},
        "why_now": why_now,
        "co_movers": co_movers,
        "leveraged": leveraged,
        "related": related,
        "volatility": volatility,
        "talking_points": _talking_points(claims, exclude_symbol=sym),
        "score": win["score"], "score_components": win["components"],
    }


def _cite_of(item: dict) -> str:
    """뉴스/항목의 cite 표현 — 출처명 + url."""
    src = item.get("source") or "source"
    url = item.get("url")
    return f"[{src}]({url})" if url else src


def _build_mover_topic(mover: dict, claims: dict, breadth: dict | None) -> dict:
    sym, pct = mover["symbol"], mover["pct"]
    verb = "advances" if pct > 0 else "declines"
    return {
        "id": f"mover-{sym}", "kind": "single_mover", "focus_symbol": sym,
        "angle": f"{sym} {verb} {pct:+.2f}% — the session's largest verified megacap move.",
        "headline": f"{sym} {pct:+.2f}% on the day",
        "chart": {"type": "single_quote", "symbols": [sym]},
        "primary_fact": {"text": f"{sym} {pct:+.2f}%", "cite": mover.get("cite", "")},
        "talking_points": _talking_points(claims, exclude_symbol=sym),
        "score": round(abs(pct), 4),
    }


def _build_breadth_topic(breadth: dict, top_mover: dict | None, claims: dict) -> dict:
    theme = breadth.get("theme") or f"Index proxies closed {breadth['direction']} on the session."
    return {
        "id": "breadth", "kind": "market_breadth", "focus_symbol": None,
        "angle": theme,
        "headline": f"US indices {breadth['direction']} today",
        "chart": {"type": "index_panel", "symbols": breadth["symbols"]},
        "primary_fact": {"text": theme, "cite": breadth.get("cite", "")},
        "talking_points": _talking_points(claims, exclude_symbol=None),
        "score": None,
    }


def guardrail_violations(topic: dict | None) -> list[str]:
    """파이프라인이 직접 조립한 문장(angle/headline)만 검사. 토킹포인트/primary_fact 는
    stage02 claim verbatim 인용이라 stage02 가드레일을 이미 통과했으므로 재검사 제외."""
    if not topic:
        return []
    bad = []
    for field in ("angle", "headline"):
        text = topic.get(field, "") or ""
        for m in ADVICE_RE.finditer(text):
            bad.append(f"{m.group(0)!r} :: [{field}] {text[:80]}")
    return bad


def main() -> int:
    log("INFO", "=== STAGE ③ 소재 선정 시작 ===", "stage03")
    data = read_json(IN_PATH, default=None)
    if not data:
        log("ERROR", f"입력 없음: {IN_PATH} (stage01 먼저 실행 필요)", "stage03")
        return 2

    claims = build_claims(data)
    sel = select_topic(claims, data)
    topic = sel["topic"]
    if not topic:
        log("ERROR", f"소재 선정 실패: {sel['rationale']}", "stage03")
        return 3

    violations = guardrail_violations(topic)
    if violations:
        log("ERROR", f"가드레일 위반(투자권유/예측 표현) {len(violations)}건 — 단계 실패: "
                     f"{violations[:3]}", "stage03")
        return 4

    # ── P4: LLM 테마/공급망 연관기업 (2중 게이트, 비차단·fail-closed) ──
    if topic.get("kind") == "issue_mover" and topic.get("focus_symbol"):
        try:
            from ..theme_graph import build_theme_links
            sym = topic["focus_symbol"]
            fname = (COMPANY_NAMES.get(sym, [sym])[0]).title()
            tg = build_theme_links(sym, fname, _news_by_ticker(data).get(sym, []))
            if tg["links"]:
                topic["theme_links"] = tg["links"]
            topic["theme_audit"] = tg["audit"]
        except Exception as e:
            log("WARN", f"theme_graph 비차단 실패: {type(e).__name__} {str(e)[:120]}", "stage03")
        # R14: 트레이더 관점 행동가능 포인트 추출(catalyst/surprise/risk/related태그/hook/payoff)
        try:
            from ..trader_analysis import analyze
            topic["trader_analysis"] = analyze(
                topic["focus_symbol"], data, topic.get("why_now") or {},
                (topic.get("related") or {}).get("peers", []))
        except Exception as e:
            log("WARN", f"trader_analysis 비차단 실패: {type(e).__name__} {str(e)[:120]}", "stage03")

    out = {
        "schema_version": "1.0", "pipeline_id": "shorts_maker", "machine": "mac",
        "stage": 3, "agent": "Producer", "generated_utc": utc_now(),
        "date": data.get("date") or today_utc(), "source_file": IN_PATH.name,
        "topic": topic, "rationale": sel["rationale"], "candidates": sel["candidates"],
        "guardrail": {"advice_violations": 0},
    }
    write_json_atomic(OUT_PATH, out)
    log("INFO", f"=== STAGE ③ 완료: topic={topic['id']} kind={topic['kind']} "
                f"chart={topic['chart']['type']} points={len(topic['talking_points'])} ===", "stage03")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
