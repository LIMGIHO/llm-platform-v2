# Search Planner v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Codex의 `/v1/search/*` 도구 계층 위에 단일 LLM 플래너를 구현해 `/v1/search/plan`을 통해 질문을 tool 호출 계획으로 변환한다.

**Architecture:** qwen2.5-1.5b-instruct(fp16/Q8)가 few-shot 프롬프트를 보고 JSON 한 줄로 `{intent, steps, reason}`을 출력한다. 파싱 실패 시 repair 재시도 1회, 그래도 실패하면 `blog_rag` fallback. `/v1/search/plan`은 도구를 실행하지 않아 빠르게 플래너 품질만 검증할 수 있다.

**Tech Stack:** FastAPI, LlamaIndex OpenAILike, Pydantic v2, pytest + pytest-asyncio(asyncio_mode=auto), LM Studio `:1234`

---

## 파일 맵

| 상태 | 경로 | 역할 |
|---|---|---|
| **수정** | `app/mer_persona/schemas/search.py` | `ToolName.RAG = "rag_search"` 추가 |
| **수정** | `app/mer_persona/core/config.py` | `LMSTUDIO_MODEL_PLANNER` 설정 추가 |
| **수정** | `app/shared/llm/lmstudio.py` | `"planner"` task 라우팅 추가 |
| **수정** | `app/mer_persona/core/deps.py` | `get_planner_llm` Depends 추가 |
| **신규** | `app/mer_persona/services/search/planner.py` | 플래너 핵심 로직 |
| **신규** | `app/mer_persona/routers/search.py` | `POST /v1/search/plan` 엔드포인트 |
| **수정** | `app/mer_persona/main.py` | search 라우터 등록 |
| **신규** | `tests/unit/test_search_planner.py` | 플래너 유닛 테스트 |
| **신규** | `tests/eval/plan_eval.jsonl` | 라우팅 평가셋 30개 |
| **신규** | `tests/eval/run_plan_eval.py` | 평가 러너 스크립트 |

---

## Task 1: Schema · Config · LLM 라우팅 기반 설정

**Files:**
- Modify: `app/mer_persona/schemas/search.py` (ToolName 클래스)
- Modify: `app/mer_persona/core/config.py`
- Modify: `app/shared/llm/lmstudio.py`
- Modify: `app/mer_persona/core/deps.py`
- Test: `tests/unit/test_search_planner.py` (부분)

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/unit/test_search_planner.py` 생성:

```python
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
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

```bash
cd /Users/limgiho/Desktop/Source/llm-platform-v2
python -m pytest tests/unit/test_search_planner.py::test_tool_name_rag_exists -v
```

예상 출력: `FAILED` — `ToolName` has no attribute `RAG`

- [ ] **Step 3: `schemas/search.py` — ToolName.RAG 추가**

`app/mer_persona/schemas/search.py` 의 `ToolName` 클래스를 다음으로 교체:

```python
class ToolName(StrEnum):
    WEB    = "web_search"
    MARKET = "market_data"
    FILES  = "local_file_search"
    RAG    = "rag_search"
```

- [ ] **Step 4: `config.py` — LMSTUDIO_MODEL_PLANNER 추가**

`app/mer_persona/core/config.py` 의 LM Studio 섹션에 아래 한 줄 추가 (`LMSTUDIO_MODEL_VERIFIER` 바로 다음):

```python
LMSTUDIO_MODEL_PLANNER: str = "qwen2.5-1.5b-instruct"
```

- [ ] **Step 5: `lmstudio.py` — planner task 라우팅 추가**

`app/shared/llm/lmstudio.py` 의 `build_llm` 함수 내 두 dict에 항목 추가:

```python
task_model_map = {
    "router": settings.LMSTUDIO_MODEL_ROUTER,
    "verifier": settings.LMSTUDIO_MODEL_VERIFIER,
    "planner": settings.LMSTUDIO_MODEL_PLANNER,   # ← 추가
}
task_timeout_map = {
    "verifier": 60,
    "router": 30,
    "planner": 15,                                 # ← 추가 (소형 모델, 타이트한 timeout)
}
```

