"""json_utils.py — atomic JSON write + H.8 schema validators (H.8)."""
from __future__ import annotations
import json
from pathlib import Path

# H.8 atomic write 대상 파일명 목록 (참조용)
ATOMIC_TARGETS = frozenset({
    "manifest.json", "pipeline_status.json", "current_run.json",
    "price.json", "script.json", "video_validation.json",
    "assets_manifest.json", "publish_snapshot.json",
    "compliance_report.json", "timeline.json", "metadata.json",
})


def atomic_write_json(path, data: dict | list) -> None:
    """Write JSON atomically: .tmp → rename. 전원 차단/크래시 시 부분 쓰기 방지."""
    p = Path(path)
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    tmp = p.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(p)


# ── schema validators ──────────────────────────────────────────────────────

_PRICE_REQUIRED = frozenset({
    "ticker", "last_close", "pct_change", "as_of", "rsi", "vol_vs_avg",
})


def check_price_schema(price: dict) -> list[str]:
    issues = [f"price.json missing field: {k}" for k in sorted(_PRICE_REQUIRED - price.keys())]
    if price.get("pct_change") is None:
        issues.append("price.json pct_change is null")
    if not price.get("as_of"):
        issues.append("price.json as_of is empty")
    return issues


_META_REQUIRED = frozenset({"titles", "description", "hashtags", "tags"})


def check_metadata_schema(meta: dict) -> list[str]:
    return [f"metadata.json missing field: {k}" for k in sorted(_META_REQUIRED - meta.keys())]


def check_timeline_schema(tl: dict) -> list[str]:
    """timeline.json 내 null 금지 항목 검사."""
    issues = []
    if tl.get("total_duration") is None:
        issues.append("timeline.json total_duration is null")
    for s in tl.get("scenes", []):
        name = s.get("name", f"prog={s.get('prog')}")
        if s.get("start") is None:
            issues.append(f"timeline.json scene '{name}' start is null")
        if s.get("end") is None:
            issues.append(f"timeline.json scene '{name}' end is null")
    return issues
