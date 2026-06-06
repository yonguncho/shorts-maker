"""stage08 — ⑧ 최종 영상 검증 (QA_mac).

입력 : state/video_render.json   (stage07 — 산출 영상 경로/메타)
       state/script.json         (stage04 — 목표 길이/비트)
산출물: state/qa_video.json       (항목별 PASS/FAIL + verdict)

검증 항목(ffprobe 기반, 결정론):
  1) file        — 파일 존재·비어있지 않음
  2) dimensions  — 1080×1920 세로
  3) duration    — script 총 길이와 ±tol
  4) video_codec — h264 / yuv420p (플랫폼 호환)
  5) audio       — 오디오 스트림 존재(무음 트랙; 플랫폼 호환)
  6) integrity   — 디코드 오류 없이 끝까지 재생 가능(ffmpeg null 디코드)

verdict=fail 이면 rc!=0 → ⑨ 게시 게이트로 진행하지 않음.
실행: .venv/bin/python -m src.stages.stage08_qa_video
"""
from __future__ import annotations
import subprocess

from ..common import read_json, write_json_atomic, log, utc_now, STATE_DIR, ROOT

VIDEO_META = STATE_DIR / "video_render.json"
SCRIPT_PATH = STATE_DIR / "script.json"
OUT_PATH = STATE_DIR / "qa_video.json"

EXP_W, EXP_H = 1080, 1920
DURATION_TOL = 1.0


def _ffprobe(path) -> dict:
    p = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration,size:stream=index,codec_type,codec_name,width,height,pix_fmt",
         "-of", "json", str(path)],
        capture_output=True, text=True)
    import json
    try:
        return json.loads(p.stdout)
    except json.JSONDecodeError:
        return {}


def main() -> int:
    log("INFO", "=== STAGE ⑧ 최종 영상 검증 시작 ===", "stage08")
    vmeta = read_json(VIDEO_META, default=None)
    if not vmeta or not vmeta.get("video"):
        log("ERROR", f"입력 없음: {VIDEO_META} (stage07 먼저 실행 필요)", "stage08")
        return 2
    script = read_json(SCRIPT_PATH, default={}) or {}
    target = round(sum(b.get("duration_sec", 0) for b in script.get("beats", [])), 1) \
        or vmeta.get("target_sec", 45.0)

    video = ROOT / vmeta["video"]
    checks = []

    # 1) file
    exists = video.exists() and video.stat().st_size > 0
    size = video.stat().st_size if video.exists() else 0
    checks.append({"name": "file", "status": "pass" if exists else "fail",
                   "detail": f"{video.name} {size}B" if exists else "파일 없음/빈 파일"})
    if not exists:
        return _finish(checks, script, 4)

    probe = _ffprobe(video)
    fmt = probe.get("format", {})
    streams = probe.get("streams", [])
    vid = next((s for s in streams if s.get("codec_type") == "video"), {})
    aud = next((s for s in streams if s.get("codec_type") == "audio"), {})

    # 2) dimensions
    w, h = vid.get("width"), vid.get("height")
    okdim = (w, h) == (EXP_W, EXP_H)
    checks.append({"name": "dimensions", "status": "pass" if okdim else "fail",
                   "detail": f"{w}x{h}" + ("" if okdim else f" ≠ {EXP_W}x{EXP_H}")})

    # 3) duration
    dur = round(float(fmt.get("duration", 0)), 1)
    okdur = abs(dur - target) <= DURATION_TOL
    checks.append({"name": "duration", "status": "pass" if okdur else "fail",
                   "detail": f"{dur}s" + ("" if okdur else f" ≠ 목표 {target}s(±{DURATION_TOL})")})

    # 4) video codec
    okcodec = vid.get("codec_name") == "h264" and vid.get("pix_fmt") == "yuv420p"
    checks.append({"name": "video_codec", "status": "pass" if okcodec else "fail",
                   "detail": f"{vid.get('codec_name')}/{vid.get('pix_fmt')}"})

    # 5) audio stream
    okaud = bool(aud)
    checks.append({"name": "audio", "status": "pass" if okaud else "warn",
                   "detail": f"{aud.get('codec_name')}(무음 트랙)" if okaud else "오디오 스트림 없음"})

    # 6) integrity — 끝까지 디코드
    dec = subprocess.run(["ffmpeg", "-v", "error", "-i", str(video), "-f", "null", "-"],
                         capture_output=True, text=True)
    okint = dec.returncode == 0 and not dec.stderr.strip()
    checks.append({"name": "integrity", "status": "pass" if okint else "fail",
                   "detail": "디코드 오류 없음" if okint else f"디코드 오류: {dec.stderr[-200:]}"})

    fails = [c for c in checks if c["status"] == "fail"]
    return _finish(checks, script, 4 if fails else 0)


def _finish(checks: list, script: dict, rc: int) -> int:
    fails = [c for c in checks if c["status"] == "fail"]
    warns = [c for c in checks if c["status"] == "warn"]
    verdict = "fail" if fails else "pass"
    out = {
        "schema_version": "1.0", "pipeline_id": "shorts_maker", "machine": "mac",
        "stage": 8, "agent": "QA_mac", "generated_utc": utc_now(),
        "date": script.get("date"), "verdict": verdict, "checks": checks,
        "summary": {"total": len(checks), "fail": len(fails), "warn": len(warns),
                    "pass": len(checks) - len(fails) - len(warns)},
    }
    write_json_atomic(OUT_PATH, out)
    for c in checks:
        lvl = "ERROR" if c["status"] == "fail" else ("WARN" if c["status"] == "warn" else "INFO")
        log(lvl, f"[{c['status'].upper()}] {c['name']}: {c['detail']}", "stage08")
    if verdict == "fail":
        log("ERROR", f"=== STAGE ⑧ FAIL: {len(fails)}개 검증 실패 → 게시 게이트로 진행 안 함 ===", "stage08")
    else:
        log("INFO", f"=== STAGE ⑧ PASS: {len(checks)}개 통과(warn={len(warns)}) → ⑨ 게이트 준비 ===", "stage08")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
