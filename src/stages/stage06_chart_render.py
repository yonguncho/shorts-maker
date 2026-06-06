"""stage06 — ⑥ 차트 렌더 (Editor).

입력 : state/script.json                (stage04 — chart_plan / beats 의 chart_cue)
       state/verified_market_data.json  (stage01 — 시세 스냅샷)
산출물: output/assets/chart_<id>.png    (비트별 차트, 1080×1920 세로, 다크 미니멀)
        state/chart_render.json          (차트 id→파일 매핑 + 메타, stage07 가 사용)

설계:
  - 데이터는 스냅샷(현재가·변동률·OHLC)뿐 시계열 없음 → 정직하게 **% 변동 막대**로 표현.
    single_quote: 메가캡 피어 막대 중 포커스 종목 강조. index_panel: 지수 프록시 막대.
  - 다크 미니멀: 검정 배경·축소된 그리드·큰 폰트(세로 쇼츠 가독). 상단 타이틀, 하단 ~30%는
    자막용 여백(stage07 이 자막을 얹음). 하단 작은 출처/면책 라인.
  - 사용자 확정(2026-06-01): 차트=다크 미니멀, 규격=1080×1920.

실행: .venv/bin/python -m src.stages.stage06_chart_render
"""
from __future__ import annotations
import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from ..common import read_json, write_json_atomic, log, utc_now, OUTPUT_DIR, STATE_DIR
from .stage02_analysis_report import INDEX_PROXY, _pct, _price
from .. import rag_store

SCRIPT_PATH = STATE_DIR / "script.json"
DATA_PATH = STATE_DIR / "verified_market_data.json"
ASSETS_DIR = OUTPUT_DIR / "assets"
OUT_JSON = STATE_DIR / "chart_render.json"

W, H, DPI = 1080, 1920, 100
MEGACAP = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA"]

# 다크 미니멀 팔레트
BG = "#0b0d10"; FG = "#e6edf3"; SUB = "#9aa4ad"; GRID = "#20262d"
UP = "#3fb950"; DOWN = "#f85149"; DIM_A = 0.45; ACCENT = "#58a6ff"
# 연관종목 라인 팔레트(포커스=ACCENT, 피어 순환)
PEER_COLORS = ["#d29922", "#a371f7", "#3fb950", "#f85149"]


def _by_ticker(data: dict) -> dict:
    return {q["ticker"]: q for q in data.get("market_snapshot", []) if q.get("ticker")}


def _load_series(conn) -> dict:
    """RAG history(yfinance) 문서에서 ticker별 최신 종가 시계열 로드. {ticker: [(date, close)...]}."""
    out, seen = {}, set()
    for d in rag_store.search(conn, kind="history", limit=200):
        t = d.get("ticker")
        if not t or t in seen:
            continue
        seen.add(t)
        try:
            ex = json.loads(d.get("extra_json") or "{}")
        except (ValueError, TypeError):
            continue
        series = ex.get("series") or []
        if len(series) >= 5:
            out[t] = [(row[0], float(row[1])) for row in series if len(row) == 2]
    return out


def _chart_id(cue: dict) -> str:
    return f"{cue['type']}_{'-'.join(cue.get('symbols') or [])}"


def _series(syms, by_ticker, label_fn):
    """(label, pct) 목록 — pct 있는 종목만, pct 내림차순."""
    out = []
    for s in syms:
        q = by_ticker.get(s)
        if not q:
            continue
        pc = _pct(q)
        if pc is None:
            continue
        out.append((label_fn(s), s, pc))
    out.sort(key=lambda x: x[2], reverse=True)
    return out


def _fig_axes():
    fig = plt.figure(figsize=(W / DPI, H / DPI), dpi=DPI)
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0.16, 0.34, 0.72, 0.34])
    ax.set_facecolor(BG)
    for sp in ax.spines.values():
        sp.set_color(GRID)
    ax.tick_params(colors=SUB, labelsize=16, length=0)
    return fig, ax


