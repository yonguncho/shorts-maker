"""rag_store.py — 출처중심 RAG 저장소 (SQLite).

임베딩 대신 출처 메타데이터·등급·교차검증·신선도·키워드 검색에 집중.
신빙성 검증(verify.py)의 근거 저장소이자, 추후 ⑩ 단계의 교훈/성과 누적 대상.

문서(document) 한 건 = 수집된 사실 단위(가격 1건, 뉴스 1건, 공시 1건 등).
"""
from __future__ import annotations
import sqlite3
from pathlib import Path
from typing import Iterable

from .common import RAG_DIR, utc_now, sha256

DB_PATH = RAG_DIR / "rag.db"

# 출처 등급: 낮을수록 신뢰. 1차(SEC공시)=1 > 2차(뉴스/시장데이터)=2 > 3차(집계/2차가공)=3
SOURCE_GRADE = {
    "sec": 1,
    "finnhub_quote": 2,
    "news": 2,
    "yfinance": 2,      # 과거 시계열(가격) — 2차 시장데이터
    "aggregate": 3,
    "derived": 3,       # 계산된 사실(상관관계 등) — 가공
    "trends": 3,        # 검색량(Google Trends) — 집계
    "social": 3,        # 소셜 언급량(Reddit) — 집계, 사실귀속 표현으로만
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id            TEXT PRIMARY KEY,   -- 콘텐츠 해시 기반(중복 방지)
    kind          TEXT NOT NULL,      -- quote | news | filing | derived
    source        TEXT NOT NULL,      -- 출처명 (finnhub, sec_edgar, reuters 등)
    source_type   TEXT NOT NULL,      -- SOURCE_GRADE 키
    grade         INTEGER NOT NULL,   -- 출처 등급 (1/2/3)
    ticker        TEXT,               -- 관련 종목/심볼 (있으면)
    title         TEXT,
    content       TEXT NOT NULL,      -- 사실 본문/요약
    url           TEXT,               -- 출처 URL/문서ID
    published_utc TEXT,               -- 원문 발행 시각 (있으면)
    fetched_utc   TEXT NOT NULL,      -- 수집 시각
    extra_json    TEXT                -- 부가 데이터(JSON 문자열)
);
CREATE INDEX IF NOT EXISTS idx_docs_ticker ON documents(ticker);
CREATE INDEX IF NOT EXISTS idx_docs_kind ON documents(kind);
CREATE INDEX IF NOT EXISTS idx_docs_published ON documents(published_utc);
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def doc_id(kind: str, source: str, content: str, url: str = "") -> str:
    return sha256(f"{kind}|{source}|{url}|{content}")[:24]


def add_document(conn, *, kind, source, source_type, ticker=None, title=None,
                 content="", url=None, published_utc=None, extra_json=None) -> str:
    """문서 1건 추가(중복 id면 무시). 반환: doc id."""
    grade = SOURCE_GRADE.get(source_type, 3)
    did = doc_id(kind, source, content, url or "")
    conn.execute(
        """INSERT OR IGNORE INTO documents
           (id, kind, source, source_type, grade, ticker, title, content, url, published_utc, fetched_utc, extra_json)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (did, kind, source, source_type, grade, ticker, title, content, url,
         published_utc, utc_now(), extra_json),
    )
    return did


def search(conn, *, keyword=None, kind=None, ticker=None, since_utc=None, limit=50) -> list[dict]:
    """키워드/종류/종목/신선도 기반 검색."""
    q = "SELECT * FROM documents WHERE 1=1"
    args: list = []
    if keyword:
        q += " AND (content LIKE ? OR title LIKE ?)"
        args += [f"%{keyword}%", f"%{keyword}%"]
    if kind:
        q += " AND kind = ?"; args.append(kind)
    if ticker:
        q += " AND ticker = ?"; args.append(ticker)
    if since_utc:
        q += " AND COALESCE(published_utc, fetched_utc) >= ?"; args.append(since_utc)
    q += " ORDER BY grade ASC, COALESCE(published_utc, fetched_utc) DESC LIMIT ?"
    args.append(limit)
    return [dict(r) for r in conn.execute(q, args).fetchall()]


def cross_reference(conn, *, keyword: str, ticker=None) -> list[dict]:
    """같은 사실을 뒷받침하는 서로 다른 출처를 찾는다(교차검증용)."""
    rows = search(conn, keyword=keyword, ticker=ticker, limit=100)
    # 출처(source)별로 묶어 반환
    by_source: dict[str, list[dict]] = {}
    for r in rows:
        by_source.setdefault(r["source"], []).append(r)
    return [{"source": s, "count": len(v), "grade": min(d["grade"] for d in v)} for s, v in by_source.items()]


def stats(conn) -> dict:
    total = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    by_kind = {r[0]: r[1] for r in conn.execute("SELECT kind, COUNT(*) FROM documents GROUP BY kind")}
    by_grade = {r[0]: r[1] for r in conn.execute("SELECT grade, COUNT(*) FROM documents GROUP BY grade")}
    return {"total": total, "by_kind": by_kind, "by_grade": by_grade}
