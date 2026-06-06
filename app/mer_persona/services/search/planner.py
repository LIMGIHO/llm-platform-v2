"""Search tool planner — 단일 LLM이 질문을 tool 호출 계획으로 변환한다."""
from __future__ import annotations

import json
import logging
import re

from llama_index.core.llms import ChatMessage
from llama_index.llms.openai_like import OpenAILike

from app.mer_persona.schemas.search import SearchPlanResponse, ToolCallRequest, ToolName

logger = logging.getLogger(__name__)

# ── 유효 intent 집합 ──────────────────────────────────────────────────────────
_VALID_INTENTS = frozenset(
    ["smalltalk", "blog_rag", "blog_list", "web_search",
     "market_data", "file_search", "mixed", "reject"]
)

# ── 시스템 프롬프트 ────────────────────────────────────────────────────────────
_SYSTEM_PROMPT = """\
너는 검색 도구 플래너다. 질문을 보고 어떤 도구를 쓸지 JSON 한 줄로 답해라.

도구 목록: web_search | market_data | local_file_search | rag_search

강한 규칙:
- 시세·환율·주가·지수·코인 → market_data만 (web_search 절대 금지)
- 인사·잡담·시스템 기능 질문 → intent=smalltalk, steps=[]
- 블로그 글 목록·날짜·발행 순 조회 → intent=blog_list, steps=[]
- 처리 불가(내부 DB·개인 데이터) → intent=reject, steps=[]
- 블로그 글 내용 설명·요약·분석 → intent=blog_rag, steps=[rag_search]
- 로컬 코드·파일·설정 검색 → intent=file_search, steps=[local_file_search]
- 최신 뉴스·공개 웹 정보 → intent=web_search, steps=[web_search]
- 여러 정보 출처가 필요하면 → intent=mixed, steps에 필요한 도구 나열

출력 형식 (JSON 한 줄, 다른 텍스트 없음):
{"intent":"<라벨>","steps":[{"tool":"<도구>","query":"<검색어>"}],"reason":"<한줄근거>"}

Few-shot 예시:
Q: 오늘 삼성전자 주가? → {"intent":"market_data","steps":[{"tool":"market_data","query":"삼성전자 주가"}],"reason":"실시간 시세 요청"}
Q: 달러 환율 얼마야? → {"intent":"market_data","steps":[{"tool":"market_data","query":"USD/KRW 환율"}],"reason":"실시간 환율"}
Q: 조선업 메르 블로그 내용 설명해줘 → {"intent":"blog_rag","steps":[{"tool":"rag_search","query":"조선업"}],"reason":"블로그 RAG 검색"}
Q: 최근 HMM 뉴스 찾아줘 → {"intent":"web_search","steps":[{"tool":"web_search","query":"HMM 최신 뉴스"}],"reason":"최신 웹 검색"}
Q: 이 프로젝트에서 intent_router 어디 있어? → {"intent":"file_search","steps":[{"tool":"local_file_search","query":"intent_router"}],"reason":"로컬 파일 검색"}
Q: 최근 올라온 블로그 글 목록 보여줘 → {"intent":"blog_list","steps":[],"reason":"블로그 글 목록 조회"}
Q: 안녕 → {"intent":"smalltalk","steps":[],"reason":"인사"}
Q: 내 포트폴리오 수익률 알려줘 → {"intent":"reject","steps":[],"reason":"내부 DB 접근 불가"}
Q: 메르 블로그 조선업 내용이랑 최신 뉴스 같이 정리해줘 → {"intent":"mixed","steps":[{"tool":"rag_search","query":"조선업"},{"tool":"web_search","query":"조선업 최신 뉴스"}],"reason":"복합 검색"}
"""


# ── JSON 파싱 & 검증 ──────────────────────────────────────────────────────────

