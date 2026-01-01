# konnektr_mcp/server.py
import contextlib
import contextvars
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
from fastmcp.server.auth.providers.auth0 import Auth0Provider

from konnektr_graph.aio import KonnektrGraphClient

from konnektr_mcp.config import get_settings
from konnektr_mcp.client_factory import create_client


# ========== Request Context ==========

@dataclass
class RequestContext:
    """Per-request context containing resource_id and SDK client."""

    resource_id: str
    access_token: str
    client: KonnektrGraphClient


# Context variable for per-request state
_request_context: contextvars.ContextVar[RequestContext | None] = contextvars.ContextVar(
    "request_context", default=None
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


# ========== Resource ID Middleware ==========


class ResourceIdMiddleware:
    """
    Middleware that extracts resource_id from query param OR header.

    Supports:
    - Query param: ?resource_id=xyz
    - Header: X-Resource-Id: xyz

    Priority: Query param > Header
    """

    HEADER_NAME = b"x-resource-id"
    QUERY_PARAM = "resource_id"

    def __init__(self, app: ASGIApp):
        self.app = app

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

        # Extract access token from Authorization header
        access_token = self._extract_token(scope)

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

    def _extract_token(self, scope: Scope) -> str:
        """Extract Bearer token from Authorization header."""
        headers = dict(scope.get("headers", []))
        auth_header = headers.get(b"authorization", b"").decode()
        if auth_header.lower().startswith("bearer "):
            return auth_header[7:]
        return ""


# ========== FastMCP Server ==========

settings = get_settings()

# Use FastMCP's built-in Auth0 provider with shared audience
# Token has audience: https://graph.konnektr.io (same as API)
# This is the "shared audience" strategy - simple and works well
auth = (
    Auth0Provider(
        config_url=f"https://{settings.auth0_domain}/.well-known/openid-configuration",
        base_url=settings.mcp_resource_url,
        client_id=settings.auth0_client_id,
        client_secret=settings.auth0_client_secret,
        audience=settings.auth0_audience,
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


# ========== Model Tools ==========


@mcp.tool()
async def list_models(dependencies_for: list[str] | None = None) -> list[dict]:
    """
    List all DTDL models in the graph (summary only). Use get_model for full details.

    This returns a lightweight list of model IDs and display names to help you discover
    available schemas without consuming too many tokens.

    Args:
        dependencies_for: Optional list of model IDs to filter by dependencies

    Returns:
        List of model summaries with IDs and display names
    """
    client = get_client()
    models = []
    async for model in client.list_models(
        dependencies_for=dependencies_for, include_model_definition=False
    ):
        model_dict = model.__dict__ if hasattr(model, "__dict__") else model
        models.append(
            {
                "id": model_dict.get("id"),
                "displayName": (
                    model_dict.get("language_display_names", {}).get("en")
                    or list(model_dict.get("language_display_names", {}).values())[0]
                    if model_dict.get("language_display_names")
                    else None
                ),
            }
        )
    return models


@mcp.tool()
async def get_model(model_id: str) -> dict:
    """
    Get the complete DTDL model definition including all properties, relationships, and components.

    Use this to understand what properties are required/optional and what relationships are allowed
    before creating digital twins.

    Args:
        model_id: The DTMI (e.g., 'dtmi:example:Room;1')

    Returns:
        Full model definition with flattened inherited properties
    """
    client = get_client()
    model = await client.get_model(model_id, include_model_definition=True)
    return model.model.__dict__


@mcp.tool()
async def create_models(models: list[dict]) -> str:
    """
    Create one or more DTDL models. Models must be valid DTDL v3.

    The system validates DTDL syntax and will return detailed error messages if the schema is invalid.

    Args:
        models: Array of DTDL model definitions

    Returns:
        Success message with count of created models
    """
    client = get_client()
    created_models = await client.create_models(models)
    return f"Successfully created {len(created_models)} models."


@mcp.tool()
async def search_models(
    search_text: Optional[str] = None, limit: int = 10
) -> list[dict]:
    """
    Search for DTDL models using semantic search and keyword matching.

    Searches across model IDs, display names, and descriptions to help you find relevant schemas.

    Args:
        search_text: Search query (searches display name, description, ID)
        limit: Maximum number of results

    Returns:
        Matching models with IDs, display names, and descriptions
    """
    client = get_client()
    try:
        results = await client.search_models(search_text or "", limit)
        # Return simplified results
        return [
            {
                "id": m.get("id"),
                "displayName": m.get("displayName"),
                "description": m.get("description"),
            }
            for m in results
        ]
    except Exception as e:
        return [{"error": f"Search failed: {str(e)}"}]


# ========== Digital Twin Tools ==========


@mcp.tool()
async def get_digital_twin(twin_id: str) -> dict:
    """
    Get a digital twin by its ID.

    Args:
        twin_id: The unique ID of the digital twin

    Returns:
        Twin data including all properties and metadata
    """
    client = get_client()
    return await client.get_digital_twin(twin_id)


@mcp.tool()
async def create_or_replace_digital_twin(twin_id: str, twin: dict) -> dict:
    """
    Create a new digital twin or replace an existing one.

    The twin must conform to its DTDL model. The system will validate:
    - All required properties are present
    - Property types match the schema
    - No extra properties beyond the model definition

    Args:
        twin_id: Unique ID for the twin
        twin: Twin data including $metadata with $model property

    Returns:
        Created/updated twin data

    Example:
        {
            "$metadata": {"$model": "dtmi:example:Room;1"},
            "temperature": 72.5,
            "humidity": 45
        }
    """
    client = get_client()
    return await client.upsert_digital_twin(twin_id, twin)


@mcp.tool()
async def update_digital_twin(twin_id: str, patch: list[dict]) -> dict:
    """
    Update a digital twin using JSON Patch operations (RFC 6902).

    Args:
        twin_id: ID of the twin to update
        patch: JSON Patch operations, e.g., [{"op": "replace", "path": "/temperature", "value": 75}]

    Returns:
        Success confirmation
    """
    client = get_client()
    await client.update_digital_twin(twin_id, patch)
    return {"success": True, "message": f"Twin '{twin_id}' updated successfully"}


@mcp.tool()
async def delete_digital_twin(twin_id: str) -> dict:
    """
    Delete a digital twin. All relationships must be deleted first.

    Args:
        twin_id: ID of the twin to delete

    Returns:
        Success confirmation
    """
    client = get_client()
    await client.delete_digital_twin(twin_id)
    return {"success": True, "message": f"Twin '{twin_id}' deleted successfully"}


@mcp.tool()
async def search_digital_twins(
    search_text: str, model_id: str | None = None, limit: int = 10
) -> list[dict]:
    """
    Search for digital twins using semantic search and keyword matching.

    Use this for memory retrieval based on concepts and meanings, not just exact matches.

    Args:
        search_text: Search query (semantic + keyword)
        model_id: Optional filter by model ID
        limit: Maximum results

    Returns:
        Matching twins with all their properties
    """
    client = get_client()
    try:
        return await client.search_twins(search_text, model_id, limit)
    except Exception as e:
        return [{"error": f"Search failed: {str(e)}"}]


# ========== Relationship Tools ==========


@mcp.tool()
async def list_relationships(
    twin_id: str, relationship_name: str | None = None
) -> list[dict]:
    """
    List all outgoing relationships from a digital twin.

    Args:
        twin_id: Source twin ID
        relationship_name: Optional filter by relationship name

    Returns:
        List of relationships
    """
    client = get_client()
    relationships = []
    async for rel in client.list_relationships(twin_id, relationship_name):
        relationships.append(rel)
    return relationships


@mcp.tool()
async def get_relationship(twin_id: str, relationship_id: str) -> dict:
    """
    Get a specific relationship by ID.

    Args:
        twin_id: Source twin ID
        relationship_id: The relationship ID

    Returns:
        Relationship data
    """
    client = get_client()
    return await client.get_relationship(twin_id, relationship_id)


@mcp.tool()
async def create_or_replace_relationship(
    source_twin_id: str, relationship_id: str, relationship: dict
) -> dict:
    """
    Create a relationship between two digital twins.

    Relationships must be defined in the source twin's DTDL model. The system validates:
    - The relationship type is allowed by the model
    - The target twin's model is compatible
    - Required relationship properties are present

    Args:
        source_twin_id: Source twin ID
        relationship_id: Unique ID for this relationship
        relationship: Data with $relationshipName and $targetId

    Returns:
        Created relationship

    Example:
        {
            "$relationshipName": "contains",
            "$targetId": "room-101",
            "since": "2024-01-01"
        }
    """
    client = get_client()
    return await client.upsert_relationship(source_twin_id, relationship_id, relationship)


@mcp.tool()
async def update_relationship(
    twin_id: str, relationship_id: str, patch: list[dict]
) -> dict:
    """
    Update a relationship using JSON Patch operations.

    Args:
        twin_id: Source twin ID
        relationship_id: Relationship ID
        patch: JSON Patch operations

    Returns:
        Success confirmation
    """
    client = get_client()
    await client.update_relationship(twin_id, relationship_id, patch)
    return {
        "success": True,
        "message": f"Relationship '{relationship_id}' updated successfully",
    }


@mcp.tool()
async def delete_relationship(twin_id: str, relationship_id: str) -> dict:
    """
    Delete a relationship.

    Args:
        twin_id: Source twin ID
        relationship_id: Relationship ID to delete

    Returns:
        Success confirmation
    """
    client = get_client()
    await client.delete_relationship(twin_id, relationship_id)
    return {
        "success": True,
        "message": f"Relationship '{relationship_id}' deleted successfully",
    }


# ========== Query Tools ==========


@mcp.tool()
async def query_digital_twins(query: str) -> list[dict]:
    """
    Execute a query against the digital twins graph.

    Use the ADT Query Language (SQL-like syntax) for complex graph traversals and filtering.

    Args:
        query: Query in ADT Query Language, e.g.:
               'SELECT * FROM digitaltwins WHERE IS_OF_MODEL("dtmi:example:Room;1")'
               'SELECT * FROM digitaltwins T WHERE T.temperature > 70'

    Returns:
        Query results
    """
    client = get_client()
    results = []
    async for result in client.query_twins(query):
        results.append(result)
    return results


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
base_app = Starlette(
    routes=[
        Route("/health", health),  # Legacy, uses readiness logic
        Route("/healthz", liveness),  # Kubernetes liveness probe
        Route("/readyz", readiness),  # Kubernetes readiness probe
        Route("/ready", readiness),  # Alternative readiness endpoint
        Mount("/", app=mcp.http_app()),
    ]
)

# Wrap with middleware (order matters: CORS -> ResourceId -> App)
app = CORSMiddleware(
    ResourceIdMiddleware(base_app),
    allow_origins=["*"],  # Configure appropriately for production
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*", "X-Resource-Id"],  # Allow custom header
    expose_headers=["Mcp-Session-Id"],
)


# Run with: uvicorn konnektr_mcp.server:app --host 0.0.0.0 --port 8080
