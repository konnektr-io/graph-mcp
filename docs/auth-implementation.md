# Authentication Implementation Guide

## Current Challenge

The Konnektr MCP Server has a dual-audience challenge:

1. **MCP Server** needs tokens with audience: `https://mcp.graph.konnektr.io`
2. **API Pods** need tokens with audience: `https://graph.konnektr.io`

Auth0 doesn't support multiple audiences in a single token, so we need token exchange.

## Architecture Options

### Option 1: Token Exchange (OBO) - RECOMMENDED

**Flow:**
```
1. Agent authenticates with Auth0
   └─> Gets token for audience: https://mcp.graph.konnektr.io

2. Agent calls MCP server with token

3. MCP server validates token
   └─> Validates audience: https://mcp.graph.konnektr.io
   └─> Validates scopes: mcp:tools

4. MCP server exchanges token (OBO flow)
   └─> Calls Auth0 token exchange endpoint
   └─> Gets NEW token for audience: https://graph.konnektr.io

5. MCP server calls API with exchanged token
   └─> API validates token
   └─> API processes request
```

**Auth0 Configuration:**

1. **MCP Resource Server (API):**
   - Identifier: `https://mcp.graph.konnektr.io`
   - Scopes: `mcp:tools`

2. **Graph API Resource Server:**
   - Identifier: `https://graph.konnektr.io`
   - Scopes: `graph:read`, `graph:write`

3. **Enable Token Exchange:**
   - In Auth0 dashboard → Applications → Your App → Advanced Settings
   - Enable "Token Exchange" grant type

**Implementation:**

```python
# konnektr_mcp/auth.py
import httpx
from jose import jwt, JWTError
from mcp.server.auth.provider import AccessToken
from mcp.server.auth import RemoteAuthProvider
from konnektr_mcp.config import get_settings

class Auth0RemoteAuthProvider(RemoteAuthProvider):
    """
    Remote auth provider for Auth0 with Dynamic Client Registration.
    Implements OAuth 2.1 RFC 9068 for MCP.
    """

    @property
    def well_known_uri(self) -> str:
        settings = get_settings()
        # Return MCP server's well-known endpoint
        return f"{settings.mcp_resource_url}/.well-known/oauth-protected-resource"

    async def verify_token(self, token: str) -> AccessToken | None:
        settings = get_settings()

        try:
            # Validate token for MCP audience
            jwks = await get_jwks()
            unverified_header = jwt.get_unverified_header(token)

            rsa_key = None
            for key in jwks["keys"]:
                if key["kid"] == unverified_header["kid"]:
                    rsa_key = {
                        "kty": key["kty"],
                        "kid": key["kid"],
                        "use": key["use"],
                        "n": key["n"],
                        "e": key["e"],
                    }
                    break

            if not rsa_key:
                return None

            # Verify token for MCP audience
            payload = jwt.decode(
                token,
                rsa_key,
                algorithms=["RS256"],
                audience=settings.mcp_resource_url,  # MCP audience!
                issuer=settings.issuer_url,
            )

            scopes = payload.get("scope", "").split()

            return AccessToken(
                token=token,
                client_id=payload.get("azp") or payload.get("sub", "unknown"),
                scopes=scopes,
                expires_at=payload.get("exp"),
            )

        except JWTError:
            return None


async def exchange_token_for_api(mcp_token: str) -> str:
    """
    Exchange MCP token for API token using Auth0 OBO flow.

    Args:
        mcp_token: Token with audience https://mcp.graph.konnektr.io

    Returns:
        Token with audience https://graph.konnektr.io
    """
    settings = get_settings()

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"https://{settings.auth0_domain}/oauth/token",
            json={
                "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
                "client_id": settings.auth0_client_id,
                "client_secret": settings.auth0_client_secret,
                "subject_token": mcp_token,
                "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
                "requested_token_type": "urn:ietf:params:oauth:token-type:access_token",
                "audience": "https://graph.konnektr.io",  # API audience!
                "scope": "graph:read graph:write"
            }
        )

        if response.status_code != 200:
            raise Exception(f"Token exchange failed: {response.text}")

        data = response.json()
        return data["access_token"]
```

**Well-Known Endpoint:**

