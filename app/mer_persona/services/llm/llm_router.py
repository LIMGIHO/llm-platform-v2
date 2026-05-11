"""LLM 백엔드 추상화 — M1에서 구현."""
from app.mer_persona.core.config import Settings
from app.shared.llm.lmstudio import build_embed_model, build_llm


def get_llm(settings: Settings, task: str = "default"):
    return build_llm(settings, task)


def get_embed_model(settings: Settings):
    return build_embed_model(settings)
