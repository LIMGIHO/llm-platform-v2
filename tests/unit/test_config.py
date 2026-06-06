from app.mer_persona.core.config import Settings


def test_settings_defaults():
    s = Settings(
        _env_file=None,  # 파일 없이 기본값만 테스트
        LMSTUDIO_BASE_URL="http://localhost:1234/v1",
        PG_DSN="postgresql+psycopg://mer:mer@localhost:5432/mer",
    )
    assert s.LMSTUDIO_EMBED_MODEL == "text-embedding-bge-m3"
    assert s.HYBRID_ALPHA == 0.5


def test_search_settings_defaults():
    s = Settings(
        _env_file=None,
        LMSTUDIO_BASE_URL="http://localhost:1234/v1",
        PG_DSN="postgresql+psycopg://mer:mer@localhost:5432/mer",
    )
    assert s.SEARCH_MAX_STEPS == 3
    assert s.SEARCH_TOOL_TIMEOUT_SEC == 10
    assert s.SEARCH_FILE_ROOT == "."
    assert s.SEARCH_FILE_TOP_K == 10
    assert s.SEARCH_WEB_PROVIDER == "disabled"
    assert s.SEARCH_MARKET_PROVIDER == "disabled"
