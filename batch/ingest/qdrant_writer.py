"""Qdrant 배치 upsert — hash 기반 idempotent."""
from __future__ import annotations

import uuid

from llama_index.core.schema import TextNode
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

_BATCH_SIZE = 100


def _node_to_point_id(node: TextNode) -> str:
    """node_hash(32자 hex) → UUID 문자열 (Qdrant point ID)."""
    node_hash = node.metadata.get("node_hash", node.id_)
    return str(uuid.UUID(node_hash.ljust(32, "0")[:32]))


def ensure_collection(client: QdrantClient, collection: str, vector_size: int) -> None:
    """컬렉션이 없으면 생성한다."""
    existing = {c.name for c in client.get_collections().collections}
    if collection not in existing:
        client.create_collection(
            collection_name=collection,
            vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
        )


def upsert_nodes(
    client: QdrantClient,
    collection: str,
    nodes: list[TextNode],
    embeddings: list[list[float]],
) -> int:
    """nodes + embeddings 쌍을 Qdrant에 배치 upsert. 성공 건수 반환."""
    assert len(nodes) == len(embeddings), "nodes / embeddings 길이 불일치"

    if embeddings:
        ensure_collection(client, collection, len(embeddings[0]))

    total = 0
    for i in range(0, len(nodes), _BATCH_SIZE):
        batch_nodes = nodes[i : i + _BATCH_SIZE]
        batch_vecs = embeddings[i : i + _BATCH_SIZE]

        points = [
            PointStruct(
                id=_node_to_point_id(node),
                vector=vec,
                payload={
                    "post_id_src": node.metadata.get("post_id_src", ""),
                    "title": node.metadata.get("title", ""),
                    "url": node.metadata.get("url", ""),
                    "published_at": node.metadata.get("published_at", ""),
                    "category": node.metadata.get("category", ""),
                    "source_type": node.metadata.get("source_type", "blog"),
                    "chunk_no": node.metadata.get("chunk_no", 0),
                    "node_hash": node.metadata.get("node_hash", ""),
                    "text": node.text[:500],  # 검색 결과 미리보기용
                },
            )
            for node, vec in zip(batch_nodes, batch_vecs)
        ]

        client.upsert(collection_name=collection, points=points, wait=True)
        total += len(points)

    return total


def get_client(url: str, api_key: str = "") -> QdrantClient:
    return QdrantClient(url=url, api_key=api_key or None, timeout=120)
