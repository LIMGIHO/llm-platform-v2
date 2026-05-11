"""한국어 BM25 토크나이저 (batch build + app query 공용).

모듈 레벨 named function → pickle 가능 (BM25Retriever 저장/복원 시 사용).
"""
from __future__ import annotations

from kiwipiepy import Kiwi

_kiwi: Kiwi | None = None


def _get_kiwi() -> Kiwi:
    global _kiwi
    if _kiwi is None:
        _kiwi = Kiwi()
    return _kiwi


def tokenize_ko(text: str) -> list[str]:
    """한국어 형태소 분석 후 어절 토큰 리스트 반환."""
    return [token.form for token in _get_kiwi().tokenize(text)]
