# konnektr_mcp/server.py
import logging
from typing_extensions import Annotated
from typing import Any, Dict, Optional

from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.routing import Mount, Route
from starlette.requests import Request
from starlette.responses import JSONResponse

from fastmcp import FastMCP
from fastmcp.server.auth import JWTVerifier
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
from konnektr_mcp.embeddings import (
    EmbeddingProvider,
    EmbeddingService,
    create_embedding_service,
    set_embedding_service,
    get_embedding_service,
    is_embedding_service_configured,
)
from konnektr_mcp.middleware import (
    RequestContext,
    get_current_context,
    get_client,
    CustomMiddleware,
)
from konnektr_mcp.auth import DualAuthOIDCProxy

logger = logging.getLogger(__name__)

# Configure logging for debugging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)


settings = get_settings()

# Initialize embedding service if enabled
if settings.embedding_enabled:
    try:
        provider = EmbeddingProvider(settings.embedding_provider)

        if provider == EmbeddingProvider.OPENAI:
            if settings.openai_api_key:
                embedding_service = create_embedding_service(
                    provider=provider,
                    api_key=settings.openai_api_key,
                    model=settings.openai_embedding_model,
                    dimensions=settings.embedding_dimensions,
                    openai_base_url=settings.openai_base_url,
                )
                set_embedding_service(embedding_service)
                logger.info(
                    f"Initialized OpenAI embedding service with model {settings.openai_embedding_model}"
                )
            else:
                logger.warning(
                    "Embedding enabled but OPENAI_API_KEY not set. Embeddings will not be generated."
                )

        elif provider == EmbeddingProvider.AZURE_OPENAI:
            if (
                settings.azure_openai_api_key
                and settings.azure_openai_endpoint
                and settings.azure_openai_deployment_name
            ):
                embedding_service = create_embedding_service(
                    provider=provider,
                    api_key=settings.azure_openai_api_key,
                    dimensions=settings.embedding_dimensions,
                    azure_endpoint=settings.azure_openai_endpoint,
                    azure_deployment_name=settings.azure_openai_deployment_name,
                    azure_api_version=settings.azure_openai_api_version,
                )
                set_embedding_service(embedding_service)
                logger.info(
                    f"Initialized Azure OpenAI embedding service with deployment {settings.azure_openai_deployment_name}"
                )
            else:
                logger.warning(
                    "Embedding enabled but Azure OpenAI settings incomplete. "
                    "Required: AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_DEPLOYMENT_NAME"
                )

        elif provider == EmbeddingProvider.GEMINI:
            if settings.google_api_key:
                embedding_service = create_embedding_service(
                    provider=provider,
                    api_key=settings.google_api_key,
                    model=settings.google_embedding_model,
                    dimensions=settings.embedding_dimensions,
                )
                set_embedding_service(embedding_service)
                logger.info(
                    f"Initialized Google Gemini embedding service with model {settings.google_embedding_model}"
                )
            else:
                logger.warning(
                    "Embedding enabled with Gemini provider but GOOGLE_API_KEY not set. "
                    "Embeddings will not be generated."
                )

    except Exception as e:
        logger.error(f"Failed to initialize embedding service: {e}", exc_info=True)
else:
    logger.info("Embedding service disabled via EMBEDDING_ENABLED=false")

