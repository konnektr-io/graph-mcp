# konnektr_mcp/client_factory.py
"""
Factory for creating Konnektr Graph SDK clients with proper credentials.
This eliminates the need for wrapper methods - just use the SDK directly.
"""

from konnektr_graph.aio import KonnektrGraphClient
from konnektr_graph.auth import StaticTokenCredential
from konnektr_mcp.config import get_settings


def create_client(resource_id: str, access_token: str) -> KonnektrGraphClient:
    """
    Create a KonnektrGraphClient with the appropriate endpoint and credentials.

    Args:
        resource_id: The resource ID for routing to the correct API instance
        access_token: The Bearer token for authentication

    Returns:
        Configured KonnektrGraphClient instance
    """
    settings = get_settings()
    endpoint = settings.api_base_url_template.format(resource_id=resource_id)
    credential = StaticTokenCredential(access_token)

    return KonnektrGraphClient(endpoint=endpoint, credential=credential)
