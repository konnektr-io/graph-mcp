"""
Middleware for request context and authentication.

Handles resource_id extraction and upstream token extraction for the Konnektr MCP server.
"""

import contextvars
import logging
from dataclasses import dataclass
from typing import Optional
from urllib.parse import parse_qs
from fastmcp.server.auth import OIDCProxy
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from konnektr_graph.aio import KonnektrGraphClient

from konnektr_mcp.client_factory import create_client

logger = logging.getLogger(__name__)


# ========== Request Context ==========


@dataclass
class RequestContext:
    """Per-request context containing resource_id and SDK client."""

    resource_id: str
    access_token: str
    client: KonnektrGraphClient


# Context variable for per-request state
_request_context: contextvars.ContextVar[RequestContext | None] = (
    contextvars.ContextVar("request_context", default=None)
)


def get_current_context() -> RequestContext:
    """Get the current request context. Raises if not set."""
    ctx = _request_context.get()
    if ctx is None:
        raise RuntimeError(
            "No request context available. "
            "Ensure resource_id is provided via query param (?resource_id=xyz) "
            "or header (X-Resource-Id: xyz)"
        )
    return ctx


def get_client() -> KonnektrGraphClient:
    """Get the SDK client from current context."""
    return get_current_context().client


# ========== Middleware ==========


class CustomMiddleware:
    """
    Middleware that extracts resource_id from query param OR header.

    Supports:
    - Query param: ?resource_id=xyz
    - Header: X-Resource-Id: xyz

    Priority: Query param > Header

    Also handles upstream token extraction for authenticated requests.
    For client credentials flow, the token is the Auth0 token itself.
    For PKCE flow, the token needs to be swapped via the OIDCProxy.
    """

    HEADER_NAME = b"x-resource-id"
    QUERY_PARAM = "resource_id"

    def __init__(self, app: ASGIApp, auth_provider: Optional[OIDCProxy] = None):
        """
        Initialize the middleware.

        Args:
            app: The ASGI application to wrap
            auth_enabled: Whether authentication is enabled
        """
        self.app = app
        self.auth = auth_provider

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        """Handle incoming HTTP request."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")

        # Only apply to MCP endpoints
        if not path.startswith("/mcp"):
            await self.app(scope, receive, send)
            return

        # Extract resource_id from query param or header
        resource_id = self._extract_resource_id(scope)

        if not resource_id:
            # Return error if resource_id is missing
            response = JSONResponse(
                {
                    "error": "missing_resource_id",
                    "message": "resource_id is required. Provide via query param (?resource_id=xyz) or header (X-Resource-Id: xyz)",
                },
                status_code=400,
            )
            await response(scope, receive, send)
            return

        # Extract upstream Auth0 token from authenticated user context if auth is enabled
        # For unauthenticated backends (like demo), we'll use an empty token
        access_token: str = ""
        if self.auth is not None:
            # Extract the token validated by FastMCP auth from the Authorization header
            token_result = await self._extract_token_from_header(scope)
            if not token_result:
                response = JSONResponse(
                    {
                        "error": "authentication_required",
                        "message": "Valid authentication token required",
                    },
                    status_code=401,
                )
                await response(scope, receive, send)
                return
            access_token = token_result

        # Create SDK client for this request
        client = create_client(resource_id, access_token)
        request_ctx = RequestContext(
            resource_id=resource_id,
            access_token=access_token,
            client=client,
        )

        # Set context and process request
        token = _request_context.set(request_ctx)
        try:
            await self.app(scope, receive, send)
        finally:
            _request_context.reset(token)
            await client.close()

    def _extract_resource_id(self, scope: Scope) -> str | None:
        """Extract resource_id from query param or header."""
        # Try query param first
        query_string = scope.get("query_string", b"").decode()
        if query_string:
            params = parse_qs(query_string)
            resource_ids = params.get(self.QUERY_PARAM, [])
            if resource_ids:
                return resource_ids[0]

        # Fall back to header
        headers = dict(scope.get("headers", []))
        header_value = headers.get(self.HEADER_NAME, b"").decode()
        if header_value:
            return header_value

        return None

    async def _extract_token_from_header(self, scope: Scope) -> str | None:
        """
        Extract the access token from the Authorization header.

        After FastMCP auth validation:
        - For client credentials flow: The token is the raw Auth0 token
        - For PKCE flow: The token is a FastMCP JWT that maps to an upstream Auth0 token

        Note: Token swapping for PKCE flow happens at the application level in server.py
        via the middleware's integration with OIDCProxy.

        Returns:
            The token string if present, None otherwise
        """
        try:
            headers = dict(scope.get("headers", []))
            auth_header = headers.get(b"authorization", b"").decode()

            if not auth_header:
                logger.warning("No Authorization header found in request")
                return None

            if not auth_header.startswith("Bearer "):
                logger.warning("Authorization header does not use Bearer scheme")
                return None

            token = auth_header[7:]  # Remove "Bearer " prefix
            if not token:
                logger.warning("Authorization header present but token is empty")
                return None

            # Use the auth provider to swap the FastMCP JWT for the upstream token
            # The load_access_token method looks up the JTI mapping and returns
            # an AccessToken with the validated upstream token
            if self.auth is None:
                logger.warning("No auth provider configured for token swap")
                return None

            validated_token = await self.auth.load_access_token(token)
            if validated_token is not None:
                # The validated token's .token attribute now contains the upstream Auth0 token
                upstream_token = validated_token.token
                if upstream_token:
                    logger.debug(
                        f"Successfully retrieved upstream token via token swap (length: {len(upstream_token)})"
                    )
                    return upstream_token
                else:
                    logger.warning(
                        "Validated token found but upstream token field is empty"
                    )
                    return None

            logger.debug(
                f"Extracted token from Authorization header (length: {len(token)})"
            )
            return token

        except Exception as e:
            logger.error(f"Error extracting token from header: {e}", exc_info=True)
            return None
