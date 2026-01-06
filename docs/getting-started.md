# Getting Started with Konnektr Graph MCP Server

## What You'll Build

By the end of this guide, you'll have:
- ✅ A running MCP server locally
- ✅ Connection to your first graph instance
- ✅ Understanding of how to use it as AI agent memory

**Time:** ~15 minutes

## Prerequisites Checklist

- [ ] Python 3.12+ installed (`python --version`)
- [ ] pip installed (`pip --version`)
- [ ] Git installed (`git --version`)
- [ ] Access to a Konnektr Graph API instance
- [ ] (Optional) Auth0 account for authentication

## Step-by-Step Setup

### 1. Clone the Repository

```bash
# Clone
git clone <repository-url>
cd graph-mcp

# Verify structure
ls -la
# Should see: konnektr_mcp/, docs/, requirements.txt, etc.
```

### 2. Create Virtual Environment

```bash
# Create venv
python -m venv venv

# Activate (choose your OS)
source venv/bin/activate          # Linux/Mac
venv\Scripts\activate              # Windows CMD
venv\Scripts\Activate.ps1          # Windows PowerShell

# Verify activation
which python                       # Should show venv path
```

### 3. Install Dependencies

```bash
# Install all dependencies
pip install -r requirements.txt

# Verify installation
pip list | grep mcp
pip list | grep konnektr-graph
pip list | grep uvicorn

# Expected output:
# mcp                    1.9.0+
# konnektr-graph         0.1.2+
# uvicorn                0.30.0+
```

### 4. Configure Environment

```bash
# Copy template
cp .env.example .env

# Edit .env file
nano .env  # or your favorite editor
```

**For local development without authentication:**
```env
# Disable auth for testing
AUTH_ENABLED=false

# Point to your local API (or staging)
API_BASE_URL_TEMPLATE=http://localhost:5000
# or
API_BASE_URL_TEMPLATE=https://{resource_id}.staging.api.graph.konnektr.io

# Enable embeddings (optional but recommended)
EMBEDDING_ENABLED=true
EMBEDDING_PROVIDER=openai
OPENAI_API_KEY=sk-your-api-key
```

**For production with Auth0:**
```env
AUTH_ENABLED=true
AUTH0_DOMAIN=your-tenant.auth0.com
AUTH0_AUDIENCE=https://graph.konnektr.io
API_BASE_URL_TEMPLATE=https://{resource_id}.api.graph.konnektr.io

# Embeddings (choose one provider)
EMBEDDING_ENABLED=true
EMBEDDING_PROVIDER=openai
OPENAI_API_KEY=sk-your-api-key
# Or use Azure OpenAI:
# EMBEDDING_PROVIDER=azure_openai
# AZURE_OPENAI_API_KEY=your-key
# AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
# AZURE_OPENAI_DEPLOYMENT_NAME=text-embedding-3-small
# Or use Google Gemini:
# EMBEDDING_PROVIDER=gemini
# GOOGLE_API_KEY=your-google-api-key
```

See [embeddings.md](embeddings.md) for detailed embedding configuration.

### 5. Run the Server

```bash
# Start server with auto-reload
uvicorn konnektr_mcp.server:app --reload --port 8080

# Expected output:
# INFO:     Started server process
# INFO:     Waiting for application startup.
# INFO:     Application startup complete.
# INFO:     Uvicorn running on http://127.0.0.1:8080
```

**Troubleshooting:**
- ❌ "No module named 'konnektr_mcp'" → Check you're in correct directory
- ❌ "Port 8080 already in use" → Use different port: `--port 8081`
- ❌ Import errors → Run `pip install -r requirements.txt` again

### 6. Verify Health

Open another terminal:

```bash
# Check health endpoint
curl http://localhost:8080/health

# Expected response:
# {"status":"healthy","version":"0.1.0"}
```

### 7. Test with MCP Inspector

```bash
# Install MCP Inspector (once)
npm install -g @modelcontextprotocol/inspector

# Or use npx (no installation)
npx @modelcontextprotocol/inspector http://localhost:8080/mcp?resource_id=test
```

This opens a browser window where you can:
- See all available tools
- Test tool invocations
- View request/response payloads

