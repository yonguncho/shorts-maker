"""assets.py — 에셋 자동 수집 (폰트/아이콘/효과음) + 저작권 manifest.

이 단계에서는 폰트(Anton/Inter/JetBrains Mono) + Lucide 아이콘 다운로드만 구현.
(Pexels 섹터이미지·Pixabay 효과음은 키 필요 → 후속 단계)
강제 제약: 실존 인물 사진 검색 금지(키워드 블랙리스트 + raise). 모든 다운로드는 manifest 기록.
"""
from __future__ import annotations
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
sys.path.insert(0, str(Path(__file__).resolve().parent))
import json_utils as JU

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent
FONTS = BASE / "fonts"; ICONS = BASE / "icons"; SFX = BASE / "sfx"
STOCK = ROOT / "assets" / "stock"
for _d in (FONTS, ICONS, SFX, STOCK):
    _d.mkdir(parents=True, exist_ok=True)
MANIFEST = BASE / "assets_manifest.json"
_UA = {"User-Agent": "trader-cho-assets/1.0"}

# 섹터별 스톡 검색어(P1.1). 인물 배제(assert_no_person). 추상·물체·환경만.
SECTOR_KEYWORDS = {
    "semiconductor": ["semiconductor chip macro", "data center server room",
                      "circuit board glow", "ai processor close up"],
}
# 티커 → 섹터(반도체/AI 집중 + 일반화 시드). 미지정 시 semiconductor 기본.
TICKER_SECTOR = {t: "semiconductor" for t in
                 ["ARM", "NVDA", "MRVL", "MU", "TSM", "ASML", "AMD", "AVGO", "SMCI", "INTC", "QCOM"]}
TICKER_SECTOR.update({t: "automotive" for t in ["TSLA", "RIVN", "F", "GM"]})
TICKER_SECTOR.update({t: "tech" for t in ["AAPL", "MSFT", "GOOGL", "META", "AMZN", "ORCL", "CRM", "NFLX"]})
PEXELS_SEARCH       = "https://api.pexels.com/v1/search"
PEXELS_VIDEO_SEARCH = "https://api.pexels.com/videos/search"
UNSPLASH_SEARCH     = "https://api.unsplash.com/search/photos"
PIXABAY_SEARCH      = "https://pixabay.com/api/"

STOCK_VIDEO = ROOT / "assets" / "stock_video"
STOCK_VIDEO.mkdir(parents=True, exist_ok=True)

# 실존 인물 차단(강제 제약 1) — 이미지 검색어에 포함되면 raise
PERSON_BLACKLIST = ["ceo", "executive", "president", "politician", "real person", "celebrity",
                    "face", "portrait", "headshot", "person", "man ", "woman ", "people",
                    "elon", "musk", "huang", "jensen", "cook", "powell"]

FONT_SOURCES = {
    "Anton-Regular.ttf": ("https://raw.githubusercontent.com/google/fonts/main/ofl/anton/Anton-Regular.ttf",
                          "https://raw.githubusercontent.com/google/fonts/main/ofl/anton/OFL.txt", "OFL-1.1"),
    "Inter.ttf": ("https://raw.githubusercontent.com/google/fonts/main/ofl/inter/Inter%5Bopsz,wght%5D.ttf",
                  "https://raw.githubusercontent.com/google/fonts/main/ofl/inter/OFL.txt", "OFL-1.1"),
    "JetBrainsMono.ttf": ("https://raw.githubusercontent.com/google/fonts/main/ofl/jetbrainsmono/JetBrainsMono%5Bwght%5D.ttf",
                          "https://raw.githubusercontent.com/google/fonts/main/ofl/jetbrainsmono/OFL.txt", "OFL-1.1"),
}
# key → Lucide 후보명(이름 변경 대응). 첫 성공 후보를 key.svg 로 저장.
ICON_CANDIDATES = {
    "siren": ["siren"],
    "trending-up": ["trending-up"],
    "trending-down": ["trending-down"],
    "alert-triangle": ["triangle-alert", "alert-triangle"],
    "bar-chart": ["chart-bar", "chart-column", "bar-chart-3"],
    "line-chart": ["chart-line", "line-chart"],
    "info": ["info"],
    "check": ["check"],
    "x": ["x"],
}
ICON_URL = "https://raw.githubusercontent.com/lucide-icons/lucide/main/icons/{}.svg"


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_manifest():
    if MANIFEST.exists():
        try:
            return json.loads(MANIFEST.read_text())
        except ValueError:
            pass
    return []


