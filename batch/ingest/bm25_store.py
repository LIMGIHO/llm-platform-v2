"""BM25 코퍼스를 pickle로 영속화 — batch가 빌드, app이 로드."""
from __future__ import annotations

import pickle
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from llama_index.core.schema import TextNode
from llama_index.retrievers.bm25 import BM25Retriever

from app.shared.utils.tokenizer import tokenize_ko


@dataclass
class BM25Corpus:
    collection: str
    nodes: list[TextNode]
    built_at: str = field(default_factory=lambda: datetime.now().isoformat())


def save(nodes: list[TextNode], collection: str, data_dir: str) -> Path:
    """TextNode 목록을 pickle로 저장하고 저장 경로를 반환."""
    corpus = BM25Corpus(collection=collection, nodes=nodes)
    path = Path(data_dir) / "bm25" / f"{collection}.pkl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        pickle.dump(corpus, f, protocol=pickle.HIGHEST_PROTOCOL)
    return path


def load_retriever(collection: str, data_dir: str, top_k: int = 10) -> BM25Retriever:
    """pickle을 읽어 BM25Retriever를 재구성한다 (app 시작 시 호출)."""
    path = Path(data_dir) / "bm25" / f"{collection}.pkl"
    if not path.exists():
        raise FileNotFoundError(f"BM25 corpus 파일 없음: {path}")
    with open(path, "rb") as f:
        corpus: BM25Corpus = pickle.load(f)
    return BM25Retriever.from_defaults(
        nodes=corpus.nodes,
        tokenizer=tokenize_ko,  # 모듈 레벨 named fn → picklable
        similarity_top_k=top_k,
    )


def corpus_mtime(collection: str, data_dir: str) -> float | None:
    """파일 mtime 반환 (핫 리로드 판단용). 없으면 None."""
    path = Path(data_dir) / "bm25" / f"{collection}.pkl"
    return path.stat().st_mtime if path.exists() else None
