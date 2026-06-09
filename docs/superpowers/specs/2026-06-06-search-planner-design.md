# Search Planner v1 설계 스펙

**작성일**: 2026-06-06  
**상태**: 승인됨  
**대상 코드베이스**: llm-platform-v2

---

## 배경 & 목적

현재 `llm-platform-v2`의 답변 파이프라인은 다음 병목을 가진다:

- **Intent 분류**: reasoning 모델(`qwen3.5-4b-...-distilled`)이 분류 1회에 11~22초 소모.
- **모델 스왑**: task별 모델이 달라 LM Studio가 요청마다 디스크 재로딩 → 답변 1건에 최대 111초.

이를 해결하기 위해 **Search Planner v1**을 도입한다:

- 단일 소형 LLM이 "어떤 도구를 쓸지" 고르는 플래너/분류기 역할.
- llama.cpp 상주로 모델 스왑 제거 → 분류 <300ms 목표.
- Codex가 병행 구현 중인 `/v1/search/*` 검색 도구 계층과 합류.

llm-platform-v2는 메르 블로그 RAG를 넘어 **범용 로컬 LLM 게이트웨이**로 확장되며, 댓글필터(merblFilter) 등 외부 클라이언트가 호출한다. 플래너는 그 통합 입구(unified entry point)다.

---

## 범위 (Scope)

### 내 lane (이 스펙)

- `app/mer_persona/services/search/planner.py` 신규
- `app/mer_persona/routers/search.py` 신규: `/v1/search/plan` 엔드포인트
- `tests/eval/plan_eval.jsonl` + eval 러너 신규
- `schemas/search.py`에 `rag_search` ToolName 추가

### Codex lane (이 스펙 범위 밖)

- `app/mer_persona/services/search/web.py`, `market.py`, `tools.py` (도구 실행부)
- `/v1/search/answer` (agent loop + 합성) — Codex 도구 완성 후 합류

### 공유 계약 (변경 최소화)

```python
# schemas/search.py — 이미 정의됨, rag_search만 추가
class ToolName(StrEnum):
    WEB    = "web_search"
    MARKET = "market_data"
    FILES  = "local_file_search"
    RAG    = "rag_search"       # ← 이 스펙에서 추가

class SearchPlanResponse(BaseModel):
    intent: str                          # 굵은 의도 라벨
    steps: list[ToolCallRequest]         # 0~N개 도구 호출
    reason: str
    raw_output: str = ""
    validation_errors: list[str] = []
```

---

## 모델 & 서빙

### 모델 선택 원칙

> **양자화 모델 제외**: 플래너의 라우팅 품질이 전체 파이프라인 정확도를 결정하므로,
> 공격적 양자화(Q4 이하)는 사용하지 않는다. fp16/bf16 또는 Q8 이상만 허용.
> 모델 크기 절감은 양자화가 아닌 **더 작은 비양자화 모델 선택**으로 해결한다.

### v1 시작 모델

| 항목 | 값 |
|---|---|
| 모델 | `qwen2.5-1.5b-instruct` (fp16 또는 Q8) |
| 이유 | LM Studio에 이미 로드됨, 비-reasoning, 소형(빠름), 검증 베이스라인 |
| Temperature | 0 (결정적 출력) |
| max_tokens | 256 (도구 리스트 생성에 충분) |

### 목표 서빙 형태 (v2 전환 시)

- **llama.cpp 전용 상주 프로세스** (포트 분리, 별도 llama-server 인스턴스)
- **GBNF 문법 제약**: 플래너 출력을 유효한 `SearchPlanResponse` JSON 형식으로 강제
- 단일 forward logprob 분류 옵션(생성 없이 라벨 확률만 읽기) — 추후 검토

> v1에서는 기존 LM Studio 호환 OpenAILike 클라이언트로 시작, llama.cpp 이전 시 클라이언트만 교체.

---

## 출력 분류 체계

### Intent 라벨

| intent | 설명 | steps |
|---|---|---|
| `smalltalk` | 인사·잡담·시스템 질문 | 0개 (바로 답변) |
| `blog_rag` | 메르 블로그 내용 기반 답변 | `[rag_search]` |
| `blog_list` | 블로그 글 목록·검색 | 0개 (Postgres 직접) |
| `web_search` | 최신 뉴스·공개 정보 | `[web_search]` |
| `market_data` | 시세·환율·주가 | `[market_data]` |
| `file_search` | 로컬 코드·문서 검색 | `[local_file_search]` |
| `mixed` | 복합 정보 필요 | 2~3개 도구 조합 |
| `reject` | 실시간 정보·내부DB 등 처리 불가 | 0개 (거절 메시지) |

### 강한 라우팅 규칙 (프롬프트에 명시)

1. 시세·환율·주가·지수 → **반드시 `market_data`**, `web_search` 금지.
2. 블로그 글 목록/검색만 원하면 → `blog_list` (steps 0개, Postgres 직접 처리).
3. 블로그 내용 설명·요약 → `blog_rag`.
4. 로컬 파일/코드 위치 → `file_search`.

---

