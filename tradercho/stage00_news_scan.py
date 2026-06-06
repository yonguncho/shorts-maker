"""stage00_news_scan.py — 매일 뉴스 RSS 수집 → Claude Haiku로 쇼츠 종목 자동 선정.

출력: state/today_picks.json
사용: python stage00_news_scan.py [--hours 6] [--max-articles 40] [--dry-run]
"""
from __future__ import annotations
import argparse
import json
import sys
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path

import feedparser
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import llm
import json_utils as JU

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = ROOT / "state"
STATE_DIR.mkdir(exist_ok=True)

FEEDS = [
    "https://feeds.finance.yahoo.com/rss/2.0/headline?s=^GSPC",    # Yahoo Finance (20건)
    "https://www.cnbc.com/id/10000664/device/rss/rss.html",         # CNBC Markets (30건)
    "https://www.cnbc.com/id/15839135/device/rss/rss.html",         # CNBC Finance (30건)
    "https://feeds.marketwatch.com/marketwatch/topstories/",        # MarketWatch Top (10건)
    "https://feeds.marketwatch.com/marketwatch/bulletins/",         # MarketWatch Breaking (10건)
    "https://www.benzinga.com/feed",                                 # Benzinga (10건)
]

# S&P 500 + NASDAQ 주요 종목 화이트리스트 (확장됨)
KNOWN_TICKERS = frozenset("""
ARM NVDA TSLA MRVL MU TSM ASML AMD AVGO INTC QCOM AAPL MSFT GOOGL AMZN
META AVAV PLTR SMCI DELL ORCL CRM NFLX DIS BA F GM RIVN COIN UBER
CIEN DAL UAL AAL LUV WMT TGT COST HD LOW NKE SBUX MCD JPM BAC GS MS C WFC
GE HON MMM CAT DE UNH CVS WBA PFE JNJ MRK ABBV LLY TMO ABT MDT
XOM CVX COP SLB OXY VZ T CMCSA CHTR TMUS AMT CCI EQIX
PYPL SQ SHOP SNAP TWTR ZM CRWD SNOW DDOG NET OKTA ZS PANW FTNT
SPY QQQ IWM DIA GLD SLV TLT HYG
V MA AXP BRK.B BRK.A AMT PLD REIT O
""".upper().split())

_HEADERS = {"User-Agent": "trader-cho-scanner/1.0 (educational content)"}

# A0.5 URL 검증 상수
# 홈·목록 페이지 정확 차단 — 슬래시 없는 trailing 패턴은 depth check가 담당
_INVALID_URL_PATTERNS = (
    "?guccounter=",          # 추적 파라미터만 있는 URL
    "finance.yahoo.com/?",   # Yahoo Finance 홈 쿼리
    "yahoo.com/news?",       # 목록 쿼리스트링 (뉴스 리스트 페이지)
)
_VALID_URL_INDICATORS = (
    "/article/", "/story/", "/news/",
    "/2026/", "/2025/", "/2024/",
)


def is_valid_article_url(url: str) -> bool:
    """A0.5: article_url이 실제 기사 페이지인지 검증.
    구조 검사(빠름) → HTTP HEAD 200 확인(timeout 3s).
    """
    if not url or url.count("/") < 4:
        return False
    if any(p in url for p in _INVALID_URL_PATTERNS):
        return False
    # 유효 지시자 있으면 구조 패스
    has_indicator = any(p in url for p in _VALID_URL_INDICATORS)
    # HTTP HEAD 200 확인
    try:
        r = requests.head(url, timeout=3, allow_redirects=True,
                          headers=_HEADERS)
        return r.status_code == 200
    except Exception:
        # 네트워크 실패 시: 지시자 있으면 허용, 없으면 차단
        return has_indicator


def _parse_pub_date(entry) -> datetime | None:
    for attr in ("published", "updated"):
        raw = getattr(entry, attr, None) or entry.get(attr)
        if raw:
            try:
                return parsedate_to_datetime(raw).astimezone(timezone.utc)
            except Exception:
                pass
    return None


def fetch_articles(hours: int = 6, max_per_feed: int = 15) -> list[dict]:
    """RSS 피드에서 최근 {hours}시간 기사 수집. 중복(URL) 제거."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    seen_urls: set[str] = set()
    articles: list[dict] = []

    for feed_url in FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            source = feed.feed.get("title", feed_url.split("/")[2])
            count = 0
            for entry in feed.entries:
                if count >= max_per_feed:
                    break
                url = entry.get("link", "")
                if not url or url in seen_urls:
                    continue
                pub = _parse_pub_date(entry)
                if pub and pub < cutoff:
                    continue
                seen_urls.add(url)
                articles.append({
                    "title": entry.get("title", ""),
                    "url": url,
                    "summary": (entry.get("summary") or entry.get("description") or "")[:400],
                    "source": source,
                    "published_at": pub.isoformat() if pub else None,
                })
                count += 1
            print(f"  {source}: {count}건")
        except Exception as e:
            print(f"  ⚠ {feed_url[:60]}: {e}")

    print(f"총 {len(articles)}건 수집 (최근 {hours}h, 중복제거)")
    return articles


_SELECTION_PROMPT = """You are a financial content strategist for a YouTube Shorts channel called "Trader Cho" covering US stocks.
Analyze these news headlines/summaries and select the 3 best stocks for today's short-form video content.

