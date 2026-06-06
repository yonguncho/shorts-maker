"""budget.py — 무료티어 일일 콜 예산 가드 (state/source_budget.json).

어댑터(수집기)는 외부 호출 전 can_spend()로 한도를 확인하고, 호출 후 spend()로 카운트한다.
날짜(UTC)가 바뀌면 used 가 자동 리셋된다. 한도 초과 시 수집기는 그 소스를 건너뛴다.
값(키)은 절대 저장하지 않는다 — 오직 콜 카운트만.
"""
from __future__ import annotations

from .common import STATE_DIR, read_json, write_json_atomic, today_utc, utc_now, log

BUDGET_PATH = STATE_DIR / "source_budget.json"

# 소스별 일일 콜 한도 (무료티어 기준 보수적 설정)
DEFAULT_LIMITS = {
    "finnhub": 2000,    # 60/min — 일일론 넉넉, churn 방지용 상한
    "yfinance": 2000,   # 비공식, 하드리밋 없음 → 보수적 상한
    "pytrends": 100,    # 비공식, 429 잦음 → 낮게
    "reddit": 1000,     # OAuth 100/min
    "newsapi": 100,     # 무료티어
    "sec": 1000,        # fair-access(초당 제한은 수집기 sleep 으로)
}


def _fresh() -> dict:
    return {
        "schema_version": "1.0",
        "date": today_utc(),
        "limits": dict(DEFAULT_LIMITS),
        "used": {k: 0 for k in DEFAULT_LIMITS},
        "updated_utc": utc_now(),
    }


def load_budget() -> dict:
    b = read_json(BUDGET_PATH, default=None)
    if not b or b.get("date") != today_utc():
        b = _fresh()
        write_json_atomic(BUDGET_PATH, b)
    # 새 소스가 코드에 추가됐을 때 키 보강
    for k, v in DEFAULT_LIMITS.items():
        b.setdefault("limits", {}).setdefault(k, v)
        b.setdefault("used", {}).setdefault(k, 0)
    return b


def remaining(source: str) -> int:
    b = load_budget()
    return int(b["limits"].get(source, 0)) - int(b["used"].get(source, 0))


def can_spend(source: str, n: int = 1) -> bool:
    return remaining(source) >= n


def spend(source: str, n: int = 1) -> int:
    """n 콜 소비를 기록하고 잔량 반환. 한도 없는 소스는 동적 추가."""
    b = load_budget()
    b["limits"].setdefault(source, DEFAULT_LIMITS.get(source, 1000))
    b["used"][source] = int(b["used"].get(source, 0)) + n
    b["updated_utc"] = utc_now()
    write_json_atomic(BUDGET_PATH, b)
    rem = int(b["limits"][source]) - int(b["used"][source])
    if rem < 0:
        log("WARN", f"예산 초과: {source} used={b['used'][source]} limit={b['limits'][source]}", "budget")
    return rem
