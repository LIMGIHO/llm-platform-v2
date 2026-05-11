from llama_index.embeddings.openai import OpenAIEmbedding
from llama_index.llms.openai_like import OpenAILike

from app.mer_persona.core.config import Settings


def build_llm(settings: Settings, task: str = "default") -> OpenAILike:
    """task 키로 모델을 라우팅한다. unknown task는 기본 chat model 사용."""
    task_model_map = {
        "router": settings.LMSTUDIO_MODEL_ROUTER,
        "verifier": settings.LMSTUDIO_MODEL_VERIFIER,
    }
    # verifier는 짧은 입력 + 짧은 출력이므로 별도 단축 timeout 적용
    # Channel Error 시 무한 hang 방지
    task_timeout_map = {
        "verifier": 60,
        "router": 30,
    }
    model = task_model_map.get(task, settings.LMSTUDIO_CHAT_MODEL)
    timeout = task_timeout_map.get(task, settings.LLM_TIMEOUT_SEC)
    return OpenAILike(
        model=model,
        api_base=settings.LMSTUDIO_BASE_URL,
        api_key="lm-studio",
        is_chat_model=True,
        temperature=0.2,
        timeout=timeout,
        context_window=settings.LMSTUDIO_CTX,
    )


def build_embed_model(settings: Settings) -> OpenAIEmbedding:
    return OpenAIEmbedding(
        model_name=settings.LMSTUDIO_EMBED_MODEL,
        api_base=settings.LMSTUDIO_BASE_URL,
        api_key="lm-studio",
        embed_batch_size=32,
    )
