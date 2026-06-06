"""make_channel_art.py — Trader Cho YouTube 채널 로고 + 배너 생성.

출력:
  assets/channel/logo_800.png       (800x800, 원형 마스코트)
  assets/channel/banner_2560.png    (2560x1440, YouTube 채널 배너)

사용:
  python tradercho/make_channel_art.py
"""
from __future__ import annotations
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
MASCOT_PATH = ROOT / "assets/mascot/trader_cho_vector.png"
OUT_DIR = ROOT / "assets/channel"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# 브랜드 팔레트
YELLOW   = "#FFE94A"
NAVY     = "#1B2A4A"
WHITE    = "#FFFFFF"
DARK     = "#1a1a1a"
GREEN    = "#3CB043"

FONT_PATH = "/System/Library/Fonts/HelveticaNeue.ttc"
FONT_BOLD   = 1   # Bold
FONT_REG    = 0   # Regular
FONT_LIGHT  = 7   # Light


def _font(size: int, idx: int = FONT_BOLD) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_PATH, size, index=idx)


def _text_bbox(draw: ImageDraw.ImageDraw, text: str, font) -> tuple:
    return draw.textbbox((0, 0), text, font=font)


# ── 로고 800×800 ──────────────────────────────────────────────────────────────

def make_logo(size: int = 800) -> Path:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 원형 배경 (노란색)
    margin = 16
    draw.ellipse([margin, margin, size - margin, size - margin],
                 fill=YELLOW, outline=NAVY, width=12)

    # 마스코트 로드 + 리사이즈 (원 안에 여유있게)
    mascot = Image.open(MASCOT_PATH).convert("RGBA")
    m_size = int(size * 0.72)
    mascot = mascot.resize((m_size, m_size), Image.LANCZOS)
    # 수평 중앙, 약간 위로 (하단 텍스트 여백)
    mx = (size - m_size) // 2
    my = int(size * 0.06)
    img.paste(mascot, (mx, my), mascot)

    # "TRADER CHO" 텍스트 하단
    label = "TRADER CHO"
    fnt = _font(int(size * 0.085), FONT_BOLD)
    bb = _text_bbox(draw, label, fnt)
    tw = bb[2] - bb[0]
    tx = (size - tw) // 2
    ty = int(size * 0.80)

    # 텍스트 그림자
    draw.text((tx + 3, ty + 3), label, font=fnt, fill=(0, 0, 0, 100))
    draw.text((tx, ty), label, font=fnt, fill=NAVY)

    out = OUT_DIR / "logo_800.png"
    img.save(out, "PNG")
    print(f"✅ 로고 저장: {out}")
    return out


# ── 배너 2560×1440 ────────────────────────────────────────────────────────────
# YouTube 안전 영역:
#   모든 기기(safe): 1546×423  → x: 507-2053, y: 509-931
#   데스크톱:        2560×423  → y: 509-931 (전폭)
#   TV:              2560×1440 (전체)

SAFE_X1, SAFE_Y1 = 507,  509
SAFE_X2, SAFE_Y2 = 2053, 931
SAFE_W  = SAFE_X2 - SAFE_X1   # 1546
SAFE_H  = SAFE_Y2 - SAFE_Y1   # 422

PAD = 40  # 안전 영역 내부 여백