# Initialize authentication
auth = None
if settings.auth_enabled:
    # Create JWTVerifier for client credentials flow
    jwt_verifier = JWTVerifier(
        jwks_uri=f"https://{settings.auth0_domain}/.well-known/jwks.json",
        audience=settings.auth0_audience,
        issuer=f"https://{settings.auth0_domain}/",
    )

    # Create DualAuthOIDCProxy for both flows
    # Extends OIDCProxy with JWTVerifier support while keeping all OIDC functionality
    auth = DualAuthOIDCProxy(
        jwt_verifier=jwt_verifier,
        # OIDCProxy arguments for interactive PKCE flow
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
    use_vector_search: Annotated[
        bool,
        "Enable vector similarity search using embeddings (requires configured embedding service)",
    ] = True,
    limit: Annotated[int, "Maximum number of results"] = 10,
) -> list[dict]:
    """
    Search for DTDL models using hybrid search (semantic + keyword matching).

    Combines:
    - **Vector similarity**: Finds semantically similar models based on meaning (if embedding service configured)
    - **Keyword matching**: Matches against model IDs, display names, and descriptions

    The search automatically generates an embedding for your query and compares it against model embeddings.

    Returns:
        Matching models with IDs, display names, descriptions, and similarity scores
    """
    client = get_client()

    # If vector search is enabled and embedding service is configured, generate query embedding
    query_embedding = None
    if use_vector_search and search_text and is_embedding_service_configured():
        try:
            embedding_service = get_embedding_service()
            query_embedding = await embedding_service.generate_embedding(search_text)
            if not query_embedding:
                raise ValueError("Received empty embedding from service")
            logger.debug(
                f"Generated query embedding with {len(query_embedding)} dimensions"
            )
        except Exception as e:
            logger.warning(
                f"Failed to generate query embedding: {e}. Falling back to keyword search."
            )

    # The SDK's search_models will handle both vector and keyword search
    # Pass the query embedding if available
    return await client.search_models(
        search_text or "",
        limit,
        vector=query_embedding,
    )


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
    embeddings: Annotated[
        Optional[Dict[str, str]],
        """A dictionary mapping embedding property names to their text content for vectorization.
        Example: {"descriptionEmbedding": "This is the description text to embed", "contentEmbedding": "Another text"}
        The server will generate vector embeddings from the text and store them in the specified properties.""",
    ] = None,
) -> dict:
    """
    Create a new digital twin or replace an existing one.

    The twin must conform to its DTDL model. The system will validate:
    - All required properties are present
    - Property types match the schema
    - No extra properties beyond the model definition

    Use the `embeddings` parameter to automatically generate and store vector embeddings for semantic search.
    Provide a dict mapping property names to text content - the server generates the vectors.

    Example:
        properties = {"name": "User Preferences", "description": "UI and display settings"}
        embeddings = {"descriptionEmbedding": "User prefers dark mode and minimal interface design"}

    Returns:
        Created/updated twin data
    """
    client = get_client()

    # Prepare the properties with generated embeddings
    all_properties = dict(properties) if properties else {}

    # Generate embeddings if provided and service is configured
    if embeddings and is_embedding_service_configured():
        embedding_service = get_embedding_service()

        # Batch all texts for efficient embedding generation
        property_names = list(embeddings.keys())
        texts = [embeddings[name] for name in property_names]

        logger.debug(f"Generating embeddings for {len(texts)} properties")
        generated_embeddings = await embedding_service.generate_embeddings(texts)

        # Add embeddings to properties
        for name, embedding in zip(property_names, generated_embeddings):
            all_properties[name] = embedding
            if not embedding:
                logger.warning(f"Generated empty embedding for property '{name}'")
            else:
                logger.debug(
                    f"Generated embedding for '{name}' with {len(embedding)} dimensions"
                )

    elif embeddings and not is_embedding_service_configured():
        logger.warning(
            "Embeddings requested but embedding service not configured. "
            "Set EMBEDDING_ENABLED=true and configure provider settings."
        )

    twin = BasicDigitalTwin(
        dtId=twin_id,
        metadata=DigitalTwinMetadata(model_id),
        contents=all_properties,
    )
    new_twin = await client.upsert_digital_twin(twin_id, twin)
    return new_twin.to_dict()


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


