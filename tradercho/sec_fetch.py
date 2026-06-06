"""sec_fetch.py — SEC EDGAR 당일 8-K 공시 수집.

EDGAR 공개 REST API (무료·무키). 요청 실패/공시 없어도 파이프라인 중단 없음.
사용: python sec_fetch.py AAPL
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests

ROOT = Path(__file__).resolve().parent.parent
_UA = {"User-Agent": "TraderCho/1.0 yongun.cho03@gmail.com", "Accept": "application/json"}
_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"


def _today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _get(url: str, params: dict, retries: int = 1) -> dict | None:
    """EDGAR API GET. 실패 시 1회 재시도 후 None 반환."""
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, headers=_UA, params=params, timeout=10)
            if r.status_code == 200:
                return r.json()
            if attempt < retries:
                time.sleep(2)
        except Exception:
            if attempt < retries:
                time.sleep(2)
    return None


def fetch(ticker: str, date: str | None = None) -> dict:
    """당일 8-K 공시 수집. 공시 없어도 항상 dict 반환 (파이프라인 중단 없음)."""
    today = date or _today_str()
    base = {
        "ticker": ticker.upper(),
        "as_of": today,
        "has_8k": False,
        "filings": [],
    }

    params = {
        "q": f'"{ticker.upper()}"',
        "forms": "8-K",
        "dateRange": "custom",
        "startdt": today,
        "enddt": today,
    }

    data = _get(_SEARCH_URL, params)
    if not data:
        print(f"  [SEC] {ticker}: API 응답 없음 (스킵)")
        return base

    hits = data.get("hits", {}).get("hits", [])
    if not hits:
        print(f"  [SEC] {ticker}: 당일 8-K 없음")
        return base

    filings = []
    for h in hits[:5]:
        src = h.get("_source", {})
        entity = src.get("entity_name", "")
        if entity and ticker.upper() not in entity.upper():
            # 티커 문자열이 다른 회사에 포함된 경우 필터
            pass
        filed_at = src.get("file_date", today)
        accession = src.get("file_num", "") or src.get("period_of_report", "")
        form_url = src.get("file_url", "")
        if not form_url:
            # accession 번호로 EDGAR URL 조합
            acc_no = (h.get("_id") or "").replace("/", "-")
            form_url = f"https://www.sec.gov/Archives/edgar/data/{acc_no}" if acc_no else ""

        display = src.get("display_names", ticker)
        if isinstance(display, list):
            display = ", ".join(display)
        filings.append({
            "title": src.get("form_type", "8-K") + " — " + str(display),
            "filed_at": filed_at,
            "url": form_url,
            "description": (src.get("file_description") or "")[:200],
        })

    base["has_8k"] = len(filings) > 0
    base["filings"] = filings
    print(f"  [SEC] {ticker}: 8-K {len(filings)}건 발견")
    return base


def save(result: dict, out_dir: Path) -> Path:
    """out_dir/sec_8k.json 저장."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "sec_8k.json"
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


if __name__ == "__main__":
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    result = fetch(ticker)
    print(json.dumps(result, indent=2, ensure_ascii=False))
