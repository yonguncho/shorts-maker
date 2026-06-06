"""motion.py — 역동성 엔진 (Phase 4-3, 핵심 3종 + 유틸).

moviepy 2.x API 불안정 → 프레임 단위(PIL) 변환 값으로 제공. compose_short 가 매 프레임에 적용.
- pop_in: scale 0.3→1.3→0.95→1.0 + alpha (0.3s)
- ken_burns: 5종 순환 (zoom_in/out/left/right/diagonal) → (scale, dx, dy)
- idle_motion: sin 흔들기 → dy
- count_up: 0→target 카운트업 값
"""
from __future__ import annotations
import math

KEN_PATTERNS = ["zoom_in", "zoom_out", "pan_left", "pan_right", "pan_diagonal"]


def ease_out(t: float) -> float:
    """cubic-bezier(0.4,0,0.2,1) 근사."""
    return 1 - (1 - max(0.0, min(1.0, t))) ** 3


def pop_in(t: float, dur: float = 0.3) -> tuple[float, float]:
    """반환 (scale, alpha). t>=dur 면 (1.0, 1.0)."""
    if t >= dur:
        return 1.0, 1.0
    p = t / dur
    # 키프레임 0→0.3, 0.4→1.3, 0.7→0.95, 1.0→1.0
    if p < 0.4:
        scale = 0.3 + (1.3 - 0.3) * (p / 0.4)
    elif p < 0.7:
        scale = 1.3 + (0.95 - 1.3) * ((p - 0.4) / 0.3)
    else:
        scale = 0.95 + (1.0 - 0.95) * ((p - 0.7) / 0.3)
    alpha = min(1.0, p / 0.3)
    return scale, alpha


def ken_burns(t: float, dur: float, pattern_idx: int, amount: float = 0.08):
    """반환 (scale, dx_frac, dy_frac). dx/dy 는 캔버스 대비 비율."""
    pat = KEN_PATTERNS[pattern_idx % len(KEN_PATTERNS)]
    p = ease_out(t / dur) if dur > 0 else 0.0
    if pat == "zoom_in":
        return 1.0 + amount * p, 0.0, 0.0
    if pat == "zoom_out":
        return 1.0 + amount * (1 - p), 0.0, 0.0
    if pat == "pan_left":
        return 1.0 + amount, -amount * 0.5 * p, 0.0
    if pat == "pan_right":
        return 1.0 + amount, amount * 0.5 * p, 0.0
    return 1.0 + amount, amount * 0.4 * p, -amount * 0.4 * p   # diagonal


def idle_offset(t: float, amplitude: float = 8.0, period: float = 2.0) -> float:
    return amplitude * math.sin(2 * math.pi * t / period)


def count_up(t: float, target: float, dur: float = 1.2) -> float:
    if t >= dur:
        return target
    return round(target * ease_out(t / dur), 2)


def zoom_punch(t: float, dur: float = 0.2, peak: float = 1.06) -> float:
    """씬 시작 줌펀치 scale (1→peak→1)."""
    if t >= dur:
        return 1.0
    p = t / dur
    return 1.0 + (peak - 1.0) * math.sin(math.pi * p)


# ── 양념 모션(L3.6: shake 영상당 ≤3, glitch ≤2) ─────────────
def shake(t: float, dur: float = 0.15, intensity: float = 14.0) -> tuple[float, float]:
    """감쇠 흔들기 → (dx, dy). 리스크 씬 진입 등 강조. t>=dur 면 (0,0)."""
    if t >= dur or dur <= 0:
        return 0.0, 0.0
    decay = 1.0 - t / dur
    a = intensity * decay
    return (a * math.sin(t * 90.0), a * 0.6 * math.cos(t * 110.0))


def typewriter(text: str, t: float, cps: float = 28.0) -> str:
    """t초까지 노출된 부분 문자열(초당 cps자). 헤드라인/스마트리드 타이핑."""
    n = int(max(0.0, t) * cps)
    return text[:n]


def typewriter_done(text: str, cps: float = 28.0) -> float:
    return len(text or "") / cps


def glitch(t: float, dur: float = 0.18, max_shift: int = 10):
    """RGB 채널 시프트 글리치 → (active, shift_px, slice_y_frac). 양념 한정."""
    if t >= dur or dur <= 0:
        return False, 0, 0.0
    p = t / dur
    shift = int(max_shift * (1 - p) * (1 if int(t * 60) % 2 == 0 else -1))
    return True, shift, (t * 7.0) % 1.0


def mascot_react(kind: str, t: float):
    """씬 시작 반응 모션(C.3) → (dx, dy) 픽셀 오프셋. 0.35~0.5s 내 1회."""
    if kind == "shock_jump" and t < 0.35:
        p = t / 0.35
        return (8.0 * math.sin(t * 70) * (1 - p), -16.0 * math.sin(math.pi * p))
    if kind == "warn_shake" and t < 0.4:
        p = t / 0.4
        return (12.0 * math.sin(t * 55) * (1 - p), 0.0)
    if kind == "point_chart" and t < 0.5:
        p = ease_out(t / 0.5)
        return (12.0 * p, -4.0 * p)
    if kind == "cheer_arms" and t < 0.5:
        p = ease_out(t / 0.5)
        return (0.0, -12.0 * p)
    if kind == "tilt_question" and t < 0.45:   # 고개 갸웃(좌우 흔들 후 정지)
        p = t / 0.45
        return (7.0 * math.sin(math.pi * p), 0.0)
    return (0.0, 0.0)


def talking_motion(t: float, active_start: float, active_dur: float, amplitude: float = 4.0):
    """말풍선 활성 구간 동안 sin 보빙(말하는 호흡) → dy. period 0.3s. 임시 입모양 대체."""
    if t < active_start or t > active_start + active_dur:
        return 0.0
    return amplitude * math.sin(2 * math.pi * (t - active_start) / 0.3)


def reveal_fraction(t: float, dur: float, ease: bool = True) -> float:
    """0→1 진행률(차트 라인 드로잉·바 필 공용)."""
    if dur <= 0:
        return 1.0
    p = max(0.0, min(1.0, t / dur))
    return ease_out(p) if ease else p
