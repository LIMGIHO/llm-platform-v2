"""v1 댓글 export JSONL → LlamaIndex Document 변환."""
from __future__ import annotations

import json
from pathlib import Path

from llama_index.core import Document


def load_from_export(path: str) -> list[Document]:
    """JSONL 한 줄 = 댓글 1개 → Document. 빈 본문은 스킵."""
    src = Path(path)
    if not src.exists():
        raise FileNotFoundError(f"댓글 export 파일 없음: {path}")

    documents: list[Document] = []
    with open(src, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as e:
                raise ValueError(f"JSONL 파싱 오류 (line {lineno}): {e}") from e

            body = (row.get("body") or "").strip()
            if not body:
                continue

            doc = Document(
                text=body,
                metadata={
                    "post_id": str(row.get("post_id", "")),
                    "author": row.get("author") or "",
                    "written_at": row.get("written_at") or "",
                    "source_type": "comment",
                    "src_hash": row.get("hash", ""),
                },
                id_=str(row.get("id", lineno)),
            )
            documents.append(doc)

    return documents
