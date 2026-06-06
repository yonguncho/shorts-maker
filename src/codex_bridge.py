"""codex_bridge.py — Codex 적대적 공방 하네스 (Windows codex_bridge 방식 이식).

- codex exec subprocess 에 stdin 으로 프롬프트 주입, stdout 캡처.
- 응답 끝에 ===CODEX_DONE=== 마커 + JSON 판정을 요구해 안정 파싱.
- 완료조건: Codex PASS AND 최소 2라운드.
- Codex 불가/오류 시 claude --print (Haiku) 폴백.

용법:
    from .codex_bridge import debate
    result = debate(subject="...", payload_text="...", defender=my_defender_fn)
defender(attack: dict, round_no: int) -> (new_payload_text, defense_notes)
"""
from __future__ import annotations
import json
import re
import subprocess
from .common import log, ROOT

DONE_MARKER = "===CODEX_DONE==="
CODEX_TIMEOUT = 180
CLAUDE_TIMEOUT = 120

ATTACK_TEMPLATE = """You are Codex, an adversarial credibility reviewer in a financial-data pipeline.
Attack the following material for the role "{subject}".
Be skeptical and specific. Look for: HIDDEN or OVERSTATED claims, unsourced facts,
mislabeled confidence, stale data presented as fresh, logical leaps, ignored conflicting data.

MATERIAL TO ATTACK:
---
{payload}
---

PASS/FAIL CRITERIA (this is a credibility gate, not a completeness/perfection gate):
- The goal is HONESTY and DEFENSIBILITY, not Bloomberg-grade completeness.
- FAIL only if there is a MATERIAL credibility defect: an unsourced factual claim, a
  confidence label that overstates the evidence, stale data passed off as current, a
  stated rule contradicted by the data, or a logical leap.
- A KNOWN LIMITATION that is EXPLICITLY DISCLOSED (e.g. "single-vendor price feed, not
  independently verified", "news URL is an aggregator redirect", "value is last close not
  real-time") is ACCEPTABLE and must NOT by itself cause FAIL — disclosure resolves it.
- Missing extra data (VIX, futures, more vendors) is a completeness wish, NOT a credibility
  defect — do not FAIL solely for "could include more".
- PASS if every factual claim is sourced and no label overstates the evidence.

Respond with your critique, then on the FINAL lines output EXACTLY:
{marker}
{{"verdict": "PASS" or "FAIL", "issues": ["concise issue 1", "issue 2", ...]}}
The JSON must be valid and on a single line after the marker."""


def _run_codex(prompt: str) -> str | None:
    try:
        p = subprocess.run(
            ["codex", "exec", "--skip-git-repo-check"],
            input=prompt, capture_output=True, text=True,
            timeout=CODEX_TIMEOUT, cwd=str(ROOT),
        )
        if p.returncode != 0:
            log("WARN", f"codex 비정상 종료 rc={p.returncode}: {p.stderr[:200]}", "codex")
            return None
        return p.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        log("WARN", f"codex 실행 실패: {e}", "codex")
        return None


def _run_claude_fallback(prompt: str) -> str | None:
    """Codex 불가 시 claude --print (Haiku) 폴백."""
    try:
        p = subprocess.run(
            ["claude", "--print", "--model", "haiku"],
            input=prompt, capture_output=True, text=True,
            timeout=CLAUDE_TIMEOUT, cwd=str(ROOT),
        )
        if p.returncode != 0:
            log("ERROR", f"claude 폴백 실패 rc={p.returncode}: {p.stderr[:200]}", "codex")
            return None
        return p.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        log("ERROR", f"claude 폴백 실행 실패: {e}", "codex")
        return None


def _parse_verdict(output: str) -> dict:
    """stdout 에서 ===CODEX_DONE=== 뒤 JSON 추출. 실패 시 휴리스틱."""
    if DONE_MARKER in output:
        tail = output.split(DONE_MARKER, 1)[1].strip()
        m = re.search(r"\{.*\}", tail, re.DOTALL)
        if m:
            try:
                v = json.loads(m.group(0))
                v.setdefault("verdict", "FAIL")
                v.setdefault("issues", [])
                return v
            except json.JSONDecodeError:
                pass
    # 폴백 휴리스틱
    verdict = "PASS" if re.search(r"\bPASS\b", output) and not re.search(r"\bFAIL\b", output) else "FAIL"
    return {"verdict": verdict, "issues": ["(파싱 실패 — 원문 검토 필요)"], "raw_tail": output[-400:]}


def attack_once(subject: str, payload_text: str) -> dict:
    """1라운드 공격 실행. 반환: {engine, verdict, issues, ...}"""
    prompt = ATTACK_TEMPLATE.format(subject=subject, payload=payload_text, marker=DONE_MARKER)
    out = _run_codex(prompt)
    engine = "codex"
    if out is None:
        out = _run_claude_fallback(prompt)
        engine = "claude_fallback"
    if out is None:
        return {"engine": "none", "verdict": "ERROR", "issues": ["Codex/claude 모두 불가"]}
    v = _parse_verdict(out)
    v["engine"] = engine
    return v


def debate(*, subject: str, payload_text: str, defender, min_rounds: int = 2,
           max_rounds: int = 4) -> dict:
    """완료조건: Codex PASS AND 최소 min_rounds.

    defender(attack: dict, round_no: int) -> (new_payload_text, defense_notes)
      공격을 받아 자료를 보강/축소하고 갱신된 payload_text 를 반환.
    """
    rounds = []
    payload = payload_text
    r = 0
    while r < max_rounds:
        r += 1
        attack = attack_once(subject, payload)
        log("INFO", f"[{subject}] R{r} engine={attack['engine']} verdict={attack['verdict']} "
                    f"issues={len(attack.get('issues', []))}", "codex")
        new_payload, notes = defender(attack, r)
        rounds.append({"round": r, "attack": attack, "defense_notes": notes})
        payload = new_payload
        passed = attack.get("verdict") == "PASS"
        if passed and r >= min_rounds:
            return {"status": "passed", "rounds": rounds, "final_payload": payload,
                    "total_rounds": r}
    return {"status": "max_rounds_reached", "rounds": rounds, "final_payload": payload,
            "total_rounds": r}
