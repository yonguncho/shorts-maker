"""logo_fetch.py — 티커 로고 취득 (캐시 → Wikidata P154 → Logo.dev → graceful skip).

assets.py download_logo() 를 대체하는 보강 버전.
우선순위: 1)로컬캐시 2)Wikidata CC-BY-SA 3)Logo.dev(상표, display only) 4)skip.
모든 취득 결과는 assets_manifest.json(전역)에 기록.
"""
from __future__ import annotations
import os
import sys
import time
from pathlib import Path
from datetime import datetime, timezone

import requests

# upload.wikimedia.org 429 시 재시도 딜레이(초)
_WIKIMEDIA_RETRY_DELAYS = [3, 8]

sys.path.insert(0, str(Path(__file__).resolve().parent))
import json_utils as JU

ROOT = Path(__file__).resolve().parent.parent
LOGOS_DIR = ROOT / "assets" / "logos"
LOGOS_DIR.mkdir(parents=True, exist_ok=True)

MANIFEST_PATH = Path(__file__).resolve().parent / "assets_manifest.json"

_UA = {"User-Agent": "trader-cho-assets/1.0 (educational content; not commercial)"}
_WUA = {"User-Agent": "trader-cho-assets/1.0 (educational shorts; Wikidata bot)"}

# 티커 → (회사명, Wikidata QID). QID 있으면 검색 1회 절약.
TICKER_WIKI: dict[str, tuple[str, str | None]] = {
    "ARM":  ("Arm Holdings", "Q296782"),
    "NVDA": ("Nvidia", "Q182477"),
    "TSLA": ("Tesla, Inc.", "Q478214"),
    "AAPL": ("Apple Inc.", "Q312"),
    "MSFT": ("Microsoft", "Q2283"),
    "GOOGL":("Google", "Q95"),
    "AMZN": ("Amazon", "Q3884"),
    "META": ("Meta Platforms", "Q380"),
    "AMD":  ("Advanced Micro Devices", "Q128896"),
    "INTC": ("Intel", "Q248"),
    "AVGO": ("Broadcom Inc.", "Q188113"),
    "QCOM": ("Qualcomm", "Q156455"),
    "MU":   ("Micron Technology", "Q743809"),
    "TSM":  ("TSMC", "Q713489"),
    "ASML": ("ASML Holding", "Q1065596"),
    "MRVL": ("Marvell Technology", None),
    "PLTR": ("Palantir Technologies", None),
    "SMCI": ("Supermicro", None),
    "DELL": ("Dell Technologies", None),
    "ORCL": ("Oracle Corporation", "Q41506"),
    "CRM":  ("Salesforce", None),
    "NFLX": ("Netflix", "Q907311"),
    "DIS":  ("The Walt Disney Company", None),
    "BA":   ("Boeing", "Q66"),
    "JPM":  ("JPMorgan Chase", "Q192412"),
    "BAC":  ("Bank of America", "Q487921"),
    "V":    ("Visa Inc.", "Q2119655"),
    "MA":   ("Mastercard", "Q3047622"),
    "WMT":  ("Walmart", "Q483551"),
    "COST": ("Costco", "Q715583"),
    "NKE":  ("Nike, Inc.", "Q483915"),
    "DAL":  ("Delta Air Lines", "Q188887"),
    "UAL":  ("United Airlines", "Q174769"),
    "CIEN": ("Ciena Corporation", None),
    "RIVN": ("Rivian", None),
    "COIN": ("Coinbase", None),
    "UBER": ("Uber", None),
}

