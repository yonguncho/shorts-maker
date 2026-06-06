"""mascot.py — 마스코트 누끼 + 표정 매핑 (Phase 4-2).

clean.png: mascot/raw.png 가 있고 rembg 설치돼 있으면 누끼, 아니면 기존 투명 마스코트 재사용.
표정 5종(shocked/analysis/warning/cheer/thinking)은 기존 포즈셋(assets/mascot/poses)에서 매핑 복사.
get_expression_for_scene: 시나리오 → 표정 경로.
"""
from __future__ import annotations
import shutil
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
BASE = Path(__file__).resolve().parent / "mascot"
BASE.mkdir(parents=True, exist_ok=True)
# 벡터 마스코트(후보1 채택, 2026-06-03)를 정본으로 사용. 표정 포즈는 벡터판 생성 전까지
# poses_vector(미존재)→clean 폴백으로 일관 적용. 구 3D poses 디렉터리는 보존(미사용).
SRC_POSES = ROOT / "assets" / "mascot" / "poses_vector"
CLEAN_SRC = ROOT / "assets" / "mascot" / "trader_cho_vector.png"

# 표정 → 포즈 파일 매핑. Phase6: pointing/laughing/tilting 추가(raw 없으면 폴백).
# raw_{name}.png(poses_vector_raw) 있으면 그걸로, 없으면 가장 가까운 기존 포즈로 폴백.
EXPR_SRC = {"shocked": "surprise", "analysis": "point", "warning": "warn",
            "cheer": "celebrate", "thinking": "think",
            "pointing": "point", "laughing": "celebrate", "tilting": "think"}
EXPRESSIONS = list(EXPR_SRC.keys())


def _placeholder(path):
    img = Image.new("RGBA", (400, 520), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((60, 60, 340, 460), radius=40, fill=(26, 33, 40, 255),
                        outline=(122, 162, 247, 255), width=6)
    d.text((200, 260), "TC", fill=(122, 162, 247, 255), anchor="mm")
    img.save(path)


def _rembg_clean(raw, out) -> bool:
    try:
        from rembg import remove
        out_bytes = remove(Path(raw).read_bytes())
        Path(out).write_bytes(out_bytes)
        return True
    except Exception:
        return False


def ensure():
    """clean.png + 표정 5종 준비. 반환: {expr: path}."""
    clean = BASE / "clean.png"
    raw = BASE / "raw.png"
    if raw.exists() and _rembg_clean(raw, clean):
        pass  # rembg 누끼 성공
    elif CLEAN_SRC.exists():
        shutil.copy(CLEAN_SRC, clean)   # 기존 투명 마스코트 재사용
    else:
        _placeholder(clean)
    out = {}
    for expr, src in EXPR_SRC.items():
        dst = BASE / f"{expr}.png"
        srcp = SRC_POSES / f"{src}.png"
        if srcp.exists():
            shutil.copy(srcp, dst)
        elif clean.exists():
            shutil.copy(clean, dst)
        else:
            _placeholder(dst)
        out[expr] = dst
    return out


# 씬별 마스코트 (표정, 화면폭 대비 비율, 위치). FIX2: 전면 크기 상향.
SCENE_MASCOT = {        # FIX2: 마스코트 전면 크기 상향 + compare 씬 활성화
    "opening":    (None,        0.0,  "none"),            # STEP5: s_opening이 직접 그림(0.55)
    "hook":       ("thinking",  0.42, "left_third"),     # 0.40 → 0.42
    "result":     ("laughing",  0.0,  "none"),
    "catalyst":   ("shocked",   0.38, "right_center"),   # 0.35 → 0.38
    "durability": ("analysis",  0.32, "br"),             # 0.26 → 0.32
    "chart":      ("pointing",  0.22, "bottom_left"),    # 0.25 → 0.22 (차트 방해 최소화)
    "volume":     ("analysis",  0.32, "right_bottom"),   # 0.30 → 0.32
    "compare":    ("analysis",  0.28, "br"),             # 0.0 → 0.28 활성화
    "related":    ("analysis",  0.20, "right_low"),      # 0.16 → 0.20, br → right_low
    "smart":      ("thinking",  0.28, "right_center"),
    "risk":       ("warning",   0.38, "center"),         # 0.40 → 0.38
    "payoff":     ("cheer",     0.40, "left_third"),     # 0.35 → 0.40
    "closing":    ("cheer",     0.58, "center_bottom"),  # 0.50 → 0.58
}


def get_size_position_for_scene(scene_id: str):
    """반환 (expr, width_frac, pos_code). width_frac=0 이면 마스코트 없음."""
    return SCENE_MASCOT.get(scene_id, ("thinking", 0.16, "br"))


def get_expression_for_scene(catalyst: dict, surprise, scene_type: str) -> Path:
    cat = catalyst or {}
    if cat.get("durability") == "TEMPORARY":
        expr = "warning"
    elif cat.get("type") == "earnings_beat":
        expr = "cheer"
    elif surprise and scene_type == "hook":
        expr = "shocked"
    elif scene_type in ("chart", "analysis"):
        expr = "analysis"
    elif scene_type in ("hook", "thinking"):
        expr = "thinking"
    elif scene_type == "closing":
        expr = "cheer"
    else:
        expr = "thinking"
    p = BASE / f"{expr}.png"
    return p if p.exists() else (BASE / "clean.png")


if __name__ == "__main__":
    paths = ensure()
    print("clean.png +", len(paths), "expressions:", {k: v.name for k, v in paths.items()})
    # 매핑 데모
    for st in ["hook", "chart", "closing"]:
        print(f"  scene={st} →", get_expression_for_scene({"type": "product", "durability": "TEMPORARY"}, "x", st).name)
