# konnektr_mcp/server.py
import contextvars
import logging
from dataclasses import dataclass
from typing_extensions import Annotated
from urllib.parse import parse_qs
from typing import Any, Dict, Optional

from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.routing import Mount, Route
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from fastmcp import FastMCP
from fastmcp.server.auth import OIDCProxy
from mcp.types import Icon
from key_value.aio.stores.disk import DiskStore
from konnektr_graph.aio import KonnektrGraphClient
from konnektr_graph.types import (
    DtdlInterface,
    JsonPatchOperation,
    BasicDigitalTwin,
    BasicRelationship,
    DigitalTwinMetadata,
)

from konnektr_mcp.config import get_settings
from konnektr_mcp.client_factory import create_client

# from konnektr_mcp.types import DigitalTwin, DigitalTwinMetadata, Relationship

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
        client_storage=DiskStore(directory="/var/lib/fastmcp/oauth"),
    )
    if settings.auth_enabled
    else None
)

mcp = FastMCP(
    name="Konnektr MCP",
    version="0.1.0",
    website_url="https://konnektr.io",
    icons=[Icon(src="https://konnektr.io/konnektr.svg", mimeType="image/svg+xml")],
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
3. **Create Models**: Use `create_model` to add new DTDL models. Prefer extending existing models.
4. **Create Twins**: Store validated data as digital twins conforming to models
5. **Build Graph**: Connect twins using relationships defined in the models
6. **Search & Query**: Find information using semantic search or graph queries

The system will provide detailed validation errors if you try to create twins or relationships that don't match the schema.""",
    stateless_http=True,
    json_response=True,
    auth=(auth if settings.auth_enabled else None),
)


# ========== Model Tools ==========


@mcp.tool(annotations={"readOnlyHint": True})
async def list_models(
    dependencies_for: Annotated[
        Optional[list[str]], "Optional list of model IDs to filter by dependencies"
    ] = None,
) -> list[dict]:
    """
    List all DTDL models in the graph (summary only). Use get_model for full details.

    This returns a lightweight list of model IDs and display names to help you discover
    available schemas without consuming too many tokens.

    Returns:
        List of model summaries with IDs and display names
    """
    client = get_client()
    models = []
    async for model in client.list_models(
        dependencies_for=dependencies_for, include_model_definition=False
    ):
        models.append(model.to_dict())
    return models


@mcp.tool(annotations={"readOnlyHint": True})
async def get_model(
    model_id: Annotated[
        str, "The DTMI of the model to retrieve (e.g. 'dtmi:example:Room;1')"
    ],
) -> dict:
    """
    Get the complete DTDL model definition including all properties, relationships, and components.

    Use this to understand what properties are required/optional and what relationships are allowed
    before creating digital twins.

    Returns:
        Full model definition with flattened inherited properties and relationships
    """
    client = get_client()
    model = await client.get_model(model_id, include_base_model_contents=True)
    return model.to_dict()


@mcp.tool()
async def create_model(model: Annotated[dict, "DTDL model definition"]) -> dict:
    """
    Create one DTDL model. Models must be valid DTDL v3/v4.
    Any dependent models must already exist in the system.
    The system validates DTDL syntax and will return detailed error messages if the schema is invalid.

    Example basic model:
        {
            "@id": "dtmi:example:Space;1",
            "@type": "Interface",
            "displayName": {"en":"Space"},
            "description": {"en":"A physical space in a building."},
            "contents": [
                {
                    "@type": "Property",
                    "name": "name",
                    "displayName": {"en":"Name"},
                    "description": {"en":"The name of the room."},
                    "schema": "string"
                }
            ],
            "@context": "dtmi:dtdl:context;4"
        }
    Example with inheritance and quantitative property:
        {
            "@id": "dtmi:example:Room;1",
            "@type": "Interface",
            "displayName": {"en":"Room"},
            "description": {"en":"A room in a building."},
            "extends": ["dtmi:example:Space;1"],
            "contents": [
                {
                    "@type": ["Property","Temperature"],
                    "name": "temperature",
                    "displayName": {"en":"Temperature"},
                    "description": {"en":"The current room temperature in Celsius."},
                    "schema": "double",
                    "unit": "degreeCelsius",
                    "writable": true
                }
            ],
            "@context": ["dtmi:dtdl:context;4","dtmi:dtdl:extension:quantitativeTypes;2"]
        }

    Returns:
        Success message with count of created models
    """
    client = get_client()
    dtdl_model = DtdlInterface.from_dict(model)
    await client.create_models([dtdl_model])
    return {"success": True, "message": f"Successfully created model {dtdl_model.id}."}


