"""pipeline_text_only.py — Phase 3 텍스트 파이프라인 CLI (영상 합성 전).

흐름: data_fetch → trader_lens → lint(trader) → hook_generator → lint(hook)
     → outputs/{ticker}_{YYYYMMDD}/{price.json, trader_lens.json, hook.json}
사용: python pipeline_text_only.py --ticker ARM --article docs/samples/arm_article.txt
"""
from __future__ import annotations
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import data_fetch
import trader_lens
import hook_generator
import lint_script
import json_utils as JU
import news_fetch as NF
import sec_fetch as SF
import tc_report as TCR

ROOT = Path(__file__).resolve().parent.parent


def run(ticker: str, article_path: str = None, article_date: str = None,
        skip_sec: bool = False, out_dir: Path = None):
    run_date = datetime.now(timezone.utc).strftime("%Y%m%d")
    rpt = TCR.reporter(ticker.upper(), run_date)

    print(f"\n[0] LESSONS.md 로드 → {ROOT/'docs/LESSONS.md'} (운영 규칙 적용)")
    if article_path:
        p = Path(article_path)
        article = p.read_text(encoding="utf-8") if p.exists() else article_path
        if len(article.strip()) < 100:
            rpt("error", status="error", error="article_too_short")
            raise ValueError(
                f"[FAIL] Article for {ticker} is empty or too short "
                f"({len(article.strip())} chars). Pipeline stopped."
            )
    else:
        # --article 생략 시 yfinance .news에서 당일 기사 자동 취득
        print(f"    --article 미지정 → yfinance 당일 뉴스 자동 취득 ({ticker})")
        rpt("news_fetch")
        article_text, meta = NF.fetch_latest(ticker)
        article = article_text
        if not article_date:
            article_date = meta.get("pub_date") or None
        print(f"    source={meta.get('source')} pub={meta.get('pub_date')} url={meta.get('url','')[:60]}")
        rpt("news_fetch", status="done",
            source=meta.get("source", ""), pub_date=meta.get("pub_date", ""))

    # Finviz 헤드라인 취득 (보조 컨텍스트 — 실패해도 파이프라인 중단 없음)
    print(f"[0b] Finviz 헤드라인 취득 …")
    finviz_headlines = NF.fetch_finviz(ticker)

    print("[1] data_fetch … (단일 스냅샷, 이후 재페치 금지 — L0.4)")
    rpt("data_fetch")
    pj = data_fetch.fetch(ticker)
    pj["fetched_at_utc"] = datetime.now(timezone.utc).isoformat()
    if pj.get("warnings"):
        print("    ⚠", pj["warnings"])
    # 신선도 검증: as_of 가 오늘 대비 몇 일 경과했는지 확인
    try:
        _as_of_date = datetime.fromisoformat(pj["as_of"]).date()
        _today = datetime.now(timezone.utc).date()
        _days_stale = (_today - _as_of_date).days
        if _days_stale == 0:
            print(f"    as_of={pj['as_of'][:10]}  ✓ 당일 데이터")
        elif _days_stale <= 3:
            print(f"    ⚠ STALE: as_of={pj['as_of'][:10]}  ({_days_stale}일 경과 — 주말/공휴일 여부 확인)")
        else:
            rpt("error", status="error", error=f"stale_data_{_days_stale}d")
            raise ValueError(
                f"[FAIL] 데이터 {_days_stale}일 경과 (as_of={pj['as_of'][:10]}) — "
                f"장 마감 후 재실행하거나 yfinance 데이터 상태 확인 필요 (L0.4)"
            )
    except ValueError:
        raise
    except Exception:
        pass
    rpt("data_fetch", status="done",
        pct_change=pj.get("pct_change"), last_close=pj.get("last_close"),
        vol_vs_avg=pj.get("vol_vs_avg"), rsi=pj.get("rsi"),
        analyst_target=((pj.get("analyst") or {}).get("price_targets") or {}).get("mean"))

    # 출력 디렉토리 조기 생성 (SEC 저장 등 이후 단계에서 공용)
    out = Path(out_dir) if out_dir else ROOT / "outputs" / f"{ticker.upper()}_{datetime.now(timezone.utc):%Y%m%d}"
    out.mkdir(parents=True, exist_ok=True)

    # SEC 8-K 공시 취득 (skip_sec=True 시 스킵)
    sec_result = None
    if not skip_sec:
        print("[1b] SEC 8-K 공시 취득 …")
        data_date_str = str(pj.get("as_of", ""))[:10] or None
        sec_result = SF.fetch(ticker, date=data_date_str)
        rpt("sec_fetch", status="done",
            has_8k=sec_result.get("has_8k", False),
            filings_count=len(sec_result.get("filings", [])))

    print("[2] trader_lens …")
    rpt("trader_lens")
    tj, eng1 = trader_lens.extract(ticker, article, pj,
                                   sec8k=sec_result,
                                   finviz_headlines=finviz_headlines)
    print(f"    engine={eng1}")
    rpt("trader_lens", status="done",
        catalyst_type=tj.get("catalyst", {}).get("type", ""),
        durability=tj.get("catalyst", {}).get("durability", ""),
        volume_verdict=tj.get("volume", {}).get("verdict", ""))

    print("[3] lint(trader_json) …")
    rpt("lint")
    lint_script.check_trader(tj)
    hedged = lint_script.hedging_present(json.dumps(tj))
    print(f"    PASS (hedging present={hedged})")
    rpt("lint", status="done", hedged=hedged)

    print("[4] hook_generator (RAG) …")
    rpt("hook_gen")
    data_date = str(pj.get("as_of") or "")[:10] or None
    hj, eng2 = hook_generator.generate(ticker, tj, article_date=article_date, data_date=data_date,
                                       price_pct=pj.get("pct_change"), rsi=pj.get("rsi"))
    ta = hj.get("time_anchored")
    print(f"    engine={eng2} framework={hj.get('hook_framework')} "
          f"time_anchored={ta} (art={hj.get('article_date')} data={hj.get('data_date')} "
          f"stale={hj.get('days_stale')}d)")

    print("[5] lint(hook_json) …")
    rpt("hook_lint")
    lint_script.check_hook(hj)
    print("    PASS")
    rpt("hook_lint", status="done",
        hook_line=hj.get("hook_line", ""),
        hook_framework=hj.get("hook_framework", ""))

    # series_3m 포함 저장(P0.1: compose/thumbnail가 재페치 없이 동일 스냅샷 사용). H.8 atomic write.
    JU.atomic_write_json(out / "price.json", pj)
    JU.atomic_write_json(out / "trader_lens.json", tj)
    JU.atomic_write_json(out / "hook.json", hj)
    if sec_result:
        JU.atomic_write_json(out / "sec_8k.json", sec_result)
    print(f"\n저장: {out}")
    return pj, tj, hj


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticker", required=True)
    ap.add_argument("--article", default=None)
    ap.add_argument("--article-date", default=None,
                    help="기사/촉매 보도일 YYYY-MM-DD (데이터일과 다르면 시점-앵커 훅). 미지정 시 동일세션 가정.")
    ap.add_argument("--skip-sec", action="store_true", help="SEC 8-K 취득 스킵")
    ap.add_argument("--out-dir", default=None, help="출력 디렉토리 직접 지정 (기본: outputs/{TICKER}_{YYYYMMDD})")
    a = ap.parse_args()
    pj, tj, hj = run(a.ticker, a.article, a.article_date, skip_sec=a.skip_sec,
                     out_dir=a.out_dir)
    print("\n===== price.json =====");  print(json.dumps(pj, indent=2, ensure_ascii=False))
    print("\n===== trader_lens.json =====");  print(json.dumps(tj, indent=2, ensure_ascii=False))
    print("\n===== hook.json =====");  print(json.dumps(hj, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
