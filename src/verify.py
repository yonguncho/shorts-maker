"""verify.py — ① RAG 신빙성 검증 + Codex 공방.

검증 규칙:
  - 출처 등급제: SEC(1) > 뉴스/시장데이터(2) > 집계(3)  (rag_store.SOURCE_GRADE)
  - 신선도: published/fetched 가 최근 MAX_AGE_DAYS 이내 (주말·휴장 고려한 창)
  - 출처 추적: url/source 없으면 폐기 (환각 차단)
  - 교차검증: 같은 사실을 뒷받침하는 서로 다른 출처 수
  - 신뢰도 등급: 위 요소를 종합해 high/medium/low, low/stale/무출처는 폐기 대상
Codex 공방: 데이터셋 신빙성을 공격 → 방어자(rule-based)가 약한 항목 제거/주석 → 재공격. PASS&≥2R.
"""
from __future__ import annotations
import json as _json_mod
from datetime import datetime, timezone

from .common import utc_now, today_utc, write_json_atomic, STATE_DIR, log
from . import rag_store
from .codex_bridge import debate


def _safe_json(s):
    try:
        return _json_mod.loads(s) if s else {}
    except (ValueError, TypeError):
        return {}

MAX_AGE_DAYS = 5          # 주말/휴장 커버 (당일 우선, 창은 5일)
OUT_PATH = STATE_DIR / "verified_market_data.json"

# 미국 증시 관련성 키워드 (뉴스 selection criteria — Codex "weak relevance" 대응)
RELEVANCE_KW = [
    "stock", "shares", "market", "s&p", "sp500", "s&p 500", "nasdaq", "dow",
    "wall street", "equit", "fed", "federal reserve", "rate", "inflation", "cpi",
    "earnings", "treasury", "yield", "bond", "dollar", "economy", "gdp", "jobs",
    "payroll", "tariff", "oil", "crude", "nvidia", "apple", "tesla", "microsoft",
    "amazon", "meta", "google", "alphabet", "etf", "index", "ipo", "merger",
    "guidance", "revenue", "profit", "recession", "bull", "bear", "rally", "sell-off",
]

# 우리 워치리스트(이 티커에 직접 태깅된 company-news 는 항상 관련)
WATCH_TICKERS = {"SPY", "QQQ", "DIA", "IWM", "AAPL", "MSFT", "NVDA", "AMZN",
                 "GOOGL", "META", "TSLA", "VIXY"}

# 오프스코프 제외 키워드 (Codex 지적: 인도/사우디/크립토/주택/개인재테크/리스티클/비상장 등 미국증시 무관 혼입)
# 워치리스트 태깅 뉴스라도 이 키워드가 있으면 드롭(태깅 우회 버그 차단).
EXCLUDE_KW = [
    "india", "indian", "saudi", "qatar", "guyana", "bollywood", "cricket", "k-pop", "kpop",
    "polymarket", "crypto", "bitcoin", "ethereum", "dogecoin", "xrp", "casino", "lottery",
    "minimum wage", "housing", "real estate", "mortgage", "music", "soccer", "football",
    # 개인재테크/조언/리스티클 (하드 시장데이터 아님)
    "retirement", "savings", "401(k)", "401k", "credit card", "personal finance",
    "how to", "you're probably", "best stocks", "should you buy", "things to know",
    "what to know", "millionaire", "dividend aristocrat", "guide to",
    # 비상장 기업 IPO 추측 (Codex: private-company speculation)
    "spacex", "starlink",
]

# 의견/해설/조언/리스티클 신호 (하드데이터 아님 → low 강등)
OPINION_KW = [
    "opinion", "commentary", "op-ed", "column", "analysis:", "/opinion", "editorial",
    "how to", "you're probably", "best stocks", "should you", "things to know",
    "what to know", "vs ", "which should", "guide to", "believes", "thinks", "my guide",
    "here's how", "here's what", "could", "might", "may ", "predict", "forecast", "outlook",
]

# 보도자료/홍보성 출처 (하드데이터 아님 → low)
PROMO_SRC = {"globenewswire", "globe newswire", "business wire", "businesswire",
             "pr newswire", "prnewswire", "accesswire", "newsfile", "motley fool", "zacks"}

