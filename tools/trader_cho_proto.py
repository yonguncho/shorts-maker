"""trader_cho_proto.py — 'Trader Cho' 다이내믹 쇼츠 (v2: 트레이더분석 + 리텐션/신뢰 연출).

콘텐츠: state/topic.json 의 trader_analysis(hook/surprise/risk/related태그/payoff) + 차트 + 기사캡처.
연출(사용자 피드백 R10~R12):
 - 패턴인터럽트(0.8s 풀스크린 플래시), 상단 프로그레스바, 씬전환 whoosh SFX
 - 미니 데이터카드(RSI/거래량/52주), 관계태그, 리스크 한줄(씬), payoff
 - 출처 워터마크 상시, 헤더 타임스탬프, 클로징 면책(텍스트+음성), 마스코트 포즈 씬별 교체
영어 나레이션(macOS say) + ffmpeg 켄번즈. 파이프라인 비침습(독립).
"""
from __future__ import annotations
import json, os, re, subprocess, sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path("/Users/abcd/ai_workplace_mac/shorts_maker")
sys.path.insert(0, str(ROOT))   # src.* 임포트용
ASSETS = ROOT / "output/assets"
OUT = ROOT / "output/ready_for_review"
TMP = Path("/tmp/tcproto"); TMP.mkdir(parents=True, exist_ok=True)
W, H, FPS = 1080, 1920, 30
F_BLACK = "/System/Library/Fonts/Supplemental/Arial Black.ttf"
F_BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
BG = (11, 13, 16); ACCENT = (88, 166, 255); GREEN = (63, 185, 80); RED = (248, 81, 73)
DATE = "June 1, 2026"
DISC = "Not financial advice. For educational purposes only. You are responsible for your own investment decisions."
TAGS = {"ASML": "equipment", "TSM": "foundry", "AMD": "competitor", "MRVL": "custom silicon",
        "MU": "memory", "NVDA": "platform", "AVGO": "networking", "QCOM": "mobile",
        "SMCI": "servers", "RIOT": "GPU demand", "MSFT": "software", "DELL": "OEM", "ARM": "core IP"}
SPOKEN = {"NVDA": "Nvidia", "MRVL": "Marvell", "MU": "Micron", "TSM": "Taiwan Semi", "AMD": "A.M.D.",
          "ASML": "A.S.M.L.", "ARM": "Arm", "RIOT": "Riot", "AVGO": "Broadcom", "SMCI": "Super Micro",
          "QCOM": "Qualcomm", "MSFT": "Microsoft", "DELL": "Dell"}
def spk(t): return SPOKEN.get(t, t)

_POSE = {n: Image.open(ROOT/f"assets/mascot/poses/{n}.png").convert("RGBA")
         for n in ("point", "present", "thumb", "explain",
                   "surprise", "warn", "think", "celebrate")
         if (ROOT/f"assets/mascot/poses/{n}.png").exists()}
_FULL = Image.open(ROOT/"assets/mascot/trader_cho_3d_char.png").convert("RGBA")
def pose(name): return _POSE.get(name, _FULL)
def font(p, s): return ImageFont.truetype(p, s)


def outlined(d, xy, text, fnt, fill=(255, 255, 255), oc=(0, 0, 0), ow=4, anchor="la"):
    x, y = xy
    for dx in range(-ow, ow+1):
        for dy in range(-ow, ow+1):
            if dx*dx+dy*dy <= ow*ow:
                d.text((x+dx, y+dy), text, font=fnt, fill=oc, anchor=anchor)
    d.text((x, y), text, font=fnt, fill=fill, anchor=anchor)


def wrap(d, text, fnt, maxw):
    out, cur = [], ""
    for w in (text or "").split():
        t = (cur+" "+w).strip()
        if d.textlength(t, font=fnt) <= maxw:
            cur = t
        else:
            out.append(cur) if cur else None; cur = w
    if cur:
        out.append(cur)
    return out


def avatar(d=104):
    w, h = _FULL.size
    head = _FULL.crop((0, 0, w, w)).resize((d, d))
    mask = Image.new("L", (d, d), 0); ImageDraw.Draw(mask).ellipse((0, 0, d, d), fill=255)
    o = Image.new("RGBA", (d, d), (0, 0, 0, 0)); o.paste(head, (0, 0), head); o.putalpha(mask)
    return o


