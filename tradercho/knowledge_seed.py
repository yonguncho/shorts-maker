"""knowledge_seed.py — docs/knowledge/*.md 를 청킹해 knowledge_base 컬렉션에 색인 (RAG R2).

청킹: '## ' 섹션 단위(이미 토픽별로 정리됨). 각 섹션 = 1 청크(50~150단어, 800토큰 미만).
메타데이터: category(문서 상단 'Category:' 라인) · source · file · section · indexed_at.
재실행 안전: id 결정론적 → upsert 로 중복 갱신.
"""
from __future__ import annotations
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rag_store

ROOT = Path(__file__).resolve().parent.parent
KNOW_DIR = ROOT / "docs" / "knowledge"


def _meta_line(text: str, key: str) -> str:
    m = re.search(rf"^{key}:\s*(.+)$", text, re.MULTILINE | re.IGNORECASE)
    return m.group(1).strip() if m else ""


def chunk_markdown(text: str):
    """'## ' 헤딩 단위로 (section_title, body) 분할."""
    parts = re.split(r"\n##\s+", text)
    chunks = []
    for p in parts[1:] if len(parts) > 1 else parts:
        lines = p.strip().split("\n", 1)
        title = lines[0].strip()
        body = lines[1].strip() if len(lines) > 1 else ""
        if body:
            chunks.append((title, f"{title}\n{body}"))
    return chunks


def seed(reset: bool = True):
    files = sorted(KNOW_DIR.glob("*.md"))
    if not files:
        print(f"지식 문서 없음: {KNOW_DIR}")
        return
    if reset:   # 깨끗한 재색인(섹션 수 변동 시 stale 청크 제거)
        try:
            rag_store.client().delete_collection("knowledge_base")
            print("knowledge_base 초기화(재색인)")
        except Exception:
            pass
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    total = 0
    for f in files:
        text = f.read_text(encoding="utf-8")
        category = _meta_line(text, "Category") or f.stem
        source = _meta_line(text, "Source") or "internal-knowledge-seed"
        chunks = chunk_markdown(text)
        ids = [f"{f.stem}__{i:02d}" for i in range(len(chunks))]
        docs = [c[1] for c in chunks]
        metas = [{"category": category, "source": source, "file": f.name,
                  "source_file": f.name, "section": c[0],
                  "position": i, "position_in_doc": f"{i+1}/{len(chunks)}",
                  "indexed_at": now} for i, c in enumerate(chunks)]
        if docs:
            rag_store.add("knowledge_base", ids, docs, metas)
            total += len(docs)
        print(f"  {f.name}: category={category} chunks={len(docs)}")
    print(f"색인 완료: {total} 청크 | knowledge_base count = {rag_store.collection('knowledge_base').count()}")


def reingest(file_name: str, section: str | None = None):
    """특정 파일(+섹션)만 재색인(전체 reset 없이 upsert). 섹션 미지정 시 파일 전체."""
    f = KNOW_DIR / file_name
    if not f.exists():
        print(f"파일 없음: {f}")
        return
    text = f.read_text(encoding="utf-8")
    category = _meta_line(text, "Category") or f.stem
    source = _meta_line(text, "Source") or "internal-knowledge-seed"
    chunks = chunk_markdown(text)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    done = 0
    for i, (title, body) in enumerate(chunks):
        if section and section.lower() not in title.lower():
            continue
        rag_store.add("knowledge_base", [f"{f.stem}__{i:02d}"], [body],
                      [{"category": category, "source": source, "file": f.name,
                        "source_file": f.name, "section": title,
                        "position": i, "position_in_doc": f"{i+1}/{len(chunks)}",
                        "indexed_at": now}])
        print(f"  재색인: {f.name} [{i:02d}] \"{title}\"")
        done += 1
    print(f"재색인 완료: {done} 청크 (section={section or 'ALL'})")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--reingest", action="store_true")
    ap.add_argument("--file")
    ap.add_argument("--section")
    a = ap.parse_args()
    if a.reingest:
        if not a.file:
            ap.error("--reingest 에는 --file 필요")
        reingest(a.file, a.section)
    else:
        seed()
