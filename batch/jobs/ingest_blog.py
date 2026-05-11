"""블로그 포스트 ingest 잡.

흐름:
  mer_blog_posts (Postgres) → 미인덱싱 포스트만 → Node → embed → Qdrant + BM25 + mer_nodes
  배치마다 embed → upsert → record 즉시 처리 (중간 실패 시 이어서 재시작 가능)
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone

from tqdm import tqdm

from app.mer_persona.core.config import get_settings
from app.mer_persona.core.logging import configure_logging, get_logger
from app.shared.db.session import get_sync_session
from batch.ingest import bm25_store, qdrant_writer
from batch.ingest.metadata_builder import enrich_metadata
from batch.ingest.node_parser import parse_nodes

logger = get_logger(__name__)

_COLLECTION = "mer_blog"
_EMBED_BATCH = 32


def _load_unindexed_posts(since: str | None = None) -> list[dict]:
    """mer_nodes에 없는 포스트를 mer_blog_posts에서 조회한다."""
    from sqlalchemy import text

    with get_sync_session() as session:
        indexed: set[str] = {
            row[0] for row in session.execute(
                text("SELECT source_id FROM mer_nodes WHERE source_type = 'blog'")
            )
        }
        rows = session.execute(
            text("SELECT post_id_src, title, url, published_at, category, raw_text, hash "
                 "FROM mer_blog_posts ORDER BY published_at ASC NULLS LAST")
        ).fetchall()

    since_dt = None
    if since:
        since_dt = datetime.fromisoformat(since).replace(tzinfo=timezone.utc)

    posts = []
    for r in rows:
        post_id_src, title, url, published_at, category, raw_text, hash_ = r
        if post_id_src in indexed:
            continue
        if not raw_text or not raw_text.strip():
            continue
        if since_dt and published_at and published_at < since_dt:
            continue
        posts.append({
            "post_id_src": post_id_src,
            "title": title or "",
            "url": url or "",
            "published_at": published_at.isoformat() if published_at else "",
            "category": category or "",
            "raw_text": raw_text,
            "hash": hash_,
        })

    return posts


def _existing_node_hashes() -> set[str]:
    from sqlalchemy import text
    with get_sync_session() as session:
        return {
            row[0] for row in session.execute(
                text("SELECT hash FROM mer_nodes WHERE source_type = 'blog'")
            )
        }


def _record_nodes_batch(nodes, existing: set[str]) -> None:
    from sqlalchemy import text

    new_nodes = [n for n in nodes if n.metadata.get("node_hash", "") not in existing]
    if not new_nodes:
        return

    with get_sync_session() as session:
        session.execute(
            text(
                "INSERT INTO mer_nodes "
                "(source_type, source_id, chunk_no, text, hash, qdrant_point_id, metadata, created_at) "
                "VALUES (:st, :sid, :cn, :txt, :h, :qid, CAST(:meta AS jsonb), NOW())"
            ),
            [
                {
                    "st": "blog",
                    "sid": n.metadata.get("post_id_src", ""),
                    "cn": n.metadata.get("chunk_no", 0),
                    "txt": n.text,
                    "h": n.metadata.get("node_hash", ""),
                    "qid": n.id_,
                    "meta": json.dumps(n.metadata),
                }
                for n in new_nodes
            ],
        )

    for n in new_nodes:
        existing.add(n.metadata.get("node_hash", ""))


def run(since: str | None = None, dry_run: bool = False) -> None:
    configure_logging()
    settings = get_settings()
    t_start = time.monotonic()

    # ── 1. Load ──────────────────────────────────────────────────────────
    logger.info("ingest_blog.load", since=since)
    posts = _load_unindexed_posts(since=since)
    logger.info("ingest_blog.loaded", count=len(posts))

    if not posts:
        logger.info("ingest_blog.skip", reason="no unindexed posts")
        return

    # ── 2. Document 변환 + Enrich ─────────────────────────────────────────
    from llama_index.core import Document

    documents = []
    for p in posts:
        doc = Document(
            text=p["raw_text"],
            metadata={
                "post_id_src": p["post_id_src"],
                "title": p["title"],
                "url": p["url"],
                "published_at": p["published_at"],
                "category": p["category"],
                "source_type": "blog",
                "src_hash": p["hash"],
            },
            id_=p["post_id_src"],
        )
        documents.append(enrich_metadata(doc))

    # ── 3. Parse nodes ───────────────────────────────────────────────────
    nodes = parse_nodes(documents)
    logger.info("ingest_blog.nodes_parsed", count=len(nodes))

    if dry_run:
        logger.info("ingest_blog.dry_run", nodes=len(nodes))
        for i, node in enumerate(nodes[:3]):
            logger.info("sample_node", idx=i, preview=node.text[:80])
        return

    # ── 4. Setup ─────────────────────────────────────────────────────────
    from app.shared.llm.lmstudio import build_embed_model

    embed_model = build_embed_model(settings)
    qclient = qdrant_writer.get_client(settings.QDRANT_URL, settings.QDRANT_API_KEY)
    existing_hashes = _existing_node_hashes()

    processed_nodes: list = []

    # ── 5. 배치마다 embed → Qdrant upsert → mer_nodes 기록 ───────────────
    logger.info("ingest_blog.embedding_start", total=len(nodes), batch=_EMBED_BATCH)
    for i in tqdm(range(0, len(nodes), _EMBED_BATCH), desc="embedding"):
        batch = nodes[i: i + _EMBED_BATCH]
        vecs = embed_model.get_text_embedding_batch([n.text for n in batch])
        qdrant_writer.upsert_nodes(qclient, _COLLECTION, batch, vecs)
        _record_nodes_batch(batch, existing_hashes)
        processed_nodes.extend(batch)

    logger.info("ingest_blog.upserted", count=len(processed_nodes))

    # ── 6. BM25 corpus 저장 ───────────────────────────────────────────────
    bm25_path = bm25_store.save(processed_nodes, _COLLECTION, settings.BATCH_DATA_DIR)
    logger.info("ingest_blog.bm25_saved", path=str(bm25_path))

    elapsed = int((time.monotonic() - t_start) * 1000)
    logger.info("ingest_blog.done", nodes=len(processed_nodes), elapsed_ms=elapsed)
