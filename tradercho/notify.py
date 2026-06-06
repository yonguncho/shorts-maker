"""notify.py — 일일 영상 완성 알림 + YouTube 설명 생성.

흐름:
  1. 최근 완성된 영상 탐색 (outputs/ 내 12h 이내 MP4)
  2. GitHub Release 업로드 → download URL
  3. YouTube 설명 생성
  4. 이메일 발송 (GMAIL_APP_PASSWORD 설정 시)
  5. docs/daily_reports/report_YYYYMMDD.md 저장 (항상 — 이메일 실패 시 대체)

사용:
  python tradercho/notify.py              # 최근 영상 자동 탐지
  python tradercho/notify.py --dry-run    # 업로드/발송 없이 내용 확인
"""
from __future__ import annotations

import argparse
import json
import logging
import smtplib
import sys
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUTS_DIR   = ROOT / "outputs"
REPORTS_DIR   = ROOT / "docs" / "daily_reports"
STATE_DIR     = ROOT / "state"
LOG_DIR       = ROOT / "logs"

TO_EMAIL = "yongun.cho03@gmail.com"
FROM_EMAIL = "yongun.cho03@gmail.com"

log = logging.getLogger("notify")


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


# ── 영상 탐색 ─────────────────────────────────────────────────────────────────