- [ ] **Step 6: `deps.py` — get_planner_llm Depends 추가**

`app/mer_persona/core/deps.py` 의 `get_llm` 함수 바로 아래에 추가:

```python
def get_planner_llm(s: Settings = Depends(get_settings)) -> OpenAILike:
    """Planner 전용 LLM (qwen2.5-1.5b-instruct, 캐시됨)."""
    return get_llm("planner", s)
```

- [ ] **Step 7: 테스트 통과 확인**

```bash
python -m pytest tests/unit/test_search_planner.py::test_tool_name_rag_exists tests/unit/test_search_planner.py::test_tool_name_all_values -v
```

예상 출력: `2 passed`

- [ ] **Step 8: 커밋**

```bash
git add app/mer_persona/schemas/search.py \
        app/mer_persona/core/config.py \
        app/shared/llm/lmstudio.py \
        app/mer_persona/core/deps.py \
        tests/unit/test_search_planner.py
git commit -m "feat: add rag_search tool, planner model config and deps"
```

---

## Task 2: Planner 핵심 로직 (`planner.py`)

**Files:**
- Create: `app/mer_persona/services/search/planner.py`
- Modify: `tests/unit/test_search_planner.py` (테스트 추가)

- [ ] **Step 1: 실패하는 테스트 추가**

`tests/unit/test_search_planner.py` 에 아래 테스트들 추가:

```python
from app.mer_persona.services.search.planner import plan
from app.mer_persona.schemas.search import SearchPlanResponse, ToolName


# ── Task 2: 플래너 핵심 로직 ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_plan_market_data():
    """시세 질문 → market_data, rag_search/web_search 아님."""
    llm = _mock_llm(
        '{"intent":"market_data","steps":[{"tool":"market_data","query":"삼성전자 주가"}],"reason":"실시간 시세"}'
    )
    result = await plan("오늘 삼성전자 주가?", llm)
    assert isinstance(result, SearchPlanResponse)
    assert result.intent == "market_data"
    assert len(result.steps) == 1
    assert result.steps[0].tool == ToolName.MARKET
    assert result.validation_errors == []


@pytest.mark.asyncio
async def test_plan_blog_rag():
    """블로그 내용 질문 → blog_rag, rag_search 도구."""
    llm = _mock_llm(
        '{"intent":"blog_rag","steps":[{"tool":"rag_search","query":"조선업"}],"reason":"블로그 RAG"}'
    )
    result = await plan("조선업 메르 블로그 설명해줘", llm)
    assert result.intent == "blog_rag"
    assert result.steps[0].tool == ToolName.RAG


@pytest.mark.asyncio
async def test_plan_smalltalk_no_steps():
    """인사 → smalltalk, steps 없음."""
    llm = _mock_llm('{"intent":"smalltalk","steps":[],"reason":"인사"}')
    result = await plan("안녕", llm)
    assert result.intent == "smalltalk"
    assert result.steps == []


@pytest.mark.asyncio
async def test_plan_invalid_json_triggers_repair():
    """잘못된 JSON → repair 재시도 → 결과 반환."""
    bad_response = MagicMock()
    bad_response.message.content = "이건 JSON이 아닙니다"
    good_response = MagicMock()
    good_response.message.content = '{"intent":"blog_rag","steps":[],"reason":"repair 성공"}'
    llm = MagicMock()
    llm.achat = AsyncMock(side_effect=[bad_response, good_response])
    result = await plan("질문", llm)
    assert llm.achat.call_count == 2
    assert result.intent == "blog_rag"


@pytest.mark.asyncio
async def test_plan_invalid_tool_name_recorded_in_errors():
    """알 수 없는 tool → validation_errors에 기록, 해당 step 제외."""
    llm = _mock_llm(
        '{"intent":"web_search","steps":[{"tool":"unknown_tool","query":"test"}],"reason":"test"}'
    )
    result = await plan("테스트", llm)
    assert any("unknown_tool" in e for e in result.validation_errors)
    assert result.steps == []  # 유효하지 않은 step은 제외


@pytest.mark.asyncio
async def test_plan_max_steps_respected():
    """max_steps 초과 시 steps를 잘라낸다."""
    llm = _mock_llm(
        '{"intent":"mixed","steps":['
        '{"tool":"web_search","query":"a"},'
        '{"tool":"rag_search","query":"b"},'
        '{"tool":"market_data","query":"c"}'
        '],"reason":"test"}'
    )
    result = await plan("복합 질문", llm, max_steps=2)
    assert len(result.steps) <= 2


@pytest.mark.asyncio
async def test_plan_llm_error_returns_fallback():
    """LLM 예외 → fallback SearchPlanResponse 반환, 예외 전파 없음."""
    llm = MagicMock()
    llm.achat = AsyncMock(side_effect=RuntimeError("LM Studio down"))
    result = await plan("질문", llm)
    assert isinstance(result, SearchPlanResponse)
    assert result.intent == "blog_rag"
    assert result.validation_errors != []
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

```bash
python -m pytest tests/unit/test_search_planner.py -k "test_plan_" -v 2>&1 | head -20
```

예상 출력: `ImportError` 또는 `ModuleNotFoundError: planner`

- [ ] **Step 3: `planner.py` 구현**

`app/mer_persona/services/search/planner.py` 생성:

```python
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
```

- [ ] **Step 4: 테스트 통과 확인**

```bash
python -m pytest tests/unit/test_search_planner.py -k "test_plan_" -v
```

예상 출력: `7 passed`

- [ ] **Step 5: 커밋**

```bash
git add app/mer_persona/services/search/planner.py \
        tests/unit/test_search_planner.py
