# Architecture Documentation

## System Overview

The Konnektr Graph MCP Server is a centralized Model Context Protocol server that provides AI agents with validated, schema-enforced memory storage using Digital Twins Definition Language (DTDL). It routes requests to per-deployment API instances while maintaining a single authentication endpoint.

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                         AI Agent (Claude, etc.)                  │
└────────────────────────────────┬────────────────────────────────┘
                                 │
                                 │ MCP Protocol
                                 │
┌────────────────────────────────▼────────────────────────────────┐
│              https://mcp.graph.konnektr.io/mcp                   │
│                   ?resource_id=customer-graph-xyz                │
└────────────────────────────────┬────────────────────────────────┘
                                 │
                                 │
      ┌──────────────────────────┼──────────────────────────┐
      │    Centralized MCP Server (FastMCP)                  │
      │                                                       │
      │  ┌─────────────────────────────────────────────┐    │
      │  │    Resource ID Middleware                   │    │
      │  │  • Extract resource_id from query/header    │    │
      │  │  • Validate OAuth token (Auth0)             │    │
      │  │  • Create SDK client per request            │    │
      │  └────────────────┬────────────────────────────┘    │
      │                   │                                  │
      │  ┌────────────────▼────────────────────────────┐    │
      │  │    MCP Tools (FastMCP)                      │    │
      │  │  • list_models, get_model, create_models    │    │
      │  │  • create/update/delete digital twins       │    │
      │  │  • create/query relationships               │    │
      │  │  • semantic search, graph queries           │    │
      │  └────────────────┬────────────────────────────┘    │
      │                   │                                  │
      │  ┌────────────────▼────────────────────────────┐    │
      │  │    Konnektr Graph Python SDK                │    │
      │  │  • KonnektrGraphClient (aiohttp)            │    │
      │  │  • StaticTokenCredential                    │    │
      │  └────────────────┬────────────────────────────┘    │
      └───────────────────┼──────────────────────────────────┘
                          │
                          │ HTTPS + Bearer Token
                          │
┌─────────────────────────▼──────────────────────────────────────┐
│         https://customer-graph-xyz.api.graph.konnektr.io        │
│                                                                  │
│                 Per-Deployment API Pod                           │
│  • DTDL Schema Validation                                       │
│  • PostgreSQL with AGE (Graph Database)                         │
│  • Vector Embeddings (pgvector)                                 │
│  • Hybrid Search (Vector + Keyword)                             │
└──────────────────────────────────────────────────────────────────┘
```

## Component Breakdown

### 1. MCP Server (FastMCP)

**Responsibilities:**
- Expose MCP-compliant tools to AI agents
- Handle tool invocations and parameter validation
- Manage stateless HTTP sessions

**Technology:**
- FastMCP framework (automatic schema generation)
- Starlette (ASGI web framework)
- Uvicorn (ASGI server)

### 2. Resource ID Middleware

**Responsibilities:**
- Extract `resource_id` from query parameters or headers
- Create per-request context with isolated SDK client
- Clean up resources after request completion

**Routing Logic:**
```python
# Priority order:
1. Query parameter: ?resource_id=xyz
2. Header: X-Resource-Id: xyz
3. Error if missing
```

**Context Management:**
- Uses `contextvars` for thread-safe per-request state
- Each request gets isolated `KonnektrGraphClient` instance
- Automatic cleanup via try/finally in middleware

### 3. Authentication Layer

**Flow:**
```
AI Agent
  └─> Obtains OAuth 2.1 token from Auth0
       └─> Includes token in MCP request
            └─> MCP Server validates via Auth0TokenVerifier
                 ├─> Fetches JWKS from Auth0 (cached)
                 ├─> Verifies JWT signature
                 ├─> Validates audience & issuer
                 ├─> Checks required scopes
                 └─> Creates AccessToken or returns None
```

**Security Features:**
- RS256 JWT signature validation
- Audience validation: `https://graph.konnektr.io`
- Required scopes: `mcp:tools`
- JWKS caching for performance
- Optional auth bypass for local dev (`AUTH_ENABLED=false`)

### 4. Client Factory

**Purpose:**
Simplified pattern that eliminates redundant wrapper methods.

