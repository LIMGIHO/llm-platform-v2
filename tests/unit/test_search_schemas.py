from pydantic import ValidationError

from app.mer_persona.schemas.search import (
    FileSearchRequest,
    SearchAnswerRequest,
    SearchResult,
    ToolCallRequest,
    ToolName,
)


def test_search_answer_request_defaults():
    req = SearchAnswerRequest(query="오늘 삼성전자 주가 알려줘")
    assert req.query == "오늘 삼성전자 주가 알려줘"
    assert req.max_steps == 3
    assert req.top_k == 5


def test_tool_call_request_rejects_unknown_tool():
    try:
        ToolCallRequest(tool="unknown", query="x")
    except ValidationError as exc:
        assert "tool" in str(exc)
    else:
        raise AssertionError("unknown tool should fail validation")


def test_file_search_request_rejects_absolute_scope_escape():
    try:
        FileSearchRequest(query="secret", path_scope="/etc")
    except ValidationError as exc:
        assert "path_scope" in str(exc)
    else:
        raise AssertionError("absolute path scope should fail validation")


def test_search_result_accepts_file_metadata():
    result = SearchResult(
        type="file",
        source="local",
        title="intent_router.py",
        path="app/mer_persona/services/mer/intent_router.py",
        snippet="class IntentRoute",
        score=1.0,
        metadata={"line": 12},
    )
    assert result.type == "file"
    assert result.metadata["line"] == 12


def test_tool_name_values_are_stable():
    assert ToolName.WEB == "web_search"
    assert ToolName.MARKET == "market_data"
    assert ToolName.FILES == "local_file_search"
