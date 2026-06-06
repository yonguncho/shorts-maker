"""thumbnail.py — 1080x1920 썸네일 생성 (Phase 4 P2.1).

레이아웃 5종 자동선택(catalyst.type 기반). ARM 우선 = LAYOUT_BIG_NUMBER.
Pexels 섹터 블러 배경 + 상단 hook 띠 + 거대 % + 마스코트 + 로고 + 워터마크.
safe-zone 상하 10% 텍스트 금지. 출력 outputs/{ticker}_{date}/thumbnail.png.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
import theme as T
import components as C
import mascot as Mascot
import assets as A

ROOT = Path(__file__).resolve().parent.parent
CW, CH = T.CANVAS
TOP_SAFE = int(CH * 0.10); BOT_SAFE = int(CH * 0.90)


def select_layout(trader: dict):
    """catalyst.type → 레이아웃 + 근거. 구현: BIG_NUMBER, CHART_HERO. (VS/ALERT는 후속→BIG_NUMBER 폴백)"""
    ctype = (trader.get("catalyst", {}).get("type") or "").lower()
    if ctype in ("earnings_beat", "guidance_raise"):
        return "LAYOUT_CHART_HERO", f"{ctype}(펀더멘털 발표) → 차트 히어로(라인+거대%)"
    if ctype == "competitor":
        return "LAYOUT_BIG_NUMBER", "경쟁(VS 후속) → BIG_NUMBER 폴백"
    return "LAYOUT_BIG_NUMBER", f"{ctype or 'default'} → 거대 % 임팩트"


def _hook_band(img, d, text):
    """상단 빨간 띠 + hook 텍스트(흰색, Anton). safe-zone 아래."""
    band_y = TOP_SAFE + 20
    f = T.get_font("display", 76)
    lines = C._wrap(d, text, "display", 76, CW - 120, max_lines=2)
    bh = 40 + len(lines) * int(76 * 1.12) + 30
    d.rectangle((0, band_y, CW, band_y + bh), fill=T.c("accent_bear"))
    yy = band_y + 36
    for ln in lines:
        d.text((CW // 2, yy), ln, font=f, fill=(255, 255, 255), anchor="ma")
        yy += int(76 * 1.12)
    return band_y + bh


def _urgency_badge(img, d, pct, y):
    """절대값 5% 이상 이동 시 DROPS/SURGES 배지 (중앙 정렬). 반환: 배지 하단 y."""
    if abs(pct) < 5.0:
        return y
    label = f"{'DROPS' if pct < 0 else 'SURGES'} {abs(pct):.1f}%"
    col = "accent_bear" if pct < 0 else "accent_bull"
    f = T.get_font("mono_bold", T.SIZES["md"])
    tw = d.textlength(label, font=f)
    pad_x, pad_y = 32, 16
    bw, bh = int(tw + pad_x * 2), int(T.SIZES["md"] + pad_y * 2)
    bx = (CW - bw) // 2
    d.rounded_rectangle((bx, y, bx + bw, y + bh), radius=T.RADIUS["pill"],
                         fill=T.c(col), outline=(0, 0, 0, 180), width=2)
    d.text((CW // 2, y + bh // 2), label, font=f, fill=(255, 255, 255), anchor="mm")
    return y + bh + 12


def _analyst_target_strip(img, d, price, y):
    """애널리스트 평균 목표가 vs 현재가 스트립. 데이터 없으면 스킵."""
    analyst = price.get("analyst", {})
    target = (analyst.get("price_targets") or {}).get("mean")
    if not target:
        return
    current = price.get("last_close", 0)
    diff_pct = (current / target - 1) * 100
    arrow = "▲" if diff_pct > 0 else "▼"
    col = T.c("accent_bear") if diff_pct > 0 else T.c("accent_bull")
    text = f"Analyst avg target  ${target:.0f}  {arrow} {abs(diff_pct):.0f}% {'above' if diff_pct > 0 else 'below'} consensus"
    d.text((CW // 2, y), text, font=T.get_font("mono", T.SIZES["sm"]), fill=col, anchor="mm")


def _big_number(trader, price, hook):
    img = Image.new("RGBA", T.CANVAS, (0, 0, 0, 0))
    sector = A.sector_for_ticker(trader.get("ticker", "ARM"))
    base = T.make_bg().convert("RGBA")
    if T.ACTIVE_THEME != "brightnews":  # FIX1: Bright News는 Pexels 블러 스킵
        base = C.scene_background(base, sector, variant=1, blur=30, alpha=0.25)
    img.alpha_composite(base)
    d = ImageDraw.Draw(img)
    pct = price.get("pct_change", 0.0)
    col = T.signed_color(pct)

    # hook_line 직접 사용 (없으면 방향 기반 폴백)
    band_text = hook.get("hook_line") or ("Too hot to chase?" if pct < 0 else "Just getting started?")
    band_bottom = _hook_band(img, d, band_text)

    # DROPS/SURGES 긴급 배지 (±5% 이상)
    badge_y = band_bottom + 20
    badge_y = _urgency_badge(img, d, pct, badge_y)

    # 로고 (배지 오른쪽 or 기존 위치)
    logo = A.download_logo(trader.get("ticker", "ARM"))
    if logo and Path(logo).exists():
        try:
            lg = Image.open(logo).convert("RGBA")
            lw = 110; lg = lg.resize((lw, int(lg.height * lw / lg.width)))
            chip = Image.new("RGBA", (lw + 24, lg.height + 24), T.hex2rgb(T.COLORS["bg_chip"]) + (235,))
            chip.alpha_composite(lg, (12, 12))
            img.alpha_composite(chip, (T.SAFE_ZONE["side"], band_bottom + 20))
        except Exception as e:
            print("  ⚠ 로고 합성 실패:", e)

    # 거대 % (중앙)
    sign = "+" if pct >= 0 else ""
    C.huge_number(img, f"{sign}{pct:.2f}%", color=col, center=(CW // 2, 980), size=320,
                  sublabel="in one day",
                  sublabel2=f"vs SPX {price.get('spx_pct_change', 0):+.2f}%")

    # 애널리스트 목표가 비교 스트립
    _analyst_target_strip(img, d, price, 1200)

    # 마스코트 (38% — 더 큰 존재감)
    expr_key = "shocked" if abs(pct) >= 5 else ("warning" if pct < 0 else "cheer")
    try:
        ep = Mascot.ensure()
        m = Image.open(ep.get(expr_key, ep.get("thinking"))).convert("RGBA")
        W = int(CW * 0.38); m = m.resize((W, int(m.height * W / m.width)))
        img.alpha_composite(m, (CW - m.width - 12, BOT_SAFE - m.height))
    except Exception as e:
        print("  ⚠ 썸네일 마스코트 실패:", e)

    # 좌하단 워터마크
    d.text((T.SAFE_ZONE["side"], BOT_SAFE - 6), "TRADER CHO",
           font=T.get_font("display", T.SIZES["md"]), fill=T.c("accent_data"), anchor="lb")
    d.text((CW // 2, CH - 44), "Not financial advice · Educational purposes",
           font=T.get_font("body", T.SIZES["xs"]), fill=T.c("text_muted"), anchor="mm")
    return img.convert("RGB")


def _logo_chip(img, ticker, xy):
    logo = A.download_logo(ticker)
    if not (logo and Path(logo).exists()):
        return
    try:
        lg = Image.open(logo).convert("RGBA"); lw = 110
        lg = lg.resize((lw, int(lg.height * lw / lg.width)))
        chip = Image.new("RGBA", (lw + 24, lg.height + 24), T.hex2rgb(T.COLORS["bg_chip"]) + (235,))
        chip.alpha_composite(lg, (12, 12)); img.alpha_composite(chip, xy)
    except Exception as e:
        print("  ⚠ 로고 합성 실패:", e)


def _chart_hero(trader, price, hook):
    """LAYOUT_CHART_HERO: 상단 hook 띠 + 3M 라인차트 + 거대 % + 방향 화살표."""
    img = T.make_bg().convert("RGBA")
    sector = A.sector_for_ticker(trader.get("ticker", ""))
    if T.ACTIVE_THEME != "brightnews":  # FIX1
        img = C.scene_background(img, sector, variant=4, blur=30, alpha=0.22)
    d = ImageDraw.Draw(img)
    pct = price.get("pct_change", 0.0); col = T.signed_color(pct)
    bb = _hook_band(img, d, hook.get("hook_line") or ("The print is in." if pct >= 0 else "Sell the news?"))
    series = price.get("series_3m") or [price.get("last_close", 100)] * 2
    C.chart_panel(img, series, "3M", "yfinance", (T.SAFE_ZONE["side"], bb + 60),
                  size=(CW - T.SAFE_ZONE["side"] * 2, 560))
    sign = "+" if pct >= 0 else ""
    arrow = "▲" if pct >= 0 else "▼"
    C.huge_number(img, f"{arrow}{sign}{pct:.2f}%", color=col, center=(CW // 2, bb + 60 + 560 + 200),
                  size=240, sublabel=f"vs SPX {price.get('spx_pct_change', 0):+.2f}%")
    try:
        ep = Mascot.ensure(); m = Image.open(ep["cheer"]).convert("RGBA")
        W = int(CW * 0.26); m = m.resize((W, int(m.height * W / m.width)))
        img.alpha_composite(m, (CW - m.width - 16, BOT_SAFE - m.height))
    except Exception:
        pass
    _logo_chip(img, trader.get("ticker", ""), (T.SAFE_ZONE["side"], bb + 16))
    d.text((T.SAFE_ZONE["side"], BOT_SAFE - 6), "TRADER CHO",
           font=T.get_font("display", T.SIZES["md"]), fill=T.c("accent_data"), anchor="lb")
    d.text((CW // 2, CH - 44), "Not financial advice · Educational purposes",
           font=T.get_font("body", T.SIZES["xs"]), fill=T.c("text_muted"), anchor="mm")
    return img.convert("RGB")


def generate(ticker="ARM", out_dir=None, theme="terminal"):
    T.apply_theme(theme)
    out_dir = Path(out_dir) if out_dir else sorted((ROOT / "outputs").glob(f"{ticker.upper()}_*"))[-1]
    price = json.loads((out_dir / "price.json").read_text())
    trader = json.loads((out_dir / "trader_lens.json").read_text())
    hook = json.loads((out_dir / "hook.json").read_text())
    layout, reason = select_layout(trader)
    img = _chart_hero(trader, price, hook) if layout == "LAYOUT_CHART_HERO" else _big_number(trader, price, hook)
    suffix = "" if theme == "terminal" else f"_{theme}"
    out = out_dir / f"thumbnail{suffix}.png"
    img.save(out)
    print(f"thumbnail: {out} | layout={layout} ({reason}) | theme={theme}")
    return out, layout, reason


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("ticker", nargs="?", default="ARM")
    ap.add_argument("--theme", default="terminal", choices=["terminal", "brightnews"])
    a = ap.parse_args()
    generate(a.ticker, theme=a.theme)
