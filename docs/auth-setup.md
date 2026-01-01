# Auth0 Configuration for Konnektr MCP Server

## Strategy: Shared Audience

We use the **shared audience** strategy where both the MCP server and the Graph API use the same Auth0 audience: `https://graph.konnektr.io`.

This is simpler than token exchange and works perfectly for our use case since:
- The MCP server just proxies requests to the API
- Both components trust the same tokens
- No additional token exchange overhead

## Architecture

```
Agent
  ↓
Gets token from Auth0
  audience: https://graph.konnektr.io
  scopes: mcp:tools graph:read graph:write
  ↓
Calls MCP Server with token
  ↓
MCP Server validates token
  - Checks audience: https://graph.konnektr.io ✓
  - Checks scopes: mcp:tools ✓
  ↓
MCP Server calls API with SAME token
  ↓
API validates token
  - Checks audience: https://graph.konnektr.io ✓
  - Checks scopes: graph:read graph:write ✓
```

## Auth0 Setup

### 1. Create/Update API (Resource Server)

In Auth0 Dashboard → Applications → APIs:

```yaml
Name: Konnektr Graph API
Identifier: https://graph.konnektr.io
Signing Algorithm: RS256

Permissions (Scopes):
  - mcp:tools          # MCP server operations
  - graph:read         # Read graph data
  - graph:write        # Modify graph data
```

**Important:** Use `https://graph.konnektr.io` as the identifier, NOT `https://mcp.graph.konnektr.io`. The MCP server will validate tokens for this same audience.

### 2. Enable Dynamic Client Registration

In Auth0 Dashboard → Applications → Advanced Settings:

Enable:
- [x] Dynamic Client Registration

This allows MCP clients (like Claude Desktop) to register themselves automatically.

### 3. Configure Application (Optional for M2M)

If you want to test with machine-to-machine:

```yaml
Application Type: Machine to Machine
Name: Konnektr MCP Test Client

Authorized APIs:
  - Konnektr Graph API
    Scopes: mcp:tools, graph:read, graph:write
```

## MCP Server Configuration

Create `.env` file:

```env
# Auth0
AUTH0_DOMAIN=your-tenant.auth0.com
AUTH0_AUDIENCE=https://graph.konnektr.io  # Shared audience!
AUTH_ENABLED=true

# API
API_BASE_URL_TEMPLATE=https://{resource_id}.api.graph.konnektr.io

# MCP Server URL (for .well-known endpoint)
MCP_RESOURCE_URL=https://mcp.graph.konnektr.io
```

## How FastMCP Handles Auth

FastMCP's `Auth0RemoteAuthProvider` automatically:

1. **Exposes `.well-known/oauth-protected-resource` endpoint**
   - Returns OAuth 2.0 Protected Resource Metadata (RFC 9728)
   - MCP clients use this to discover auth configuration

2. **Validates tokens**
   - Fetches JWKS from Auth0
   - Verifies JWT signature
   - Checks audience and issuer
   - Returns `AccessToken` or `None`

3. **Handles Dynamic Client Registration**
   - MCP clients can register themselves
   - Gets client credentials
   - Handles OAuth flows

## Testing

### Test with curl

```bash
# 1. Get token from Auth0
TOKEN=$(curl -X POST https://your-tenant.auth0.com/oauth/token \
  -H 'content-type: application/json' \
  -d '{
    "client_id":"YOUR_CLIENT_ID",
    "client_secret":"YOUR_CLIENT_SECRET",
    "audience":"https://graph.konnektr.io",
    "grant_type":"client_credentials",
    "scope":"mcp:tools graph:read graph:write"
  }' | jq -r '.access_token')

# 2. Call MCP server
curl https://mcp.graph.konnektr.io/mcp?resource_id=test \
  -H "Authorization: Bearer $TOKEN"

# 3. Check well-known endpoint
curl https://mcp.graph.konnektr.io/.well-known/oauth-protected-resource
```

### Expected well-known response

```json
{
  "resource": "https://graph.konnektr.io",
  "authorization_servers": [
    "https://your-tenant.auth0.com"
  ],
  "scopes_supported": ["mcp:tools", "graph:read", "graph:write"],
  "bearer_methods_supported": ["header"],
  "resource_signing_alg_values_supported": ["RS256"]
}
```

## MCP Client Configuration

### Claude Desktop