def _record(file, source, url, license, used_in=None):
    m = _load_manifest()
    m = [x for x in m if x.get("file") != str(file)]
    m.append({"file": str(file), "source": source, "url": url, "license": license,
              "downloaded_at": _now(), "used_in": used_in or []})
    JU.atomic_write_json(MANIFEST, m)


def assert_no_person(query: str):
    q = (query or "").lower()
    for b in PERSON_BLACKLIST:
        if b in q:
            raise ValueError(f"인물 키워드 차단(강제 제약): '{b}' in '{query}'")


def _get(url):
    r = requests.get(url, headers=_UA, timeout=30)
    r.raise_for_status()
    return r.content


LOGOS = BASE.parent / "assets" / "logos"
# 티커 → (회사명, Wikidata QID 힌트). QID 있으면 검색 생략. 시드 30+.
TICKER_WIKI = {
    "ARM": ("Arm Holdings", None), "NVDA": ("Nvidia", "Q182477"),
    "MRVL": ("Marvell Technology", None), "MU": ("Micron Technology", None),
    "TSM": ("TSMC", "Q713489"), "ASML": ("ASML Holding", None),
    "AMD": ("Advanced Micro Devices", "Q128896"), "AVGO": ("Broadcom", None),
    "INTC": ("Intel", "Q248"), "QCOM": ("Qualcomm", None), "TSLA": ("Tesla, Inc.", "Q478214"),
    "AAPL": ("Apple Inc.", "Q312"), "MSFT": ("Microsoft", "Q2283"), "GOOGL": ("Google", "Q95"),
    "AMZN": ("Amazon (company)", "Q3884"), "META": ("Meta Platforms", "Q380"),
    "AVAV": ("AeroVironment", None), "PLTR": ("Palantir Technologies", None),
    "SMCI": ("Supermicro", None), "DELL": ("Dell Technologies", None),
    "ORCL": ("Oracle Corporation", "Q41506"), "CRM": ("Salesforce", None),
    "NFLX": ("Netflix", "Q907311"), "DIS": ("The Walt Disney Company", None),
    "BA": ("Boeing", "Q66"), "F": ("Ford Motor Company", None), "GM": ("General Motors", None),
    "RIVN": ("Rivian", None), "COIN": ("Coinbase", None), "UBER": ("Uber", None),
}
_WUA = {"User-Agent": "trader-cho-assets/1.0 (educational shorts)"}


def _wikidata_logo_bytes(name, qid=None):
    """Wikidata P154(logo) → Commons 래스터 PNG bytes. (bytes, source_url) or (None, None)."""
    if not qid:
        r = requests.get("https://www.wikidata.org/w/api.php", headers=_WUA, timeout=20,
                         params={"action": "wbsearchentities", "search": name, "language": "en",
                                 "type": "item", "format": "json", "limit": 1})
        hits = r.json().get("search", [])
        if not hits:
            return None, None
        qid = hits[0]["id"]
    e = requests.get(f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json",
                     headers=_WUA, timeout=20)
    claims = e.json()["entities"][qid]["claims"]
    if "P154" not in claims:
        return None, None
    fn = claims["P154"][0]["mainsnak"]["datavalue"]["value"]
    a = requests.get("https://commons.wikimedia.org/w/api.php", headers=_WUA, timeout=20,
                     params={"action": "query", "titles": f"File:{fn}", "prop": "imageinfo",
                             "iiprop": "url", "iiurlwidth": 512, "format": "json"})
    page = list(a.json()["query"]["pages"].values())[0]
    thumb = page["imageinfo"][0]["thumburl"]
    img = requests.get(thumb, headers=_WUA, timeout=20)
    data = img.content
    if img.status_code != 200 or not (data[:8].startswith(b"\x89PNG") or data[:3] == b"\xff\xd8\xff"):
        raise RuntimeError(f"이미지 응답 아님(status={img.status_code}, magic={data[:12]!r})")
    return data, f"https://www.wikidata.org/wiki/{qid}"


