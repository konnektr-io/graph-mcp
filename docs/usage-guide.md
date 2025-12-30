# Usage Guide: AI Agent Memory with Konnektr Graph

## Overview

Konnektr Graph provides **validated, schema-enforced memory** for AI agents using Digital Twins Definition Language (DTDL). Unlike simple key-value stores or unstructured databases, Konnektr ensures all stored information conforms to predefined schemas, creating a **semantic knowledge graph** that agents can trust and query intelligently.

## Core Concepts

### 1. DTDL Models (Schemas)

Models define the structure of your data using DTDL v3:

```json
{
  "@id": "dtmi:example:Memory;1",
  "@type": "Interface",
  "displayName": "Agent Memory",
  "contents": [
    {
      "@type": "Property",
      "name": "content",
      "schema": "string"
    },
    {
      "@type": "Property",
      "name": "timestamp",
      "schema": "dateTime"
    },
    {
      "@type": "Property",
      "name": "importance",
      "schema": "integer"
    },
    {
      "@type": "Relationship",
      "name": "relatedTo",
      "target": "dtmi:example:Memory;1"
    }
  ]
}
```

**Key Features:**
- Strongly typed properties
- Required vs optional fields
- Inheritance between models
- Relationship definitions

### 2. Digital Twins (Data Instances)

Twins are instances conforming to models:

```json
{
  "$dtId": "memory-001",
  "$metadata": {
    "$model": "dtmi:example:Memory;1"
  },
  "content": "User prefers dark mode in applications",
  "timestamp": "2024-01-15T10:30:00Z",
  "importance": 8
}
```

### 3. Relationships (Connections)

Link related twins to build a knowledge graph:

```json
{
  "$relationshipId": "rel-001",
  "$sourceId": "memory-001",
  "$targetId": "memory-002",
  "$relationshipName": "relatedTo"
}
```

### 4. Semantic Search

Find information by meaning, not just keywords:

```
Query: "user interface preferences"
Matches:
  - "User prefers dark mode" (high similarity)
  - "UI should be minimalist" (medium similarity)
  - "Color scheme is important" (lower similarity)
```

## Typical Workflows

### Workflow 1: Initial Setup (Understanding Available Schemas)

```python
# Agent explores what types of data can be stored

# 1. List all available models
models = await list_models()
# Returns: [{"id": "dtmi:example:Memory;1", "displayName": "Agent Memory"}, ...]

# 2. Search for relevant models
results = await search_models(search_text="conversation")
# Finds models related to conversations

# 3. Get full model details
model = await get_model(model_id="dtmi:example:Memory;1")
# Returns complete schema with all properties and relationships
```

**When to use:**
- Agent first connects to graph
- Exploring unfamiliar knowledge domains
- Before storing new types of data

### Workflow 2: Storing New Information (Create Memory)

```python
# Agent learns something new and wants to store it

# 1. Identify the appropriate model
models = await search_models(search_text="user preference")
model_id = models[0]["id"]

# 2. Create a digital twin
twin = {
    "$metadata": {"$model": model_id},
    "content": "User prefers concise responses without extra explanations",
    "timestamp": "2024-01-15T10:30:00Z",
    "importance": 9,
    "category": "communication_style"
}

result = await create_or_replace_digital_twin(
    twin_id="pref-communication-001",
    twin=twin
)
```

**Validation happens automatically:**
- ✅ All required properties present → Success
- ❌ Missing required property → Error with details
- ❌ Wrong property type → Error with details
- ❌ Extra properties not in schema → Error

### Workflow 3: Finding Relevant Information (Memory Retrieval)

```python
# Agent needs to recall information

# Option A: Semantic search (best for concepts)
results = await search_digital_twins(
    search_text="how does the user like to communicate",
    limit=5
)
# Returns twins semantically similar to query

# Option B: Model-filtered search
results = await search_digital_twins(
    search_text="preferences",
    model_id="dtmi:example:UserPreference;1",
    limit=10
)
# Returns only twins of specific type

# Option C: Structured query (best for precise filtering)
results = await query_digital_twins(
    query="SELECT * FROM digitaltwins WHERE importance > 7"
)
# SQL-like queries for complex conditions
```

### Workflow 4: Updating Existing Information

