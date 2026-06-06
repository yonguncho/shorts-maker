"""rag_store.py — ChromaDB 로컬 벡터DB (RAG R1).

임베딩 = ChromaDB 내장 DefaultEmbeddingFunction(ONNX all-MiniLM-L6-v2, 로컬·무료, torch 불필요).
컬렉션 3개:
  - knowledge_base : 외부 도메인 지식(영구)
  - channel_history: 채널 영상 성과(자기학습)
  - market_context : 최근 시장 이슈/종목 컨텍스트(단기)
persist_dir = <project>/rag_db
"""
from __future__ import annotations
from pathlib import Path

import chromadb

ROOT = Path(__file__).resolve().parent.parent
RAG_DIR = ROOT / "rag_db"
COLLECTIONS = ("knowledge_base", "channel_history", "market_context")

_client = None


def client():
    global _client
    if _client is None:
        RAG_DIR.mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(path=str(RAG_DIR))
    return _client


def collection(name: str):
    if name not in COLLECTIONS:
        raise ValueError(f"unknown collection: {name} (use one of {COLLECTIONS})")
    return client().get_or_create_collection(name=name, metadata={"hnsw:space": "cosine"})


def ensure_collections():
    return {c: collection(c).count() for c in COLLECTIONS}


def add(name: str, ids, documents, metadatas):
    """upsert(중복 id 갱신)."""
    collection(name).upsert(ids=list(ids), documents=list(documents), metadatas=list(metadatas))


def query(name: str, text: str, n: int = 3, where: dict | None = None) -> list[dict]:
    """검색 → [{text, distance, ...metadata}] (가까운 순). 항상 출처 메타 포함(강제 제약 10)."""
    res = collection(name).query(query_texts=[text], n_results=n,
                                 where=where or None,
                                 include=["documents", "metadatas", "distances"])
    out = []
    ids = (res.get("ids") or [[]])[0]
    docs = (res.get("documents") or [[]])[0]
    metas = (res.get("metadatas") or [[]])[0]
    dists = (res.get("distances") or [[]])[0]
    for cid, d, m, dist in zip(ids, docs, metas, dists):
        dist = float(dist)
        item = {"chunk_id": cid, "text": d, "distance": round(dist, 4),
                "score": round(1.0 - dist, 4)}   # cosine 유사도(1-거리)
        item.update(m or {})
        out.append(item)
    return out


def stats() -> dict:
    return {c: collection(c).count() for c in COLLECTIONS}


if __name__ == "__main__":
    print("collections:", stats(), "| persist:", RAG_DIR)
