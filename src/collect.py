"""collect.py — ① 데이터 수집 (Finnhub 가격·뉴스 + SEC EDGAR 공시).

모든 수집 항목은 출처 메타와 함께 RAG 저장소(rag_store)에 적재된다.
키는 .env 에서만 읽는다(common.require_env). 값은 로그하지 않는다.
"""
from __future__ import annotations
import json
import time
from datetime import datetime, timezone, timedelta

import requests

from .common import require_env, load_env, log, utc_now, today_utc
from . import rag_store

FINNHUB = "https://finnhub.io/api/v1"

# 미국 증시 동향용 워치리스트: 지수 ETF 프록시 + 메가캡
INDEX_PROXIES = ["SPY", "QQQ", "DIA", "IWM"]
MEGACAPS = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA"]
WATCHLIST = INDEX_PROXIES + MEGACAPS
VOL_PROXY = "VIXY"   # VIX 추종 ETF — 종목별 IV(옵션데이터)는 무료 티어 차단 → 시장 변동성 프록시

# ── 종목 생태계(섹터/공급망 동행 후보) — '진짜 연관종목'의 단일 진실 ──
# 메가캡별 실제 산업 생태계. 상관관계 유니버스를 여기까지 넓혀야 "NVDA→AMD/TSM/SMCI" 같은
# 의미있는 동행 종목이 나온다(메가캡끼리만 보면 '다 같이 움직인다'는 뻔한 결과만 나옴).
SECTOR_PEERS = {
    "NVDA": ["AMD", "TSM", "SMCI", "ARM", "MU", "AVGO", "MRVL", "ASML"],
    "AAPL": ["AVGO", "QCOM", "TSM", "MU", "SWKS", "GLW"],
    "MSFT": ["ORCL", "CRM", "NOW", "PLTR", "AMD", "SMCI"],
    "AMZN": ["SHOP", "WMT", "MSFT", "GOOGL", "SE"],
    "GOOGL": ["META", "MSFT", "AMZN", "TTD", "PLTR"],
    "META": ["GOOGL", "SNAP", "PINS", "RDDT", "TTD"],
    "TSLA": ["RIVN", "LCID", "NIO", "GM", "F", "ON", "ALB"],
}
# 단일종목 레버리지 ETF (해당 종목 일일 ±2배 추종) — 동반 '증폭' 변동, 눈길끄는 사실 데이터.
LEVERAGED_ETF = {
    "NVDA": ["NVDX", "NVDL"],
    "TSLA": ["TSLL"],
    "AAPL": ["AAPU"],
    "MSFT": ["MSFU"],
    "AMZN": ["AMZU"],
}

# ── 테마(섹터 트렌드) — '오늘 가장 뜨거운 이슈'를 뉴스+움직임으로 탐지하기 위한 단일 진실 ──
# 각 테마 = 뉴스 키워드 + 대표 종목 바스켓. stage03 이 테마별 점수를 매겨 소재 테마를 고른다.
THEMES = {
    "AI & Semiconductors": {
        "kw": ["ai", "artificial intelligence", "chip", "semiconductor", "gpu", "data center",
               "nvidia", "foundry", "accelerator", "llm", "compute", "blackwell", "hbm"],
        "tickers": ["NVDA", "AMD", "TSM", "SMCI", "ARM", "MU", "AVGO", "MRVL", "ASML", "QCOM", "INTC"],
    },
    "Space & Satellite": {
        "kw": ["space", "satellite", "rocket", "launch", "lunar", "orbital", "spacex",
               "starlink", "moon", "defense", "missile", "hypersonic"],
        "tickers": ["RKLB", "LUNR", "ASTS", "RDW", "PL", "BA", "LMT", "RTX", "NOC"],
    },
    "EV & Battery": {
        "kw": ["ev", "electric vehicle", "battery", "charging", "lithium", "autonomous",
               "robotaxi", "fsd", "self-driving", "solar"],
        "tickers": ["TSLA", "RIVN", "LCID", "NIO", "GM", "F", "ALB", "ENPH", "FSLR"],
    },
    "Crypto-linked": {
        "kw": ["bitcoin", "crypto", "ethereum", "blockchain", "coinbase", "mining", "btc", "stablecoin"],
        "tickers": ["COIN", "MSTR", "MARA", "RIOT", "HOOD"],
    },
    "Cloud & Software": {
        "kw": ["cloud", "software", "saas", "enterprise", "azure", "aws", "cybersecurity", "data platform"],
        "tickers": ["MSFT", "GOOGL", "AMZN", "CRM", "NOW", "SNOW", "NET", "DDOG", "PLTR", "ORCL"],
    },
}

