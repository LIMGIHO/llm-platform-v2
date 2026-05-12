"""Postgres mer_nodes에서 BM25 corpus를 처음부터 재빌드한다."""
from __future__ import annotations

from app.mer_persona.core.config import get_settings
from app.mer_persona.core.logging import configure_logging, get_logger
from sqlalchemy import text as sa_text

from app.shared.db.session import get_sync_session
from batch.ingest import bm25_store

logger = get_logger(__name__)

_COLLECTION = "mer_blog"


def run() -> None:
    configure_logging()
    settings = get_settings()
    logger.info("rebuild_bm25.start", collection=_COLLECTION)

    with get_sync_session() as session:
        rows = session.execute(
            sa_text(
                "SELECT text, source_id, chunk_no, hash, metadata_ FROM mer_nodes "
                "WHERE source_type = 'blog' ORDER BY source_id, chunk_no"
            )
        ).fetchall()

    if not rows:
        logger.warning("rebuild_bm25.skip", reason="mer_nodes에 blog 데이터 없음")
        return

    # Postgres 행 → TextNode 재구성
    from llama_index.core.schema import TextNode

    nodes = []
    for text, source_id, chunk_no, node_hash, meta in rows:
        node = TextNode(
            text=text,
            id_=node_hash,
            metadata={
                **(meta or {}),
                "chunk_no": chunk_no,
                "node_hash": node_hash,
                "source_id": source_id,
            },
        )
        nodes.append(node)

    path = bm25_store.save(nodes, _COLLECTION, settings.BATCH_DATA_DIR)
    logger.info("rebuild_bm25.done", nodes=len(nodes), path=str(path))
