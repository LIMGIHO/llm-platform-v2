# llm-platform-v2 설계 계획서

작성일: 2026-05-03
기준 v1: `llm-platform` (Ollama + Qdrant + 자체 hybrid retrieval, gateway/llm-adapter/blogger-api 다중 서비스)

---

## 1. 목표 & 핵심 결정 사항

### 1.1 목표
메르 페르소나(블로그 + 댓글 기반 RAG QA)를 LlamaIndex 기반 파이프라인으로 재구성하고, 배포 환경이 바뀌어도 빠르게 올릴 수 있도록 **역할별 컨테이너**(DB / 앱 / 배치 / 관측)로 분리한다.

### 1.2 핵심 결정 (사용자 확인 완료)
| 항목 | 결정 |
|---|---|
| LLM 백엔드 | **LM Studio 단독** (OpenAI 호환 endpoint, chat + embedding) |
| 기본 채팅 모델 | **Gemma 4 E4B** (메인 합성용). Qwen3.5 4B는 분류/라우팅, Qwen3.5 9B는 verifier 등 task별 라우팅 |
| 임베딩 모델 | **bge-m3** (1024차원, 다국어/한국어 강함, 8K 컨텍스트). LM Studio에서 GGUF로 로드 |
| 데이터 마이그레이션 | **v1에서 원본만 export → v2 ingest 파이프라인으로 재인덱싱** |
| 서비스 분리 | **app(질의) / batch(ingest) 두 컨테이너**로 코드 레벨부터 분리 |
| 관측 스택 | **Prometheus + Grafana + Postgres trace 테이블** (Loki/cAdvisor는 옵션) |
| 페르소나 범위 | 메르 페르소나 단일. 단, `app/<persona>/` 패턴으로 확장 가능하게 |
| 패키지 매니저 | **uv** (pyproject.toml + uv.lock, Docker 캐시 친화적) |
| BM25 영속화 | **파일 pickle** (`/data/bm25/<collection>.pkl`). batch가 빌드 → app이 로드 |
| Python 버전 | **3.12** (LlamaIndex 최신 안정 호환) |
| 레포 전략 | **단일 monorepo**. `app/`, `batch/`, `app/shared/` 한 트리, 단일 `pyproject.toml`/`uv.lock`. Dockerfile만 분리(`Dockerfile.app`, `Dockerfile.batch`) |

### 1.3 비기능 요구사항
- 새 서버에 `git clone && docker compose up -d` 한 번으로 기동.
- DB/벡터스토어 데이터 볼륨은 분리 가능(NFS, 외부 볼륨, 클라우드 디스크 모두 지원).
- LM Studio는 **호스트에서 실행되는 외부 의존**으로 다룸 (컨테이너 내부에 GPU 모델을 띄우지 않음).
- ingest 작업은 app과 별개 컨테이너에서 cron / on-demand 실행.

---

## 2. 시스템 토폴로지

```
┌────────────────────────────────────────────────────────────────────┐
│ 호스트(Mac/Linux)                                                  │
│  ┌──────────────┐                                                  │
│  │ LM Studio    │ ← OpenAI 호환 :1234 (chat + embedding)          │
│  └──────┬───────┘                                                  │
│         │                                                          │
│  ┌──────┴────────── docker network: mer-net ──────────────────┐   │
│  │                                                              │   │
│  │  ┌─────────────┐   ┌──────────────┐   ┌───────────────┐    │   │
│  │  │ app         │   │ batch        │   │ observability │    │   │
│  │  │ (FastAPI)   │   │ (CLI/cron)   │   │ prom + graf   │    │   │
│  │  │  :8000      │   │              │   │  :9090 :3000  │    │   │
│  │  └─────┬───────┘   └──────┬───────┘   └──────┬────────┘    │   │
│  │        │                  │                   │             │   │
│  │  ┌─────┴──────────────────┴───────────────────┴────────┐   │   │
│  │  │  shared infra                                        │   │   │
│  │  │  postgres :5432    qdrant :6333    redis :6379       │   │   │
│  │  └──────────────────────────────────────────────────────┘   │   │
│  └─────────────────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────────────────┘
```

