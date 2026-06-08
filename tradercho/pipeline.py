"""pipeline.py — 원클릭 통합 (Phase 4 P2.2 + 자동화 --auto).

수동: python pipeline.py --ticker ARM --article docs/samples/arm_article.txt
자동: python pipeline.py --auto   (stage00_news_scan → today_picks.json → confidence=high 순 처리)

순서: LESSONS view → data_fetch → trader_lens → lint → rag/hook → lint → assets(로고+스톡)
      → mascot → thumbnail → compose_short → render_report → 회고(retrospective).
산출물: outputs/{ticker}_{YYYYMMDD}/ (thumbnail.png, short.mp4, *.json, render_report.json, retrospective.md).
--auto 산출물: runs/{RUN_ID}/ 하위 심볼릭 링크.
"""
from __future__ import annotations
import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pipeline_text_only as textpipe
import assets as A
import mascot as Mascot
import thumbnail as Thumb
import compose_short as Compose
import json_utils as JU
import h_stability as HS
import tc_report as TCR

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = ROOT / "state"
RUNS_DIR = ROOT / "runs"
STEPS = 12


def _step(i, msg):
    print(f"\n[{i}/{STEPS}] {msg}")


def _probe(mp4):
    try:
        d = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                            "format=duration,size", "-of", "json", str(mp4)],
                           capture_output=True, text=True)
        return json.loads(d.stdout).get("format", {})
    except Exception:
        return {}


def run(ticker, article, article_date=None, theme="terminal", skip_sec=False, out_dir=None):
    ticker = ticker.upper()
    run_date = datetime.now(timezone.utc).strftime("%Y%m%d")
    rpt = TCR.reporter(ticker, run_date)
    out_dir = Path(out_dir) if out_dir else ROOT / "outputs" / f"{ticker}_{datetime.now(timezone.utc):%Y%m%d}"
    out_dir.mkdir(parents=True, exist_ok=True)

    _step(1, "LESSONS.md 로드(운영 규칙 적용)")
    print("   ", ROOT / "docs/LESSONS.md")

    # 2~7: 텍스트 파이프라인(data_fetch→SEC→trader_lens→lint→hook→lint, 저장)
    print("\n[2-7/12] 텍스트 파이프라인(data_fetch·SEC·trader_lens·lint·RAG·hook_generator·lint)")
    pj, tj, hj = textpipe.run(ticker, article, article_date, skip_sec=skip_sec, out_dir=out_dir)

    _step(8, "assets: 로고 + 섹터 스톡 이미지 + 영상 클립")
    rpt("assets")
    sector = A.sector_for_ticker(ticker)
    logo = A.download_logo(ticker)
    try:
        stock = A.download_stock(sector)
    except Exception as e:
        stock = []; print("   ⚠ 스톡 사진 실패:", e)
    try:
        A.download_stock_video(sector)
        vframes = A.extract_video_frames(sector)
    except Exception as e:
        vframes = []; print("   ⚠ 영상 클립 실패:", e)
    print(f"    sector={sector} logo={'O' if logo else 'X'} "
          f"stock={len(stock)}장 video_frames={len(vframes)}장")
    rpt("assets", status="done", sector=sector,
        stock_count=len(stock), video_frames=len(vframes))

    _step(9, "mascot 표정 매핑")
    paths = Mascot.ensure()
    print(f"    expressions={list(paths)}")

    _step(10, "thumbnail 생성")
    thumb, layout, reason = Thumb.generate(ticker, out_dir)

    _step(11, "compose_short(영상 합성) — 수 분 소요")
    rpt("compose")
    out_mp4 = "short.mp4" if theme == "terminal" else f"short_{theme}.mp4"
    Compose.render(ticker, out_name=out_mp4, theme=theme)
    mp4 = out_dir / out_mp4

    # render_report.json (H.8 atomic write)
    fmt = _probe(mp4)
    report = {"ticker": ticker, "generated_at": datetime.now(timezone.utc).isoformat(),
              "article_date": hj.get("article_date"), "data_date": hj.get("data_date"),
              "duration_s": float(fmt.get("duration", 0) or 0), "size_bytes": int(fmt.get("size", 0) or 0),
              "cuts": len(Compose.SCENES), "logical_scenes": Compose.N_LOGICAL,
              "hook_line": hj.get("hook_line"), "volume_verdict": tj.get("volume", {}).get("verdict"),
              "thumbnail_layout": layout,
              "outputs": [p.name for p in [mp4, thumb, out_dir / "price.json",
                          out_dir / "trader_lens.json", out_dir / "hook.json",
                          out_dir / "related_dates.json"] if p.exists()]}
    JU.atomic_write_json(out_dir / "render_report.json", report)
    rpt("compose", status="done",
        duration_s=report["duration_s"], cuts=report["cuts"],
        size_bytes=report["size_bytes"], thumbnail_layout=layout)

    # H.8 stability validation
    rpt("validate")
    hs_results = HS.validate(out_dir, ticker)
    print(HS.report(hs_results))
    JU.atomic_write_json(out_dir / "video_validation.json",
                         {"h_stability": hs_results,
                          "generated_at": datetime.now(timezone.utc).isoformat()})
    hs_pass = all(v for k, v in hs_results.items() if k != "metadata_schema")
    rpt("validate", status="done" if hs_pass else "warn",
        h_stability_pass=hs_pass)

    _step(12, "회고(retrospective) — LESSONS 후보 제안")
    _retrospective(out_dir, ticker, pj, tj, hj, report)
    print(f"\n✅ 완료 → {out_dir}")
    return out_dir, report