@mcp.tool(annotations={"destructiveHint": True})
async def delete_model(
    model_id: Annotated[
        str, "The DTMI of the model to delete (e.g. 'dtmi:example:Room;1')"
    ],
) -> dict:
    """
    Delete a DTDL model. All dependent models and digital twins must be deleted first.

    Returns:
        Success confirmation
    """
    client = get_client()
    await client.delete_model(model_id)
    return {"success": True, "message": f"Model '{model_id}' deleted successfully"}


@mcp.tool(annotations={"readOnlyHint": True})
async def search_models(
    search_text: Annotated[
        Optional[str], "Search query (searches display name, description, ID)"
    ] = None,
    limit: Annotated[int, "Maximum number of results"] = 10,
) -> list[dict]:
    """
    Search for DTDL models using semantic search and keyword matching.
    Searches across model IDs, display names, and descriptions to help you find relevant schemas.


    Returns:
        Matching models with IDs, display names, and descriptions
    """
    client = get_client()
    return await client.search_models(search_text or "", limit)


# ========== Digital Twin Tools ==========


@mcp.tool(annotations={"readOnlyHint": True})
async def get_digital_twin(
    twin_id: Annotated[str, "The unique ID of the digital twin"],
) -> dict:
    """
    Get a digital twin by its ID.

    Args:
        twin_id: The unique ID of the digital twin

    Returns:
        Twin data including all properties and metadata
    """
    client = get_client()
    twin = await client.get_digital_twin(twin_id)
    return twin.to_dict()
    # return DigitalTwin.model_validate(twin.to_dict())


@mcp.tool()
async def create_or_replace_digital_twin(
    twin_id: Annotated[str, "The unique ID of the digital twin"],
    model_id: Annotated[str, "The DTMI of the model this twin conforms to"],
    properties: Annotated[
        Optional[Dict[str, Any]],
        """A dictionary of twin properties (e.g., {"temperature": 70}).""",
    ] = None,
) -> dict:
    """
    Create a new digital twin or replace an existing one.

    The twin must conform to its DTDL model. The system will validate:
    - All required properties are present
    - Property types match the schema
    - No extra properties beyond the model definition

    Returns:
        Created/updated twin data
    """
    client = get_client()
    twin = BasicDigitalTwin(
        dtId=twin_id,
        metadata=DigitalTwinMetadata(model_id),
        contents=properties or {},
    )
    new_twin = await client.upsert_digital_twin(twin_id, twin)
    return new_twin.to_dict()
    # return DigitalTwin.model_validate(new_twin.to_dict())


@mcp.tool()
async def update_digital_twin(
    twin_id: Annotated[str, "ID of the twin to update"],
    patch: Annotated[
        list[JsonPatchOperation],
        """JSON Patch operations, e.g., [{"op": "replace", "path": "/temperature", "value": 75}]""",
    ],
):
    """
    Update a digital twin using JSON Patch operations (RFC 6902).

    Returns:
        Success confirmation
    """
    client = get_client()
    await client.update_digital_twin(twin_id, patch)
    return {"success": True, "message": f"Twin '{twin_id}' updated successfully"}


@mcp.tool(annotations={"destructiveHint": True})
async def delete_digital_twin(
    twin_id: Annotated[str, "ID of the twin to delete"],
    delete_relationships: Annotated[
        bool,
        "If true, delete all relationships connected to the twin before deleting the twin itself",
    ] = False,
) -> dict:
    """
    Delete a digital twin. All relationships must be deleted first (unless delete_relationships is true).

    Returns:
        Success confirmation
    """
    client = get_client()
    if delete_relationships:
        # Delete all outgoing relationships
        async for rel in client.list_relationships(twin_id):
            await client.delete_relationship(twin_id, rel.relationshipId)
        # Delete all incoming relationships
        async for rel in client.list_incoming_relationships(twin_id):
            await client.delete_relationship(rel.sourceId, rel.relationshipId)
    await client.delete_digital_twin(twin_id)
    return {"success": True, "message": f"Twin '{twin_id}' deleted successfully"}


@mcp.tool()
async def search_digital_twins(
    search_text: Annotated[str, "Search query (semantic + keyword)"],
    model_id: Annotated[Optional[str], "Optional filter by model ID"] = None,
    limit: Annotated[int, "Maximum results"] = 10,
) -> list[dict]:
    """
    Search for digital twins using semantic search and keyword matching.

    Use this for memory retrieval based on concepts and meanings, not just exact matches.

    Returns:
        Matching twins with all their properties
    """
    client = get_client()
    return await client.search_twins(search_text, model_id, limit)


# ========== Relationship Tools ==========


@mcp.tool()
async def list_relationships(
    source_id: Annotated[str, "Source twin ID"],
    relationship_name: Annotated[
        Optional[str], "Optional filter by relationship name"
    ] = None,
) -> list[dict]:
    """
    List all outgoing relationships from a digital twin.

    Returns:
        List of relationships
    """
    client = get_client()
    relationships = []
    async for rel in client.list_relationships(source_id, relationship_name):
        relationships.append(rel.to_dict())
    return relationships