### 2.1 docker-compose 분리
v2는 `compose.*.yml`로 stack을 쪼갠다.

```
deploy/
  compose.infra.yml         # postgres, qdrant, redis (영속 볼륨)
  compose.app.yml           # app (FastAPI 질의 서버)
  compose.batch.yml         # batch (ingest job, cron worker)
  compose.observability.yml # prometheus, grafana, (옵션) loki, promtail
  compose.dev.yml           # 개발 override (hot reload, port 노출)
```

운영 시 조합:
- 풀스택: `docker compose -f compose.infra.yml -f compose.app.yml -f compose.batch.yml -f compose.observability.yml up -d`
- 앱만(외부 DB 사용): `docker compose -f compose.app.yml up -d`
- 배치 단독 호스트: `compose.infra.yml + compose.batch.yml`

### 2.2 컨테이너별 역할
| 컨테이너 | 역할 | 외부 포트 | 주요 환경 |
|---|---|---|---|
| `mer-app` | 질의/응답 FastAPI, Verifier 포함 | 8000 | `LMSTUDIO_BASE_URL`, `QDRANT_URL`, `PG_DSN` |
| `mer-batch` | 블로그/댓글 ingest, 인덱스 빌드, 스타일팩 빌드 | - | 동일 + `BATCH_MODE`, cron 스케줄 |
| `postgres` | 본문/메타/트레이스/스타일 DB | 5432 | `POSTGRES_*` |
| `qdrant` | 벡터스토어 | 6333 | - |
| `redis` | 캐시(쿼리 재작성, retrieval 결과), 비동기 큐 | 6379 | - |
| `prometheus` | 메트릭 수집 | 9090 | - |
| `grafana` | 대시보드 | 3000 | `GF_*` |

---

## 3. 코드 구조 (앱 단위 분리)

루트:

```
llm-platform-v2/
├── app/
│   ├── mer_persona/          # ← v2의 핵심 (질의 + 답변)
│   │   ├── main.py           # FastAPI entrypoint (app 컨테이너)
│   │   ├── routers/
│   │   │   ├── mer_chat.py
│   │   │   ├── mer_answer.py
│   │   │   └── debug.py
│   │   ├── schemas/
│   │   │   ├── mer.py
│   │   │   ├── chat.py
│   │   │   └── retrieve.py
│   │   ├── services/
│   │   │   ├── llm/
│   │   │   │   ├── llm_router.py      # 백엔드 추상화 (현재 LM Studio 단일)
│   │   │   │   └── lmstudio_llm.py    # LlamaIndex LLM 래퍼
│   │   │   ├── index/
│   │   │   │   ├── vector_index.py    # Qdrant 연결 + LlamaIndex VectorStoreIndex
│   │   │   │   ├── bm25_index.py      # BM25Retriever (in-memory + 영속화)
│   │   │   │   ├── qdrant_store.py    # QdrantVectorStore wrapper
│   │   │   │   └── postgres_store.py  # Document/메타 조회
│   │   │   ├── retrieval/
│   │   │   │   ├── query_rewriter.py  # HyDE / multi-query
│   │   │   │   ├── hybrid_retriever.py# QueryFusionRetriever (vector+BM25)
│   │   │   │   ├── metadata_filter.py
│   │   │   │   └── reranker.py        # SentenceTransformer rerank or LLM rerank
│   │   │   └── mer/
│   │   │       ├── intent_router.py   # smalltalk/근거질문/검색/내부DB/최신성 분류
│   │   │       ├── evidence_builder.py
│   │   │       ├── style_pack_builder.py
│   │   │       ├── prompt_builder.py
│   │   │       ├── response_synthesizer.py
│   │   │       └── verifier.py
│   │   └── core/
│   │       ├── config.py     # pydantic-settings
│   │       ├── logging.py    # 구조화 로그(JSON) + trace_id
│   │       ├── tracing.py    # Postgres trace 테이블 기록
│   │       └── deps.py       # FastAPI Depends 모음
│   │
│   └── shared/               # app과 batch가 공유하는 코드
│       ├── llm/              # LLM/embedding 클라이언트
│       ├── db/               # SQLAlchemy 모델, 세션
│       ├── schemas/          # 공통 Pydantic
│       └── utils/
│
├── batch/                    # ← ingest/build 작업 (batch 컨테이너)
│   ├── main.py               # CLI entrypoint (typer/click)
│   ├── jobs/
│   │   ├── ingest_blog.py    # blog_loader + node_parser + dual-index
│   │   ├── ingest_comments.py
│   │   ├── rebuild_bm25.py
│   │   ├── refresh_style_pack.py
│   │   └── snapshot_qdrant.py
│   ├── ingest/
│   │   ├── blog_loader.py    # v1 export → Document
│   │   ├── comment_loader.py
│   │   ├── node_parser.py    # SemanticSplitter or SentenceWindow
│   │   └── metadata_builder.py
│   └── scheduler/
│       └── cron.py           # APScheduler 또는 host cron
│
├── deploy/
│   ├── compose.infra.yml
│   ├── compose.app.yml
│   ├── compose.batch.yml
│   ├── compose.observability.yml
│   ├── compose.dev.yml
│   ├── Dockerfile.app
│   ├── Dockerfile.batch
│   └── env/
│       ├── .env.example
│       └── prometheus.yml, grafana/...
│
├── infra/
│   ├── migrations/           # Alembic
│   └── scripts/
│       ├── init_db.sh
│       └── init_qdrant.sh
│
├── tests/
│   ├── unit/
│   ├── integration/          # docker-compose 띄워서 검증
│   └── eval/                 # 메르 답변 품질 평가셋
│
├── pyproject.toml            # uv or poetry, app/batch 동일 lock
├── Makefile
└── docs/
    └── v2-plan.md            # 이 문서
```

`app/`과 `batch/`가 둘 다 `app/shared/`를 import → Dockerfile에서 build context를 루트로 두고, 각 이미지마다 entrypoint만 다르게.

### 3.1 Monorepo + 이미지 분리 전략
- **하나의 git 레포 / 하나의 `pyproject.toml` / 하나의 `uv.lock`**으로 의존성을 단일 관리(버전 드리프트 방지).
- 의존성 그룹은 uv의 optional/dependency-groups로 분리:
  ```toml
  [project]
  dependencies = ["fastapi", "llama-index", "qdrant-client", ...]   # 공통
  [dependency-groups]
  app   = ["uvicorn", "sentence-transformers"]   # 질의 서버 전용
  batch = ["typer", "apscheduler", "kiwipiepy"]  # 배치 전용
  dev   = ["pytest", "ruff", "mypy"]
  ```
- `Dockerfile.app`은 `uv sync --group app`, `Dockerfile.batch`는 `uv sync --group batch`로 이미지 슬림화.
- 빌드 컨텍스트는 항상 레포 루트 → `app/shared/` 동일 코드 사용.
- CI는 변경된 폴더만 감지해서 해당 이미지만 재빌드(`paths` 트리거).

---

## 4. LlamaIndex 매핑 표

사용자가 그린 파이프라인을 LlamaIndex 클래스로 1:1 매핑.