def header(img, i, n):
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W, 142), fill=(0, 0, 0))
    img.alpha_composite(avatar(104), (26, 19))
    d.text((150, 34), "TRADER CHO", font=font(F_BLACK, 44), fill=(255, 255, 255))
    d.text((150, 92), f"As of {DATE}", font=font(F_BOLD, 28), fill=ACCENT)
    # progress bar
    d.rectangle((0, 142, W, 152), fill=(40, 46, 53))
    d.rectangle((0, 142, int(W*i/n), 152), fill=ACCENT)


TITLE = ""   # 상시 질문 타이틀(build 에서 설정)


def fetch_logo(focus):
    """Finnhub profile2 로 회사 로고 다운로드(실패 시 None)."""
    try:
        import requests
        tok = None
        env = ROOT/".env"
        if env.exists():
            for ln in env.read_text().splitlines():
                if ln.startswith("FINNHUB_API_KEY="):
                    tok = ln.split("=", 1)[1].strip()
        if not tok:
            return None
        r = requests.get("https://finnhub.io/api/v1/stock/profile2",
                         params={"symbol": focus, "token": tok}, timeout=12)
        url = (r.json() or {}).get("logo")
        if not url:
            return None
        ir = requests.get(url, timeout=12)
        if ir.status_code == 200 and len(ir.content) > 800:
            p = str(TMP/"logo.png"); open(p, "wb").write(ir.content); return p
    except Exception:
        pass
    return None


