"""article_fetch.py — URL에서 뉴스 기사 본문 추출 (BeautifulSoup).

A0.6: require()는 본문 100자 미만이면 ValueError → 파이프라인 중단.
"""
from __future__ import annotations
import re
import requests
from bs4 import BeautifulSoup

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; trader-cho-reader/1.0; educational)"
}
MIN_CHARS = 100

# 본문 컨테이너 셀렉터 우선순위 (itemprop·role·tag 순)
_CONTAINER_SELECTORS = [
    {"itemprop": "articleBody"},
    {"role": "main"},
    "article",
    "main",
]


def fetch(url: str, timeout: int = 12) -> str:
    """URL에서 기사 본문 추출. 실패하면 빈 문자열 반환."""
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=timeout, allow_redirects=True)
        resp.raise_for_status()
    except Exception as e:
        raise RuntimeError(f"article_fetch GET 실패 ({url[:80]}): {e}")

    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "aside", "form"]):
        tag.decompose()

    container = None
    for sel in _CONTAINER_SELECTORS:
        if isinstance(sel, str):
            container = soup.find(sel)
        else:
            container = soup.find(attrs=sel)
        if container:
            break
    if not container:
        container = soup.body or soup

    paragraphs = container.find_all("p")
    text = " ".join(p.get_text(" ", strip=True) for p in paragraphs)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def require(url: str, ticker: str = "") -> str:
    """기사 본문 취득 + 100자 미만이면 ValueError (A0.6)."""
    text = fetch(url)
    if len(text.strip()) < MIN_CHARS:
        raise ValueError(
            f"[FAIL] Article for {ticker or url[:50]} is empty or too short "
            f"({len(text.strip())} chars). Pipeline stopped. Provide a valid article."
        )
    return text