```python
# Agent learns new details or corrections

# Option A: Partial update (JSON Patch)
await update_digital_twin(
    twin_id="pref-communication-001",
    patch=[
        {"op": "replace", "path": "/importance", "value": 10},
        {"op": "add", "path": "/notes", "value": "Very strongly expressed"}
    ]
)

# Option B: Full replacement
updated_twin = {
    "$metadata": {"$model": "dtmi:example:UserPreference;1"},
    "content": "User prefers detailed technical explanations with code examples",
    "timestamp": "2024-01-16T14:20:00Z",
    "importance": 10
}

await create_or_replace_digital_twin(
    twin_id="pref-communication-001",
    twin=updated_twin
)
```

### Workflow 5: Building Connections (Knowledge Graph)

```python
# Agent connects related memories

# 1. Create individual memories
await create_or_replace_digital_twin(
    twin_id="conv-001",
    twin={
        "$metadata": {"$model": "dtmi:example:Conversation;1"},
        "topic": "Python async programming",
        "date": "2024-01-15"
    }
)

await create_or_replace_digital_twin(
    twin_id="code-001",
    twin={
        "$metadata": {"$model": "dtmi:example:CodeSnippet;1"},
        "language": "python",
        "code": "async def fetch(): ..."
    }
)

# 2. Create relationship
await create_or_replace_relationship(
    source_twin_id="conv-001",
    relationship_id="rel-conv-code-001",
    relationship={
        "$relationshipName": "discussed",
        "$targetId": "code-001",
        "context": "Example provided during explanation"
    }
)

# 3. Query graph
results = await query_digital_twins(
    query="""
    SELECT conversation, code
    FROM RELATIONSHIPS
    WHERE conversation.$dtId = 'conv-001'
    AND $relationshipName = 'discussed'
    """
)
```

### Workflow 6: Graph Exploration (Following Connections)

```python
# Agent explores related information

# 1. Start with known twin
twin = await get_digital_twin(twin_id="conv-001")

# 2. Find all outgoing relationships
relationships = await list_relationships(
    twin_id="conv-001"
)

# 3. Optional: Filter by relationship type
code_relationships = await list_relationships(
    twin_id="conv-001",
    relationship_name="discussed"
)

# 4. Fetch related twins
for rel in code_relationships:
    target_twin = await get_digital_twin(twin_id=rel["$targetId"])
    # Process related twin
```

## Use Case Examples

### Use Case 1: Conversational Agent with Long-Term Memory

**Scenario:** Agent needs to remember user preferences across sessions.

**Schema:**

```json
{
  "@id": "dtmi:agent:UserPreference;1",
  "@type": "Interface",
  "displayName": "User Preference",
  "contents": [
    {
      "@type": "Property",
      "name": "category",
      "schema": "string"
    },
    {
      "@type": "Property",
      "name": "preference",
      "schema": "string"
    },
    {
      "@type": "Property",
      "name": "confidence",
      "schema": "double"
    },
    {
      "@type": "Property",
      "name": "learnedFrom",
      "schema": "string"
    }
  ]
}
```

**Agent Behavior:**

```python
async def remember_preference(category: str, preference: str, confidence: float):
    """Store new preference"""
    twin_id = f"pref-{category}-{hash(preference)}"

    await create_or_replace_digital_twin(
        twin_id=twin_id,
        twin={
            "$metadata": {"$model": "dtmi:agent:UserPreference;1"},
            "category": category,
            "preference": preference,
            "confidence": confidence,
            "learnedFrom": "conversation"
        }
    )

async def recall_preferences(query: str) -> list:
    """Retrieve relevant preferences"""
    return await search_digital_twins(
        search_text=query,
        model_id="dtmi:agent:UserPreference;1",
        limit=5
    )

# Usage
await remember_preference(
    category="communication",
    preference="Prefers technical depth over simplicity",
    confidence=0.9
)

preferences = await recall_preferences("how to respond to technical questions")
```

### Use Case 2: Task Management with Dependencies

**Scenario:** Agent tracks tasks and their dependencies.

**Schema:**

```json
{
  "@id": "dtmi:agent:Task;1",
  "@type": "Interface",
  "displayName": "Task",
  "contents": [
    {
      "@type": "Property",
      "name": "title",
      "schema": "string"
    },
    {
      "@type": "Property",
      "name": "status",
      "schema": {
        "@type": "Enum",
        "valueSchema": "string",
        "enumValues": [
          {"name": "pending"},
          {"name": "in_progress"},
          {"name": "completed"}
        ]
      }
    },
    {
      "@type": "Relationship",
      "name": "dependsOn",
      "target": "dtmi:agent:Task;1"
    }
  ]
}
```

**Agent Behavior:**