def make_banner() -> Path:
    W, H = 2560, 1440
    img = Image.new("RGB", (W, H), YELLOW)
    draw = ImageDraw.Draw(img)

    # ── TV 확장 영역 배경 장식 (안전 영역 밖) ──
    # 상단 네이비 띠
    draw.rectangle([0, 0, W, SAFE_Y1 - 1], fill=NAVY)
    # 하단 네이비 띠
    draw.rectangle([0, SAFE_Y2 + 1, W, H], fill=NAVY)
    # 오른쪽 네이비 블록 (안전 영역 오른쪽 밖)
    draw.rectangle([SAFE_X2, 0, W, H], fill=NAVY)
    # 왼쪽 네이비 블록 (안전 영역 왼쪽 밖)
    draw.rectangle([0, 0, SAFE_X1, H], fill=NAVY)

    # TV 영역 장식 — 상단 채널명
    fnt_tv = _font(80, FONT_BOLD)
    draw.text((W // 2 - 200, 180), "TRADER CHO", font=fnt_tv, fill=YELLOW)
    # 하단 장식선
    for i in range(3):
        y = SAFE_Y2 + 60 + i * 55
        draw.line([(SAFE_X1, y), (SAFE_X2, y)], fill=YELLOW, width=4 - i)

    # ── 안전 영역 배경 (노란색 직사각형) ──
    draw.rectangle([SAFE_X1, SAFE_Y1, SAFE_X2, SAFE_Y2], fill=YELLOW)

    # 안전 영역 내부 오른쪽 절반 → 네이비
    split_x = SAFE_X1 + int(SAFE_W * 0.52)
    draw.rectangle([split_x, SAFE_Y1, SAFE_X2, SAFE_Y2], fill=NAVY)

    # ── 마스코트 (안전 영역 내부, 중앙 경계에 걸쳐) ──
    mascot_orig = Image.open(MASCOT_PATH).convert("RGBA")
    m_h = SAFE_H + 40          # 안전 영역보다 약간 크게 (상하 튀어나옴 허용)
    m_w = int(mascot_orig.width * m_h / mascot_orig.height)
    mascot = mascot_orig.resize((m_w, m_h), Image.LANCZOS)
    # 중앙 경계(split_x) 기준으로 마스코트를 중앙에 배치
    mx = split_x - m_w // 2
    my = SAFE_Y1 - 20
    img.paste(mascot, (mx, my), mascot)

    # ── 왼쪽 텍스트 (노란 배경 위, 네이비 텍스트) ──
    text_x = SAFE_X1 + PAD
    text_right = split_x - m_w // 2 - 20   # 마스코트 왼쪽 경계

    fnt_name = _font(108, FONT_BOLD)
    fnt_tag  = _font(48,  FONT_REG)
    fnt_sub  = _font(36,  FONT_LIGHT)

    # "Trader Cho" 채널명
    ty = SAFE_Y1 + PAD
    draw.text((text_x, ty), "Trader", font=fnt_name, fill=NAVY)
    bb = _text_bbox(draw, "Trader", fnt_name)
    ty2 = ty + (bb[3] - bb[1]) + 8
    draw.text((text_x, ty2), "Cho", font=fnt_name, fill=NAVY)

    # 태그라인
    bb2 = _text_bbox(draw, "Cho", fnt_name)
    ty3 = ty2 + (bb2[3] - bb2[1]) + 14
    draw.line([(text_x, ty3), (text_x + 380, ty3)], fill=NAVY, width=4)
    ty3 += 14
    draw.text((text_x, ty3), "US Stocks · Every Market Day", font=fnt_tag, fill=NAVY)

    # ── 오른쪽 텍스트 (네이비 배경 위, 흰 텍스트) ──
    rx = split_x + m_w // 2 + 24   # 마스코트 오른쪽
    ry = SAFE_Y1 + PAD

    draw.text((rx, ry), "@traderchoofficial", font=fnt_sub, fill="#aaccff")
    ry += 50

    for bullet in [
        "•  Daily stock breakdown",
        "•  What moved & why",
        "•  60-second insights",
    ]:
        draw.text((rx, ry), bullet, font=fnt_sub, fill=WHITE)
        ry += 54

    ry += 10
    draw.text((rx, ry), "Not financial advice.", font=_font(30, FONT_LIGHT),
              fill="#888888")

    out = OUT_DIR / "banner_2560.png"
    img.save(out, "PNG")
    print(f"✅ 배너 저장: {out}")
    return out


if __name__ == "__main__":
    make_logo()
    make_banner()
    print("\n완료 → assets/channel/")
