from contextlib import asynccontextmanager

from fastapi import FastAPI
from llama_index.core import Settings as LISettings
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.responses import Response

from app.mer_persona.core.config import get_settings
from app.mer_persona.core.logging import configure_logging, get_logger
from app.shared.cache.redis_client import close_redis
from app.shared.llm.lmstudio import build_embed_model, build_llm

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging()

    # LlamaIndex 전역 설정 — VectorIndexRetriever 등이 자동으로 사용
    LISettings.llm = build_llm(settings)
    LISettings.embed_model = build_embed_model(settings)

    # Semantic Router warm-up — 첫 요청 전에 utterance 임베딩을 미리 완료
    from app.mer_persona.services.mer.intent_router import _build_route_matrix
    import app.mer_persona.services.mer.intent_router as _ir
    try:
        _ir._route_matrix = await _build_route_matrix()
        logger.info("startup.semantic_router", status="ready")
    except Exception as exc:
        logger.warning("startup.semantic_router", status="failed", error=str(exc))

    # CrossEncoder 리랭커 pre-load — 첫 요청 지연 방지
    from app.mer_persona.services.retrieval import reranker as _reranker
    try:
        loop = __import__("asyncio").get_event_loop()
        await loop.run_in_executor(
            None, _reranker._load_model, settings.RERANKER_MODEL
        )
    except Exception as exc:
        logger.warning("startup.reranker", status="failed", error=str(exc))

    logger.info("startup", base_url=settings.LMSTUDIO_BASE_URL, git_sha=settings.GIT_SHA)
    yield
    await close_redis()
    logger.info("shutdown")


app = FastAPI(title="llm-platform-v2 (mer)", version="0.1.0", lifespan=lifespan)

# ── routers ───────────────────────────────────────────────────────────────
from app.mer_persona.routers import chat_ui, mer_answer, mer_chat  # noqa: E402

app.include_router(chat_ui.router)
app.include_router(mer_chat.router, prefix="/v1/mer")
app.include_router(mer_answer.router, prefix="/v1/mer")

from app.mer_persona.routers import debug, ops  # noqa: E402
app.include_router(debug.router, prefix="/v1/debug")
app.include_router(ops.router, prefix="/ops")


# ── ops endpoints ─────────────────────────────────────────────────────────
@app.get("/healthz", tags=["ops"])
async def healthz():
    return {"status": "ok"}


@app.get("/version", tags=["ops"])
async def version():
    s = get_settings()
    return {
        "git_sha": s.GIT_SHA,
        "build_time": s.BUILD_TIME,
        "chat_model": s.LMSTUDIO_CHAT_MODEL,
    }


@app.get("/metrics", tags=["ops"], include_in_schema=False)
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