def find_recent_outputs(hours: int = 12) -> list[Path]:
    """최근 N시간 내에 생성된 출력 디렉터리 목록 반환."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    results = []
    if not OUTPUTS_DIR.exists():
        return results
    for d in sorted(OUTPUTS_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not d.is_dir():
            continue
        # 디렉터리명 패턴: TICKER_YYYYMMDD
        parts = d.name.rsplit("_", 1)
        if len(parts) != 2 or not parts[1].isdigit() or len(parts[1]) != 8:
            continue
        # MP4 확인
        candidates = list(d.glob("*.mp4"))
        if not candidates:
            continue
        mp4 = max(candidates, key=lambda p: p.stat().st_mtime)
        # 최근 여부
        mtime = datetime.fromtimestamp(mp4.stat().st_mtime, tz=timezone.utc)
        if mtime >= cutoff:
            results.append(d)
    return results


# ── YouTube 설명 생성 ─────────────────────────────────────────────────────────

def make_youtube_description(out_dir: Path) -> str:
    """output 디렉터리의 JSON에서 YouTube 설명 생성."""
    ticker = out_dir.name.rsplit("_", 1)[0]
    date_str = out_dir.name.rsplit("_", 1)[1]
    try:
        d = datetime.strptime(date_str, "%Y%m%d")
        date_label = d.strftime("%b %-d, %Y")
    except Exception:
        date_label = date_str

    # 데이터 로드
    price = _load_json(out_dir / "price.json")
    hook  = _load_json(out_dir / "hook.json")
    lens  = _load_json(out_dir / "trader_lens.json")
    report = _load_json(out_dir / "render_report.json")

    hook_line   = hook.get("hook_line", f"{ticker} — what happened today?")
    payoff_line = hook.get("payoff_line") or lens.get("payoff_line", "")
    catalyst    = lens.get("catalyst", {})
    cat_why     = catalyst.get("why", "")
    cat_type    = catalyst.get("type", "").replace("_", " ").title()
    cat_dur     = catalyst.get("durability", "")

    pct      = price.get("pct_change", 0)
    spx_pct  = price.get("spx_pct_change", 0)
    rsi      = price.get("rsi", "—")
    vol_x    = price.get("vol_vs_avg", "—")
    pos_52w  = price.get("position_52w", "")

    pct_sign = "+" if pct >= 0 else ""
    spx_sign = "+" if spx_pct >= 0 else ""

    # 해시태그
    sector_tags = {
        "AMD": "#AMD #semiconductors", "ARM": "#ARM #semiconductors",
        "NVDA": "#Nvidia #semiconductors", "TSLA": "#Tesla #EV",
        "AAPL": "#Apple #tech", "MSFT": "#Microsoft #tech",
        "GOOGL": "#Google #tech", "META": "#Meta #tech",
        "AMZN": "#Amazon #tech", "COIN": "#Coinbase #crypto",
    }
    base_tags = sector_tags.get(ticker, f"#{ticker}")

    lines = [
        hook_line,
        "",
        f"{ticker} ({pct_sign}{pct:.2f}%) — here's the full breakdown.",
        "",
        f"📊 Today's Numbers:",
        f"• {ticker}: {pct_sign}{pct:.2f}% ({pos_52w})" if pos_52w else f"• {ticker}: {pct_sign}{pct:.2f}%",
        f"• vs SPX: {spx_sign}{spx_pct:.2f}%",
        f"• RSI: {rsi}  |  Volume: {vol_x}x avg",
    ]

    if cat_why:
        lines += [
            "",
            f"🔍 Catalyst: {cat_type}" + (f" ({cat_dur})" if cat_dur else ""),
            cat_why,
        ]

    if payoff_line:
        lines += [
            "",
            "⚖️ The Read:",
            payoff_line,
        ]

    # 실제 데이터 날짜 (as_of 필드, 없으면 디렉터리 날짜)
    as_of_raw = price.get("as_of", "")
    try:
        data_date_label = datetime.fromisoformat(as_of_raw).strftime("%b %-d, %Y")
    except Exception:
        data_date_label = date_label

    lines += [
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"📅 Data: {data_date_label}",
        "⚠️ Not financial advice. Educational purposes only.",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        f"{base_tags} #stocks #investing #shorts #stockmarket #finance",
    ]

    return "\n".join(lines)


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


# ── 이메일 발송 ───────────────────────────────────────────────────────────────

def send_email(subject: str, body: str, app_password: str) -> bool:
    """Gmail SMTP 발송. 성공 시 True."""
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = FROM_EMAIL
        msg["To"]      = TO_EMAIL
        msg.attach(MIMEText(body, "plain", "utf-8"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(FROM_EMAIL, app_password)
            s.sendmail(FROM_EMAIL, [TO_EMAIL], msg.as_bytes())
        log.info("  ✉ 이메일 발송 → %s", TO_EMAIL)
        return True
    except Exception as e:
        log.error("  이메일 발송 실패: %s", e)
        return False


# ── 리포트 빌더 ───────────────────────────────────────────────────────────────

def _build_report(out_dir: Path, download_url: str, release_url: str,
                  yt_desc: str) -> str:
    ticker = out_dir.name.rsplit("_", 1)[0]
    date_str = out_dir.name.rsplit("_", 1)[1]
    price = _load_json(out_dir / "price.json")
    pct = price.get("pct_change", 0)
    sign = "+" if pct >= 0 else ""

    now_kst = datetime.now(tz=__import__("pytz").timezone("Asia/Seoul"))

    lines = [
        f"# Trader Cho 일일 리포트 — {ticker} {date_str}",
        f"생성: {now_kst:%Y-%m-%d %H:%M KST}",
        "",
        f"## {ticker} {sign}{pct:.2f}%",
        "",
        "## 📥 영상 다운로드",
        f"- **직접 다운로드**: {download_url}" if download_url else "- ⚠ GitHub 업로드 실패 — `python tradercho/github_publish.py outputs/{out_dir.name}` 재시도",
        f"- **Release 페이지**: {release_url}" if release_url else "",
        "",
        "## 📝 YouTube 설명 (붙여넣기용)",
        "",
        "```",
        yt_desc,
        "```",
        "",
        "---",
        "> ⚠️ 게시 전 반드시 직접 확인 후 수동 업로드 (게시 게이트 유지)",
        "> Not financial advice. Educational purposes.",
    ]
    return "\n".join(lines)


# ── 메인 ─────────────────────────────────────────────────────────────────────

def run(dry_run: bool = False) -> list[dict]:
    """최근 영상 탐지 → 업로드 → 설명 생성 → 이메일 발송 → 리포트 저장."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    env = _load_env()
    app_password = env.get("GMAIL_APP_PASSWORD", "")

    recent = find_recent_outputs(hours=12)
    if not recent:
        log.warning("최근 12h 내 완성된 영상 없음")
        return []

    results = []
    email_blocks = []

    for out_dir in recent:
        ticker   = out_dir.name.rsplit("_", 1)[0]
        date_str = out_dir.name.rsplit("_", 1)[1]
        log.info("처리: %s", out_dir.name)

        yt_desc = make_youtube_description(out_dir)

        # GitHub 업로드
        download_url = release_url = ""
        if not dry_run:
            try:
                import github_publish as GP
                pub = GP.upload(out_dir, yt_description=yt_desc)
                if "error" not in pub:
                    download_url = pub["download_url"]
                    release_url  = pub["release_url"]
                else:
                    log.warning("  GitHub 업로드 실패: %s", pub["error"])
            except Exception as e:
                log.warning("  GitHub 업로드 예외: %s", e)
        else:
            download_url = "[DRY-RUN] https://github.com/.../releases/download/..."
            release_url  = "[DRY-RUN] https://github.com/.../releases/tag/..."
            log.info("  [DRY-RUN] GitHub 업로드 스킵")

        # 리포트 파일 저장
        report_text = _build_report(out_dir, download_url, release_url, yt_desc)
        report_path = REPORTS_DIR / f"report_{date_str}_{ticker}.md"
        report_path.write_text(report_text, encoding="utf-8")
        log.info("  리포트 저장: %s", report_path)

        price = _load_json(out_dir / "price.json")
        pct = price.get("pct_change", 0)
        sign = "+" if pct >= 0 else ""

        email_blocks.append({
            "ticker": ticker,
            "date_str": date_str,
            "pct": f"{sign}{pct:.2f}%",
            "download_url": download_url,
            "release_url": release_url,
            "yt_desc": yt_desc,
            "report_path": str(report_path),
        })
        results.append({"ticker": ticker, "report_path": str(report_path),
                        "download_url": download_url})

    # 이메일 조합 + 발송
    if email_blocks:
        subject, body = _build_email(email_blocks)
        if not dry_run and app_password:
            send_email(subject, body, app_password)
        elif dry_run:
            log.info("[DRY-RUN] 이메일 내용 미리보기:\n\nSUBJECT: %s\n\n%s", subject, body[:1500])
        else:
            log.warning("GMAIL_APP_PASSWORD 미설정 → 이메일 발송 스킵. 리포트: %s",
                        ", ".join(b["report_path"] for b in email_blocks))

    return results


