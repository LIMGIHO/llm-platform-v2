"""QdrantVectorStore + VectorIndexRetriever (app 쪽 retrieval용)."""
from __future__ import annotations

from llama_index.core import VectorStoreIndex
from llama_index.core.retrievers import VectorIndexRetriever
from llama_index.vector_stores.qdrant import QdrantVectorStore
from qdrant_client import AsyncQdrantClient

from app.mer_persona.core.config import get_settings

_COLLECTION_BLOG = "mer_blog"
_COLLECTION_COMMENTS = "mer_comments"

_qdrant_aclient: AsyncQdrantClient | None = None


def _get_qdrant_aclient() -> AsyncQdrantClient:
    global _qdrant_aclient
    if _qdrant_aclient is None:
        s = get_settings()
        _qdrant_aclient = AsyncQdrantClient(
            url=s.QDRANT_URL,
            api_key=s.QDRANT_API_KEY or None,
            timeout=30,
        )
    return _qdrant_aclient


def get_vector_retriever(top_k: int = 10) -> VectorIndexRetriever:
    """mer_blog 컬렉션 VectorIndexRetriever."""
    return _make_retriever(_COLLECTION_BLOG, top_k)


def get_comments_vector_retriever(top_k: int = 10) -> VectorIndexRetriever:
    """mer_comments 컬렉션 VectorIndexRetriever."""
    return _make_retriever(_COLLECTION_COMMENTS, top_k)


def _make_retriever(collection: str, top_k: int) -> VectorIndexRetriever:
    """QdrantVectorStore 기반 VectorIndexRetriever를 반환한다.

    embed_model은 lifespan에서 설정한 LlamaIndex global Settings를 사용.
    """
    aclient = _get_qdrant_aclient()
    vector_store = QdrantVectorStore(collection_name=collection, aclient=aclient)
    index = VectorStoreIndex.from_vector_store(vector_store)
    return VectorIndexRetriever(index=index, similarity_top_k=top_k)
