from typing import Annotated, Optional
from fastmcp import FastMCP
from konnektr_mcp.server import get_client
from konnektr_graph.types import (
    BasicDigitalTwin,
    BasicRelationship,
    DtdlInterface,
    JsonPatchOperation,
)


def register_tools(mcp: FastMCP) -> None:

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

        Args:
            model_id: The DTMI (e.g., 'dtmi:example:Room;1')

        Returns:
            Full model definition with flattened inherited properties and relationships
        """
        client = get_client()
        model = await client.get_model(model_id, include_base_model_contents=True)
        return model.to_dict()

    @mcp.tool()
    async def create_model(model: Annotated[dict, "DTDL model definition"]):
        """
        Create one DTDL model. Models must be valid DTDL v3/v4.
        Any dependent models must already exist in the system.
        The system validates DTDL syntax and will return detailed error messages if the schema is invalid.

        Returns:
            Success message with count of created models
        """
        client = get_client()
        dtdl_model = DtdlInterface.from_dict(model)
        await client.create_models([dtdl_model])
        return f"Successfully created model {dtdl_model.id}."

    @mcp.tool(annotations={"readOnlyHint": True})
    async def search_models(search_text: Optional[str] = None, limit: int = 10):
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

    @mcp.tool(annotations={"readOnlyHint": True})
    async def get_digital_twin(
        twin_id: Annotated[str, "The unique ID of the digital twin"],
    ):
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
    async def create_or_replace_digital_twin(twin_id: str, twin: BasicDigitalTwin):
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
    async def update_digital_twin(twin_id: str, patch: list[JsonPatchOperation]):
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
    async def list_relationships(twin_id: str, relationship_name: str | None = None):
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
    async def get_relationship(twin_id: str, relationship_id: str):
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
        source_twin_id: str, relationship_id: str, relationship: BasicRelationship
    ):
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
        return await client.upsert_relationship(
            source_twin_id, relationship_id, relationship
        )

    @mcp.tool()
    async def update_relationship(
        twin_id: str, relationship_id: str, patch: list[JsonPatchOperation]
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
    async def delete_relationship(twin_id: str, relationship_id: str):
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