def _extract_json(text: str) -> dict | None:
    """텍스트에서 첫 번째 JSON 객체를 추출한다."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group())
    except json.JSONDecodeError:
        return None


def _parse_plan(raw: str) -> tuple[SearchPlanResponse | None, list[str]]:
    """raw LLM 출력을 SearchPlanResponse로 파싱한다.

    Returns:
        (SearchPlanResponse, errors): 파싱 성공 시 errors는 빈 리스트.
        (None, errors): JSON 자체를 찾지 못한 경우.
    """
    errors: list[str] = []
    data = _extract_json(raw)
    if data is None:
        return None, ["JSON 파싱 실패: 응답에 JSON 객체 없음"]

    # intent 검증
    intent = str(data.get("intent", "")).strip()
    if intent not in _VALID_INTENTS:
        errors.append(f"알 수 없는 intent: {intent!r}")
        intent = "blog_rag"

    # steps 파싱
    raw_steps = data.get("steps", [])
    if not isinstance(raw_steps, list):
        errors.append(f"steps가 리스트가 아님: {type(raw_steps)}")
        raw_steps = []

    steps: list[ToolCallRequest] = []
    for i, s in enumerate(raw_steps):
        if not isinstance(s, dict):
            errors.append(f"steps[{i}]: dict가 아님")
            continue
        tool_val = str(s.get("tool", "")).strip()
        try:
            tool = ToolName(tool_val)
        except ValueError:
            errors.append(f"steps[{i}]: 알 수 없는 tool {tool_val!r}")
            continue
        query = str(s.get("query", "")).strip()
        if not query:
            errors.append(f"steps[{i}]: query가 비어 있음")
            continue
        steps.append(ToolCallRequest(tool=tool, query=query))

    reason = str(data.get("reason", "")).strip()
    return (
        SearchPlanResponse(
            intent=intent,
            steps=steps,
            reason=reason,
            raw_output=raw,
            validation_errors=errors,
        ),
        errors,
    )


# ── 퍼블릭 인터페이스 ─────────────────────────────────────────────────────────

async def plan(
    query: str,
    llm: OpenAILike,
    *,
    recent_turns: list[tuple[str, str]] | None = None,
    max_steps: int = 3,
) -> SearchPlanResponse:
    """질문을 분석해 SearchPlanResponse를 반환한다.

    LLM을 최대 2회 호출한다: 1회 정상 시도 + 파싱 실패 시 1회 repair.
    모든 오류는 SearchPlanResponse.validation_errors에 기록되며 예외를 전파하지 않는다.
    """
    # 대화 맥락 추가 (선택)
    system_content = _SYSTEM_PROMPT
    if recent_turns:
        lines = "\n".join(
            f"[{role}] {content[:120]}" for role, content in recent_turns[-4:]
        )
        system_content += f"\n\n## 최근 대화 맥락 (참고)\n{lines}"

    messages = [
        ChatMessage(role="system", content=system_content),
        ChatMessage(role="user", content=f"Q: {query}"),
    ]

    # 1차 LLM 호출
    try:
        resp = await llm.achat(messages)
        raw = resp.message.content or ""
    except Exception as exc:
        logger.warning("planner.llm_error attempt=1 error=%s", exc)
        return SearchPlanResponse(
            intent="blog_rag",
            steps=[],
            reason="LLM 오류 — blog_rag fallback",
            validation_errors=[f"LLM 호출 실패: {exc}"],
        )

    result, errors = _parse_plan(raw)

    # 완전 성공 (파싱 OK + 에러 없음)
    if result is not None and not errors:
        result.steps = result.steps[:max_steps]
        return result

    # repair 재시도 (JSON 없거나 validation 오류)
    repair_messages = messages + [
        ChatMessage(role="assistant", content=raw),
        ChatMessage(
            role="user",
            content=(
                f"출력에 오류가 있습니다: {errors}\n"
                "도구 이름은 web_search|market_data|local_file_search|rag_search 중 하나여야 합니다.\n"
                "JSON 한 줄만 다시 출력하세요."
            ),
        ),
    ]
    try:
        resp2 = await llm.achat(repair_messages)
        raw2 = resp2.message.content or ""
        result2, _ = _parse_plan(raw2)
        if result2 is not None:
            result2.steps = result2.steps[:max_steps]
            return result2
    except Exception as exc2:
        logger.warning("planner.llm_error attempt=2 error=%s", exc2)

    # fallback: 1차 파싱 결과라도 반환, 없으면 기본값
    if result is not None:
        result.steps = result.steps[:max_steps]
        return result

    return SearchPlanResponse(
        intent="blog_rag",
        steps=[],
        reason="파싱 2회 실패 — blog_rag fallback",
        validation_errors=errors or ["알 수 없는 오류"],
    )
