"""Document 메타데이터 후처리 — 필드 정규화 및 추가 추출."""
from __future__ import annotations

import re

from llama_index.core import Document

# 종목 코드 패턴 (6자리 숫자) — 옵션: 언급 종목 추출
_TICKER_RE = re.compile(r"\b(\d{6})\b")


def enrich_metadata(doc: Document) -> Document:
    """제목 정규화, 카테고리 소문자화, 언급 티커 추출."""
    meta = doc.metadata

    # 제목 공백 정규화
    meta["title"] = re.sub(r"\s+", " ", meta.get("title", "")).strip()

    # 카테고리 소문자 정규화
    if meta.get("category"):
        meta["category"] = meta["category"].strip().lower()

    # 언급 종목 코드 추출 (선택적 — 향후 메타 필터에서 활용)
    tickers = list(set(_TICKER_RE.findall(doc.text[:2000])))
    if tickers:
        meta["tickers"] = tickers

    return doc