```python
async def create_task(task_id: str, title: str, depends_on: list[str] = None):
    """Create task with dependencies"""

    # Create task twin
    await create_or_replace_digital_twin(
        twin_id=task_id,
        twin={
            "$metadata": {"$model": "dtmi:agent:Task;1"},
            "title": title,
            "status": "pending"
        }
    )

    # Create dependency relationships
    if depends_on:
        for dep_task_id in depends_on:
            await create_or_replace_relationship(
                source_twin_id=task_id,
                relationship_id=f"dep-{task_id}-{dep_task_id}",
                relationship={
                    "$relationshipName": "dependsOn",
                    "$targetId": dep_task_id
                }
            )

async def get_ready_tasks() -> list:
    """Find tasks with no incomplete dependencies"""
    query = """
    SELECT task
    FROM digitaltwins task
    WHERE task.status = 'pending'
    AND NOT EXISTS (
        SELECT * FROM RELATIONSHIPS dep
        WHERE dep.$sourceId = task.$dtId
        AND dep.$relationshipName = 'dependsOn'
        AND dep.$targetId IN (
            SELECT incomplete.$dtId FROM digitaltwins incomplete
            WHERE incomplete.status != 'completed'
        )
    )
    """
    return await query_digital_twins(query)
```

### Use Case 3: Knowledge Base with Sources

**Scenario:** Agent builds knowledge base with citations.

**Schema:**

```json
{
  "@id": "dtmi:agent:Fact;1",
  "@type": "Interface",
  "contents": [
    {"@type": "Property", "name": "statement", "schema": "string"},
    {"@type": "Property", "name": "confidence", "schema": "double"},
    {"@type": "Relationship", "name": "sourcedFrom", "target": "dtmi:agent:Source;1"}
  ]
}
```

**Agent Behavior:**

```python
async def store_fact(fact: str, source_id: str, confidence: float):
    """Store fact with source citation"""
    fact_id = f"fact-{hash(fact)}"

    # Store fact
    await create_or_replace_digital_twin(
        twin_id=fact_id,
        twin={
            "$metadata": {"$model": "dtmi:agent:Fact;1"},
            "statement": fact,
            "confidence": confidence
        }
    )

    # Link to source
    await create_or_replace_relationship(
        source_twin_id=fact_id,
        relationship_id=f"source-{fact_id}-{source_id}",
        relationship={
            "$relationshipName": "sourcedFrom",
            "$targetId": source_id
        }
    )

async def verify_fact(fact_query: str) -> dict:
    """Find fact and check its sources"""
    # Find similar facts
    facts = await search_digital_twins(search_text=fact_query, limit=1)

    if not facts:
        return {"verified": False, "reason": "No matching fact found"}

    fact = facts[0]
    fact_id = fact["$dtId"]

    # Get sources
    relationships = await list_relationships(
        twin_id=fact_id,
        relationship_name="sourcedFrom"
    )

    sources = []
    for rel in relationships:
        source = await get_digital_twin(twin_id=rel["$targetId"])
        sources.append(source)

    return {
        "verified": len(sources) > 0,
        "fact": fact["statement"],
        "confidence": fact["confidence"],
        "sources": sources
    }
```

## Error Handling Patterns

### Pattern 1: Graceful Schema Validation

```python
async def store_safely(twin_id: str, data: dict, model_id: str):
    """Attempt to store with helpful error feedback"""
    try:
        # Get model to understand requirements
        model = await get_model(model_id=model_id)

        # Add metadata
        data["$metadata"] = {"$model": model_id}

        # Attempt creation
        return await create_or_replace_digital_twin(
            twin_id=twin_id,
            twin=data
        )

    except ValidationError as e:
        # Parse error to understand what's wrong
        print(f"Validation failed: {e}")
        print(f"Required properties: {model['contents']}")

        # Agent can adjust and retry
        return None
```

### Pattern 2: Idempotent Operations

```python
async def ensure_twin_exists(twin_id: str, twin_data: dict):
    """Create or update twin idempotently"""
    try:
        # Try to get existing
        existing = await get_digital_twin(twin_id=twin_id)

        # Update if exists
        await update_digital_twin(
            twin_id=twin_id,
            patch=[{"op": "replace", "path": "/...", "value": "..."}]
        )

    except NotFoundError:
        # Create if doesn't exist
        await create_or_replace_digital_twin(
            twin_id=twin_id,
            twin=twin_data
        )
```

### Pattern 3: Search with Fallback

