from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # LM Studio
    LMSTUDIO_BASE_URL: str = "http://host.docker.internal:1234/v1"
    LMSTUDIO_CHAT_MODEL: str = "google/gemma-4-e4b"
    LMSTUDIO_MODEL_ROUTER: str = "qwen3.5-4b-claude-4.6-opus-reasoning-distilled"
    LMSTUDIO_MODEL_VERIFIER: str = "qwen/qwen3.5-9b"
    LMSTUDIO_EMBED_MODEL: str = "text-embedding-bge-m3"
    LMSTUDIO_CTX: int = 8192
    LLM_TIMEOUT_SEC: int = 180

    # Postgres
    PG_DSN: str = "postgresql+psycopg://llm-platform:1234@postgres:5432/llm-platform"

    # Qdrant
    QDRANT_URL: str = "http://qdrant:6333"
    QDRANT_API_KEY: str = ""

    # Redis
    REDIS_URL: str = "redis://redis:6379/0"

    # App behaviour
    APP_PORT: int = 8000
    TRACE_TEXT_LIMIT: int = 1200
    ANSWER_SCORE_FLOOR: float = 0.35
    RERANK_TOP_K: int = 10
    HYBRID_ALPHA: float = 0.5
    RERANKER_MODEL: str = "BAAI/bge-reranker-v2-m3"
    STYLE_TOP_K: int = 3         # few-shot 예시 수

    # Style pack (batch ingest)
    STYLE_AUTHOR: str = ""       # 이 작성자 댓글만 스타일용으로 사용. 빈 값=전체
    STYLE_MIN_LEN: int = 50      # 최소 댓글 길이 (chars) — 질문(타인 댓글) 기준
    STYLE_MAX_LEN: int = 600     # 최대 댓글 길이
    STYLE_GOLD_MIN_LEN: int = 80 # Gold(메르 대댓글) 최소 길이 — 인사성 짧은 답변 제외

    # Batch
    BATCH_DATA_DIR: str = "/data"
    BATCH_BLOG_EXPORT: str = "/data/import/mer_blog_posts.json"
    BATCH_COMMENT_EXPORT: str = "/data/import/mer_blog_comments.json"

    # Naver scraper
    NAVER_BLOG_ID: str = "ranto28"
    NAVER_BLOG_NO: str = "35863879"
    NAVER_POLL_INTERVAL_SEC: int = 900
    NAVER_COMMENT_CV: str = "20260303192025"
    NAVER_COMMENT_PAGE_SIZE: int = 100
    NAVER_USER_AGENT: str = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

    # Build info (injected by Docker)
    GIT_SHA: str = "local"
    BUILD_TIME: str = "unknown"


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
