"""scheduler.py — Trader Cho 일일 영상 자동화 스케줄러.

ET 기준 평일 (NYSE 개장일만):
  16:30 → stage00_news_scan (뉴스 수집 + 종목 선정)
  17:00 → pipeline.py --auto  (영상 생성, 실패 시 1회 재시도)

KST 매일:
  07:00 → notify.py (GitHub 업로드 + YouTube 설명 + 이메일)

pytz 로 DST 자동 처리. launchd com.tradercho.scheduler 가 상시 감시.
직접 실행:
  python tradercho/scheduler.py               # 데몬 모드
  python tradercho/scheduler.py --dry-run     # 실제 실행 없이 tick 동작 확인
  python tradercho/scheduler.py --run-now stage00
  python tradercho/scheduler.py --run-now pipeline
  python tradercho/scheduler.py --run-now notify
"""
from __future__ import annotations

import argparse
import logging
import sys
import threading
import time
from datetime import date, datetime
from pathlib import Path
import subprocess

import schedule
import pytz

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = ROOT / "state"
LOG_DIR  = ROOT / "logs"
VENV_PY  = ROOT / ".venv" / "bin" / "python"

ET  = pytz.timezone("America/New_York")
KST = pytz.timezone("Asia/Seoul")

# ET 기준 실행 시각 (hour, minute)
STAGE00_ET  = (16, 30)   # 뉴스 수집 + 종목 선정
PIPELINE_ET = (17,  0)   # 영상 생성

STAGE00_TIMEOUT  = 600   # 10분
PIPELINE_TIMEOUT = 5400  # 90분 (종목당 5~10분 × 최대 수 종목)
PIPELINE_RETRY_DELAY = 300  # 1차 실패 후 재시도 대기 5분
NOTIFY_TIMEOUT   = 300   # 5분

# KST 기준 알림 시각
NOTIFY_KST = (7, 0)     # 매일 오전 7시 KST (GitHub 업로드 + 이메일)

log = logging.getLogger("scheduler")

# 당일 실행 여부 추적 (ET 날짜 기준)
_ran: dict[str, str] = {"stage00": "", "pipeline": "", "notify": ""}
_lock = threading.Lock()


# ── 시장 개장일 확인 ──────────────────────────────────────────────────────────

def is_market_day(d: date | None = None) -> bool:
    """NYSE 개장일이면 True. pandas_market_calendars 없으면 평일 가정."""
    try:
        import pandas_market_calendars as mcal
        target = d or datetime.now(ET).date()
        cal = mcal.get_calendar("NYSE")
        sched = cal.schedule(start_date=str(target), end_date=str(target))
        return not sched.empty
    except Exception as e:
        log.warning("is_market_day 체크 실패 (%s) → 평일 가정", e)
        return True


# ── 알림 ────────────────────────────────────────────────────────────────────

def notify_failure(stage: str, error: str) -> None:
    LOG_DIR.mkdir(exist_ok=True)
    with open(LOG_DIR / "failures.log", "a") as f:
        f.write(f"{datetime.now(KST).isoformat()} {stage} FAILED\n{error[:2000]}\n---\n")
    log.error("[FAIL] %s: %s", stage, error[:200])


def notify_ready(tail: str = "") -> None:
    """영상 완성 → 게시 게이트 대기 플래그 기록."""
    STATE_DIR.mkdir(exist_ok=True)
    flag = STATE_DIR / "ready_to_review.flag"
    flag.write_text(f"ready:{datetime.now(KST).isoformat()}\n{tail}")
    log.info("✅ 영상 완성 — 게시 게이트 대기 중 (state/ready_to_review.flag)")


# ── 잡 구현 ──────────────────────────────────────────────────────────────────

def _py() -> str:
    return str(VENV_PY) if VENV_PY.exists() else sys.executable


def _log_subprocess(result: subprocess.CompletedProcess) -> None:
    out = (result.stdout or "").strip()
    if out:
        log.info(out[-2000:])
    err = (result.stderr or "").strip()
    if err:
        log.warning(err[-1000:])


