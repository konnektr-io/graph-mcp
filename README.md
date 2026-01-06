# Konnektr Graph MCP Server

**Semantic Knowledge Graph Memory System for AI Agents**

A centralized Model Context Protocol (MCP) server that provides AI agents with validated, schema-enforced memory storage using Digital Twins Definition Language (DTDL). Built with FastMCP and the Konnektr Graph Python SDK.

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![MCP Compatible](https://img.shields.io/badge/MCP-compatible-green.svg)](https://modelcontextprotocol.io/)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

## Why Konnektr Graph?

Unlike simple key-value stores or unstructured databases, Konnektr Graph provides:

- **Schema Validation**: All data must conform to DTDL models - invalid structures are rejected with clear error messages
- **Semantic Search**: Find information by meaning using vector embeddings, not just keyword matching
- **Knowledge Graph**: Connect related concepts with validated relationships
- **Multi-Tenancy**: Single MCP endpoint routes to isolated per-customer graph instances
- **Type Safety**: Strongly-typed properties, required fields, and relationship constraints

Perfect for AI agents that need reliable, structured memory across conversations.

## Quick Start

### Prerequisites

- Python 3.12+
- pip
- Access to Konnektr Graph API

### Installation

```bash
# 1. Clone repository
git clone <repository-url>
cd graph-mcp

# 2. Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env - set AUTH_ENABLED=false for local dev

# 5. Run server
uvicorn konnektr_mcp.server:app --reload --port 8080

# 6. Test with MCP Inspector
npx @modelcontextprotocol/inspector http://localhost:8080/mcp?resource_id=test
```

### Using in Claude Desktop

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "konnektr-graph": {
      "type": "http",
      "url": "https://mcp.graph.konnektr.io/mcp?resource_id=your-graph-id"
    }
  }
}
```

## Architecture

```
┌─────────────────┐
│   AI Agent      │  Stores validated memories
└────────┬────────┘
         │ MCP Protocol
┌────────▼────────────────────────────────────────┐
│  Centralized MCP Server                         │
│  • Validates OAuth tokens (Auth0)               │
│  • Routes by resource_id                        │
│  • 14 MCP tools for graph operations            │
└────────┬────────────────────────────────────────┘
         │ Konnektr Graph Python SDK
┌────────▼────────────────────────────────────────┐
│  Per-Deployment API Pods                        │
│  • PostgreSQL + AGE (graph database)            │
│  • Vector embeddings (pgvector)                 │
│  • DTDL schema validation                       │
└─────────────────────────────────────────────────┘
```

### Key Design Decisions

1. **Simplified Client Factory** - No wrapper methods, direct SDK usage
2. **Flattened Structure** - No nested `src/` folder
3. **PyPI SDK** - Uses `konnektr-graph>=0.1.2` from PyPI
4. **Stateless Design** - Scales horizontally, no shared state
5. **Resource Isolation** - Per-request context with automatic cleanup

## Available Tools

### Models (Schemas)
- `list_models` - List all available DTDL models
- `get_model` - Get complete model definition
- `create_models` - Create new DTDL models
- `search_models` - Hybrid semantic + keyword search for models

### Digital Twins (Data)
- `get_digital_twin` - Get twin by ID
- `create_or_replace_digital_twin` - Create/update twin with optional embeddings
- `update_digital_twin` - JSON Patch update
- `update_digital_twin_embeddings` - Update embeddings from new text content
- `delete_digital_twin` - Delete twin
- `search_digital_twins` - Hybrid semantic + keyword search for twins
- `vector_search_with_graph` - Advanced vector search with graph context

### Relationships (Connections)
- `list_relationships` - List twin's relationships
- `get_relationship` - Get specific relationship
- `create_or_replace_relationship` - Create/update relationship
- `update_relationship` - JSON Patch update relationship
- `delete_relationship` - Delete relationship

### Queries
- `query_digital_twins` - Execute Cypher queries with vector support
- `get_embedding_info` - Get embedding service configuration

## Example Usage

### Storing Agent Memory with Embeddings

```python
# 1. Discover available schemas
models = await list_models()
# [{"id": "dtmi:agent:Memory;1", "displayName": "Agent Memory"}, ...]

# 2. Get schema details
model = await get_model(model_id="dtmi:agent:Memory;1")
# Returns full DTDL with properties and relationships

