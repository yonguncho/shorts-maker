"""tc_report.py — Windows Dashboard 에이전트 상태 보고.

엔드포인트: http://100.117.42.16:8765/api/tradercho/report
fire-and-forget: 실패해도 파이프라인 중단 없음.

사용:
  from tc_report import reporter
  r = reporter("ARM", "20260605")
  r("data_fetch", pct_change=-12.84)
  r("compose", status="done", duration_s=44.0)
  r("error", stage="trader_lens", error="timeout")
"""
from __future__ import annotations
import json
import urllib.request as _ur

DASHBOARD_URL = "http://100.117.42.16:8765/api/tradercho/report"


def send(stage: str, ticker: str = "", date: str = "",
         status: str = "running", **kwargs) -> None:
    """단건 보고. 실패 시 조용히 무시."""
    payload = {"date": date, "stage": stage, "ticker": ticker,
               "status": status, **kwargs}
    try:
        _ur.urlopen(_ur.Request(
            DASHBOARD_URL,
            data=json.dumps(payload, default=str).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        ), timeout=3)
    except Exception:
        pass


def reporter(ticker: str, date: str):
    """ticker·date를 고정한 보고 함수 반환. 파이프라인 run() 내부에서 사용."""
    def _r(stage: str, status: str = "running", **kwargs):
        send(stage, ticker=ticker, date=date, status=status, **kwargs)
    return _r
