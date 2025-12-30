# OIDC Proxy Assessment & Implementation Guide

## Problem Statement

### Current Auth Challenge

Your previous architecture had **one MCP server per database/resource**, each with its own Auth0 application registration. This caused:

1. **Auth0 API Rate Limits:** Too many dynamic client registrations
2. **Management Overhead:** One app per customer deployment
3. **Cost:** Auth0 pricing based on active applications
4. **Complexity:** Hard to audit and maintain

### Current Solution

Centralized MCP server with `resource_id` routing:
- ✅ Single MCP endpoint
- ✅ Reduced Auth0 API calls
- ❌ Still uses **Dynamic Client Registration** (DCR)
- ❌ One Auth0 app per agent/client

## FastMCP OIDC Proxy Overview

FastMCP's OIDC Proxy feature (https://gofastmcp.com/servers/auth/oidc-proxy) provides:

### Architecture

```
┌────────────────────────────────────────────────────────────┐
│                     AI Agent                               │
└───────────────────────┬────────────────────────────────────┘
                        │
                        │ 1. MCP connection request
                        │
┌───────────────────────▼────────────────────────────────────┐
│              OIDC Proxy (Separate Service)                 │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  Auth Flow Handling                                 │   │
│  │  • OAuth 2.1 Device Code Flow / PKCE                │   │
│  │  • User authenticates with Auth0                    │   │
│  │  • Proxy exchanges code for tokens                  │   │
│  │  • Stores session in Redis                          │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  Token Management                                   │   │
│  │  • Maps MCP session -> OAuth tokens                 │   │
│  │  • Handles token refresh automatically              │   │
│  │  • Injects fresh tokens into MCP requests           │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│         Single Auth0 Application: "Konnektr MCP"           │
└───────────────────────┬────────────────────────────────────┘
                        │
                        │ 2. MCP request + injected token
                        │
┌───────────────────────▼────────────────────────────────────┐
│              MCP Server (Your Server)                      │
│  • Receives request with valid OAuth token                 │
│  • No auth logic needed (trust proxy)                      │
│  • Routes based on resource_id as before                   │
└────────────────────────────────────────────────────────────┘
```

### Key Features

1. **Single Auth0 Application:**
   - No more dynamic client registration
   - One app serves all agents/clients
   - Dramatically reduces Auth0 costs

2. **Token Lifecycle Management:**
   - Automatic refresh
   - Secure storage in Redis
   - Session-based access

3. **User Authentication:**
   - Device Code Flow for CLI tools
   - PKCE for web apps
   - Supports standard OAuth 2.1

4. **State Storage:**
   - Redis for session-to-token mapping
   - Shared across proxy instances (scalable)
   - TTL-based cleanup

## Should You Use OIDC Proxy?

### Pros

#### ✅ Major Benefits

1. **Single Auth0 App Registration**
   - Eliminates DCR overhead
   - One app for all clients: `konnektr-mcp-proxy`
   - Reduces Auth0 costs significantly

2. **Better User Experience**
   - Users authenticate once per session
   - Automatic token refresh (transparent)
   - No manual token management

3. **Simplified MCP Server**
   - Remove Auth0TokenVerifier
   - Remove JWKS fetching
   - Trust proxy-injected tokens

4. **Centralized Auth Logic**
   - One place to update auth flows
   - Easier to add MFA, SSO, etc.
   - Audit logging in one place

5. **Scalability**
   - Redis-backed session storage
   - Proxy scales independently of MCP server
   - Shared state across instances

### Cons

#### ❌ Drawbacks

1. **Additional Infrastructure**
   - Requires Redis deployment
   - Another service to monitor/maintain
   - Added complexity in deployment

2. **Session Management Overhead**
   - Redis storage costs
   - Session expiry handling
   - Redis availability = auth availability

3. **Increased Latency**
   - Extra hop through proxy
   - Redis lookup per request
   - Network overhead

4. **Security Considerations**
   - Proxy becomes high-value target
   - Redis contains sensitive tokens
   - Need to secure proxy<->MCP communication

5. **Operational Complexity**
   - More moving parts
   - Redis backup/restore
   - Proxy configuration management

## Recommendation

### Use OIDC Proxy If:

✅ You have **many agents/clients** (hundreds to thousands)
✅ Dynamic Client Registration is causing Auth0 rate limits
✅ You're already using Redis for other purposes
✅ You want centralized auth audit logging
✅ User experience (token refresh) is important

### Stick with Current Approach If:

✅ You have **few agents/clients** (dozens)
✅ Auth0 rate limits are not an issue
✅ Want to minimize infrastructure dependencies
✅ Prefer stateless architecture
✅ Direct token validation is acceptable

### Hybrid Approach (Recommended for Growth)

