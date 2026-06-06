"""components.py — UI 컴포넌트 (Terminal Pro).

컴포넌트: data_chip / huge_number / header / news_card / durability_badge /
          bar_compare / chart_panel / risk_alert.
모두 theme 토큰만 사용, safe-zone 자동. 외곽선은 자막·거대숫자에만(L1.2). 이모지 금지(L1.1).
아이콘은 시스템 cairo 부재로 SVG 래스터 대신 PIL 단색 글리프로 드로잉.
"""
from __future__ import annotations
import io
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent))
import theme as T

STOCK_DIR = Path(__file__).resolve().parent.parent / "assets" / "stock"
_STOCK_CACHE = {}   # (sector,variant,blur,alpha) → 처리된 RGBA (재사용)


def scene_background(img, sector, variant=0, blur=30, alpha=0.25, darken=0.45):
    """섹터 스톡 이미지를 blur + alpha로 bg 위에 합성(P1.1). 단색 블러라 L1.4(그라데이션) 위반 아님.
    img: RGBA(make_bg 결과). 캐싱으로 프레임당 재처리 회피."""
    pool = sorted((STOCK_DIR / sector).glob("*.jpg"))
    if not pool:
        return img
    key = (sector, variant % len(pool), blur, alpha, darken)
    layer = _STOCK_CACHE.get(key)
    if layer is None:
        p = pool[variant % len(pool)]
        bg = Image.open(p).convert("RGB")
        cw, ch = T.CANVAS
        # cover-fit(중앙 크롭)
        s = max(cw / bg.width, ch / bg.height)
        bg = bg.resize((int(bg.width * s) + 1, int(bg.height * s) + 1))
        bg = bg.crop(((bg.width - cw) // 2, (bg.height - ch) // 2,
                      (bg.width - cw) // 2 + cw, (bg.height - ch) // 2 + ch))
        bg = bg.filter(ImageFilter.GaussianBlur(blur))
        # 다크닝(텍스트 대비 확보) 후 알파
        bg = Image.blend(bg, Image.new("RGB", (cw, ch), T.hex2rgb(T.COLORS["bg_primary"])), darken)
        layer = bg.convert("RGBA")
        layer.putalpha(int(alpha * 255))
        _STOCK_CACHE[key] = layer
    base = img if img.mode == "RGBA" else img.convert("RGBA")
    base.alpha_composite(layer)
    return base


# ── 유틸 ─────────────────────────────────────────────
def _wrap(draw, text, role, size, maxw, max_lines=99):
    f = T.get_font(role, size)
    out, cur = [], ""
    for w in (text or "").split():
        t = (cur + " " + w).strip()
        if draw.textlength(t, font=f) <= maxw:
            cur = t
        else:
            if cur:
                out.append(cur)
            cur = w
        if len(out) >= max_lines:
            break
    if cur and len(out) < max_lines:
        out.append(cur)
    return out


def _alert_glyph(draw, box, color):
    """경고 삼각형(라운드 모서리 + 느낌표) — Lucide 대체 단색 글리프."""
    x0, y0, x1, y1 = box
    w = x1 - x0
    col = T.c(color)
    lw = max(4, w // 12)
    # 삼각형
    apex = (x0 + w / 2, y0)
    left = (x0, y1)
    right = (x1, y1)
    draw.line([apex, left, right, apex], fill=col, width=lw, joint="curve")
    # 느낌표
    cx = x0 + w / 2
    draw.line([(cx, y0 + w * 0.32), (cx, y0 + w * 0.66)], fill=col, width=lw)
    r = lw * 0.7
    draw.ellipse((cx - r, y1 - w * 0.18 - r, cx + r, y1 - w * 0.18 + r), fill=col)


# ── data_chip ────────────────────────────────────────
def data_chip(draw, label, value, pos, *, value_color="accent_data"):
    x, y = pos
    pad_x, pad_y, gap = T.SPACE["md"], T.SPACE["sm"], T.SPACE["sm"]
    lab_f = T.get_font("mono", T.SIZES["xs"])
    val_f = T.get_font("mono_bold", T.SIZES["sm"])
    lab_w = draw.textlength(label, font=lab_f)
    val_w = draw.textlength(value, font=val_f)
    h = T.SIZES["sm"] + pad_y * 2 + 8
    w = pad_x * 2 + lab_w + gap + val_w
    draw.rounded_rectangle((x, y, x + w, y + h), radius=T.RADIUS["pill"],
                           fill=T.c("bg_chip"), outline=T.c("border_subtle"), width=2)
    cy = y + h / 2
    draw.text((x + pad_x, cy), label, font=lab_f, fill=T.c("text_secondary"), anchor="lm")
    draw.text((x + pad_x + lab_w + gap, cy), value, font=val_f, fill=T.c(value_color), anchor="lm")
    return x + w, h


def data_chip_row(draw, chips, pos):
    x, y = pos
    for ch in chips:
        color = ch[2] if len(ch) > 2 else "accent_data"
        x, _ = data_chip(draw, ch[0], ch[1], (x, y), value_color=color)
        x += T.SPACE["md"]
    return x


# ── huge_number ──────────────────────────────────────
def huge_number(img, value_str, *, color="accent_bull", center=None, size=None,
                sublabel=None, sublabel2=None):
    d = ImageDraw.Draw(img)
    size = size or T.SIZES["huge"]
    cx, cy = center or (T.CANVAS[0] // 2, T.CANVAS[1] // 2)
    maxw = T.CANVAS[0] - T.SAFE_ZONE["side"] * 2
    f = T.get_font("display", size)
    while d.textlength(value_str, font=f) > maxw and size > 80:
        size -= 8
        f = T.get_font("display", size)
    d.text((cx, cy), value_str, font=f, fill=T.c(color), anchor="mm",
           stroke_width=T.TEXT_STROKE["width"], stroke_fill=T.hex2rgb(T.TEXT_STROKE["color"]))
    yy = cy + size * 0.5 + T.SPACE["lg"]
    if sublabel:   # preview_v1 피드백: sublabel 옵션
        d.text((cx, yy), sublabel, font=T.get_font("body", T.SIZES["lg"]),
               fill=T.c("text_secondary"), anchor="mm")
        yy += T.SIZES["lg"]
    if sublabel2:
        d.text((cx, yy), sublabel2, font=T.get_font("mono", T.SIZES["md"]),
               fill=T.c("text_muted"), anchor="mm")


# ── header ───────────────────────────────────────────
def header(img, date_str, time_et, progress_idx, total):
    d = ImageDraw.Draw(img)
    side = T.SAFE_ZONE["side"]
    h = T.SAFE_ZONE["header_h"]
    # 마스코트 아바타 placeholder (64x64 라운드)
    av = 64
    ay = (h - av) // 2
    d.rounded_rectangle((side, ay, side + av, ay + av), radius=T.RADIUS["md"],
                        fill=T.c("bg_chip"), outline=T.c("border_subtle"), width=2)
    d.text((side + av / 2, ay + av / 2), "TC", font=T.get_font("display", 30),
           fill=T.c("accent_data"), anchor="mm")
    # 채널명 + 시점
    tx = side + av + T.SPACE["md"]
    d.text((tx, h / 2 - 22), "TRADER CHO", font=T.get_font("heading", T.SIZES["lg"]),
           fill=T.c("text_primary"), anchor="lm")
    d.text((tx, h / 2 + 26), f"As of {date_str}, {time_et} ET",
           font=T.get_font("mono", T.SIZES["sm"]), fill=T.c("text_secondary"), anchor="lm")
    # 진행 도트(우측 상단)
    dot, gap = 12, 14
    total_w = total * dot + (total - 1) * gap
    dx = T.CANVAS[0] - side - total_w
    dy = 34
    for i in range(total):
        col = T.c("accent_data") if i < progress_idx else T.c("border_subtle")
        d.ellipse((dx + i * (dot + gap), dy, dx + i * (dot + gap) + dot, dy + dot), fill=col)
    # 하단 보더
    d.line((0, h, T.CANVAS[0], h), fill=T.c("border_subtle"), width=1)


# ── news_card ────────────────────────────────────────
def news_card(img, headline, source, date_time, width, position, max_lines=4):
    d = ImageDraw.Draw(img)
    x, y = position
    pad = T.SPACE["lg"]
    hf = T.get_font("heading", T.SIZES["lg"])
    all_lines = _wrap(d, headline, "heading", T.SIZES["lg"], width - pad * 2, max_lines=99)
    lines = all_lines[:max_lines]
    if len(all_lines) > max_lines and lines:   # 마지막 줄 ellipsis(단어 중간 잘림 방지)
        last = lines[-1]
        while last and d.textlength(last + " …", font=hf) > width - pad * 2:
            last = last.rsplit(" ", 1)[0] if " " in last else last[:-1]
        lines[-1] = (last + " …").strip()
    lh = int(T.SIZES["lg"] * 1.25)
    head_h = len(lines) * lh
    h = pad + head_h + T.SPACE["md"] + 1 + T.SPACE["md"] + T.SIZES["sm"] + pad
    d.rounded_rectangle((x, y, x + width, y + h), radius=T.RADIUS["md"],
                        fill=T.c("bg_secondary"), outline=T.c("border_subtle"), width=1)
    cy = y + pad
    for ln in lines:
        d.text((x + pad, cy), ln, font=T.get_font("heading", T.SIZES["lg"]),
               fill=T.c("text_primary"), anchor="la")
        cy += lh
    cy += T.SPACE["md"]
    d.line((x + pad, cy, x + width - pad, cy), fill=T.c("border_subtle"), width=1)
    cy += T.SPACE["md"]
    d.text((x + pad, cy), f"{source}  ·  {date_time}", font=T.get_font("mono", T.SIZES["sm"]),
           fill=T.c("text_secondary"), anchor="la")
    return h


# ── durability_badge ────────────────────────────────
def durability_badge(img, kind, reason, position, width=520):
    d = ImageDraw.Draw(img)
    x, y = position
    bg = "accent_bull" if kind.upper() == "DURABLE" else "accent_alert"
    pad = T.SPACE["lg"]
    h = pad + T.SIZES["xl"] + T.SPACE["md"] + T.SIZES["sm"] + pad
    d.rounded_rectangle((x, y, x + width, y + h), radius=T.RADIUS["lg"], fill=T.c(bg))
    cx = x + width / 2
    d.text((cx, y + pad + T.SIZES["xl"] / 2), kind.upper(),
           font=T.get_font("display", T.SIZES["xl"]), fill=T.c("bg_primary"), anchor="mm")
    # reason: 작은 dot + 텍스트(이모지 대신 드로잉)
    ry = y + pad + T.SIZES["xl"] + T.SPACE["md"] + T.SIZES["sm"] / 2
    rtext = reason
    rf = T.get_font("mono", T.SIZES["sm"])
    rw = d.textlength(rtext, font=rf)
    dotr = 6
    start = cx - (rw + 18) / 2
    d.ellipse((start, ry - dotr, start + dotr * 2, ry + dotr), fill=T.c("bg_primary"))
    d.text((start + 18, ry), rtext, font=rf, fill=T.c("bg_primary"), anchor="lm")
    return h


# ── bar_compare ──────────────────────────────────────
def bar_compare(img, items, highlight_idx, position, width=960, caption="Today's change %",
                row_h=None, gap=None):
    d = ImageDraw.Draw(img)
    x, y = position
    d.text((x + width, y), caption, font=T.get_font("body", T.SIZES["sm"]),
           fill=T.c("text_secondary"), anchor="ra")
    y += T.SIZES["sm"] + T.SPACE["md"]
    row_h = row_h if row_h is not None else 46
    gap = gap if gap is not None else T.SPACE["sm"]
    lab_w = 160
    bar_x = x + lab_w + T.SPACE["md"]
    bar_max_w = width - lab_w - T.SPACE["md"] - 150
    mx = max(abs(it["value"]) for it in items) or 1.0
    for i, it in enumerate(items):
        ry = y + i * (row_h + gap)
        d.text((x, ry + row_h / 2), it["label"], font=T.get_font("mono", T.SIZES["md"]),
               fill=T.c("text_primary"), anchor="lm")
        d.rounded_rectangle((bar_x, ry, bar_x + bar_max_w, ry + row_h), radius=T.RADIUS["sm"],
                            fill=T.c("bg_chip"))
        bw = max(8, int(bar_max_w * abs(it["value"]) / mx))
        col = "accent_bull" if it.get("is_positive", it["value"] >= 0) else "accent_bear"
        d.rounded_rectangle((bar_x, ry, bar_x + bw, ry + row_h), radius=T.RADIUS["sm"], fill=T.c(col))
        if i == highlight_idx:
            d.rounded_rectangle((bar_x - 3, ry - 3, bar_x + bar_max_w + 3, ry + row_h + 3),
                                radius=T.RADIUS["sm"], outline=T.c("accent_data"), width=3)
        d.text((bar_x + bar_max_w + T.SPACE["md"], ry + row_h / 2),
               f"{it['value']:+.2f}%", font=T.get_font("mono_bold", T.SIZES["md"]),
               fill=T.c(col), anchor="lm")
    return (T.SIZES["sm"] + T.SPACE["md"]) + len(items) * (row_h + gap)


# ── chart_panel ──────────────────────────────────────
def chart_panel(img, price_series, period_label, source_label, position, size=(960, 320),
                highlight_last=True):
    # P1.3: 차트/라벨이 좌측 가장자리에 붙지 않게 시작 x를 safe-zone 으로 강제(자동).
    position = (max(position[0], T.SAFE_ZONE["side"]), position[1])
    w, h = size
    up = price_series[-1] >= price_series[0]
    col = COLORS_line = T.COLORS["accent_bull"] if up else T.COLORS["accent_bear"]
    fig = plt.figure(figsize=(w / 100, h / 100), dpi=100)
    fig.patch.set_alpha(0)
    ax = fig.add_axes([0.10, 0.16, 0.86, 0.80])
    ax.set_facecolor("none")
    xs = range(len(price_series))
    ax.plot(xs, price_series, color=col, linewidth=3, zorder=3)
    ax.fill_between(xs, price_series, min(price_series), color=col, alpha=0.15, zorder=2)
    ax.grid(axis="y", color=T.COLORS["border_subtle"], linewidth=0.5)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.tick_params(colors=T.COLORS["text_secondary"], labelsize=11, length=0)
    ax.set_xticks([])
    if highlight_last:
        ax.scatter([xs[-1]], [price_series[-1]], color=T.COLORS["accent_data"], s=70, zorder=4)
    buf = io.BytesIO(); fig.savefig(buf, format="png", transparent=True); plt.close(fig); buf.seek(0)
    panel = Image.open(buf).convert("RGBA")
    img.alpha_composite(panel, position) if img.mode == "RGBA" else img.paste(panel, position, panel)
    d = ImageDraw.Draw(img)
    px, py = position
    # 마지막 가격 라벨(좌상단, 배경칩으로 라인과 분리)
    plabel = f"${price_series[-1]:,.2f}"
    pf = T.get_font("mono_bold", T.SIZES["lg"])
    pw = d.textlength(plabel, font=pf)
    d.rounded_rectangle((px + 6, py + 6, px + 6 + pw + 24, py + 6 + T.SIZES["lg"] + 14),
                        radius=T.RADIUS["sm"], fill=T.c("bg_chip"))
    d.text((px + 18, py + 13), plabel, font=pf, fill=T.c("accent_data"), anchor="la")
    d.text((px + 8, py + h - 8), f"Period: {period_label}  ·  Source: {source_label}",
           font=T.get_font("mono", T.SIZES["xs"]), fill=T.c("text_muted"), anchor="lb")


# ── speech_bubble (Phase 6 핵심) ─────────────────────
def speech_bubble(img, text, position, mascot_side="left", max_width=640, max_lines=3,
                  alpha=230, accent="accent_data"):
    """마스코트 말풍선: 둥근 사각형 + 향 꼬리. bg_secondary 90% + accent 보더 3px.
    position=풍선 좌상단. mascot_side: 꼬리가 향하는 쪽(마스코트 위치). 반환 (w,h)."""
    pad = T.SPACE["md"]
    tmp = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    # autofit: 전체 텍스트가 max_lines 안에 '잘리지 않게' 폰트 자동 축소(말풍선 잘림 0)
    nwords = len((text or "").split())
    size = T.SIZES["lg"]
    for sz in range(T.SIZES["lg"], 39, -4):
        ll = _wrap(tmp, text, "heading", sz, max_width - pad * 2, max_lines=max_lines)
        if sum(len(x.split()) for x in ll) >= nwords:
            size = sz; lines = ll; break
    else:
        size = 40; lines = _wrap(tmp, text, "heading", 40, max_width - pad * 2, max_lines=max_lines)
    f = T.get_font("heading", size)
    lh = int(size * 1.18)
    tw = max((tmp.textlength(ln, font=f) for ln in lines), default=10)
    bw = int(tw + pad * 2); bh = int(len(lines) * lh + pad * 2)
    tail = 34
    layer = Image.new("RGBA", (bw + tail * 2, bh + tail), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    bx = tail   # 풍선 본체 좌측(꼬리 공간 확보)
    fill = T.hex2rgb(T.COLORS["bg_secondary"]) + (alpha,)
    ld.rounded_rectangle((bx, 0, bx + bw, bh), radius=T.RADIUS["lg"], fill=fill,
                         outline=T.c(accent), width=3)
    # 꼬리(마스코트 쪽 하단 모서리)
    ty = bh - 18
    if mascot_side == "left":
        ld.polygon([(bx + 26, ty), (bx + 26 + 36, ty), (bx - 6, ty + tail)], fill=fill)
        ld.line([(bx + 26, ty), (bx - 6, ty + tail)], fill=T.c(accent), width=3)
        ld.line([(bx - 6, ty + tail), (bx + 26 + 36, ty)], fill=T.c(accent), width=3)
    else:
        rx = bx + bw
        ld.polygon([(rx - 26, ty), (rx - 26 - 36, ty), (rx + 6, ty + tail)], fill=fill)
        ld.line([(rx - 26, ty), (rx + 6, ty + tail)], fill=T.c(accent), width=3)
        ld.line([(rx + 6, ty + tail), (rx - 26 - 36, ty)], fill=T.c(accent), width=3)
    cy = pad
    for ln in lines:
        ld.text((bx + pad, cy), ln, font=f, fill=T.c("text_primary"), anchor="la")
        cy += lh
    base = img if img.mode == "RGBA" else img.convert("RGBA")
    base.alpha_composite(layer, (int(position[0] - tail), int(position[1])))
    return bw, bh


# ── sources_card (B.5) ───────────────────────────────
def sources_card(img, lines, position, width=900, title="SOURCES"):
    """출처 카드(신뢰 신호). lines: [(label, value), ...]. mono. 반환 높이."""
    d = ImageDraw.Draw(img)
    x, y = position
    pad = T.SPACE["lg"]
    th = T.SIZES["md"]; lh = int(T.SIZES["sm"] * 1.55)
    h = pad + th + T.SPACE["md"] + len(lines) * lh + pad
    d.rounded_rectangle((x, y, x + width, y + h), radius=T.RADIUS["md"],
                        fill=T.c("bg_secondary"), outline=T.c("border_subtle"), width=1)
    d.rounded_rectangle((x, y, x + 6, y + h), radius=0, fill=T.c("accent_data"))
    d.text((x + pad, y + pad), title, font=T.get_font("display", th),
           fill=T.c("accent_data"), anchor="la")
    cy = y + pad + th + T.SPACE["md"]
    for lab, val in lines:
        d.text((x + pad, cy), f"{lab}", font=T.get_font("mono_bold", T.SIZES["sm"]),
               fill=T.c("text_secondary"), anchor="la")
        d.text((x + pad + 200, cy), val, font=T.get_font("mono", T.SIZES["sm"]),
               fill=T.c("text_primary"), anchor="la")
        cy += lh
    return h


# ── chart_thumbnail (STEP2: 데이터 존재 신호) ─────────
def chart_thumbnail(img, series, position, size=(220, 110)):
    """미니 라인차트(라벨 없음). 차트가 주인공 아닌 씬에 '데이터 있음' 신호. 등락색."""
    if not series or len(series) < 2:
        return
    w, h = size; x, y = position
    lo, hi = min(series), max(series)
    rng = (hi - lo) or 1.0
    col = T.c("accent_bull") if series[-1] >= series[0] else T.c("accent_bear")
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    ld.rounded_rectangle((0, 0, w - 1, h - 1), radius=T.RADIUS["sm"],
                         fill=T.hex2rgb(T.COLORS["bg_chip"]) + (180,), outline=T.c("border_subtle"), width=1)
    pad = 8
    pts = []
    n = len(series)
    for i, v in enumerate(series):
        px = pad + (w - 2 * pad) * i / (n - 1)
        py = (h - pad) - (h - 2 * pad) * (v - lo) / rng
        pts.append((px, py))
    ld.line(pts, fill=col, width=3, joint="curve")
    ld.ellipse((pts[-1][0] - 4, pts[-1][1] - 4, pts[-1][0] + 4, pts[-1][1] + 4), fill=T.c("accent_data"))
    base = img if img.mode == "RGBA" else img.convert("RGBA")
    base.alpha_composite(layer, (int(x), int(y)))


# ── logo_chip (B.1, graceful) ────────────────────────
_LOGO_DIR = Path(__file__).resolve().parent.parent / "assets" / "logos"


def logo_chip(img, ticker, center, target_w=160, chip=True):
    """회사 로고를 칩에 담아 합성(없으면 무시=graceful). 반환 True/False."""
    p = _LOGO_DIR / f"{(ticker or '').upper()}.png"
    if not p.exists() or p.stat().st_size < 800:
        return False
    try:
        lg = Image.open(p).convert("RGBA")
        s = target_w / lg.width
        lg = lg.resize((target_w, max(1, int(lg.height * s))))
        if chip:
            pad = 14
            box = Image.new("RGBA", (lg.width + pad * 2, lg.height + pad * 2),
                            T.hex2rgb(T.COLORS["bg_chip"]) + (235,))
            box.alpha_composite(lg, (pad, pad)); lg = box
        base = img if img.mode == "RGBA" else img.convert("RGBA")
        base.alpha_composite(lg, (int(center[0] - lg.width / 2), int(center[1] - lg.height / 2)))
        return True
    except Exception:
        return False


# ── risk_alert ───────────────────────────────────────
def risk_alert(img, message, position, width=960, severity="warn"):
    d = ImageDraw.Draw(img)
    x, y = position
    pad = T.SPACE["lg"]
    lines = _wrap(d, message, "body", T.SIZES["md"], width - 200, max_lines=4)
    lh = int(T.SIZES["md"] * 1.25)
    h = pad * 2 + max(72, len(lines) * lh + T.SIZES["lg"])
    d.rounded_rectangle((x, y, x + width, y + h), radius=T.RADIUS["md"], fill=T.c("bg_secondary"))
    d.rounded_rectangle((x, y, x + 6, y + h), radius=0, fill=T.c("accent_alert"))  # 좌측 4px+
    # 아이콘
    isz = 72
    _alert_glyph(d, (x + pad, y + (h - isz) / 2, x + pad + isz, y + (h - isz) / 2 + isz), "accent_alert")
    tx = x + pad + isz + T.SPACE["lg"]
    d.text((tx, y + pad), "RISK", font=T.get_font("display", T.SIZES["lg"]),
           fill=T.c("accent_alert"), anchor="la")
    cy = y + pad + T.SIZES["lg"] + 4
    for ln in lines:
        d.text((tx, cy), ln, font=T.get_font("body", T.SIZES["md"]),
               fill=T.c("text_primary"), anchor="la")
        cy += lh
    return h


# ── photo_card (A2.4: 씬1·3·11 회사 사진 보조 카드) ─────
MANIFEST_PATH = Path(__file__).resolve().parent / "assets_manifest.json"


def _photo_license(image_path) -> str | None:
    """assets_manifest.json에서 이미지 라이선스 조회. 없으면 None."""
    try:
        import json
        if not MANIFEST_PATH.exists():
            return None
        abs_path = str(Path(image_path).resolve())
        m = json.loads(MANIFEST_PATH.read_text())
        for entry in m:
            # manifest 경로도 절대경로로 정규화 후 비교
            entry_path = str(Path(entry.get("file", "")).resolve())
            if entry_path == abs_path:
                return entry.get("license") or None
    except Exception:
        pass
    return None


def photo_card(img, image_path, center, width=220, height=140,
               label: str | None = None, require_license: bool = True) -> bool:
    """회사 사진을 둥근 카드로 합성. 사진 없거나 라이선스 없으면 graceful skip.

    L0.1: 인물 사진은 company_photo_fetch가 차단 — 여기서 재검사 않음.
    L5.2: require_license=True 시 manifest에 라이선스 없으면 ValueError.
    반환: True=그림, False=skip.
    """
    if not image_path:
        return False
    p = Path(image_path)
    if not p.exists() or p.stat().st_size < 5000:
        return False

    if require_license:
        lic = _photo_license(str(p))
        if not lic:
            raise ValueError(f"photo_card: no license in manifest for {p.name} (L5.2)")

    try:
        ph = Image.open(p).convert("RGBA")
        # 비율 유지 리사이즈 (width 기준)
        r = width / ph.width
        new_h = max(1, int(ph.height * r))
        ph = ph.resize((width, new_h), Image.LANCZOS)
        # height 초과 시 center-crop
        if new_h > height:
            top = (new_h - height) // 2
            ph = ph.crop((0, top, width, top + height))
        elif new_h < height:
            height = new_h  # 실제 높이로 조정

        card_w, card_h = ph.size

        # 그림자 레이어 (offset 3px, 반투명 어두운 rect)
        shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
        sx = int(center[0] - card_w // 2) + 3
        sy = int(center[1] - card_h // 2) + 3
        ImageDraw.Draw(shadow).rounded_rectangle(
            (sx, sy, sx + card_w, sy + card_h),
            radius=T.RADIUS["sm"],
            fill=(0, 0, 0, 80),
        )
        base = img if img.mode == "RGBA" else img.convert("RGBA")
        base.alpha_composite(shadow)

        # 이미지 + 흰 보더 3px 마스크
        card = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 0))
        mask = Image.new("L", (card_w, card_h), 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            (0, 0, card_w - 1, card_h - 1), radius=T.RADIUS["sm"], fill=255
        )
        card.paste(ph, mask=mask)

        # 흰 보더 3px (마스크 위에 outline)
        border_layer = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 0))
        ImageDraw.Draw(border_layer).rounded_rectangle(
            (0, 0, card_w - 1, card_h - 1),
            radius=T.RADIUS["sm"],
            fill=None,
            outline=(255, 255, 255, 230),
            width=3,
        )
        card.alpha_composite(border_layer)

        cx = int(center[0] - card_w // 2)
        cy = int(center[1] - card_h // 2)
        base.alpha_composite(card, (cx, cy))

        # 캡션 (있으면, mono xs, text_muted)
        if label:
            d = ImageDraw.Draw(base)
            d.text((cx + card_w // 2, cy + card_h + 6), label,
                   font=T.get_font("mono", T.SIZES["xs"]),
                   fill=T.c("text_muted"), anchor="mt")

        return True
    except ValueError:
        raise
    except Exception:
        return False   # graceful skip — 렌더 중단 없음


# ── 미리보기 ─────────────────────────────────────────
def _disclaimer(d):
    d.text((T.CANVAS[0] // 2, T.CANVAS[1] - 50), "Not financial advice · Educational purposes",
           font=T.get_font("body", T.SIZES["xs"]), fill=T.c("text_muted"), anchor="mm")


def preview_v1(out="docs/preview_v1.png"):
    ROOT = Path(__file__).resolve().parent.parent
    img = T.make_bg(); d = ImageDraw.Draw(img); side = T.SAFE_ZONE["side"]
    d.text((side, T.SAFE_ZONE["top"] - 40), "As of Jun 1, 2026 · 4:00 PM ET",
           font=T.get_font("mono", T.SIZES["xs"]), fill=T.c("text_muted"), anchor="lm")
    d.text((side, T.SAFE_ZONE["top"] + 30), "ARM", font=T.get_font("display", 96),
           fill=T.c("accent_data"), anchor="lm")
    data_chip_row(d, [("RSI", "82.5", "accent_alert"), ("VOL", "1.66× avg", "accent_data"),
                      ("52W", "HIGH", "accent_bull")], (side, T.SAFE_ZONE["top"] + 180))
    huge_number(img, "+15.73%", color="accent_bull", center=(T.CANVAS[0] // 2, 980),
                sublabel="in one day", sublabel2="vs SPX +0.3%")
    _disclaimer(d)
    p = ROOT / out; p.parent.mkdir(parents=True, exist_ok=True); img.save(p); print("saved", p); return p


def preview_v2(out="docs/preview_v2.png"):
    """씬3+5+10 모자이크 — 6개 컴포넌트 한 프레임 검증(반환 높이로 동적 스택)."""
    ROOT = Path(__file__).resolve().parent.parent
    img = T.make_bg(); side = T.SAFE_ZONE["side"]; cw = 1080 - side * 2
    d = ImageDraw.Draw(img)
    gap = T.SPACE["md"]
    header(img, "Jun 2, 2026", "4:00 PM", 5, 12)
    data_chip_row(d, [("RSI", "82.5", "accent_alert"), ("VOL", "1.66×", "accent_data"),
                      ("52W", "HIGH", "accent_bull")], (side, T.SAFE_ZONE["header_h"] + T.SPACE["md"]))
    y = T.SAFE_ZONE["header_h"] + 90
    y += news_card(img, "ARM Holdings advances on AI PC chip validation",
                   "247wallst.com", "Jun 1, 2026", cw, (side, y)) + gap
    y += durability_badge(img, "DURABLE", "earnings · guidance", (side, y), width=560) + gap
    import numpy as np
    rng = np.random.default_rng(11)
    series = list(np.cumsum(rng.normal(0.4, 2.2, 60)) + 165)
    ch_h = 270
    chart_panel(img, series, "3M", "yfinance", (side, y), size=(cw, ch_h)); y += ch_h + gap
    bars = [{"label": "ARM", "value": 15.73}, {"label": "MRVL", "value": 7.04},
            {"label": "MU", "value": 6.64}, {"label": "NVDA", "value": 6.25},
            {"label": "TSM", "value": 4.11}]
    y += bar_compare(img, bars, 0, (side, y), width=cw) + gap
    risk_alert(img, "Overheated: RSI 82.5, 5 days up in a row.", (side, y), width=cw)
    _disclaimer(d)
    p = ROOT / out; p.parent.mkdir(parents=True, exist_ok=True); img.save(p); print("saved", p); return p


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "v2":
        preview_v2()
    else:
        preview_v1()
