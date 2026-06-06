"""article.py — 뉴스 기사 실제 publisher 해석 + 본문 발췌 스크랩 (best-effort).

Finnhub 뉴스 url 은 finnhub.io/api/news?id=... 리다이렉트다. 한 hop 따라가면 실제 publisher URL 이 나온다.
거기서 og:description / meta description / 첫 문단을 발췌해 '기사에서 가져온' 신뢰성 있는 리드를 만든다.
네트워크 의존이라 전부 graceful: 실패하면 Finnhub 가 준 요약(fallback_summary)으로 되돌아간다.
1회 호출(선정된 why_now 기사 1건)만 수행해 비용·취약성을 최소화한다. 짧은 발췌만 사용(공정이용·출처표기).
"""
from __future__ import annotations
import html
import os
import re
import subprocess
import requests

from .common import log

_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def capture_screenshot(url: str, out_path: str, width: int = 1080, height: int = 1340) -> bool:
    """Chrome 헤드리스로 기사 페이지 상단을 스크린샷(실패 시 False). device-scale=1 로 1x 캡처."""
    if not url or not os.path.exists(_CHROME):
        return False
    prof = "/tmp/shortsmaker_chrome_shot"
    cmd = [_CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-sandbox",
           "--no-first-run", "--no-default-browser-check", "--disable-extensions",
           f"--user-data-dir={prof}", "--force-device-scale-factor=1",
           "--virtual-time-budget=6000",
           f"--window-size={width},{height}", f"--screenshot={out_path}", url]
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    except subprocess.TimeoutExpired:
        pass   # --headless=new 가 캡처 후 깔끔히 종료 안 하는 경우 多 → 아래서 파일로 판정(이미 kill됨)
    except OSError as e:
        log("WARN", f"기사 스크린샷 실패: {type(e).__name__}", "article")
        return False
    ok = os.path.exists(out_path) and os.path.getsize(out_path) > 5000
    if not ok:
        log("WARN", "기사 스크린샷 비어있음/미생성", "article")
    return ok

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
_TIMEOUT = 8

_OG_IMAGE = re.compile(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', re.I)
_OG_IMAGE2 = re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', re.I)
_OG_DESC = re.compile(r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']', re.I)
_META_DESC = re.compile(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']', re.I)
_OG_DESC2 = re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:description["\']', re.I)
_PARA = re.compile(r"<p[^>]*>(.*?)</p>", re.I | re.S)
_TAGS = re.compile(r"<[^>]+>")


def resolve_canonical(url: str) -> str:
    """finnhub 리다이렉트(또는 일반 url)를 1 hop 따라가 실제 publisher URL 반환. 실패 시 원본."""
    if not url:
        return url
    try:
        r = requests.get(url, allow_redirects=False, timeout=_TIMEOUT,
                         headers={"User-Agent": _UA})
        loc = r.headers.get("Location")
        if r.status_code in (301, 302, 303, 307, 308) and loc:
            return loc
    except requests.RequestException as e:
        log("WARN", f"기사 URL 해석 실패: {type(e).__name__}", "article")
    return url


def _publisher(url: str) -> str:
    m = re.search(r"https?://(?:www\.)?([^/]+)/", url or "")
    return m.group(1) if m else "source"


_LINK_NOISE = re.compile(r"\s*\|\s*[^)|]*?(prediction|forecast|price target|stock)\b", re.I)


def _clean(text: str) -> str:
    text = _TAGS.sub(" ", text or "")
    text = html.unescape(text)                 # &#8216; &#8217; &amp; 등 전부 디코드
    text = _LINK_NOISE.sub("", text)           # publisher 내부앵커 노이즈 "| ARM Price Prediction" 제거
    text = text.replace(" )", ")").replace("( ", "(")
    return re.sub(r"\s+", " ", text).strip()


def fetch_excerpt(canonical_url: str) -> str | None:
    """publisher 페이지에서 og:description/meta description/첫 문단 발췌(짧게). 실패 시 None."""
    try:
        r = requests.get(canonical_url, timeout=_TIMEOUT, headers={"User-Agent": _UA})
        if r.status_code != 200 or not r.text:
            return None
        html = r.text
        for rx in (_OG_DESC, _OG_DESC2, _META_DESC):
            m = rx.search(html)
            if m and len(m.group(1).strip()) > 30:
                return _clean(m.group(1))
        # 첫 의미있는 문단
        for m in _PARA.finditer(html):
            p = _clean(m.group(1))
            if len(p) > 60:
                return p
    except requests.RequestException as e:
        log("WARN", f"기사 발췌 실패: {type(e).__name__}", "article")
    return None


def fetch_og_image(canonical_url: str, out_path: str) -> str | None:
    """기사 페이지의 대표 이미지(og:image)를 받아 저장(실패 시 None). 관련 기사 사진 슬라이드용."""
    try:
        r = requests.get(canonical_url, timeout=_TIMEOUT, headers={"User-Agent": _UA})
        if r.status_code != 200:
            return None
        m = _OG_IMAGE.search(r.text) or _OG_IMAGE2.search(r.text)
        if not m:
            return None
        img_url = html.unescape(m.group(1))
        ir = requests.get(img_url, timeout=_TIMEOUT, headers={"User-Agent": _UA})
        if ir.status_code == 200 and len(ir.content) > 3000:
            open(out_path, "wb").write(ir.content)
            return out_path
    except requests.RequestException as e:
        log("WARN", f"og:image 실패: {type(e).__name__}", "article")
    return None


def enrich(finnhub_url: str, fallback_summary: str = "") -> dict:
    """기사 1건 보강: 실제 publisher URL + 발췌(스크랩). 발췌 실패 시 fallback_summary 사용.
    반환: {canonical_url, publisher, excerpt, scraped(bool)}."""
    canonical = resolve_canonical(finnhub_url)
    excerpt = fetch_excerpt(canonical) if canonical else None
    scraped = bool(excerpt)
    if not excerpt:
        excerpt = (fallback_summary or "").strip() or None
    return {
        "canonical_url": canonical, "publisher": _publisher(canonical),
        "excerpt": (excerpt[:200].rsplit(" ", 1)[0] + "…") if excerpt and len(excerpt) > 200 else excerpt,
        "scraped": scraped,
    }