def _render_price_line(focus: str, series_map: dict, path) -> dict | None:
    """포커스 종목의 과거 종가 라인 차트(다크 미니멀, 변동 방향 색·면적)."""
    s = series_map.get(focus)
    if not s or len(s) < 5:
        return None
    vals = [v for _, v in s]
    last, first = vals[-1], vals[0]
    chg = (last / first - 1) * 100 if first else 0.0
    color = UP if chg >= 0 else DOWN
    x = list(range(len(vals)))

    fig, ax = _fig_axes()
    ax.plot(x, vals, color=color, linewidth=3.0, zorder=3)
    ax.fill_between(x, vals, min(vals), color=color, alpha=0.12, zorder=2)
    ax.scatter([x[-1]], [last], color=color, s=60, zorder=4)
    ax.annotate(f"${last:,.2f}", (x[-1], last), color=FG, fontsize=22, fontweight="bold",
                xytext=(-10, 14), textcoords="offset points", ha="right")
    ax.set_xticks([0, len(vals) - 1]); ax.set_xticklabels([s[0][0], s[-1][0]], color=SUB, fontsize=14)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.margins(x=0.02)

    title = f"{focus} · 3-month"
    subtitle = f"Last ${last:,.2f} · {chg:+.1f}% (3M) · range ${min(vals):,.0f}–${max(vals):,.0f}"
    fig.text(0.5, 0.80, title, ha="center", color=FG, fontsize=52, fontweight="bold")
    fig.text(0.5, 0.745, subtitle, ha="center", color=SUB, fontsize=22)
    fig.text(0.5, 0.045, "Source: Yahoo Finance · educational commentary, not investment advice",
             ha="center", color=SUB, fontsize=18)
    fig.savefig(path, facecolor=BG); plt.close(fig)
    return {"title": title, "subtitle": subtitle,
            "series_points": len(vals), "period_change_pct": round(chg, 2),
            "bars": []}


def _render_correlation(syms: list, series_map: dict, corr_pairs: dict, path) -> dict | None:
    """포커스+연관종목의 리베이스(=100) 라인 오버레이 — '함께 움직였다'를 시각화."""
    if len(syms) < 2:
        return None
    focus, peers = syms[0], syms[1:]
    have = [t for t in syms if t in series_map and len(series_map[t]) >= 5]
    if focus not in have or len(have) < 2:
        return None
    # 공통 길이로 정렬(뒤에서 맞춤)
    n = min(len(series_map[t]) for t in have)
    r_by_peer = {p["peer"]: p.get("corr") for p in (corr_pairs.get(focus) or [])}

    fig, ax = _fig_axes()
    legend = []
    for t in have:
        vals = [v for _, v in series_map[t][-n:]]
        base = vals[0] or 1.0
        reb = [v / base * 100 for v in vals]
        x = list(range(n))
        if t == focus:
            ax.plot(x, reb, color=ACCENT, linewidth=3.4, zorder=4)
            legend.append((f"{t} (focus)", ACCENT))
        else:
            c = PEER_COLORS[peers.index(t) % len(PEER_COLORS)]
            ax.plot(x, reb, color=c, linewidth=2.2, alpha=0.9, zorder=3)
            r = r_by_peer.get(t)
            legend.append((f"{t}  r={r:+.2f}" if r is not None else t, c))
    ax.axhline(100, color=GRID, linewidth=1.0, zorder=1)
    dates = [d for d, _ in series_map[focus][-n:]]
    ax.set_xticks([0, n - 1]); ax.set_xticklabels([dates[0], dates[-1]], color=SUB, fontsize=14)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.margins(x=0.02)
    # 범례(수동 텍스트 — 다크 가독)
    for i, (lab, c) in enumerate(legend):
        fig.text(0.18, 0.66 - i * 0.028, "—", color=c, fontsize=26, fontweight="bold")
        fig.text(0.215, 0.662 - i * 0.028, lab, color=FG, fontsize=20)

    title = f"{focus} & peers move together"
    subtitle = "Rebased to 100 · 3-month · Pearson r of daily returns"
    fig.text(0.5, 0.80, title, ha="center", color=FG, fontsize=40, fontweight="bold")
    fig.text(0.5, 0.745, subtitle, ha="center", color=SUB, fontsize=20)
    fig.text(0.5, 0.045, "Source: Yahoo Finance (computed) · not investment advice",
             ha="center", color=SUB, fontsize=18)
    fig.savefig(path, facecolor=BG); plt.close(fig)
    return {"title": title, "subtitle": subtitle,
            "peers": [{"symbol": t, "corr": r_by_peer.get(t)} for t in have if t != focus],
            "bars": []}


