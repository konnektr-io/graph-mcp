# Embedding Support

The Konnektr MCP Server supports vector embeddings for semantic search capabilities. This enables AI agents to find information based on meaning and context, not just exact keyword matches.

## Overview

Embeddings are dense vector representations of text that capture semantic meaning. The MCP server can:

1. **Generate embeddings** from text content when creating or updating digital twins
2. **Perform hybrid search** combining vector similarity with graph relationships
3. **Execute vector queries** using Cypher with pgvector functions

## Configuration

### Environment Variables

Configure embedding support via environment variables:

```bash
# Enable/disable embedding generation (default: true)
EMBEDDING_ENABLED=true

# Provider selection: "openai", "azure_openai", or "gemini"
EMBEDDING_PROVIDER=openai

# Fixed embedding dimensions (default: 1024)
EMBEDDING_DIMENSIONS=1024
```

### OpenAI Configuration (Default)

```bash
EMBEDDING_PROVIDER=openai
OPENAI_API_KEY=sk-your-api-key
OPENAI_EMBEDDING_MODEL=text-embedding-3-small  # default

# Optional: Use OpenAI-compatible endpoint
OPENAI_BASE_URL=https://your-proxy.example.com/v1
```

### Azure OpenAI Configuration

```bash
EMBEDDING_PROVIDER=azure_openai
AZURE_OPENAI_API_KEY=your-azure-key
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT_NAME=text-embedding-3-small
AZURE_OPENAI_API_VERSION=2024-02-01  # optional, default shown
```

### Google Gemini Configuration

```bash
EMBEDDING_PROVIDER=gemini
GOOGLE_API_KEY=your-google-api-key
GOOGLE_EMBEDDING_MODEL=text-embedding-004  # default

# Note: Dimensions are optional, defaults to 1024
EMBEDDING_DIMENSIONS=1024
```

**Setup Steps:**