# 3. Store validated memory WITH embeddings for semantic search
result = await create_or_replace_digital_twin(
    twin_id="memory-pref-001",
    model_id="dtmi:agent:Memory;1",
    properties={
        "content": "User prefers concise technical responses",
        "timestamp": "2024-01-15T10:30:00Z",
        "importance": 9
    },
    embeddings={
        # Server generates vector embedding from this text
        "contentEmbedding": "User prefers concise technical responses with code examples"
    }
)
```

### Semantic Search

```python
# Find relevant memories by meaning (uses vector similarity)
results = await search_digital_twins(
    search_text="how does user like to communicate",
    embedding_property="contentEmbedding",
    limit=5
)
# Returns twins semantically similar to query

# Advanced: Vector search with graph context
results = await vector_search_with_graph(
    search_text="communication preferences",
    embedding_property="contentEmbedding",
    distance_metric="cosine",
    include_graph_context=True
)
```

### Building Knowledge Graph

```python
# Create relationship between memories
await create_or_replace_relationship(
    relationship_id="rel-001",
    source_id="memory-001",
    target_id="memory-002",
    relationship_name="relatedTo"
)

# Query graph with vector ordering
results = await query_digital_twins(
    query="""
    MATCH (t:Twin)
    WHERE t.`$metadata`.`$model` = 'dtmi:agent:Memory;1'
    RETURN t ORDER BY cosine_distance(t.contentEmbedding, [0.1, ...]) ASC
    LIMIT 10
    """
)
```

## Embedding Configuration

The server supports embedding generation for semantic search:

```env
# Enable embeddings (default: true)
EMBEDDING_ENABLED=true
EMBEDDING_PROVIDER=openai  # or azure_openai, custom

# OpenAI
OPENAI_API_KEY=sk-your-key
OPENAI_EMBEDDING_MODEL=text-embedding-3-small

# Or Azure OpenAI
# AZURE_OPENAI_API_KEY=your-key
# AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
# AZURE_OPENAI_DEPLOYMENT_NAME=text-embedding-3-small
```

See [docs/embeddings.md](docs/embeddings.md) for full configuration options.

## Project Structure

```
graph-mcp/
├── konnektr_mcp/           # Main package (no nested src/)
│   ├── __init__.py
│   ├── server.py           # FastMCP server with all tools
│   ├── config.py           # Pydantic settings
│   ├── auth.py             # Auth0 token verification
│   └── client_factory.py   # SDK client factory (simplified)
├── docs/                   # Comprehensive documentation
│   ├── architecture.md     # System design & components
│   ├── usage-guide.md      # AI agent usage patterns
│   ├── deployment.md       # K8s, Docker, CI/CD
│   └── oidc-proxy.md       # Auth scaling assessment
├── requirements.txt        # Python dependencies (PyPI)
├── pyproject.toml          # Package metadata
├── Dockerfile              # Container image
├── .env.example            # Environment template
└── README.md               # This file
```

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `AUTH0_DOMAIN` | Auth0 tenant domain | Required |
| `AUTH0_AUDIENCE` | OAuth audience | `https://graph.konnektr.io` |
| `AUTH_ENABLED` | Enable authentication | `true` |
| `API_BASE_URL_TEMPLATE` | API endpoint template | `https://{resource_id}.api...` |
| `MCP_RESOURCE_URL` | MCP server URL | `https://mcp.graph.konnektr.io` |

### Resource ID Configuration

The `resource_id` identifies which graph instance to use:

**Option 1: Query Parameter** (Recommended)
```
https://mcp.graph.konnektr.io/mcp?resource_id=customer-graph-xyz
```

**Option 2: Custom Header**
```
X-Resource-Id: customer-graph-xyz
```

## Documentation

Comprehensive documentation in the `/docs` folder:

- **[Architecture](docs/architecture.md)** - System design, components, data flow, security
- **[Usage Guide](docs/usage-guide.md)** - AI agent patterns, workflows, best practices
- **[Deployment](docs/deployment.md)** - Local, Docker, Kubernetes, CI/CD
- **[OIDC Proxy Assessment](docs/oidc-proxy.md)** - Auth scaling strategy

## Development

### Running Tests

