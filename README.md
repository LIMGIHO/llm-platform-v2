# llm-platform-v2

경제 블로거 메르의 글과 댓글을 검색해 질문에 답하고, 근거가 된 원문을 함께 보여주는 개인 프로젝트입니다.

LlamaIndex + LM Studio + Qdrant + Postgres + Redis.

[Vercel에서 공개 챗봇 사용해 보기](https://merbl-filter.vercel.app/posts?merChat=all)

---

## 질의응답 API 구조 (`/v1/mer/answer`)

아래 도식은 이 저장소의 질의응답 API가 질문을 처리하는 과정입니다. 위 데모는 별도의 공개 채팅 경로를 사용합니다.

```
사용자 질문
  │
  ├── Intent Router (Qwen3.5-4B)
  │     ├── needs_fresh / internal_db  → 거절 응답
  │     └── smalltalk                  → 직접 LLM 답변
  │
  ├── Hybrid Retrieval
  │     ├── Vector (Qdrant, bge-m3)
  │     └── BM25  (kiwipiepy, pickle)
  │     → QueryFusionRetriever (RRF) → Reranker (bge-reranker-v2-m3)
  │
  ├── Style Pack (Qdrant mer_style, few-shot 어조 예시)
  │
  ├── Prompt Builder  →  Gemma 4 E4B
  │
  └── Verifier (Qwen3.5-9B)  →  VerifierResult
        │
        └── Postgres traces / trace_steps
```

## 빠른 시작

### 1. 의존성 설치

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
make setup
```

### 2. LM Studio 준비

LM Studio에서 다음 모델을 다운로드하고 서버를 `0.0.0.0:1234`로 기동:

| 모델 | 용도 |
|------|------|
| `google/gemma-4-e4b` | 메인 답변 생성 |
| `qwen3.5-4b-claude-4.6-opus-reasoning-distilled` | Intent Router |
| `qwen/qwen3.5-9b` | Verifier |
| `text-embedding-bge-m3` | Embedding (1024-dim) |

### 3. 환경 설정 및 기동

처음 실행할 때는 예제 환경 파일을 복사한 뒤 모델과 데이터베이스 연결 값을 확인합니다.

```bash
cp -n deploy/env/.env.example deploy/env/.env
```

```bash
make up-infra       # Postgres, Qdrant, Redis
make migrate        # DB 스키마 초기화
make up-app         # FastAPI 앱 (포트 8000)
make up-obs         # Prometheus + Grafana (선택)
```

### 4. 데이터 인제스트

```bash
# v1 데이터 마이그레이션 (Postgres)
uv run python -m batch.main migrate-v1 --from-dir /data/import

# 블로그 포스트 인덱싱 (Qdrant + BM25)
make ingest-blog

# 댓글 인덱싱 (스타일 팩 포함)
uv run python -m batch.main ingest-comments
```

### 5. 동작 확인

```bash
curl -s http://localhost:8000/healthz | jq
curl -s -X POST http://localhost:8000/v1/mer/answer \
  -H "Content-Type: application/json" \
  -d '{"query": "금리가 오르면 채권 가격이 왜 내려가나요?"}' | jq .answer
```

---

## 주요 엔드포인트

| Method | Path | 설명 |
|--------|------|------|
| POST | `/v1/mer/answer` | RAG + Intent + Verify 답변 |
| POST | `/v1/mer/chat` | 단순 대화 (Redis 히스토리) |
| POST | `/v1/mer/retrieve` | 디버그용 retrieval 결과 |
| POST | `/v1/search/plan` | 검색 도구 선택 계획 확인 |
| POST | `/v1/search/answer` | 제한된 Retrieval Agent 답변 |
| POST | `/v1/search/tools/files` | 로컬 파일 검색 단독 테스트 |
| POST | `/v1/search/tools/web` | 웹 검색 도구 단독 테스트 |
| POST | `/v1/search/tools/market` | 시장 데이터 도구 단독 테스트 |
| GET | `/v1/debug/traces` | 최근 트레이스 목록 |
| GET | `/v1/debug/traces/{id}` | 트레이스 상세 + 단계별 타이밍 |
| GET | `/metrics` | Prometheus 메트릭 |
| GET | `/healthz` | 헬스체크 |

---

## 설정 (`.env`)

빠른 시작에서 준비한 `deploy/env/.env`의 주요 설정은 다음과 같습니다.

```dotenv
LMSTUDIO_BASE_URL=http://host.docker.internal:1234/v1
LMSTUDIO_CHAT_MODEL=google/gemma-4-e4b
LMSTUDIO_MODEL_ROUTER=qwen3.5-4b-claude-4.6-opus-reasoning-distilled
LMSTUDIO_MODEL_VERIFIER=qwen/qwen3.5-9b
LMSTUDIO_EMBED_MODEL=text-embedding-bge-m3
PG_DSN=postgresql+psycopg://llm-platform:1234@postgres:5432/llm-platform
QDRANT_URL=http://qdrant:6333
REDIS_URL=redis://redis:6379/0
```

### Search API

`/v1/search/tools/files`는 LLM 없이 동작하는 로컬 파일 검색 도구입니다.
`/v1/search/tools/web`와 `/v1/search/tools/market`는 provider가 설정되지 않으면 명확한 502 오류를 반환합니다.
통합 `/v1/search/answer`는 먼저 bounded Retrieval Agent 형태로 파일 검색 경로를 검증하고, provider 설정 후 웹/시장 데이터 도구를 확장합니다.

---

## 개발

```bash
make test     # pytest 단위 테스트 실행
make lint     # ruff check
make fmt      # ruff format

# 평가 (앱이 기동된 상태에서)
uv run python tests/eval/run_eval.py --url http://localhost:8000
```

---

## 디렉토리 구조

```
llm-platform-v2/
├── app/
│   ├── mer_persona/
│   │   ├── core/          # config, logging, metrics, deps
│   │   ├── routers/       # mer_answer, mer_chat, debug
│   │   ├── schemas/       # Pydantic 모델
│   │   └── services/
│   │       ├── index/     # vector_index, bm25_index
│   │       ├── mer/       # intent_router, verifier, prompt_builder, ...
│   │       ├── retrieval/ # hybrid_retriever, reranker, query_rewriter
│   │       └── tracing.py
│   └── shared/
│       ├── cache/         # Redis
│       ├── db/            # SQLAlchemy 모델 + 세션
│       ├── llm/           # LM Studio 빌더
│       └── utils/         # 한국어 토크나이저
├── batch/
│   ├── ingest/            # 로더, 파서, Qdrant 라이터
│   └── jobs/              # ingest_blog, ingest_comments, migrate_v1, ...
├── deploy/
│   ├── compose.*.yml
│   ├── Dockerfile.app
│   ├── Dockerfile.batch
│   └── env/               # .env.example, prometheus.yml, grafana/
├── infra/
│   └── migrations/        # SQL 스키마
└── tests/
    ├── unit/              # 단위 테스트
    └── eval/              # 30개 평가셋 + runner
```
