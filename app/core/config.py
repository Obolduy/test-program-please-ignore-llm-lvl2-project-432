from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_base_url: str = "http://localhost:1234/v1"
    llm_api_key: str = "local"
    llm_model: str = "qwen2.5-7b-instruct"
    llm_model_cheap: str = "qwen2.5-3b-instruct"
    llm_timeout_s: float = 120.0
    llm_max_retries: int = 3

    database_url: str = "postgresql://card:card@localhost:5433/card"
    db_pool_min: int = 1
    db_pool_max: int = 10

    temporal_host: str = "localhost:7233"
    temporal_task_queue: str = "card-queue"
    temporal_activity_threads: int = 4

    embed_model: str = "intfloat/multilingual-e5-base"
    embed_dim: int = 768
    embed_device: str = "cpu"

    retrieval_top_k: int = 5
    retrieval_threshold: float = 0.81

    confidence_threshold: float = 0.5
    card_fix_attempts: int = 2

    suspicious_chunk_limit: int = 2

    llm_prices: dict[str, dict[str, float]] = {"default": {"input": 0.0, "output": 0.0}}


settings = Settings()