def _retrospective(out_dir, ticker, pj, tj, hj, report):
    """이번 런 사실 + 새 lesson 후보(L5.4)."""
    verdict = tj.get("volume", {}).get("verdict")
    cand = []
    if pj.get("article_date") != hj.get("data_date"):
        cand.append("기사일≠데이터일 시 시점-앵커 훅 자동 적용 확인(결정2) — 정상.")
    if verdict == "suspect":
        cand.append("거래량 suspect인데 상승 → '왜 약한 거래량에 올랐나' 훅 각도 후보(다음 런 실험).")
    cand.append("데이터가 런마다 변동(yfinance live) → 파이프라인 시작 시 price 스냅샷 1회 후 전 단계 공유 권장(시점 일관성).")
    md = [f"# 회고 — {ticker} {report.get('data_date')}", "",
          f"- 훅: {hj.get('hook_line')}",
          f"- 거래량 판정(L2.7): {verdict} (vol_vs_avg={pj.get('vol_vs_avg')})",
          f"- 컷: {report.get('cuts')} / 길이: {report.get('duration_s'):.1f}s",
          f"- 썸네일 레이아웃: {report.get('thumbnail_layout')}", "",
          "## LESSONS 후보 (검토용, 자동 반영 안 함)"]
    md += [f"- {c}" for c in cand]
    (out_dir / "retrospective.md").write_text("\n".join(md) + "\n")
    print("    retrospective.md +", len(cand), "lesson 후보")


