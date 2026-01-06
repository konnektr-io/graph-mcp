# konnektr_mcp/config.py
from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import Optional


class Settings(BaseSettings):
    # Auth0 Configuration
    auth0_domain: str = ""
    auth0_client_id: str = ""  # Required for token exchange
    auth0_client_secret: str = ""  # Required for token exchange
    auth0_audience: str = "https://graph.konnektr.io"  # Graph API audience
    auth_enabled: bool = True

    # API Configuration
    api_base_url_template: str = "https://{resource_id}.api.graph.konnektr.io"
    api_timeout_seconds: int = 30

    # MCP Server
    mcp_resource_url: str = "https://mcp.graph.konnektr.io"

    # Embedding Configuration
    # Provider: "openai", "azure_openai", or "gemini"
    embedding_provider: str = "openai"
    embedding_enabled: bool = True

    # OpenAI settings
    openai_api_key: Optional[str] = None
    openai_embedding_model: str = "text-embedding-3-small"
    openai_base_url: Optional[str] = None  # For OpenAI-compatible endpoints

    # Azure OpenAI settings
    azure_openai_api_key: Optional[str] = None
    azure_openai_endpoint: Optional[str] = None
    azure_openai_deployment_name: Optional[str] = None
    azure_openai_api_version: str = "2024-02-01"

    # Google Gemini settings
    google_api_key: Optional[str] = None
    google_embedding_model: str = "gemini-embedding-001"

    # Fixed embedding dimension (used across all providers)
    embedding_dimensions: int = 1024

    class Config:
        env_file = ".env"


@lru_cache
def get_settings() -> Settings:
    return Settings()
