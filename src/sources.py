"""sources.py — 멀티소스 수집 어댑터 (P2~P3).

어댑터 패턴: 각 collect_*(conn) 는 외부 소스를 호출해 RAG 에 사실을 적재하고 카운트를 반환.
모든 외부 호출은 budget 가드를 통과해야 한다. 소스 추가 = 함수 추가.

- yfinance: 과거 시계열(라인/캔들 차트 + 상관관계 데이터 소스). 🟢 사실·계산.
- pytrends: Google 검색량 급증("왜 화제"). 🟡 사실귀속("검색 관심 급증")으로만.
- reddit(praw): 서브레딧 언급량. 🟡 사실귀속("r/stocks 최다 언급")으로만. OAuth 필요 → 미보유 시 graceful skip.

키는 .env 에서만 읽고 값은 로그하지 않는다.
"""
from __future__ import annotations
import json
import math

from .common import ROOT, load_env, log, utc_now, today_utc
from . import rag_store, budget

# collect.py 의 워치리스트를 단일 출처로 재사용
from .collect import WATCHLIST, MEGACAPS, INDEX_PROXIES

_YF_CACHE = ROOT / ".cache" / "yf"


# ── yfinance: 과거 시계열 + 실현변동성 ──────────────────
def fetch_history(tickers, period: str = "3mo", interval: str = "1d"):
    """yfinance 종가 DataFrame 반환(실패 시 None). threads=False + 캐시경로 필수(DB락 회피)."""
    if not budget.can_spend("yfinance", len(tickers)):
        log("WARN", "yfinance 예산 소진 — 과거 시계열 건너뜀", "sources")
        return None
    try:
        import yfinance as yf
        _YF_CACHE.mkdir(parents=True, exist_ok=True)
        try:
            yf.set_tz_cache_location(str(_YF_CACHE))
        except Exception:
            pass
        # 1년 OHLCV — 지표(RSI/52주/거래량) 계산용. (차트·상관관계는 최근 3개월만 슬라이스)
        df = yf.download(list(tickers), period=period, interval=interval,
                         progress=False, auto_adjust=True, threads=False)
        budget.spend("yfinance", len(tickers))
        if df is None or len(df) == 0:
            log("WARN", "yfinance 응답 비어있음(차단 가능)", "sources")
            return None
        return df   # 멀티필드(Open/High/Low/Close/Volume) × ticker
    except Exception as e:
        log("WARN", f"yfinance 실패: {type(e).__name__} {str(e)[:160]}", "sources")
        return None


def _realized_vol(series) -> float | None:
    """연율화 실현변동성(%) = 일간수익률 표준편차 * sqrt(252) * 100."""
    rets = series.pct_change().dropna()
    if len(rets) < 5:
        return None
    return float(rets.std() * math.sqrt(252) * 100)


def _rsi(series, period: int = 14) -> float | None:
    """Wilder RSI(14) 마지막 값."""
    if len(series) < period + 1:
        return None
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    ag = gain.ewm(alpha=1/period, adjust=False).mean()
    al = loss.ewm(alpha=1/period, adjust=False).mean()
    last_ag, last_al = float(ag.iloc[-1]), float(al.iloc[-1])
    if last_al == 0:
        return 100.0
    rs = last_ag / last_al
    return round(100 - 100/(1+rs), 1)


