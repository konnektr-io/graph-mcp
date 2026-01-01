# konnektr_mcp/config.py
from pydantic_settings import BaseSettings
from functools import lru_cache


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

    class Config:
        env_file = ".env"


@lru_cache
def get_settings() -> Settings:
    return Settings()
