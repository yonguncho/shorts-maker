"""github_publish.py — GitHub Release에 MP4 + 썸네일 업로드.

gh CLI 사용. 사전 인증 필요: gh auth login
GITHUB_REPO: .env의 GITHUB_REPO 값, 없으면 '{owner}/tradercho-daily' 자동 생성.

사용:
  python tradercho/github_publish.py outputs/ARM_20260605   # 단독 테스트
  upload(out_dir) → {"download_url": "...", "release_url": "...", "tag": "..."}
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# ── 환경 로드 ─────────────────────────────────────────────────────────────────

def _load_env() -> dict:
    env = {}
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()
    return env


def _get_repo() -> str | None:
    env = _load_env()
    if env.get("GITHUB_REPO"):
        return env["GITHUB_REPO"]
    # gh CLI 로그인 확인 후 기본 레포 이름 구성
    try:
        owner = _gh(["api", "user", "--jq", ".login"]).strip()
        return f"{owner}/tradercho-daily"
    except Exception:
        return None


# ── gh CLI 래퍼 ───────────────────────────────────────────────────────────────

def _gh_env() -> dict:
    """GH_TOKEN 을 환경변수에 주입. gh auth login 없이 PAT 직접 사용."""
    env = os.environ.copy()
    token = _load_env().get("GITHUB_TOKEN", "")
    if token:
        env["GH_TOKEN"] = token
    return env


def _gh(args: list[str], check: bool = True) -> str:
    cmd = ["/usr/local/bin/gh"] + args
    result = subprocess.run(cmd, capture_output=True, text=True,
                            cwd=str(ROOT), env=_gh_env())
    if check and result.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:3])} failed: {result.stderr.strip()}")
    return result.stdout


def is_authenticated() -> bool:
    token = _load_env().get("GITHUB_TOKEN", "")
    if token:
        # GH_TOKEN 방식: api 호출로 토큰 유효성 확인
        try:
            _gh(["api", "user", "--jq", ".login"])
            return True
        except Exception:
            return False
    # gh auth login 방식 폴백
    try:
        _gh(["auth", "status"])
        return True
    except Exception:
        return False


def ensure_repo(repo: str) -> bool:
    """레포 없으면 생성. 이미 있으면 True. 생성 실패하면 False."""
    try:
        _gh(["repo", "view", repo])
        return True
    except RuntimeError:
        pass  # 없음 → 생성 시도
    try:
        _gh(["repo", "create", repo, "--public",
             "--description", "Trader Cho daily short-form stock videos"])
        print(f"  GitHub 레포 생성: https://github.com/{repo}")
        return True
    except RuntimeError as e:
        print(f"  ⚠ 레포 생성 실패: {e}")
        return False


# ── 핵심 함수 ─────────────────────────────────────────────────────────────────

def upload(out_dir: str | Path, yt_description: str = "") -> dict:
    """
    out_dir 내 MP4 + thumbnail.png 를 GitHub Release 에 업로드.
    반환: {"download_url": str, "release_url": str, "tag": str}
          실패 시 {"error": str}
    """
    out_dir = Path(out_dir)
    if not out_dir.exists():
        return {"error": f"out_dir not found: {out_dir}"}

    # 디렉터리 이름 파싱: ARM_20260605 → ticker=ARM, date=20260605
    parts = out_dir.name.rsplit("_", 1)
    if len(parts) != 2:
        return {"error": f"out_dir name must be TICKER_YYYYMMDD: {out_dir.name}"}
    ticker, date_str = parts[0], parts[1]

    # 인증 확인
    if not is_authenticated():
        return {"error": "gh not authenticated — run: gh auth login"}

    repo = _get_repo()
    if not repo:
        return {"error": "GITHUB_REPO 설정 필요 (.env) 또는 gh auth login 필요"}

    ensure_repo(repo)

    # MP4 파일 탐색 — 가장 최신 mtime 파일 선택
    candidates = list(out_dir.glob("*.mp4"))
    if not candidates:
        return {"error": f"MP4 not found in {out_dir}"}
    mp4 = max(candidates, key=lambda p: p.stat().st_mtime)

    thumb = out_dir / "thumbnail.png"
    tag = f"{ticker}-{date_str}"

    # 날짜 포맷: 20260605 → Jun 5, 2026
    try:
        from datetime import datetime
        d = datetime.strptime(date_str, "%Y%m%d")
        date_label = d.strftime("%b %-d, %Y")
    except Exception:
        date_label = date_str

    # 기존 릴리스 있으면 삭제 후 재생성 (재실행 idempotent)
    existing = _gh(["release", "view", tag, "--repo", repo], check=False)
    if existing.strip():
        _gh(["release", "delete", tag, "--repo", repo, "--yes"], check=False)

    # 릴리스 생성 + 파일 업로드
    assets = [str(mp4)]
    if thumb.exists():
        assets.append(str(thumb))

    title = f"{ticker} · {date_label}"
    notes = yt_description or f"Trader Cho — {ticker} {date_label}"

    _gh([
        "release", "create", tag,
        "--repo", repo,
        "--title", title,
        "--notes", notes,
        *assets,
    ])

    # 다운로드 URL 조합
    owner_repo = repo
    filename = mp4.name
    download_url = f"https://github.com/{owner_repo}/releases/download/{tag}/{filename}"
    release_url  = f"https://github.com/{owner_repo}/releases/tag/{tag}"

    print(f"  ✅ 업로드 완료: {release_url}")
    result = {
        "download_url": download_url,
        "release_url": release_url,
        "tag": tag,
        "repo": repo,
        "mp4": mp4.name,
    }
    # Dashboard 보고
    try:
        import tc_report as TCR
        TCR.send("github_publish", ticker=ticker, date=date_str, status="done",
                 video_url=download_url, release_url=release_url)
    except Exception:
        pass
    return result


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("사용: python tradercho/github_publish.py outputs/ARM_20260605")
        sys.exit(1)
    result = upload(sys.argv[1])
    print(json.dumps(result, indent=2, ensure_ascii=False))