def blur_photo(src, out, darken=110):
    """배경사진을 1080x1920 로 채우고 블러+어둡게(텍스트 가독). 실패 시 None."""
    try:
        from PIL import ImageFilter
        im = Image.open(src).convert("RGB")
        s = max(W/im.size[0], H/im.size[1])
        im = im.resize((int(im.size[0]*s), int(im.size[1]*s)))
        im = im.crop(((im.size[0]-W)//2, (im.size[1]-H)//2, (im.size[0]-W)//2+W, (im.size[1]-H)//2+H))
        im = im.filter(ImageFilter.GaussianBlur(14))
        ov = Image.new("RGBA", (W, H), (8, 10, 14, darken))
        im = Image.alpha_composite(im.convert("RGBA"), ov)
        im.convert("RGB").save(out); return out
    except Exception:
        return None


def draw_title(img):
    """헤더 아래 상시 질문 타이틀(빨강/노랑 외곽선)."""
    if not TITLE:
        return
    d = ImageDraw.Draw(img)
    fnt, lines, sz = _fit(d, TITLE, W-80, max_lines=2, hi=54, lo=38)
    y = 168
    for ln in lines[:2]:
        outlined(d, (W//2, y), ln, fnt, fill=(255, 221, 0), oc=(140, 0, 0), ow=5, anchor="ma")
        y += int(sz*1.18)


def disclaimer_always(img):
    d = ImageDraw.Draw(img)
    f = font(F_BOLD, 24)
    outlined(d, (W//2, H-54), "Not financial advice. For educational purposes only.",
             f, fill=(206, 212, 218), oc=(0, 0, 0), ow=3, anchor="ma")


def watermark(img, text):
    if not text:
        return
    d = ImageDraw.Draw(img)
    f = font(F_BOLD, 26)
    tw = d.textlength(text, font=f)
    d.rectangle((20, H-150, 40+tw, H-150+40), fill=(0, 0, 0, 160))
    d.text((30, H-146), text, font=f, fill=(180, 188, 196))


def chips(img, items):
    if not items:
        return
    d = ImageDraw.Draw(img); f = font(F_BLACK, 34); x = 40; y = 250
    for t in items:
        tw = d.textlength(t, font=f); pad = 22
        d.rounded_rectangle((x, y, x+tw+pad*2, y+62), radius=16, fill=(22, 27, 34), outline=ACCENT, width=3)
        d.text((x+pad, y+10), t, font=f, fill=(230, 237, 243)); x += tw+pad*2+18


def short(s, n=96):
    return (s or "").strip()   # 더 이상 자르지 않음(폰트 자동축소로 전체 표시)


def _fit(d, text, maxw, max_lines=4, hi=60, lo=34):
    """줄임표 없이 전체 문장이 들어가는 최대 폰트 찾기(없으면 최소폰트 + 줄수 허용)."""
    for sz in range(hi, lo-1, -2):
        f = font(F_BLACK, sz)
        ls = wrap(d, text, f, maxw)
        if len(ls) <= max_lines:
            return f, ls, sz
    f = font(F_BLACK, lo)
    return f, wrap(d, text, f, maxw), lo


def caption(img, text, color=(255, 255, 255), disc=False):
    d = ImageDraw.Draw(img)
    fnt, lines, sz = _fit(d, text, W-110, max_lines=4, hi=58, lo=34)
    lh = int(sz*1.25)
    bh = len(lines)*lh+60; y0 = H-bh-100   # 하단 상시 면책 공간 확보
    img.alpha_composite(Image.new("RGBA", (W, bh), (0, 0, 0, 180)), (0, y0))
    y = y0+28
    for ln in lines:
        outlined(d, (W//2, y), ln, fnt, fill=color, oc=(0, 0, 0), ow=5, anchor="ma"); y += lh


def base(bgpath=None, flash=False):
    c = Image.new("RGBA", (W, H), ((30, 8, 8, 255) if flash else BG+(255,)))
    if bgpath and os.path.exists(bgpath):
        im = Image.open(bgpath).convert("RGBA")
        if im.size != (W, H):
            im = im.resize((W, H))
        c.alpha_composite(im, (0, 0))
    return c


def put_mascot(img, name, big=False):
    m = pose(name); th = 1040 if big else 620
    s = th/m.size[1]; m = m.resize((int(m.size[0]*s), int(m.size[1]*s)))
    if big:
        img.alpha_composite(m, ((W-m.size[0])//2, 360))
    else:
        img.alpha_composite(m, (W-m.size[0]+40, H-m.size[1]-330))


def compose(sc, i, n):
    flash = sc["kind"] == "flash"
    c = base(sc.get("bg"), flash=flash)
    if flash:
        d = ImageDraw.Draw(c); f = font(F_BLACK, 96)
        for k, ln in enumerate(wrap(d, sc["caption"], f, W-120)[:3]):
            outlined(d, (W//2, 720+k*120), ln, f, fill=(255, 230, 0), oc=(0, 0, 0), ow=7, anchor="ma")
        p = str(TMP/f"s{sc['idx']:02d}.png"); c.convert("RGB").save(p); return p
    # 질문형 오프닝: 블러 배경 + 회사 로고 + 큰 질문 타이틀
    if sc["kind"] == "question":
        if sc.get("logo") and os.path.exists(sc["logo"]):
            lg = Image.open(sc["logo"]).convert("RGBA")
            s = min(660/lg.size[0], 660/lg.size[1]); lg = lg.resize((int(lg.size[0]*s), int(lg.size[1]*s)))
            c.alpha_composite(lg, ((W-lg.size[0])//2, 760))
        d = ImageDraw.Draw(c)
        fnt, lines, sz = _fit(d, TITLE or sc["caption"], W-90, max_lines=3, hi=82, lo=52)
        y = 320
        for ln in lines[:3]:
            outlined(d, (W//2, y), ln, fnt, fill=(255, 221, 0), oc=(150, 0, 0), ow=7, anchor="ma"); y += int(sz*1.16)
        header(c, i, n); disclaimer_always(c)
        p = str(TMP/f"s{sc['idx']:02d}.png"); c.convert("RGB").save(p); return p
    if sc.get("photo") and os.path.exists(sc["photo"]):
        try:
            ph = Image.open(sc["photo"]).convert("RGBA")
            mw, mh = 940, 620; s = min(mw/ph.size[0], mh/ph.size[1])
            ph = ph.resize((int(ph.size[0]*s), int(ph.size[1]*s)))
            px = (W-ph.size[0])//2; py = 250
            d = ImageDraw.Draw(c)
            d.rectangle((px-6, py-6, px+ph.size[0]+6, py+ph.size[1]+6), outline=ACCENT, width=5)
            c.alpha_composite(ph, (px, py))
        except Exception:
            pass
    if sc.get("mascot_big"):
        put_mascot(c, sc.get("pose", "present"), big=True)
    elif sc.get("pose"):
        put_mascot(c, sc["pose"], big=False)
    chips(c, sc.get("chips"))
    header(c, i, n)
    draw_title(c)
    watermark(c, sc.get("watermark"))
    caption(c, sc["caption"], color=sc.get("cap_color", (255, 255, 255)))
    disclaimer_always(c)
    p = str(TMP/f"s{sc['idx']:02d}.png"); c.convert("RGB").save(p); return p


def compose_ui(sc, i, n):
    """차트 씬용 투명 UI 레이어(헤더·프로그레스·마스코트·칩·워터마크·자막). 차트는 별도 리빌 영상."""
    c = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if sc.get("pose"):
        put_mascot(c, sc["pose"], big=False)
    chips(c, sc.get("chips"))
    header(c, i, n)
    draw_title(c)
    watermark(c, sc.get("watermark"))
    caption(c, sc["caption"], color=sc.get("cap_color", (255, 255, 255)))
    disclaimer_always(c)
    p = str(TMP/f"ui{sc['idx']:02d}.png"); c.save(p); return p


def clip_reveal(bg_png, ui_png, narr_aiff, whoosh, idx, reveal=1.2):
    """차트를 좌→우로 그려지듯 리빌 + UI 고정 오버레이 + (whoosh+narration) 오디오."""
    out = str(TMP/f"c{idx:02d}.mp4")
    df = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                         "-of", "default=nw=1:nk=1", narr_aiff], capture_output=True, text=True)
    try:
        nd = float(df.stdout.strip())
    except ValueError:
        nd = 4.0
    dur = nd + 0.55
    fc = (f"color=c=0x0b0d10:s={W}x{H}:d={dur:.2f}[bgc];"
          f"[0:v]scale={W}:{H}[chart];"
          f"[chart]crop=w='iw*min(t/{reveal},1)':h=ih:x=0:y=0[rev];"
          f"[bgc][rev]overlay=0:0[base];"
          f"[base][1:v]overlay=0:0,fps={FPS},format=yuv420p[v];"
          f"[2:a][3:a]concat=n=2:v=0:a=1[a]")
    cmd = ["ffmpeg", "-y", "-loop", "1", "-i", bg_png, "-loop", "1", "-i", ui_png,
           "-i", whoosh, "-i", narr_aiff, "-filter_complex", fc,
           "-map", "[v]", "-map", "[a]", "-t", f"{dur:.2f}", "-r", str(FPS),
           "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-c:a", "aac", "-b:a", "160k", out]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"reveal {idx} FAIL:", r.stderr[-300:])
    return out


def sfx():
    wh = str(TMP/"whoosh.wav")
    if not os.path.exists(wh):
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anoisesrc=d=0.4:c=pink:a=0.35",
                        "-af", "highpass=f=250,lowpass=f=5000,afade=t=in:d=0.05,afade=t=out:st=0.18:d=0.22",
                        wh], capture_output=True)
    return wh


VOICE = os.environ.get("TC_VOICE", "Daniel")      # 사용자 선택: Daniel(영국 남성)
RATE = os.environ.get("TC_RATE", "178")


def _elevenlabs(text, out_mp3):
    """ELEVENLABS_API_KEY 가 .env/환경에 있으면 자연스러운 음성 생성(없으면 None)."""
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        env = ROOT/".env"
        if env.exists():
            for ln in env.read_text().splitlines():
                if ln.startswith("ELEVENLABS_API_KEY="):
                    key = ln.split("=", 1)[1].strip()
    if not key:
        return None
    try:
        import requests
        vid = os.environ.get("ELEVENLABS_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb")  # 기본 공용 음성
        r = requests.post(f"https://api.elevenlabs.io/v1/text-to-speech/{vid}",
                          headers={"xi-api-key": key, "accept": "audio/mpeg"},
                          json={"text": text, "model_id": "eleven_multilingual_v2"}, timeout=40)
        if r.status_code == 200 and len(r.content) > 1000:
            open(out_mp3, "wb").write(r.content)
            return out_mp3
    except Exception:
        pass
    return None


def tts(text, idx):
    a = str(TMP/f"n{idx:02d}.aiff")
    mp3 = _elevenlabs(text, str(TMP/f"n{idx:02d}.mp3"))
    if mp3:
        return mp3
    subprocess.run(["say", "-v", VOICE, "-r", RATE, "-o", a, text], check=False)
    if not os.path.exists(a):
        subprocess.run(["say", "-o", a, text], check=False)
    return a


def clip(png, narr_aiff, whoosh, idx, flash=False):
    out = str(TMP/f"c{idx:02d}.mp4")
    # 오디오 = whoosh + (narration). flash 는 whoosh 만.
    if flash or not narr_aiff:
        af = ["-i", whoosh]; fc = "[1:a]apad=pad_dur=0.2[a]"; amap = "[a]"; dur = 0.9
    else:
        df = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                             "-of", "default=nw=1:nk=1", narr_aiff], capture_output=True, text=True)
        try:
            nd = float(df.stdout.strip())
        except ValueError:
            nd = 3.0
        af = ["-i", whoosh, "-i", narr_aiff]
        fc = "[1:a][2:a]concat=n=2:v=0:a=1[a]"; amap = "[a]"; dur = nd+0.55
    vf = (f"scale={W}:{H},zoompan=z='min(1+0.0005*on,1.10)':d=1:"
          f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H}:fps={FPS},format=yuv420p")
    cmd = ["ffmpeg", "-y", "-loop", "1", "-i", png, *af,
           "-filter_complex", f"[0:v]{vf}[v];{fc}", "-map", "[v]", "-map", amap,
           "-t", f"{dur:.2f}", "-r", str(FPS), "-c:v", "libx264", "-preset", "medium",
           "-crf", "20", "-c:a", "aac", "-b:a", "160k", "-shortest", out]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"clip {idx} FAIL:", r.stderr[-300:])
    return out


def clean_tts(s):
    s = re.sub(r"\(NASDAQ:[^)]*\)", "", s or "")
    s = re.sub(r"\$(\d)", r"\1 dollars ", s)
    return re.sub(r"\s+", " ", s).strip()


def build():
    topic = json.load(open(ROOT/"state/topic.json"))["topic"]
    data = json.load(open(ROOT/"state/verified_market_data.json"))
    focus = topic["focus_symbol"]
    ta = topic.get("trader_analysis") or {}
    why = topic.get("why_now") or {}
    co = topic.get("co_movers") or []
    th = topic.get("theme") or {}
    rel = ta.get("related") or [{"ticker": p["peer"], "tag": TAGS.get(p["peer"], "peer")}
                                for p in (topic.get("related") or {}).get("peers", [])[:4]]
    hist = {h["ticker"]: h for h in data.get("price_history", []) if h.get("ticker")}.get(focus, {})
    m = re.search(r"([+-]\d+(?:\.\d+)?)%", topic["angle"]); fpct = m.group(1) if m else "+0"
    snap = {q["ticker"]: q for q in data.get("market_snapshot", []) if q.get("ticker")}.get(focus, {})
    pm = re.search(r"price=([\d.]+)", snap.get("content", "") or ""); price = pm.group(1) if pm else "?"
    rsi = hist.get("rsi14"); vol = hist.get("vol_vs_30d_avg"); off = hist.get("pct_off_52w_high")

    def f(prefix):
        for x in sorted(ASSETS.glob(f"chart_{prefix}*.png")):
            return str(x)
        return None
    # 관련 기사 대표사진(og:image) 다운로드 — 분석 씬 사진카드용
    og_path = None
    try:
        from src.article import fetch_og_image
        if why.get("url"):
            og_path = fetch_og_image(why["url"], str(TMP/"og.jpg"))
    except Exception:
        og_path = None
    art = f("article_shot_ARM") or f("article_shot")
    price_chart = f("price_line_ARM") or f("price_line")
    co_chart = f("co_movers_ARM") or f("co_movers")
    corr_chart = f("correlation_ARM") or f("correlation")

    co3 = ", ".join(f"{spk(c['ticker'])} up {c['pct']:.1f}" for c in co[:3])
    rel_disp = "  ".join(f"{r['ticker']}·{r['tag']}" for r in rel[:4])
    rel_say = ", ".join(f"{spk(r['ticker'])}, the {r['tag']}" for r in rel[:3])
    chip_list = [c for c in ([f"RSI {rsi}" if rsi else None,
                              f"Vol {vol}x avg" if vol else None,
                              "52w HIGH" if (off is not None and off > -3) else None]) if c]

    global TITLE
    TITLE = f"Why did {focus} just rip {fpct}%?"
    logo = fetch_logo(focus)
    q_bg = blur_photo(og_path, str(TMP/"qbg.jpg")) if og_path else None

    S = [
        dict(kind="question", bg=q_bg, logo=logo, caption=TITLE,
             narr=clean_tts(f"Why did {focus} just rip {fpct.replace('+','')} percent? Let's break it down.")),
        dict(kind="hook", mascot_big=True, pose="surprise", title=f"{focus} {fpct}%",
             caption=ta.get("hook_line") or f"{focus} is today's big mover",
             narr=(ta.get("hook_line") or f"{focus} is today's big mover.")),
        dict(kind="news", bg=art, watermark=f"Source: {why.get('source','news')}",
             caption=why.get("headline", "Breaking"),
             narr=clean_tts(why.get("summary") or why.get("headline") or "")),
        dict(kind="why", pose="think", cap_color=(255, 230, 0), photo=og_path,
             caption="The real read: " + short(ta.get("surprise") or "An indirect catalyst drove the move.", 92),
             narr=clean_tts("Here's the real read. " + short(ta.get("surprise") or "", 150))),
        dict(kind="price", bg=price_chart, pose="point", watermark="Data: Yahoo Finance",
             chips=chip_list, caption=f"{focus} {fpct}% to ${price}",
             narr=clean_tts(f"{focus} jumped {fpct.replace('+','')} percent to about {price} dollars"
                            + (f", on {vol} times average volume" if vol else "") + ".")),
        dict(kind="co", bg=co_chart, pose="point", watermark="Data: Yahoo Finance",
             caption="Moving with it: " + ", ".join(f"{c['ticker']} {c['pct']:+.1f}%" for c in co[:3]),
             narr=clean_tts(f"The whole A.I. chip group moved with it. {co3} percent.")),
        dict(kind="related", bg=corr_chart, pose="point", watermark="Data: Yahoo Finance (computed)",
             caption="Value chain: " + rel_disp,
             narr=clean_tts(f"Watch the value chain: {rel_say}.")),
        dict(kind="risk", pose="warn", cap_color=RED,
             caption="The risk: " + short(ta.get("risk") or "Sharp move — confirmation needed.", 92),
             narr=clean_tts("But here's the risk. " + short(ta.get("risk") or "", 140))),
        dict(kind="close", mascot_big=True, pose="celebrate", disc=True,
             caption=short(ta.get("payoff_line") or "Watch for confirmation, not just the headline.", 92),
             narr=clean_tts(short(ta.get("payoff_line") or "", 130) + " I'm Trader Cho. Follow for tomorrow's move. "
                            "Not financial advice, educational only.")),
    ]
    wh = sfx()
    clips = []
    for i, sc in enumerate(S, 1):
        sc["idx"] = i
        reveal = sc["kind"] in ("price", "co", "related") and sc.get("bg") and os.path.exists(sc["bg"])
        if reveal:
            bgp = str(TMP/f"bg{i:02d}.png"); base(sc["bg"]).convert("RGB").save(bgp)
            uip = compose_ui(sc, i, len(S))
            narr = tts(sc["narr"], i)
            clips.append(clip_reveal(bgp, uip, narr, wh, i))
        else:
            png = compose(sc, i, len(S))
            narr = None if sc["kind"] == "flash" else tts(sc["narr"], i)
            clips.append(clip(png, narr, wh, i, flash=(sc["kind"] == "flash")))
        print(f"scene {i} [{sc['kind']}]{' reveal' if reveal else ''} done")
    lst = TMP/"concat.txt"; lst.write_text("\n".join(f"file '{c}'" for c in clips))
    out = OUT/"trader_cho_proto.mp4"
    r = subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                        "-c:a", "aac", "-b:a", "160k", str(out)], capture_output=True, text=True)
    if r.returncode != 0:
        print("CONCAT FAIL:", r.stderr[-500:]); return
    dur = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", str(out)], capture_output=True, text=True).stdout.strip()
    print(f"DONE → {out} ({dur}s, {len(clips)} scenes)")


if __name__ == "__main__":
    build()