def job_news_scan(dry_run: bool = False) -> bool:
    """ET 16:30 — stage00_news_scan.py 실행."""
    log.info("[%s KST] Stage00 시작", datetime.now(KST).strftime("%H:%M"))
    if dry_run:
        log.info("[DRY-RUN] stage00 스킵")
        return True
    try:
        result = subprocess.run(
            [_py(), "tradercho/stage00_news_scan.py"],
            capture_output=True, text=True,
            timeout=STAGE00_TIMEOUT, cwd=str(ROOT),
        )
        _log_subprocess(result)
        if result.returncode != 0:
            notify_failure("stage00", result.stderr or result.stdout)
            return False
        log.info("[Stage00] DONE")
        return True
    except subprocess.TimeoutExpired:
        notify_failure("stage00", f"Timeout ({STAGE00_TIMEOUT}s)")
        return False
    except Exception as e:
        notify_failure("stage00", str(e))
        return False


def job_pipeline(dry_run: bool = False, _label: str = "Pipeline") -> bool:
    """ET 17:00 — pipeline.py --auto 실행."""
    log.info("[%s KST] %s 시작", datetime.now(KST).strftime("%H:%M"), _label)
    if dry_run:
        log.info("[DRY-RUN] pipeline 스킵")
        notify_ready("[DRY-RUN]")
        return True
    try:
        result = subprocess.run(
            [_py(), "tradercho/pipeline.py", "--auto"],
            capture_output=True, text=True,
            timeout=PIPELINE_TIMEOUT, cwd=str(ROOT),
        )
        _log_subprocess(result)
        if result.returncode != 0:
            notify_failure(_label, result.stderr or result.stdout)
            return False
        notify_ready((result.stdout or "")[-500:])
        return True
    except subprocess.TimeoutExpired:
        notify_failure(_label, f"Timeout ({PIPELINE_TIMEOUT}s)")
        return False
    except Exception as e:
        notify_failure(_label, str(e))
        return False


def _pipeline_with_retry(dry_run: bool = False) -> None:
    """pipeline 실행 → 실패 시 5분 대기 후 1회 재시도."""
    ok = job_pipeline(dry_run=dry_run)
    if not ok:
        log.info("Pipeline 1차 실패 → %ds 후 재시도", PIPELINE_RETRY_DELAY)
        time.sleep(PIPELINE_RETRY_DELAY)
        job_pipeline(dry_run=dry_run, _label="Pipeline(retry)")


def job_notify(dry_run: bool = False) -> bool:
    """KST 07:00 — GitHub 업로드 + YouTube 설명 + 이메일 발송."""
    log.info("[%s KST] Notify 시작", datetime.now(KST).strftime("%H:%M"))
    if dry_run:
        log.info("[DRY-RUN] notify 스킵")
        return True
    try:
        result = subprocess.run(
            [_py(), "tradercho/notify.py"],
            capture_output=True, text=True,
            timeout=NOTIFY_TIMEOUT, cwd=str(ROOT),
        )
        _log_subprocess(result)
        if result.returncode != 0:
            notify_failure("notify", result.stderr or result.stdout)
            return False
        log.info("[Notify] DONE")
        return True
    except subprocess.TimeoutExpired:
        notify_failure("notify", f"Timeout ({NOTIFY_TIMEOUT}s)")
        return False
    except Exception as e:
        notify_failure("notify", str(e))
        return False


# ── ET-aware 틱 스케줄러 ──────────────────────────────────────────────────────