**Try it:**
1. Select `list_models` tool
2. Click "Execute"
3. View results

### 8. Configure Claude Desktop (Optional)

If you want to use it with Claude:

```bash
# Find config file location
# Mac: ~/Library/Application Support/Claude/claude_desktop_config.json
# Windows: %APPDATA%\Claude\claude_desktop_config.json

# Edit config
code ~/Library/Application\ Support/Claude/claude_desktop_config.json
```

Add:
```json
{
  "mcpServers": {
    "konnektr-graph-local": {
      "type": "http",
      "url": "http://localhost:8080/mcp?resource_id=test"
    }
  }
}
```

Restart Claude Desktop, then chat:
```
You: "List all available models in my graph"
Claude: [Uses list_models tool]
```

## Your First Agent Interaction

Let's walk through a typical agent workflow:

### Scenario: Storing User Preferences

```python
# This is what happens when an agent uses the MCP tools

# 1. Agent explores available schemas
models_response = await list_models()
# Result: [{"id": "dtmi:agent:UserPreference;1", "displayName": "User Preference"}, ...]

# 2. Agent gets schema details
model = await get_model(model_id="dtmi:agent:UserPreference;1")
# Result: Full DTDL schema with properties

# 3. Agent stores preference (validated against schema)
result = await create_or_replace_digital_twin(
    twin_id="pref-001",
    twin={
        "$metadata": {"$model": "dtmi:agent:UserPreference;1"},
        "category": "communication",
        "preference": "Prefers technical depth",
        "confidence": 0.9
    }
)
# If valid: Success!
# If invalid: Error with details about what's wrong

# 4. Later, agent recalls preferences
preferences = await search_digital_twins(
    search_text="communication style preferences",
    limit=5
)
# Result: Relevant preferences ranked by similarity
```

### What Makes This Special?

**Without Konnektr Graph (typical key-value store):**
```python
# Agent can store anything
await store("pref-001", {"whatever": "data", "no": "validation"})
# ⚠️ No schema, no validation, potential data corruption
```

**With Konnektr Graph:**
```python
# Agent MUST follow schema
await create_or_replace_digital_twin("pref-001", {
    "$metadata": {"$model": "dtmi:agent:UserPreference;1"},
    # Missing required field → Clear error message
    # Wrong type → Clear error message
    # Extra fields → Clear error message
})
# ✅ Guaranteed data quality
```

## Common Workflows

### Workflow 1: Memory Storage

```
Agent learns something new
    ↓
Search for appropriate model (list_models, search_models)
    ↓
Get model details (get_model)
    ↓
Create digital twin (create_or_replace_digital_twin)
    ↓
[If validation error]
    ↓
Agent adjusts data to match schema
    ↓
Retry creation
    ↓
Success!
```

### Workflow 2: Memory Retrieval

```
Agent needs to recall information
    ↓
Semantic search (search_digital_twins)
    ↓
Get ranked results by relevance
    ↓
Agent processes top results
    ↓
[Optional] Get related twins via relationships
```

### Workflow 3: Knowledge Graph Building

```
Agent creates multiple related memories
    ↓
For each memory:
    - Create digital twin
    - Identify relationships
    - Create relationship link
    ↓
Later: Query graph (query_digital_twins)
    ↓
Get connected knowledge
```

## Quick Reference: Available Tools

### Discovery
- `list_models()` - List all schemas
- `search_models(search_text, limit)` - Find schemas by keyword

### Schema Details
- `get_model(model_id)` - Get full DTDL definition

### Data Storage
- `create_or_replace_digital_twin(twin_id, twin)` - Store validated data
- `update_digital_twin(twin_id, patch)` - Update existing data
- `delete_digital_twin(twin_id)` - Remove data

### Data Retrieval
- `get_digital_twin(twin_id)` - Get by ID
- `search_digital_twins(search_text, model_id, limit)` - Semantic search
- `query_digital_twins(query)` - SQL-like queries

### Relationships
- `list_relationships(twin_id, relationship_name)` - List connections
- `get_relationship(twin_id, relationship_id)` - Get specific connection
- `create_or_replace_relationship(...)` - Connect twins
- `update_relationship(...)` - Update connection
- `delete_relationship(...)` - Remove connection