def _build_email(blocks: list[dict]) -> tuple[str, str]:
    """이메일 제목·본문 생성. 여러 종목 있으면 합산."""
    tickers = " / ".join(b["ticker"] for b in blocks)
    date_str = blocks[0]["date_str"]
    try:
        d = datetime.strptime(date_str, "%Y%m%d")
        date_label = d.strftime("%b %-d, %Y")
    except Exception:
        date_label = date_str

    subject = f"[Trader Cho] {tickers} — {date_label} 영상 준비 완료"

    parts = ["안녕하세요!\n\nTrader Cho 오늘의 영상이 준비되었습니다. 아래 링크로 다운로드 후 검토하세요.\n"]

    for b in blocks:
        parts.append("━" * 50)
        parts.append(f"  {b['ticker']}  {b['pct']}  |  {date_label}")
        parts.append("━" * 50)
        if b["download_url"]:
            parts.append(f"\n📥 다운로드\n  {b['download_url']}\n  Release: {b['release_url']}")
        else:
            parts.append("\n⚠️ GitHub 업로드 실패 — logs/notify.log 확인")
        parts.append(f"\n📝 YouTube 설명\n\n{b['yt_desc']}")
        parts.append(f"\n📄 전체 리포트: {b['report_path']}\n")

    parts += [
        "━" * 50,
        "⚠️  게시 전 반드시 직접 확인 후 수동 업로드하세요 (자동 게시 없음).",
        "Not financial advice. Educational purposes.",
        "━" * 50,
    ]

    return subject, "\n".join(parts)


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    LOG_DIR.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(message)s",
        handlers=[
            logging.FileHandler(LOG_DIR / "notify.log"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    ap = argparse.ArgumentParser(description="일일 영상 알림 발송")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    sys.exit(0 if run(dry_run=args.dry_run) else 1)