# 소재 주인공 후보(=company-news 를 수집해 why_now 가 작동하는 종목). 메가캡 + 핵심 반도체/대표 종목.
HERO_UNIVERSE = MEGACAPS + ["AMD", "TSM", "SMCI", "ARM", "AVGO", "MU", "MRVL", "COIN", "RKLB", "PLTR"]

# 상관관계용 시계열 유니버스: 워치리스트 + 생태계 + 전 테마 바스켓(레버리지 제외 — corr≈1 자명).
SECTOR_UNIVERSE = sorted({t for peers in SECTOR_PEERS.values() for t in peers})
THEME_UNIVERSE = sorted({t for th in THEMES.values() for t in th["tickers"]})
LEVERAGED_UNIVERSE = sorted({t for v in LEVERAGED_ETF.values() for t in v})
_HIST = list(dict.fromkeys(WATCHLIST + SECTOR_UNIVERSE + THEME_UNIVERSE))
HISTORY_UNIVERSE = _HIST
# 시세(당일 변동) 유니버스: 위 + 레버리지 ETF(당일 증폭 변동 표시용).
QUOTE_UNIVERSE = list(dict.fromkeys(HISTORY_UNIVERSE + LEVERAGED_UNIVERSE))

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_FORMS = {"8-K", "10-Q", "10-K", "6-K"}


def _epoch_to_utc(ts) -> str | None:
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, TypeError, OSError):
        return None


# ── Finnhub: 가격 ─────────────────────────────────────
def collect_quotes(conn, session: requests.Session) -> int:
    token = require_env("FINNHUB_API_KEY")
    n = 0
    for sym in QUOTE_UNIVERSE:
        try:
            r = session.get(f"{FINNHUB}/quote", params={"symbol": sym, "token": token}, timeout=15)
            r.raise_for_status()
            q = r.json()
            if not q or q.get("c") in (None, 0):
                log("WARN", f"quote 비어있음: {sym}", "collect")
                continue
            content = (f"{sym} price={q.get('c')} change={q.get('d')} "
                       f"pct={q.get('dp')}% open={q.get('o')} high={q.get('h')} "
                       f"low={q.get('l')} prev_close={q.get('pc')}")
            rag_store.add_document(
                conn, kind="quote", source="finnhub", source_type="finnhub_quote",
                ticker=sym, title=f"{sym} quote", content=content,
                url=f"{FINNHUB}/quote?symbol={sym}",
                published_utc=_epoch_to_utc(q.get("t")),
                extra_json=json.dumps(q),
            )
            n += 1
            time.sleep(0.8)  # free tier rate limit 배려
        except requests.RequestException as e:
            log("WARN", f"quote 실패 {sym}: {e}", "collect")
    log("INFO", f"Finnhub 가격 {n}건 수집", "collect")
    return n


# ── Finnhub: 시장 뉴스 ────────────────────────────────
def collect_market_news(conn, session: requests.Session, limit: int = 20) -> int:
    token = require_env("FINNHUB_API_KEY")
    try:
        r = session.get(f"{FINNHUB}/news", params={"category": "general", "token": token}, timeout=15)
        r.raise_for_status()
        items = r.json()[:limit]
    except requests.RequestException as e:
        log("WARN", f"market news 실패: {e}", "collect")
        return 0
    n = 0
    for it in items:
        headline = it.get("headline", "")
        if not headline:
            continue
        rag_store.add_document(
            conn, kind="news", source=it.get("source", "finnhub_news"), source_type="news",
            ticker=(it.get("related") or None), title=headline,
            content=f"{headline}. {it.get('summary', '')}".strip(),
            url=it.get("url"), published_utc=_epoch_to_utc(it.get("datetime")),
            extra_json=json.dumps({"id": it.get("id"), "category": it.get("category")}),
        )
        n += 1
    log("INFO", f"시장 뉴스 {n}건 수집", "collect")
    return n


# ── SEC EDGAR: 공시 ───────────────────────────────────
def _sec_headers() -> dict:
    env = load_env()
    ua = env.get("SEC_USER_AGENT") or "shorts-maker/0.1 (market-commentary research)"
    return {"User-Agent": ua, "Accept-Encoding": "gzip, deflate", "Host": "data.sec.gov"}


