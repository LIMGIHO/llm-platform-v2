"""댓글 ingest 잡 — mer_comments + mer_style 컬렉션 동시 구축.

흐름:
  mer_blog_comments (Postgres) → 미인덱싱 댓글만 → embed → Qdrant + mer_nodes
  배치마다 embed → upsert → record 즉시 처리 (중간 실패 시 이어서 재시작 가능)
  style 벡터는 comment 임베딩 재활용 (재임베딩 없음)
"""
from __future__ import annotations

import json
import time

from tqdm import tqdm

from app.mer_persona.core.config import get_settings
from app.mer_persona.core.logging import configure_logging, get_logger
from app.shared.db.session import get_sync_session
from batch.ingest import qdrant_writer
from batch.ingest.node_parser import text_to_node_id

logger = get_logger(__name__)

_COMMENT_COLLECTION = "mer_comments"
_STYLE_COLLECTION = "mer_style"
_EMBED_BATCH = 32


def _load_unindexed_comments() -> list[dict]:
    """mer_nodes에 없는 댓글을 mer_blog_comments에서 조회한다."""
    from sqlalchemy import text

    with get_sync_session() as session:
        indexed: set[str] = {
            row[0] for row in session.execute(
                text("SELECT source_id FROM mer_nodes WHERE source_type = 'comment'")
            )
        }
        rows = session.execute(
            text(
                "SELECT id, post_id, author, body, written_at, hash "
                "FROM mer_blog_comments ORDER BY written_at ASC NULLS LAST"
            )
        ).fetchall()

    comments = []
    for r in rows:
        cid, post_id, author, body, written_at, hash_ = r
        if str(cid) in indexed:
            continue
        if not body or not body.strip():
            continue
        comments.append({
            "id": str(cid),
            "post_id": str(post_id or ""),
            "author": author or "",
            "body": body.strip(),
            "written_at": written_at.isoformat() if written_at else "",
            "hash": hash_ or "",
        })

    return comments


def _is_style_worthy(body: str, author: str, settings) -> bool:
    if len(body) < settings.STYLE_MIN_LEN or len(body) > settings.STYLE_MAX_LEN:
        return False
    if settings.STYLE_AUTHOR and author != settings.STYLE_AUTHOR:
        return False
    if body.count("```") >= 2:
        return False
    return True


def _existing_node_source_ids() -> set[str]:
    """이미 인덱싱된 댓글의 source_id(comment_id) 집합.

    dedup 키를 source_id로 통일한다. (과거엔 node_hash=본문해시로 dedup해서,
    본문이 동일한 서로 다른 댓글이 영원히 mer_nodes 행을 못 받고
    매 실행마다 재임베딩되는 버그가 있었다.)
    """
    from sqlalchemy import text
    with get_sync_session() as session:
        return {
            str(row[0]) for row in session.execute(
                text("SELECT source_id FROM mer_nodes WHERE source_type = 'comment'")
            )
        }


def _existing_style_ids() -> set[str]:
    from sqlalchemy import text
    with get_sync_session() as session:
        return {
            row[0] for row in session.execute(
                text("SELECT embedding_id FROM mer_style_examples")
            )
        }


def _doc_to_node(doc, source_type: str):
    from llama_index.core.schema import TextNode
    node_hash = text_to_node_id(doc.text)
    meta = {**doc.metadata, "source_type": source_type, "node_hash": node_hash}
    return TextNode(text=doc.text, id_=node_hash, metadata=meta)


def _record_nodes_batch(nodes, existing: set[str]) -> None:
    """nodes를 mer_nodes에 기록한다. dedup 키는 source_id(comment_id)."""
    from sqlalchemy import text

    new_nodes = [
        n for n in nodes
        if str(n.metadata.get("comment_id", "")) not in existing
    ]
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
                    "st": "comment",
                    "sid": n.metadata.get("comment_id", ""),
                    "cn": 0,
                    "txt": n.text,
                    "h": n.metadata.get("node_hash", ""),
                    "qid": n.id_,
                    "meta": json.dumps(n.metadata),
                }
                for n in new_nodes
            ],
        )

    for n in new_nodes:
        existing.add(str(n.metadata.get("comment_id", "")))


