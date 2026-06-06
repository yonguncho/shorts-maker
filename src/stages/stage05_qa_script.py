"""stage05 — ⑤ 대본/사실 검증 (QA_mac).

입력 : state/script.json                (stage04 — 자막 비트)
       state/verified_market_data.json  (stage01 — 검증 사실의 단일 진실)
산출물: state/qa_script.json             (항목별 PASS/FAIL 리포트 + 종합 verdict)

검증 항목(전부 결정론적):
  1) structure   — 훅/데이터/맥락/클로저 존재, 총 길이가 목표±tol
  2) timecodes   — 비트 시간 연속·비음수, 합계==총길이
  3) sourcing    — 클로저 외 모든 비트에 출처 cite
  4) guardrail   — 자막에 투자권유/예측 표현 없음(stage02 ADVICE_RE, defense-in-depth)
  5) fact_match  — 자막의 수치(±pct%, $price)가 verified_market_data 와 일치(환각 차단, 핵심)
  6) readability — 자막 길이 상한(경고)

verdict=fail 이면 rc!=0 → main_harness 가 파이프라인 정지.
실행: .venv/bin/python -m src.stages.stage05_qa_script
"""
from __future__ import annotations
import re

from ..common import read_json, write_json_atomic, log, utc_now, STATE_DIR
from .stage02_analysis_report import ADVICE_RE, _price, _pct

SCRIPT_PATH = STATE_DIR / "script.json"
DATA_PATH = STATE_DIR / "verified_market_data.json"
OUT_PATH = STATE_DIR / "qa_script.json"

DURATION_TOL = 1.0       # 목표 길이 허용 오차(초)
PCT_TOL = 0.01           # 변동률 일치 허용 오차(%p)
PRICE_TOL = 0.01         # 가격 일치 허용 오차(절대/상대 중 느슨)
SUBTITLE_MAX_CHARS = 90
SECTIONS_REQUIRED = ("hook", "data", "context", "closer")

_PCT_RE = re.compile(r"([+-]\d+(?:\.\d+)?)%")
_PRICE_RE = re.compile(r"\$(\d+(?:\.\d+)?)")
_BEAT_TICKER_RE = re.compile(r"\b([A-Z]{2,6})\b")


def _by_ticker(data: dict) -> dict:
    return {q["ticker"]: q for q in data.get("market_snapshot", []) if q.get("ticker")}


def check_structure(script: dict) -> dict:
    beats = script.get("beats", [])
    secs = {b.get("section") for b in beats}
    missing = [s for s in SECTIONS_REQUIRED if s not in secs]
    target = (script.get("spec") or {}).get("duration_sec", 45.0)
    total = script.get("total_duration_sec", 0)
    ok = not missing and abs(total - target) <= DURATION_TOL and len(beats) >= 4
    detail = []
    if missing:
        detail.append(f"누락 섹션: {missing}")
    if abs(total - target) > DURATION_TOL:
        detail.append(f"길이 {total}s ≠ 목표 {target}s(±{DURATION_TOL})")
    return {"name": "structure", "status": "pass" if ok else "fail",
            "detail": "; ".join(detail) or f"sections={sorted(secs)} total={total}s beats={len(beats)}"}


def check_timecodes(script: dict) -> dict:
    beats = script.get("beats", [])
    issues, prev_end, acc = [], 0.0, 0.0
    for b in beats:
        ts, te, d = b.get("t_start", 0), b.get("t_end", 0), b.get("duration_sec", 0)
        if ts < 0 or te < ts or d < 0:
            issues.append(f"beat{b.get('idx')}: 비정상 구간 {ts}-{te}(d={d})")
        if abs(ts - prev_end) > 0.05:
            issues.append(f"beat{b.get('idx')}: 시작 {ts}≠이전끝 {prev_end}(불연속)")
        if abs((ts + d) - te) > 0.05:
            issues.append(f"beat{b.get('idx')}: t_end {te}≠start+dur {ts + d}")
        prev_end = te
        acc += d
    if abs(acc - script.get("total_duration_sec", acc)) > 0.05:
        issues.append(f"duration 합 {round(acc, 1)}≠total {script.get('total_duration_sec')}")
    return {"name": "timecodes", "status": "pass" if not issues else "fail",
            "detail": "; ".join(issues) or f"{len(beats)}비트 연속·합계 일치"}


def check_sourcing(script: dict) -> dict:
    missing = [b.get("idx") for b in script.get("beats", [])
               if b.get("section") != "closer" and not (b.get("source") or "").strip()]
    return {"name": "sourcing", "status": "pass" if not missing else "fail",
            "detail": f"무출처 비트 {missing}" if missing else "클로저 외 전 비트 출처 보유"}


def check_guardrail(script: dict) -> dict:
    """파이프라인이 조립한 자막의 투자권유/예측 표현 검출(defense-in-depth).
    제3자 verbatim 인용(quote=True, 출처표기 헤드라인)은 '보도'이므로 제외 — stage03/04 동일 원칙."""
    bad = []
    for b in script.get("beats", []):
        if b.get("quote"):
            continue
        for m in ADVICE_RE.finditer(b.get("subtitle", "") or ""):
            bad.append(f"beat{b.get('idx')}: {m.group(0)!r}")
    return {"name": "guardrail", "status": "pass" if not bad else "fail",
            "detail": "; ".join(bad) or "투자권유/예측 표현 없음"}