| 파이프라인 단계 | 구현 (LlamaIndex) | 위치 |
|---|---|---|
| Intent 분류 | LLM 기반 분류기 (`Settings.llm`로 1-shot) → `IntentRoute` enum | `mer/intent_router.py` |
| Query Rewriter | `HyDEQueryTransform` + custom multi-query | `retrieval/query_rewriter.py` |
| Tool 선택 | `RouterRetriever` / `RouterQueryEngine` (PydanticSelector) | `retrieval/router.py` (신규) |
| Vector retrieval | `VectorIndexRetriever` over `QdrantVectorStore` | `index/vector_index.py` |
| BM25 retrieval | `BM25Retriever` (corpus 영속화) | `index/bm25_index.py` |
| Hybrid 융합 | `QueryFusionRetriever` (RRF) | `retrieval/hybrid_retriever.py` |
| 메타 필터 | `MetadataFilters` (date range, category, source_type) | `retrieval/metadata_filter.py` |
| Rerank | `SentenceTransformerRerank` 또는 `LLMRerank` | `retrieval/reranker.py` |
| Postprocess | `SimilarityPostprocessor`, custom dedup, recency boost | `retrieval/postprocess.py` |
| Evidence pack | NodeWithScore 정제 + citation id 부여 | `mer/evidence_builder.py` |
| Style pack | 댓글 corpus에서 few-shot 샘플링(키워드/주제 일치) | `mer/style_pack_builder.py` |
| Prompt 조립 | `PromptTemplate` + 시스템/페르소나/근거/스타일/히스토리 | `mer/prompt_builder.py` |
| 합성 | `Refine` 또는 `CompactAndRefine` Synthesizer 커스텀 | `mer/response_synthesizer.py` |
| Verifier | NLI 또는 LLM self-check (근거 ↔ 답변 entailment, citation 누락) | `mer/verifier.py` |
| Tracing | LlamaIndex `CallbackManager` → Postgres `traces` 테이블 | `core/tracing.py` |

---

## 5. LM Studio 연동

LM Studio는 OpenAI 호환 서버를 띄움(`/v1/chat/completions`, `/v1/embeddings`).

```python
# app/shared/llm/lmstudio.py
from llama_index.llms.openai_like import OpenAILike
from llama_index.embeddings.openai_like import OpenAILikeEmbedding

def build_llm(settings, task: str = "default"):
    """task별로 다른 모델을 라우팅 (intent_router='qwen3.5-4b', verifier='qwen3.5-9b' 등)"""
    model = settings.LMSTUDIO_MODELS.get(task, settings.LMSTUDIO_CHAT_MODEL)
    return OpenAILike(
        model=model,                                # 기본: "gemma-4-e4b"
        api_base=settings.LMSTUDIO_BASE_URL,        # ex: "http://host.docker.internal:1234/v1"
        api_key="lm-studio",                        # placeholder
        is_chat_model=True,
        temperature=0.2,
        timeout=settings.LLM_TIMEOUT_SEC,
        context_window=settings.LMSTUDIO_CTX,
    )

def build_embed_model(settings):
    return OpenAILikeEmbedding(
        model_name=settings.LMSTUDIO_EMBED_MODEL,   # "bge-m3" (1024차원)
        api_base=settings.LMSTUDIO_BASE_URL,
        api_key="lm-studio",
        embed_batch_size=32,
    )
```

- 컨테이너에서 호스트의 LM Studio로 가려면 `host.docker.internal`(Mac/Win) 또는 `extra_hosts: ["host.docker.internal:host-gateway"]`(Linux) 사용.
- 모델 버전 추적: 호출 시 LM Studio가 돌려주는 `model` 필드를 trace에 기록.
- 라우터 단일 백엔드라도 `llm_router.py`에 `Backend` 인터페이스를 두어 향후 vLLM/외부 API 추가 시 한 곳만 바꾸도록.

---

## 6. 데이터 모델

### 6.1 Postgres 스키마 (요약)
```
mer_blog_posts(id, post_id_src, title, url, published_at, category, raw_html, raw_text, hash, ingested_at)
mer_blog_comments(id, post_id, author, body, written_at, hash)
mer_nodes(id, source_type, source_id, chunk_no, text, hash, qdrant_point_id, metadata jsonb, created_at)
mer_style_examples(id, comment_id, topic_tags text[], embedding_id, score)
traces(id uuid, conversation_id, started_at, finished_at, intent, model, prompt_version, tokens_in, tokens_out, latency_ms, status, meta jsonb)
trace_steps(id, trace_id, step, started_at, finished_at, payload jsonb)
conversations(id, started_at, last_at, persona, meta jsonb)
conversation_messages(id, conversation_id, role, content, created_at, citations jsonb)
```