# 스크리너/오피니언 위주 출처 (하드 시장뉴스 아님 → low)
LOW_SOURCES = {"chartmill", "seekingalpha", "seeking alpha", "insider monkey", "insidermonkey",
               "simply wall st", "simplywall", "gurufocus", "tipranks", "investorplace",
               "247 wall st", "24/7 wall st", "the globe and mail", "talkmarkets"}

# 하드뉴스 출처(클린 금융 와이어만) — 이들에서 나오고 오피니언/리스티클 패턴이 없을 때만 medium 승격.
# Yahoo/Forbes/CNN 등 애그리게이터는 listicle/PR/오피니언을 섞어 나르므로 hard 에서 제외 → 기본 low.
HARD_NEWS_SRC = {"reuters", "cnbc", "bloomberg", "associated press", "the wall street journal",
                 "wall street journal", "wsj", "marketwatch", "barron", "financial times",
                 "the new york times"}

# 리스티클/오피니언/애널리스트의견/PR 제목 패턴 (→ low, 하드데이터 아님)
import re as _re_mod
LISTICLE_OPINION_RE = _re_mod.compile(
    r"\([A-Z]{2,5}\):"                                  # "(GOOGL):" 종목 리스티클
    r"|stock pick|stocks? to (buy|watch|research|consider|own|avoid)"
    r"|best stock|top \d+|\d+ (stocks?|cash|things|reasons|charts)"
    r"|things to (watch|know)|curated list|portfolio includes|rank among"
    r"|cash-burning|cash-producing|picking up|we'?re (buying|picking|adding)"
    r"|cramer|downgrade|upgrade|analyst call|price target|buy rating|sell rating"
    r"|raised to|cut to|initiated|reiterat|how to|you'?re probably|should you"
    r"|premier stock|best buy downgrade"
    # 오피니언 칼럼/프리뷰/추천 어조
    r"|morning bid|who needs|eerily similar|big things|things we'?re watching"
    r"|themes that drove|week ahead|to buy\?|what to watch|here'?s why|here'?s what",
    _re_mod.IGNORECASE)

# PR/홍보성 제목(제품 출시·제휴 발표 등 — 하드 시장뉴스 아님 → 드롭)
PR_RE = _re_mod.compile(
    r"\b(unveil|unveils|launches|launched|introduc|partners with|partnership|announces"
    r"|rolls out|debuts|to challenge|product)\b", _re_mod.IGNORECASE)


def _drop_news(item: dict) -> bool:
    """뉴스 데이터셋에서 아예 제외할 잡음 판정(off-scope/오피니언/리스티클/PR/스크리너 출처).
    시장 관련 일반 애그리게이터 뉴스는 남긴다(아래 _finalize_news 에서 low 로 분류)."""
    title = item.get("title") or item.get("content") or ""
    src = (item.get("source") or "").lower()
    if not _market_relevant(item):
        return True
    if any(s in src for s in LOW_SOURCES) or any(s in src for s in PROMO_SRC):
        return True
    if LISTICLE_OPINION_RE.search(title) or PR_RE.search(title):
        return True
    low_t = title.lower()
    if any(k in low_t for k in OPINION_KW):   # 광의 오피니언/예측/조언 어휘
        return True
    if low_t.startswith("prediction") or "box office" in low_t or "won big" in low_t:
        return True
    return False


def _market_relevant(item: dict) -> bool:
    text = f"{item.get('title','')} {item.get('content','')}".lower()
    if any(k in text for k in EXCLUDE_KW):                     # 오프스코프 최우선 배제(태깅 우회 차단)
        return False
    if (item.get("ticker") or "").upper() in WATCH_TICKERS:   # 그 다음, 종목 태깅된 속보는 관련
        return True
    return any(kw in text for kw in RELEVANCE_KW)


def _url_note(url: str | None) -> str:
    if not url:
        return "no-url"
    u = url.lower()
    if "news.google." in u or "/rss/" in u:
        return "aggregator(Google News RSS redirect)"
    if "finnhub.io/api" in u:
        return "aggregator(Finnhub redirect, not publisher-canonical)"
    return "canonical"