def collect_history(conn, tickers=None, period: str = "1y") -> tuple[int, object]:
    """1년 OHLCV 수집 → 종목별 지표(RSI·52주고저·거래량vs평균·실현변동성·3M변동) 계산·적재.
    반환: (건수, 최근 3개월 closes DataFrame[상관관계·차트용])."""
    tickers = list(tickers or WATCHLIST)
    df = fetch_history(tickers, period=period)
    if df is None or len(df) == 0:
        return 0, None
    closes_all = df["Close"]
    vols = df["Volume"] if "Volume" in df.columns.get_level_values(0) else None
    cols = [c for c in closes_all.columns if not closes_all[c].isna().all()]
    n = 0
    for sym in cols:
        s = closes_all[sym].dropna()
        if len(s) < 20:
            continue
        last = float(s.iloc[-1])
        s3 = s.tail(63)                                   # 최근 3개월
        first3 = float(s3.iloc[0])
        chg_pct = (last / first3 - 1) * 100 if first3 else 0.0   # 3M 변동
        rv = _realized_vol(s3)
        hi52 = float(s.max()); lo52 = float(s.min())      # 1년(≈52주) 고저
        pct_off_high = (last / hi52 - 1) * 100 if hi52 else None
        rsi = _rsi(s)
        vol_vs_avg = None
        if vols is not None and sym in vols.columns:
            v = vols[sym].dropna()
            if len(v) >= 31 and v.tail(30).mean() > 0:
                vol_vs_avg = round(float(v.iloc[-1] / v.tail(30).mean()), 2)
        content = (f"{sym} 1y: last={last:.2f}, 3M_change={chg_pct:+.1f}%, "
                   f"52w_high={hi52:.2f}, 52w_low={lo52:.2f}, "
                   f"pct_off_52w_high={pct_off_high:+.1f}%" if pct_off_high is not None else "")
        content += (f", RSI14={rsi}" if rsi is not None else "") \
            + (f", vol_vs_30d_avg={vol_vs_avg}x" if vol_vs_avg is not None else "") \
            + (f", realized_vol={rv:.1f}%/yr" if rv is not None else "") + "."
        series = [[d.strftime("%Y-%m-%d"), round(float(v), 4)]
                  for d, v in s3.items() if v == v]       # 차트용 3개월
        rag_store.add_document(
            conn, kind="history", source="yfinance", source_type="yfinance",
            ticker=sym, title=f"{sym} price history + indicators",
            content=content, url=f"https://finance.yahoo.com/quote/{sym}",
            published_utc=utc_now(),
            extra_json=json.dumps({"period": "3mo", "interval": "1d",
                                    "realized_vol_pct": rv, "period_change_pct": chg_pct,
                                    "rsi14": rsi, "high_52w": round(hi52, 2),
                                    "low_52w": round(lo52, 2),
                                    "pct_off_52w_high": (round(pct_off_high, 1) if pct_off_high is not None else None),
                                    "vol_vs_30d_avg": vol_vs_avg, "series": series}),
        )
        n += 1
    closes_3mo = closes_all[cols].tail(63)
    log("INFO", f"yfinance 1y 수집·지표계산 {n}건(RSI/52주/거래량 포함)", "sources")
    return n, closes_3mo


# ── pytrends: 검색량 급증 ──────────────────────────────
# 티커 → 검색어(회사명) 매핑 — 사람들은 티커보다 회사명을 검색
TICKER_TERMS = {
    "AAPL": "Apple stock", "MSFT": "Microsoft stock", "NVDA": "Nvidia stock",
    "AMZN": "Amazon stock", "GOOGL": "Google stock", "META": "Meta stock",
    "TSLA": "Tesla stock",
}