def _make_tick(dry_run: bool):
    """30초마다 호출. 목표시각과 일치하면 잡 스레드 시작."""
    def tick():
        now_et  = datetime.now(ET)
        now_kst = datetime.now(KST)

        t_et  = now_et.hour  * 60 + now_et.minute
        t_kst = now_kst.hour * 60 + now_kst.minute
        today_et  = now_et.strftime("%Y-%m-%d")
        today_kst = now_kst.strftime("%Y-%m-%d")

        s00_t    = STAGE00_ET[0]  * 60 + STAGE00_ET[1]
        pip_t    = PIPELINE_ET[0] * 60 + PIPELINE_ET[1]
        notify_t = NOTIFY_KST[0]  * 60 + NOTIFY_KST[1]

        with _lock:
            # ET 기준 평일 NYSE 개장일만
            if now_et.weekday() < 5 and is_market_day(now_et.date()):
                if t_et == s00_t and _ran["stage00"] != today_et:
                    _ran["stage00"] = today_et
                    log.info("▶ Stage00 트리거 (ET %02d:%02d)", *STAGE00_ET)
                    threading.Thread(
                        target=job_news_scan, kwargs={"dry_run": dry_run},
                        daemon=True, name="stage00",
                    ).start()

                if t_et == pip_t and _ran["pipeline"] != today_et:
                    _ran["pipeline"] = today_et
                    log.info("▶ Pipeline 트리거 (ET %02d:%02d)", *PIPELINE_ET)
                    threading.Thread(
                        target=_pipeline_with_retry, kwargs={"dry_run": dry_run},
                        daemon=True, name="pipeline",
                    ).start()

            # KST 기준 매일 (주말·공휴일 포함, 영상이 있으면 알림)
            if t_kst == notify_t and _ran["notify"] != today_kst:
                _ran["notify"] = today_kst
                log.info("▶ Notify 트리거 (KST %02d:%02d)", *NOTIFY_KST)
                threading.Thread(
                    target=job_notify, kwargs={"dry_run": dry_run},
                    daemon=True, name="notify",
                ).start()
    return tick


# ── 진입점 ───────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description="Trader Cho 자동화 스케줄러")
    ap.add_argument("--dry-run", action="store_true",
                    help="실제 실행 없이 스케줄 등록·tick 동작 확인 (로그만 출력)")
    ap.add_argument("--run-now", choices=["stage00", "pipeline", "notify"],
                    help="지금 즉시 지정 잡 1회 실행 후 종료")
    args = ap.parse_args()

    LOG_DIR.mkdir(exist_ok=True)
    handlers: list[logging.Handler] = [
        logging.FileHandler(LOG_DIR / "scheduler.log"),
    ]
    if sys.stdout.isatty():
        handlers.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(message)s",
        handlers=handlers,
    )

    log.info("=" * 60)
    log.info("Trader Cho Scheduler 시작%s", " [DRY-RUN]" if args.dry_run else "")
    log.info("  ROOT    : %s", ROOT)
    log.info("  Python  : %s", _py())
    log.info("  stage00 : ET %02d:%02d (평일 NYSE 개장일만)", *STAGE00_ET)
    log.info("  pipeline: ET %02d:%02d (평일 NYSE 개장일만)", *PIPELINE_ET)
    log.info("  notify  : KST %02d:%02d (매일)", *NOTIFY_KST)

    now_et = datetime.now(ET)
    log.info("  현재 ET : %s  market_day=%s",
             now_et.strftime("%Y-%m-%d %H:%M %Z"), is_market_day(now_et.date()))

    # --run-now: 즉시 실행 후 종료
    if args.run_now == "stage00":
        sys.exit(0 if job_news_scan(dry_run=args.dry_run) else 1)
    if args.run_now == "pipeline":
        sys.exit(0 if job_pipeline(dry_run=args.dry_run) else 1)
    if args.run_now == "notify":
        sys.exit(0 if job_notify(dry_run=args.dry_run) else 1)

    # 데몬 루프
    tick = _make_tick(dry_run=args.dry_run)
    schedule.every(30).seconds.do(tick)
    log.info("스케줄 루프 시작 (30초 간격 tick)")

    while True:
        schedule.run_pending()
        time.sleep(10)


if __name__ == "__main__":
    main()
