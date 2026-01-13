"""Configuration from environment variables."""
import os
from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment."""

    # Elasticsearch
    elasticsearch_url: str = os.getenv("ES_URL", "http://localhost:9200")
    elasticsearch_api_key: str = os.getenv("ES_API_KEY", "")
    elasticsearch_index: str = os.getenv("ES_INDEX", "police-incidents")

    # LLM - RedHat Granite via Elasticsearch Inference API
    llm_inference_id: str = os.getenv("LLM_INFERENCE_ID", "redhat-granite")

    # Alternative: Direct LLM connection (OpenAI-compatible)
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_api_base: str = os.getenv("LLM_API_BASE", "")
    llm_model: str = os.getenv("LLM_MODEL", "granite-3-3-8b-instruct")

    # App settings
    app_title: str = "Police Incident Search API"
    app_version: str = "1.0.0"
    debug: bool = os.getenv("DEBUG", "false").lower() == "true"

    # Feature flags
    llm_enabled: bool = os.getenv("LLM_ENABLED", "false").lower() == "true"
    chat_enabled: bool = os.getenv("CHAT_ENABLED", "false").lower() == "true"

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
