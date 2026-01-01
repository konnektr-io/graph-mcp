# Health Checks Documentation

## Overview

The Konnektr Graph MCP Server implements comprehensive health checks designed for Kubernetes environments, following best practices for container orchestration.

## Available Endpoints

### 1. `/healthz` - Liveness Probe

**Purpose:** Kubernetes liveness probe to detect if the application is alive or hung.

**Response (Success - 200):**
```json
{
  "status": "alive",
  "version": "0.1.0"
}
```

**What it checks:**
- Application process is running and responsive
- Simple ping response (minimal overhead)

**Kubernetes behavior:**
- If failing: **Restart the pod**
- Use for: Detecting deadlocks, hung processes

**Configuration:**
```yaml
livenessProbe:
  httpGet:
    path: /healthz
    port: 8080
  initialDelaySeconds: 10
  periodSeconds: 30
  timeoutSeconds: 5
  failureThreshold: 3  # Restart after 3 failures (90 seconds)
```

### 2. `/readyz` - Readiness Probe

**Purpose:** Kubernetes readiness probe to detect if the application can serve traffic.

**Response (Success - 200):**
```json
{
  "status": "ready",
  "version": "0.1.0",
  "auth_enabled": true
}
```

**Response (Not Ready - 503):**
```json
{
  "status": "not_ready",
  "reason": "MCP session manager not running"
}
```

**What it checks:**
- MCP session manager is running
- Configuration is loaded
- Application dependencies are available

