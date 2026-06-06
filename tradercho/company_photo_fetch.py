"""company_photo_fetch.py — Wikipedia Commons 회사 사옥/제품 사진 취득.

L0.1 엄수: 실존 인물 사진 금지 — 건물·제품·로고·그래픽만.
라이선스 필터: CC-BY-SA / CC-BY / CC0 / Public Domain만 허용.
캐싱: assets/company_photos/{TICKER}_HQ.jpg
출처 기록: tradercho/assets_manifest.json + per-run out_dir/assets_manifest.json
"""
from __future__ import annotations
import sys
import re
import time
from pathlib import Path
from datetime import datetime, timezone

import requests

_COMMONS_DELAY = 0.8   # Commons API 연속 호출 간 딜레이(초) — rate limit 회피

sys.path.insert(0, str(Path(__file__).resolve().parent))
import json_utils as JU

ROOT = Path(__file__).resolve().parent.parent
PHOTOS_DIR = ROOT / "assets" / "company_photos"
PHOTOS_DIR.mkdir(parents=True, exist_ok=True)

MANIFEST_PATH = Path(__file__).resolve().parent / "assets_manifest.json"

_UA = {"User-Agent": "trader-cho-assets/1.0 (educational content; commons-api)"}

# 허용 라이선스 패턴 — "CC BY-SA 4.0" / "CC-BY-SA" 모두 매칭
_ALLOWED_LICENSE_RE = re.compile(
    r"(cc[\s\-]by[\s\-]sa|cc[\s\-]by(?![\s\-]nc)|cc0|cc.zero|public.domain|pd[\s\-]|attribution.share)", re.I
)
# 차단 패턴 (제약 라이선스) — NC·ND 포함 명시 차단
_BLOCKED_LICENSE_RE = re.compile(
    r"(noncommercial|no.deriv|\bnd\b|all.rights.reserved|restricted|copyright.only)", re.I
)

# 티커 → 검색 키워드 목록 (건물/제품 우선, 인물 키워드 없음)
COMPANY_QUERIES: dict[str, list[str]] = {
    "ARM":  ["Arm Holdings Cambridge", "Arm Limited building"],
    "NVDA": ["Nvidia campus aerial", "Nvidia headquarters building"],
    "TSLA": ["Tesla Gigafactory", "Tesla factory building"],
    "AAPL": ["Apple Park headquarters", "Apple campus Cupertino"],
    "MSFT": ["Microsoft Redmond campus", "Microsoft headquarters building"],
    "GOOGL":["Googleplex headquarters Mountain View", "Google campus building"],
    "AMZN": ["Amazon headquarters Seattle Spheres", "Amazon warehouse facility"],
    "META": ["Meta headquarters Menlo Park", "Meta campus building"],
    "AMD":  ["AMD headquarters Santa Clara", "AMD processor chip"],
    "INTC": ["Intel headquarters Hillsboro", "Intel campus building"],
    "AVGO": ["Broadcom headquarters San Jose", "Broadcom semiconductor chip"],
    "QCOM": ["Qualcomm headquarters San Diego", "Qualcomm chip mobile"],
    "MU":   ["Micron Technology headquarters Boise", "Micron memory chip"],
    "TSM":  ["TSMC headquarters Hsinchu", "TSMC semiconductor fab"],
    "ASML": ["ASML headquarters Veldhoven", "ASML lithography machine EUV"],
    "MRVL": ["Marvell Technology headquarters", "Marvell semiconductor chip"],
    "PLTR": ["Palantir headquarters Denver", "Palantir office building"],
    "DELL": ["Dell headquarters Round Rock", "Dell Technologies campus"],
    "ORCL": ["Oracle headquarters Austin", "Oracle campus building"],
    "CRM":  ["Salesforce Tower San Francisco", "Salesforce headquarters"],
    "NFLX": ["Netflix headquarters Los Gatos", "Netflix campus building"],
    "DIS":  ["Walt Disney headquarters Burbank", "Disney theme park castle"],
    "BA":   ["Boeing headquarters Arlington", "Boeing aircraft factory"],
    "JPM":  ["JPMorgan Chase headquarters New York", "JPMorgan building"],
    "DAL":  ["Delta Air Lines headquarters Atlanta", "Delta airplane aircraft"],
    "CIEN": ["Ciena Corporation headquarters Hanover", "Ciena fiber optic network"],
    "RIVN": ["Rivian headquarters Normal Illinois", "Rivian electric truck"],
    "COIN": ["Coinbase headquarters San Francisco", "Coinbase office"],
    "UBER": ["Uber headquarters San Francisco", "Uber office building"],
}

# 인물 관련 키워드 블랙리스트 (L0.1)
_PERSON_BL = {"portrait", "person", "people", "employee", "staff", "ceo", "executive",
              "founder", "worker", "man", "woman", "face", "selfie", "crowd"}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _cache_path(ticker: str, suffix: str = "HQ") -> Path:
    return PHOTOS_DIR / f"{ticker.upper()}_{suffix}.jpg"


def _load_cache(ticker: str, suffix: str = "HQ") -> Path | None:
    p = _cache_path(ticker, suffix)
    return p if p.exists() and p.stat().st_size > 5000 else None


def _is_allowed_license(license_str: str) -> bool:
    s = (license_str or "").lower()
    if _BLOCKED_LICENSE_RE.search(s):
        return False
    return bool(_ALLOWED_LICENSE_RE.search(s))


def _person_check(title: str, categories: list[str]) -> bool:
    """True이면 인물 사진 — 건너뜀 (L0.1)."""
    text = (title + " " + " ".join(categories)).lower()
    return any(w in text for w in _PERSON_BL)


