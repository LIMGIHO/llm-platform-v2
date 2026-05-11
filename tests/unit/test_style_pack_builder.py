"""style_pack_builder 유닛 테스트 (Qdrant + embed_model 모킹)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.mer_persona.services.mer.style_pack_builder import StylePack, build

_MODULE = "app.mer_persona.services.mer.style_pack_builder"


@pytest.mark.asyncio
async def test_build_returns_examples():
    mock_result = MagicMock()
    mock_result.payload = {"text": "메르 스타일 예시 댓글 내용입니다."}

    mock_response = MagicMock()
    mock_response.points = [mock_result]

    with (
        patch(f"{_MODULE}._get_embed_model", return_value=MagicMock()),
        patch(f"{_MODULE}._get_qdrant_client", return_value=MagicMock()),
        patch(f"{_MODULE}.asyncio.to_thread") as mock_thread,
    ):
        mock_thread.side_effect = [
            [0.1] * 1024,       # embedding
            mock_response,      # query_points response
        ]

        pack = await build("금리 질문", top_k=1)

    assert not pack.is_empty
    assert "메르 스타일 예시" in pack.examples[0]


@pytest.mark.asyncio
async def test_build_returns_empty_when_no_embed_model():
    with patch(f"{_MODULE}._get_embed_model", return_value=None):
        pack = await build("질문")
    assert pack.is_empty


@pytest.mark.asyncio
async def test_build_graceful_on_qdrant_error():
    """Qdrant 연결 오류 시 빈 StylePack 반환 (graceful degradation)."""
    with (
        patch(f"{_MODULE}._get_embed_model", return_value=MagicMock()),
        patch(f"{_MODULE}._get_qdrant_client", return_value=MagicMock()),
        patch(
            f"{_MODULE}.asyncio.to_thread",
            side_effect=ConnectionError("Qdrant 오프라인"),
        ),
    ):
        pack = await build("질문")
    assert pack.is_empty


def test_style_pack_is_empty():
    assert StylePack().is_empty
    assert not StylePack(examples=["예시"]).is_empty