@mcp.tool()
async def update_digital_twin_embeddings(
    twin_id: Annotated[str, "ID of the twin to update"],
    embeddings: Annotated[
        Dict[str, str],
        """A dictionary mapping embedding property names to their new text content.
        Example: {"descriptionEmbedding": "Updated description text", "contentEmbedding": "Updated content"}
        The server will generate new embeddings and update the twin via JSON Patch.""",
    ],
) -> dict:
    """
    Update the vector embeddings for specified properties of a digital twin.

    This is useful when the underlying text data has changed and you want to refresh the embeddings
    used for semantic search. The function:
    1. Generates new embeddings from the provided text content
    2. Updates the twin properties using JSON Patch operations

    Example:
        embeddings = {"descriptionEmbedding": "New user preference: dark mode with high contrast"}

    Returns:
        Success confirmation with details of updated properties
    """
    if not is_embedding_service_configured():
        return {
            "success": False,
            "error": "Embedding service not configured. Set EMBEDDING_ENABLED=true and configure provider.",
        }

    embedding_service = get_embedding_service()
    client = get_client()

    # Generate embeddings for all provided texts
    property_names = list(embeddings.keys())
    texts = [embeddings[name] for name in property_names]

    logger.debug(
        f"Generating embeddings for {len(texts)} properties on twin '{twin_id}'"
    )
    generated_embeddings = await embedding_service.generate_embeddings(texts)

    # Build JSON Patch operations to update each embedding property
    patch_operations: list[JsonPatchOperation] = []
    for name, embedding in zip(property_names, generated_embeddings):
        patch_operations.append(
            JsonPatchOperation(op="replace", path=f"/{name}", value=embedding)
        )

    # Apply the patch
    await client.update_digital_twin(twin_id, patch_operations)

    return {
        "success": True,
        "message": f"Updated {len(property_names)} embedding(s) for twin '{twin_id}'",
        "updated_properties": property_names,
    }


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
    model_id: Annotated[Optional[str], "Optional filter by model ID (DTMI)"] = None,
    embedding_property: Annotated[
        Optional[str],
        "Name of the embedding property to search against (e.g., 'descriptionEmbedding'). If not specified, uses default embedding property.",
    ] = None,
    use_vector_search: Annotated[
        bool,
        "Enable vector similarity search using embeddings (requires configured embedding service)",
    ] = True,
    limit: Annotated[int, "Maximum results"] = 10,
) -> list[dict]:
    """
    Search for digital twins using hybrid search (vector similarity + keyword matching).

    Combines:
    - **Vector similarity**: Finds semantically similar twins based on meaning
    - **Keyword matching**: Matches against twin properties
    - **Model filtering**: Optionally filter by specific DTDL model types

    The search generates an embedding for your query and compares against twin embedding properties.

    Example use cases:
    - Find memories about "user interface preferences" → matches "dark mode settings", "UI theme"
    - Search for "network issues" → matches "connectivity problems", "WiFi disconnections"

    Returns:
        Matching twins with all properties and similarity scores
    """
    client = get_client()

    # If vector search is enabled and embedding service is configured, generate query embedding
    query_embedding = None
    if use_vector_search and is_embedding_service_configured():
        try:
            embedding_service = get_embedding_service()
            query_embedding = await embedding_service.generate_embedding(search_text)
            if not query_embedding:
                raise ValueError("Received empty embedding from service")
            logger.debug(
                f"Generated query embedding with {len(query_embedding)} dimensions"
            )
        except Exception as e:
            logger.warning(
                f"Failed to generate query embedding: {e}. Falling back to keyword search."
            )

    # Pass query embedding and optional embedding property name to SDK
    return await client.search_twins(
        search_text,
        model_id,
        limit,
        vector=query_embedding,
        embedding_property=embedding_property,
    )