def _logodev_bytes(ticker):
    """Logo.dev(무료 티어, .env LOGODEV_API_KEY 필요) → PNG bytes. 키 없으면 None."""
    import os
    key = os.environ.get("LOGODEV_API_KEY")
    dom = {"ARM": "arm.com", "NVDA": "nvidia.com", "TSLA": "tesla.com", "MRVL": "marvell.com",
           "MU": "micron.com", "TSM": "tsmc.com", "ASML": "asml.com", "AMD": "amd.com"}.get(ticker.upper())
    if not key or not dom:
        return None
    r = requests.get(f"https://img.logo.dev/{dom}", headers=_WUA, timeout=20,
                     params={"token": key, "size": 256, "format": "png"})
    return r.content if (r.status_code == 200 and r.content[:8].startswith(b"\x89PNG")) else None


def download_logo(ticker: str):
    """회사 로고 PNG 캐싱. 우선순위: 로컬캐시 → Wikidata(P154, CC) → None.
    보도/정보 표시 크기 한정(상표권자 귀속). 실패 시 None(graceful)."""
    LOGOS.mkdir(parents=True, exist_ok=True)
    tk = (ticker or "").upper()
    dest = LOGOS / f"{tk}.png"
    if dest.exists() and dest.stat().st_size > 800:
        return dest   # 로컬 캐시 폴백
    name, qid = TICKER_WIKI.get(tk, (tk, None))
    # 1순위 Wikidata(CC), 2순위 Logo.dev(키 필요)
    try:
        data, src = _wikidata_logo_bytes(name, qid)
        if data:
            dest.write_bytes(data)
            _record(dest, f"Wikipedia/Wikidata · {name}", src,
                    "CC-BY-SA (Wikimedia Commons); trademark of respective owner, informational use",
                    used_in=["thumbnail"])
            return dest
    except Exception as e:
        print(f"  ⚠ Wikidata 로고 {tk} 실패: {e}")
    try:
        data = _logodev_bytes(tk)
        if data:
            dest.write_bytes(data)
            _record(dest, "Logo.dev", f"https://img.logo.dev/{tk}", "Logo.dev free tier", used_in=["thumbnail"])
            return dest
    except Exception as e:
        print(f"  ⚠ Logo.dev {tk} 실패: {e}")
    return None


def _load_env_key(var: str) -> str | None:
    import os
    k = os.environ.get(var)
    if not k:
        envf = ROOT / ".env"
        if envf.exists():
            for line in envf.read_text().splitlines():
                if line.startswith(f"{var}="):
                    k = line.split("=", 1)[1].strip()
                    break
    return k or None


def _pexels_key():    return _load_env_key("PEXELS_API_KEY")
def _unsplash_key():  return _load_env_key("UNSPLASH_ACCESS_KEY")
def _pixabay_key():   return _load_env_key("PIXABAY_API_KEY")


def sector_for_ticker(ticker: str) -> str:
    return TICKER_SECTOR.get((ticker or "").upper(), "semiconductor")


def _fetch_unsplash(kw: str, dest_dir: Path, n: int) -> list[Path]:
    """Unsplash API → portrait 사진. 키 없으면 []."""
    key = _unsplash_key()
    if not key:
        return []
    try:
        r = requests.get(UNSPLASH_SEARCH,
                         headers={"Authorization": f"Client-ID {key}",
                                  "Accept-Version": "v1"},
                         params={"query": kw, "per_page": n, "orientation": "portrait"},
                         timeout=20)
        r.raise_for_status()
        results = r.json().get("results", [])[:n]
    except Exception as e:
        print(f"  ⚠ Unsplash '{kw}': {e}")
        return []
    slug = re.sub(r"[^a-z0-9]+", "_", kw.lower()).strip("_")
    out = []
    for item in results:
        url = item["urls"].get("full") or item["urls"]["regular"]
        pid = item["id"]
        fn = dest_dir / f"us_{slug}_{pid}.jpg"
        if not fn.exists() or fn.stat().st_size < 5000:
            fn.write_bytes(requests.get(url, timeout=30).content)
        _record(fn, f"Unsplash · {item.get('user', {}).get('name', '?')}",
                item.get("links", {}).get("html", ""),
                "Unsplash License (free commercial use, no attribution required)",
                used_in=["scene_background"])
        out.append(fn)
    return out