```bash
pip install -e ".[dev]"
pytest
```

### Code Style

```bash
# Format
black konnektr_mcp/

# Lint
ruff check konnektr_mcp/

# Type check
mypy konnektr_mcp/
```

### Local Development Without Auth

```bash
export AUTH_ENABLED=false
export API_BASE_URL_TEMPLATE=http://localhost:5000
uvicorn konnektr_mcp.server:app --reload
```

## Deployment

### Docker

```bash
docker build -t konnektr-mcp-server .
docker run -p 8080:8080 \
  -e AUTH0_DOMAIN=your-tenant.auth0.com \
  -e AUTH_ENABLED=true \
  konnektr-mcp-server
```

### Kubernetes

```bash
kubectl apply -f k8s/
kubectl get pods -n konnektr-mcp
```

See [deployment.md](docs/deployment.md) for complete guide.

## Key Improvements from Previous Version

### 1. Simplified Client Pattern

**Before:** Wrapper class with 20+ duplicate methods
```python
class MCP_SDK_Client:
    async def get_twin(self, twin_id: str):
        client = await self._get_client()
        return await client.get_digital_twin(twin_id)
    # ... 20 more wrappers
```

**After:** Factory pattern, direct SDK usage
```python
def create_client(resource_id, token):
    return KonnektrGraphClient(endpoint, credential)

# In tools:
client = get_client()
return await client.get_digital_twin(twin_id)  # Direct!
```

### 2. Better Structure

- Removed nested `src/` folder
- Package directly in root: `konnektr_mcp/`
- Easier imports and IDE navigation

### 3. Enhanced Tools

Added missing capabilities from C# implementation:
- `get_relationship` - Get specific relationship by ID
- `update_relationship` - JSON Patch update for relationships
- Better error messages and success confirmations
- Improved tool descriptions for AI agents

### 4. Comprehensive Documentation

- Architecture deep-dive
- AI agent usage patterns
- Production deployment guide
- OIDC Proxy scaling assessment

## Security

- OAuth 2.1 token validation (Auth0)
- JWKS caching for performance
- Required scopes: `mcp:tools`
- Per-request resource isolation
- No cross-tenant data access

See [architecture.md](docs/architecture.md#security-model) for security model details.

## Performance

- **Latency:** ~55ms per request (cached JWKS)
- **Throughput:** ~1000 req/sec per pod
- **Scalability:** Horizontal scaling with HPA
- **Stateless:** No shared state, scales linearly

## Monitoring

Health check endpoints:
```bash
curl https://mcp.graph.konnektr.io/health
# {"status": "healthy", "version": "0.1.0"}
```

Metrics:
- Request rate and latency
- Token validation time
- SDK client creation time
- Resource usage (CPU, memory)

## Authentication Scaling

The current implementation uses direct Auth0 validation per request. For scaling beyond 50+ agents/clients, consider the OIDC Proxy pattern:

- **Current:** Direct token validation, JWKS caching
- **With OIDC Proxy:** Single Auth0 app, Redis session storage, 68% cost reduction at scale

See [oidc-proxy.md](docs/oidc-proxy.md) for detailed assessment.

**Recommendation:** Start without proxy, add when scale demands it.

## Roadmap

- [ ] OIDC Proxy implementation (when >50 clients)
- [ ] Connection pooling optimization
- [ ] Distributed JWKS cache (Redis)
- [ ] Circuit breaker for API pods
- [ ] Request coalescing

## License

[Your License Here]

## Support

- **Documentation:** [docs/](docs/)
- **Issues:** [GitHub Issues](https://github.com/your-org/graph-mcp/issues)
- **API Docs:** [Konnektr Graph API](https://docs.graph.konnektr.io)

## Acknowledgments

Built with:
- [FastMCP](https://gofastmcp.com/) - MCP server framework
- [Konnektr Graph Python SDK](https://pypi.org/project/konnektr-graph/) - Graph client
- [Starlette](https://www.starlette.io/) - ASGI framework
- [Pydantic](https://pydantic.dev/) - Data validation

---

**Ready to give your AI agent validated, semantic memory?**

```bash
pip install -r requirements.txt
uvicorn konnektr_mcp.server:app --reload
```

Then point your MCP client to `http://localhost:8080/mcp?resource_id=test`