**Phase 1 (Now):** Current architecture
- Centralized MCP server with resource_id
- Direct Auth0 validation
- Minimal infrastructure

**Phase 2 (When scale demands):** Add OIDC Proxy
- Deploy proxy in front of MCP server
- Migrate clients gradually
- Support both auth methods temporarily

**Phase 3 (Long-term):** Full OIDC Proxy
- All clients use proxy
- Remove Auth0 validation from MCP server
- Simplified codebase

## Implementation Guide

If you decide to implement OIDC Proxy, here's how:

### 1. Deploy Redis

```yaml
# redis-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: redis
spec:
  replicas: 1
  selector:
    matchLabels:
      app: redis
  template:
    metadata:
      labels:
        app: redis
    spec:
      containers:
      - name: redis
        image: redis:7-alpine
        ports:
        - containerPort: 6379
        volumeMounts:
        - name: redis-data
          mountPath: /data
      volumes:
      - name: redis-data
        persistentVolumeClaim:
          claimName: redis-pvc
---
apiVersion: v1
kind: Service
metadata:
  name: redis
spec:
  selector:
    app: redis
  ports:
  - port: 6379
    targetPort: 6379
```

### 2. Configure OIDC Proxy

```python
# oidc_proxy.py
from mcp.server.auth.oidc_proxy import OIDCProxy

proxy = OIDCProxy(
    # Auth0 Configuration
    issuer_url="https://your-tenant.auth0.com/",
    client_id="your-single-app-client-id",
    client_secret="your-client-secret",  # From Auth0
    redirect_uri="http://localhost:8081/callback",  # Or your public URL

    # MCP Server to proxy to
    upstream_url="http://localhost:8080",

    # Redis for session storage
    redis_url="redis://localhost:6379/0",
    session_ttl_seconds=3600 * 24,  # 24 hours

    # Scopes to request
    scopes=["openid", "profile", "mcp:tools"],
)

# Run proxy
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(proxy.app, host="0.0.0.0", port=8081)
```

### 3. Update Auth0 Application

In Auth0, configure the single application:

```
Name: Konnektr MCP Proxy
Application Type: Native
Allowed Callback URLs: http://localhost:8081/callback, https://mcp-proxy.graph.konnektr.io/callback
Grant Types: Authorization Code, Refresh Token, Device Code
```

### 4. Modify MCP Server

Remove Auth0 validation (proxy handles it):

```python
# server.py - BEFORE (current)
mcp = FastMCP(
    name="Konnektr Graph",
    token_verifier=Auth0TokenVerifier(),  # ← Remove this
    auth=AuthSettings(...)  # ← Remove this
)

# server.py - AFTER (with OIDC Proxy)
mcp = FastMCP(
    name="Konnektr Graph",
    # No token_verifier - trust the proxy!
)
```

### 5. Deployment Architecture

```
[Internet]
      │
      ▼
[Load Balancer: mcp-proxy.graph.konnektr.io]
      │
      ▼
[OIDC Proxy Pods]
      │
      │ (injected token)
      ▼
[MCP Server Pods]
      │
      ▼
[API Pods]
```

### 6. Client Configuration

```json
{
  "mcpServers": {
    "konnektr-graph": {
      "type": "http",
      "url": "https://mcp-proxy.graph.konnektr.io/mcp?resource_id=my-graph",
      "auth": {
        "type": "oauth",
        "flow": "device_code"
      }
    }
  }
}
```

## Security Considerations

### 1. Secure Proxy ↔ MCP Server Communication

**Option A: Network Isolation**
```
OIDC Proxy and MCP Server in same VPC
No public internet between them
```

**Option B: Mutual TLS**
```
OIDC Proxy presents client certificate
MCP Server validates certificate
```

**Option C: Shared Secret**
```
Proxy adds: X-Proxy-Secret: <shared-secret>
MCP validates header presence
```

### 2. Redis Security

```yaml
# Use TLS for Redis connection
redis_url: "rediss://redis:6379/0?ssl_cert_reqs=required"

# Enable Redis AUTH
requirepass: "your-redis-password"

# Network policy: Only proxy can access Redis
```

### 3. Token Encryption

Store tokens encrypted in Redis:

```python
from cryptography.fernet import Fernet

cipher = Fernet(ENCRYPTION_KEY)

# Store
encrypted_token = cipher.encrypt(token.encode())
redis.set(session_id, encrypted_token)

# Retrieve
encrypted_token = redis.get(session_id)
token = cipher.decrypt(encrypted_token).decode()
```

### 4. Session Fixation Protection

```python
# Rotate session ID after auth
old_session_id = request.session_id
new_session_id = generate_session_id()

# Copy session data
redis.rename(old_session_id, new_session_id)

# Return new session ID to client
```

## Cost Analysis

### Current Architecture (Direct Auth0)