def collect_sec_filings(conn, session: requests.Session, tickers=None, per_ticker: int = 3) -> int:
    tickers = tickers or MEGACAPS
    # ticker → CIK 매핑
    try:
        r = session.get(SEC_TICKERS_URL, headers={"User-Agent": _sec_headers()["User-Agent"]}, timeout=20)
        r.raise_for_status()
        m = r.json()
        cik_map = {row["ticker"].upper(): str(row["cik_str"]).zfill(10) for row in m.values()}
    except (requests.RequestException, ValueError, KeyError) as e:
        log("WARN", f"SEC ticker 매핑 실패: {e}", "collect")
        return 0
    n = 0
    for t in tickers:
        cik = cik_map.get(t.upper())
        if not cik:
            continue
        try:
            time.sleep(0.25)  # SEC fair-access
            r = session.get(SEC_SUBMISSIONS.format(cik=cik), headers=_sec_headers(), timeout=20)
            r.raise_for_status()
            sub = r.json()
            recent = sub.get("filings", {}).get("recent", {})
            forms = recent.get("form", [])
            dates = recent.get("filingDate", [])
            accns = recent.get("accessionNumber", [])
            docs = recent.get("primaryDocument", [])
            added = 0
            for i, form in enumerate(forms):
                if form not in SEC_FORMS:
                    continue
                accn = accns[i].replace("-", "")
                url = (f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
                       f"{accn}/{docs[i]}") if i < len(docs) else None
                rag_store.add_document(
                    conn, kind="filing", source="sec_edgar", source_type="sec",
                    ticker=t, title=f"{t} {form} {dates[i]}",
                    content=f"{t} filed {form} on {dates[i]} (CIK {cik}).",
                    url=url, published_utc=f"{dates[i]}T00:00:00Z",
                    extra_json=json.dumps({"form": form, "accession": accns[i]}),
                )
                n += 1
                added += 1
                if added >= per_ticker:
                    break
        except (requests.RequestException, ValueError, IndexError) as e:
            log("WARN", f"SEC 공시 실패 {t}: {e}", "collect")
    log("INFO", f"SEC 공시 {n}건 수집", "collect")
    return n


# ── Finnhub: 시장 변동성 게이지(VIX 프록시) ───────────
def collect_volatility(conn, session: requests.Session) -> int:
    """VIXY(VIX 추종 ETF) 시세 = 시장 전체 '예상 변동성' 게이지. 종목별 IV 는 프리미엄이라 불가."""
    token = require_env("FINNHUB_API_KEY")
    try:
        r = session.get(f"{FINNHUB}/quote", params={"symbol": VOL_PROXY, "token": token}, timeout=15)
        r.raise_for_status()
        q = r.json()
    except (requests.RequestException, ValueError) as e:
        log("WARN", f"변동성 프록시 실패: {e}", "collect")
        return 0
    if not q or q.get("c") in (None, 0):
        return 0
    content = (f"{VOL_PROXY} price={q.get('c')} change={q.get('d')} pct={q.get('dp')}% "
               f"open={q.get('o')} high={q.get('h')} low={q.get('l')} prev_close={q.get('pc')}")
    rag_store.add_document(
        conn, kind="quote", source="finnhub", source_type="finnhub_quote",
        ticker=VOL_PROXY, title=f"{VOL_PROXY} volatility-proxy quote", content=content,
        url=f"{FINNHUB}/quote?symbol={VOL_PROXY}", published_utc=_epoch_to_utc(q.get("t")),
        extra_json=json.dumps({**q, "role": "volatility_proxy"}),
    )
    log("INFO", "변동성 프록시(VIXY) 1건 수집", "collect")
    return 1