```json
{
  "mcpServers": {
    "konnektr-graph": {
      "type": "http",
      "url": "https://mcp.graph.konnektr.io/mcp?resource_id=your-resource-id",
      "auth": {
        "type": "oauth",
        "flow": "device_code"
      }
    }
  }
}
```

Claude Desktop will:
1. Discover auth config from `.well-known/oauth-protected-resource`
2. Use device code flow to authenticate user
3. Get token with correct audience and scopes
4. Include token in all MCP requests

## Scopes

| Scope | Purpose | Required By |
|-------|---------|-------------|
| `mcp:tools` | Access MCP server tools | MCP Server |
| `graph:read` | Read digital twins, models, relationships | Graph API |
| `graph:write` | Create/update/delete graph data | Graph API |

## Security Considerations

### Why Shared Audience is Secure

**Concern:** "Isn't it less secure to share the audience?"

**Answer:** No, because:

1. **Scopes provide fine-grained control**
   - MCP server only checks for `mcp:tools`
   - API checks for `graph:read` / `graph:write`
   - Tokens can have subset of scopes

2. **Both components validate independently**
   - MCP server validates before accepting requests
   - API validates again before processing
   - Defense in depth

3. **Network isolation**
   - MCP server and API can be in separate networks
   - Even with valid token, still need network access

4. **Token lifetime limits exposure**
   - Short-lived tokens (1 hour default)
   - Refresh tokens for long-running clients

### Token Exchange (Future Enhancement)

If you need strict audience separation:

1. Create second API in Auth0: `https://mcp.graph.konnektr.io`
2. Enable token exchange grant
3. Set `USE_TOKEN_EXCHANGE=true`
4. MCP server exchanges tokens before calling API

This adds ~20ms latency but provides:
- Separate audit trails
- Stricter security boundaries
- Different token lifetimes per component

See [auth-implementation.md](./auth-implementation.md) for details.

## Troubleshooting

### "Invalid audience"

**Cause:** Token has wrong audience

**Fix:**
1. Check Auth0 API identifier is `https://graph.konnektr.io`
2. Check token request includes correct `audience` parameter
3. Verify `AUTH0_AUDIENCE` in `.env`

### "Insufficient scopes"

**Cause:** Token missing required scopes

**Fix:**
1. Ensure API has `mcp:tools`, `graph:read`, `graph:write` scopes defined
2. Client must request these scopes
3. Application must be authorized for these scopes

### "JWKS fetch failed"

**Cause:** Can't reach Auth0

**Fix:**
1. Check `AUTH0_DOMAIN` is correct
2. Verify network connectivity to Auth0
3. Check firewall rules

### ".well-known endpoint not found"

**Cause:** FastMCP auth not properly configured

**Fix:**
1. Ensure `auth_provider` is set in FastMCP initialization
2. Check Auth0RemoteAuthProvider is properly instantiated
3. Verify `AUTH_ENABLED=true`

## Verification Checklist

- [ ] Auth0 API created with identifier `https://graph.konnektr.io`
- [ ] Scopes defined: `mcp:tools`, `graph:read`, `graph:write`
- [ ] Dynamic Client Registration enabled
- [ ] `.env` file has `AUTH0_DOMAIN` and `AUTH0_AUDIENCE`
- [ ] MCP server starts without errors
- [ ] `.well-known/oauth-protected-resource` endpoint responds
- [ ] Can get token from Auth0 with correct audience
- [ ] Token works with both MCP server and Graph API

## Production Checklist

- [ ] Use production Auth0 tenant
- [ ] Configure proper CORS origins
- [ ] Set up monitoring for auth failures
- [ ] Implement rate limiting
- [ ] Configure token lifetime appropriately
- [ ] Set up alerts for JWKS fetch failures
- [ ] Document client onboarding process
- [ ] Test token refresh flow

## Summary

**Shared Audience Strategy:**
- ✅ Simple to configure
- ✅ Low latency (no token exchange)
- ✅ Works for both MCP server and API
- ✅ Secure with scope-based access control
- ✅ Uses FastMCP's built-in Auth0 provider

**Auth0 Configuration:**
- Single API: `https://graph.konnektr.io`
- Scopes: `mcp:tools`, `graph:read`, `graph:write`
- Dynamic Client Registration enabled

**MCP Server:**
- Validates tokens for `https://graph.konnektr.io` audience
- Checks for `mcp:tools` scope
- Passes same token to Graph API

**Ready to deploy!** 🚀