```python
# konnektr_mcp/server.py

async def oauth_protected_resource(request: Request):
    """
    OAuth 2.0 Protected Resource Metadata (RFC 9728)
    Required for MCP clients to discover auth configuration.
    """
    settings = get_settings()

    return JSONResponse({
        "resource": settings.mcp_resource_url,
        "authorization_servers": [
            f"https://{settings.auth0_domain}"
        ],
        "scopes_supported": ["mcp:tools"],
        "bearer_methods_supported": ["header"],
        "resource_signing_alg_values_supported": ["RS256"]
    })

# Add to routes
base_app = Starlette(
    routes=[
        Route("/.well-known/oauth-protected-resource", oauth_protected_resource),
        Route("/healthz", liveness),
        # ... other routes
    ]
)
```

**Client Factory with Token Exchange:**

```python
# konnektr_mcp/client_factory.py

from konnektr_mcp.auth import exchange_token_for_api

async def create_client_with_token_exchange(
    resource_id: str,
    mcp_token: str
) -> KonnektrGraphClient:
    """
    Create SDK client with token exchange for API calls.
    """
    settings = get_settings()
    endpoint = settings.api_base_url_template.format(resource_id=resource_id)

    # Exchange MCP token for API token
    api_token = await exchange_token_for_api(mcp_token)

    # Create client with API token
    credential = StaticTokenCredential(api_token)
    return KonnektrGraphClient(endpoint=endpoint, credential=credential)
```

### Option 2: Shared Audience - SIMPLER (But Less Secure)

**Flow:**
```
1. Agent authenticates with Auth0
   └─> Gets token for audience: https://graph.konnektr.io

2. Agent calls MCP server with token

3. MCP server validates token
   └─> Validates audience: https://graph.konnektr.io
   └─> Validates scopes: mcp:tools graph:read graph:write

4. MCP server calls API with SAME token
   └─> API validates token
   └─> API processes request
```

**Auth0 Configuration:**

1. **Single Resource Server:**
   - Identifier: `https://graph.konnektr.io`
   - Scopes: `mcp:tools`, `graph:read`, `graph:write`

**Implementation:**

```python
# konnektr_mcp/auth.py

from mcp.server.auth import RemoteAuthProvider

class Auth0RemoteAuthProvider(RemoteAuthProvider):
    @property
    def well_known_uri(self) -> str:
        # Point to Graph API's well-known endpoint
        return "https://graph.konnektr.io/.well-known/oauth-protected-resource"

    async def verify_token(self, token: str) -> AccessToken | None:
        # Validate token for Graph API audience
        payload = jwt.decode(
            token,
            rsa_key,
            algorithms=["RS256"],
            audience="https://graph.konnektr.io",  # Single audience
            issuer=settings.issuer_url,
        )

        # Check for MCP scopes
        scopes = payload.get("scope", "").split()
        if "mcp:tools" not in scopes:
            return None

        return AccessToken(token=token, ...)
```

**Client Factory:**

```python
# No token exchange needed!
def create_client(resource_id: str, access_token: str) -> KonnektrGraphClient:
    settings = get_settings()
    endpoint = settings.api_base_url_template.format(resource_id=resource_id)
    credential = StaticTokenCredential(access_token)  # Same token
    return KonnektrGraphClient(endpoint=endpoint, credential=credential)
```

### Option 3: Trust Network (Development Only)

**Flow:**
```
1. Agent calls MCP server (no auth)

2. MCP server uses service account
   └─> Gets token via Client Credentials flow

3. MCP server calls API with service token
```

**DO NOT USE IN PRODUCTION**

## Recommendation

### For Production: **Option 1 (Token Exchange)**

**Why:**
- Proper security boundaries
- MCP server has its own audience
- Fine-grained permission control
- Follows OAuth 2.1 best practices

**Setup Steps:**

1. **Create Auth0 Resource Servers:**
   ```
   MCP Server API:
     - Identifier: https://mcp.graph.konnektr.io
     - Scopes: mcp:tools

   Graph API:
     - Identifier: https://graph.konnektr.io
     - Scopes: graph:read, graph:write
   ```

2. **Enable Token Exchange:**
   - Auth0 Dashboard → Applications → Advanced Settings
   - Enable "Token Exchange" grant type
   - Add API permissions for both resource servers

