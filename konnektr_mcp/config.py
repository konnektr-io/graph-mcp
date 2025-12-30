# konnektr_mcp/config.py
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Auth0
    auth0_domain: str = ""
    auth0_audience: str = "https://graph.konnektr.io"
    auth0_issuer: str = ""  # Will be derived from domain if empty
    auth_enabled: bool = True

    # API Proxy
    api_base_url_template: str = "https://{resource_id}.api.graph.konnektr.io"
    api_timeout_seconds: int = 30

    # MCP Server
    mcp_resource_url: str = "https://mcp.graph.konnektr.io"

    class Config:
        env_file = ".env"

    @property
    def issuer_url(self) -> str:
        return self.auth0_issuer or f"https://{self.auth0_domain}/"


@lru_cache
def get_settings() -> Settings:
    return Settings()