### 6.2 Qdrant
- 컬렉션 `mer_blog`: **vector(1024, bge-m3)**, distance=`Cosine`, payload = {post_id, title, url, published_at, category, source_type:'blog', chunk_no, hash}
- 컬렉션 `mer_comments`: 동일 + source_type:'comment'
- 컬렉션 `mer_style`: 메르식 어조 댓글 임베딩 (style retrieval 용)
- 컬렉션은 ingest 시 hash 기반 upsert(idempotent).
- 임베딩 모델 교체 시 컬렉션 재생성이 필요하므로, 컬렉션 이름에 임베딩 식별자 suffix 옵션: `mer_blog__bgem3`.

### 6.3 BM25 (파일 pickle 영속화)
- batch가 토큰화된 corpus + DocStore를 `/data/bm25/<collection>.pkl`로 직렬화.
- app은 시작할 때 파일을 메모리로 로드(read-only). 검색은 인메모리.
- batch가 갱신하면 `POST /v1/admin/bm25/reload`로 핫 리로드(파일 mtime 비교).
- 한국어 토큰화는 `mecab-ko` 또는 `kiwipiepy` 사용 (Dockerfile에 설치).
- 차후 멀티 인스턴스 app으로 확장 시 ParadeDB(`pg_search`) 또는 Qdrant sparse vector로 옮길 여지.

---

## 7. Ingest 파이프라인 (batch 컨테이너)

CLI 진입점: `python -m batch.main ingest-blog --since 2025-01-01`

흐름:
1. **Loader**: v1 Postgres export(`mer_blog_posts.json`, `mer_blog_comments.json`)를 읽어 `Document` 생성.
2. **Metadata builder**: title/url/published_at/category/source_type 부여, 본문에서 추가 메타 추출(언급 종목 등 — 옵션).
3. **Node parser**: `SentenceSplitter`(1차) → 향후 `SemanticSplitterNodeParser`로 교체.
4. **Embedding**: LM Studio embedding 호출, 배치 처리.
5. **Dual index**: Qdrant upsert + BM25 corpus append.
6. **Postgres 기록**: `mer_nodes`에 hash/포인트ID 저장.
7. **Verify**: 컬렉션 카운트, 샘플 retrieval 1건 실행하여 헬스 확인.

배치 잡 종류:
- `ingest-blog`, `ingest-comments`, `rebuild-bm25`, `refresh-style-pack`, `snapshot-qdrant`(백업).
- 스케줄: APScheduler in-process, 또는 호스트 cron이 `docker exec mer-batch python -m batch.main ...`.

---

## 8. Query 파이프라인 (app 컨테이너)

라우트: `POST /v1/mer/answer`

```
request → 
  intent_router.classify(query, history)
  ├─ smalltalk         → LLM 직답 (근거 검색 skip)
  ├─ blog_evidence     → query_rewriter → router_retriever
  │                       ├─ vector(QdrantStore mer_blog)
  │                       ├─ bm25(blog)
  │                       └─ fusion → metadata_filter → rerank → postprocess
  ├─ specific_lookup   → SQL Tool (post_id/date/category 파라미터화)
  ├─ internal_db       → SQL Tool (사용자 정의 테이블)
  └─ needs_fresh       → "외부 검색 필요" 응답 + (옵션) 외부 도구 후크

evidence_builder(nodes) → EvidencePack
style_pack_builder(query, intent) → StylePack (댓글 few-shot)
prompt_builder(intent, evidence, style, history) → Prompt
response_synthesizer(prompt) → draft answer
verifier(draft, evidence) → final answer + confidence + citations
trace(write to Postgres traces / trace_steps)
```