def _fetch_pexels(kw: str, dest_dir: Path, n: int) -> list[Path]:
    """Pexels API → portrait 사진."""
    key = _pexels_key()
    if not key:
        return []
    try:
        r = requests.get(PEXELS_SEARCH, headers={"Authorization": key},
                         params={"query": kw, "per_page": n,
                                 "orientation": "portrait", "size": "large"}, timeout=20)
        r.raise_for_status()
        photos = r.json().get("photos", [])[:n]
    except Exception as e:
        print(f"  ⚠ Pexels '{kw}': {e}")
        return []
    slug = re.sub(r"[^a-z0-9]+", "_", kw.lower()).strip("_")
    out = []
    for photo in photos:
        src = photo["src"].get("portrait") or photo["src"].get("large2x") or photo["src"]["large"]
        fn = dest_dir / f"px_{slug}_{photo['id']}.jpg"
        if not fn.exists() or fn.stat().st_size < 5000:
            fn.write_bytes(_get(src))
        _record(fn, f"Pexels · {photo.get('photographer', '?')}", photo.get("url", ""),
                "Pexels License (free use, no attribution required)",
                used_in=["scene_background"])
        out.append(fn)
    return out


def _fetch_pixabay(kw: str, dest_dir: Path, n: int) -> list[Path]:
    """Pixabay API → 세로 사진 (3순위 폴백). 키 없으면 []."""
    key = _pixabay_key()
    if not key:
        return []
    try:
        r = requests.get(PIXABAY_SEARCH,
                         params={"key": key, "q": kw, "per_page": n,
                                 "image_type": "photo", "orientation": "vertical",
                                 "safesearch": "true", "min_width": 1000},
                         timeout=20)
        r.raise_for_status()
        hits = r.json().get("hits", [])[:n]
    except Exception as e:
        print(f"  ⚠ Pixabay '{kw}': {e}")
        return []
    slug = re.sub(r"[^a-z0-9]+", "_", kw.lower()).strip("_")
    out = []
    for item in hits:
        url = item.get("largeImageURL", "")
        if not url:
            continue
        fn = dest_dir / f"pb_{slug}_{item['id']}.jpg"
        if not fn.exists() or fn.stat().st_size < 5000:
            fn.write_bytes(_get(url))
        _record(fn, f"Pixabay · {item.get('user', '?')}",
                f"https://pixabay.com/photos/{item['id']}/",
                "Pixabay License (free commercial use, no attribution required)",
                used_in=["scene_background"])
        out.append(fn)
    return out


def download_stock(sector="semiconductor", per_keyword=3, orientation="portrait") -> list:
    """섹터 스톡 이미지 수집. 우선순위: Unsplash → Pexels → Pixabay.
    인물 키워드 차단(L0.1). 기존 캐시 있으면 스킵."""
    kws = SECTOR_KEYWORDS.get(sector, [sector])
    dest_dir = STOCK / sector
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = []
    for kw in kws:
        assert_no_person(kw)
        photos = _fetch_unsplash(kw, dest_dir, per_keyword)
        source = "Unsplash"
        if not photos:
            photos = _fetch_pexels(kw, dest_dir, per_keyword)
            source = "Pexels"
        if not photos:
            photos = _fetch_pixabay(kw, dest_dir, per_keyword)
            source = "Pixabay"
        if not photos:
            print(f"  ⚠ stock[{sector}] '{kw}' — 모든 소스 실패(키 확인 필요)")
        else:
            print(f"stock[{sector}]: '{kw}' → {len(photos)}장 ({source})")
        out.extend(photos)
    return out


def download_stock_video(sector="semiconductor", per_keyword=2) -> list[Path]:
    """Pexels Videos API → assets/stock_video/{sector}/ 캐싱.
    세로(portrait) MP4 클립 수집. compose_short에서 배경 동영상으로 사용."""
    key = _pexels_key()
    if not key:
        print("  ⚠ PEXELS_API_KEY 없음 — 영상 클립 스킵")
        return []
    kws = SECTOR_KEYWORDS.get(sector, [sector])
    dest_dir = STOCK_VIDEO / sector
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = []
    for kw in kws:
        assert_no_person(kw)
        try:
            r = requests.get(PEXELS_VIDEO_SEARCH,
                             headers={"Authorization": key},
                             params={"query": kw, "per_page": per_keyword,
                                     "orientation": "portrait", "size": "medium"},
                             timeout=30)
            r.raise_for_status()
            videos = r.json().get("videos", [])[:per_keyword]
        except Exception as e:
            print(f"  ⚠ Pexels Videos '{kw}': {e}")
            continue
        slug = re.sub(r"[^a-z0-9]+", "_", kw.lower()).strip("_")
        for v in videos:
            # HD portrait MP4 선택
            files = v.get("video_files", [])
            portrait = [f for f in files
                        if f.get("quality") in ("hd", "sd")
                        and f.get("file_type") == "video/mp4"
                        and (f.get("height", 0) or 0) > (f.get("width", 1) or 1)]
            if not portrait:
                portrait = [f for f in files if f.get("file_type") == "video/mp4"]
            if not portrait:
                continue
            best = sorted(portrait, key=lambda f: f.get("height", 0), reverse=True)[0]
            fn = dest_dir / f"{slug}_{v['id']}.mp4"
            if not fn.exists() or fn.stat().st_size < 50000:
                fn.write_bytes(_get(best["link"]))
            _record(fn, f"Pexels Videos · {v.get('user', {}).get('name', '?')}",
                    v.get("url", ""),
                    "Pexels License (free use, no attribution required)",
                    used_in=["scene_background_video"])
            out.append(fn)
        print(f"stock_video[{sector}]: '{kw}' → {len(videos)}클립")
    return out