**Before (Wrapper Pattern):**
```python
class MCP_SDK_Client:
    async def get_twin(self, twin_id: str):
        client = await self._get_client()
        return await client.get_digital_twin(twin_id)

    async def create_twin(self, twin_id: str, twin: dict):
        client = await self._get_client()
        return await client.upsert_digital_twin(twin_id, twin)
    # ... 20+ wrapper methods
```

**After (Factory Pattern):**
```python
def create_client(resource_id: str, token: str) -> KonnektrGraphClient:
    endpoint = settings.api_base_url_template.format(resource_id=resource_id)
    credential = StaticTokenCredential(token)
    return KonnektrGraphClient(endpoint=endpoint, credential=credential)

# In tools:
client = get_client()
return await client.get_digital_twin(twin_id)  # Direct SDK usage
```

**Benefits:**
- No code duplication
- Direct access to all SDK methods
- Easier to maintain
- Type hints work correctly

### 5. Konnektr Graph Python SDK

**Responsibilities:**
- HTTP communication with API pods
- Async paging for large result sets
- Error handling and type conversion

**Key Features:**
- `aiohttp` for async HTTP
- `AsyncPagedIterator` for streaming results
- Credential provider pattern
- Automatic JSON serialization

## Data Flow

### Creating a Digital Twin

```
1. Agent calls create_or_replace_digital_twin(
     twin_id="room-101",
     twin={"$metadata": {"$model": "dtmi:example:Room;1"}, "temp": 72}
   )

2. FastMCP validates parameters against tool schema

3. MCP Server tool function:
   - Gets client from context
   - Calls client.upsert_digital_twin()

4. SDK Client:
   - Constructs PUT request to API pod
   - Includes Bearer token in Authorization header
   - Sends JSON payload

5. API Pod:
   - Validates token
   - Validates twin against DTDL model
   - Stores in PostgreSQL/AGE
   - Returns created twin

6. Response flows back to agent
```

### Semantic Search

```
1. Agent calls search_digital_twins(search_text="temperature sensor")

2. SDK makes POST to /digitaltwins/search

3. API Pod:
   - Generates embedding from search text
   - Performs vector similarity search (pgvector)
   - Combines with keyword matching
   - Returns ranked results

4. Agent receives structured twin data
```

## Scalability Considerations

### Current Design (Centralized MCP Server)

**Advantages:**
- Single endpoint for all customers
- Reduced Auth0 API usage (was a bottleneck)
- Simplified client configuration
- Centralized monitoring and logging

**Scalability:**
- Stateless server design (scales horizontally)
- Per-request resource isolation
- Short-lived SDK clients (no connection pooling issues)
- No in-memory state to synchronize

**Bottlenecks:**
- Auth0 token validation (mitigated by JWKS caching)
- Network latency to per-deployment API pods
- JWKS cache is in-memory (not shared across instances)

### Performance Optimizations

1. **JWKS Caching:**
   - Cached in memory after first fetch
   - Eliminates repeated Auth0 API calls
   - Single cache per server instance

2. **Async I/O:**
   - Non-blocking HTTP operations
   - Concurrent request handling via uvicorn workers
   - Async SDK for parallel API calls

3. **Context Variable Isolation:**
   - O(1) context lookup per request
   - Thread-safe without locks
   - Automatic cleanup

## Security Model

### Threat Model

**Protected Against:**
- ✅ Unauthorized access (OAuth validation)
- ✅ Token forgery (JWT signature verification)
- ✅ Resource ID injection (isolated per-request clients)
- ✅ Cross-tenant access (resource_id scoping)

**Not Protected Against (API Pod Responsibility):**
- Schema validation
- Rate limiting
- Data encryption at rest
- SQL injection (uses parameterized queries)

### Trust Boundaries

```
┌──────────────────────────────────────────┐
│  AI Agent (Untrusted)                    │
└─────────────────┬────────────────────────┘
                  │ OAuth Token Required
┌─────────────────▼────────────────────────┐
│  MCP Server (Validates Token)            │
│  • Verifies JWT signature                │
│  • Validates scopes & audience           │
│  • Routes based on resource_id           │
└─────────────────┬────────────────────────┘
                  │ Token Forwarded
┌─────────────────▼────────────────────────┐
│  API Pod (Validates Token + Schema)      │
│  • Re-validates token                    │
│  • Enforces DTDL schema                  │
│  • Applies business rules                │
└──────────────────────────────────────────┘
```

