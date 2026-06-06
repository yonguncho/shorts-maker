"""llm.py — LLM 호출 헬퍼 (codex exec → claude --print 폴백) + 견고한 JSON 파싱.

trader_lens / hook_generator 가 사용. 외부 의존 없이 CLI 서브프로세스로 호출.
"""
from __future__ import annotations
import json
import subprocess

MARKER = "===JSON==="
CODEX_TIMEOUT = 180
CLAUDE_TIMEOUT = 150


def _run_codex(prompt: str) -> str | None:
    try:
        p = subprocess.run(["codex", "exec", "--skip-git-repo-check"], input=prompt,
                           capture_output=True, text=True, timeout=CODEX_TIMEOUT)
        return p.stdout if p.returncode == 0 else None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def _run_claude(prompt: str) -> str | None:
    try:
        p = subprocess.run(["claude", "--print", "--model", "haiku"], input=prompt,
                           capture_output=True, text=True, timeout=CLAUDE_TIMEOUT)
        return p.stdout if p.returncode == 0 else None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def call(prompt: str) -> tuple[str | None, str]:
    out = _run_codex(prompt)
    if out is not None:
        return out, "codex"
    out = _run_claude(prompt)
    return out, ("claude" if out is not None else "none")


def _extract_json(text: str):
    """{ } 또는 [ ] 최상위 JSON 구조 추출."""
    if not text:
        return None
    tail = text.split(MARKER, 1)[1] if MARKER in text else text
    obj_start = tail.find("{")
    arr_start = tail.find("[")
    if obj_start < 0 and arr_start < 0:
        return None
    if arr_start >= 0 and (obj_start < 0 or arr_start < obj_start):
        open_c, close_c, start = "[", "]", arr_start
    else:
        open_c, close_c, start = "{", "}", obj_start
    depth = 0
    for i in range(start, len(tail)):
        if tail[i] == open_c:
            depth += 1
        elif tail[i] == close_c:
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(tail[start:i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def call_json(prompt: str) -> tuple[dict | list | None, str]:
    """LLM 호출 → JSON dict 또는 list 파싱. (obj|None, engine)."""
    out, engine = call(prompt)
    return _extract_json(out or ""), engine
