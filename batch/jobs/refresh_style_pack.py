"""스타일 팩 갱신 잡 — 기존 mer_style 컬렉션을 품질 기준으로 재필터링한다."""
from __future__ import annotations

import time

from app.mer_persona.core.config import get_settings
from app.mer_persona.core.logging import configure_logging, get_logger

logger = get_logger(__name__)

_STYLE_COLLECTION = "mer_style"


def run() -> None:
    """댓글을 다시 로드해 스타일 기준을 재적용하고 mer_style 컬렉션을 덮어쓴다."""
    configure_logging()
    settings = get_settings()
    t_start = time.monotonic()

    logger.info("refresh_style_pack.start")

    # 댓글 파일이 없으면 스킵
    from pathlib import Path
    if not Path(settings.BATCH_COMMENT_EXPORT).exists():
        logger.warning("refresh_style_pack.skip", reason="댓글 export 파일 없음")
        return

    # ingest_comments와 동일한 로직으로 style worthy 댓글만 다시 색인
    from batch.ingest.comment_loader import load_from_export
    from batch.ingest.node_parser import text_to_node_id
    from batch.ingest import qdrant_writer
    from app.shared.llm.lmstudio import build_embed_model
    from tqdm import tqdm

    documents = load_from_export(settings.BATCH_COMMENT_EXPORT)
    style_docs = [
        d for d in documents
        if _is_style_worthy(d.text, d.metadata.get("author", ""), settings)
    ]
    logger.info("refresh_style_pack.filtered", total=len(documents), style=len(style_docs))

    if not style_docs:
        logger.warning("refresh_style_pack.skip", reason="style worthy 댓글 없음")
        return

    embed_model = build_embed_model(settings)
    embeddings = []
    for i in tqdm(range(0, len(style_docs), 32), desc="embedding"):
        batch = style_docs[i : i + 32]
        vecs = embed_model.get_text_embedding_batch([d.text for d in batch])
        embeddings.extend(vecs)

    from llama_index.core.schema import TextNode
    nodes = []
    for doc in style_docs:
        nh = text_to_node_id(doc.text)
        nodes.append(TextNode(text=doc.text, id_=nh, metadata={**doc.metadata, "node_hash": nh}))

    qclient = qdrant_writer.get_client(settings.QDRANT_URL, settings.QDRANT_API_KEY)

    # 기존 컬렉션 삭제 후 재생성 (전체 갱신)
    try:
        qclient.delete_collection(_STYLE_COLLECTION)
    except Exception:
        pass

    from qdrant_client.models import Distance, VectorParams
    qclient.create_collection(
        _STYLE_COLLECTION,
        vectors_config=VectorParams(size=1024, distance=Distance.COSINE),
        on_disk_payload=True,
    )

    upserted = qdrant_writer.upsert_nodes(qclient, _STYLE_COLLECTION, nodes, embeddings)
    elapsed = int((time.monotonic() - t_start) * 1000)
    logger.info("refresh_style_pack.done", upserted=upserted, elapsed_ms=elapsed)


def _is_style_worthy(body: str, author: str, settings) -> bool:
    if len(body) < settings.STYLE_MIN_LEN or len(body) > settings.STYLE_MAX_LEN:
        return False
    if settings.STYLE_AUTHOR and author != settings.STYLE_AUTHOR:
        return False
    if body.count("```") >= 2:
        return False
    return True