### Defense in Depth

1. **Layer 1 (MCP Server):** Token validation, resource routing
2. **Layer 2 (API Pod):** Token re-validation, schema enforcement
3. **Layer 3 (Database):** Row-level security, encryption

## Error Handling

### Validation Errors (API Pod)

When agent tries to create invalid twin:

```json
{
  "error": "Validation failed",
  "details": "Property 'temperature' is required by model dtmi:example:Room;1"
}
```

### Authentication Errors

```json
{
  "error": "unauthorized",
  "message": "Invalid or expired token"
}
```

### Not Found Errors

```json
{
  "error": "not_found",
  "message": "Twin 'room-101' does not exist"
}
```

### Design Philosophy

**Fail Fast:**
- Validate early (MCP parameter validation)
- Clear error messages
- No silent failures

**Propagate Context:**
- Include resource_id in logs
- Trace IDs for debugging
- Structured error responses

## Monitoring & Observability

### Health Checks

```
GET /health   -> {"status": "healthy", "version": "0.1.0"}
GET /ready    -> {"status": "healthy", "version": "0.1.0"}
```

### Key Metrics to Monitor

1. **Request Metrics:**
   - Requests per second
   - Response time (p50, p95, p99)
   - Error rate by status code

2. **Authentication Metrics:**
   - Token validation time
   - Token validation failures
   - JWKS fetch frequency

3. **SDK Metrics:**
   - API pod response time
   - SDK client creation time
   - Connection pool exhaustion

4. **Resource Metrics:**
   - CPU usage
   - Memory usage
   - Open connections

### Logging Strategy

```python
# Structured logging with resource_id context
{
  "timestamp": "2024-01-01T12:00:00Z",
  "level": "INFO",
  "resource_id": "customer-graph-xyz",
  "tool": "create_digital_twin",
  "twin_id": "room-101",
  "duration_ms": 45
}
```

## Future Enhancements

### 1. OIDC Proxy (See oidc-proxy.md)

Replace per-resource Auth0 apps with centralized proxy.

### 2. Connection Pooling

Currently each request creates new SDK client. Could pool clients per resource_id.

### 3. Distributed JWKS Cache

Share JWKS cache across server instances (Redis).

### 4. Circuit Breaker

Protect against failing API pods.

### 5. Request Coalescing

Batch identical requests to reduce API calls.

## Deployment Topology

### Development

```
[Local Machine]
  └─> Uvicorn (single worker)
      └─> localhost:8080
          └─> AUTH_ENABLED=false
```

### Staging

```
[Kubernetes]
  └─> Deployment (3 replicas)
      └─> Service (ClusterIP)
          └─> Ingress (HTTPS)
              └─> mcp.staging.graph.konnektr.io
```

### Production

```
[Kubernetes]
  └─> Deployment (10+ replicas, HPA)
      └─> Service (ClusterIP)
          └─> Ingress (HTTPS + WAF)
              └─> mcp.graph.konnektr.io

[Monitoring]
  ├─> Prometheus (metrics)
  ├─> Grafana (dashboards)
  └─> Jaeger (distributed tracing)
```

## Configuration Management

### Environment Variables

Loaded via `pydantic-settings`:

```python
class Settings(BaseSettings):
    auth0_domain: str  # Required in production
    auth0_audience: str = "https://graph.konnektr.io"
    auth_enabled: bool = True
    api_base_url_template: str = "https://{resource_id}.api..."

    class Config:
        env_file = ".env"  # Load from .env file
```

### Deployment Strategies

**Development:** `.env` file
**Staging:** Kubernetes ConfigMap
**Production:** Kubernetes Secret + External Secrets Operator

## API Compatibility

### MCP Protocol Version

Supports MCP protocol as implemented by FastMCP 1.9.0+.

### Breaking Changes

Semantic versioning for server:
- Major: Breaking changes to tool signatures
- Minor: New tools added
- Patch: Bug fixes

### SDK Compatibility

Server requires `konnektr-graph>=0.1.2` for search methods.