git commit -m "feat: implement search planner core with LLM + repair retry"
```

---

## Task 3: `/v1/search/plan` 라우터

**Files:**
- Create: `app/mer_persona/routers/search.py`
- Modify: `app/mer_persona/main.py`
- Modify: `tests/unit/test_search_planner.py` (엔드포인트 테스트 추가)

- [ ] **Step 1: 실패하는 엔드포인트 테스트 추가**

`tests/unit/test_search_planner.py` 에 아래 테스트 추가:

```python
from fastapi.testclient import TestClient
from unittest.mock import patch


# ── Task 3: 엔드포인트 ────────────────────────────────────────────────────────

def _make_plan_response(intent: str, tool: str | None = None) -> SearchPlanResponse:
    steps = []
    if tool:
        steps = [ToolCallRequest(tool=ToolName(tool), query="테스트 쿼리")]
    return SearchPlanResponse(intent=intent, steps=steps, reason="테스트", raw_output="")


@pytest.fixture
def client():
    from app.mer_persona.main import app
    return TestClient(app)


def test_search_plan_endpoint_returns_200(client):
    """POST /v1/search/plan 은 200과 SearchPlanResponse를 반환해야 한다."""
    mock_result = _make_plan_response("blog_rag", "rag_search")
    with patch(
        "app.mer_persona.routers.search.planner_svc.plan",
        new=AsyncMock(return_value=mock_result),
    ):
        resp = client.post("/v1/search/plan", json={"query": "조선업 설명해줘"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["intent"] == "blog_rag"
    assert body["steps"][0]["tool"] == "rag_search"


def test_search_plan_endpoint_query_too_short(client):
    """query가 비어있으면 422를 반환해야 한다."""
    resp = client.post("/v1/search/plan", json={"query": ""})
    assert resp.status_code == 422


def test_search_plan_endpoint_default_max_steps(client):
    """max_steps 미입력 시 기본값 3이 적용된다."""
    mock_result = _make_plan_response("smalltalk")
    with patch(
        "app.mer_persona.routers.search.planner_svc.plan",
        new=AsyncMock(return_value=mock_result),
    ) as mock_plan:
        client.post("/v1/search/plan", json={"query": "안녕"})
    mock_plan.assert_awaited_once()
    _, kwargs = mock_plan.call_args
    assert kwargs.get("max_steps", 3) == 3
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

```bash
python -m pytest tests/unit/test_search_planner.py -k "test_search_plan_endpoint" -v 2>&1 | head -15
```

예상 출력: `ImportError` 또는 `404 Not Found`

- [ ] **Step 3: `routers/search.py` 구현**

`app/mer_persona/routers/search.py` 생성:

```python
"""POST /v1/search/plan — 도구 실행 없이 플래너 결과만 반환."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from llama_index.llms.openai_like import OpenAILike

from app.mer_persona.core.deps import get_planner_llm
from app.mer_persona.schemas.search import SearchPlanRequest, SearchPlanResponse
from app.mer_persona.services.search import planner as planner_svc

router = APIRouter(tags=["search"])


@router.post("/plan", response_model=SearchPlanResponse)
async def search_plan(
    req: SearchPlanRequest,
    llm: OpenAILike = Depends(get_planner_llm),
) -> SearchPlanResponse:
    """질문을 분석해 tool 호출 계획을 반환한다. 도구를 실행하지 않는다."""
    return await planner_svc.plan(
        req.query,
        llm,
        max_steps=req.max_steps,
    )
```

- [ ] **Step 4: `main.py` — search 라우터 등록**

`app/mer_persona/main.py` 의 routers import 블록에 추가:

```python
from app.mer_persona.routers import chat_ui, mer_answer, mer_chat, search  # noqa: E402

app.include_router(chat_ui.router)
app.include_router(mer_chat.router, prefix="/v1/mer")
app.include_router(mer_answer.router, prefix="/v1/mer")
app.include_router(search.router, prefix="/v1/search")          # ← 추가
```

(기존 debug, ops include는 그대로 유지)

- [ ] **Step 5: 테스트 통과 확인**

```bash
python -m pytest tests/unit/test_search_planner.py -v
```

예상 출력: `전체 통과 (10+ passed)`

- [ ] **Step 6: 수동 smoke test (LM Studio 실행 중일 때)**

```bash
curl -s -X POST http://localhost:8000/v1/search/plan \
  -H 'Content-Type: application/json' \
  -d '{"query": "오늘 삼성전자 주가?"}' | python3 -m json.tool
```

예상: `intent: "market_data"`, `steps[0].tool: "market_data"`, 3초 이내 응답.

- [ ] **Step 7: 커밋**

```bash
git add app/mer_persona/routers/search.py \
        app/mer_persona/main.py \
        tests/unit/test_search_planner.py
git commit -m "feat: add /v1/search/plan endpoint wired to planner"
```

---

## Task 4: Eval 데이터셋 + 러너

**Files:**
- Create: `tests/eval/plan_eval.jsonl`
- Create: `tests/eval/run_plan_eval.py`

- [ ] **Step 1: `plan_eval.jsonl` 작성 (30개)**

`tests/eval/plan_eval.jsonl` 생성:

```jsonl
{"query": "오늘 삼성전자 주가 얼마야?", "expected_intent": "market_data", "expected_tools": ["market_data"], "category": "market"}
{"query": "지금 달러 환율 알려줘", "expected_intent": "market_data", "expected_tools": ["market_data"], "category": "market"}
{"query": "코스피 현재 지수", "expected_intent": "market_data", "expected_tools": ["market_data"], "category": "market"}
{"query": "비트코인 시세 알려줘", "expected_intent": "market_data", "expected_tools": ["market_data"], "category": "market"}
{"query": "HMM 주가 얼마야?", "expected_intent": "market_data", "expected_tools": ["market_data"], "category": "market"}
{"query": "최근 HMM 뉴스 찾아줘", "expected_intent": "web_search", "expected_tools": ["web_search"], "category": "web"}
{"query": "조선업 최신 뉴스 검색해줘", "expected_intent": "web_search", "expected_tools": ["web_search"], "category": "web"}
{"query": "미국 금리 인상 관련 최신 기사", "expected_intent": "web_search", "expected_tools": ["web_search"], "category": "web"}
{"query": "한국 경제 뉴스 최근 거 찾아줘", "expected_intent": "web_search", "expected_tools": ["web_search"], "category": "web"}
{"query": "OPEC 석유 감산 관련 뉴스", "expected_intent": "web_search", "expected_tools": ["web_search"], "category": "web"}
{"query": "이 프로젝트에서 intent_router가 어디 있어?", "expected_intent": "file_search", "expected_tools": ["local_file_search"], "category": "file"}
{"query": "planner.py 파일 위치 알려줘", "expected_intent": "file_search", "expected_tools": ["local_file_search"], "category": "file"}
{"query": "config.py에서 LMSTUDIO 설정 찾아줘", "expected_intent": "file_search", "expected_tools": ["local_file_search"], "category": "file"}
{"query": "조선업 관련해서 메르가 뭐라고 했는지 설명해줘", "expected_intent": "blog_rag", "expected_tools": ["rag_search"], "category": "blog_rag"}
{"query": "금리 인상이 부동산에 미치는 영향 메르 블로그 기준으로 설명해", "expected_intent": "blog_rag", "expected_tools": ["rag_search"], "category": "blog_rag"}
{"query": "메르 블로그에서 HMM 관련 내용 알려줘", "expected_intent": "blog_rag", "expected_tools": ["rag_search"], "category": "blog_rag"}
{"query": "달러 강세 이유를 메르 관점으로 설명해줘", "expected_intent": "blog_rag", "expected_tools": ["rag_search"], "category": "blog_rag"}
{"query": "투자 수익률 높이는 방법 메르 블로그 기준으로", "expected_intent": "blog_rag", "expected_tools": ["rag_search"], "category": "blog_rag"}
{"query": "최근 올라온 블로그 글 목록 보여줘", "expected_intent": "blog_list", "expected_tools": [], "category": "blog_list"}
{"query": "오늘 새 글 있어?", "expected_intent": "blog_list", "expected_tools": [], "category": "blog_list"}
{"query": "이번 주 메르 포스트 뭐 올라왔어?", "expected_intent": "blog_list", "expected_tools": [], "category": "blog_list"}
{"query": "안녕", "expected_intent": "smalltalk", "expected_tools": [], "category": "smalltalk"}
{"query": "뭐 할 수 있어?", "expected_intent": "smalltalk", "expected_tools": [], "category": "smalltalk"}
{"query": "고마워", "expected_intent": "smalltalk", "expected_tools": [], "category": "smalltalk"}
{"query": "내 포트폴리오 수익률 알려줘", "expected_intent": "reject", "expected_tools": [], "category": "reject"}
{"query": "내가 저장한 관심 종목 보여줘", "expected_intent": "reject", "expected_tools": [], "category": "reject"}
{"query": "내 거래 내역 조회해줘", "expected_intent": "reject", "expected_tools": [], "category": "reject"}
{"query": "메르 블로그 조선업 내용이랑 최신 뉴스 같이 정리해줘", "expected_intent": "mixed", "expected_tools": ["rag_search", "web_search"], "category": "mixed"}
{"query": "HMM 메르 블로그 분석이랑 현재 주가 같이 알려줘", "expected_intent": "mixed", "expected_tools": ["rag_search", "market_data"], "category": "mixed"}
{"query": "반도체 메르 관점 분석과 삼성전자 주가 알려줘", "expected_intent": "mixed", "expected_tools": ["rag_search", "market_data"], "category": "mixed"}
```

- [ ] **Step 2: `run_plan_eval.py` 작성**

`tests/eval/run_plan_eval.py` 생성:

```python
#!/usr/bin/env python3
"""Search planner eval runner.

사용법:
    python tests/eval/run_plan_eval.py
    python tests/eval/run_plan_eval.py --endpoint http://localhost:8000/v1/search/plan
    python tests/eval/run_plan_eval.py --verbose
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

EVAL_FILE = Path(__file__).parent / "plan_eval.jsonl"
DEFAULT_ENDPOINT = "http://localhost:8000/v1/search/plan"


def load_cases(path: Path) -> list[dict]:
    cases = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    return cases


def evaluate_case(case: dict, actual: dict) -> dict:
    """한 케이스의 intent/tool 정확도를 평가한다."""
    intent_ok = actual.get("intent") == case["expected_intent"]
    actual_tools = sorted(s["tool"] for s in actual.get("steps", []))
    expected_tools = sorted(case["expected_tools"])
    tools_ok = actual_tools == expected_tools
    return {
        "query": case["query"],
        "category": case.get("category", "unknown"),
        "expected_intent": case["expected_intent"],
        "actual_intent": actual.get("intent"),
        "intent_ok": intent_ok,
        "expected_tools": expected_tools,
        "actual_tools": actual_tools,
        "tools_ok": tools_ok,
        "latency_ms": actual.get("_latency_ms", 0),
        "validation_errors": actual.get("validation_errors", []),
    }


def run_eval(endpoint: str, verbose: bool = False) -> int:
    """eval을 실행하고 실패 케이스 수를 반환한다."""
    cases = load_cases(EVAL_FILE)
    results = []

    print(f"Running {len(cases)} cases against {endpoint}\n")

    with httpx.Client(timeout=30.0) as client:
        for case in cases:
            t0 = time.monotonic()
            try:
                resp = client.post(endpoint, json={"query": case["query"], "max_steps": 3})
                resp.raise_for_status()
                actual = resp.json()
                actual["_latency_ms"] = int((time.monotonic() - t0) * 1000)
            except Exception as e:
                actual = {
                    "intent": "ERROR",
                    "steps": [],
                    "validation_errors": [str(e)],
                    "_latency_ms": int((time.monotonic() - t0) * 1000),
                }
            result = evaluate_case(case, actual)
            results.append(result)
            if verbose or not (result["intent_ok"] and result["tools_ok"]):
                status = "✅" if result["intent_ok"] and result["tools_ok"] else "❌"
                print(
                    f"{status} [{result['category']}] {result['query'][:50]!r}\n"
                    f"   intent: {result['expected_intent']} → {result['actual_intent']} "
                    f"({'OK' if result['intent_ok'] else 'FAIL'})\n"
                    f"   tools:  {result['expected_tools']} → {result['actual_tools']} "
                    f"({'OK' if result['tools_ok'] else 'FAIL'})\n"
                    f"   latency: {result['latency_ms']}ms\n"
                )

    # ── 요약 ─────────────────────────────────────────────────────────────────
    total = len(results)
    intent_correct = sum(1 for r in results if r["intent_ok"])
    tools_correct = sum(1 for r in results if r["tools_ok"])
    both_correct = sum(1 for r in results if r["intent_ok"] and r["tools_ok"])
    avg_latency = sum(r["latency_ms"] for r in results) // total if total else 0

    # 카테고리별 intent 정확도
    by_category: dict[str, list[bool]] = {}
    for r in results:
        by_category.setdefault(r["category"], []).append(r["intent_ok"])

    print("\n" + "=" * 60)
    print(f"TOTAL: {total}")
    print(f"Intent accuracy : {intent_correct}/{total} ({100*intent_correct//total}%)")
    print(f"Tools  accuracy : {tools_correct}/{total} ({100*tools_correct//total}%)")
    print(f"Both   accuracy : {both_correct}/{total} ({100*both_correct//total}%)")
    print(f"Avg latency     : {avg_latency}ms")

    # ⚠️ market 오분류 (핵심 지표)
    market_cases = [r for r in results if r["category"] == "market"]
    market_wrong = [r for r in market_cases if not r["intent_ok"]]
    print(f"\n⚠️  Market 오분류: {len(market_wrong)}/{len(market_cases)} (목표: 0)")
    for r in market_wrong:
        print(f"   '{r['query']}' → {r['actual_intent']}")

    print("\nCategory breakdown (intent accuracy):")
    for cat, bools in sorted(by_category.items()):
        ok = sum(bools)
        print(f"  {cat:15s}: {ok}/{len(bools)}")

    failures = total - both_correct
    print(f"\n{'PASS' if failures == 0 else 'FAIL'} — {failures} case(s) failed")
    return failures


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Search planner eval runner")
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    sys.exit(run_eval(args.endpoint, verbose=args.verbose))
```

- [ ] **Step 3: httpx 의존성 확인**

```bash
python -c "import httpx; print(httpx.__version__)"
```

없으면:
```bash
uv add httpx
```

- [ ] **Step 4: eval 파일 문법 검증**

```bash
python -c "
import json
from pathlib import Path
cases = [json.loads(l) for l in Path('tests/eval/plan_eval.jsonl').read_text().splitlines() if l.strip()]
print(f'Loaded {len(cases)} cases')
cats = {}
for c in cases: cats[c['category']] = cats.get(c['category'], 0) + 1
for k,v in sorted(cats.items()): print(f'  {k}: {v}')
"
```

예상 출력:
```
Loaded 30 cases
  blog_list: 3
  blog_rag: 5
  file: 3
  market: 5
  mixed: 3
  reject: 3
  smalltalk: 3
  web: 5
```

- [ ] **Step 5: 베이스라인 eval 실행 (앱 + LM Studio 실행 중일 때)**

```bash
python tests/eval/run_plan_eval.py --verbose 2>&1 | tee /tmp/planner_eval_baseline.txt
```

결과를 확인해 오분류 패턴을 파악한다. 특히:
- Market 오분류가 있으면 프롬프트 강화 우선
- 전체 intent 정확도 < 70% 면 모델 업사이즈(3B) 검토

- [ ] **Step 6: 커밋**

```bash
git add tests/eval/plan_eval.jsonl tests/eval/run_plan_eval.py
git commit -m "feat: add search planner eval dataset (30 cases) and runner"
```

---

## Self-Review

**Spec 커버리지:**
- [x] `planner.py` 신규 — Task 2
- [x] `/v1/search/plan` 엔드포인트 — Task 3
- [x] `ToolName.RAG` 추가 — Task 1
- [x] `LMSTUDIO_MODEL_PLANNER` config — Task 1
- [x] `get_planner_llm` Depends — Task 1
- [x] eval 셋 30개 + 러너 — Task 4
- [x] 양자화 제외 원칙 — config 기본값이 모델명만 지정, 파일 체크는 운영자 몫 (스펙 "원칙"으로 문서화됨)
- [x] repair 재시도 1회 — Task 2 구현
- [x] max_steps truncation — Task 2 구현
- [x] LLM 오류 시 fallback — Task 2 구현
- [x] validation_errors 필드 — Task 2 구현
- [ ] **열린 결정 1 (blog_list Postgres 분기)** — 이 플랜 범위 밖, /v1/search/answer 구현 시 결정

**Type 일관성:**
- `planner.plan()` → `SearchPlanResponse` ✓
- `routers/search.py` 에서 `planner_svc.plan()` 호출 ✓ (import: `from app.mer_persona.services.search import planner as planner_svc`)
- `ToolCallRequest(tool=ToolName(...), query=...)` ✓ (top_k=5, args={} 기본값 적용)
- 테스트의 `_make_plan_response` → `ToolCallRequest` 직접 생성 ✓

**플레이스홀더:** 없음. 모든 단계에 실제 코드 포함.