@mcp.tool(annotations={"readOnlyHint": True})
async def vector_search_with_graph(
    search_text: Annotated[str, "Search query to find semantically similar content"],
    embedding_property: Annotated[
        str,
        "Name of the embedding property to search against (e.g., 'descriptionEmbedding', 'contentEmbedding')",
    ],
    model_id: Annotated[Optional[str], "Optional DTMI to filter by model type"] = None,
    distance_metric: Annotated[
        str,
        "Distance metric to use: 'cosine' (recommended for most cases) or 'l2' (Euclidean)",
    ] = "cosine",
    include_graph_context: Annotated[
        bool,
        "If true, also return related twins via relationships (1-hop neighborhood)",
    ] = False,
    limit: Annotated[int, "Maximum results to return"] = 10,
) -> dict:
    """
    Advanced vector similarity search with optional graph context expansion.

    This tool performs pure vector search using pgvector and can optionally expand results
    to include related twins via graph relationships.

    **How it works**:
    1. Generates an embedding for your search query
    2. Finds twins with similar embedding vectors using the specified distance metric
    3. Optionally retrieves related twins via relationships (graph expansion)

    **Distance metrics**:
    - `cosine`: Best for semantic similarity (normalized, range 0-2)
    - `l2`: Euclidean distance (good for comparing absolute positions)

    **When to use this vs search_digital_twins**:
    - Use this for direct vector search with fine-grained control
    - Use search_digital_twins for general-purpose hybrid search

    Example:
        vector_search_with_graph(
            search_text="machine learning model training",
            embedding_property="contentEmbedding",
            model_id="dtmi:example:Document;1",
            include_graph_context=True
        )

    Returns:
        Dict with:
        - matches: List of matching twins with similarity scores
        - related: Related twins via relationships (if include_graph_context=True)
        - query_embedding_dims: Dimension count of generated embedding
    """
    if not is_embedding_service_configured():
        return {
            "success": False,
            "error": "Embedding service not configured. Set EMBEDDING_ENABLED=true and configure provider.",
        }

    embedding_service = get_embedding_service()
    client = get_client()

    # Generate embedding for the search text
    query_embedding = await embedding_service.generate_embedding(search_text)
    if not query_embedding:
        return {
            "success": False,
            "error": "Failed to generate embedding for the search text.",
        }
    logger.debug(f"Generated query embedding with {len(query_embedding)} dimensions")

    # Build the vector search query using Cypher + pgvector
    distance_func = "cosine_distance" if distance_metric == "cosine" else "l2_distance"

    # Format embedding as a string for the Cypher query
    embedding_str = "[" + ",".join(str(v) for v in query_embedding) + "]"

    # Base query for vector search (optionally expanded with graph context)
    if include_graph_context:
        if model_id:
            query = f"""
            MATCH (t:Twin)
            WHERE digitaltwins.is_of_model(t, '{model_id}') AND t.`{embedding_property}` IS NOT NULL
            WITH t, {distance_func}(t.`{embedding_property}`, {embedding_str}) as distance
            ORDER BY distance ASC
            LIMIT {limit}
            OPTIONAL MATCH (incomingTwin:Twin)-[incomingRel]->(t)
            OPTIONAL MATCH (t)-[outgoingRel]->(outgoingTwin:Twin)
            RETURN t,
                   distance,
                   collect(DISTINCT {{type: 'incoming', relationship: incomingRel, twin: incomingTwin}}) as incoming,
                   collect(DISTINCT {{type: 'outgoing', relationship: outgoingRel, twin: outgoingTwin}}) as outgoing
            """
        else:
            query = f"""
            MATCH (t:Twin)
            WHERE t.`{embedding_property}` IS NOT NULL
            WITH t, {distance_func}(t.`{embedding_property}`, {embedding_str}) as distance
            ORDER BY distance ASC
            LIMIT {limit}
            OPTIONAL MATCH (incomingTwin:Twin)-[incomingRel]->(t)
            OPTIONAL MATCH (t)-[outgoingRel]->(outgoingTwin:Twin)
            RETURN t,
                   distance,
                   collect(DISTINCT {{type: 'incoming', relationship: incomingRel, twin: incomingTwin}}) as incoming,
                   collect(DISTINCT {{type: 'outgoing', relationship: outgoingRel, twin: outgoingTwin}}) as outgoing
            """
    else:
        if model_id:
            query = f"""
            MATCH (t:Twin)
            WHERE digitaltwins.is_of_model(t, '{model_id}') AND t.`{embedding_property}` IS NOT NULL
            RETURN t, {distance_func}(t.`{embedding_property}`, {embedding_str}) as distance
            ORDER BY distance ASC
            LIMIT {limit}
            """
        else:
            query = f"""
            MATCH (t:Twin)
            WHERE t.`{embedding_property}` IS NOT NULL
            RETURN t, {distance_func}(t.`{embedding_property}`, {embedding_str}) as distance
            ORDER BY distance ASC
            LIMIT {limit}
            """

    # Execute the query
    matches = []
    related: list[dict] = []
    async for result in client.query_twins(query):
        if include_graph_context and isinstance(result, dict):
            incoming = result.get("incoming") or []
            outgoing = result.get("outgoing") or []

            for entry in incoming:
                related.append(
                    {
                        "type": "incoming",
                        "relationship": entry.get("relationship"),
                        "twin": entry.get("twin"),
                    }
                )

            for entry in outgoing:
                related.append(
                    {
                        "type": "outgoing",
                        "relationship": entry.get("relationship"),
                        "twin": entry.get("twin"),
                    }
                )

            # Remove the aggregated context from the base match to keep matches clean
            result = {
                k: v for k, v in result.items() if k not in {"incoming", "outgoing"}
            }

        matches.append(result)

    result_payload = {
        "matches": matches,
        "query_embedding_dims": len(query_embedding),
        "distance_metric": distance_metric,
    }

    if include_graph_context:
        result_payload["related"] = related

    return result_payload


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


@mcp.tool(annotations={"readOnlyHint": True})
async def get_embedding_info() -> dict:
    """
    Get information about the configured embedding service.

    Returns details about:
    - Whether embeddings are enabled
    - The configured provider (OpenAI, Azure OpenAI, or custom)
    - The embedding dimension size
    - Model name (if applicable)

    Use this to verify embedding configuration before creating twins with embeddings.
    """
    if not is_embedding_service_configured():
        return {
            "enabled": False,
            "message": "Embedding service not configured. Set EMBEDDING_ENABLED=true and configure provider settings.",
        }

    embedding_service = get_embedding_service()

    return {
        "enabled": True,
        "provider": settings.embedding_provider,
        "dimensions": embedding_service.dimensions,
        "model": (
            settings.openai_embedding_model
            if settings.embedding_provider == "openai"
            else (
                settings.azure_openai_deployment_name
                if settings.embedding_provider == "azure_openai"
                else settings.google_embedding_model
            )
        ),
    }


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
