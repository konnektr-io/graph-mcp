# konnektr_mcp/server.py
import contextlib
import contextvars
import logging
import base64
import json
from dataclasses import dataclass
from urllib.parse import parse_qs
from typing import Optional

from pydantic import AnyHttpUrl
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.routing import Mount, Route
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from fastmcp import FastMCP
from fastmcp.server.auth import OIDCProxy
from fastmcp.server.dependencies import get_access_token

from konnektr_graph.aio import KonnektrGraphClient
from konnektr_graph.types import (
    BasicDigitalTwin,
    BasicRelationship,
    DtdlInterface,
    JsonPatchOperation,
)

from konnektr_mcp.config import get_settings
from konnektr_mcp.client_factory import create_client
from konnektr_mcp.tools import register_tools

logger = logging.getLogger(__name__)

# Configure logging for debugging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)


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
    """

    HEADER_NAME = b"x-resource-id"
    QUERY_PARAM = "resource_id"

    def __init__(self, app: ASGIApp, auth_provider: Optional[OIDCProxy] = None):
        self.app = app
        self.auth_provider = auth_provider

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
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
        if settings.auth_enabled:
            # The FastMCP OAuth proxy stores the upstream token after validating the FastMCP JWT
            token_result = await self._extract_upstream_token(scope)
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

    async def _extract_upstream_token(self, scope: Scope) -> str | None:
        """Extract upstream Auth0 token from authenticated user context.

        The OAuth proxy stores upstream tokens separately from the FastMCP JWTs.
        This middleware runs BEFORE FastMCP's auth middleware, so we need to:
        1. Extract the FastMCP JWT from the Authorization header
        2. Call the auth provider's load_access_token() to do the token swap
        3. Return the upstream Auth0 token
        """
        try:
            # Extract Bearer token from Authorization header
            headers = dict(scope.get("headers", []))
            auth_header = headers.get(b"authorization", b"").decode()

            if not auth_header:
                logger.warning("No Authorization header found in request")
                return None

            # Extract token from "Bearer <token>" format
            if not auth_header.startswith("Bearer "):
                logger.warning("Authorization header does not use Bearer scheme")
                return None

            fastmcp_jwt = auth_header[7:]  # Remove "Bearer " prefix
            if not fastmcp_jwt:
                logger.warning("Authorization header present but token is empty")
                return None

            logger.debug(
                f"Extracted FastMCP JWT from Authorization header (length: {len(fastmcp_jwt)})"
            )

            # Use the auth provider to swap the FastMCP JWT for the upstream token
            # The load_access_token method looks up the JTI mapping and returns
            # an AccessToken with the validated upstream token
            if self.auth_provider is None:
                logger.warning("No auth provider configured for token swap")
                return None

            validated_token = await self.auth_provider.load_access_token(fastmcp_jwt)
            if validated_token is None:
                logger.warning("Failed to swap FastMCP JWT for upstream token")
                return None

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

        except Exception as e:
            logger.error(f"Error retrieving upstream token: {e}", exc_info=True)
            return None


settings = get_settings()

# Use FastMCP's OIDC proxy for Auth0 with shared audience
# Token has audience: https://graph.konnektr.io (same as API)
# Auth0 requires audience in both authorize and token requests to issue JWTs
auth = (
    OIDCProxy(
        config_url=f"https://{settings.auth0_domain}/.well-known/openid-configuration",
        base_url=settings.mcp_resource_url,
        client_id=settings.auth0_client_id,
        client_secret=settings.auth0_client_secret,
        audience=settings.auth0_audience,
        required_scopes=["openid"],
        # Auth0 requires audience parameter to issue JWT tokens
        extra_authorize_params={"audience": settings.auth0_audience},
        extra_token_params={"audience": settings.auth0_audience},
    )
    if settings.auth_enabled
    else None
)

mcp = FastMCP(
    name="Konnektr Graph",
    instructions="""Semantic Knowledge Graph Memory System for AI Agents.

This system provides validated, schema-enforced memory storage using Digital Twins Definition Language (DTDL).
All data must conform to DTDL models - the system will reject invalid structures with detailed error messages.

## Key Capabilities:
- **Semantic Memory**: Vector embeddings for similarity search
- **Graph Relationships**: Connect related concepts and entities
- **Schema Validation**: DTDL ensures data quality and consistency
- **Hybrid Search**: Combine vector similarity with metadata filtering

## Workflow:
1. **Explore Models**: Use `list_models` or `search_models` to understand available schemas
2. **Get Model Details**: Use `get_model` to see full schema including properties and relationships
3. **Create Twins**: Store validated data as digital twins conforming to models
4. **Build Graph**: Connect twins using relationships defined in the models
5. **Search & Query**: Find information using semantic search or graph queries

The system will provide detailed validation errors if you try to create twins or relationships that don't match the schema.""",
    stateless_http=True,
    json_response=True,
    auth=(auth if settings.auth_enabled else None),
)

register_tools(mcp)

# ========== Starlette App ==========


# Liveness probe: Check if application is alive (doesn't hang)
async def liveness(request: Request):
    """
    Kubernetes liveness probe endpoint.
    Returns 200 if the application process is running.
    If this fails, Kubernetes will restart the pod.
    """
    return JSONResponse({"status": "alive", "version": "0.1.0"})


# Readiness probe: Check if application can serve traffic
async def readiness(request: Request):
    """
    Kubernetes readiness probe endpoint.
    Returns 200 if the application is ready to accept requests.
    If this fails, Kubernetes won't send traffic to this pod.
    """
    try:
        # Check settings are loaded
        settings = get_settings()
        if not settings:
            return JSONResponse(
                {"status": "not_ready", "reason": "Configuration not loaded"},
                status_code=503,
            )

        # All checks passed
        return JSONResponse(
            {
                "status": "ready",
                "version": "0.1.0",
                "auth_enabled": settings.auth_enabled,
            }
        )

    except Exception as e:
        return JSONResponse({"status": "not_ready", "reason": str(e)}, status_code=503)


# Legacy health endpoint (kept for backward compatibility)
async def health(request: Request):
    """Legacy health check - redirects to readiness probe logic"""
    return await readiness(request)


# Build the Starlette app
# Middleware needs to run in the request context where auth is available

mcp_app = mcp.http_app()

# Always wrap mcp_app with CustomMiddleware (needed for routing to correct backend)
# Pass the auth provider so middleware can perform token swaps when auth is enabled
wrapped_mcp_app = CustomMiddleware(mcp_app, auth_provider=auth)

base_app = Starlette(
    routes=[
        Route("/health", health),  # Legacy, uses readiness logic
        Route("/healthz", liveness),  # Kubernetes liveness probe
        Route("/readyz", readiness),  # Kubernetes readiness probe
        Route("/ready", readiness),  # Alternative readiness endpoint
        Mount("/", app=wrapped_mcp_app),
    ],
    lifespan=mcp_app.lifespan,
)

# Wrap with CORS middleware
app = CORSMiddleware(
    base_app,
    allow_origins=["*"],  # Configure appropriately for production
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*", "X-Resource-Id"],  # Allow custom header
    expose_headers=["Mcp-Session-Id"],
)


# Run with: uvicorn konnektr_mcp.server:app --host 0.0.0.0 --port 8080
