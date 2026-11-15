import os
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://agentsocial:agentsocial_secret@localhost:5432/agentsocial"
    REDIS_URL: str = "redis://localhost:6379/0"
    PUBLIC_API_URL: Optional[str] = None
    JWT_SECRET: str = "change_me_in_production_supersecret"
    JWT_ALGORITHM: str = "HS256"
    REPLY_TOKEN_EXPIRY_MINUTES: int = 60
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    OPENAI_MODEL: str = "gpt-4o-mini"
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    USE_OLLAMA: bool = False
    CORS_ORIGINS: str = "http://localhost:3000"
    LOG_LEVEL: str = "INFO"

    model_config = {"env_file": ".env", "extra": "ignore"}

    @property
    def public_api_url(self) -> str:
        return (
            self.PUBLIC_API_URL
            or os.getenv("RENDER_EXTERNAL_URL")
            or "http://localhost:8000"
        ).rstrip("/")


settings = Settings()
