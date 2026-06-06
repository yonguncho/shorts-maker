"""rag_retrieve.py — RAG 검색·주입 (R3).

retrieve(): knowledge_base 에서 category 필터로 top_k 검색(출처·chunk_id·position·score 동반).
CLI:
  python rag_retrieve.py --query "..." [--category cat] [--top_k 3]
  python rag_retrieve.py --simulate-video --ticker ARM --hook-type curiosity_gap --catalyst earnings_beat
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rag_store

# 엣지(무관) 쿼리 자신감 판정용 임계 (score = 1 - cosine_distance)
# 실측: 진짜 매치 top1 0.57~0.74, 횡단 0.45, 무관(crypto) 0.37 → 0.40 으로 분리.
SCORE_THRESHOLD = 0.40


def retrieve(query: str, category: str | None = None, top_k: int = 3) -> list[dict]:
    where = {"category": category} if category else None
    return rag_store.query("knowledge_base", query, n=top_k, where=where)


def _similar_past(ticker: str, catalyst: str, top_k: int) -> list[dict]:
    """channel_history(자기학습)에서 유사 과거 영상. 비어있으면 []."""
    try:
        if rag_store.collection("channel_history").count() == 0:
            return []
        return rag_store.query("channel_history", f"{ticker} {catalyst}", n=top_k)
    except Exception:
        return []


def retrieve_for_video(ticker: str, hook_type: str, catalyst: str = "",
                       news_text: str = "", top_k: int = 3) -> dict:
    """영상 1편용 컨텍스트 5슬롯(hook_generator/compose 가 사용)."""
    return {
        "hook_examples": retrieve(f"{hook_type} hook {catalyst} {news_text}".strip(),
                                  "hook_formulas", top_k),
        "motion_recipe": retrieve("beat sync cut cadence pop-in ken burns shorts",
                                  "motion", top_k),
        "trust_checklist": retrieve("data chip source watermark risk disclosure timestamp",
                                    "trust", top_k),
        "similar_past": _similar_past(ticker, catalyst, top_k),
        "market_context": retrieve(f"{catalyst} {ticker} sector catalyst durability volume",
                                   "us_market", top_k),
    }


def _fmt(r: dict) -> str:
    return (f"score={r.get('score')} dist={r.get('distance')} | "
            f"cat={r.get('category')} file={r.get('source_file')} "
            f"chunk={r.get('chunk_id')} pos={r.get('position_in_doc')} sec=\"{r.get('section')}\"")


def _print(results, query, category):
    n = len(results)
    avg = round(sum(r.get("score", 0) for r in results) / n, 4) if n else 0
    flag = "  ⚠ below-threshold(무관 가능)" if (n and results[0].get("score", 0) < SCORE_THRESHOLD) else ""
    print(f"\n=== query=\"{query}\" category={category or 'ALL'} → {n} hits | top1={results[0]['score'] if n else '-'} avg={avg}{flag} ===")
    for i, r in enumerate(results, 1):
        print(f"[{i}] {_fmt(r)}")
        body = r["text"].split("\n", 1)[1] if "\n" in r["text"] else r["text"]
        print("    " + body.strip().replace("\n", " ")[:150])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--query")
    ap.add_argument("--category", default=None)
    ap.add_argument("--top_k", type=int, default=3)
    ap.add_argument("--simulate-video", action="store_true")
    ap.add_argument("--ticker", default="ARM")
    ap.add_argument("--hook-type", default="curiosity_gap")
    ap.add_argument("--catalyst", default="earnings_beat")
    a = ap.parse_args()

    if a.simulate_video:
        res = retrieve_for_video(a.ticker, a.hook_type, a.catalyst, top_k=a.top_k)
        print(f"\n=== simulate-video ticker={a.ticker} hook={a.hook_type} catalyst={a.catalyst} ===")
        for slot, items in res.items():
            print(f"\n[{slot}] {len(items)} items")
            for r in items:
                if "section" in r:
                    print(f"   - {_fmt(r)}")
                else:
                    print(f"   - {r}")
        empties = [s for s, v in res.items() if not v and s != "similar_past"]
        print(f"\n슬롯 충족: {len(res)-len([s for s,v in res.items() if not v])}/5 비어있음(similar_past 제외)={empties or '없음'}")
        return

    if not a.query:
        ap.error("--query 또는 --simulate-video 필요")
    _print(retrieve(a.query, a.category, a.top_k), a.query, a.category)


if __name__ == "__main__":
    main()
