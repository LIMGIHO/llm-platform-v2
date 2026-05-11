# llm-platform-v2

메르(머니스미스) 페르소나 RAG QA 플랫폼 v2.  
LlamaIndex + LM Studio + Qdrant + Postgres + Redis.

---

## 아키텍처

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

### 3. 인프라 + 앱 기동

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
| GET | `/v1/debug/traces` | 최근 트레이스 목록 |
| GET | `/v1/debug/traces/{id}` | 트레이스 상세 + 단계별 타이밍 |
| GET | `/metrics` | Prometheus 메트릭 |
| GET | `/healthz` | 헬스체크 |

---

## 설정 (`.env`)

`deploy/env/.env.example`을 복사해서 수정:

```bash
cp deploy/env/.env.example deploy/env/.env
```

주요 설정:

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

---

## 개발

```bash
make test     # pytest (57개 단위 테스트)
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
    ├── unit/              # 57개 단위 테스트
    └── eval/              # 30개 평가셋 + runner
```
