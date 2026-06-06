"""lint_script.py — 헤징 강제 + 단정/인물/리스크 lint (Phase 3-4).

위반 시 LintError(어느 규칙·필드 위반인지 메시지 포함). L0.3·L2.5·인물차단·L0.2(stub).
"""
from __future__ import annotations
import re

FORBIDDEN = ["will rise", "guaranteed", "must buy", "sure thing", "100%",
             "easy money", "to the moon", "skyrocket"]
ASSERTIVE_RE = re.compile(
    r"\b(will\s+(rise|soar|jump|surge|double|crash|fall)|is going to|definitely|"
    r"guaranteed|certain to|can't lose|cannot lose)\b", re.IGNORECASE)
HEDGES = ["likely", "appears", "could", "may", "based on", "as of", "suggests", "indicates"]
PERSON_BLACKLIST = ["musk", "buffett", "powell", "huang", "jensen huang",
                    "cook", "zuckerberg", "bezos", "dimon", "yellen"]


class LintError(Exception):
    pass


def check_text(text: str, field: str):
    low = (text or "").lower()
    for w in FORBIDDEN:
        if w in low:
            raise LintError(f"[L0.3 forbidden] '{w}' in {field}: \"{text[:80]}\"")
    m = ASSERTIVE_RE.search(text or "")
    if m:
        raise LintError(f"[L0.3 assertive] '{m.group(0)}' in {field}: \"{text[:80]}\"")


def check_person(text: str, field: str):
    low = f" {(text or '').lower()} "
    for p in PERSON_BLACKLIST:
        if re.search(rf"\b{re.escape(p)}\b", low):
            raise LintError(f"[person] '{p}' in {field} (실존 인물 추출 금지)")


def five_word_overlap(text: str, corpus_texts: list[str]) -> list[str]:
    """L0.2/external_learner 대비 stub — 5단어 이상 연속 일치 검출(이번 단계 미사용)."""
    return []


def _walk_strings(obj, prefix=""):
    if isinstance(obj, str):
        yield prefix, obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk_strings(v, f"{prefix}.{k}" if prefix else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _walk_strings(v, f"{prefix}[{i}]")


def check_trader(trader_json: dict):
    if not (trader_json.get("risk") or "").strip():
        raise LintError("[L2.5] risk 필드 비어있음 — 리스크 의무")
    for field in ("hook_seed", "payoff_line"):
        check_text(trader_json.get(field, ""), field)
    check_text((trader_json.get("catalyst") or {}).get("why", ""), "catalyst.why")
    for path, s in _walk_strings(trader_json):
        check_person(s, path)
    return True


def check_hook(hook_json: dict):
    for field in ("hook_line", "payoff_line"):
        check_text(hook_json.get(field, ""), field)
        check_person(hook_json.get(field, ""), field)
    return True


def hedging_present(text: str) -> bool:
    low = (text or "").lower()
    return any(h in low for h in HEDGES)


if __name__ == "__main__":
    # 자가 테스트
    try:
        check_text("This stock will rise tomorrow", "test")
    except LintError as e:
        print("OK caught:", e)
    try:
        check_person("The CEO said so", "test")
    except LintError as e:
        print("OK caught:", e)
    print("clean text passes:", check_text("ARM likely appears extended", "test") is None)
