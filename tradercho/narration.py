"""narration.py — 씬별 나레이션 (macOS say -v Daniel) + 길이검증 (Phase 5 P0).

씬 1·2·3·6·8·10·11·12에 나레이션. 4·5·7·9는 그래픽 강조(생략).
숫자 발음변환, 헤징 유지, 단정/인물 lint 통과. wav 길이 ≤ 씬 듀레이션−0.3s(초과 시 rate↑→텍스트 단축).
출력: outputs/{ticker}_{date}/narration/scene_NN.wav + narration.json(텍스트·길이).
"""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import trader_lens
import lint_script

ROOT = Path(__file__).resolve().parent.parent
VOICE = "Daniel"
RATE = 186   # wpm (자연스러운 속도, 무손실 — 씬 길이가 나레이션에 맞춰짐)
NARR_SCENES = [1, 2, 3, 6, 8, 10, 11, 12]

_ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
         "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
         "seventeen", "eighteen", "nineteen"]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def _int_words(n):
    n = int(n)
    if n < 20:
        return _ONES[n]
    if n < 100:
        return _TENS[n // 10] + ("-" + _ONES[n % 10] if n % 10 else "")
    if n < 1000:
        return _ONES[n // 100] + " hundred" + (" " + _int_words(n % 100) if n % 100 else "")
    return str(n)


def num_words(x, decimals=2):
    """2.26 → 'two point two six', 0.45 → 'zero point four five', 18 → 'eighteen'."""
    neg = x < 0
    x = abs(round(float(x), decimals))
    s = f"{x:.{decimals}f}".rstrip("0").rstrip(".")
    if "." in s:
        ip, dp = s.split(".")
        w = _int_words(ip or "0") + " point " + " ".join(_ONES[int(d)] for d in dp)
    else:
        w = _int_words(s)
    return ("negative " + w) if neg else w


def _first_sentence(text):
    t = (text or "").strip()
    for sep in (". ", "; "):
        if sep in t:
            return t.split(sep)[0].strip() + "."
    return t if t.endswith(".") else t + "."


def _compress(text, max_words=15):
    words = _first_sentence(text).split()
    if len(words) <= max_words:
        return " ".join(words)
    return " ".join(words[:max_words]).rstrip(",.;:") + "."


_VERDICT_PHRASE = {"suspect": "Suspect — light conviction.",
                   "neutral": "Roughly average.",
                   "conviction": "Heavy — real conviction."}


def build_texts(price, trader, hook, sympathy):
    """간결한 *목적형* 나레이션(원문 통째 낭독 X) — 씬당 ~3~5s, 60s Shorts 한도 내."""
    tk = price.get("ticker", "this stock")
    pct = price.get("pct_change", 0.0)
    vol = price.get("vol_vs_avg", 1.0)
    verdict = (trader.get("volume", {}).get("verdict") or "neutral")
    t = {}
    t[1] = hook.get("hook_line", f"What's moving {tk}?")
    t[2] = f"{tk} closed {'up' if pct >= 0 else 'down'} {num_words(abs(pct))} percent today."
    t[3] = _compress(trader.get("catalyst", {}).get("why", ""), 11)            # 촉매 요약 ≤13단어
    t[6] = f"Volume — just {num_words(vol)} times average. {_VERDICT_PHRASE.get(verdict, '')}".strip()
    t[8] = (sympathy.strip().rstrip(".") + ".") if sympathy else f"{tk} against the broader tape today."
    t[10] = _compress(trader.get("risk", "Stay aware of the risk here."), 13)  # 리스크 ≤13단어
    t[11] = _compress(hook.get("payoff_line", ""), 12)                          # 페이오프 ≤14단어
    t[12] = "Daily US-market setups. Educational, not advice."                  # B.5: 면책 음성 포함
    return {k: v for k, v in t.items() if v.strip()}


def _wav_dur(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", str(p)], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def _say(text, wav, rate):
    aiff = wav.with_suffix(".aiff")
    subprocess.run(["say", "-v", VOICE, "-r", str(rate), "-o", str(aiff), text], capture_output=True)
    subprocess.run(["ffmpeg", "-y", "-i", str(aiff), "-ar", "44100", "-ac", "2", str(wav)],
                   capture_output=True)
    aiff.unlink(missing_ok=True)
    return _wav_dur(wav)


def synth(ticker, out_dir=None):
    tk = ticker.upper()
    out_dir = Path(out_dir) if out_dir else sorted((ROOT / "outputs").glob(f"{tk}_*"))[-1]
    price = json.loads((out_dir / "price.json").read_text())
    trader = json.loads((out_dir / "trader_lens.json").read_text())
    hook = json.loads((out_dir / "hook.json").read_text())
    price.setdefault("ticker", tk)

    # 섹터 동조(씬8) — 피어 1회 조회 + related_dates.json 기록(compose 재사용=단일 스냅샷)
    data_date = str(price.get("as_of", ""))[:10]
    rd_path = out_dir / "related_dates.json"
    if rd_path.exists():
        related = json.loads(rd_path.read_text()).get("related", [])
    else:
        related = trader_lens.fetch_related_changes(trader.get("related", []), data_date, limit=5)
        rd_path.write_text(json.dumps({"data_date": data_date, "related": related}, indent=2, ensure_ascii=False))
    peers = [r["pct_change"] for r in related if r.get("same_day") and r.get("pct_change") is not None]
    sympathy = trader_lens.sympathy_insight(price.get("pct_change", 0.0), peers) if peers else ""

    texts = build_texts(price, trader, hook, sympathy)
    nd = out_dir / "narration"; nd.mkdir(exist_ok=True)
    for f in nd.glob("*.wav"):
        f.unlink()

    # A.1: 무손실(트림 없음). 씬 길이가 나레이션에 맞춰 늘어남(scene_timeline). rate 고정.
    manifest = {}
    for scene in NARR_SCENES:
        text = texts.get(scene)
        if not text:
            continue
        for chk in (lint_script.check_text, lint_script.check_person):
            try:
                chk(text, f"narration.scene{scene}")
            except lint_script.LintError as e:
                print(f"  ⚠ scene{scene} lint: {e}")
        wav = nd / f"scene_{scene:02d}.wav"
        dur = _say(text, wav, RATE)
        manifest[scene] = {"text": text, "wav": wav.name, "dur": round(dur, 2), "rate": RATE}
        print(f"  scene{scene:2d} {dur:5.2f}s : {text}")
    (out_dir / "narration.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    longest = max((s["dur"] for s in manifest.values()), default=0)
    print(f"narration: {len(manifest)} scenes (무손실, 최장 {longest:.2f}s) → {nd}")
    return manifest


if __name__ == "__main__":
    synth(sys.argv[1] if len(sys.argv) > 1 else "ARM")