@mcp.tool()
async def get_relationship(
    source_id: Annotated[str, "Source twin ID"],
    relationship_id: Annotated[str, "The relationship ID"],
) -> dict:
    """
    Get a specific relationship by ID.

    Returns:
        Relationship data
    """
    client = get_client()
    rel = await client.get_relationship(source_id, relationship_id)
    return rel.to_dict()
    # return Relationship.model_validate(rel.to_dict())


@mcp.tool()
async def create_or_replace_relationship(
    relationship_id: Annotated[str, "The unique ID of the relationship"],
    source_id: Annotated[str, "Source twin ID"],
    target_id: Annotated[str, "Target twin ID"],
    relationship_name: Annotated[str, "The relationship name as defined in the model"],
    properties: Annotated[
        Optional[Dict[str, Any]],
        """A dictionary of relationship properties (e.g., {"since": "2024-01-01"}).""",
    ] = None,
) -> dict:
    """
    Create a relationship between two digital twins.

    Relationships must be defined in the source twin's DTDL model. The system validates:
    - The relationship type is allowed by the model
    - The target twin's model is compatible
    - Only allowed relationship properties are present

    Returns:
        Created relationship

    Example:
        {
            "$relationshipName": "contains",
            "$relationshipId": "rel-123",
            "$sourceId": "building-1",
            "$targetId": "room-101",
            "since": "2024-01-01"
        }
    """
    client = get_client()
    relationship = BasicRelationship(
        relationshipId=relationship_id,
        sourceId=source_id,
        targetId=target_id,
        relationshipName=relationship_name,
        properties=properties or {},
    )
    rel = await client.upsert_relationship(source_id, relationship_id, relationship)
    return rel.to_dict()
    # return Relationship.model_validate(rel.to_dict())


@mcp.tool()
async def update_relationship(
    source_id: Annotated[str, "Source twin ID"],
    relationship_id: Annotated[str, "Relationship ID"],
    patch: Annotated[list[JsonPatchOperation], "JSON Patch operations"],
) -> dict:
    """
    Update relationship properties using JSON Patch operations. Only properties can be updated.
    If you need to change name/source/target, delete and recreate the relationship.

    Returns:
        Success confirmation
    """
    client = get_client()
    await client.update_relationship(source_id, relationship_id, patch)
    return {
        "success": True,
        "message": f"Relationship '{relationship_id}' updated successfully",
    }


@mcp.tool(annotations={"destructiveHint": True})
async def delete_relationship(
    source_id: Annotated[str, "Source twin ID"],
    relationship_id: Annotated[str, "Relationship ID"],
) -> dict:
    """
    Delete a relationship.

    Returns:
        Success confirmation
    """
    client = get_client()
    await client.delete_relationship(source_id, relationship_id)
    return {
        "success": True,
        "message": f"Relationship '{relationship_id}' deleted successfully",
    }


# ========== Query Tools ==========


@mcp.tool()
async def query_digital_twins(query: Annotated[str, "Cypher query"]) -> list[dict]:
    """
    Execute a cypher query against the graph.

    **Schema Awareness**: Always check the DTDL model (use `GetModel`) to understand the
        properties and relationships of the twins you are querying. `GetModel` returns a
        flattened view including inherited properties.

    **Nodes & Labels**:
    - Digital Twins always have the `:Twin` label.
    - DTDL Models always have the `:Model` label.
    - Relationships are edges with the relationship name as the label.

    **Filtering**:
    - Access twin ID via `t.`$dtId``.
    - Access model ID via `t.`$metadata`.`$model``.
    - Access properties directly, e.g., `t.temperature`.

    **Inheritance**:
    To query all twins of a specific model AND its subtypes:
    ```cypher
    MATCH (t:Twin)
    WHERE digitaltwins.is_of_model(t, 'dtmi:example:BaseModel;1')
    RETURN t
    ```

    **Graph Traversal**:
    - Use standard cypher syntax to traverse relationships.
    - Example:
        ```cypher
        MATCH (a:Twin)-[r:contains]->(b:Twin)
        WHERE digitaltwins.is_of_model(t, 'dtmi:example:Room;1')
            AND b.`$metadata`.`$model` = 'dtmi:example:Thermostat;1'
            AND b.temperature > 75
        RETURN a, b`

    **Vector / Hybrid Search**:
    - If a property is defined as an embedding (Array<Double>), use pgvector functions.
    - Syntax: `MATCH (t:Twin) RETURN t ORDER BY l2_distance(t.propertyName, [vector_values]) ASC LIMIT 10`
    - You can also use `cosine_distance` if appropriate for the embedding type.
    - Always verify the embedding property name from the DTDL model.


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