### Model Creation
- `create_models(models)` - Create new schemas (advanced)

## Testing Your Setup

Run this checklist:

```bash
# 1. Server is running
curl http://localhost:8080/health
# ✅ Should return: {"status":"healthy","version":"0.1.0"}

# 2. MCP endpoint responds
curl http://localhost:8080/mcp?resource_id=test
# ✅ Should return MCP protocol response

# 3. Tools are available (via MCP Inspector)
npx @modelcontextprotocol/inspector http://localhost:8080/mcp?resource_id=test
# ✅ Should show all tools in browser

# 4. Can list models (if API is running)
# Use MCP Inspector to call list_models
# ✅ Should return models from your graph
```

## Troubleshooting

### Issue: "Connection refused"

**Cause:** Server not running or wrong port

**Solution:**
```bash
# Check if server is running
ps aux | grep uvicorn

# Restart server
uvicorn konnektr_mcp.server:app --reload --port 8080
```

### Issue: "AUTH0_DOMAIN not set"

**Cause:** Missing environment variable and AUTH_ENABLED=true

**Solution:**
```bash
# For local dev, disable auth
echo "AUTH_ENABLED=false" >> .env

# Or set Auth0 credentials
echo "AUTH0_DOMAIN=your-tenant.auth0.com" >> .env
```

### Issue: "No models found"

**Cause:** API instance has no models yet or API not accessible

**Solution:**
```bash
# Check API is reachable
curl https://your-resource-id.api.graph.konnektr.io/health

# Verify API_BASE_URL_TEMPLATE in .env
grep API_BASE_URL_TEMPLATE .env
```

### Issue: "Package not found: konnektr-graph"

**Cause:** Virtual environment not activated or package not installed

**Solution:**
```bash
# Activate venv
source venv/bin/activate  # or Windows equivalent

# Reinstall
pip install -r requirements.txt

# Verify
pip show konnektr-graph
```

## Next Steps

Now that you're up and running:

1. **Explore the Documentation**
   - [Usage Guide](./usage-guide.md) - Learn AI agent patterns
   - [Architecture](./architecture.md) - Understand the system
   - [Deployment](./deployment.md) - Go to production

2. **Try Real Scenarios**
   - Store user preferences
   - Build a knowledge graph
   - Implement semantic search

3. **Customize**
   - Create your own DTDL models
   - Add custom tools
   - Integrate with your app

4. **Deploy**
   - Docker container
   - Kubernetes cluster
   - Production monitoring

## Learning Resources

### DTDL (Digital Twins Definition Language)
- [DTDL v3 Spec](https://github.com/Azure/opendigitaltwins-dtdl/blob/master/DTDL/v3/DTDL.v3.md)
- [DTDL Tutorial](https://learn.microsoft.com/en-us/azure/digital-twins/concepts-models)

### MCP (Model Context Protocol)
- [MCP Documentation](https://modelcontextprotocol.io/)
- [FastMCP Guide](https://gofastmcp.com/)

### Graph Databases
- [Graph Database Concepts](https://neo4j.com/developer/graph-database/)
- [PostgreSQL AGE](https://age.apache.org/)

## Get Help

- **Documentation:** Check [docs/](../docs/) folder
- **Examples:** See [usage-guide.md](./usage-guide.md)
- **Issues:** [GitHub Issues](https://github.com/your-org/graph-mcp/issues)
- **API Docs:** [Konnektr Graph API](https://docs.graph.konnektr.io)

## Success Checklist

Before moving to production, verify:

- [ ] Server starts without errors
- [ ] Health endpoint responds
- [ ] Can connect via MCP Inspector
- [ ] Can list models from your graph
- [ ] Can create and retrieve digital twins
- [ ] Can create relationships
- [ ] Can search semantically
- [ ] Authentication works (if enabled)
- [ ] Logs are readable
- [ ] Error messages are clear

**All checked?** You're ready to integrate with your AI agent! 🎉

---

**Questions?** Check [usage-guide.md](./usage-guide.md) for detailed patterns and examples.