def check_fact_match(script: dict, data: dict) -> dict:
    """자막 수치(±pct%, $price)가 verified_market_data 와 일치하는지 — 환각/오타 차단의 핵심.

    수치를 같은 비트의 티커에 결속한다: 비트에 티커가 정확히 1개면 그 티커에 모든 수치를 결속,
    여러 개면 'TICKER … ±%' 인접결속을 시도, 그래도 결속 불가하면 검증 누락으로 FAIL 처리
    (헤드라인 수치가 조용히 미검증되는 일을 막는다)."""
    by_ticker = _by_ticker(data)
    mism, checked = [], 0
    for b in script.get("beats", []):
        # 제3자 verbatim 인용 헤드라인은 우리 데이터로 대조할 대상이 아님(인용은 출처가 사실 주체)
        if b.get("quote"):
            continue
        sub = b.get("subtitle", "") or ""
        uniq = list(dict.fromkeys(s for s in _BEAT_TICKER_RE.findall(sub) if s in by_ticker))
        pcts = _PCT_RE.findall(sub)
        prices = _PRICE_RE.findall(sub)

        # ── 변동률 결속 ──
        if pcts:
            if len(uniq) == 1:
                sym = uniq[0]
                for ps in pcts:
                    checked += 1
                    vpct = _pct(by_ticker[sym])
                    if vpct is None or abs(vpct - float(ps)) > PCT_TOL:
                        mism.append(f"beat{b['idx']}: {sym} {ps}% ≠ 검증 {vpct}%")
            else:
                adj = re.findall(r"\b([A-Z]{2,6})\b[^%]*?([+-]\d+(?:\.\d+)?)%", sub)
                adj = [(s, p) for s, p in adj if s in by_ticker]
                if len(adj) == len(pcts) and adj:
                    for sym, ps in adj:
                        checked += 1
                        vpct = _pct(by_ticker[sym])
                        if vpct is None or abs(vpct - float(ps)) > PCT_TOL:
                            mism.append(f"beat{b['idx']}: {sym} {ps}% ≠ 검증 {vpct}%")
                else:
                    mism.append(f"beat{b['idx']}: 수치 {pcts}% 를 티커에 결속 불가(tickers={uniq}) — 검증 누락")

        # ── 가격 결속(같은 비트 티커 필요) ──
        if prices:
            if uniq:
                sym = uniq[0]
                vprice = _price(by_ticker[sym])
                for ps in prices:
                    checked += 1
                    if vprice is None or abs(vprice - float(ps)) > max(PRICE_TOL, (vprice or 0) * 0.001):
                        mism.append(f"beat{b['idx']}: {sym} ${ps} ≠ 검증 ${vprice}")
            else:
                mism.append(f"beat{b['idx']}: 가격 ${prices} 결속할 티커 없음 — 검증 누락")

    status = "pass" if not mism else "fail"
    return {"name": "fact_match", "status": status,
            "detail": "; ".join(mism) or f"수치 {checked}건 전부 검증데이터와 일치"}


def check_readability(script: dict) -> dict:
    longs = [b.get("idx") for b in script.get("beats", [])
             if len(b.get("subtitle", "") or "") > SUBTITLE_MAX_CHARS]
    return {"name": "readability", "status": "pass" if not longs else "warn",
            "detail": f"{SUBTITLE_MAX_CHARS}자 초과 비트 {longs}(렌더 줄바꿈 필요)" if longs
                      else f"전 자막 ≤{SUBTITLE_MAX_CHARS}자"}


def main() -> int:
    log("INFO", "=== STAGE ⑤ 대본 QA 시작 ===", "stage05")
    script = read_json(SCRIPT_PATH, default=None)
    if not script or not script.get("beats"):
        log("ERROR", f"입력 없음/비트 없음: {SCRIPT_PATH} (stage04 먼저 실행 필요)", "stage05")
        return 2
    data = read_json(DATA_PATH, default={}) or {}

    checks = [
        check_structure(script),
        check_timecodes(script),
        check_sourcing(script),
        check_guardrail(script),
        check_fact_match(script, data),
        check_readability(script),
    ]
    fails = [c for c in checks if c["status"] == "fail"]
    warns = [c for c in checks if c["status"] == "warn"]
    verdict = "fail" if fails else "pass"

    out = {
        "schema_version": "1.0", "pipeline_id": "shorts_maker", "machine": "mac",
        "stage": 5, "agent": "QA_mac", "generated_utc": utc_now(),
        "date": script.get("date"), "source_files": [SCRIPT_PATH.name, DATA_PATH.name],
        "verdict": verdict, "checks": checks,
        "summary": {"total": len(checks), "fail": len(fails), "warn": len(warns),
                    "pass": len(checks) - len(fails) - len(warns)},
    }
    write_json_atomic(OUT_PATH, out)

    for c in checks:
        lvl = "ERROR" if c["status"] == "fail" else ("WARN" if c["status"] == "warn" else "INFO")
        log(lvl, f"[{c['status'].upper()}] {c['name']}: {c['detail']}", "stage05")

    if verdict == "fail":
        log("ERROR", f"=== STAGE ⑤ FAIL: {len(fails)}개 검증 실패 → 파이프라인 정지 ===", "stage05")
        return 4
    log("INFO", f"=== STAGE ⑤ PASS: {len(checks)}개 검증 통과(warn={len(warns)}) ===", "stage05")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
