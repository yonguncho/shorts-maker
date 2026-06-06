"""motion_sync.py — BGM 비트 추출 + 컷/자막 비트 스냅 (Phase 4-1).

extract_beats: librosa.beat.beat_track (결과 {audio}.beats.json 캐싱).
              librosa 미설치/실패 시 고정 BPM(110) 그리드로 graceful fallback(로그 명시).
snap_to_beat: 가장 가까운 비트로 스냅(±tolerance), 벗어나면 원시각.
build_timeline: 씬·sub-cut 시작을 비트에 정렬한 타임라인 반환.
"""
from __future__ import annotations
import json
import subprocess
from pathlib import Path

import numpy as np

FALLBACK_BPM = 110.0


def _decode_mono(audio_path: str, sr: int = 22050):
    """ffmpeg 로 오디오 → mono float32 PCM(numpy). librosa.load 대체."""
    p = subprocess.run(["ffmpeg", "-v", "error", "-i", str(audio_path), "-ac", "1",
                        "-ar", str(sr), "-f", "f32le", "-"], capture_output=True)
    if p.returncode != 0 or not p.stdout:
        return None, sr
    return np.frombuffer(p.stdout, dtype=np.float32), sr


def _detect_beats_numpy(audio_path: str):
    """numpy STFT 스펙트럴 플럭스 onset + 자기상관 tempo → 비트 그리드(phase 정렬).
    librosa/numba 없이 실제 오디오에서 tempo 검출. 반환 (beats, bpm) or (None, None)."""
    y, sr = _decode_mono(audio_path)
    if y is None or len(y) < sr:
        return None, None
    hop, win = 512, 1024
    n = 1 + (len(y) - win) // hop
    if n < 8:
        return None, None
    w = np.hanning(win).astype(np.float32)
    mags = np.empty((n, win // 2 + 1), dtype=np.float32)
    for i in range(n):
        seg = y[i * hop:i * hop + win] * w
        mags[i] = np.abs(np.fft.rfft(seg))
    flux = np.maximum(0, np.diff(mags, axis=0)).sum(axis=1)   # 양의 스펙트럴 플럭스
    env = flux - flux.mean()
    fps = sr / hop
    ac = np.correlate(env, env, "full")[len(env) - 1:]
    lo, hi = int(fps * 60 / 180), int(fps * 60 / 60)          # BPM 60~180
    if hi <= lo or hi >= len(ac):
        return None, None
    best = int(np.argmax(ac[lo:hi])) + lo
    bpm = 60.0 * fps / best
    phase = int(np.argmax(env[:best])) if best > 0 else 0     # 첫 비트 위상
    beats, k = [], 0
    while phase + k * best < len(env):
        beats.append(round((phase + k * best) * hop / sr, 3))
        k += 1
    return beats, round(bpm, 1)


def extract_beats(audio_path: str, fallback_bpm: float = FALLBACK_BPM, duration: float = 60.0):
    """[beat_times] 반환 + 캐싱. (tempo, beats, source) 형태가 아니라 list[float]."""
    cache = Path(str(audio_path) + ".beats.json")
    if cache.exists():
        try:
            d = json.loads(cache.read_text())
            return d["beats"], d.get("tempo"), d.get("source", "cache")
        except Exception:
            pass
    tempo, beats, source = fallback_bpm, None, "fallback_grid"
    # 1순위: librosa(설치돼 있으면). 이 venv 는 numba/llvmlite 빌드불가라 보통 미설치.
    try:
        import librosa
        y, sr = librosa.load(audio_path, mono=True)
        tempo, frames = librosa.beat.beat_track(y=y, sr=sr, units="frames")
        beats = [round(float(t), 3) for t in librosa.frames_to_time(frames, sr=sr)]
        tempo = round(float(tempo), 1) if hasattr(tempo, "__float__") else float(tempo[0])
        source = "librosa"
    except Exception:
        beats = None
    # 2순위: numpy FFT onset+autocorrelation (실제 오디오 분석, numba 불필요)
    if not beats:
        try:
            b, bpm = _detect_beats_numpy(audio_path)
            if b and len(b) > 4:
                beats, tempo, source = b, bpm, "numpy_onset"
        except Exception:
            beats = None
    if not beats:
        # 고정 BPM 그리드
        step = 60.0 / fallback_bpm
        n = int(duration / step)
        beats = [round(i * step, 3) for i in range(n + 1)]
        source = "fallback_grid"
    try:
        cache.write_text(json.dumps({"tempo": tempo, "beats": beats, "source": source}))
    except Exception:
        pass
    return beats, tempo, source


def snap_to_beat(target_time: float, beat_times, tolerance: float = 0.15) -> float:
    if not beat_times:
        return target_time
    nearest = min(beat_times, key=lambda b: abs(b - target_time))
    return round(nearest, 3) if abs(nearest - target_time) <= tolerance else round(target_time, 3)


def build_timeline(scenes, bgm_path, tolerance: float = 0.15):
    """scenes: [{type, dur, content}] (sub-cut 포함). 시작 시각을 비트에 스냅.
    반환: [{type, planned_start, snapped_start, end, content}]."""
    beats, tempo, source = extract_beats(bgm_path)
    out, t = [], 0.0
    for sc in scenes:
        planned = t
        snapped = snap_to_beat(planned, beats, tolerance)
        dur = sc.get("dur", 3.0)
        out.append({"type": sc.get("type", "scene"), "planned_start": round(planned, 3),
                    "snapped_start": snapped, "end": round(snapped + dur, 3),
                    "content": sc.get("content", "")})
        t = planned + dur   # 다음 씬은 계획상 누적(스냅은 시각효과용, 길이는 보존)
    return out, {"tempo": tempo, "source": source, "n_beats": len(beats)}


if __name__ == "__main__":
    import sys
    bgm = sys.argv[1] if len(sys.argv) > 1 else "assets/bgm/test_track.mp3"
    beats, tempo, source = extract_beats(bgm)
    print(f"BGM: {bgm}\n  tempo≈{tempo} BPM | beats={len(beats)} | source={source}")
    print(f"  first beats: {beats[:8]}")
    # 가상 12씬 타임라인
    durs = [2, 3, 5, 4, 5, 4, 5, 5, 5, 4, 3, 3]
    scenes = [{"type": f"scene{i+1}", "dur": d, "content": f"s{i+1}"} for i, d in enumerate(durs)]
    tl, meta = build_timeline(scenes, bgm)
    print(f"\nTimeline ({meta}):")
    deltas = []
    for c in tl:
        delta = abs(c["snapped_start"] - c["planned_start"])
        deltas.append(delta)
        print(f"  {c['type']:8} planned={c['planned_start']:6.3f} snapped={c['snapped_start']:6.3f} Δ={delta:.3f} end={c['end']:.3f}")
    print(f"\nsnap 보정량: avg={sum(deltas)/len(deltas):.3f}s max={max(deltas):.3f}s")
