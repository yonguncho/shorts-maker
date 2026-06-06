"""h_stability.py — H.8 안정성 검증 번들.

렌더 단계가 아닌 정합성 검사 묶음:
  timeline 무결성 / metadata 스키마 / price 스키마 / ticker whitelist / safety cap
pipeline.py가 compose 완료 후 호출. 실패 항목은 경고 출력(raise 없음 — 게시 결정은 사용자).
"""
from __future__ import annotations
import json
from pathlib import Path
import json_utils as JU

# H.8: 지원 티커 화이트리스트 (확장 가능)
TICKER_WHITELIST = frozenset("""
ARM NVDA TSLA MRVL MU TSM ASML AMD AVGO INTC QCOM AAPL MSFT GOOGL AMZN
META AVAV PLTR SMCI DELL ORCL CRM NFLX DIS BA F GM RIVN COIN UBER
SPX SPY QQQ IWM
""".upper().split())

MAX_DURATION_S = 90.0
MIN_DURATION_S = 20.0


def validate(out_dir, ticker: str) -> list[dict]:
    """5개 검사 실행. 반환: [{check, ok, msg}, ...]
    ok=True/False/None(None=파일 없음·선택적 검사).
    """
    out_dir = Path(out_dir)
    results: list[dict] = []

    def _r(check: str, ok, msg: str = ""):
        results.append({"check": check, "ok": ok, "msg": msg})

    # 1. ticker whitelist
    ok = ticker.upper() in TICKER_WHITELIST
    _r("ticker_whitelist", ok,
       "" if ok else f"'{ticker}' not in TICKER_WHITELIST — add to h_stability.py")

    # 2. price schema
    pj = out_dir / "price.json"
    if pj.exists():
        issues = JU.check_price_schema(json.loads(pj.read_text()))
        _r("price_schema", not issues, "; ".join(issues))
    else:
        _r("price_schema", False, "price.json not found")

    # 3. timeline null 금지 (total_duration / scene.start / scene.end)
    tj = out_dir / "timeline.json"
    if tj.exists():
        issues = JU.check_timeline_schema(json.loads(tj.read_text()))
        _r("timeline_no_null", not issues, "; ".join(issues))
    else:
        _r("timeline_no_null", False, "timeline.json not found")

    # 4. safety cap (duration)
    if tj.exists():
        dur = json.loads(tj.read_text()).get("total_duration") or 0
        ok = MIN_DURATION_S <= dur <= MAX_DURATION_S
        _r("safety_cap", ok,
           f"duration={dur:.1f}s (allowed {MIN_DURATION_S:.0f}~{MAX_DURATION_S:.0f}s)")
    else:
        _r("safety_cap", False, "timeline.json missing — cannot check duration")

    # 5. metadata schema (선택적 — 게시 전 metadata_generator 미실행 시 None)
    mj = out_dir / "metadata.json"
    if mj.exists():
        issues = JU.check_metadata_schema(json.loads(mj.read_text()))
        _r("metadata_schema", not issues, "; ".join(issues))
    else:
        _r("metadata_schema", None, "metadata.json not present (run metadata_generator first)")

    return results


def report(results: list[dict]) -> str:
    lines = ["=== H_stability ==="]
    for r in results:
        ok = r["ok"]
        mark = "✓" if ok is True else ("—" if ok is None else "✗")
        line = f"  {mark} {r['check']}"
        if r["msg"]:
            line += f"  ← {r['msg']}"
        lines.append(line)
    fails = [r for r in results if r["ok"] is False]
    lines.append(f"  {'PASS' if not fails else f'FAIL({len(fails)})'}")
    return "\n".join(lines)
