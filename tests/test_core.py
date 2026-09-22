from app.core.config import settings
from app.core.logging import get_logger, setup_logging


def test_settings_have_working_defaults():
    assert settings.database_url.startswith("postgresql://")
    assert ":" in settings.temporal_host
    assert settings.llm_base_url.startswith("http")
    assert settings.embed_dim > 0
    assert 0.0 < settings.retrieval_threshold < 1.0


def test_setup_logging_is_idempotent():
    setup_logging()
    setup_logging()
    get_logger("smoke").info("smoke_ok")
