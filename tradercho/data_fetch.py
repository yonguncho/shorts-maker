"""data_fetch.py — yfinance 래퍼 (Phase 3-1).

입력: 티커 → price_json (가격/변동률/거래량배율/RSI/52주/SPX 상대강도/as_of ET).
yfinance 실데이터만(L0.4). 데이터 부족 시 기간 자동 축소 + 경고. 시간대 항상 ET.
"""
from __future__ import annotations
import math
from datetime import time
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


def _rsi(series, period=14):
    if len(series) < period + 1:
        return None
    delta = series.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    ag, al = float(gain.iloc[-1]), float(loss.iloc[-1])
    if al == 0:
        return 100.0
    return round(100 - 100 / (1 + ag / al), 1)


def _position_52w(last, hi, lo):
    if hi <= lo:
        return "mid"
    off_high = (last / hi - 1) * 100
    off_low = (last / lo - 1) * 100
    if off_high >= -1:
        return "52w HIGH"
    if off_high >= -5:
        return "near high"
    if off_low <= 3:
        return "52w LOW"
    if off_low <= 12:
        return "near low"
    return "mid"


def _spx_change():
    import yfinance as yf
    try:
        h = yf.Ticker("^GSPC").history(period="5d", auto_adjust=True)
        if len(h) >= 2:
            return round((float(h["Close"].iloc[-1]) / float(h["Close"].iloc[-2]) - 1) * 100, 2)
    except Exception:
        pass
    return None


def _fetch_analyst(t) -> dict | None:
    """애널리스트 컨센서스·목표주가·다음 어닝일 취득. 실패 시 None 반환."""
    out = {}
    try:
        rec = t.recommendations_summary
        if rec is not None and not getattr(rec, "empty", True):
            row = rec.iloc[0]
            out["consensus"] = {
                "period": str(row.get("period", "")),
                "strong_buy": int(row.get("strongBuy", 0) or 0),
                "buy": int(row.get("buy", 0) or 0),
                "hold": int(row.get("hold", 0) or 0),
                "sell": int(row.get("sell", 0) or 0),
                "strong_sell": int(row.get("strongSell", 0) or 0),
            }
    except Exception:
        pass
    try:
        pt = t.analyst_price_targets
        if pt is not None:
            pt_d = pt.to_dict() if hasattr(pt, "to_dict") else (pt if isinstance(pt, dict) else {})
            cleaned = {}
            for k, v in pt_d.items():
                try:
                    fv = float(v)
                    if not math.isnan(fv):
                        cleaned[k] = round(fv, 2)
                except Exception:
                    pass
            if cleaned:
                out["price_targets"] = cleaned
    except Exception:
        pass
    try:
        import pandas as pd
        ed = t.earnings_dates
        if ed is not None and not getattr(ed, "empty", True):
            now = pd.Timestamp.now(tz="UTC")
            future = ed[ed.index > now]
            if not future.empty:
                out["next_earnings"] = str(future.index[0].date())
    except Exception:
        pass
    return out if out else None


def fetch(ticker: str) -> dict:
    import yfinance as yf
    warnings = []
    t = yf.Ticker(ticker)
    h = t.history(period="1y", auto_adjust=True)
    if h is None or len(h) < 2:
        raise ValueError(f"{ticker}: 시세 데이터 없음")
    if len(h) < 63:
        warnings.append(f"상장/데이터 < 3개월({len(h)}봉) — 가용 기간으로 계산")

    closes = h["Close"].dropna()
    vols = h["Volume"].dropna()
    last = float(closes.iloc[-1])
    prev = float(closes.iloc[-2])
    pct = round((last / prev - 1) * 100, 2)
    hi52, lo52 = float(closes.max()), float(closes.min())
    rsi = _rsi(closes)
    vol_vs_avg = None
    if len(vols) >= 31 and vols.tail(30).mean() > 0:
        vol_vs_avg = round(float(vols.iloc[-1] / vols.tail(30).mean()), 2)
    spx = _spx_change()
    rs = round(pct - spx, 2) if spx is not None else None

    last_dt = closes.index[-1]
    try:
        as_of = last_dt.tz_convert(ET).replace(hour=16, minute=0, second=0, microsecond=0).isoformat()
    except Exception:
        as_of = last_dt.to_pydatetime().replace(tzinfo=ET, hour=16, minute=0, second=0).isoformat()

    analyst = _fetch_analyst(t)
    result = {
        "ticker": ticker.upper(),
        "last_close": round(last, 2),
        "pct_change": pct,
        "vol_vs_avg": vol_vs_avg,
        "rsi": rsi,
        "high_52w": round(hi52, 2),
        "low_52w": round(lo52, 2),
        "position_52w": _position_52w(last, hi52, lo52),
        "spx_pct_change": spx,
        "relative_strength": rs,
        "as_of": as_of,
        "warnings": warnings,
        # 차트용 3개월 종가(Phase 4 chart_panel)
        "series_3m": [round(float(v), 2) for v in closes.tail(63)],
    }
    if analyst:
        result["analyst"] = analyst
        cons = analyst.get("consensus", {})
        total = sum(cons.get(k, 0) for k in ("strong_buy", "buy", "hold", "sell", "strong_sell"))
        bull = cons.get("strong_buy", 0) + cons.get("buy", 0)
        print(f"  [ANALYST] consensus: {bull}/{total} bullish  "
              f"target={analyst.get('price_targets', {}).get('mean', 'N/A')}  "
              f"next_earnings={analyst.get('next_earnings', 'N/A')}")
    else:
        print("  [ANALYST] 데이터 없음 (스킵)")
    return result


if __name__ == "__main__":
    import json
    import sys
    tk = sys.argv[1] if len(sys.argv) > 1 else "ARM"
    d = fetch(tk)
    d.pop("series_3m", None)
    print(json.dumps(d, indent=2))