def _commons_get(params: dict, retries: int = 2) -> dict | None:
    """Commons API GET with 429 backoff. None 반환 시 호출자가 skip."""
    for attempt in range(retries + 1):
        try:
            r = requests.get("https://commons.wikimedia.org/w/api.php",
                             headers=_UA, timeout=20, params=params)
            if r.status_code == 429:
                if attempt < retries:
                    time.sleep(5 * (attempt + 1))
                    continue
                return None
            if r.status_code != 200 or not r.content:
                return None
            return r.json()
        except Exception:
            return None
    return None


def _search_commons(query: str, limit: int = 5) -> list[dict]:
    """Wikipedia Commons 파일 검색 → [{title, url, license, author, page_url}]."""
    data = _commons_get({"action": "query", "list": "search", "srsearch": query,
                         "srnamespace": "6", "format": "json", "srlimit": limit * 2})
    if not data:
        print(f"    ⚠ Commons 검색 실패 또는 429: {query[:50]}")
        return []
    hits = data.get("query", {}).get("search", [])

    results = []
    for h in hits:
        title = h.get("title", "")
        if not title.lower().endswith((".jpg", ".jpeg", ".png")):
            continue
        try:
            time.sleep(_COMMONS_DELAY)
            info_data = _commons_get({"action": "query", "titles": title,
                                      "prop": "imageinfo|categories",
                                      "iiprop": "url|extmetadata", "iiurlwidth": 1080,
                                      "format": "json"})
            if not info_data:
                continue
            page = list(info_data["query"]["pages"].values())[0]
            ii = page.get("imageinfo", [{}])[0]
            meta = ii.get("extmetadata", {})
            license_str = (meta.get("LicenseShortName", {}).get("value", "") or
                           meta.get("License", {}).get("value", ""))
            author = meta.get("Artist", {}).get("value", "") or meta.get("Credit", {}).get("value", "")
            # 인물 사진 필터 (L0.1)
            cats = [c.get("title", "") for c in page.get("categories", [])]
            if _person_check(title, cats):
                continue
            if not _is_allowed_license(license_str):
                continue
            # Special:FilePath bypass — avoids upload.wikimedia.org direct 429
            fname = title.replace("File:", "").replace(" ", "_")
            thumb_url = (
                f"https://commons.wikimedia.org/wiki/Special:FilePath/{fname}?width=1080"
            )
            if not thumb_url:
                continue
            results.append({"title": title, "url": thumb_url,
                            "license": license_str, "author": re.sub(r"<[^>]+>", "", author),
                            "page_url": f"https://commons.wikimedia.org/wiki/{title.replace(' ','_')}"})
            if len(results) >= limit:
                break
        except Exception:
            continue
    return results


def fetch_company_photo(ticker: str, suffix: str = "HQ", verbose: bool = True) -> Path | None:
    """티커 회사 사진 취득. suffix='HQ'(건물) 또는 'product'. 없으면 None."""
    ticker = ticker.upper()

    cached = _load_cache(ticker, suffix)
    if cached:
        if verbose:
            print(f"  photo {ticker}_{suffix}: cache hit")
        return cached

    queries = COMPANY_QUERIES.get(ticker, [f"{ticker} headquarters building"])
    # suffix==product 이면 두 번째 쿼리 우선
    if suffix == "product" and len(queries) > 1:
        queries = [queries[1], queries[0]]

    if verbose:
        print(f"  photo {ticker}_{suffix}: searching Commons…", end=" ", flush=True)

    for q in queries:
        results = _search_commons(q, limit=3)
        if not results:
            continue
        for hit in results:
            try:
                img_data = None
                for attempt in range(4):
                    resp = requests.get(hit["url"], headers=_UA, timeout=20)
                    if resp.status_code == 200 and len(resp.content) > 5000:
                        img_data = resp.content
                        break
                    if resp.status_code == 429:
                        wait = int(resp.headers.get("Retry-After", 15)) + 5
                        if verbose:
                            print(f"\n    429 throttle → {wait}s", end=" ", flush=True)
                        time.sleep(wait)
                        continue
                    break
                if img_data:
                    p = _cache_path(ticker, suffix)
                    p.write_bytes(img_data)
                    _record_manifest(ticker, suffix, hit)
                    if verbose:
                        print(f"OK ({hit['license']})")
                    return p
            except Exception as e:
                if verbose:
                    print(f"download fail: {e}")
                continue

    if verbose:
        print("skip (no CC image found)")
    return None


def _record_manifest(ticker: str, suffix: str, hit: dict):
    """assets_manifest.json에 사진 취득 기록 (append 방식)."""
    try:
        import json
        m: list = json.loads(MANIFEST_PATH.read_text()) if MANIFEST_PATH.exists() else []
        file_str = str(_cache_path(ticker, suffix))
        m = [x for x in m if x.get("file") != file_str]
        m.append({"file": file_str, "source": f"Wikipedia Commons · {hit['title']}",
                  "url": hit["page_url"], "license": hit["license"],
                  "author": hit.get("author", ""), "downloaded_at": _now(),
                  "used_in": ["scene_background", "catalyst_card"]})
        JU.atomic_write_json(MANIFEST_PATH, m)
    except Exception as e:
        print(f"    ⚠ manifest 기록 실패: {e}")


def ensure_photos(ticker: str) -> dict[str, Path | None]:
    """HQ + product 사진 2장 취득. {suffix: path|None}."""
    return {
        "HQ":      fetch_company_photo(ticker, "HQ"),
        "product": fetch_company_photo(ticker, "product"),
    }


if __name__ == "__main__":
    tickers = sys.argv[1:] or ["NVDA", "TSLA", "AVGO"]
    for t in tickers:
        photos = ensure_photos(t)
        for k, v in photos.items():
            print(f"  {t}_{k}: {v}")