def _record_style_batch(docs, existing: set[str]) -> None:
    from sqlalchemy import text

    new_rows = [
        {
            "embedding_id": text_to_node_id(d.text),
            "topic_tags": [],
            "score": 1.0,
        }
        for d in docs
        if text_to_node_id(d.text) not in existing
    ]
    if not new_rows:
        return

    with get_sync_session() as session:
        session.execute(
            text(
                "INSERT INTO mer_style_examples (embedding_id, topic_tags, score) "
                "VALUES (:embedding_id, :topic_tags, :score)"
            ),
            new_rows,
        )

    for row in new_rows:
        existing.add(row["embedding_id"])


def run(dry_run: bool = False) -> None:
    configure_logging()
    settings = get_settings()
    t_start = time.monotonic()

    # ── 1. Load ──────────────────────────────────────────────────────────
    comments = _load_unindexed_comments()
    logger.info("ingest_comments.loaded", count=len(comments))

    if not comments:
        logger.info("ingest_comments.skip", reason="no unindexed comments")
        return

    # ── 2. Document 변환 ──────────────────────────────────────────────────
    from llama_index.core import Document

    documents = []
    for c in comments:
        doc = Document(
            text=c["body"],
            metadata={
                "comment_id": c["id"],
                "post_id": c["post_id"],
                "author": c["author"],
                "written_at": c["written_at"],
                "source_type": "comment",
                "src_hash": c["hash"],
            },
            id_=c["id"],
        )
        documents.append(doc)

    style_ids: set[str] = {
        d.id_ for d in documents
        if _is_style_worthy(d.text, d.metadata.get("author", ""), settings)
    }
    logger.info(
        "ingest_comments.split",
        total=len(documents),
        style_worthy=len(style_ids),
    )

    if dry_run:
        for d in documents[:3]:
            if d.id_ in style_ids:
                logger.info("style_sample", preview=d.text[:80])
        return

    # ── 3. Setup ─────────────────────────────────────────────────────────
    from app.shared.llm.lmstudio import build_embed_model

    embed_model = build_embed_model(settings)
    qclient = qdrant_writer.get_client(settings.QDRANT_URL, settings.QDRANT_API_KEY)
    existing_node_source_ids = _existing_node_source_ids()
    existing_style_ids = _existing_style_ids()

    total_comments = 0
    total_style = 0

    # ── 4. 배치마다 embed → upsert → record ──────────────────────────────
    for i in tqdm(range(0, len(documents), _EMBED_BATCH), desc="embedding"):
        batch_docs = documents[i: i + _EMBED_BATCH]
        vecs = embed_model.get_text_embedding_batch([d.text for d in batch_docs])

        # mer_comments
        batch_nodes = [_doc_to_node(d, "comment") for d in batch_docs]
        qdrant_writer.upsert_nodes(qclient, _COMMENT_COLLECTION, batch_nodes, vecs)
        _record_nodes_batch(batch_nodes, existing_node_source_ids)
        total_comments += len(batch_nodes)

        # mer_style — 이미 계산된 벡터 재활용
        style_pairs = [
            (d, v) for d, v in zip(batch_docs, vecs)
            if d.id_ in style_ids
        ]
        if style_pairs:
            style_docs_batch, style_vecs_batch = zip(*style_pairs)
            style_nodes_batch = [_doc_to_node(d, "style") for d in style_docs_batch]
            qdrant_writer.upsert_nodes(
                qclient, _STYLE_COLLECTION,
                list(style_nodes_batch), list(style_vecs_batch),
            )
            _record_style_batch(list(style_docs_batch), existing_style_ids)
            total_style += len(style_nodes_batch)

    logger.info("ingest_comments.done",
                comments=total_comments, style=total_style,
                elapsed_ms=int((time.monotonic() - t_start) * 1000))
