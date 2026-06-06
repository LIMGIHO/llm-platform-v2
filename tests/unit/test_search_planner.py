"""search planner 유닛 테스트."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.mer_persona.schemas.search import ToolName


def _mock_llm(json_response: str) -> MagicMock:
    """llm.achat()을 모킹하는 헬퍼."""
    msg = MagicMock()
    msg.content = json_response
    response = MagicMock()
    response.message = msg
    llm = MagicMock()
    llm.achat = AsyncMock(return_value=response)
    return llm


# ── Task 1: Schema 검증 ──────────────────────────────────────────────────────

def test_tool_name_rag_exists():
    assert ToolName.RAG == "rag_search"

def test_tool_name_all_values():
    values = {t.value for t in ToolName}
    assert "rag_search" in values
    assert "web_search" in values
    assert "market_data" in values
    assert "local_file_search" in values
