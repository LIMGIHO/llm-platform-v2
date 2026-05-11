"""BM25Retriever 로드 + 핫 리로드 (app 컨테이너)."""
from __future__ import annotations

from llama_index.retrievers.bm25 import BM25Retriever

from app.mer_persona.core.config import get_settings
from app.mer_persona.core.logging import get_logger
from batch.ingest.bm25_store import corpus_mtime, load_retriever

logger = get_logger(__name__)

_COLLECTION = "mer_blog"

_retriever: BM25Retriever | None = None
_loaded_mtime: float | None = None


def get_bm25_retriever(top_k: int = 10) -> BM25Retriever | None:
    """pickle에서 BM25Retriever를 로드한다. 파일 없으면 None 반환."""
    global _retriever, _loaded_mtime
    settings = get_settings()
    mtime = corpus_mtime(_COLLECTION, settings.BATCH_DATA_DIR)

    if mtime is None:
        logger.warning("bm25.not_found", collection=_COLLECTION)
        return None

    if _retriever is None or mtime != _loaded_mtime:
        logger.info("bm25.loading", collection=_COLLECTION, mtime=mtime)
        _retriever = load_retriever(_COLLECTION, settings.BATCH_DATA_DIR, top_k=top_k)
        _loaded_mtime = mtime
        logger.info("bm25.loaded")

    return _retriever


def reload() -> bool:
    """강제 핫 리로드 (POST /v1/admin/bm25/reload 에서 호출). 성공 여부 반환."""
    global _loaded_mtime
    _loaded_mtime = None  # 캐시 무효화
    return get_bm25_retriever() is not None
