"""Document → TextNode 파싱 (SentenceSplitter 기반)."""
from __future__ import annotations

import hashlib

from llama_index.core import Document
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.schema import TextNode

# 한국어 기준 약 500~600자 분량 (LlamaIndex token count 기준)
_CHUNK_SIZE = 512
_CHUNK_OVERLAP = 50

_splitter: SentenceSplitter | None = None


def _get_splitter() -> SentenceSplitter:
    global _splitter
    if _splitter is None:
        _splitter = SentenceSplitter(chunk_size=_CHUNK_SIZE, chunk_overlap=_CHUNK_OVERLAP)
    return _splitter


def text_to_node_id(text: str) -> str:
    """텍스트 SHA-256 해시 앞 32자 → 결정적 node ID."""
    return hashlib.sha256(text.encode()).hexdigest()[:32]


def parse_nodes(documents: list[Document]) -> list[TextNode]:
    """Document 목록을 TextNode 목록으로 변환.

    - 각 노드에 chunk_no(문서 내 순서), node_hash 메타데이터 추가
    - node ID는 텍스트 해시 → idempotent upsert 보장
    """
    splitter = _get_splitter()
    all_nodes: list[TextNode] = []

    for doc in documents:
        nodes = splitter.get_nodes_from_documents([doc])
        for chunk_no, node in enumerate(nodes):
            node_hash = text_to_node_id(node.text)
            node.metadata["chunk_no"] = chunk_no
            node.metadata["node_hash"] = node_hash
            # 부모 문서 메타 상속 (splitter가 이미 복사하지만 명시적으로 보완)
            for key in ("post_id_src", "title", "url", "published_at", "category", "source_type"):
                if key not in node.metadata and key in doc.metadata:
                    node.metadata[key] = doc.metadata[key]
            node.id_ = node_hash
            all_nodes.append(node)

    return all_nodes