**Assumptions:**
- 100 agents/clients
- Each client creates dynamic Auth0 app
- Auth0 charges per active application

**Costs:**
- Auth0: ~$100/month (100 apps × $1/app)
- Infrastructure: $50/month (MCP server)
- **Total: ~$150/month**

### With OIDC Proxy

**Assumptions:**
- 100 agents/clients
- Single Auth0 app for all clients
- Redis required for session storage

**Costs:**
- Auth0: ~$20/month (1 app + API calls)
- Infrastructure: $50/month (MCP server)
- Redis: $30/month (managed Redis with backups)
- OIDC Proxy: $30/month (additional pods)
- **Total: ~$130/month**

**Savings:** ~$20/month for 100 clients

### Break-Even Point

OIDC Proxy becomes cost-effective at ~**50+ agents/clients**.

### At Scale (1000 clients)

**Current Architecture:**
- Auth0: ~$1000/month (dynamic apps)
- Infrastructure: $100/month (scaled MCP)
- **Total: ~$1100/month**

**With OIDC Proxy:**
- Auth0: ~$50/month (API calls)
- Infrastructure: $100/month (MCP server)
- Redis: $100/month (scaled Redis cluster)
- OIDC Proxy: $100/month (scaled pods)
- **Total: ~$350/month**

**Savings:** ~$750/month at 1000 clients (68% reduction)

## Performance Impact

### Latency Comparison

**Current (Direct Auth0):**
```
Agent → MCP Server (JWKS cached) → API Pod
        ↑ 5ms                       ↑ 50ms
Total: 55ms
```

**With OIDC Proxy:**
```
Agent → OIDC Proxy → MCP Server → API Pod
        ↑ 2ms Redis   ↑ 0ms (no   ↑ 50ms
        lookup        auth check)
Total: 52ms
```

**Impact:** Roughly equal (Redis lookup vs JWKS validation)

### Throughput

**Current:**
- Limited by JWKS validation CPU
- ~1000 req/sec per MCP pod

**With Proxy:**
- Limited by Redis throughput
- Redis can handle 100k+ ops/sec
- Proxy pods scale independently
- ~2000 req/sec (better scalability)

## Migration Path

### Step 1: Parallel Deployment (Week 1)

Deploy OIDC Proxy alongside existing setup:

```
Agents → [OIDC Proxy] → MCP Server (validates tokens)
Agents → MCP Server (validates tokens directly)
```

Both paths work simultaneously.

### Step 2: Pilot Testing (Week 2-3)

Migrate 10% of clients to proxy:

```json
// Old clients
"url": "https://mcp.graph.konnektr.io/mcp?resource_id=xyz"

// Pilot clients
"url": "https://mcp-proxy.graph.konnektr.io/mcp?resource_id=xyz"
```

### Step 3: Gradual Migration (Week 4-8)

- 25% of clients to proxy
- 50% of clients to proxy
- 75% of clients to proxy
- Monitor metrics, adjust capacity

### Step 4: Full Cutover (Week 9)

All clients use proxy, remove Auth0 validation from MCP server.

### Step 5: Cleanup (Week 10)

- Delete old Auth0 dynamic apps
- Remove Auth0TokenVerifier code
- Update documentation

## Monitoring & Debugging

### Key Metrics

**OIDC Proxy:**
- Auth flow success rate
- Token refresh success rate
- Redis connection errors
- Session expiry rate
- Latency per request

**Redis:**
- Memory usage
- Keys count
- Commands per second
- Hit rate

### Debugging Tools

```bash
# Check Redis sessions
redis-cli KEYS "session:*" | wc -l

# Inspect session
redis-cli GET "session:abc123"

# Monitor Redis in real-time
redis-cli MONITOR

# Check proxy logs
kubectl logs -f deployment/oidc-proxy
```

## Conclusion

### For Konnektr Graph MCP Server

**Recommendation:** **Start without OIDC Proxy, add later when needed.**

**Reasoning:**
1. Your current centralized architecture already solves the main problem (too many Auth0 apps per resource)
2. OIDC Proxy adds operational complexity (Redis, another service)
3. You can add it later without breaking clients (gradual migration)
4. Let your scale dictate when to add it (>50 agents = good time)

**When to Revisit:**
- Auth0 costs become significant (>$100/month)
- You want better user experience (auto token refresh)
- You're already using Redis for other purposes
- You need centralized auth audit logs

### Implementation Priority: **LOW → MEDIUM**

Focus first on:
1. ✅ Core MCP functionality (done)
2. ✅ Resource routing (done)
3. ⏳ Production hardening (monitoring, logging)
4. ⏳ Performance optimization
5. 🔮 OIDC Proxy (future optimization)

The architecture is designed to add OIDC Proxy seamlessly when the time comes.
