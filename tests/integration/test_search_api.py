import pytest
from httpx import ASGITransport, AsyncClient

from app.mer_persona.main import app


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_file_tool_endpoint_finds_repo_file():
    async with _client() as client:
        resp = await client.post(
            "/v1/search/tools/files",
            json={
                "query": "IntentRoute",
                "path_scope": "app/mer_persona/services/mer",
                "top_k": 5,
            },
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["tool"] == "local_file_search"
    assert data["tool_call"]["status"] == "ok"
    assert any("intent_router.py" in r["path"] for r in data["results"])


@pytest.mark.asyncio
async def test_web_tool_endpoint_reports_disabled_provider():
    async with _client() as client:
        resp = await client.post("/v1/search/tools/web", json={"query": "최근 HMM 뉴스"})
    assert resp.status_code == 502
    assert "SEARCH_WEB_PROVIDER" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_market_tool_endpoint_reports_disabled_provider():
    async with _client() as client:
        resp = await client.post("/v1/search/tools/market", json={"symbol": "005930.KS"})
    assert resp.status_code == 502
    assert "SEARCH_MARKET_PROVIDER" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_plan_endpoint_uses_rule_fallback_without_llm_execution():
    async with _client() as client:
        resp = await client.post(
            "/v1/search/plan",
            json={"query": "이 프로젝트에서 intent_router 어디 있어?"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["steps"][0]["tool"] == "local_file_search"


@pytest.mark.asyncio
async def test_answer_endpoint_returns_file_citation():
    async with _client() as client:
        resp = await client.post(
            "/v1/search/answer",
            json={"query": "이 프로젝트에서 IntentRoute 어디 있어?", "max_steps": 3},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "local_file_search" in data["used_tools"]
    assert data["trace_id"]
    assert data["citations"]
