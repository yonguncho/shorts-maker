"""stage07 — ⑦ 영상 합성 (Editor).

입력 : state/script.json         (stage04 — 비트·자막·타임코드·chart_cue)
       state/chart_render.json   (stage06 — 차트 id→PNG)
산출물: output/ready_for_review/short_<date>.mp4   (1080×1920 세로, 무음, 자막 번인)
        state/video_render.json

설계(사용자 확정 2026-06-01: 무음):
  - 비트마다 해당 차트 PNG 를 배경으로, 하단 여백에 자막을 PIL 로 구워 프레임 생성
    (ffmpeg drawtext 이스케이프 회피, 자막 스타일 완전 제어).
  - ffmpeg concat 데먹서로 비트 길이만큼 이어붙여 30fps CFR 인코딩. 오디오는 무음 AAC 트랙
    (플랫폼 호환). BGM 은 게시 전 수동 추가(설계 결정).

실행: .venv/bin/python -m src.stages.stage07_video_render
"""
from __future__ import annotations
import subprocess
import textwrap

import matplotlib.font_manager as fm
from PIL import Image, ImageDraw, ImageFont

from ..common import read_json, write_json_atomic, log, utc_now, OUTPUT_DIR, STATE_DIR, ROOT

SCRIPT_PATH = STATE_DIR / "script.json"
CHART_PATH = STATE_DIR / "chart_render.json"
ASSETS_DIR = OUTPUT_DIR / "assets"
FRAMES_DIR = ASSETS_DIR / "frames"
REVIEW_DIR = OUTPUT_DIR / "ready_for_review"
OUT_JSON = STATE_DIR / "video_render.json"

W, H, FPS = 1080, 1920, 30
BG = (11, 13, 16)            # #0b0d10
FG = (230, 237, 243)
SUB_BAND_TOP = 1360          # 자막 밴드 시작 y(차트 하단 여백)
WRAP_CHARS = 26
LINE_PX = 70
FONT_PX = 50

_FONT = fm.findfont("DejaVu Sans:bold")


def _chart_index(chart_doc: dict) -> dict:
    return {c["id"]: c for c in chart_doc.get("charts", [])}


def _cue_id(cue) -> str | None:
    if not cue:
        return None
    return f"{cue['type']}_{'-'.join(cue.get('symbols') or [])}"


def compose_frame(beat: dict, charts: dict, idx: int) -> str:
    """차트 배경 + 자막 번인 프레임 PNG 생성, 경로 반환."""
    cid = _cue_id(beat.get("chart_cue"))
    chart = charts.get(cid) if cid else None
    if chart:
        img = Image.open(ROOT / chart["file"]).convert("RGB").resize((W, H))
    else:
        img = Image.new("RGB", (W, H), BG)   # closer 등 차트 없는 비트
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(_FONT, FONT_PX)

    lines = []
    for para in (beat.get("subtitle", "") or "").split("\n"):
        lines.extend(textwrap.wrap(para, WRAP_CHARS) or [""])
    if len(lines) > 3:                      # 4줄 이상이면 3줄로 줄이고 말줄임 표기(정직)
        lines = lines[:3]
        lines[-1] = lines[-1].rstrip(".,;: ") + "…"

    # 자막 밴드 가독성용 반투명 스트립
    block_h = len(lines) * LINE_PX + 40
    y0 = SUB_BAND_TOP
    strip = Image.new("RGBA", (W, block_h), (0, 0, 0, 130))
    img.paste(Image.new("RGB", (W, block_h), (5, 6, 8)), (0, y0),
              strip.split()[3])

    y = y0 + 20
    for ln in lines:
        bb = draw.textbbox((0, 0), ln, font=font)
        draw.text(((W - (bb[2] - bb[0])) / 2, y), ln, font=font, fill=FG)
        y += LINE_PX

    FRAMES_DIR.mkdir(parents=True, exist_ok=True)
    path = FRAMES_DIR / f"frame_{idx:02d}.png"
    img.save(path)
    return str(path)


def main() -> int:
    log("INFO", "=== STAGE ⑦ 영상 합성 시작 ===", "stage07")
    script = read_json(SCRIPT_PATH, default=None)
    chart_doc = read_json(CHART_PATH, default=None)
    if not script or not script.get("beats"):
        log("ERROR", f"입력 없음/비트 없음: {SCRIPT_PATH}", "stage07")
        return 2
    if not chart_doc:
        log("ERROR", f"차트 없음: {CHART_PATH} (stage06 먼저 실행 필요)", "stage07")
        return 2
    charts = _chart_index(chart_doc)
    beats = script["beats"]

    # 1) 프레임 합성 + concat 리스트
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    lines = []
    for i, b in enumerate(beats, 1):
        fpath = compose_frame(b, charts, i)
        lines.append(f"file '{fpath}'")
        lines.append(f"duration {b.get('duration_sec', 3)}")
    lines.append(f"file '{compose_frame(beats[-1], charts, len(beats))}'")  # concat 데먹서 마지막 프레임 반복
    list_path = ASSETS_DIR / "concat_list.txt"
    list_path.write_text("\n".join(lines), encoding="utf-8")

    # 2) ffmpeg 인코딩 (무음 AAC 트랙 + yuv420p h264)
    date = script.get("date") or "out"
    out_mp4 = REVIEW_DIR / f"short_{date}.mp4"
    total = round(sum(b.get("duration_sec", 0) for b in beats), 1)
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", str(list_path),
        "-f", "lavfi", "-t", str(total), "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-vf", f"fps={FPS},format=yuv420p",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-c:a", "aac", "-b:a", "128k", "-shortest",
        str(out_mp4),
    ]
    log("INFO", f"ffmpeg 인코딩: {len(beats)}비트 → {out_mp4.name} (목표 {total}s)", "stage07")
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
    if p.returncode != 0:
        log("ERROR", f"ffmpeg 실패 rc={p.returncode}: {p.stderr[-400:]}", "stage07")
        return 3

    # 3) 검증: 실제 길이/해상도
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "format=duration:stream=width,height",
         "-of", "default=noprint_wrappers=1", str(out_mp4)],
        capture_output=True, text=True)
    info = dict(l.split("=", 1) for l in probe.stdout.splitlines() if "=" in l)
    dur = round(float(info.get("duration", 0)), 1)
    w, h = int(info.get("width", 0)), int(info.get("height", 0))
    ok_dim = (w, h) == (W, H)
    ok_dur = abs(dur - total) <= 1.0
    if not (ok_dim and ok_dur):
        log("WARN", f"검증 경고: {w}x{h} dur={dur}s (목표 {W}x{H} {total}s)", "stage07")

    out = {
        "schema_version": "1.0", "pipeline_id": "shorts_maker", "machine": "mac",
        "stage": 7, "agent": "Editor", "generated_utc": utc_now(), "date": script.get("date"),
        "video": str(out_mp4.relative_to(ROOT)), "dimensions": [w, h],
        "duration_sec": dur, "target_sec": total, "fps": FPS, "audio": "silent",
        "beats": len(beats), "bgm_note": "BGM 미포함 — 게시 전 수동 추가(설계 결정)",
        "verified": {"dimensions_ok": ok_dim, "duration_ok": ok_dur},
    }
    write_json_atomic(OUT_JSON, out)
    log("INFO", f"=== STAGE ⑦ 완료: {out_mp4.name} {w}x{h} {dur}s "
                f"(dim_ok={ok_dim} dur_ok={ok_dur}) ===", "stage07")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