```python
async def find_or_create(search_query: str, default_data: dict):
    """Find existing or create new"""
    # Try to find existing
    results = await search_digital_twins(
        search_text=search_query,
        limit=1
    )

    if results and len(results) > 0:
        return results[0]

    # Create new if not found
    twin_id = f"auto-{hash(search_query)}"
    return await create_or_replace_digital_twin(
        twin_id=twin_id,
        twin=default_data
    )
```

## Best Practices

### 1. Model Design

**DO:**
- ✅ Use descriptive model IDs: `dtmi:company:domain:Type;1`
- ✅ Add display names and descriptions in multiple languages
- ✅ Define relationships explicitly in models
- ✅ Use enums for fixed value sets
- ✅ Version models properly (increment version number)

**DON'T:**
- ❌ Store unstructured JSON in string properties
- ❌ Use generic property names like "data" or "info"
- ❌ Create models for every slight variation
- ❌ Skip required properties

### 2. Twin Management

**DO:**
- ✅ Use meaningful twin IDs: `user-pref-123`, `task-2024-001`
- ✅ Include timestamps for time-based queries
- ✅ Store embeddings for semantic search
- ✅ Clean up obsolete twins

**DON'T:**
- ❌ Use random UUIDs as IDs (hard to debug)
- ❌ Store large blobs (>1MB) in properties
- ❌ Create thousands of orphaned twins
- ❌ Duplicate data across twins

### 3. Search Optimization

**DO:**
- ✅ Use semantic search for concept-based retrieval
- ✅ Filter by model_id to narrow results
- ✅ Limit results to what you'll actually use
- ✅ Cache frequently accessed twins

**DON'T:**
- ❌ Search for exact IDs (use get_digital_twin instead)
- ❌ Request huge limits (>100)
- ❌ Search without any context
- ❌ Ignore search rankings

### 4. Graph Structure

**DO:**
- ✅ Create bidirectional relationships when needed
- ✅ Use descriptive relationship names
- ✅ Add properties to relationships (context, weight, etc.)
- ✅ Design for common query patterns

**DON'T:**
- ❌ Create circular dependencies without purpose
- ❌ Use relationships as properties
- ❌ Create dense graphs (one twin connected to thousands)
- ❌ Forget to delete relationships before deleting twins

## Performance Considerations

### Latency Budget

Typical operation times:
- Create/Update twin: 50-100ms
- Get twin by ID: 20-50ms
- Semantic search: 100-200ms
- Complex query: 200-500ms

### Batch Operations

```python
# SLOW: Sequential creation
for item in items:
    await create_or_replace_digital_twin(...)

# FAST: Parallel creation (if order doesn't matter)
import asyncio
tasks = [create_or_replace_digital_twin(...) for item in items]
results = await asyncio.gather(*tasks)
```

### Caching Strategy

```python
from functools import lru_cache

# Cache models (rarely change)
@lru_cache(maxsize=100)
async def get_model_cached(model_id: str):
    return await get_model(model_id=model_id)

# Don't cache twins (frequently change)
# Always fetch fresh:
twin = await get_digital_twin(twin_id=twin_id)
```

## Troubleshooting

### Issue: "Property X is required"

**Cause:** Twin missing required property from model.

**Solution:**
```python
# Get model to see requirements
model = await get_model(model_id="dtmi:example:Type;1")
required_props = [
    c["name"] for c in model["contents"]
    if c.get("@type") == "Property" and not c.get("writable") == False
]
print(f"Required: {required_props}")
```

### Issue: "Relationship type not allowed"

**Cause:** Relationship not defined in source model.

**Solution:**
```python
# Check model for allowed relationships
model = await get_model(model_id=source_twin_model)
relationships = [
    c for c in model["contents"]
    if c.get("@type") == "Relationship"
]
print(f"Allowed relationships: {[r['name'] for r in relationships]}")
```

### Issue: Search returns no results

**Possible causes:**
- No twins match the semantic query
- Model filter too restrictive
- Twins don't have embeddings

**Solution:**
```python
# Broaden search
results = await search_digital_twins(
    search_text=query,
    # Remove model_id filter
    limit=20  # Increase limit
)

# Or use query instead
results = await query_digital_twins(
    query="SELECT * FROM digitaltwins"
)
```

## Next Steps

- **Production Setup:** See [deployment.md](./deployment.md)
- **Security:** See [security.md](./security.md)
- **Architecture:** See [architecture.md](./architecture.md)
- **OIDC Proxy:** See [oidc-proxy.md](./oidc-proxy.md)