def run_auto(theme: str = "brightnews", min_confidence: str = "high") -> list[dict]:
    """--auto 모드: stage00 실행 → picks → 종목별 run().
    min_confidence: 'high'만 처리, 없으면 'medium'도 포함.
    반환: [{ticker, out_dir, report, pick}]
    """
    import stage00_news_scan as S0

    RUN_ID = datetime.now(timezone.utc).strftime("run_%Y%m%d_%H%M%S")
    run_dir = RUNS_DIR / RUN_ID
    run_dir.mkdir(parents=True, exist_ok=True)
    print(f"\n[AUTO] RUN_ID={RUN_ID}")

    # stage00: 뉴스 수집 + 종목 선정
    print("\n[AUTO-0] stage00_news_scan …")
    picks = S0.run()
    if not picks:
        print("  ⚠ picks 없음. 종료.")
        return []

    # 우선순위: high → medium → low
    _order = {"high": 0, "medium": 1, "low": 2}
    sorted_picks = sorted(picks, key=lambda p: _order.get(p.get("confidence", "low"), 3))
    if min_confidence == "high":
        selected = [p for p in sorted_picks if p.get("confidence") == "high"]
        if not selected:
            print("  ⚠ high confidence 없음 → medium도 포함")
            selected = [p for p in sorted_picks if p.get("confidence") in ("high", "medium")]
    else:
        selected = sorted_picks
    if not selected:
        print("  ⚠ 선정 종목 없음. 종료.")
        return []

    results = []
    for pick in selected:
        ticker = pick["ticker"]
        article_url = pick.get("article_url", "")
        import article_fetch as AF
        import news_fetch as NF
        article_text = None

        # A0.5: url_valid=False → news_fetch.fetch_latest() 폴백 (RSS 홈URL 대응)
        if not pick.get("url_valid", True):
            print(f"\n[AUTO] ⚠ {ticker} url_valid=false → news_fetch 폴백")
            try:
                article_text, meta = NF.fetch_latest(ticker)
                if len(article_text.strip()) < AF.MIN_CHARS:
                    article_text = None
                else:
                    article_url = meta.get("url", article_url)
                    print(f"    [폴백] {len(article_text)}chars from {article_url[:60]}")
            except Exception as e:
                print(f"    [폴백] fetch_latest 실패: {e}")
            if article_text is None:
                print(f"\n[AUTO] ✗ {ticker} 스킵 (폴백도 본문 없음)")
                results.append({"ticker": ticker, "skipped": "url_invalid_no_fallback",
                                "article_url": article_url, "pick": pick})
                continue
        else:
            # A0.6: article_url에서 본문 취득 — 100자 미만이면 스킵
            try:
                article_text = AF.fetch(article_url)
                if len(article_text.strip()) < AF.MIN_CHARS:
                    print(f"\n[AUTO] ✗ {ticker} 스킵 (기사 본문 {len(article_text.strip())}자 미만 — A0.6)")
                    results.append({"ticker": ticker, "skipped": "article_too_short",
                                    "article_url": article_url, "pick": pick})
                    continue
                print(f"    article: {len(article_text)} chars from {article_url[:60]}")
            except Exception as e:
                print(f"\n[AUTO] ✗ {ticker} 스킵 (article_fetch 실패: {e})")
                results.append({"ticker": ticker, "skipped": "article_fetch_failed",
                                "article_url": article_url, "pick": pick})
                continue

        print(f"\n[AUTO] ▶ {ticker}  ({pick.get('confidence')} / {pick.get('catalyst_type')})")
        try:
            out_dir, report = run(ticker, article=article_text, article_date=None, theme=theme)
            results.append({"ticker": ticker, "out_dir": str(out_dir),
                            "report": report, "pick": pick})
            # runs/ 하위에 심볼릭 링크
            link = run_dir / ticker
            if not link.exists():
                link.symlink_to(out_dir)
        except Exception as e:
            print(f"  ✗ {ticker} 실패: {e}")
            results.append({"ticker": ticker, "error": str(e), "pick": pick})

    summary = {"run_id": RUN_ID, "generated_at": datetime.now(timezone.utc).isoformat(),
               "results": results}
    JU.atomic_write_json(run_dir / "run_summary.json", summary)
    print(f"\n[AUTO] 완료 → {run_dir}")
    return results


def main():
    ap = argparse.ArgumentParser(
        description="TRADER CHO pipeline (수동: --ticker, 자동: --auto)")
    ap.add_argument("--ticker", default=None, help="종목 티커 (수동 모드)")
    ap.add_argument("--article", default=None)
    ap.add_argument("--article-date", default=None)
    ap.add_argument("--theme", default="brightnews", choices=["terminal", "brightnews"])
    ap.add_argument("--auto", action="store_true",
                    help="stage00 자동 종목 선정 → 배치 처리")
    ap.add_argument("--min-confidence", default="high", choices=["high", "medium", "low"],
                    help="--auto 모드에서 처리할 최소 confidence")
    ap.add_argument("--skip-sec", action="store_true", help="SEC 8-K 취득 스킵")
    ap.add_argument("--out-dir", default=None, help="출력 디렉토리 직접 지정 (기본: outputs/{TICKER}_{YYYYMMDD})")
    a = ap.parse_args()

    if a.auto:
        run_auto(theme=a.theme, min_confidence=a.min_confidence)
    elif a.ticker:
        run(a.ticker, a.article, a.article_date, a.theme, skip_sec=a.skip_sec, out_dir=a.out_dir)
    else:
        ap.error("--ticker 또는 --auto 중 하나 필요")


if __name__ == "__main__":
    main()
