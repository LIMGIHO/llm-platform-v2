from app.mer_persona.core.config import Settings


def test_settings_defaults():
    s = Settings(
        _env_file=None,  # 파일 없이 기본값만 테스트
        LMSTUDIO_BASE_URL="http://localhost:1234/v1",
        PG_DSN="postgresql+psycopg://mer:mer@localhost:5432/mer",
    )
    assert s.LMSTUDIO_EMBED_MODEL == "bge-m3"
    assert s.HYBRID_ALPHA == 0.5