### 8.1 응답 스키마
```json
{
  "trace_id": "uuid",
  "conversation_id": "uuid",
  "intent": "blog_evidence",
  "answer": "...",
  "citations": [{"id": "c1", "title": "...", "url": "...", "published_at": "...", "score": 0.83}],
  "confidence": 0.74,
  "verifier": {"entailed": true, "missing_citations": []},
  "latency_ms": 1820,
  "model": "qwen2.5-7b-instruct"
}
```

### 8.2 거절 정책
- 검색 결과 없음 / 모든 노드 score < threshold → "근거를 찾지 못했습니다" 고정 응답 + 사용된 검색어 노출.
- Verifier가 entailment 실패하면 답변 보류 후 재시도(최대 1회), 그래도 실패 시 거절.

---

## 9. API 설계 (app)

| Method | Path | 설명 |
|---|---|---|
| GET  | `/healthz` | infra 의존성 헬스 |
| GET  | `/version` | git sha, 모델 정보 |
| POST | `/v1/mer/chat` | 대화형 (history 유지, conversation_id) |
| POST | `/v1/mer/answer` | 단발성 RAG 답변 |
| POST | `/v1/mer/retrieve` | 디버그용 retrieval만 |
| GET  | `/v1/debug/traces` | 최근 trace 목록 |
| GET  | `/v1/debug/traces/{id}` | step 상세 |
| GET  | `/v1/debug/traces/{id}/report?format=html` | 사람이 보기 좋은 리포트 |
| GET  | `/metrics` | Prometheus exposition |

batch는 HTTP 없이 CLI만. 단, 진행상황은 Postgres `batch_jobs` 테이블에 기록.

---

## 10. 환경 설정

`.env.example` 핵심:
```
# LM Studio (호스트에서 실행, 컨테이너에서 host.docker.internal로 접근)
LMSTUDIO_BASE_URL=http://host.docker.internal:1234/v1
LMSTUDIO_CHAT_MODEL=gemma-4-e4b           # 기본 합성 모델
LMSTUDIO_MODEL_ROUTER=qwen3.5-4b          # intent 분류/라우팅 (빠른 모델)
LMSTUDIO_MODEL_VERIFIER=qwen3.5-9b        # entailment / self-check
LMSTUDIO_EMBED_MODEL=bge-m3               # 임베딩 (1024차원)
LMSTUDIO_CTX=8192
LLM_TIMEOUT_SEC=180

# Postgres
PG_DSN=postgresql+psycopg://mer:mer@postgres:5432/mer

# Qdrant
QDRANT_URL=http://qdrant:6333
QDRANT_API_KEY=

# Redis
REDIS_URL=redis://redis:6379/0

# App
APP_PORT=8000
TRACE_TEXT_LIMIT=1200
ANSWER_SCORE_FLOOR=0.35
RERANK_TOP_K=10
HYBRID_ALPHA=0.5

# Batch
BATCH_DATA_DIR=/data
BATCH_BLOG_EXPORT=/data/import/mer_blog_posts.json
BATCH_COMMENT_EXPORT=/data/import/mer_blog_comments.json
```

설정은 `pydantic-settings`로 한 곳(`shared/config.py`)에서 로딩, app/batch가 공통 사용.

---

## 11. v1 → v2 마이그레이션

1. **export 스크립트**(v1 측에서 실행): 
   - `mer_blog_posts`, `mer_blog_comments` 테이블을 JSON Lines로 dump.
   - 스크립트는 `infra/scripts/export_v1.sh`로 v2 레포에 포함.
2. **v2 인프라 기동**: `compose.infra.yml`만 먼저.
3. **마이그레이션 실행**: `compose.batch.yml` 한 번만 띄워 `python -m batch.main migrate-v1 --from /data/import/`.
4. **인덱스 빌드**: `ingest-blog`, `ingest-comments`, `refresh-style-pack` 순차 실행.
5. **app 기동**: `compose.app.yml` up → `/healthz`/`/v1/mer/answer` 스모크.
6. **검증셋 실행**: `tests/eval/` 셋으로 v1 vs v2 응답 비교(BLEU/citation 일치율 등).