def _render_article_shot(cue: dict, path) -> dict | None:
    """실제 기사 페이지를 Chrome 헤드리스로 캡처해 1080×1920 캔버스 상단에 배치(하단은 자막여백)."""
    from PIL import Image
    from ..article import capture_screenshot
    raw = ASSETS_DIR / "article_raw.png"
    if not capture_screenshot(cue.get("url", ""), str(raw)):
        return None
    try:
        shot = Image.open(raw).convert("RGB")
        w0, h0 = shot.size
        nh = int(h0 * W / w0)
        shot = shot.resize((W, nh))
        canvas = Image.new("RGB", (W, H), (11, 13, 16))
        canvas.paste(shot, (0, 0))                 # 상단에 기사 캡처, 하단 여백=자막 밴드
        canvas.save(path)
        return {"title": "article_screenshot", "subtitle": "", "bars": [], "captured": True}
    except Exception as e:
        log("WARN", f"기사 캡처 합성 실패: {type(e).__name__}", "stage06")
        return None


def _render(cue: dict, by_ticker: dict, series_map: dict, corr_pairs: dict, path) -> dict | None:
    typ = cue["type"]
    syms = cue.get("symbols") or []
    if typ == "article_shot":
        return _render_article_shot(cue, path)
    if typ == "price_line":
        return _render_price_line(syms[0], series_map, path) if syms else None
    if typ == "correlation":
        return _render_correlation(syms, series_map, corr_pairs, path)
    if typ == "single_quote":
        focus = syms[0] if syms else None
        rows = _series(MEGACAP, by_ticker, lambda s: s)
        if focus and focus not in [r[1] for r in rows]:  # 포커스가 메가캡 외면 단독
            q = by_ticker.get(focus)
            if q and _pct(q) is not None:
                rows = [(focus, focus, _pct(q))]
        fq = by_ticker.get(focus or "")
        fpct = _pct(fq) if fq else None
        fprice = _price(fq) if fq else None
        title = f"{focus} {fpct:+.2f}%" if fpct is not None else (focus or "—")
        subtitle = (f"Last ${fprice:g} · vs prior close" if fprice is not None else "Megacap moves")
    elif typ == "index_panel":
        rows = _series(list(INDEX_PROXY), by_ticker, lambda s: f"{INDEX_PROXY[s]}")
        focus = None
        title = "US index ETF proxies"
        subtitle = "ETF prices as proxies — not index levels"
    elif typ == "co_movers":
        focus = syms[0] if syms else None
        rows = _series(syms, by_ticker, lambda s: s)   # 포커스+생태계 종목 당일 %
        fq = by_ticker.get(focus or "")
        fpct = _pct(fq) if fq else None
        title = f"Moving with {focus} today" if focus else "Movers today"
        subtitle = (f"{focus} {fpct:+.2f}% · ecosystem % change today"
                    if fpct is not None else "Ecosystem % change today")
    else:
        return None
    if not rows:
        return None

    labels = [r[0] for r in rows]
    syms_o = [r[1] for r in rows]
    pcts = [r[2] for r in rows]
    colors = [UP if p >= 0 else DOWN for p in pcts]
    alphas = [1.0 if (focus is None or s == focus) else DIM_A for s in syms_o]

    fig = plt.figure(figsize=(W / DPI, H / DPI), dpi=DPI)
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0.16, 0.34, 0.70, 0.34])
    ax.set_facecolor(BG)

    y = range(len(labels))
    bars = ax.barh(list(y), pcts, color=colors, height=0.62, zorder=3)
    for b, a, s in zip(bars, alphas, syms_o):
        b.set_alpha(a)
        if focus and s == focus:
            b.set_edgecolor(ACCENT); b.set_linewidth(2.5)
    # 값 라벨
    span = max((abs(p) for p in pcts), default=1.0) or 1.0
    for yi, p in zip(y, pcts):
        ax.text(p + (span * 0.04 if p >= 0 else -span * 0.04), yi, f"{p:+.2f}%",
                va="center", ha="left" if p >= 0 else "right",
                color=FG, fontsize=20, fontweight="bold", zorder=4)

    ax.axvline(0, color=GRID, linewidth=1.5, zorder=2)
    ax.set_yticks(list(y)); ax.set_yticklabels(labels, color=FG, fontsize=22)
    ax.invert_yaxis()
    ax.set_xticks([])
    ax.set_xlim(-span * 1.35, span * 1.35)
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.tick_params(length=0)

    # 제목 길이에 따라 폰트 축소(가장자리 잘림 방지)
    t_fs = 58 if len(title) <= 12 else (46 if len(title) <= 20 else 40)
    fig.text(0.5, 0.80, title, ha="center", color=FG, fontsize=t_fs, fontweight="bold")
    fig.text(0.5, 0.745, subtitle, ha="center", color=SUB, fontsize=24)
    fig.text(0.5, 0.045, "Source: Finnhub · educational commentary, not investment advice",
             ha="center", color=SUB, fontsize=18)

    fig.savefig(path, facecolor=BG)
    plt.close(fig)
    return {"title": title, "subtitle": subtitle,
            "bars": [{"label": l, "symbol": s, "pct": round(p, 4),
                      "highlight": bool(focus and s == focus)}
                     for l, s, p in rows]}