def extract_video_frames(sector="semiconductor") -> list[Path]:
    """stock_video/{sector}/*.mp4 → stock/{sector}/vid_*.jpg (중간 프레임 추출).
    ffmpeg -ss 50% -vframes 1 으로 대표 프레임 하나 저장 → scene_background 풀에 자동 편입."""
    import subprocess
    src_dir = STOCK_VIDEO / sector
    dest_dir = STOCK / sector
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = []
    for mp4 in sorted(src_dir.glob("*.mp4")):
        jpg = dest_dir / f"vid_{mp4.stem}.jpg"
        if jpg.exists() and jpg.stat().st_size > 5000:
            out.append(jpg)
            continue
        # 영상 길이 조회
        probe = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(mp4)],
            capture_output=True, text=True)
        try:
            dur = float(probe.stdout.strip())
            seek = dur * 0.4
        except Exception:
            seek = 3.0
        result = subprocess.run(
            ["ffmpeg", "-y", "-ss", str(seek), "-i", str(mp4),
             "-vframes", "1", "-q:v", "2", str(jpg)],
            capture_output=True)
        if result.returncode == 0 and jpg.exists() and jpg.stat().st_size > 5000:
            _record(jpg, f"Pexels Videos frame (from {mp4.name})", "",
                    "Pexels License (free use)", used_in=["scene_background"])
            out.append(jpg)
            print(f"  video frame: {jpg.name}")
        else:
            print(f"  ⚠ 프레임 추출 실패: {mp4.name}")
    return out


def download_fonts() -> dict:
    out = {}
    for name, (url, lic_url, lic) in FONT_SOURCES.items():
        dest = FONTS / name
        if not dest.exists() or dest.stat().st_size < 10000:
            dest.write_bytes(_get(url))
            try:
                (FONTS / (name.split(".")[0] + "_LICENSE.txt")).write_bytes(_get(lic_url))
            except Exception:
                pass
            _record(dest, "Google Fonts", url, lic)
        out[name] = dest
        print(f"font: {name} ({dest.stat().st_size} B)")
    return out


def replace_svg_color(svg_path, new_color: str) -> str:
    """Lucide SVG 의 stroke 색을 new_color 로 치환한 SVG 문자열 반환."""
    t = Path(svg_path).read_text()
    t = re.sub(r'stroke="[^"]*"', f'stroke="{new_color}"', t)
    if "currentColor" in t:
        t = t.replace("currentColor", new_color)
    if "stroke=" not in t:
        t = t.replace("<svg ", f'<svg stroke="{new_color}" ', 1)
    return t


def download_icons() -> dict:
    out = {}
    for key, candidates in ICON_CANDIDATES.items():
        dest = ICONS / f"{key}.svg"
        if dest.exists():
            out[key] = dest
            continue
        for cand in candidates:
            url = ICON_URL.format(cand)
            try:
                dest.write_bytes(_get(url))
                _record(dest, "Lucide Icons", url, "ISC")
                out[key] = dest
                print(f"icon: {key}.svg (via {cand})")
                break
            except requests.HTTPError:
                continue
        else:
            print(f"icon: {key} — 후보 전부 실패(건너뜀)")
    return out


def ensure_assets():
    fonts = download_fonts()
    icons = download_icons()
    return {"fonts": fonts, "icons": icons}


if __name__ == "__main__":
    ensure_assets()
    print("manifest:", MANIFEST)