# 티커 → 도메인 (Logo.dev 3순위)
LOGO_DEV_DOMAINS: dict[str, str] = {
    "ARM":  "arm.com",   "NVDA": "nvidia.com",  "TSLA": "tesla.com",
    "AAPL": "apple.com", "MSFT": "microsoft.com","GOOGL":"google.com",
    "AMZN": "amazon.com","META": "meta.com",     "AMD":  "amd.com",
    "INTC": "intel.com", "AVGO": "broadcom.com", "QCOM": "qualcomm.com",
    "MU":   "micron.com","TSM":  "tsmc.com",     "ASML": "asml.com",
    "MRVL": "marvell.com","PLTR":"palantir.com", "DELL": "dell.com",
    "ORCL": "oracle.com","CRM":  "salesforce.com","NFLX":"netflix.com",
    "DIS":  "disney.com","BA":   "boeing.com",   "JPM":  "jpmorganchase.com",
    "V":    "visa.com",  "MA":   "mastercard.com","WMT":  "walmart.com",
    "NKE":  "nike.com",  "DAL":  "delta.com",    "UAL":  "united.com",
    "CIEN": "ciena.com", "COIN": "coinbase.com", "UBER": "uber.com",
    "RIVN": "rivian.com",
}


# upload.wikimedia.org 429 지속 종목에 대한 직접 썸네일 URL (Wikidata P154 확인 후 하드코딩).
# URL 변경 시 Wikidata → Commons API로 재조회: _wikidata_logo 로직 참조.
_DIRECT_THUMB: dict[str, tuple[str, str]] = {
    # ticker: (thumburl, wikidata_source_url)
    "ARM":  ("https://upload.wikimedia.org/wikipedia/commons/thumb/7/7a/Arm_logo_2025.svg/512px-Arm_logo_2025.svg.png",
             "https://www.wikidata.org/wiki/Q296782"),
}


def _direct_logo(ticker: str) -> tuple[bytes | None, str]:
    """직접 썸네일 URL(하드코딩) → bytes. 429 throttle 우회용."""
    entry = _DIRECT_THUMB.get(ticker.upper())
    if not entry:
        return None, ""
    url, source = entry
    for delay in [0, 4, 10]:
        if delay:
            time.sleep(delay)
        try:
            r = requests.get(url, headers=_WUA, timeout=20)
            if r.status_code == 200 and _is_image(r.content):
                return r.content, source
            if r.status_code != 429:
                break
        except Exception:
            break
    return None, ""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _cache_path(ticker: str) -> Path:
    return LOGOS_DIR / f"{ticker.upper()}.png"


def _load_cache(ticker: str) -> Path | None:
    p = _cache_path(ticker)
    return p if p.exists() and p.stat().st_size > 500 else None


def _save_cache(ticker: str, data: bytes) -> Path:
    p = _cache_path(ticker)
    p.write_bytes(data)
    return p


def _is_image(data: bytes) -> bool:
    return (data[:8].startswith(b"\x89PNG") or data[:3] == b"\xff\xd8\xff"
            or data[:4] == b"GIF8" or data[:4] == b"RIFF")


def _wikidata_logo(ticker: str) -> tuple[bytes | None, str]:
    """Wikidata P154 → PNG bytes. (bytes|None, source_url)."""
    info = TICKER_WIKI.get(ticker.upper())
    if not info:
        return None, ""
    name, qid = info
    try:
        if not qid:
            r = requests.get("https://www.wikidata.org/w/api.php", headers=_WUA, timeout=15,
                             params={"action": "wbsearchentities", "search": name,
                                     "language": "en", "type": "item", "format": "json", "limit": 1})
            hits = r.json().get("search", [])
            if not hits:
                return None, ""
            qid = hits[0]["id"]
        e = requests.get(f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json",
                         headers=_WUA, timeout=15)
        claims = e.json()["entities"][qid]["claims"]
        if "P154" not in claims:
            return None, ""
        fn = claims["P154"][0]["mainsnak"]["datavalue"]["value"]
        a = requests.get("https://commons.wikimedia.org/w/api.php", headers=_WUA, timeout=15,
                         params={"action": "query", "titles": f"File:{fn}", "prop": "imageinfo",
                                 "iiprop": "url", "iiurlwidth": 512, "format": "json"})
        page = list(a.json()["query"]["pages"].values())[0]
        thumb = page["imageinfo"][0]["thumburl"]
        # upload.wikimedia.org 429 → retry with delay
        for attempt, delay in enumerate([0] + _WIKIMEDIA_RETRY_DELAYS):
            if delay:
                time.sleep(delay)
            img = requests.get(thumb, headers=_WUA, timeout=20)
            if img.status_code == 200 and _is_image(img.content):
                return img.content, f"https://www.wikidata.org/wiki/{qid}"
            if img.status_code != 429:
                break
        return None, ""
    except Exception:
        return None, ""