def collect_trends(conn, tickers=None) -> int:
    """관심종목 검색량(Google Trends). 'rising'(급증) 신호를 사실귀속으로 적재."""
    tickers = [t for t in (tickers or MEGACAPS) if t in TICKER_TERMS]
    if not tickers:
        return 0
    if not budget.can_spend("pytrends", 1):
        log("WARN", "pytrends 예산 소진 — 트렌드 건너뜀", "sources")
        return 0
    try:
        import time as _time
        from pytrends.request import TrendReq
        # 주의: TrendReq 의 retries/backoff_factor 는 구버전 urllib3 Retry(method_whitelist)를
        # 생성해 신버전에서 TypeError → 전달하지 않고 아래 수동 백오프 루프로만 429 완화.
        pt = TrendReq(hl="en-US", tz=0, timeout=(10, 25))
        terms = [TICKER_TERMS[t] for t in tickers]
        n = 0
        # pytrends 는 한 번에 최대 5개 키워드 → 청크
        for i in range(0, len(terms), 5):
            chunk_terms = terms[i:i + 5]
            chunk_syms = tickers[i:i + 5]
            iot = None
            for attempt in range(3):
                try:
                    pt.build_payload(chunk_terms, timeframe="now 7-d", geo="US")
                    budget.spend("pytrends", 1)
                    iot = pt.interest_over_time()
                    break
                except Exception as ie:
                    if "429" in str(ie) and attempt < 2:
                        _time.sleep(2 + attempt * 3)  # 백오프
                        continue
                    raise
            if iot is None or len(iot) == 0:
                continue
            for sym, term in zip(chunk_syms, chunk_terms):
                if term not in iot.columns:
                    continue
                col = iot[term].dropna()
                if len(col) < 4:
                    continue
                recent = float(col.iloc[-len(col) // 3:].mean())
                base = float(col.iloc[:len(col) // 3].mean()) or 1.0
                surge = (recent / base - 1) * 100
                content = (f"{sym}: Google search interest for \"{term}\" "
                           f"{'surged' if surge >= 30 else 'changed'} {surge:+.0f}% "
                           f"in the last 7 days [geo=US, category=all, web search, "
                           f"timeframe=now 7-d, relative interest 0-100, as of {today_utc()}; "
                           f"method: %change of mean(last third of series) vs mean(first third)].")
                rag_store.add_document(
                    conn, kind="trend", source="google_trends", source_type="trends",
                    ticker=sym, title=f"{sym} search interest",
                    content=content, url="https://trends.google.com",
                    published_utc=utc_now(),
                    extra_json=json.dumps({"term": term, "surge_pct": surge,
                                           "recent_mean": recent, "base_mean": base}),
                )
                n += 1
        log("INFO", f"Google Trends {n}건 수집", "sources")
        return n
    except Exception as e:
        log("WARN", f"pytrends 실패: {type(e).__name__} {str(e)[:160]}", "sources")
        return 0


# ── reddit(praw): 서브레딧 언급량 (OAuth 필요, optional) ──
def reddit_available() -> bool:
    env = load_env()
    return bool(env.get("REDDIT_CLIENT_ID") and env.get("REDDIT_CLIENT_SECRET"))


def collect_reddit(conn, tickers=None, subreddits=("stocks", "wallstreetbets"),
                   limit: int = 80) -> int:
    """서브레딧 hot 게시물에서 워치리스트 티커 언급 빈도를 사실귀속으로 적재.
    OAuth 크리덴셜 미보유 시 0 반환(graceful skip)."""
    if not reddit_available():
        log("INFO", "Reddit 크리덴셜 미보유 — 소셜 신호 건너뜀(graceful skip)", "sources")
        return 0
    if not budget.can_spend("reddit", len(subreddits)):
        log("WARN", "reddit 예산 소진 — 건너뜀", "sources")
        return 0
    tickers = list(tickers or MEGACAPS)
    env = load_env()
    try:
        import praw
        reddit = praw.Reddit(
            client_id=env["REDDIT_CLIENT_ID"],
            client_secret=env["REDDIT_CLIENT_SECRET"],
            user_agent=env.get("REDDIT_USER_AGENT", "shorts-maker/0.1 by market-research"),
            check_for_async=False,
        )
        reddit.read_only = True
        counts: dict[str, int] = {t: 0 for t in tickers}
        # 회사명도 같이 카운트
        names = {t: TICKER_TERMS.get(t, t).split()[0] for t in tickers}
        for sub in subreddits:
            budget.spend("reddit", 1)
            for post in reddit.subreddit(sub).hot(limit=limit):
                text = f"{post.title} {getattr(post, 'selftext', '')}".upper()
                for t in tickers:
                    if f"${t}" in text or f" {t} " in f" {text} " or names[t].upper() in text:
                        counts[t] += 1
        ranked = sorted([(t, c) for t, c in counts.items() if c > 0],
                        key=lambda x: -x[1])
        n = 0
        for t, c in ranked:
            content = (f"{t} was mentioned in {c} of the top posts across "
                       f"r/{' & r/'.join(subreddits)} (retail attention signal).")
            rag_store.add_document(
                conn, kind="social", source="reddit", source_type="social",
                ticker=t, title=f"{t} reddit mentions",
                content=content, url=f"https://reddit.com/r/{subreddits[0]}",
                published_utc=utc_now(),
                extra_json=json.dumps({"mentions": c, "subreddits": list(subreddits)}),
            )
            n += 1
        log("INFO", f"Reddit 언급량 {n}건 수집", "sources")
        return n
    except Exception as e:
        log("WARN", f"reddit 실패: {type(e).__name__} {str(e)[:160]}", "sources")
        return 0
