from pathlib import Path

import pytest

from app.mer_persona.schemas.search import SearchAnswerRequest
from app.mer_persona.services.search.agent import answer_search


@pytest.mark.asyncio
async def test_answer_search_uses_file_results(tmp_path: Path):
    target = tmp_path / "app" / "router.py"
    target.parent.mkdir(parents=True)
    target.write_text("class IntentRoute:\n    pass\n", encoding="utf-8")

    response = await answer_search(
        SearchAnswerRequest(query="이 프로젝트에서 IntentRoute 어디 있어?"),
        llm=None,
        file_root=str(tmp_path),
    )

    assert response.used_tools == ["local_file_search"]
    assert response.citations
    assert "router.py" in response.answer
    assert response.confidence > 0


@pytest.mark.asyncio
async def test_answer_search_reports_no_results(tmp_path: Path):
    response = await answer_search(
        SearchAnswerRequest(query="이 프로젝트에서 MissingNeedle 어디 있어?"),
        llm=None,
        file_root=str(tmp_path),
    )

    assert response.used_tools == ["local_file_search"]
    assert response.citations == []
    assert "검색 결과를 찾지 못했습니다" in response.answer
    assert response.confidence == 0.0
