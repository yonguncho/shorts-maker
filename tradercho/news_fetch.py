"""news_fetch.py — 티커별 당일 뉴스 자동 취득.

yfinance .news → 가장 최근 기사 URL → article_fetch로 본문 추출.
우선순위: isHosted=True(Yahoo 직접 호스팅) → previewUrl → canonicalUrl.

fetch_finviz(ticker) — Finviz 뉴스 헤드라인 스크래핑 (보조).

사용:
  from news_fetch import fetch_latest, fetch_finviz
  text, meta = fetch_latest("ARM")
  headlines = fetch_finviz("ARM")  # [{title, url, date, source}]
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import article_fetch as AF

MIN_CHARS = AF.MIN_CHARS
_TODAY_ONLY_HOURS = 36  # 36h 이내 기사만 사용 (주말/공휴일 여유)


def _candidate_urls(item: dict) -> list[str]:
    """뉴스 항목에서 시도할 URL 목록 반환 (우선순위순)."""
    c = item.get("content", item)
    urls = []
    # Yahoo 직접 호스팅 기사는 canonicalUrl이 안정적
    if c.get("isHosted"):
        cu = (c.get("canonicalUrl") or {}).get("url", "")
        if cu:
            urls.append(cu)
    # previewUrl: Yahoo Finance 프록시 (비호스팅 기사도 일부 접근 가능)
    pv = c.get("previewUrl") or ""
    if pv and pv not in urls:
        urls.append(pv)
    # clickThroughUrl
    ct = (c.get("clickThroughUrl") or {}).get("url", "")
    if ct and ct not in urls:
        urls.append(ct)
    # canonicalUrl 마지막 시도 (아직 없으면)
    cu = (c.get("canonicalUrl") or {}).get("url", "")
    if cu and cu not in urls:
        urls.append(cu)
    return [u for u in urls if u]


def _pub_dt(item: dict) -> datetime | None:
    c = item.get("content", item)
    raw = c.get("pubDate") or c.get("displayTime") or ""
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return None


def fetch_latest(ticker: str, max_articles: int = 10) -> tuple[str, dict]:
    """
    티커의 최신 뉴스 기사 본문 취득.
    반환: (article_text, meta_dict)
    meta_dict = {"title", "source", "pub_date", "url"}
    취득 실패 시 RuntimeError.
    """
    import yfinance as yf
    t = yf.Ticker(ticker)
    news = t.news or []
    if not news:
        raise RuntimeError(f"{ticker}: yfinance .news 결과 없음")

    cutoff = datetime.now(timezone.utc).replace(
        tzinfo=timezone.utc
    ) - __import__("datetime").timedelta(hours=_TODAY_ONLY_HOURS)

    # 최신순 정렬
    news_sorted = sorted(
        news,
        key=lambda x: (_pub_dt(x) or datetime.min.replace(tzinfo=timezone.utc)),
        reverse=True,
    )

    errors = []
    for item in news_sorted[:max_articles]:
        pub = _pub_dt(item)
        if pub and pub < cutoff:
            continue  # 오래된 기사 건너뜀

        c = item.get("content", item)
        title = c.get("title", "")
        source = (c.get("provider") or {}).get("displayName", "")
        pub_str = (pub.strftime("%Y-%m-%d") if pub else "")

        for url in _candidate_urls(item):
            try:
                text = AF.fetch(url)
                if len(text.strip()) >= MIN_CHARS:
                    print(f"  뉴스 취득 ✓ [{source}] {title[:60]}")
                    return text, {
                        "title": title,
                        "source": source,
                        "pub_date": pub_str,
                        "url": url,
                    }
            except Exception as e:
                errors.append(f"{url[:60]}: {e}")

    raise RuntimeError(
        f"{ticker}: 유효한 기사 본문 취득 실패 (시도 {len(errors)}건).\n"
        + "\n".join(errors[:5])
    )


def fetch_finviz(ticker: str, max_items: int = 10) -> list[dict]:
    """Finviz 뉴스 헤드라인 스크래핑.
    반환: [{title, url, date, source}] — 실패 시 [] 반환 (파이프라인 중단 없음).
    """
    import requests
    from bs4 import BeautifulSoup

    url = f"https://finviz.com/quote.ashx?t={ticker.upper()}"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        )
    }
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code != 200:
            print(f"  [FINVIZ] {ticker}: HTTP {r.status_code} (스킵)")
            return []
        soup = BeautifulSoup(r.text, "html.parser")
        # Finviz news table (id="news-table" on newer layout, class on older)
        table = soup.select_one("#news-table") or soup.select_one("table.fullview-news-outer")
        if not table:
            print(f"  [FINVIZ] {ticker}: 뉴스 테이블 없음 (스킵)")
            return []
        items = []
        for row in table.select("tr"):
            tds = row.select("td")
            if len(tds) < 2:
                continue
            a = tds[1].select_one("a")
            if not a:
                continue
            source_span = tds[1].select_one("span.news-link-right") or tds[1].select_one("span")
            source = source_span.get_text(strip=True) if source_span else ""
            items.append({
                "title": a.get_text(strip=True),
                "url": a.get("href", ""),
                "date": tds[0].get_text(strip=True),
                "source": source,
            })
            if len(items) >= max_items:
                break
        print(f"  [FINVIZ] {ticker}: {len(items)}건")
        return items
    except Exception as e:
        print(f"  [FINVIZ] {ticker}: 실패 ({e}) (스킵)")
        return []