def _logodev_logo(ticker: str) -> tuple[bytes | None, str]:
    """Logo.dev → PNG bytes. LOGODEV_API_KEY 필요 (무료: logo.dev 가입 후 취득).
    키 없으면 401 → skip. .env에 LOGODEV_API_KEY=<key> 추가 시 동작."""
    domain = LOGO_DEV_DOMAINS.get(ticker.upper())
    if not domain:
        return None, ""
    key = os.environ.get("LOGODEV_API_KEY", "")
    if not key:
        return None, ""   # 키 없으면 바로 skip (401 요청 낭비 방지)
    params: dict = {"token": key, "format": "png", "size": "256"}
    try:
        r = requests.get(f"https://img.logo.dev/{domain}", params=params,
                         headers=_UA, timeout=10)
        if r.status_code == 200 and _is_image(r.content):
            return r.content, f"https://img.logo.dev/{domain}"
        return None, ""
    except Exception:
        return None, ""


def _record_manifest(ticker: str, source: str, url: str, license_: str, cached_at: str):
    """assets_manifest.json(전역)에 로고 취득 기록."""
    try:
        import json
        m: list = json.loads(MANIFEST_PATH.read_text()) if MANIFEST_PATH.exists() else []
        file_str = str(_cache_path(ticker))
        m = [x for x in m if x.get("file") != file_str]
        m.append({"file": file_str, "source": source, "url": url,
                  "license": license_, "downloaded_at": cached_at, "used_in": ["thumbnail"]})
        JU.atomic_write_json(MANIFEST_PATH, m)
    except Exception as e:
        print(f"  ⚠ manifest 기록 실패: {e}")


def get_logo(ticker: str, verbose: bool = True) -> Path | None:
    """티커 로고 Path 반환. 없으면 None(graceful skip).
    우선순위: 로컬캐시 → Wikidata → 직접URL(429우회) → Logo.dev → None.
    """
    ticker = ticker.upper()

    # 1순위: 로컬 캐시
    cached = _load_cache(ticker)
    if cached:
        if verbose:
            print(f"  logo {ticker}: cache hit")
        return cached

    # 2순위: Wikidata P154 (CC-BY-SA)
    if verbose:
        print(f"  logo {ticker}: trying Wikidata…", end=" ", flush=True)
    data, url = _wikidata_logo(ticker)
    if data:
        p = _save_cache(ticker, data)
        _record_manifest(ticker, f"Wikidata P154 · {TICKER_WIKI.get(ticker, (ticker,))[0]}",
                         url, "CC-BY-SA (Wikimedia Commons; trademark of respective owner)", _now())
        if verbose:
            print("OK")
        return p

    # 2.5순위: 직접 썸네일 URL (Wikidata P154 확인됐으나 429 throttle 종목)
    data, url = _direct_logo(ticker)
    if data:
        p = _save_cache(ticker, data)
        _record_manifest(ticker, f"Wikidata P154 (direct) · {TICKER_WIKI.get(ticker, (ticker,))[0]}",
                         url, "CC-BY-SA (Wikimedia Commons; trademark of respective owner)", _now())
        if verbose:
            print("OK (direct)")
        return p
    if verbose:
        print("fail → Logo.dev…", end=" ", flush=True)

    # 3순위: Logo.dev (상표 display only)
    data, url = _logodev_logo(ticker)
    if data:
        p = _save_cache(ticker, data)
        _record_manifest(ticker, f"Logo.dev · {LOGO_DEV_DOMAINS.get(ticker, '')}",
                         url, "trademark (display only, educational use)", _now())
        if verbose:
            print("OK")
        return p
    if verbose:
        print("skip")

    # 4순위: graceful skip
    return None


if __name__ == "__main__":
    import sys
    tickers = sys.argv[1:] or ["ARM", "NVDA", "TSLA", "AVGO", "DAL"]
    for t in tickers:
        p = get_logo(t)
        print(f"  → {p}")