def main() -> int:
    log("INFO", "=== STAGE ⑥ 차트 렌더 시작 ===", "stage06")
    script = read_json(SCRIPT_PATH, default=None)
    if not script:
        log("ERROR", f"입력 없음: {SCRIPT_PATH} (stage04 먼저 실행 필요)", "stage06")
        return 2
    data = read_json(DATA_PATH, default={}) or {}
    by_ticker = _by_ticker(data)
    corr_pairs = (data.get("correlations") or {}).get("pairs") or {}
    conn = rag_store.connect()
    series_map = _load_series(conn)
    conn.close()
    log("INFO", f"시계열 로드: {len(series_map)}종목 · 상관 포커스 {len(corr_pairs)}건", "stage06")
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)

    # 렌더할 고유 차트 = chart_plan(없으면 beats 에서 수집)
    cues = script.get("chart_plan") or []
    if not cues:
        seen, cues = set(), []
        for b in script.get("beats", []):
            c = b.get("chart_cue")
            if c and _chart_id(c) not in seen:
                seen.add(_chart_id(c)); cues.append(c)

    charts, missing = [], []
    for cue in cues:
        cid = _chart_id(cue)
        path = ASSETS_DIR / f"chart_{cid}.png"
        meta = _render(cue, by_ticker, series_map, corr_pairs, path)
        used_type = cue["type"]
        # 캡처/시계열 미확보 시 폴백(파이프라인 비차단)
        if meta is None and cue["type"] in ("price_line", "correlation", "article_shot"):
            syms = cue.get("symbols") or []
            fb = ({"type": "price_line", "symbols": syms[:1]} if cue["type"] == "article_shot"
                  else {"type": "single_quote", "symbols": syms[:1]})
            meta = _render(fb, by_ticker, series_map, corr_pairs, path)
            if meta is not None:
                used_type = f"{fb['type']}(fallback)"
                log("WARN", f"{cid}: {cue['type']} 미확보 → {fb['type']} 폴백", "stage06")
        if meta is None:
            missing.append(cid)
            log("WARN", f"차트 데이터 없음 → 건너뜀: {cid}", "stage06")
            continue
        charts.append({"id": cid, "type": used_type, "symbols": cue.get("symbols", []),
                       "file": str(path.relative_to(OUTPUT_DIR.parent)), **meta})
        log("INFO", f"렌더: {cid} → {path.name} [{used_type}]", "stage06")

    if not charts:
        log("ERROR", "렌더된 차트 0개 — 단계 실패", "stage06")
        return 3

    out = {
        "schema_version": "1.0", "pipeline_id": "shorts_maker", "machine": "mac",
        "stage": 6, "agent": "Editor", "generated_utc": utc_now(),
        "date": script.get("date"), "dimensions": [W, H], "theme": "dark_minimal",
        "charts": charts, "missing": missing,
    }
    write_json_atomic(OUT_JSON, out)
    log("INFO", f"=== STAGE ⑥ 완료: charts={len(charts)} missing={len(missing)} "
                f"→ output/assets/ ===", "stage06")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
