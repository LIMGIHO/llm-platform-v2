"""Search planner for bounded retrieval agent."""
from __future__ import annotations

import json
import re

from llama_index.core.llms import ChatMessage

from app.mer_persona.schemas.search import SearchPlanResponse, ToolCallRequest

_SYSTEM_PROMPT = """\
너는 검색 도구 선택기다. 사용자의 질문을 보고 어떤 검색 도구를 사용할지 JSON으로만 답한다.

사용 가능한 도구:
- web_search: 최신 뉴스, 공개 웹페이지, 일반 웹 정보
- market_data: 현재 주가, 환율, 지수, 코인 가격
- local_file_search: 로컬 코드, 문서, 로그, 설정 파일 검색

규칙:
1. 현재 가격, 주가, 환율, 지수, 코인 시세는 market_data만 사용한다.
2. 파일, 코드, 함수, 에러 로그, 프로젝트 위치 질문은 local_file_search를 사용한다.
3. 최신 뉴스나 일반 공개 웹 정보는 web_search를 사용한다.
4. JSON 한 줄만 반환한다.

형식:
{"intent":"market|web|files|mixed|unsupported","steps":[{"tool":"market_data|web_search|local_file_search","query":"검색어","top_k":5,"args":{}}],"reason":"짧은 이유"}
"""

_MARKET_PAT = re.compile(r"(주가|환율|시세|현재가|코스피|코스닥|나스닥|비트코인|달러|환전)")
_FILE_PAT = re.compile(r"(파일|코드|함수|클래스|에러|로그|프로젝트|어디|경로|router|service|config)")
_WEB_PAT = re.compile(r"(뉴스|최근|최신|웹|검색|기사|자료|발표)")


def _extract_json(text: str) -> dict:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("planner output did not contain JSON")
    data = json.loads(match.group())
    if not isinstance(data, dict):
        raise ValueError("planner JSON must be an object")
    return data


def _rule_fallback(
    query: str,
    errors: list[str] | None = None,
    raw: str = "",
) -> SearchPlanResponse:
    if _MARKET_PAT.search(query):
        return SearchPlanResponse(
            intent="market",
            steps=[ToolCallRequest(tool="market_data", query=query)],
            reason="규칙 기반 fallback: 현재 시장 데이터 요청",
            raw_output=raw,
            validation_errors=errors or [],
        )
    if _FILE_PAT.search(query):
        return SearchPlanResponse(
            intent="files",
            steps=[
                ToolCallRequest(
                    tool="local_file_search",
                    query=query,
                    args={"path_scope": "."},
                )
            ],
            reason="규칙 기반 fallback: 로컬 파일/코드 검색 요청",
            raw_output=raw,
            validation_errors=errors or [],
        )
    if _WEB_PAT.search(query):
        return SearchPlanResponse(
            intent="web",
            steps=[ToolCallRequest(tool="web_search", query=query)],
            reason="규칙 기반 fallback: 웹 검색 요청",
            raw_output=raw,
            validation_errors=errors or [],
        )
    return SearchPlanResponse(
        intent="unsupported",
        steps=[],
        reason="사용 가능한 검색 도구와 명확히 맞지 않음",
        raw_output=raw,
        validation_errors=errors or [],
    )


async def plan_search(query: str, llm=None, max_steps: int = 3) -> SearchPlanResponse:
    if llm is None:
        return _rule_fallback(query)

    raw = ""
    errors: list[str] = []
    try:
        response = await llm.achat(
            [
                ChatMessage(role="system", content=_SYSTEM_PROMPT),
                ChatMessage(role="user", content=f"질문: {query}"),
            ]
        )
        raw = response.message.content or ""
        data = _extract_json(raw)
        steps = [ToolCallRequest(**item) for item in data.get("steps", [])[:max_steps]]
        return SearchPlanResponse(
            intent=str(data.get("intent", "unsupported")),
            steps=steps,
            reason=str(data.get("reason", "")),
            raw_output=raw,
            validation_errors=[],
        )
    except Exception as exc:
        errors.append(str(exc))
        return _rule_fallback(query, errors=errors, raw=raw)
