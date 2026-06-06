"""compose_short.py — 영상 합성 (Phase 4: 12씬 풀 빌드).

PIL 프레임 렌더(theme/components) + motion(프레임단위) + motion_sync(비트정렬 컷) + ffmpeg(인코딩/오디오).
12씬 신뢰형 구성. 모든 씬 컷을 BGM 비트에 스냅(L3.2). 헤더·면책 상시(L0.5/L2.3).
양념 모션: typewriter(씬3·9) / chart_draw(씬6) / bar_fill(씬5·7) / shake+glitch(씬10, L3.6 한계내).
moviepy 대신 PIL+ffmpeg(결정론·안정). 부분 렌더: RENDER_ONLY 환경변수에 씬 인덱스 CSV.
"""
from __future__ import annotations
import json
import math
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
import theme as T
import components as C
import motion as M
import mascot as Mascot
import motion_sync as MS
import trader_lens
import hook_generator
import json_utils as JU

ROOT = Path(__file__).resolve().parent.parent
FPS = 30
BGM = ROOT / "assets" / "bgm" / "test_track.mp3"
TMP = Path("/tmp/tc_compose")

# 세그먼트(sub-cut) 기반 타임라인(P1.3). 각 컷은 비트 스냅 + whoosh. prog=논리 씬(1~12).
# fn=렌더러, phase=세부단계, scene=논리 씬명(마스코트/배경/진행도 기준).
SCENES = [
    {"fn": "opening",    "phase": "",        "dur": 1.5, "prog": 0,  "scene": "opening"},  # FIX5: 0.8→1.5s
    {"fn": "hook",       "phase": "",        "dur": 2.4, "prog": 1,  "scene": "hook"},
    {"fn": "result",     "phase": "",        "dur": 2.8, "prog": 2,  "scene": "result"},
    {"fn": "catalyst",   "phase": "intro",   "dur": 1.0, "prog": 3,  "scene": "catalyst"},
    {"fn": "catalyst",   "phase": "card",    "dur": 2.4, "prog": 3,  "scene": "catalyst"},
    {"fn": "catalyst",   "phase": "highlight", "dur": 1.6, "prog": 3, "scene": "catalyst"},
    {"fn": "durability", "phase": "",        "dur": 2.6, "prog": 4,  "scene": "durability"},
    {"fn": "chart",      "phase": "draw",    "dur": 2.0, "prog": 5,  "scene": "chart"},
    {"fn": "chart",      "phase": "pulse",   "dur": 1.4, "prog": 5,  "scene": "chart"},
    {"fn": "chart",      "phase": "chips",   "dur": 1.6, "prog": 5,  "scene": "chart"},
    {"fn": "volume",     "phase": "bar",     "dur": 1.8, "prog": 6,  "scene": "volume"},
    {"fn": "volume",     "phase": "verdict", "dur": 1.6, "prog": 6,  "scene": "volume"},
    {"fn": "compare",    "phase": "",        "dur": 3.0, "prog": 7,  "scene": "compare"},
    {"fn": "related",    "phase": "stagger", "dur": 2.2, "prog": 8,  "scene": "related"},
    {"fn": "related",    "phase": "pulse",   "dur": 1.5, "prog": 8,  "scene": "related"},
    {"fn": "smart",      "phase": "",        "dur": 3.6, "prog": 9,  "scene": "smart"},
    {"fn": "risk",       "phase": "",        "dur": 3.6, "prog": 10, "scene": "risk"},
    {"fn": "payoff",     "phase": "",        "dur": 3.4, "prog": 11, "scene": "payoff"},
    {"fn": "closing",    "phase": "",        "dur": 3.0, "prog": 12, "scene": "closing"},
]
N_LOGICAL = 12
# STEP2: 모든 씬에 섹터 배경 강제(빈 공간 해소). 빈공간 lint 통과 목표.
BG_SCENES = {"hook", "result", "catalyst", "durability", "chart", "volume",
             "compare", "related", "smart", "risk", "payoff", "closing"}
# C.3 마스코트 반응 모션(씬 시작 1회) + Phase6 tilt
MASC_REACT = {"hook": "shock_jump", "chart": "point_chart", "risk": "warn_shake",
              "payoff": "cheer_arms", "closing": "cheer_arms", "volume": "tilt_question"}
# Phase6 STEP1.5: 말풍선=캐릭터 quip(≤4단어), 씬1·6·11만(L4.6). 마스코트 머리 위.
BUBBLE = {"hook":   ((250, 960),  "left",  0.5, 360),
          "volume": ((560, 1060), "right", 0.5, 320),
          "payoff": ((250, 1000), "left",  0.5, 340)}


# STEP2: 차트 미니어처 배치 씬(데이터 존재 신호, 빈공간 채움). (x,y) 좌상단.
THUMB = {"catalyst": (T.SAFE_ZONE["side"], 1360),
         "payoff":   (T.CANVAS[0] - 240, 1360),
         "volume":   (T.SAFE_ZONE["side"], 1360),
         "compare":  (T.CANVAS[0] - 240, T.SAFE_ZONE["header_h"] + 40),
         "smart":    (T.CANVAS[0] - 240, 1360)}


def _draw_scene_thumb(img, ctx, scene_name):
    pos = THUMB.get(scene_name)
    if pos:
        C.chart_thumbnail(img, ctx.get("series"), pos)


# FIX4: 씬1·3·11 회사 사진 → 풀스크린 배경으로 업그레이드(photo_card 카드 제거)
# hook/catalyst/payoff = 사진 배경(노랑 오버레이 55%). 카드 CFG는 레거시 보존용.
PHOTO_BG_SCENES = {"hook", "catalyst", "payoff"}

_PHOTO_CARD_CFG = {  # 레거시 — PHOTO_BG_SCENES에 포함된 씬은 사용하지 않음
    "hook":     (T.CANVAS[0] - T.SAFE_ZONE["side"] - 110, 1630, "hq"),
    "catalyst": (T.CANVAS[0] - T.SAFE_ZONE["side"] - 110, 1620, "product"),
    "payoff":   (590, 1620, "hq"),
}


def _make_photo_bg(base_bg, photo_path, overlay_alpha=0.55):
    """회사 사진을 1080×1920 풀스크린 배경으로: center-crop → 노랑 오버레이(FIX4)."""
    try:
        photo = Image.open(photo_path).convert("RGB")
        tw, th = T.CANVAS
        iw, ih = photo.size
        scale = max(tw / iw, th / ih)
        nw, nh = int(iw * scale) + 2, int(ih * scale) + 2
        photo = photo.resize((nw, nh), Image.LANCZOS)
        x0 = (nw - tw) // 2; y0 = (nh - th) // 2
        photo = photo.crop((x0, y0, x0 + tw, y0 + th)).convert("RGBA")
        ov = Image.new("RGBA", T.CANVAS,
                       T.hex2rgb(T.COLORS["bg_primary"]) + (int(255 * overlay_alpha),))
        photo.alpha_composite(ov)
        return photo
    except Exception:
        return base_bg.copy()


def _draw_photo_card(img, ctx, scene_name, t):
    """보조 회사 사진 카드(FIX4: PHOTO_BG_SCENES는 배경으로 대체 → 스킵)."""
    if scene_name in PHOTO_BG_SCENES:
        return  # 배경으로 사용 중 — 카드 불필요
    if t < 0.6:
        return
    cfg = _PHOTO_CARD_CFG.get(scene_name)
    if not cfg:
        return
    cx, cy, pkey = cfg
    # scene별 우선순위: product 우선(씬3), HQ 우선(씬1·11)
    if pkey == "product":
        photo_path = ctx.get("company_photo_product") or ctx.get("company_photo_hq")
    else:
        photo_path = ctx.get("company_photo_hq") or ctx.get("company_photo_product")
    if not photo_path:
        return
    try:
        alpha = min(1.0, (t - 0.6) / 0.25)
        # 임시 레이어에 photo_card 렌더 → 페이드인 적용
        layer = Image.new("RGBA", T.CANVAS, (0, 0, 0, 0))
        try:
            C.photo_card(layer, photo_path, center=(cx, cy),
                         width=220, height=140, require_license=True)
        except ValueError:
            return   # 라이선스 없음 — graceful skip
        if alpha < 1.0:
            a = layer.split()[3].point(lambda p: int(p * alpha))
            layer.putalpha(a)
        base = img if img.mode == "RGBA" else img.convert("RGBA")
        base.alpha_composite(layer)
    except Exception:
        pass   # graceful skip


def _draw_scene_bubble(img, ctx, scene_name, t):
    cfg = BUBBLE.get(scene_name)
    if not cfg:
        return
    (pos, side, appear, mw) = cfg
    text = ctx.get("bubbles", {}).get(scene_name)
    if not text or t < appear:
        return
    s, a = M.pop_in(t - appear, 0.3)   # 풍선 pop_in
    if a < 0.05:
        return
    lay = Image.new("RGBA", T.CANVAS, (0, 0, 0, 0))
    C.speech_bubble(lay, text, pos, mascot_side=side, max_width=mw, max_lines=4)
    if a < 1.0:
        al = lay.split()[3].point(lambda p: int(p * a)); lay.putalpha(al)
    img.alpha_composite(lay)


