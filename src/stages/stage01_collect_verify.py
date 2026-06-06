"""stage01 — ① 데이터 수집 + RAG 신빙성 검증 (Analyst).

실행: .venv/bin/python -m src.stages.stage01_collect_verify
산출물: state/verified_market_data.json
"""
from __future__ import annotations

from ..common import log, adversarial_gate_mode
from .. import collect, verify, rag_store


def main() -> int:
    log("INFO", "=== STAGE ① 데이터 수집 시작 ===", "stage01")
    conn = rag_store.connect()
    try:
        stats = collect.collect_all(conn)
        log("INFO", f"수집 요약: {stats}", "stage01")
        final = verify.run(conn)
    finally:
        conn.close()

    acc = (len(final["market_snapshot"]), len(final["news"]), len(final["filings"]))
    deb = final.get("credibility_debate", {})
    status = deb.get("status")
    log("INFO", f"=== STAGE ① 완료: 채택 quotes={acc[0]} news={acc[1]} filings={acc[2]} "
                f"| debate={status} {deb.get('total_rounds')}R ===", "stage01")
    # 게이트: passed/skipped 는 통과. 미통과 시 모드에 따라 — blocking=정지(rc3), advisory=경고+진행.
    if status in ("passed", "skipped"):
        return 0
    mode = adversarial_gate_mode()
    if mode == "blocking":
        log("ERROR", f"신빙성 공방 미통과({status}) — blocking 모드 → 단계 실패", "stage01")
        return 3
    log("WARN", f"신빙성 공방 미통과({status}) — advisory 모드: 지적은 credibility_debate 에 기록, "
                f"파이프라인은 진행. (blocking 복원: ADVERSARIAL_GATE_MODE=blocking)", "stage01")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