# ── Finnhub: 실적 캘린더(카탈리스트, 사실) ────────────
def collect_earnings_calendar(conn, session: requests.Session, days_ahead: int = 10, watch=None) -> int:
    token = require_env("FINNHUB_API_KEY")
    watch = set(watch or MEGACAPS)
    today = datetime.now(timezone.utc).date()
    to = today + timedelta(days=days_ahead)
    try:
        r = session.get(f"{FINNHUB}/calendar/earnings",
                        params={"from": today.isoformat(), "to": to.isoformat(), "token": token}, timeout=20)
        r.raise_for_status()
        cal = r.json().get("earningsCalendar", []) or []
    except (requests.RequestException, ValueError) as e:
        log("WARN", f"실적 캘린더 실패: {e}", "collect")
        return 0
    n = 0
    for e in cal:
        sym = e.get("symbol")
        if sym not in watch:
            continue
        date = e.get("date"); hour = e.get("hour") or ""
        eps, rev = e.get("epsEstimate"), e.get("revenueEstimate")
        content = (f"{sym} earnings scheduled {date}" + (f" ({hour})" if hour else "")
                   + (f"; EPS est {eps}" if eps is not None else "")
                   + (f"; revenue est {rev}" if rev is not None else "") + ".")
        rag_store.add_document(
            conn, kind="earnings", source="finnhub", source_type="finnhub_quote",
            ticker=sym, title=f"{sym} earnings {date}", content=content,
            url=f"{FINNHUB}/calendar/earnings?symbol={sym}",
            published_utc=(f"{date}T00:00:00Z" if date else None),
            extra_json=json.dumps(e),
        )
        n += 1
    log("INFO", f"실적 캘린더 {n}건 수집(향후 {days_ahead}일, watch 교집합)", "collect")
    return n


# ── Finnhub: 종목별 속보(최신 이슈) ───────────────────
def collect_company_news(conn, session: requests.Session, tickers=None,
                         days_back: int = 4, per_ticker: int = 4) -> int:
    token = require_env("FINNHUB_API_KEY")
    tickers = tickers or MEGACAPS
    today = datetime.now(timezone.utc).date()
    frm = today - timedelta(days=days_back)
    n = 0
    for sym in tickers:
        try:
            r = session.get(f"{FINNHUB}/company-news",
                            params={"symbol": sym, "from": frm.isoformat(),
                                    "to": today.isoformat(), "token": token}, timeout=20)
            r.raise_for_status()
            items = r.json() or []
        except (requests.RequestException, ValueError) as e:
            log("WARN", f"종목 속보 실패 {sym}: {e}", "collect")
            continue
        added = 0
        for it in items:
            h = it.get("headline", "")
            if not h:
                continue
            rag_store.add_document(
                conn, kind="news", source=it.get("source", "finnhub"), source_type="news",
                ticker=sym, title=h, content=f"{h}. {it.get('summary', '')}".strip(),
                url=it.get("url"), published_utc=_epoch_to_utc(it.get("datetime")),
                extra_json=json.dumps({"id": it.get("id"), "related": sym, "category": it.get("category")}),
            )
            n += 1; added += 1
            if added >= per_ticker:
                break
        time.sleep(0.6)
    log("INFO", f"종목별 속보 {n}건 수집({len(tickers)}종목)", "collect")
    return n


def collect_all(conn) -> dict:
    session = requests.Session()
    session.headers.update({"User-Agent": "shorts-maker/0.1"})
    res = {
        "quotes": collect_quotes(conn, session),
        "volatility": collect_volatility(conn, session),
        "earnings": collect_earnings_calendar(conn, session),
        "market_news": collect_market_news(conn, session),
        "company_news": collect_company_news(conn, session, tickers=HERO_UNIVERSE),
        "filings": collect_sec_filings(conn, session),
    }
    # ── 멀티소스(P2~P3) + 상관관계(연관종목) ──
    # 함수 내 import 로 순환참조 회피. 각 소스는 예산가드/예외격리되어 실패해도 파이프라인 비차단.
    from . import sources, correlate
    hist_n, closes = sources.collect_history(conn, tickers=HISTORY_UNIVERSE, period="1y")
    res["history"] = hist_n
    res["trends"] = sources.collect_trends(conn)
    res["reddit"] = sources.collect_reddit(conn)
    # 연관종목 = 메가캡별 생태계 상관관계. 지수/변동성/레버리지 ETF 는 peer 후보에서 제외
    # (지수=진부, 레버리지=corr≈1 자명).
    corr = correlate.compute(conn, closes, focus_tickers=HERO_UNIVERSE, top_n=5, period_label="3mo",
                             exclude_peers=INDEX_PROXIES + [VOL_PROXY] + LEVERAGED_UNIVERSE)
    res["correlations"] = len(corr.get("pairs", {}))
    res["collected_utc"] = utc_now()
    res["date"] = today_utc()
    conn.commit()
    return res
