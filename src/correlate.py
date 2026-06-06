"""correlate.py — 상관관계 '연관종목' 엔진 (P2).

pandas .corr() 로 일간수익률 상관계수를 계산한다. 이는 예측이 아니라 **계산된 사실**이므로
가드레일 안전지대(🟢): "NVDA 와 역사적으로 동행한 종목" = 관찰·사실 프레임.

각 포커스 종목에 대해 가장 상관 높은 동행 종목 top-N 을 kind='derived' 로 적재한다.
엣지마다 '계산값'임을 명시하고, 표본기간/방법을 함께 기록한다.
"""
from __future__ import annotations
import json

from .common import log, utc_now
from . import rag_store

# 상관관계가 의미 있으려면 최소 표본 일수
MIN_OBS = 20
# "강한 동행"으로 부를 임계 (자막 표현 게이트)
STRONG = 0.5


def compute(conn, closes, focus_tickers=None, top_n: int = 3,
            period_label: str = "60d", exclude_peers=None) -> dict:
    """closes: yfinance 종가 DataFrame. 상관계수 계산 + 연관종목 적재.
    exclude_peers: 동행 후보에서 제외할 심볼(예: 지수 ETF — 'SPY와 동행'은 진부).
    반환: {ticker: [{"peer","corr","strong"}...]} + corr 행렬 메타."""
    if closes is None or len(closes) < MIN_OBS or closes.shape[1] < 2:
        log("WARN", f"상관관계 표본 부족(rows={0 if closes is None else len(closes)}) — 건너뜀", "correlate")
        return {"pairs": {}, "n_obs": 0}

    rets = closes.pct_change().dropna()
    if len(rets) < MIN_OBS:
        log("WARN", f"수익률 표본 부족({len(rets)}) — 건너뜀", "correlate")
        return {"pairs": {}, "n_obs": len(rets)}

    # 재계산 스냅샷이므로 이전 correlation_engine derived 문서를 정리(값 drift 누적 방지)
    try:
        conn.execute("DELETE FROM documents WHERE kind='derived' AND source='correlation_engine'")
    except Exception as e:
        log("WARN", f"이전 상관관계 정리 실패(비차단): {e}", "correlate")

    corr = rets.corr()
    cols = list(corr.columns)
    exclude = set(exclude_peers or [])
    focus = [t for t in (focus_tickers or cols) if t in cols]
    pairs: dict[str, list] = {}
    n = 0
    for t in focus:
        series = corr[t].drop(t).drop(labels=[c for c in exclude if c in corr.columns],
                                      errors="ignore").dropna().sort_values(ascending=False)
        peers = [{"peer": p, "corr": round(float(c), 3), "strong": bool(c >= STRONG)}
                 for p, c in series.head(top_n).items()]
        if not peers:
            continue
        pairs[t] = peers
        # 자막용 사실 문장 — '계산된 상관' 명시
        peer_str = ", ".join(f"{p['peer']} (r={p['corr']:+.2f})" for p in peers)
        content = (f"{t} historically moved together with {peer_str} "
                   f"[Pearson correlation of daily returns, last {period_label}, n={len(rets)} sessions]. "
                   f"Computed fact, not a forecast.")
        rag_store.add_document(
            conn, kind="derived", source="correlation_engine", source_type="derived",
            ticker=t, title=f"{t} correlated peers",
            content=content, url=None, published_utc=utc_now(),
            extra_json=json.dumps({"method": "pearson_daily_returns",
                                   "n_obs": len(rets), "period": period_label,
                                   "peers": peers}),
        )
        n += 1
    log("INFO", f"상관관계 연관종목 {n}건 적재(표본 {len(rets)}세션)", "correlate")
    return {"pairs": pairs, "n_obs": len(rets), "tickers": cols}
