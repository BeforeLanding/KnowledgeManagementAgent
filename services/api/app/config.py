from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    database_url: str = "sqlite:///./kma.db"
    redis_url: str = "redis://localhost:6379/0"
    qdrant_url: str = "http://localhost:6333"
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "kma-local"
    minio_secret_key: str = "change-me-local-only"
    minio_bucket: str = "knowledge-documents"
    minio_secure: bool = False
    jwt_secret: str = Field(default="development-secret-change-this-32-chars")
    access_token_minutes: int = 15
    refresh_token_days: int = 7
    model_provider: str = "fake"
    openai_base_url: str = "https://api.openai.com/v1"
    openai_api_key: str = ""
    chat_model: str = ""
    embedding_model: str = ""
    provider_connect_timeout_seconds: float = 5.0
    provider_read_timeout_seconds: float = 60.0
    provider_write_timeout_seconds: float = 10.0
    provider_pool_timeout_seconds: float = 5.0
    provider_max_attempts: int = Field(default=3, ge=1, le=5)
    provider_retry_backoff_seconds: float = Field(default=0.25, ge=0)
    agent_max_tool_calls: int = Field(default=4, ge=1, le=4)
    agent_max_citations: int = Field(default=6, ge=1, le=20)
    agent_context_words: int = Field(default=6000, ge=100, le=20000)
    web_origin: str = "http://localhost:3000"
    max_file_mb: int = 25
    max_email_mb: int = 50
    chunk_tokens: int = 700
    chunk_overlap: int = 100
    trace_redaction: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