Articles (title | source | published | summary):
{article_list}

Selection criteria (in order of importance):
1. Strong price catalyst (earnings beat, guidance raise, product launch, analyst upgrade/downgrade, macro event with clear stock angle)
2. Clear directional move (up or down, not sideways) that retail investors can understand
3. Well-known ticker (retail investor interest)
4. Shorts-worthy narrative (surprising, counterintuitive, or dramatic)

Avoid selecting:
- Penny stocks or micro-caps
- Crypto-related stories
- Pure macro/Fed stories with no clear single-stock angle
- Stocks with no recent price move mentioned

Output ONLY a JSON array (no explanation, no markdown):
[
  {{
    "ticker": "NVDA",
    "catalyst_type": "earnings_beat",
    "direction": "up",
    "hook_angle": "one sentence hook idea for the short video",
    "article_url": "https://...",
    "article_source": "Reuters",
    "article_published": "2026-06-04T08:00:00Z",
    "confidence": "high"
  }}
]

confidence: "high" (clear catalyst + price move), "medium" (catalyst clear, move ambiguous), "low" (weak signal).
Select exactly 3. If fewer than 3 qualify, include the best available with lower confidence.
catalyst_type must be one of: earnings_beat, guidance_raise, product, analyst_action, macro, other.
direction must be: up or down.
"""


def select_picks(articles: list[dict], dry_run: bool = False) -> list[dict]:
    """Claude Haiku로 최적 종목 3개 선정."""
    if not articles:
        print("  ⚠ 기사 없음 → 빈 picks")
        return []

    article_list = "\n".join(
        f"- {a['title']} | {a['source']} | {a.get('published_at','?')[:16]} | {a['summary'][:200]}"
        for a in articles[:40]
    )
    prompt = _SELECTION_PROMPT.format(article_list=article_list)

    if dry_run:
        print("  [dry-run] LLM 호출 스킵 → 샘플 picks 반환")
        # dry-run 샘플은 가짜 URL이므로 url_valid=True 고정 (HEAD 검사 불필요)
        return [
            {"ticker": "NVDA", "catalyst_type": "product", "direction": "up",
             "hook_angle": "Nvidia's new RTX announcement just lit up the chip space",
             "article_url": "https://finance.yahoo.com/news/nvidia-rtx-announcement-dryrun",
             "article_source": "dry-run",
             "article_published": datetime.now(timezone.utc).isoformat(),
             "confidence": "high", "url_valid": True},
        ]

    print("  Claude Haiku 종목 선정 중…")
    result, engine = llm.call_json(prompt)
    print(f"  engine={engine}")

    if not isinstance(result, list):
        print(f"  ⚠ LLM 응답 파싱 실패: {result!r:.200}")
        return []

    # 기본 검증: known tickers만 허용 (penny/crypto 1차 필터)
    picks = []
    for p in result:
        if not isinstance(p, dict):
            continue
        ticker = str(p.get("ticker", "")).upper().strip()
        if not ticker:
            continue
        if ticker not in KNOWN_TICKERS:
            print(f"  ⚠ 미지원 티커 '{ticker}' 제외 (KNOWN_TICKERS 추가 필요)")
            continue
        p["ticker"] = ticker
        # A0.5: article_url 검증 — 실제 기사 페이지인지 확인
        url = p.get("article_url", "")
        valid = is_valid_article_url(url)
        p["url_valid"] = valid
        if not valid:
            print(f"  ⚠ {ticker} article_url 무효 (url_valid=false): {url[:80]}")
        picks.append(p)

    valid_count = sum(1 for p in picks if p.get("url_valid"))
    print(f"  → {len(picks)}종목 선정 (url_valid: {valid_count}/{len(picks)}): "
          f"{[p['ticker'] for p in picks]}")
    return picks


def save_picks(picks: list[dict]) -> Path:
    out = STATE_DIR / "today_picks.json"
    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scan_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "picks": picks,
    }
    JU.atomic_write_json(out, data)
    print(f"  저장: {out}")
    return out


def run(hours: int = 6, max_articles: int = 40, dry_run: bool = False) -> list[dict]:
    print("\n[stage00] 뉴스 RSS 수집…")
    articles = fetch_articles(hours=hours, max_per_feed=max_articles // len(FEEDS) + 3)
    raw_path = STATE_DIR / "raw_articles.json"
    JU.atomic_write_json(raw_path, {"generated_at": datetime.now(timezone.utc).isoformat(),
                                    "articles": articles})

    print("\n[stage00] 종목 선정(Claude Haiku)…")
    picks = select_picks(articles, dry_run=dry_run)
    save_picks(picks)
    return picks


def main():
    ap = argparse.ArgumentParser(description="Daily news scan → stock picks")
    ap.add_argument("--hours", type=int, default=6, help="최근 N시간 기사 수집")
    ap.add_argument("--max-articles", type=int, default=40)
    ap.add_argument("--dry-run", action="store_true", help="LLM 호출 없이 샘플 반환")
    a = ap.parse_args()
    picks = run(hours=a.hours, max_articles=a.max_articles, dry_run=a.dry_run)
    print("\n=== today_picks ===")
    for p in picks:
        conf = p.get("confidence", "?")
        print(f"  [{conf.upper():6s}] {p['ticker']} — {p.get('hook_angle', '')}")


if __name__ == "__main__":
    main()
