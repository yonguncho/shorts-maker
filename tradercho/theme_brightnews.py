"""theme_brightnews.py — TRADER CHO Bright News 톤 (한국 경제쇼츠 친숙 톤).

Terminal Pro(다크) 대비: 밝은 노랑 배경 + 검정 텍스트 + 자극 액센트 + 흰 외곽선.
디자인 토큰만 제공(구조·폰트·사이즈·safe-zone 동일). theme.apply_theme("brightnews")가 주입.
"""

COLORS_BRIGHT = {
    # Backgrounds
    "bg_primary":   "#FFE94A",   # 노랑 헤더·배경 (경제TV/뉴스 톤)
    "bg_secondary": "#FFFFFF",   # 카드 흰색(뉴스카드·말풍선·패널)
    "bg_chip":      "#FFF7C2",   # 데이터칩 연노랑
    # Text (FIX2: 노랑 위 대비 강화)
    "text_primary":   "#111111",
    "text_secondary": "#222222",
    "text_muted":     "#444444",
    # Accents (자극적)
    "accent_bull":  "#0EA853",   # 진녹색
    "accent_bear":  "#E63946",   # 진빨강
    "accent_alert": "#FF6B00",   # 주황
    "accent_data":  "#1E40AF",   # 진파랑
    "accent_hot":   "#DC2626",   # 빨강
    # Outlines (검정 텍스트엔 흰 외곽선)
    "outline_strong": "#FFFFFF",
    "border_subtle":  "#D4D4D4",
}
# 검정 텍스트 가독 위해 외곽선 흰색·두껍게
TEXT_STROKE_BRIGHT = {"width": 14, "color": "#FFFFFF"}