---

## 12. 마일스톤

**M0. 스캐폴딩** (1~2일)
- 폴더 구조, pyproject, pre-commit, Makefile, Dockerfile.app/batch 골격
- `compose.infra.yml` (postgres + qdrant + redis) + `init_db.sh`
- `app/main.py` `/healthz`, `batch/main.py` `--help`

**M1. LM Studio + 단일 채팅** (1일)
- `lmstudio_llm.py` + `llm_router.py`
- `/v1/mer/chat` 단순 echo+LLM (검색 없이 smalltalk만)

**M2. Ingest MVP** (2~3일)
- v1 export 포맷 정의 + sample data
- blog_loader → node_parser → Qdrant + BM25 + Postgres 기록
- 단일 컬렉션부터, idempotent upsert

**M3. Hybrid Retrieval + 답변** (3~4일)
- VectorIndexRetriever, BM25Retriever, QueryFusionRetriever
- Reranker(SentenceTransformer) → Postprocess
- evidence_builder → prompt_builder(기본) → CompactAndRefine
- `/v1/mer/answer` 정상 응답 + citation

**M4. 메르 페르소나 & Style Pack** (2~3일)
- comment ingest, style 컬렉션
- style_pack_builder(주제 매칭 few-shot)
- prompt_builder에 페르소나/스타일 주입

**M5. Intent Router + Verifier** (2~3일)
- intent_router(LLM 분류 + 휴리스틱)
- verifier(LLM self-check + 인용 누락 검사)
- 거절 정책, confidence

**M6. 관측/운영** (1~2일)
- Postgres traces/trace_steps + `/v1/debug/*`
- Prometheus exporter (`/metrics`) + Grafana 기본 대시보드
- batch 잡 진행상황 테이블 + Grafana 패널

**M7. 평가 & 마이그레이션 종료** (2일)
- v1 데이터 풀 마이그레이션
- 평가셋 30~50개 정의, 회귀 테스트
- README/runbook 정리

총 **~3주** 풀타임 기준.

---

## 13. 정의된 완료 기준 (DoD)

- [ ] 새 호스트에서 `make setup-all`로 30분 내 풀스택 기동
- [ ] `compose.app.yml` 단독 배포 가능 (외부 DB/Qdrant 지정)
- [ ] `compose.batch.yml`만으로 ingest 가능
- [ ] LM Studio 모델/엔드포인트만 바꿔서 재시작하면 바로 다른 모델로 운영
- [ ] `/v1/mer/answer`가 citation 포함, verifier 적용된 응답 반환
- [ ] trace UI에서 한 응답의 모든 단계가 시각화됨
- [ ] 평가셋 통과율 v1 대비 동등 이상

---

## 14. 다음 단계 (오늘 바로 할 일)

1. **LM Studio에서 bge-m3 다운로드** (현재 미설치). LM Studio 검색창에 `bge-m3`로 GGUF 모델 찾아 받기.
2. **M0 스캐폴딩 시작**:
   - 루트 폴더 + `pyproject.toml`(uv) + `uv.lock`
   - `app/mer_persona/main.py` (FastAPI, `/healthz`만)
   - `batch/main.py` (typer CLI, `--help`만)
   - `deploy/Dockerfile.app`, `Dockerfile.batch` (uv 기반 멀티스테이지)
   - `deploy/compose.infra.yml` (postgres + qdrant + redis + 영속 볼륨)
   - `infra/migrations/0001_init.sql` (mer_blog_posts, mer_blog_comments, mer_nodes, traces)
3. **v1 export 스크립트** 작성 → `infra/scripts/export_v1.sh` (Postgres dump → JSONL)
4. **LM Studio 모델 4개 확정 로드**: gemma-4-e4b, qwen3.5-4b, qwen3.5-9b, bge-m3
