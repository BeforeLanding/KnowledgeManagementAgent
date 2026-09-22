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
    web_origin: str = "http://localhost:3000"
    max_file_mb: int = 25
    max_email_mb: int = 50
    chunk_tokens: int = 700
    chunk_overlap: int = 100
    trace_redaction: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