**Kubernetes behavior:**
- If failing: **Remove from load balancer** (don't restart)
- Use for: Temporary issues, startup delays, graceful degradation

**Configuration:**
```yaml
readinessProbe:
  httpGet:
    path: /readyz
    port: 8080
  initialDelaySeconds: 5
  periodSeconds: 10
  timeoutSeconds: 3
  failureThreshold: 2  # Remove after 2 failures (20 seconds)
```

### 3. `/health` - Legacy Endpoint

**Purpose:** Backward compatibility with existing monitoring tools.

**Response:** Same as `/readyz`

**Note:** This endpoint uses readiness probe logic for comprehensive health checking.

### 4. `/ready` - Alternative Readiness Endpoint

**Purpose:** Alternative name for readiness probe (some tools prefer this naming).

**Response:** Same as `/readyz`

## Endpoint Comparison

| Endpoint | Purpose | Kubernetes Use | Failure Action | Check Depth |
|----------|---------|----------------|----------------|-------------|
| `/healthz` | Liveness | Liveness Probe | Restart Pod | Basic |
| `/readyz` | Readiness | Readiness Probe | Remove from LB | Comprehensive |
| `/ready` | Readiness | Readiness Probe | Remove from LB | Comprehensive |
| `/health` | Legacy | Either | Depends | Comprehensive |

## Kubernetes Configuration

### Complete Example

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: konnektr-mcp-server
spec:
  template:
    spec:
      containers:
      - name: mcp-server
        image: konnektr-mcp-server:latest
        ports:
        - containerPort: 8080
          name: http

        # Liveness: Restart if hung
        livenessProbe:
          httpGet:
            path: /healthz
            port: http
          initialDelaySeconds: 10
          periodSeconds: 30
          timeoutSeconds: 5
          failureThreshold: 3

        # Readiness: Remove from LB if not ready
        readinessProbe:
          httpGet:
            path: /readyz
            port: http
          initialDelaySeconds: 5
          periodSeconds: 10
          timeoutSeconds: 3
          failureThreshold: 2

        # Startup: Give time to start before liveness checks
        startupProbe:
          httpGet:
            path: /healthz
            port: http
          periodSeconds: 5
          failureThreshold: 12  # 60 seconds total
```

## Testing Health Endpoints

### Local Testing

```bash
# Start server
uvicorn konnektr_mcp.server:app --port 8080

# Test liveness
curl http://localhost:8080/healthz
# Expected: {"status":"alive","version":"0.1.0"}

# Test readiness
curl http://localhost:8080/readyz
# Expected: {"status":"ready","version":"0.1.0","auth_enabled":false}

# Test with verbose output
curl -v http://localhost:8080/readyz
# Should see: HTTP/1.1 200 OK
```

### Kubernetes Testing

```bash
# From within cluster
kubectl run -it --rm debug --image=curlimages/curl --restart=Never -- \
  curl http://konnektr-mcp-server/healthz

# From inside a pod
kubectl exec -it deployment/konnektr-mcp-server -- \
  curl http://localhost:8080/readyz

# Port forward and test
kubectl port-forward svc/konnektr-mcp-server 8080:80
curl http://localhost:8080/healthz
```

### External Testing

```bash
# Test via ingress (production)
curl https://mcp.graph.konnektr.io/healthz
curl https://mcp.graph.konnektr.io/readyz

# Check response time
time curl https://mcp.graph.konnektr.io/healthz

# Watch continuously
watch -n 5 'curl -s https://mcp.graph.konnektr.io/readyz | jq'
```

## Troubleshooting

### Readiness Probe Failing

**Symptoms:**
- Pod shows 0/1 Ready
- No traffic being sent to pod
- `/readyz` returns 503

**Common Causes:**

1. **MCP session manager not started**
   ```bash
   kubectl logs <pod-name> | grep "session manager"
   ```

2. **Configuration error**
   ```bash
   kubectl exec -it <pod-name> -- env | grep AUTH0
   ```

3. **Port not listening**
   ```bash
   kubectl exec -it <pod-name> -- netstat -tlnp | grep 8080
   ```

**Fix:**
```bash
# Check logs
kubectl logs <pod-name>

# Describe pod
kubectl describe pod <pod-name>

# Check environment
kubectl exec -it <pod-name> -- env
```

### Liveness Probe Failing

**Symptoms:**
- Pod constantly restarting
- CrashLoopBackOff status
- `/healthz` returns no response or 5xx

**Common Causes:**

1. **Application deadlock/hang**
   - Check logs for errors
   - Increase timeout if slow startup

2. **Resource exhaustion**
   ```bash
   kubectl top pod <pod-name>
   ```

3. **Too aggressive probe settings**
   - Increase `initialDelaySeconds`
   - Increase `failureThreshold`

**Fix:**
```yaml
# More lenient liveness probe
livenessProbe:
  initialDelaySeconds: 30  # Increase
  periodSeconds: 60         # Check less frequently
  timeoutSeconds: 10        # More time
  failureThreshold: 5       # More failures allowed
```

### Startup Probe Failing

**Symptoms:**
- Pod never becomes ready
- Stuck in "Starting" state
- Application needs >60s to start

**Fix:**
```yaml
# Increase startup time allowance
startupProbe:
  periodSeconds: 10
  failureThreshold: 30  # 300 seconds total
```

## Best Practices

### 1. Separate Liveness and Readiness

**DO:**
```yaml
livenessProbe:
  httpGet:
    path: /healthz  # Simple check
readinessProbe:
  httpGet:
    path: /readyz   # Comprehensive check
```

**DON'T:**
```yaml
livenessProbe:
  httpGet:
    path: /readyz   # Too complex for liveness
```

**Why:** Liveness should be simple to avoid false restarts.

### 2. Use Startup Probes

**DO:**
```yaml
startupProbe:
  httpGet:
    path: /healthz
  failureThreshold: 12  # Give time to start
livenessProbe:
  httpGet:
    path: /healthz
  failureThreshold: 3   # Stricter after startup
```

**Why:** Prevents liveness probe from killing slow-starting apps.

### 3. Set Appropriate Timeouts

**DO:**
```yaml
livenessProbe:
  periodSeconds: 30      # Check every 30s
  timeoutSeconds: 5      # 5s per check
  failureThreshold: 3    # 90s total before restart
```

**DON'T:**
```yaml
livenessProbe:
  periodSeconds: 5       # Too frequent
  failureThreshold: 1    # Too aggressive
```

**Why:** Avoid unnecessary restarts during temporary load spikes.

### 4. Monitor Probe Success Rate

```bash
# Check pod events
kubectl get events -n konnektr-mcp --sort-by='.lastTimestamp'

# Check probe failures
kubectl describe pod <pod-name> | grep -A 10 "Liveness\|Readiness"
```

## Monitoring Integration

### Prometheus Metrics

The health endpoints can be monitored via Prometheus:

```yaml
# ServiceMonitor for Prometheus Operator
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: konnektr-mcp-health
spec:
  selector:
    matchLabels:
      app: konnektr-mcp
  endpoints:
  - port: http
    path: /readyz
    interval: 30s
```

### Alerting

Example alert rules:

```yaml
groups:
- name: konnektr-mcp
  rules:
  - alert: MCPServerNotReady
    expr: |
      kube_pod_status_ready{namespace="konnektr-mcp",condition="false"} == 1
    for: 5m
    annotations:
      summary: "MCP server pod not ready"

  - alert: MCPServerRestarting
    expr: |
      rate(kube_pod_container_status_restarts_total{namespace="konnektr-mcp"}[15m]) > 0
    annotations:
      summary: "MCP server pod restarting frequently"
```

## Performance Considerations

### Endpoint Latency

- `/healthz`: <5ms (simple check)
- `/readyz`: <20ms (comprehensive check)

### Load Impact

With default settings:
- Liveness: 1 request every 30s per pod
- Readiness: 1 request every 10s per pod
- For 10 pods: ~0.67 requests/sec total

**Negligible impact on application performance.**

### Optimization

If health checks cause issues:

1. Increase `periodSeconds` (check less frequently)
2. Cache configuration checks
3. Add request timeout to dependencies

## Docker Health Check

The Dockerfile also includes a health check:

```dockerfile
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import httpx; exit(0 if httpx.get('http://localhost:8080/readyz', timeout=2).status_code == 200 else 1)" || exit 1
```

This is used by Docker/Docker Compose but **not by Kubernetes**.

## Summary

| Check Type | Endpoint | Use Case | Failure Action |
|------------|----------|----------|----------------|
| **Liveness** | `/healthz` | Process alive | Restart pod |
| **Readiness** | `/readyz` | Can serve traffic | Remove from LB |
| **Startup** | `/healthz` | Initial startup | Wait before liveness |
| **Legacy** | `/health` | Compatibility | Same as readiness |

**Key Takeaway:** Use `/healthz` for liveness (simple), `/readyz` for readiness (comprehensive).