1. Get a Google API key from [Google AI Studio](https://aistudio.google.com/app/apikey)
2. Enable the Generative Language API in your Google Cloud project
3. Set `GOOGLE_API_KEY` environment variable
4. Set `EMBEDDING_PROVIDER=gemini`

## Embedding Dimensions

The server uses a **fixed dimension of 1024** by default. This simplifies:

- Index creation in pgvector
- Cross-property vector searches
- Model compatibility and cost efficiency

To use a different dimension:

```bash
EMBEDDING_DIMENSIONS=768
```

> **Note**: All embedding properties should use the same dimension for consistent search behavior.

## Usage

### Creating Twins with Embeddings

Use the `embeddings` parameter to generate and store vectors:

```python
await create_or_replace_digital_twin(
    twin_id="memory-001",
    model_id="dtmi:example:Memory;1",
    properties={
        "title": "User Preferences",
        "description": "Dark mode and accessibility settings"
    },
    embeddings={
        # Map property names to text content
        "descriptionEmbedding": "User prefers dark mode with high contrast and larger fonts for accessibility",
        "titleEmbedding": "User preferences and settings"
    }
)
```

The server:

1. Generates embeddings from the provided text
2. Stores the vectors in the specified properties
3. Creates/updates the twin with all properties

### Updating Embeddings

When content changes, update embeddings:

```python
await update_digital_twin_embeddings(
    twin_id="memory-001",
    embeddings={
        "descriptionEmbedding": "Updated: User now prefers light mode with default fonts"
    }
)
```

### Searching with Embeddings

#### Simple Search

Use `search_digital_twins` for hybrid search:

```python
results = await search_digital_twins(
    search_text="accessibility settings",
    model_id="dtmi:example:Memory;1",  # optional filter
    embedding_property="descriptionEmbedding",  # specify which embedding to search
    limit=10
)
```

#### Advanced Vector Search with Graph Context

Use `vector_search_with_graph` for more control:

```python
results = await vector_search_with_graph(
    search_text="user interface preferences",
    embedding_property="descriptionEmbedding",
    model_id="dtmi:example:Memory;1",
    distance_metric="cosine",  # or "l2"
    include_graph_context=True,  # also return related twins
    limit=10
)
```

Returns:

```json
{
    "matches": [
        {"t": {"$dtId": "memory-001", ...}, "distance": 0.15},
        {"t": {"$dtId": "memory-002", ...}, "distance": 0.23}
    ],
    "related": [
        {"type": "outgoing", "relationship": {...}},
        {"type": "incoming", "relationship": {...}}
    ],
    "query_embedding_dims": 1536,
    "distance_metric": "cosine"
}
```

#### Direct Cypher Queries

For full control, use Cypher with pgvector functions:

```cypher
MATCH (t:Twin)
WHERE t.`$metadata`.`$model` = 'dtmi:example:Memory;1'
RETURN t, cosine_distance(t.descriptionEmbedding, [0.1, 0.2, ...]) as distance
ORDER BY distance ASC
LIMIT 10
```

Available distance functions:

- `cosine_distance(a, b)` - Cosine distance (0-2 range)
- `l2_distance(a, b)` - Euclidean distance
- `l1_distance(a, b)` - Manhattan distance
- `inner_product(a, b)` - Dot product (negative for similarity ordering)

## DTDL Model Definition

Define embedding properties in your DTDL models:

```json
{
  "@id": "dtmi:example:SemanticMemory;1",
  "@type": "Interface",
  "displayName": "Semantic Memory",
  "contents": [
    {
      "@type": "Property",
      "name": "content",
      "schema": "string",
      "description": "The text content of the memory"
    },
    {
      "@type": "Property",
      "name": "contentEmbedding",
      "schema": {
        "@type": "Array",
        "elementSchema": "double"
      },
      "description": "Vector embedding of the content (1536 dimensions)"
    },
    {
      "@type": "Property",
      "name": "summary",
      "schema": "string"
    },
    {
      "@type": "Property",
      "name": "summaryEmbedding",
      "schema": {
        "@type": "Array",
        "elementSchema": "double"
      },
      "description": "Vector embedding of the summary"
    }
  ]
}
```

## Best Practices

### 1. Choose Meaningful Text for Embeddings

Good:

```python
embeddings={
    "descriptionEmbedding": "User prefers dark mode interface with high contrast colors for better readability in low light conditions"
}
```

Poor:

```python
embeddings={
    "descriptionEmbedding": "dark mode true"  # Too short, lacks context
}
```

### 2. Use Multiple Embedding Properties

Create separate embeddings for different aspects:

```python
embeddings={
    "titleEmbedding": title_text,
    "contentEmbedding": full_content,
    "summaryEmbedding": summary_text
}
```

### 3. Consistent Naming Convention

Use clear, consistent names:

- `contentEmbedding`
- `descriptionEmbedding`
- `titleEmbedding`
- `summaryEmbedding`

### 4. Index Frequently Searched Properties

For large datasets, create pgvector indexes on embedding properties for faster searches.

### 5. Check Configuration

Use `get_embedding_info()` to verify configuration:

```python
info = await get_embedding_info()
# Returns: {"enabled": True, "provider": "openai", "dimensions": 1536, "model": "text-embedding-3-small"}
```

## Troubleshooting

### "Embedding service not configured"

Ensure:

1. `EMBEDDING_ENABLED=true`
2. Provider-specific credentials are set
3. Check server logs for initialization errors

### Dimension Mismatch

If you change `EMBEDDING_DIMENSIONS`, existing embeddings with different dimensions will cause errors. Either:

- Re-generate all embeddings with the new dimension
- Keep the same dimension throughout

### Search Returns No Results

1. Verify embedding properties exist on the twins
2. Check the embedding property name is correct
3. Try with `use_vector_search=False` to test keyword search
4. Verify twins have the expected model type

## Performance Considerations

- Batch embedding generation is used when creating twins with multiple embedding properties
- Consider using appropriate pgvector indexes for large datasets
- Limit graph context expansion for performance-sensitive queries