# ── 저수준 헬퍼 ───────────────────────────────────────
def _text_layer(text, role, size, color, stroke=0):
    f = T.get_font(role, size)
    tmp = Image.new("RGBA", (10, 10)); td = ImageDraw.Draw(tmp)
    b = td.textbbox((0, 0), text, font=f, stroke_width=stroke)
    w, h = b[2] - b[0] + stroke * 2 + 8, b[3] - b[1] + stroke * 2 + 8
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.text((w / 2, h / 2), text, font=f, fill=T.c(color) if color in T.COLORS else color,
           anchor="mm", stroke_width=stroke,
           stroke_fill=T.hex2rgb(T.TEXT_STROKE["color"]) if stroke else None)
    return img


def _paste_scaled(base, layer, center, scale=1.0, alpha=1.0):
    if scale <= 0:
        return
    w, h = int(layer.width * scale), int(layer.height * scale)
    lz = layer.resize((max(1, w), max(1, h)))
    if alpha < 1.0:
        a = lz.split()[3].point(lambda p: int(p * alpha))
        lz.putalpha(a)
    base.alpha_composite(lz, (int(center[0] - w / 2), int(center[1] - h / 2)))


def _scene_motion(frame, t, dur, pattern_idx):
    """진입 줌펀치 + 연속 줌호흡(씬별 위상차로 변주, L3.5 취지) + 미세 ±4px 팬 →
    어떤 프레임도 0.5s 이상 정지하지 않음(L3.1). 큰 켄번즈 '팬'은 제거(좌측 정렬 텍스트
    잘림 방지). 크롭 여백이 작아 좌우 안전여백 보존. frame: RGB. 반환 RGB(동일 크기)."""
    base = 1.03 + 0.012 * math.sin(2 * math.pi * t / 2.4 + pattern_idx)   # 1.018~1.042 연속
    scale = base * M.zoom_punch(t, 0.28)
    w, h = frame.size
    bw, bh = int(w * scale) + 2, int(h * scale) + 2
    big = frame.resize((bw, bh))
    panx = 4.0 * math.sin(2 * math.pi * t / 2.7 + pattern_idx * 0.7)
    pany = 3.0 * math.sin(2 * math.pi * t / 3.3 + pattern_idx * 0.5)
    # 앵커 (center_x, 0.35h): 상단을 적게 크롭해 헤더/섹션타이틀 보호(P0.1)
    x0 = max(0, min(bw - w, (bw - w) // 2 + int(round(panx))))
    y0 = max(0, min(bh - h, int(0.35 * (bh - h)) + int(round(pany))))
    return big.crop((x0, y0, x0 + w, y0 + h))


def _glitch_frame(rgb_img, t, dur=0.18):
    """RGB 채널 시프트 글리치(양념, L3.6 ≤2/영상). rgb_img: RGB."""
    active, shift, _ = M.glitch(t, dur)
    if not active or shift == 0:
        return rgb_img
    r, g, b = rgb_img.split()
    r = r.transform(r.size, Image.AFFINE, (1, 0, shift, 0, 1, 0))
    b = b.transform(b.size, Image.AFFINE, (1, 0, -shift, 0, 1, 0))
    return Image.merge("RGB", (r, g, b))


def _disclaimer(d):
    d.text((T.CANVAS[0] // 2, T.CANVAS[1] - 50), "Not financial advice · Educational purposes",
           font=T.get_font("body", T.SIZES["xs"]), fill=T.c("text_muted"), anchor="mm")


def _autofit_lines(text, role, maxw, max_lines, hi, lo=44):
    tmp = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    n_words = len((text or "").split())
    for size in range(hi, lo - 1, -4):
        lines = C._wrap(tmp, text, role, size, maxw, max_lines=max_lines)
        if sum(len(ln.split()) for ln in lines) >= n_words:
            return size, lines
    return lo, C._wrap(tmp, text, role, lo, maxw, max_lines=max_lines)


def _mascot_img(expr_path, target_h):
    m = Image.open(expr_path).convert("RGBA")
    s = target_h / m.height
    return m.resize((int(m.width * s), target_h))


import re as _re
_RISK_WORDS = {"risk", "stretched", "suspect", "extended", "overheated", "crowded",
               "stretch", "hot", "late", "extended?", "crowded?"}
_RE_W = _re.compile(r"[^A-Za-z0-9%+.\-]")
_RE_PCT = _re.compile(r"[+-]?\d+\.?\d*%")


def _word_color(w):
    """STEP3: 단어 → 토큰 색 (티커=data, +%=bull, -%=bear, 위험어=alert, else=primary)."""
    core = _RE_W.sub("", w)
    base = _RE_W.sub("", w.replace("'s", "").replace("’s", ""))
    if base.isupper() and 2 <= len(base) <= 5:
        return "accent_data"
    if _RE_PCT.fullmatch(core):
        return "accent_bear" if core.startswith("-") else "accent_bull"
    if w.strip(".,?!—-").lower() in _RISK_WORDS:
        return "accent_alert"
    return "text_primary"


def _mixed_subtitle(img, lines, y0, size, line_h, scale=1.0, alpha=1.0, center=True):
    """STEP3: 줄별 단어를 색 분리 + 흰 외곽선으로 렌더(중앙정렬). 키워드 강조 자막."""
    sw = T.TEXT_STROKE["width"]
    tmp = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    f = T.get_font("heading", size)
    space = tmp.textlength(" ", font=f)
    ly = y0
    for ln in lines:
        words = ln.split()
        widths = [tmp.textlength(w, font=f) for w in words]
        total = sum(widths) + space * (len(words) - 1)
        x = (T.CANVAS[0] - total) / 2 if center else T.SAFE_ZONE["side"]
        for w, wd in zip(words, widths):
            layer = _text_layer(w, "heading", size, _word_color(w), stroke=sw)
            _paste_scaled(img, layer, (x + wd / 2, ly + size / 2), scale, alpha)
            x += wd + space
        ly += line_h


def _section_title(d, text, y, color="accent_data"):
    """좌측 정렬 섹션 라벨(L1.5)."""
    d.text((T.SAFE_ZONE["side"], y), text.upper(), font=T.get_font("mono_bold", T.SIZES["md"]),
           fill=T.c(color), anchor="lm")


def _text_block(text, maxw, max_lines, hi, lo, y_top, y_bot, dur, role="body", line_mul=1.32):
    """본문 텍스트를 잘리지 않게 자동맞춤 + 세로 중앙정렬 + 타이핑 cps 산출(씬 65%에 완료)."""
    size, lines = _autofit_lines(text, role, maxw, max_lines, hi, lo)
    lh = int(size * line_mul); block = lh * len(lines)
    y0 = y_top + max(0, (y_bot - y_top - block) // 2)
    nchars = sum(len(l) for l in lines) + max(0, len(lines) - 1)
    cps = max(26.0, nchars / max(0.8, dur * 0.62))
    return {"size": size, "lines": lines, "line_h": lh, "y0": y0, "nchars": nchars,
            "cps": cps, "role": role}


def _tw_lines(lines, n):
    """고정 줄목록에서 앞 n글자만 누적 노출. 반환 (보이는줄리스트, 완료여부)."""
    out, rem = [], n
    for ln in lines:
        if rem <= 0:
            out.append(""); continue
        if rem >= len(ln):
            out.append(ln); rem -= len(ln) + 1
        else:
            out.append(ln[:rem]); rem = 0
    total = sum(len(l) for l in lines) + max(0, len(lines) - 1)
    return out, n >= total


def _draw_block(d, blk, t, side=None, typing=True, color="text_primary"):
    side = T.SAFE_ZONE["side"] if side is None else side
    f = T.get_font(blk["role"], blk["size"])
    if typing:
        vis, done = _tw_lines(blk["lines"], int(t * blk["cps"]))
    else:
        vis, done = blk["lines"], True
    y = blk["y0"]; last_xy = None
    for i, full_ln in enumerate(blk["lines"]):
        show = vis[i] if i < len(vis) else ""
        if show:
            d.text((side, y), show, font=f, fill=T.c(color), anchor="la")
            last_xy = (side + d.textlength(show, font=f), y)
        y += blk["line_h"]
    if typing and not done and last_xy and int(t * 3) % 2 == 0:
        d.text((last_xy[0] + 6, last_xy[1]), "▌", font=f, fill=T.c("accent_data"), anchor="la")


# ── FIX6: 겹침 감지 lint ─────────────────────────────
from collections import namedtuple as _NT
BBox = _NT("BBox", ["name", "x1", "y1", "x2", "y2"])


def _bbox_intersect(a: BBox, b: BBox) -> bool:
    return a.x1 < b.x2 and a.x2 > b.x1 and a.y1 < b.y2 and a.y2 > b.y1


def check_overlap(elements: list) -> list:
    """겹치는 요소 쌍 반환 (warn 전용 — raise 아님)."""
    return [(a.name, b.name) for i, a in enumerate(elements)
            for b in elements[i + 1:] if _bbox_intersect(a, b)]


def _scene_static_bboxes(scene_name: str) -> list:
    """씬별 정적 주요 요소 BBox (마스코트·썸네일·헤더). 동적 위치는 근사값."""
    bboxes = [BBox("header", 0, 0, T.CANVAS[0], T.SAFE_ZONE["header_h"])]
    _, wfrac, pos = Mascot.get_size_position_for_scene(scene_name)
    if wfrac > 0:
        mw = int(T.CANVAS[0] * wfrac); mh = int(mw * 1.3)
        cw, ch = T.CANVAS
        if pos == "left_third":    mx, my = 12, ch - mh - 210
        elif pos == "right_center": mx, my = cw - mw - 16, (ch - mh) // 2 + 230
        elif pos == "center_bottom": mx, my = (cw - mw) // 2, ch - mh - 300
        elif pos == "right_bottom": mx, my = cw - mw - 16, ch - mh - 250
        elif pos == "bottom_left": mx, my = 28, ch - mh - 300
        elif pos == "right_low":   mx, my = 750, ch - mh - 90
        elif pos == "center":      mx, my = (cw - mw) // 2, (ch - mh) // 2 + 180
        else:                      mx, my = cw - mw + 16, ch - mh - 300
        bboxes.append(BBox("mascot", mx, my, mx + mw, my + mh))
    tp = THUMB.get(scene_name)
    if tp:
        bboxes.append(BBox("chart_thumb", tp[0], tp[1], tp[0] + 220, tp[1] + 110))
    return bboxes


def run_overlap_lint() -> dict:
    """전체 씬 겹침 검사. {scene: [(a,b), ...]} 반환 (warn 전용)."""
    done, result = set(), {}
    for seg in SCENES:
        s = seg["scene"]
        if s in done:
            continue
        done.add(s)
        overlaps = check_overlap(_scene_static_bboxes(s))
        if overlaps:
            result[s] = overlaps
    return result


# ── 씬 렌더 함수들 (img: RGBA, t: 씬내 경과초, dur: 씬길이, ctx, phase) ──
def _place_mascot(img, ctx, scene_name, t):
    """폭 기반 동적 크기 + 씬별 위치(P1.2). mascot.get_size_position_for_scene 사용."""
    expr, wfrac, pos = Mascot.get_size_position_for_scene(scene_name)
    if not expr or wfrac <= 0 or pos == "none":
        return
    W = int(T.CANVAS[0] * wfrac)
    ck = (expr, W)
    m = ctx["masc"].get(ck)
    if m is None:
        src = Image.open(ctx["expr_paths"][expr]).convert("RGBA")
        m = src.resize((W, int(src.height * W / src.width))); ctx["masc"][ck] = m
    dy = int(M.idle_offset(t, 7, 2.0))
    rx, ry = M.mascot_react(MASC_REACT.get(scene_name, ""), t)   # C.3 반응 모션
    dy += int(ry)
    if scene_name in BUBBLE:                                     # A: 말풍선 구간 말하는 보빙
        dy += int(M.talking_motion(t, BUBBLE[scene_name][2], 9.9, amplitude=4.0))
    cw, ch = T.CANVAS
    if pos == "center_bottom":
        x, y = (cw - m.width) // 2, ch - m.height - 300 + dy
    elif pos == "right_center":
        x, y = cw - m.width - 16, (ch - m.height) // 2 + 230 + dy
    elif pos == "bottom_left":
        x, y = 28, ch - m.height - 300 + dy
    elif pos == "left_third":            # 좌측 하단 1/3 (말풍선 우측)
        x, y = 12, ch - m.height - 210 + dy
    elif pos == "right_bottom":
        x, y = cw - m.width - 16, ch - m.height - 250 + dy
    elif pos == "right_low":   # FIX2: related 씬 — 우하단 잘림 없는 위치
        x, y = 750, ch - m.height - 90 + dy
    elif pos == "center":
        x, y = (cw - m.width) // 2, (ch - m.height) // 2 + 180 + dy
    else:  # br
        x, y = cw - m.width + 16, ch - m.height - 300 + dy
    img.alpha_composite(m, (int(x + rx), int(y)))


def s_opening(img, d, t, dur, ctx, phase=""):
    """FIX5: 오프닝 1.5s — 흰플래시(0~0.15) → % pop_in(0.15~0.70) → 마스코트(0.70~) → fadeout(1.20~1.50)."""
    pct = ctx["pct"]; col = ctx["color"]
    if t >= 0.15:                                   # 거대 숫자 (0.15s 이후 유지)
        s, a = M.pop_in(t - 0.15, 0.3)
        sign = "+" if pct >= 0 else ""
        layer = _text_layer(f"{sign}{pct:.2f}%", "display", 280, col, stroke=T.TEXT_STROKE["width"])
        _paste_scaled(img, layer, (T.CANVAS[0] // 2, 800), s, a)
    if t >= 0.70:                                   # 마스코트 등장 (FIX2: 55%, FIX5: 0.5→0.70)
        try:
            m = Image.open(ctx["expr_paths"]["shocked"]).convert("RGBA")
            W = int(T.CANVAS[0] * 0.55); m = m.resize((W, int(m.height * W / m.width)))
            dx, dy = M.mascot_react("shock_jump", t - 0.70)
            img.alpha_composite(m, ((T.CANVAS[0] - m.width) // 2 + int(dx), 1120 + int(dy)))
        except Exception:
            pass
    if t >= 1.20:                                   # 페이드아웃 준비(1.20~1.50s)
        fade_a = int(min(80, (t - 1.20) / 0.30 * 80))
        img.alpha_composite(Image.new("RGBA", T.CANVAS, (0, 0, 0, fade_a)))
    if t < 0.15:                                    # 흰 플래시(맨 위)
        a = 255 if t < 0.10 else int(255 * (0.15 - t) / 0.05)
        img.alpha_composite(Image.new("RGBA", T.CANVAS, (255, 255, 255, a)))


def s_hook(img, d, t, dur, ctx, phase=""):
    hb = ctx["hook_block"]   # B: 풀자막(사실) + 말풍선(quip) 별도. STEP3: mixed_text 색분리
    scale, alpha = M.pop_in(t, 0.3)
    # 슬라이드업: 0.25s 동안 50px 아래서 위로 올라옴
    slide_y = int(50 * max(0.0, 1.0 - t / 0.25))
    _mixed_subtitle(img, hb["lines"], hb["y0"] + slide_y, hb["size"], hb["line_h"], scale, alpha, center=True)
    # 0.4s 이후 마지막 줄 아래에 강조 언더라인 L→R 드로우
    if t > 0.4 and hb["lines"]:
        prog = min(1.0, (t - 0.4) / 0.28)
        f = T.get_font("heading", hb["size"])
        tmp_d = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
        lw = tmp_d.textlength(hb["lines"][-1], font=f)
        uy = hb["y0"] + slide_y + hb["line_h"] * len(hb["lines"]) + 10
        ux0 = int((T.CANVAS[0] - lw) / 2)
        ux1 = ux0 + int(lw * prog)
        ul_col = T.c("accent_bear" if ctx["pct"] < 0 else "accent_bull")
        if ux1 > ux0:
            d.line([(ux0, uy), (ux1, uy)], fill=ul_col, width=6)


def s_result(img, d, t, dur, ctx, phase=""):
    C.data_chip_row(d, ctx["chips"], (T.SAFE_ZONE["side"], T.SAFE_ZONE["header_h"] + T.SPACE["md"]))
    # FIX1a: 로고 → 헤더 우측(48px). 데이터칩 행과 절대 겹침 없음.
    C.logo_chip(img, ctx.get("ticker", ""), (T.CANVAS[0] - T.SAFE_ZONE["side"] - 36, 100), target_w=48)
    d.text((T.SAFE_ZONE["side"], 360), f"Article: {ctx['article_date']}  ·  Data: {ctx['data_date']}",
           font=T.get_font("mono", T.SIZES["xs"]), fill=T.c("text_muted"), anchor="lm")
    val = M.count_up(t, ctx["pct"], 1.2)
    sign = "+" if val >= 0 else ""
    size = T.SIZES["huge"]
    if 1.2 <= t < 1.45:
        size = int(T.SIZES["huge"] * M.zoom_punch(t - 1.2, 0.25, 1.06))
    elif t >= 1.45:
        size = int(T.SIZES["huge"] * (1 + 0.014 * math.sin(2 * math.pi * (t - 1.45) / 1.6)))
    C.huge_number(img, f"{sign}{val:.2f}%", color=ctx["color"], center=(T.CANVAS[0] // 2, 1000),
                  size=size, sublabel="in one day",
                  sublabel2=f"vs SPX {ctx['price'].get('spx_pct_change'):+.2f}%")
    # 방향 화살표 배지: count-up 완료(1.2s) 후 pop-in, 좌측 여백
    if t >= 1.2:
        arrow = "▼" if ctx["pct"] < 0 else "▲"
        s, a = M.pop_in(t - 1.2, 0.22)
        arr_layer = _text_layer(arrow, "display", 130, ctx["color"], stroke=0)
        _paste_scaled(img, arr_layer, (68, 1000), s, a)


def s_catalyst(img, d, t, dur, ctx, phase="card"):
    side = T.SAFE_ZONE["side"]; cw = T.CANVAS[0] - side * 2
    _section_title(d, "What happened", T.SAFE_ZONE["header_h"] + 60)
    cat = ctx["trader"].get("catalyst", {})
    tag = (cat.get("type", "") or "").replace("_", " ").upper()
    ty = T.SAFE_ZONE["header_h"] + 110
    if tag:
        tw = d.textlength(tag, font=T.get_font("mono_bold", T.SIZES["sm"]))
        d.rounded_rectangle((side, ty, side + tw + 40, ty + 56),
                            radius=T.RADIUS["pill"], fill=T.c("bg_chip"), outline=T.c("border_subtle"), width=2)
        d.text((side + 20, ty + 28), tag, font=T.get_font("mono_bold", T.SIZES["sm"]),
               fill=T.c("accent_data"), anchor="lm")
    if phase == "intro":
        return
    slide = int((1 - M.ease_out(min(1.0, t / 0.4))) * 70) if phase == "card" else 0
    card_y = ty + 84 + slide
    h = C.news_card(img, cat.get("why", ""), ctx.get("source", "News"),
                    ctx.get("article_label", ctx["article_date"]), cw, (side, card_y), max_lines=4)
    if phase == "highlight":   # P2.2 키워드 형광펜 스윕
        _keyword_sweep(img, d, cat.get("why", ""), (side, card_y), cw, h, t, ctx.get("hl_words", []))


def s_durability(img, d, t, dur, ctx, phase=""):
    _section_title(d, "Durable or temporary?", T.SAFE_ZONE["header_h"] + 70)
    cat = ctx["trader"].get("catalyst", {})
    kind = cat.get("durability", "DURABLE")
    reason = (cat.get("type", "") or "catalyst").replace("_", " ")
    scale, alpha = M.pop_in(t, 0.35)
    layer = Image.new("RGBA", T.CANVAS, (0, 0, 0, 0))
    bw = 620; bx = (T.CANVAS[0] - bw) // 2
    h = C.durability_badge(layer, kind, reason, (bx, 560), width=bw)
    _paste_scaled(img, layer.crop((bx, 560, bx + bw, 560 + h)),
                  (T.CANVAS[0] // 2, 560 + h / 2), scale, alpha)
    note = ctx["trader"].get("chart", {}).get("too_late_read", "")
    if note and t > 0.5:
        for i, ln in enumerate(C._wrap(d, note, "body", T.SIZES["md"], T.CANVAS[0] - 120, max_lines=3)):
            d.text((T.SAFE_ZONE["side"], 820 + i * int(T.SIZES["md"] * 1.3)), ln,
                   font=T.get_font("body", T.SIZES["md"]), fill=T.c("text_secondary"), anchor="la")


# 거래량 판정 → (라벨색, 배지fill, 배지텍스트색) (L2.7, 하드코딩 금지)
_VERDICT_STYLE = {"conviction": ("accent_bull", "accent_bull", "bg_primary"),
                  "neutral":    ("text_secondary", "bg_chip", "text_secondary"),
                  "suspect":    ("accent_alert", "accent_alert", "bg_primary")}


def s_volume(img, d, t, dur, ctx, phase="bar"):
    verdict = (ctx["trader"].get("volume", {}).get("verdict", "neutral") or "neutral").lower()
    lab_col, fill_col, txt_col = _VERDICT_STYLE.get(verdict, _VERDICT_STYLE["neutral"])
    _section_title(d, "Volume vs average", T.SAFE_ZONE["header_h"] + 70)
    vs = ctx["price"].get("vol_vs_avg", 1.0)
    cur = vs * (M.reveal_fraction(t, dur * 0.7) if phase == "bar" else 1.0)
    C.huge_number(img, f"{cur:.2f}×", color=lab_col, center=(T.CANVAS[0] // 2, 780),
                  size=T.SIZES["huge"], sublabel="of 30-day average volume")
    if phase == "verdict":
        s, a = M.pop_in(t, 0.3)
        vtxt = verdict.upper()
        vf = T.get_font("display", T.SIZES["lg"]); vw = d.textlength(vtxt, font=vf)
        layer = Image.new("RGBA", (int(vw + 84), 98), (0, 0, 0, 0)); ld = ImageDraw.Draw(layer)
        outline = T.c("border_subtle") if fill_col == "bg_chip" else None
        ld.rounded_rectangle((0, 0, vw + 80, 94), radius=T.RADIUS["pill"], fill=T.c(fill_col),
                             outline=outline, width=2 if outline else 0)
        ld.text(((vw + 80) / 2, 47), vtxt, font=vf, fill=T.c(txt_col), anchor="mm")
        _paste_scaled(img, layer, (T.CANVAS[0] // 2, 1110), s, a)


def s_chart(img, d, t, dur, ctx, phase="draw"):
    _section_title(d, "Where it trades now", T.SAFE_ZONE["header_h"] + 50)
    series = ctx["series"]
    side = T.SAFE_ZONE["side"]; cw = T.CANVAS[0] - side * 2
    n = max(2, int(len(series) * M.reveal_fraction(t, dur * 0.9))) if phase == "draw" else len(series)
    # STEP2: 차트 패널 배경(빈공간 해소 + 라인 가독성). 반투명 카드.
    panel = Image.new("RGBA", (cw + 20, 620), T.hex2rgb(T.COLORS["bg_secondary"]) + (205,))
    ImageDraw.Draw(panel).rounded_rectangle((0, 0, cw + 19, 619), radius=T.RADIUS["md"],
                                            outline=T.c("border_subtle"), width=1)
    img.alpha_composite(panel, (side - 10, 350))
    # P2.1: 차트 영역 확대(약 60% 높이)
    C.chart_panel(img, series[:n], "3M", "yfinance", (side, 380), size=(cw, 560))
    # B.3: 출처 칩(크게) + 업데이트 일자 + B.1 로고(우상단, graceful)
    C.data_chip(d, "SOURCE", "Yahoo Finance", (side + 8, 398), value_color="accent_data")
    C.data_chip(d, "UPDATED", ctx.get("data_date", ""), (side + 8, 458), value_color="text_secondary")
    # FIX1b: 로고 → 헤더 우측(40px). 차트 패널/라인 끝점과 절대 겹침 없음.
    C.logo_chip(img, ctx.get("ticker", ""), (T.CANVAS[0] - T.SAFE_ZONE["side"] - 28, 100), target_w=40)
    lx = side + 40   # P0.2: 좌측 잘림 방지 여백(모션 후에도 leftmost x≥80 보장)
    if phase in ("pulse", "chips"):
        rsi = ctx["price"].get("rsi"); pos = ctx["price"].get("position_52w", "")
        s, a = M.pop_in(t, 0.3)
        lay = _text_layer(f"RSI {rsi}  ·  {pos}", "mono_bold", T.SIZES["md"],
                          "accent_alert" if (rsi or 0) >= 70 else "accent_data")
        _paste_scaled(img, lay, (lx + lay.width // 2, 1010), s, a)
    if phase == "chips":
        note = ctx["trader"].get("chart", {}).get("rsi_note", "")
        for i, ln in enumerate(C._wrap(d, note, "body", T.SIZES["md"], cw - 40, max_lines=2)):
            d.text((lx, 1070 + i * int(T.SIZES["md"] * 1.3)), ln,
                   font=T.get_font("body", T.SIZES["md"]), fill=T.c("text_secondary"), anchor="la")


def s_compare(img, d, t, dur, ctx, phase=""):
    _section_title(d, f"{ctx.get('ticker','ARM')} vs the tape", T.SAFE_ZONE["header_h"] + 50)
    side = T.SAFE_ZONE["side"]; cw = T.CANVAS[0] - side * 2
    frac = M.reveal_fraction(t, 1.0)
    bars = [{"label": b["label"], "value": round(b["value"] * frac, 2),
             "is_positive": b["value"] >= 0} for b in ctx["compare_bars"]]
    C.bar_compare(img, bars, 0, (side, 440), width=cw, caption="Today's change %")


def s_related(img, d, t, dur, ctx, phase="stagger"):
    _section_title(d, ctx.get("sector_title", "Sector sympathy"), T.SAFE_ZONE["header_h"] + 60)
    side = T.SAFE_ZONE["side"]; cw = T.CANVAS[0] - side * 2
    bars_src = ctx.get("sector_bars", [])
    if not bars_src:
        d.text((side, 520), "No comparable sector moves captured.",
               font=T.get_font("body", T.SIZES["md"]), fill=T.c("text_secondary"), anchor="la")
        return
    # P1.4: bar_compare(related[] 실 %, 같은 거래일만), ARM 강조, stagger 0.1s 차오름
    bars = []
    for i, b in enumerate(bars_src):
        fr = M.reveal_fraction(t - i * 0.1, 0.5) if phase == "stagger" else 1.0
        bars.append({"label": b["label"], "value": round(b["value"] * fr, 2),
                     "is_positive": b["value"] >= 0})
    # FIX3: 막대 크기 상향(90→120px), 간격(30→40px), 시작 y 상향(420→300)
    bh = C.bar_compare(img, bars, 0, (side, 300), width=cw,
                       caption=ctx.get("sector_caption", "Today's change %"),
                       row_h=120, gap=40)
    # FIX3: sympathy_insight 항상 typewriter (stagger/pulse 모두, 막대 아래 40px)
    insight = ctx.get("sympathy_insight", "")
    if insight:
        shown = M.typewriter(insight, t, cps=22)
        iy = 300 + (bh or 360) + 40
        d.text((side, iy), shown, font=T.get_font("mono", T.SIZES["md"]),
               fill=T.c("text_secondary"), anchor="la")


def _draw_analyst_chip(img, d, price, y_bottom):
    """애널리스트 컨센서스 + 목표가 칩 (smart 씬 하단). 데이터 없으면 스킵."""
    analyst = price.get("analyst", {})
    cons = analyst.get("consensus", {})
    pt = (analyst.get("price_targets") or {})
    target = pt.get("mean")
    if not cons and not target:
        return
    side = T.SAFE_ZONE["side"]; cw = T.CANVAS[0] - side * 2
    items = []
    if cons:
        total = sum(cons.get(k, 0) for k in ("strong_buy", "buy", "hold", "sell", "strong_sell"))
        bull = cons.get("strong_buy", 0) + cons.get("buy", 0)
        pct_bull = int(bull / total * 100) if total else 0
        col = "accent_bull" if pct_bull >= 60 else ("accent_alert" if pct_bull >= 40 else "accent_bear")
        items.append((f"BUY  {pct_bull}%  of {total} analysts", col))
    if target:
        current = price.get("last_close", 0)
        diff_pct = (current / target - 1) * 100
        arrow = "▲" if diff_pct > 0 else "▼"
        tcol = "accent_bear" if diff_pct > 0 else "accent_bull"
        items.append((f"Target  ${target:.0f}  {arrow} {abs(diff_pct):.0f}% vs now", tcol))
    chip_h = 52; gap = 14
    total_h = len(items) * chip_h + (len(items) - 1) * gap
    y = y_bottom - total_h - 20
    for label, col in items:
        f = T.get_font("mono", T.SIZES["sm"])
        tw = d.textlength(label, font=f)
        bx = side; bw = cw
        d.rounded_rectangle((bx, y, bx + bw, y + chip_h), radius=T.RADIUS["sm"],
                             fill=T.hex2rgb(T.COLORS["bg_chip"]) + (210,),
                             outline=T.c("border_subtle"), width=1)
        d.text((bx + 20, y + chip_h // 2), label, font=f, fill=T.c(col), anchor="lm")
        y += chip_h + gap


def s_smart(img, d, t, dur, ctx, phase=""):
    _section_title(d, "The smart-money read", T.SAFE_ZONE["header_h"] + 70)
    side = T.SAFE_ZONE["side"]; cw = T.CANVAS[0] - side * 2
    # STEP2: 텍스트 패널 배경(빈공간 해소)
    blk = ctx["smart_block"]; ph = int(blk["line_h"] * len(blk["lines"]) + 80)
    panel = Image.new("RGBA", (cw + 20, ph), T.hex2rgb(T.COLORS["bg_secondary"]) + (195,))
    ImageDraw.Draw(panel).rounded_rectangle((0, 0, cw + 19, ph - 1), radius=T.RADIUS["md"],
                                            outline=T.c("border_subtle"), width=1)
    img.alpha_composite(panel, (side - 10, blk["y0"] - 40))
    _draw_block(d, blk, t, typing=True)
    # 애널리스트 컨센서스 칩 (0.8s 이후 페이드인)
    if t > 0.8:
        _draw_analyst_chip(img, d, ctx["price"], T.CANVAS[1] - T.SAFE_ZONE.get("footer_h", 60) - 80)


def s_risk(img, d, t, dur, ctx, phase=""):
    _section_title(d, "Before you chase", T.SAFE_ZONE["header_h"] + 70, color="accent_alert")
    side = T.SAFE_ZONE["side"]; cw = T.CANVAS[0] - side * 2
    C.risk_alert(img, ctx["trader"].get("risk", "Elevated risk."), (side, 540), width=cw)


def s_payoff(img, d, t, dur, ctx, phase=""):
    _section_title(d, "So — what's the read?", T.SAFE_ZONE["header_h"] + 60)
    pb = ctx["payoff_block"]   # B: 풀자막(payoff) 유지 + 말풍선(quip) 별도
    per_word = 0.16
    for i, (w, x, y) in enumerate(pb["words"]):
        local = t - i * per_word
        if local < 0:
            continue
        s, a = M.pop_in(local, 0.22)   # STEP3: payoff 단어 색분리 + 흰 외곽선
        layer = _text_layer(w, "heading", pb["size"], _word_color(w), stroke=T.TEXT_STROKE["width"])
        _paste_scaled(img, layer, (x + layer.width // 2, y + pb["size"] // 2), s, a)


def _sources_lines(ctx):
    return [("Data", f"Yahoo Finance  ·  {ctx.get('data_date', '')}"),
            ("News", f"{ctx.get('source', 'news')}  ·  {ctx.get('article_date', '')}")]


def s_closing(img, d, t, dur, ctx, phase=""):
    scale, alpha = M.pop_in(t, 0.4)
    layer = _text_layer("TRADER CHO", "display", 104, "accent_data", stroke=0)
    _paste_scaled(img, layer, (T.CANVAS[0] // 2, 360), scale, alpha)
    if t > 0.35:
        d.text((T.CANVAS[0] // 2, 470), "Daily US-market setups, decoded.",
               font=T.get_font("heading", T.SIZES["md"]), fill=T.c("text_primary"), anchor="mm")
    # B.5: Sources 카드(신뢰 신호) — 0.5s 후 등장
    if t > 0.5:
        side = T.SAFE_ZONE["side"]; cw = T.CANVAS[0] - side * 2
        C.sources_card(img, _sources_lines(ctx), (side, 560), width=cw)


def _keyword_sweep(img, d, text, card_pos, width, card_h, t, hl_words):
    """P2.2: 헤드라인 핵심 단어 위로 accent_alert 알파 형광펜 좌→우 스윕(0.5s)."""
    if not hl_words:
        return
    sweep = M.reveal_fraction(t, 0.5)
    pad = T.SPACE["lg"]; x0 = card_pos[0] + pad; y0 = card_pos[1] + pad
    hf = T.get_font("heading", T.SIZES["lg"]); lh = int(T.SIZES["lg"] * 1.25)
    lines = C._wrap(d, text, "heading", T.SIZES["lg"], width - pad * 2, max_lines=4)
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0)); od = ImageDraw.Draw(overlay)
    for li, ln in enumerate(lines):
        cx = x0
        for word in ln.split():
            wlen = od.textlength(word + " ", font=hf)
            base = word.strip(".,").lower()
            if base in hl_words:
                hw = od.textlength(word, font=hf) * sweep
                yy = y0 + li * lh
                od.rounded_rectangle((cx - 4, yy + 8, cx + hw + 4, yy + T.SIZES["lg"]),
                                     radius=6, fill=T.hex2rgb(T.COLORS["accent_alert"]) + (100,))
            cx += wlen
    img.alpha_composite(overlay)


SCENE_FN = {"opening": s_opening, "hook": s_hook, "result": s_result, "catalyst": s_catalyst, "durability": s_durability,
            "volume": s_volume, "chart": s_chart, "compare": s_compare, "related": s_related,
            "smart": s_smart, "risk": s_risk, "payoff": s_payoff, "closing": s_closing}


# ── 타임라인(narration-구동, A) ───────────────────────
CLOSING_MIN = 4.0   # B.5: Sources 카드 표시용 클로징 최소 길이
NARR_TAIL = 0.5     # A: 나레이션 뒤 여유


def _prog_segs():
    out = {}
    for i, seg in enumerate(SCENES):
        out.setdefault(seg["prog"], []).append(i)
    return out


def scene_timeline(bgm=BGM, out_dir=None):
    """narration-구동 타임라인(A.1): 나레이션 씬 길이=max(시각최소, wav+0.5). 비트스냅.
    out_dir의 narration.json 있으면 그 wav 길이로 씬 확장. 반환에 narr(검증용) 포함."""
    narr = {}
    if out_dir:
        nj = Path(out_dir) / "narration.json"
        if nj.exists():
            narr = {int(k): v["dur"] for k, v in json.loads(nj.read_text()).items()}
    ps = _prog_segs()
    pdur = [seg["dur"] for seg in SCENES]   # planned 세그먼트 길이(확장 전)

    def _extend(prog, target):
        segs = ps[prog]; cur = sum(pdur[i] for i in segs)
        if target > cur:
            pdur[segs[-1]] = round(pdur[segs[-1]] + (target - cur), 3)

    _extend(12, CLOSING_MIN)                       # 클로징 최소
    for prog, wd in narr.items():                  # 나레이션 씬 확장(무손실)
        _extend(prog, wd + NARR_TAIL)

    beats, tempo, src = MS.extract_beats(str(bgm))
    planned, acc = [], 0.0
    for d in pdur:
        planned.append(acc); acc += d
    snapped = [MS.snap_to_beat(p, beats) for p in planned]
    for i in range(1, len(snapped)):               # 단조 + 확장 길이 보존
        if snapped[i] <= snapped[i - 1] + 0.5:
            snapped[i] = round(snapped[i - 1] + pdur[i], 3)
    durs = [round(snapped[i + 1] - snapped[i], 3) for i in range(len(SCENES) - 1)] + [pdur[-1]]
    total = round(snapped[-1] + durs[-1], 2)
    spans = {}
    for i, seg in enumerate(SCENES):
        pr = seg["prog"]
        if pr not in spans:
            spans[pr] = {"start": snapped[i], "dur": 0.0, "name": seg["scene"]}
        spans[pr]["dur"] = round(snapped[i] + durs[i] - spans[pr]["start"], 3)
    result_idx = next(i for i, s in enumerate(SCENES) if s["fn"] == "result")
    smart_idx = next(i for i, s in enumerate(SCENES) if s["fn"] == "smart")
    return {"snapped": snapped, "durs": durs, "total": total, "spans": spans, "narr": narr,
            "tempo": tempo, "src": src, "result_idx": result_idx, "smart_idx": smart_idx,
            "cut_times": snapped[:]}


def lint_cut_durations(TL: dict) -> list[dict]:
    """H.8 micro-cut lint.
    narration 씬(prog ∈ NARR_PROGS): floor = narr_wav + NARR_TAIL.
    비narration 씬(opening 등): floor = scene_config.duration 합산(10% 허용).
    반환: [{prog, name, actual, floor}] (위반 항목만)."""
    import narration as _N
    NARR_PROGS = set(_N.NARR_SCENES)
    config_dur: dict[int, float] = {}
    for seg in SCENES:
        config_dur[seg["prog"]] = config_dur.get(seg["prog"], 0.0) + seg["dur"]
    issues = []
    for prog, span in TL["spans"].items():
        actual = span["dur"]
        if prog in NARR_PROGS:
            narr_d = TL["narr"].get(prog, 0.0)
            floor = (narr_d + NARR_TAIL) if narr_d else config_dur.get(prog, 0.0)
        else:
            floor = config_dur.get(prog, 0.0) * 0.90  # 10% 허용
        if actual < floor - 0.05:
            issues.append({"prog": prog, "name": span["name"],
                           "actual": round(actual, 3), "floor": round(floor, 3)})
    return issues


def empty_space_lint(frame_dir=TMP, raise_over=0.62, warn_over=0.50, out_dir=None):
    """STEP2.2: 씬별 첫 프레임의 safe-zone 내 bg_primary 유사 픽셀 비율. warn/raise.
    out_dir 전달 시 narration-구동 타임라인으로 프레임 인덱스 정렬(렌더와 동일)."""
    import numpy as np
    bg = np.array(T.hex2rgb(T.COLORS["bg_primary"]))
    side = T.SAFE_ZONE["side"]; top = T.SAFE_ZONE["top"]
    bot = T.CANVAS[1] - T.SAFE_ZONE["footer_h"]
    TL = scene_timeline(out_dir=out_dir)
    durs = TL["durs"]; nfr = [max(1, int(d * FPS)) for d in durs]
    start = []; b = 0
    for n in nfr:
        start.append(b); b += n
    last_seg = {}   # 정착 프레임(마지막 서브컷 85%) 샘플 — reveal 중간 아닌 완성상태
    for i, s in enumerate(SCENES):
        last_seg[s["prog"]] = i
    frames = sorted(Path(frame_dir).glob("f*.png"))
    out = []
    for prog in range(1, N_LOGICAL + 1):
        si = last_seg[prog]; fi = start[si] + min(int(nfr[si] * 0.85), nfr[si] - 1)
        if fi >= len(frames):
            continue
        from PIL import Image as _I
        a = np.asarray(_I.open(frames[fi]).convert("RGB"))[top:bot, side:T.CANVAS[0] - side]
        empty = float((np.abs(a.astype(int) - bg).sum(2) < 24).mean())
        out.append({"scene": prog, "empty_ratio": round(empty, 3),
                    "warn": empty >= warn_over, "raise": empty >= raise_over})
    return out


def assert_no_truncation(out_dir, margin=0.25):
    """A.3: 모든 narration wav 길이 + margin ≤ 씬 듀레이션. 위반 시 raise(잘림 0건 강제)."""
    TL = scene_timeline(out_dir=out_dir)
    bad = []
    for scene, wd in TL["narr"].items():
        sd = TL["spans"].get(scene, {}).get("dur", 0)
        if wd + margin > sd:
            bad.append((scene, round(wd, 2), round(sd, 2)))
    if bad:
        raise RuntimeError(f"나레이션 잘림 위험(A.3): {bad} (wav+{margin} > 씬길이)")
    return TL


# ── 메인 렌더 ─────────────────────────────────────────
def render(ticker="ARM", out_name="short_full_v2.mp4", theme="terminal"):
    T.apply_theme(theme)   # Phase7: 디자인 토큰 분기(terminal/brightnews)
    print(f"THEME={theme} (bg_primary={T.COLORS['bg_primary']})")
    TMP.mkdir(parents=True, exist_ok=True)
    for f in TMP.glob("*.png"):
        f.unlink()
    out_dir = sorted((ROOT / "outputs").glob(f"{ticker.upper()}_*"))[-1]
    price = json.loads((out_dir / "price.json").read_text())
    hook = json.loads((out_dir / "hook.json").read_text())
    trader = json.loads((out_dir / "trader_lens.json").read_text())
    expr_paths = Mascot.ensure()

    pct = price["pct_change"]
    color = T.signed_color(pct)
    data_date = hook.get("data_date") or price["as_of"][:10]
    article_date = hook.get("article_date") or data_date
    date_label = data_date if article_date == data_date else f"Art {article_date[5:]} · Data {data_date[5:]}"
    hook_line = hook.get("hook_line", f"What's moving {ticker}?")
    payoff_line = hook.get("payoff_line", "")

    # 시계열(차트). pipeline이 price.json에서 series_3m를 제거하므로(슬림화), 렌더 시
    # data_fetch로 실데이터 재조회(L0.4: 임의숫자 금지 — 실 시계열만). 실패 시 단일종가 평탄선.
    series = price.get("series_3m")
    if not series:
        try:
            import data_fetch
            series = data_fetch.fetch(ticker).get("series_3m")
        except Exception as e:
            print("  ⚠ series 재조회 실패:", e)
    if not series or len(series) < 2:
        lc = price.get("last_close", 100.0)
        series = [lc, lc]

    # 훅/페이오프 텍스트 블록 사전 계산
    hsize, hlines = _autofit_lines(hook_line, "heading", T.CANVAS[0] - 160, 4, T.SIZES["xl"])
    hlh = int(hsize * 1.16); hblock = hlh * len(hlines)
    hook_block = {"size": hsize, "lines": hlines, "line_h": hlh,
                  "y0": 300 + max(0, (580 - hblock) // 2) + hlh // 2}
    psize, plines = _autofit_lines(payoff_line, "heading", T.CANVAS[0] - 140, 5, T.SIZES["lg"])
    plh = int(psize * 1.28)
    p_y0 = 460 + max(0, (560 - plh * len(plines)) // 2)
    _td = ImageDraw.Draw(Image.new("RGBA", (10, 10))); _pf = T.get_font("heading", psize)
    p_words, _yy = [], p_y0
    for ln in plines:
        _xx = T.SAFE_ZONE["side"]
        for w in ln.split():
            p_words.append((w, _xx, _yy))
            _xx += _td.textlength(w + " ", font=_pf)
        _yy += plh
    payoff_block = {"size": psize, "lines": plines, "line_h": plh, "y0": p_y0, "words": p_words}

    chips = [("RSI", str(price.get("rsi")), "accent_alert"),
             ("VOL", f"{price.get('vol_vs_avg')}×", "accent_data"),
             ("52W", (price.get("position_52w", "") or "").replace("52w ", "").upper() or "MID", "accent_bull")]
    # 실값 보유한 ARM/SPX만(피어 일중 등락 실값 부재 → 임의숫자 금지 L0.4)
    compare_bars = [{"label": ticker.upper(), "value": pct},
                    {"label": "SPX", "value": price.get("spx_pct_change", 0.0)}]

    # P1.4/P0.2: 섹터 피어 실 등락% + as_of 시점일관성(같은 거래일만). 실데이터(L0.4).
    # P0.1 스냅샷: related_dates.json 있으면 재페치 없이 재사용(파이프라인 스냅샷 동결).
    rd_path = out_dir / "related_dates.json"
    if rd_path.exists():
        related_changes = json.loads(rd_path.read_text()).get("related", [])
        print("  ⓘ related_dates.json 재사용(스냅샷 동결)")
    else:
        related_changes = trader_lens.fetch_related_changes(trader.get("related", []), data_date, limit=5)
        rd_path.write_text(json.dumps({"data_date": data_date, "related": related_changes},
                                      indent=2, ensure_ascii=False))
    same_day = [r for r in related_changes if r.get("same_day") and r.get("pct_change") is not None]
    dropped = [r["ticker"] for r in related_changes if not r.get("same_day")]
    if dropped:
        print(f"  ⚠ 시점 불일치 피어 제외(P0.2): {dropped}")
    durable = (trader.get("catalyst", {}).get("durability", "") or "").upper() == "DURABLE"
    if len(same_day) >= 4:   # 본 명세: ARM + 피어 4~5
        sector_bars = [{"label": ticker.upper(), "value": pct}] + \
                      [{"label": r["ticker"], "value": r["pct_change"]} for r in same_day[:5]]
        sector_title = "Moving with ARM" if durable else "Sector sympathy"
    else:                    # 폴백: ARM vs SPX(현 동작 유지)
        print(f"  ⓘ 동일거래일 피어 {len(same_day)}개(<4) → 섹터 씬 SPX 폴백")
        sector_bars = [{"label": ticker.upper(), "value": pct},
                       {"label": "SPX", "value": price.get("spx_pct_change", 0.0)}]
        sector_title = f"{ticker.upper()} vs the tape"
    # P1.1: 섹터 동조 인사이트 1줄(피어 실데이터 기반)
    sympathy_insight = trader_lens.sympathy_insight(
        pct, [b["value"] for b in sector_bars[1:]]) if len(sector_bars) >= 3 else ""

    # STEP1.5 C: 말풍선=마스코트 quip(≤4단어 구어체, L4.6). 씬1/6/11만.
    quips = hook_generator.mascot_quips(trader, price)
    bubbles = {"hook": quips.get(1), "volume": quips.get(6), "payoff": quips.get(11)}

    # 키워드 형광펜 대상(P2.2): why 의 고유명사류
    import re as _re
    why_txt = trader.get("catalyst", {}).get("why", "")
    hl_words, _seen = [], set()
    for w in _re.findall(r"\b[A-Z][A-Za-z0-9]+\b", why_txt):
        lw = w.lower()
        if len(lw) > 1 and lw not in ("the", "an") and lw not in _seen:
            _seen.add(lw); hl_words.append(lw)
    hl_words = hl_words[:4]

    # 비트 정렬 타임라인(세그먼트 단위, 각 컷=비트 스냅+whoosh)
    TL = scene_timeline(out_dir=out_dir)   # A: narration-구동(narration.json 있으면 씬 확장)
    snapped, durs, total = TL["snapped"], TL["durs"], TL["total"]
    smart_idx = TL["smart_idx"]
    ding_t = round(snapped[TL["result_idx"]] + 1.2, 2)
    cut_times = TL["cut_times"]
    print(f"BGM tempo≈{TL['tempo']} src={TL['src']} | total={total}s | {len(SCENES)} cuts | sector_peers={len(sector_bars)-1}")
    print(f"  ding@{ding_t}s | durs={durs}")

    maxw = T.CANVAS[0] - T.SAFE_ZONE["side"] * 2
    smart_block = _text_block(trader.get("smart_money", ""), maxw, 9,
                              T.SIZES["lg"], 40, 400, 1180, durs[smart_idx])

    import datetime
    def _fmt(iso):
        try:
            return datetime.date.fromisoformat(iso[:10]).strftime("%b %-d, %Y")
        except ValueError:
            return iso
    source = hook.get("source") or trader.get("source") or "247wallst.com"
    try:
        import assets
        sector = assets.sector_for_ticker(ticker)
    except Exception:
        sector = "semiconductor"

    # A2.4: 회사 사진(HQ + product 각각) — 씬별 우선순위 선택(씬1·11=HQ, 씬3=product)
    company_photo_hq = None
    company_photo_product = None
    try:
        import company_photo_fetch as CPF
        photos = CPF.ensure_photos(ticker)
        company_photo_hq = photos.get("HQ")
        company_photo_product = photos.get("product")
    except Exception:
        pass

    ctx = {"ticker": ticker.upper(), "price": price, "trader": trader, "hook": hook,
           "pct": pct, "color": color,
           "data_date": data_date, "article_date": article_date, "chips": chips,
           "series": series, "compare_bars": compare_bars, "sector_bars": sector_bars,
           "hook_block": hook_block, "payoff_block": payoff_block, "smart_block": smart_block,
           "expr_paths": expr_paths, "masc": {}, "source": source, "sector": sector,
           "company_photo_hq": company_photo_hq, "company_photo_product": company_photo_product,
           "article_label": _fmt(article_date), "hl_words": hl_words,
           "sector_title": sector_title, "sector_caption": f"Sector sympathy · {data_date}",
           "sympathy_insight": sympathy_insight, "bubbles": bubbles}

    only = os.environ.get("RENDER_ONLY")
    only_set = set(int(x) for x in only.split(",")) if only else None

    base_bg = T.make_bg().convert("RGBA")
    bg_cache = {}   # scene명 → 배경합성된 RGBA(재사용)

    idx = 0
    for si, seg in enumerate(SCENES):
        if only_set is not None and si not in only_set:
            continue
        dur = durs[si]; scene = seg["scene"]; phase = seg["phase"]
        nframes = max(1, int(dur * FPS))
        fn = SCENE_FN[seg["fn"]]
        # 배경 선택:
        # ① brightnews + PHOTO_BG_SCENES → 회사 사진 풀스크린 배경(FIX4)
        # ② terminal + BG_SCENES → Pexels blur 배경
        # ③ 그 외 → 단색 base_bg
        if T.ACTIVE_THEME == "brightnews" and scene in PHOTO_BG_SCENES:
            pkey = "product" if scene == "catalyst" else "hq"
            photo_path = ctx.get(f"company_photo_{pkey}") or ctx.get("company_photo_hq")
            cached = bg_cache.get(f"photo_{scene}")
            if cached is None:
                if photo_path:
                    cached = _make_photo_bg(base_bg.copy(), photo_path, overlay_alpha=0.55)
                else:
                    cached = base_bg
                bg_cache[f"photo_{scene}"] = cached
            seg_bg = cached
        elif scene in BG_SCENES and T.ACTIVE_THEME != "brightnews":
            cached = bg_cache.get(scene)
            if cached is None:
                cached = C.scene_background(base_bg.copy(), ctx.get("sector", "semiconductor"),
                                            variant=seg["prog"], blur=28, alpha=0.32, darken=0.38)
                bg_cache[scene] = cached
            seg_bg = cached
        else:
            seg_bg = base_bg
        for k in range(nframes):
            t = k / FPS
            img = seg_bg.copy()
            d = ImageDraw.Draw(img)
            _place_mascot(img, ctx, scene, t)
            fn(img, d, t, dur, ctx, phase)
            _draw_scene_thumb(img, ctx, scene)       # STEP2 차트 미니어처
            _draw_photo_card(img, ctx, scene, t)     # A2.4 보조 회사 사진 카드(씬1/3/11)
            _draw_scene_bubble(img, ctx, scene, t)   # Phase6 1.2 말풍선
            frame = _scene_motion(img.convert("RGB"), t, dur, si)
            if seg["fn"] == "risk":
                dx, dy = M.shake(t, 0.15, 12)
                if dx or dy:
                    frame = frame.transform(frame.size, Image.AFFINE, (1, 0, dx, 0, 1, dy))
                frame = _glitch_frame(frame, t, 0.18)
            C.header(frame, date_label, "4:00 PM", seg["prog"], N_LOGICAL)
            _disclaimer(ImageDraw.Draw(frame))
            frame.save(TMP / f"f{idx:05d}.png"); idx += 1

    if only_set is not None:
        print(f"부분 렌더 {sorted(only_set)} → {idx} frames in {TMP}")
        return
    # ding: 결과 카운트업 도착 + payoff 마지막 단어(P1.5 success bell)
    payoff_idx = next(i for i, s in enumerate(SCENES) if s["fn"] == "payoff")
    n_pw = len(ctx["payoff_block"]["words"])
    payoff_bell = round(snapped[payoff_idx] + min(durs[payoff_idx] - 0.1, (n_pw - 1) * 0.16 + 0.22), 2)

    def _post_render_save():
        """H.8: timeline.json + run-level assets_manifest.json 저장 (렌더 완료 후 실제값)."""
        import narration as _N
        import datetime as _dt
        narr_progs = set(_N.NARR_SCENES)
        scenes_out = []
        for prog, span in sorted(TL["spans"].items()):
            start = round(span["start"], 3)
            end = round(span["start"] + span["dur"], 3)
            scenes_out.append({
                "prog": prog,
                "name": span["name"],
                "start": start,
                "end": end,
                "dur": round(span["dur"], 3),
                "has_narration": prog in narr_progs,
            })
        tl_data = {
            "total_duration": TL["total"],
            "tempo_bpm": TL["tempo"],
            "theme": T.ACTIVE_THEME,
            "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
            "scenes": scenes_out,
            "segments": [
                {"seg_idx": i, "fn": s["fn"], "phase": s["phase"], "prog": s["prog"],
                 "start": round(snapped[i], 3), "dur": round(durs[i], 3)}
                for i, s in enumerate(SCENES)
            ],
        }
        # null 방어: 위 값은 모두 실계산값이므로 None 불가; 그래도 검사
        for sc in tl_data["scenes"]:
            assert sc["start"] is not None and sc["end"] is not None, f"timeline null: {sc}"
        assert tl_data["total_duration"] is not None, "timeline total_duration null"
        JU.atomic_write_json(out_dir / "timeline.json", tl_data)

        # run-level assets_manifest: Pexels skip 여부 기록
        bg_info = (
            {"type": "solid_color", "color": T.COLORS["bg_primary"], "pexels_called": False}
            if T.ACTIVE_THEME == "brightnews"
            else {"type": "pexels_blur", "pexels_called": True}
        )
        run_manifest = {"background": bg_info, "theme": T.ACTIVE_THEME}
        JU.atomic_write_json(out_dir / "assets_manifest.json", run_manifest)
        print(f"  ✓ timeline.json + assets_manifest.json → {out_dir}")

        # micro-cut lint (H.8)
        cut_issues = lint_cut_durations(TL)
        if cut_issues:
            print(f"  ⚠ micro-cut lint {len(cut_issues)}건: {cut_issues}")
        else:
            print("  ✓ micro-cut lint PASS")

    # FIX6: 겹침 감지 lint (warn only — raise 아님)
    overlap_result = run_overlap_lint()
    if overlap_result:
        for sc, pairs in overlap_result.items():
            print(f"  ⚠ [overlap-lint] {sc}: {pairs}")
        JU.atomic_write_json(out_dir / "overlap_lint.json",
                             {"overlaps": {k: [list(p) for p in v] for k, v in overlap_result.items()},
                              "warn_count": sum(len(v) for v in overlap_result.values())})
    else:
        print("  ✓ overlap-lint PASS (겹침 없음)")

    # 나레이션 있으면 3레이어 ducking 믹스, 없으면 기존 BGM+SFX
    if (out_dir / "narration.json").exists():
        audio = TMP / "audio_narr.wav"
        if build_narrated_audio(out_dir, total, cut_times, [ding_t, payoff_bell], audio):
            _mux(out_dir / out_name, audio, total)
            _post_render_save()
            print(f"DONE(narrated) → {out_dir/out_name}")
            return
    _build_av(total, cut_times, [ding_t, payoff_bell], out_dir, out_name)
    _post_render_save()


def _sfx():
    wh = TMP / "whoosh.wav"; dg = TMP / "ding.wav"
    if not wh.exists():
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anoisesrc=d=0.4:c=pink:a=0.35",
                        "-af", "highpass=f=250,lowpass=f=5000,afade=t=in:d=0.05,afade=t=out:st=0.18:d=0.22",
                        str(wh)], capture_output=True)
    if not dg.exists():
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=920:duration=0.3",
                        "-af", "afade=t=out:d=0.26", str(dg)], capture_output=True)
    return wh, dg


# dB → 선형 진폭
def _db(x):
    return round(10 ** (x / 20.0), 4)


def build_narrated_audio(out_dir, total, cut_times, ding_times, audio_out,
                         bgm_db=-25, sfx_db=-10, ding_db=-8, duck_db=-8):
    """3레이어 오디오: BGM(−25dB, 나레이션 구간 −8dB ducking+0.3s ramp) + SFX(−10dB) + narration(0dB).
    narration.json(씬 시작/길이) 기반. 반환 audio_out 경로(없으면 None)."""
    out_dir = Path(out_dir)
    manifest = json.loads((out_dir / "narration.json").read_text()) if (out_dir / "narration.json").exists() else {}
    nd = out_dir / "narration"
    wh, dg = _sfx()
    base, duck = _db(bgm_db), _db(bgm_db + duck_db)
    # 나레이션 시작점 = 타임라인 씬 시작(A: narration-구동). +0.2s 오프셋.
    spans = scene_timeline(out_dir=out_dir)["spans"]
    starts = {int(sc): spans.get(int(sc), {}).get("start", 0) + 0.2 for sc in manifest}
    # ducking 볼륨 엔벨로프(나레이션 구간 duck, 0.3s ramp). t 식.
    wins = []
    for sc, s in manifest.items():
        st = starts.get(int(sc)); du = s.get("dur")
        if st is not None and du:
            wins.append((round(st, 3), round(st + du, 3)))
    expr = str(base)
    for (s, e) in wins:   # 구간 내 duck + 진입/이탈 0.3s 선형 ramp
        expr = (f"if(between(t,{s},{e}),{duck},"
                f"if(between(t,{s-0.3},{s}),{base}+({duck}-{base})*(t-{s-0.3})/0.3,"
                f"if(between(t,{e},{e+0.3}),{duck}+({base}-{duck})*(t-{e})/0.3,{expr})))")
    inputs = ["-stream_loop", "-1", "-i", str(BGM)]
    parts = [f"[0:a]atrim=0:{total},volume='{expr}':eval=frame[bg]"]
    labels = ["[bg]"]; n = 1
    for ct in cut_times:                     # whoosh @ 컷
        inputs += ["-i", str(wh)]; ms = int(ct * 1000)
        parts.append(f"[{n}:a]adelay={ms}|{ms},volume={_db(sfx_db)}[w{n}]"); labels.append(f"[w{n}]"); n += 1
    for dt in ding_times:                    # ding/bell
        inputs += ["-i", str(dg)]; ms = int(dt * 1000)
        parts.append(f"[{n}:a]adelay={ms}|{ms},volume={_db(ding_db)}[d{n}]"); labels.append(f"[d{n}]"); n += 1
    n_narr = 0
    for sc, s in sorted(manifest.items(), key=lambda x: int(x[0])):
        wav = nd / s["wav"]
        if not wav.exists():
            continue
        ms = int(round(starts.get(int(sc), 0) * 1000)); du = s.get("dur", 1.0)
        inputs += ["-i", str(wav)]   # A.2: 0.2s 페이드인 / 0.3s 페이드아웃
        parts.append(f"[{n}:a]afade=t=in:d=0.2,afade=t=out:st={max(0,du-0.3):.2f}:d=0.3,"
                     f"adelay={ms}|{ms},volume=1.0[v{n}]"); labels.append(f"[v{n}]"); n += 1; n_narr += 1
    if n_narr == 0:
        return None
    # makeup +10dB: say/BGM 소스가 정규화 안돼 절대레벨이 낮음 → 나레이션을 −3~−8dB 대역으로.
    fc = (";".join(parts) + ";" + "".join(labels) +
          f"amix=inputs={len(labels)}:duration=first:dropout_transition=0:normalize=0,"
          f"volume=10dB,alimiter=limit=0.95,atrim=0:{total}[a]")
    r = subprocess.run(["ffmpeg", "-y", *inputs, "-filter_complex", fc, "-map", "[a]", str(audio_out)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print("NARR AUDIO FAIL:", r.stderr[-400:]); return None
    return audio_out


def remux_audio(video_in, audio_in, out):
    """영상 스트림 복사 + 새 오디오 교체(v5.5: 오디오만 재합성)."""
    r = subprocess.run(["ffmpeg", "-y", "-i", str(video_in), "-i", str(audio_in),
                        "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
                        "-shortest", str(out)], capture_output=True, text=True)
    return r.returncode == 0


def gen_sources_card(ticker="ARM"):
    """B.5: 단독 sources_card.png 생성(영상 외 검증용)."""
    import datetime
    out_dir = sorted((ROOT / "outputs").glob(f"{ticker.upper()}_*"))[-1]
    hook = json.loads((out_dir / "hook.json").read_text())
    src = hook.get("source") or "247wallst.com"
    ad = hook.get("article_date", "")
    try:
        ad = datetime.date.fromisoformat(ad[:10]).strftime("%b %-d, %Y")
    except ValueError:
        pass
    img = T.make_bg().convert("RGBA")
    lines = [("Data", "Yahoo Finance"), ("Catalyst", f"{src} ({ad})"),
             ("Visuals", "Pexels (CC0)"), ("Logos", "Wikimedia Commons (CC-BY-SA)")]
    side = T.SAFE_ZONE["side"]
    C.sources_card(img, lines, (side, 700), width=T.CANVAS[0] - side * 2)
    d = ImageDraw.Draw(img)
    _disclaimer(d)
    out = out_dir / "sources_card.png"
    img.convert("RGB").save(out)
    print(f"sources_card → {out}")
    return out


def make_v5_5(ticker="ARM"):
    """v5 영상 + 나레이션 3레이어 믹스 → short_full_v5_5.mp4 (오디오만 재합성, P0.4)."""
    out_dir = sorted((ROOT / "outputs").glob(f"{ticker.upper()}_*"))[-1]
    TL = scene_timeline()
    ding_t = round(TL["snapped"][TL["result_idx"]] + 1.2, 2)
    payoff_idx = next(i for i, s in enumerate(SCENES) if s["fn"] == "payoff")
    payoff_bell = round(TL["snapped"][payoff_idx] + 1.5, 2)
    audio = TMP / "audio_v55.wav"
    if not build_narrated_audio(out_dir, TL["total"], TL["cut_times"], [ding_t, payoff_bell], audio):
        print("v5.5 오디오 생성 실패"); return
    v5 = out_dir / "short_full_v5.mp4"; out = out_dir / "short_full_v5_5.mp4"
    if remux_audio(v5, audio, out):
        print(f"DONE → {out}")
    else:
        print("remux 실패")


def _mux(out, audio, total):
    """TMP의 PNG 프레임 + 주어진 오디오 → mp4 인코딩."""
    r = subprocess.run(["ffmpeg", "-y", "-framerate", str(FPS), "-i", str(TMP / "f%05d.png"),
                        "-i", str(audio), "-t", str(total), "-c:v", "libx264", "-preset", "medium",
                        "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
                        "-shortest", str(out)], capture_output=True, text=True)
    if r.returncode != 0:
        print("ENCODE FAIL:", r.stderr[-500:])
    return r.returncode == 0


def _build_av(total, cut_times, ding_times, out_dir, out_name="short_full_v2.mp4"):
    wh, dg = _sfx()
    audio = TMP / "audio.wav"
    # BGM이 짧으면 루프(-stream_loop)해서 total 길이 확보. atrim으로 정확히 절단.
    inputs = ["-stream_loop", "-1", "-i", str(BGM)]
    parts = [f"[0:a]atrim=0:{total},volume=0.35[bg]"]
    labels = ["[bg]"]
    n = 1
    for ct in cut_times:
        inputs += ["-i", str(wh)]
        ms = int(ct * 1000)
        parts.append(f"[{n}:a]adelay={ms}|{ms}[w{n}]"); labels.append(f"[w{n}]"); n += 1
    for dt in (ding_times if isinstance(ding_times, (list, tuple)) else [ding_times]):
        inputs += ["-i", str(dg)]
        dms = int(dt * 1000)
        parts.append(f"[{n}:a]adelay={dms}|{dms}[dg{n}]"); labels.append(f"[dg{n}]"); n += 1
    fc = ";".join(parts) + ";" + "".join(labels) + f"amix=inputs={len(labels)}:duration=first:dropout_transition=0:normalize=0,atrim=0:{total}[a]"
    subprocess.run(["ffmpeg", "-y", *inputs, "-filter_complex", fc, "-map", "[a]", str(audio)],
                   capture_output=True)
    out = out_dir / out_name
    r = subprocess.run(["ffmpeg", "-y", "-framerate", str(FPS), "-i", str(TMP / "f%05d.png"),
                        "-i", str(audio), "-t", str(total), "-c:v", "libx264", "-preset", "medium",
                        "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
                        "-shortest", str(out)], capture_output=True, text=True)
    if r.returncode != 0:
        print("ENCODE FAIL:", r.stderr[-700:]); return
    print(f"DONE → {out}")


if __name__ == "__main__":
    render(sys.argv[1] if len(sys.argv) > 1 else "ARM")