## 플래너 구현 (`planner.py`)

### 입력

```python
async def plan(
    query: str,
    llm: OpenAILike,
    *,
    recent_turns: list[tuple[str, str]] | None = None,
    max_steps: int = 3,
) -> SearchPlanResponse:
```

### 처리 흐름

```
query
  ↓
[1] 시스템 프롬프트 빌드 (few-shot + 강한 규칙 + 대화맥락)
  ↓
[2] LLM 호출 → raw JSON 출력
  ↓
[3] JSON 파싱 + Pydantic 검증
  ↓ 실패 시
[4] repair prompt 재시도 1회 (원 출력 + 에러 메시지 포함)
  ↓ 재실패 시
[5] fallback: intent="blog_rag", steps=[], validation_errors 기록
  ↓
SearchPlanResponse 반환
```

### 시스템 프롬프트 골격

```
너는 검색 도구 플래너다. 질문을 보고 어떤 도구를 몇 번 쓸지 JSON으로 답해라.

도구 목록: web_search | market_data | local_file_search | rag_search

강한 규칙:
- 시세/환율/주가 → market_data만 (web_search 절대 금지)
- 처리 불가 → intent=reject, steps=[]

출력 형식 (한 줄 JSON):
{"intent":"<라벨>","steps":[{"tool":"<도구>","query":"<검색어>"}],"reason":"<한줄근거>"}

Few-shot 예시:
Q: 오늘 삼성전자 주가? → {"intent":"market_data","steps":[{"tool":"market_data","query":"삼성전자"}],"reason":"실시간 시세"}
Q: 조선업 메르 블로그 내용 설명해줘 → {"intent":"blog_rag","steps":[{"tool":"rag_search","query":"조선업"}],"reason":"블로그 RAG"}
Q: HMM 최신 뉴스 찾아줘 → {"intent":"web_search","steps":[{"tool":"web_search","query":"HMM 뉴스"}],"reason":"최신 웹 검색"}
Q: 안녕 → {"intent":"smalltalk","steps":[],"reason":"인사"}
```

---

## 엔드포인트

### `POST /v1/search/plan`

- 목적: 도구 실행 없이 플랜만 반환 (디버그·검증용)
- 입력: `SearchPlanRequest{query, max_steps}`
- 출력: `SearchPlanResponse{intent, steps, reason, raw_output, validation_errors}`
- LLM 1회 호출 (repair 포함 최대 2회)
- 이 엔드포인트는 `/v1/search/answer` 없이도 단독 테스트 가능

---

## 지속 검증 루프

### eval 셋 (`tests/eval/plan_eval.jsonl`)

형식:
```jsonl
{"query": "오늘 삼성전자 주가?", "expected_intent": "market_data", "expected_tools": ["market_data"]}
{"query": "조선업 메르 블로그 설명해줘", "expected_intent": "blog_rag", "expected_tools": ["rag_search"]}
{"query": "최근 HMM 뉴스", "expected_intent": "web_search", "expected_tools": ["web_search"]}
...
```

카테고리: web(5) / market(5) / file(3) / blog_rag(5) / blog_list(3) / smalltalk(3) / reject(3) / mixed(3) = 30개 시작.

### eval 러너 (`tests/eval/run_plan_eval.py`)

측정 항목:
- **intent 정확도** (전체 / 카테고리별)
- **tool_set 정확도** (예상 도구 집합 일치)
- **plan 지연(ms)** (LLM 호출 포함)
- market 질문이 web_search로 빠지는 비율 (0% 목표)

실행:
```bash
python tests/eval/run_plan_eval.py --endpoint http://localhost:8000/v1/search/plan
```

---

## 속도 목표

| 경로 | 현재 | 목표(v1) | 목표(v2 llama.cpp) |
|---|---|---|---|
| Intent 분류 | 11~22초 | <3초 | <300ms |
| 답변 생성(RAG) | ~90초 | (변동 없음, 별도 개선) | (모델 스왑 제거로 단축) |

---

## 구현 계획 요약 (Phase)

| Phase | 내용 |
|---|---|
| 1 | `ToolName.RAG` 추가, `planner.py` 신규, `/v1/search/plan` 라우터 연결 |
| 2 | eval 셋 30개 + 러너 작성, intent/tool 정확도 측정 |
| 3 | few-shot 보강·프롬프트 튜닝 (eval 기반 반복) |
| 4 | llama.cpp 이전 + GBNF 문법제약 적용 |
| 5 | `/v1/search/answer` Codex agent loop에 플래너 합류 |

---

## 미결 사항 (열린 결정)

1. `blog_list` 처리: 플래너가 `steps=[]`로 반환 시 라우터가 Postgres 직접 조회하게 할지, 아니면 별도 핸들러로 분기할지.
2. `mixed` intent 시 step 순서(병렬 vs 순차) 결정 — Codex agent loop 설계에 따름.
3. llama.cpp 이전 시점: eval 정확도 목표치(예: intent 90%↑) 달성 후 전환.
4. GBNF 문법 파일 관리 위치: `app/mer_persona/services/search/grammars/` 예정.
