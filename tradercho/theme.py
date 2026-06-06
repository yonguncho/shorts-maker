"""theme.py — TRADER CHO 디자인 시스템 단일 소스 (Terminal Pro).

색·폰트·크기·여백은 전부 여기 토큰에서만. 하드코딩 금지(L1, 강제제약 9).
"""
from __future__ import annotations
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageFont

BASE = Path(__file__).resolve().parent
FONTS_DIR = BASE / "fonts"

# ============ DESIGN TOKENS (Terminal Pro) ============
COLORS = {
    "bg_primary": "#0A0E14", "bg_secondary": "#11161D", "bg_chip": "#1A2128",
    "text_primary": "#E6EDF3", "text_secondary": "#8B949E", "text_muted": "#6E7681",
    "accent_bull": "#00D68F", "accent_bear": "#FF5C75", "accent_alert": "#FFB454",
    "accent_data": "#7AA2F7", "accent_hot": "#F7768E",
    "outline_strong": "#000000", "border_subtle": "#30363D",
}
FONTS = {"display": "Anton", "body": "Inter", "mono": "JetBrains Mono", "heading": "Inter Bold"}
SIZES = {"huge": 280, "xl": 120, "lg": 72, "md": 48, "sm": 32, "xs": 24}
SAFE_ZONE = {"top": 220, "bottom": 420, "side": 60, "header_h": 200, "footer_h": 380}
SPACE = {"xs": 8, "sm": 16, "md": 24, "lg": 40, "xl": 64, "xxl": 96}
RADIUS = {"sm": 8, "md": 16, "lg": 24, "pill": 999}
TEXT_STROKE = {"width": 10, "color": COLORS["outline_strong"]}
DURATION = {"punch": 0.2, "transition": 0.3, "countup": 1.2, "bar_fill": 0.8,
            "pop_in": 0.3, "shake": 0.15}
EASING = "cubic-bezier(0.4, 0, 0.2, 1)"

CANVAS = (1080, 1920)

# role → (파일, 가변폰트 instance 이름 or None)
_ROLE_FONT = {
    "display": ("Anton-Regular.ttf", None),
    "body": ("Inter.ttf", "Medium"),
    "heading": ("Inter.ttf", "Bold"),
    "mono": ("JetBrainsMono.ttf", "Medium"),
    "mono_bold": ("JetBrainsMono.ttf", "Bold"),
}


def hex2rgb(h: str) -> tuple:
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def c(name: str) -> tuple:
    """토큰 컬러 → RGB 튜플."""
    return hex2rgb(COLORS[name])


# ── 테마 분기(런타임 주입, Phase 7) ───────────────────
_TERMINAL_COLORS = dict(COLORS)
_TERMINAL_STROKE = dict(TEXT_STROKE)
ACTIVE_THEME = "terminal"


def apply_theme(name: str = "terminal"):
    """COLORS/TEXT_STROKE를 제자리 교체(c()가 호출 시점에 읽으므로 import 변경 불필요).
    'terminal'(기본 다크) / 'brightnews'(노랑 밝은톤). 구조·폰트·사이즈는 불변."""
    global ACTIVE_THEME
    if name == "brightnews":
        import theme_brightnews as TB
        COLORS.clear(); COLORS.update(TB.COLORS_BRIGHT)
        TEXT_STROKE.update(TB.TEXT_STROKE_BRIGHT)
    else:
        COLORS.clear(); COLORS.update(_TERMINAL_COLORS)
        TEXT_STROKE.update(_TERMINAL_STROKE)
    _font_cache.clear() if "_font_cache" in globals() else None
    ACTIVE_THEME = name
    return ACTIVE_THEME


@lru_cache(maxsize=256)
def get_font(role: str, size: int):
    file, vname = _ROLE_FONT.get(role, _ROLE_FONT["body"])
    f = ImageFont.truetype(str(FONTS_DIR / file), size)
    if vname:
        try:
            f.set_variation_by_name(vname)
        except Exception:
            pass
    return f


def draw_text_with_stroke(draw, text, pos, role="body", size=48, color="text_primary",
                          stroke=False, anchor="la"):
    """토큰 폰트·컬러로 텍스트. stroke=True 면 자막용 외곽선(L1.2: 자막에만)."""
    f = get_font(role, size)
    fill = c(color) if color in COLORS else color
    if stroke:
        draw.text(pos, text, font=f, fill=fill, anchor=anchor,
                  stroke_width=TEXT_STROKE["width"], stroke_fill=hex2rgb(TEXT_STROKE["color"]))
    else:
        draw.text(pos, text, font=f, fill=fill, anchor=anchor)


def text_size(draw, text, role, size):
    f = get_font(role, size)
    b = draw.textbbox((0, 0), text, font=f)
    return b[2] - b[0], b[3] - b[1]


def make_bg(size=CANVAS, base="bg_primary", noise=6) -> Image.Image:
    """평면 다크 배경 + 미묘한 노이즈(그라데이션 금지 L1.4). noise=세기."""
    w, h = size
    img = Image.new("RGB", size, c(base))
    if noise > 0:
        n = np.random.default_rng(7).integers(-noise, noise + 1, (h, w, 1), dtype=np.int16)
        arr = np.asarray(img).astype(np.int16) + n
        img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")
    return img


def signed_color(pct: float) -> str:
    """등락 부호 → 토큰 컬러명."""
    return "accent_bull" if pct >= 0 else "accent_bear"
