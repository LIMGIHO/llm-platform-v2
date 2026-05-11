"""v1 export JSONL → LlamaIndex Document 변환."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from llama_index.core import Document


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def load_from_export(path: str, since: str | None = None) -> list[Document]:
    """JSONL 파일을 읽어 Document 목록으로 반환.

    since: "YYYY-MM-DD" 형식. 이 날짜 이전 포스트는 건너뜀.
    """
    since_dt: datetime | None = None
    if since:
        since_dt = datetime.fromisoformat(since).replace(tzinfo=timezone.utc)

    documents: list[Document] = []
    src = Path(path)
    if not src.exists():
        raise FileNotFoundError(f"export 파일을 찾을 수 없습니다: {path}")

    with open(src, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as e:
                raise ValueError(f"JSONL 파싱 오류 (line {lineno}): {e}") from e

            text = row.get("raw_text") or ""
            if not text.strip():
                continue  # 본문 없는 포스트 스킵

            published_at = _parse_dt(row.get("published_at"))
            if since_dt and published_at and published_at < since_dt:
                continue

            doc = Document(
                text=text,
                metadata={
                    "post_id_src": str(row["post_id_src"]),
                    "title": row.get("title", ""),
                    "url": row.get("url", ""),
                    "published_at": published_at.isoformat() if published_at else "",
                    "category": row.get("category") or "",
                    "source_type": "blog",
                    "src_hash": row.get("hash", ""),
                },
                id_=str(row["post_id_src"]),
            )
            documents.append(doc)

    return documents