3. **Configure Application:**
   ```env
   AUTH0_DOMAIN=your-tenant.auth0.com
   AUTH0_CLIENT_ID=your-app-client-id
   AUTH0_CLIENT_SECRET=your-app-client-secret
   MCP_RESOURCE_URL=https://mcp.graph.konnektr.io
   API_AUDIENCE=https://graph.konnektr.io
   ```

4. **Deploy updated MCP server** with token exchange

### For Development: **Option 2 (Shared Audience)**

**Why:**
- Simpler setup
- Faster development
- Can upgrade to Option 1 later

**Setup Steps:**

1. **Create Single Resource Server:**
   ```
   Graph API (with MCP scopes):
     - Identifier: https://graph.konnektr.io
     - Scopes: mcp:tools, graph:read, graph:write
   ```

2. **Configure Application:**
   ```env
   AUTH0_DOMAIN=your-tenant.auth0.com
   AUTH0_AUDIENCE=https://graph.konnektr.io
   MCP_RESOURCE_URL=https://graph.konnektr.io
   ```

## Migration Path

**Phase 1: Start with Option 2 (Shared Audience)**
- Faster to implement
- Get MCP server working quickly
- Validate overall architecture

**Phase 2: Migrate to Option 1 (Token Exchange)**
- Add MCP resource server
- Implement token exchange
- Update client configuration
- Zero downtime migration (support both)

## Auth0 Configuration Checklist

### Option 1 (Token Exchange)

- [ ] Create MCP Resource Server in Auth0
  - Identifier: `https://mcp.graph.konnektr.io`
  - Scopes: `mcp:tools`

- [ ] Create Graph API Resource Server (if not exists)
  - Identifier: `https://graph.konnektr.io`
  - Scopes: `graph:read`, `graph:write`

- [ ] Create Auth0 Application (or use existing)
  - Type: Machine to Machine or Native
  - Authorize for both APIs

- [ ] Enable Token Exchange
  - Advanced Settings → Grant Types
  - Enable: `urn:ietf:params:oauth:grant-type:token-exchange`

- [ ] Configure Token Exchange
  - Add permission for MCP → Graph API token exchange

### Option 2 (Shared Audience)

- [ ] Create/Update Graph API Resource Server
  - Identifier: `https://graph.konnektr.io`
  - Scopes: `mcp:tools`, `graph:read`, `graph:write`

- [ ] Create Auth0 Application
  - Authorize for Graph API
  - Request all scopes

## Testing

### Option 1 (Token Exchange)

```bash
# 1. Get MCP token
curl -X POST https://your-tenant.auth0.com/oauth/token \
  -H 'content-type: application/json' \
  -d '{
    "client_id":"YOUR_CLIENT_ID",
    "client_secret":"YOUR_CLIENT_SECRET",
    "audience":"https://mcp.graph.konnektr.io",
    "grant_type":"client_credentials"
  }'

# 2. Use MCP token with server
curl https://mcp.graph.konnektr.io/mcp?resource_id=test \
  -H "Authorization: Bearer YOUR_MCP_TOKEN"

# 3. Server exchanges for API token internally
```

### Option 2 (Shared Audience)

```bash
# 1. Get token for Graph API
curl -X POST https://your-tenant.auth0.com/oauth/token \
  -H 'content-type: application/json' \
  -d '{
    "client_id":"YOUR_CLIENT_ID",
    "client_secret":"YOUR_CLIENT_SECRET",
    "audience":"https://graph.konnektr.io",
    "grant_type":"client_credentials"
  }'

# 2. Use with MCP server (same token works for API)
curl https://mcp.graph.konnektr.io/mcp?resource_id=test \
  -H "Authorization: Bearer YOUR_TOKEN"
```

## Summary

| Aspect | Option 1 (Token Exchange) | Option 2 (Shared Audience) |
|--------|---------------------------|----------------------------|
| Security | ⭐⭐⭐⭐⭐ Excellent | ⭐⭐⭐ Good |
| Complexity | Medium | Low |
| Setup Time | 2-3 hours | 30 minutes |
| Latency | +20ms (token exchange) | 0ms overhead |
| Separation | Clear boundaries | Shared audience |
| **Recommendation** | **Production** | **Development** |

**Start with Option 2, migrate to Option 1 when ready for production.**