def _age_days(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        dt = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0
    except ValueError:
        return None


_OPINION_KW = OPINION_KW   # 위에서 확장 정의(조언/리스티클/예측 포함)
_STOP = {"the", "and", "for", "with", "from", "this", "that", "are", "was", "will",
         "has", "have", "after", "over", "into", "amid", "says", "say", "new", "more",
         "u.s.", "us", "as", "on", "in", "of", "to", "a", "is", "it", "its", "by", "at"}


def evaluate_item(conn, doc: dict) -> dict:
    """기초 평가만(출처/신선도/등급). confidence·cross_sources 는 kind별 finalize 에서 확정."""
    has_source = bool(doc.get("url")) and bool(doc.get("source"))
    age = _age_days(doc.get("published_utc") or doc.get("fetched_utc"))
    fresh = age is not None and age <= MAX_AGE_DAYS
    return {
        "id": doc["id"], "kind": doc["kind"], "ticker": doc.get("ticker"),
        "title": doc.get("title"), "content": doc.get("content"),
        "source": doc.get("source"), "source_type": doc.get("source_type"),
        "grade": doc.get("grade", 3), "url": doc.get("url"),
        "published_utc": doc.get("published_utc"),
        "age_days": round(age, 2) if age is not None else None,
        "fresh": fresh, "has_source": has_source,
        "cross_sources": 1, "confidence": None, "labels": [],
    }


def _finalize_quote(x: dict) -> dict:
    """단일벤더 가격: 사실이지만 독립검증 없음 → 최대 medium, 명시 라벨."""
    x["cross_sources"] = 1
    if not x["has_source"]:
        x["confidence"] = "discard"
    elif not x["fresh"]:
        x["confidence"] = "low"
    else:
        x["confidence"] = "medium"   # high 아님(단일벤더)
    x["labels"].append("vendor_single_source: Finnhub 최신 체결/호가, 사실 수치이나 독립검증 없음")
    x["timestamp_note"] = "published_utc = 제공자 마지막 체결/호가 시각(장중/종가 혼재 가능, 실시간 보장 없음)"
    return x


def _finalize_earnings(x: dict) -> dict:
    """실적 캘린더: 예정된 이벤트(사실). 단일 벤더(Finnhub) → 최대 medium. 미래일자라 신선도 강등 없음."""
    x["cross_sources"] = 1
    x["confidence"] = "discard" if not x["has_source"] else "medium"
    x["labels"].append("earnings calendar (Finnhub) — scheduled catalyst, single vendor")
    return x


def _finalize_filing(x: dict) -> dict:
    x["cross_sources"] = 1
    if not x["has_source"]:
        x["confidence"] = "discard"
    elif not x["fresh"]:
        x["confidence"] = "low"
    else:
        x["confidence"] = "high"     # SEC 1차 출처
    x["labels"].append("SEC primary source (grade1)")
    return x


def _sig_tokens(title: str) -> set:
    return {w for w in (title or "").lower().replace(",", " ").replace(".", " ").split()
            if len(w) > 3 and w not in _STOP}


def _finalize_news(news: list[dict]) -> list[dict]:
    """뉴스 교차검증 실집계: 같은 사안(제목 토큰 2개+ 겹침)을 다룬 서로 다른 출처 수."""
    toks = [(_sig_tokens(x["title"]), x) for x in news]
    for ts, x in toks:
        sources = {x["source"]}
        for ts2, y in toks:
            if y is x:
                continue
            if len(ts & ts2) >= 2:
                sources.add(y["source"])
        x["cross_sources"] = len(sources)
        src = (x.get("source") or "").lower()
        # 오피니언/PR/리스티클/스크리너는 _drop_news 에서 이미 데이터셋에서 제외됨.
        # 여기 남은 건 시장관련 뉴스 → 하드뉴스 출처면 medium, 애그리게이터면 low(인용/맥락용).
        is_hard_src = any(s in src for s in HARD_NEWS_SRC)
        if not x["has_source"]:
            x["confidence"] = "discard"
        elif not x["fresh"]:
            x["confidence"] = "low"
        elif not is_hard_src:
            x["confidence"] = "low"
            x["labels"].append("aggregator/non-hard-news source — 사실 보도로만 인용, 하드 주장 미사용(low)")
        else:
            # 하드뉴스 출처 → 최대 medium. high 는 SEC 1차에만.
            x["confidence"] = "medium"
            if x["cross_sources"] >= 2:
                x["labels"].append(
                    f"title-overlap heuristic: {x['cross_sources']} sources share headline tokens "
                    f"(NOT independent confirmation — may be syndication/aggregator dupes; stays medium)")
            else:
                x["labels"].append("single-source news — 사실 보도로만 사용")
    return news


def build_dataset(conn) -> dict:
    # quote: search 는 grade ASC·published DESC → ticker 첫 등장이 최신. 재실행 누적 대비 최신 1건만.
    quotes_all = [_finalize_quote(evaluate_item(conn, d)) for d in rag_store.search(conn, kind="quote", limit=200)]
    quotes_by: dict = {}
    for q in quotes_all:
        quotes_by.setdefault(q.get("ticker"), q)
    quotes = list(quotes_by.values())

    filings = [_finalize_filing(evaluate_item(conn, d)) for d in rag_store.search(conn, kind="filing", limit=100)]
    news_all = [evaluate_item(conn, d) for d in rag_store.search(conn, kind="news", limit=200)]

    # earnings: ticker+date 중복 제거(최신 fetched 우선)
    earnings, eseen = [], set()
    for d in rag_store.search(conn, kind="earnings", limit=80):
        x = _finalize_earnings(evaluate_item(conn, d))
        k = (x.get("ticker"), (x.get("published_utc") or "")[:10])
        if k in eseen:
            continue
        eseen.add(k)
        earnings.append(x)

    # 뉴스: 관련성 필터 + 제목 중복 제거 (selection criteria 명시)
    seen, seen_urls, news = set(), set(), []
    dropped_irrelevant = 0
    for it in news_all:
        key = (it.get("title") or "").strip().lower()[:80]
        url = (it.get("url") or "").strip().lower()
        if _drop_news(it):   # off-scope/오피니언/리스티클/PR/스크리너 → 데이터셋에서 제외
            dropped_irrelevant += 1
            continue
        if key in seen or (url and url in seen_urls):   # 제목 또는 URL 중복 제거
            continue
        seen.add(key)
        if url:
            seen_urls.add(url)
        it["url_note"] = _url_note(it.get("url"))
        news.append(it)
    news = _finalize_news(news)   # 교차검증 실집계 + 의견 분리 + confidence 확정
    corroborated = sum(1 for x in news if x["cross_sources"] >= 2)

    # ── 멀티소스 신호(P2~P3) — 새 RAG 종류를 다운스트림(소재선정/차트)로 전파 ──
    # 과거 시계열(yfinance, grade2) — 실현변동성 포함. '사실 시계열, 단일벤더 → medium'.
    # search 는 published DESC → ticker 첫 등장이 최신. 재실행 누적 대비 ticker별 최신 1건만.
    price_history, _hseen = [], set()
    for d in rag_store.search(conn, kind="history", limit=120):
        t = d.get("ticker")
        if t in _hseen:
            continue
        _hseen.add(t)
        ex = _safe_json(d.get("extra_json"))
        price_history.append({
            "ticker": t, "content": d.get("content"),
            "source": d.get("source"), "url": d.get("url"),
            "realized_vol_pct": ex.get("realized_vol_pct"),
            "period_change_pct": ex.get("period_change_pct"),
            "rsi14": ex.get("rsi14"), "high_52w": ex.get("high_52w"),
            "low_52w": ex.get("low_52w"), "pct_off_52w_high": ex.get("pct_off_52w_high"),
            "vol_vs_30d_avg": ex.get("vol_vs_30d_avg"),
            "period": ex.get("period"), "confidence": "medium",
            "labels": ["yfinance historical+indicators (vendor, grade2) — 사실 시계열, 독립검증 없음"],
        })

    # 상관관계 연관종목(derived) — 계산된 사실(예측 아님). 가드레일 안전지대. ticker별 최신만.
    correlations = {"pairs": {}, "method": None, "n_obs": None, "period": None}
    for d in rag_store.search(conn, kind="derived", limit=120):
        if d.get("source") != "correlation_engine" or not d.get("ticker"):
            continue
        if d["ticker"] in correlations["pairs"]:   # 이미 최신 채택 → skip
            continue
        ex = _safe_json(d.get("extra_json"))
        correlations["pairs"][d["ticker"]] = ex.get("peers", [])
        if correlations["method"] is None:
            correlations.update({"method": ex.get("method"), "n_obs": ex.get("n_obs"),
                                 "period": ex.get("period")})

    # 검색량(Google Trends) / 소셜(Reddit) — 🟡 '사실귀속'(검색관심/언급횟수)으로만, 심리·조언 아님.
    def _latest_by_ticker(kind):
        out, seen = [], set()
        for d in rag_store.search(conn, kind=kind, limit=120):
            if d.get("ticker") in seen:
                continue
            seen.add(d.get("ticker"))
            out.append(d)
        return out

    trends = [{"ticker": d.get("ticker"), "content": d.get("content"),
               "surge_pct": _safe_json(d.get("extra_json")).get("surge_pct"),
               "source": "google_trends", "url": d.get("url"), "confidence": "low",
               "labels": ["search-interest signal — '검색 관심' 사실귀속으로만(심리/조언 아님)"]}
              for d in _latest_by_ticker("trend")]
    social = [{"ticker": d.get("ticker"), "content": d.get("content"),
               "mentions": _safe_json(d.get("extra_json")).get("mentions"),
               "source": "reddit", "url": d.get("url"), "confidence": "low",
               "labels": ["retail-attention signal — '언급 횟수' 사실귀속으로만"]}
              for d in _latest_by_ticker("social")]

    return {
        "schema_version": "1.0", "pipeline_id": "shorts_maker", "machine": "mac",
        "generated_utc": utc_now(), "date": today_utc(),
        "session_context": (
            "가격은 수집 시점에 Finnhub 가 반환한 최신 값이다. 미국 정규장 시간대에는 장중(intraday) 값일 수 있고, "
            "장 마감 후에는 직전 세션 종가다. quote published_utc 는 제공자의 마지막 체결/호가 시각이며, "
            "OHLC 는 해당 거래일 기준. 실시간 보장 없음(지연 가능)."
        ),
        "verification": {
            "rules": ["source_grade(SEC=1차>news/quote=2차)", "freshness<=%dd(quote/news)" % MAX_AGE_DAYS,
                      "source_required(무출처 폐기)", "cross_check(뉴스 제목토큰 겹침 집계, 단 high 승격 안 함)",
                      "confidence=정직(quote/news≤medium, SEC=high, 의견/PR=low)",
                      "us_relevance_filter(+오프스코프 배제)", "title_dedupe", "opinion_pr_separation"],
            "max_age_days": MAX_AGE_DAYS,
            "news_selection": ("DROP: off-scope(개인재테크/크립토/주택/스포츠/비상장) + opinion/listicle/"
                               "screener-source + PR(제품출시·제휴) 는 데이터셋에서 완전 제외. "
                               "KEEP: 시장관련 뉴스만 — 하드뉴스 출처(Reuters/CNBC/Bloomberg/WSJ 등)=medium, "
                               "애그리게이터(Yahoo 등)=low(출처표기 인용·맥락용으로만, 하드 주장엔 미사용). "
                               "제목 또는 URL 중복 제거."),
            "dropped_offscope_opinion_pr_news": dropped_irrelevant,
            "news_title_overlap_2plus": corroborated,
            "cross_check_result": ("xref 는 '제목 토큰 겹침' 휴리스틱일 뿐 독립 확증이 아니다(신디케이션/애그리게이터 "
                                   "중복일 수 있음). 어떤 뉴스도 이 때문에 high 로 승격되지 않으며 전부 ≤medium. "
                                   "title-overlap≥2 건수=%d." % corroborated),
            "known_limitations": [
                "가격은 단일 벤더(Finnhub) — confidence≤medium, 사실 수치로만 사용, 독립 재검증 미적용",
                "quote 는 장중(intraday)/종가가 혼재할 수 있음 — published_utc(제공자 체결/호가 시각)로 판단, 실시간 보장 없음",
                "뉴스 URL 다수가 Google News/Finnhub 리다이렉트(publisher-canonical 아님) — url_note 로 명시",
                "시장 변동성은 VIXY(VIX 추종 ETF) 프록시 — 종목별 내재변동성(옵션 IV)은 무료 티어 미제공",
                "실적 캘린더는 예정 이벤트(미래) — EPS/매출은 '추정치'이며 실적 발표 시 갱신됨",
                "뉴스 감성 점수는 미수집(프리미엄) — 감성은 헤드라인 휴리스틱으로만, 정량 점수 아님",
            ],
        },
        "market_snapshot": quotes, "news": news, "filings": filings, "earnings": earnings,
        "price_history": price_history, "correlations": correlations,
        "trends": trends, "social": social,
        "rag_stats": rag_store.stats(conn),
    }


def _filter_accepted(dataset: dict) -> dict:
    """confidence=discard 인 항목 제거(무출처 폐기). 반환: 폐기 수 기록된 dataset."""
    dropped = 0
    for key in ("market_snapshot", "news", "filings", "earnings"):
        kept = [x for x in dataset[key] if x["confidence"] != "discard"]
        dropped += len(dataset[key]) - len(kept)
        dataset[key] = kept
    dataset.setdefault("verification", {})["dropped_no_source"] = dropped
    return dataset


def dataset_to_payload(dataset: dict) -> str:
    """Codex 공방용 요약. 잘림 없이 전 항목·전 수치·타임스탬프·출처주석을 그대로 노출(감사 가능)."""
    def lbl(x):
        return (" {" + "; ".join(x.get("labels", [])) + "}") if x.get("labels") else ""

    def q_line(x):
        return (f"- {x['ticker']}: {x['content']}  "
                f"[quote_ts={x.get('published_utc')} src={x['source']}(grade{x['grade']}) "
                f"fresh={x['fresh']} conf={x['confidence']}]{lbl(x)}")

    def n_line(x):
        return (f"- [{x['confidence']}|grade{x['grade']}|src={x['source']}|"
                f"pub={x.get('published_utc')}|url={x.get('url_note','?')}|xref={x['cross_sources']}] "
                f"{x['title']} :: {x['content'] or ''}  <{x['url']}>{lbl(x)}")

    def f_line(x):
        return (f"- {x['title']} [src=SEC_EDGAR(grade1) pub={x.get('published_utc')} "
                f"conf={x['confidence']}] <{x['url']}>{lbl(x)}")

    def h_line(x):
        return (f"- {x['ticker']}: {x['content']} [src=yfinance(grade2) conf={x['confidence']}]"
                f"{lbl(x)}")

    def sig_line(x):
        return (f"- {x['ticker']}: {x['content']} [src={x['source']} conf={x['confidence']}]{lbl(x)}")

    q = "\n".join(q_line(x) for x in dataset["market_snapshot"]) or "  (none)"
    n = "\n".join(n_line(x) for x in dataset["news"]) or "  (none)"
    f = "\n".join(f_line(x) for x in dataset["filings"]) or "  (none)"
    nq, nn, nf = len(dataset["market_snapshot"]), len(dataset["news"]), len(dataset["filings"])

    # 멀티소스 신호(있을 때만) — 감사 가능하게 노출
    hist = dataset.get("price_history", [])
    corr = dataset.get("correlations", {}) or {}
    trends = dataset.get("trends", [])
    social = dataset.get("social", [])
    extra = ""
    if hist:
        extra += (f"\nPRICE HISTORY — showing all {len(hist)} (yfinance, grade2, "
                  f"실현변동성 포함):\n" + "\n".join(h_line(x) for x in hist) + "\n")
    if corr.get("pairs"):
        cl = "\n".join(
            f"- {t}: " + ", ".join(f"{p['peer']}(r={p['corr']:+.2f})" for p in peers)
            for t, peers in corr["pairs"].items())
        extra += (f"\nCORRELATED PEERS — derived/computed fact (method={corr.get('method')}, "
                  f"n={corr.get('n_obs')}, period={corr.get('period')}; NOT a forecast):\n{cl}\n")
    if trends:
        extra += (f"\nSEARCH-INTEREST (Google Trends) — 사실귀속 신호({len(trends)}):\n"
                  + "\n".join(sig_line(x) for x in trends) + "\n")
    if social:
        extra += (f"\nRETAIL-ATTENTION (Reddit) — 사실귀속 신호({len(social)}):\n"
                  + "\n".join(sig_line(x) for x in social) + "\n")

    return (
        f"DATE: {dataset['date']}  GENERATED: {dataset['generated_utc']}\n"
        f"SESSION CONTEXT: {dataset.get('session_context','')}\n"
        f"VERIFICATION: {dataset['verification']}\n"
        f"(아래는 채택된 전체 항목 — 잘림 없음. 표시 개수 = 실제 개수)\n\n"
        f"MARKET SNAPSHOT — showing all {nq} of {nq} quotes:\n{q}\n\n"
        f"NEWS — showing all {nn} of {nn} accepted (relevance-filtered, deduped):\n{n}\n\n"
        f"FILINGS — showing all {nf} of {nf} (SEC primary, grade1):\n{f}\n"
        f"{extra}"
    )


def _quote_is_sane(x: dict) -> bool:
    """malformed quote 폐기: extra 파싱해 price/prev_close 가 양수인지 확인."""
    import json as _json
    try:
        raw = _json.loads((x.get("content") or ""))  # content 는 문자열이라 보통 실패 → 아래로
    except Exception:
        raw = {}
    c = x.get("content") or ""
    # content 문자열에서 price=, prev_close= 추출
    import re as _re
    def num(field):
        m = _re.search(field + r"=([-\d.]+)", c)
        return float(m.group(1)) if m else None
    price, pc = num("price"), num("prev_close")
    return (price is not None and price > 0) and (pc is not None and pc > 0)


def make_defender(dataset: dict):
    """Codex 공격을 받아 약한 항목을 결정론적으로 제거/주석하고 갱신 payload 반환.

    표현 결함은 dataset_to_payload 에서 이미 제거(잘림 없음/정직한 카운트/타임스탬프/주석).
    여기서는 실제 데이터 품질을 강화: malformed·stale·low 제거 + 단일출처 주석.
    """
    state = {"dataset": dataset}

    def defender(attack: dict, round_no: int):
        ds = state["dataset"]
        notes = []
        # 1) malformed quote 제거
        before = len(ds["market_snapshot"])
        ds["market_snapshot"] = [x for x in ds["market_snapshot"] if _quote_is_sane(x)]
        if len(ds["market_snapshot"]) != before:
            notes.append(f"quotes: {before}→{len(ds['market_snapshot'])} (malformed 제거)")
        # 2) 가격/공시: stale+low 제거(강한 정제). 뉴스: stale 만 제거하고 low 는 '정직 라벨'로 유지
        #    (오피니언/애그리게이터는 low 로 정직 표기 → 인용/맥락용으로만 사용, 하드 주장엔 미사용).
        for key in ("market_snapshot", "filings"):
            before = len(ds[key])
            ds[key] = [x for x in ds[key] if x["fresh"] and x["confidence"] != "low"]
            if len(ds[key]) != before:
                notes.append(f"{key}: {before}→{len(ds[key])} (stale/low 제거)")
        before = len(ds["news"])
        ds["news"] = [x for x in ds["news"] if x["fresh"]]   # 뉴스는 stale 만 제거, low 는 유지(정직 라벨)
        if len(ds["news"]) != before:
            notes.append(f"news: {before}→{len(ds['news'])} (stale 제거; low 는 정직 라벨 유지)")
        # 3) 라벨은 finalize 단계에서 이미 정직하게 부착됨(단일벤더/의견/교차검증).
        if not notes:
            notes.append("추가 제거 없음 — 정직한 전체 노출로 방어")
        state["dataset"] = ds
        return dataset_to_payload(ds), "; ".join(notes)

    return defender, state


def run(conn) -> dict:
    dataset = build_dataset(conn)
    dataset = _filter_accepted(dataset)
    defender, state = make_defender(dataset)
    log("INFO", "Codex 신빙성 공방 시작 (min 2R)", "verify")
    result = debate(subject="Analyst data credibility (US market data)",
                    payload_text=dataset_to_payload(dataset), defender=defender,
                    min_rounds=2, max_rounds=4)
    final = state["dataset"]
    final["credibility_debate"] = {
        "status": result["status"], "total_rounds": result["total_rounds"],
        "rounds": [{"round": r["round"], "engine": r["attack"]["engine"],
                    "verdict": r["attack"]["verdict"], "issues": r["attack"].get("issues", []),
                    "defense": r["defense_notes"]} for r in result["rounds"]],
    }
    write_json_atomic(OUT_PATH, final)
    log("INFO", f"verified_market_data.json 저장 (debate={result['status']}, "
                f"{result['total_rounds']}R)", "verify")
    return final
