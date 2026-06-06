"""themes.py — '오늘 가장 뜨거운 테마' 탐지 (뉴스 트렌드 + 종목 움직임).

각 테마(반도체AI/우주/EV/크립토/클라우드)를 두 신호로 점수화한다 — 둘 다 '사실':
  - news_hits: 채택 뉴스(저신뢰 애그리게이터 포함) 제목/본문이 테마 키워드와 매칭된 건수(=이슈 화제성).
  - 움직임: 테마 종목들의 당일 |변동률| 평균·최대 및 상승 폭(=시장 반응).
점수 = 뉴스화제 + 변동강도. 소재 선정(stage03)이 이 1위 테마의 주인공 종목을 고른다.
예측·추천이 아니라 '오늘 뉴스가 많고 많이 움직인 섹터'라는 관찰 사실이다.
"""
from __future__ import annotations
import re

from .common import log
from .collect import THEMES

_PCT_RE = re.compile(r"pct=([-+]?\d+(?:\.\d+)?)")

W_NEWS = 1.0      # 뉴스 1건당
W_AVGABS = 1.5    # 평균 |변동률|
W_MAXABS = 0.6    # 최대 |변동률|


def _pct(q: dict):
    m = _PCT_RE.search(q.get("content", "") or "")
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def score_themes(data: dict) -> list[dict]:
    """테마별 점수 내림차순 리스트. 각 항목: name·score·news_hits·움직임 통계·present(현재 시세 보유 종목)."""
    news = data.get("news", [])
    snap = {q["ticker"]: q for q in data.get("market_snapshot", []) if q.get("ticker")}
    out = []
    for name, th in THEMES.items():
        kws, tickers = th["kw"], th["tickers"]
        hits = 0
        for n in news:
            blob = f"{n.get('title','')} {n.get('content','')}".lower()
            if any(k in blob for k in kws):
                hits += 1
        present = [t for t in tickers if t in snap and _pct(snap[t]) is not None]
        pcts = [_pct(snap[t]) for t in present]
        avg_abs = sum(abs(p) for p in pcts) / len(pcts) if pcts else 0.0
        max_abs = max((abs(p) for p in pcts), default=0.0)
        up = sum(1 for p in pcts if p > 0)
        score = hits * W_NEWS + avg_abs * W_AVGABS + max_abs * W_MAXABS
        out.append({
            "name": name, "score": round(score, 3), "news_hits": hits,
            "n_present": len(present), "up": up,
            "avg_abs_pct": round(avg_abs, 2), "max_abs_pct": round(max_abs, 2),
            "present": present,
        })
    out.sort(key=lambda x: x["score"], reverse=True)
    log("INFO", "테마 점수: " + " | ".join(
        f"{r['name']}={r['score']}(news{r['news_hits']},up{r['up']}/{r['n_present']})" for r in out),
        "themes")
    return out
