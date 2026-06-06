"""common.py — shorts_maker 파이썬 공통 유틸 (경로/.env/UTC/로그/원자적 JSON)."""
from __future__ import annotations
import json
import os
import sys
import hashlib
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = ROOT / "state"
RAG_DIR = ROOT / "rag"
OUTPUT_DIR = ROOT / "output"
LOG_DIR = ROOT / "logs"
SHARED_DIR = ROOT / "shared"
for _d in (STATE_DIR, RAG_DIR, OUTPUT_DIR, LOG_DIR, SHARED_DIR):
    _d.mkdir(parents=True, exist_ok=True)


def utc_now() -> str:
    """UTC ISO8601 (초 단위, Z 접미)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


_ENV_CACHE: dict | None = None


def load_env() -> dict:
    """.env 를 읽어 dict 반환 + os.environ 에 주입. 값은 절대 로그하지 않는다."""
    global _ENV_CACHE
    if _ENV_CACHE is not None:
        return _ENV_CACHE
    env: dict[str, str] = {}
    f = ROOT / ".env"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            if k:
                env[k] = v
                os.environ.setdefault(k, v)
    _ENV_CACHE = env
    return env


def require_env(key: str) -> str:
    env = load_env()
    val = env.get(key) or os.environ.get(key)
    if not val:
        raise RuntimeError(f".env 에 {key} 가 없습니다 (값을 확인하세요).")
    return val


def log(level: str, msg: str, name: str = "pipeline") -> None:
    line = f"[{utc_now()}] [{level}] [{name}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_DIR / f"{name}.log", "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def write_json_atomic(path: Path, obj) -> None:
    """temp→rename 으로 원자적 저장 (대시보드가 반쪽 파일 읽는 것 방지)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def read_json(path: Path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def adversarial_gate_mode() -> str:
    """적대검증 게이트 동작 모드.
    - "advisory"(기본): 공방을 돌리고 지적을 기록하되, PASS 못 해도 파이프라인은 진행(경고).
    - "blocking": 공방 미통과(max_rounds_reached) 시 단계 실패(rc!=0)로 파이프라인 정지.
    환경변수 ADVERSARIAL_GATE_MODE 로 제어(2026-06-01 결정: 노이즈 뉴스 피드에 게이트가 구조적
    미수렴 → 기본 advisory. 뉴스소스 정제 후 blocking 으로 복원 가능)."""
    val = (os.environ.get("ADVERSARIAL_GATE_MODE") or load_env().get("ADVERSARIAL_GATE_MODE") or "advisory").strip().lower()
    return "blocking" if val == "blocking" else "advisory"
