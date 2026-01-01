# Kubernetes Deployment

This directory contains Kubernetes manifests for deploying the Konnektr MCP Server.

## Quick Deploy

```bash
# 1. Create namespace
kubectl create namespace konnektr-mcp

# 2. Create secrets (edit secrets.yaml first!)
kubectl apply -f secrets.yaml

# 3. Deploy application
kubectl apply -f deployment.yaml

# 4. Deploy HPA
kubectl apply -f hpa.yaml

# 5. Deploy ingress
kubectl apply -f ingress.yaml

# 6. Verify
kubectl get pods -n konnektr-mcp
kubectl get svc -n konnektr-mcp
kubectl get ingress -n konnektr-mcp
```

## Files

- **deployment.yaml** - Main deployment with proper health checks
- **secrets.yaml** - Auth0 configuration (template)
- **hpa.yaml** - Horizontal Pod Autoscaler
- **ingress.yaml** - NGINX ingress configuration

## Health Checks

The deployment includes three types of health checks:

### 1. Liveness Probe (`/healthz`)

**Purpose:** Detect if the application is alive or hung
**Action:** Restart pod if failing

```yaml
livenessProbe:
  httpGet:
    path: /healthz
    port: http
  initialDelaySeconds: 10
  periodSeconds: 30
  failureThreshold: 3
```

**What it checks:**
- Application process is running
- Simple ping response

### 2. Readiness Probe (`/readyz`)

**Purpose:** Detect if the application is ready to serve traffic
**Action:** Remove from load balancer if failing (don't restart)

```yaml
readinessProbe:
  httpGet:
    path: /readyz
    port: http
  initialDelaySeconds: 5
  periodSeconds: 10
  failureThreshold: 2
```

**What it checks:**
- MCP session manager is running
- Configuration is loaded
- Application can accept requests

### 3. Startup Probe (`/healthz`)

**Purpose:** Give application time to start before liveness checks begin
**Action:** Wait for startup before beginning liveness checks

```yaml
startupProbe:
  httpGet:
    path: /healthz
    port: http
  periodSeconds: 5
  failureThreshold: 12  # 60 seconds total
```

## Testing Health Endpoints

```bash
# Inside a pod
kubectl exec -it deployment/konnektr-mcp-server -n konnektr-mcp -- \
  curl http://localhost:8080/healthz

# {"status":"alive","version":"0.1.0"}

kubectl exec -it deployment/konnektr-mcp-server -n konnektr-mcp -- \
  curl http://localhost:8080/readyz

# {"status":"ready","version":"0.1.0","auth_enabled":true}

# From outside (via ingress)
curl https://mcp.graph.konnektr.io/healthz
```

## Secrets Management

### Option 1: Manual (Development)

```bash
# Create secret manually
kubectl create secret generic auth0-config \
  --from-literal=domain=your-tenant.auth0.com \
  --from-literal=audience=https://graph.konnektr.io \
  -n konnektr-mcp
```

### Option 2: External Secrets Operator (Production)

Recommended for production. See `secrets.yaml` for example.

```bash
# Install External Secrets Operator
helm repo add external-secrets https://charts.external-secrets.io
helm install external-secrets external-secrets/external-secrets -n external-secrets-system --create-namespace

# Configure your secret store (Vault, AWS Secrets Manager, etc.)
# Then apply the ExternalSecret manifest in secrets.yaml
```

## Resource Sizing

### Small Deployment (<100 req/sec)

```yaml
replicas: 3
resources:
  requests:
    memory: "256Mi"
    cpu: "250m"
  limits:
    memory: "512Mi"
    cpu: "500m"
```

### Medium Deployment (100-500 req/sec)

```yaml
replicas: 5
resources:
  requests:
    memory: "512Mi"
    cpu: "500m"
  limits:
    memory: "1Gi"
    cpu: "1000m"
```

### Large Deployment (>500 req/sec)

```yaml
replicas: 10
resources:
  requests:
    memory: "1Gi"
    cpu: "1000m"
  limits:
    memory: "2Gi"
    cpu: "2000m"
```

Adjust `hpa.yaml` maxReplicas accordingly.

## Monitoring

### Check Pod Status

```bash
# Get pods
kubectl get pods -n konnektr-mcp

# Describe pod
kubectl describe pod <pod-name> -n konnektr-mcp

# View logs
kubectl logs -f deployment/konnektr-mcp-server -n konnektr-mcp

# View logs from all pods
kubectl logs -f -l app=konnektr-mcp -n konnektr-mcp
```

### Check HPA Status

```bash
# Get HPA status
kubectl get hpa -n konnektr-mcp

# Describe HPA
kubectl describe hpa konnektr-mcp-server -n konnektr-mcp

# Watch HPA in real-time
kubectl get hpa -n konnektr-mcp -w
```

### Check Health

```bash
# Test from within cluster
kubectl run -it --rm debug --image=curlimages/curl --restart=Never -n konnektr-mcp -- \
  curl http://konnektr-mcp-server/healthz

# Test readiness
kubectl run -it --rm debug --image=curlimages/curl --restart=Never -n konnektr-mcp -- \
  curl http://konnektr-mcp-server/readyz
```

## Troubleshooting

### Pods not starting

```bash
# Check pod events
kubectl describe pod <pod-name> -n konnektr-mcp

# Check logs
kubectl logs <pod-name> -n konnektr-mcp

# Common issues:
# - ImagePullBackOff: Check image name and registry credentials
# - CrashLoopBackOff: Check logs for application errors
# - Secret not found: Create auth0-config secret
```

### Readiness probe failing

```bash
# Check readiness endpoint
kubectl exec -it <pod-name> -n konnektr-mcp -- \
  curl http://localhost:8080/readyz

# Check logs
kubectl logs <pod-name> -n konnektr-mcp

# Common causes:
# - MCP session manager not starting
# - Configuration error (check secrets)
# - Port 8080 not listening
```

### HPA not scaling

```bash
# Check metrics server
kubectl top nodes
kubectl top pods -n konnektr-mcp

# If metrics not available, install metrics-server
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml

# Check HPA status
kubectl describe hpa konnektr-mcp-server -n konnektr-mcp
```

### Ingress not working

```bash
# Check ingress
kubectl describe ingress konnektr-mcp-server -n konnektr-mcp

# Check ingress controller logs
kubectl logs -f -n ingress-nginx -l app.kubernetes.io/component=controller

# Test without ingress
kubectl port-forward svc/konnektr-mcp-server 8080:80 -n konnektr-mcp
curl http://localhost:8080/healthz
```

## Rollout Strategy

### Rolling Update (default)

```yaml
strategy:
  type: RollingUpdate
  rollingUpdate:
    maxSurge: 1
    maxUnavailable: 0  # Zero downtime
```

### Deploy new version

```bash
# Update image
kubectl set image deployment/konnektr-mcp-server \
  mcp-server=your-registry/konnektr-mcp-server:v0.2.0 \
  -n konnektr-mcp

# Watch rollout
kubectl rollout status deployment/konnektr-mcp-server -n konnektr-mcp

# Check rollout history
kubectl rollout history deployment/konnektr-mcp-server -n konnektr-mcp
```

### Rollback

```bash
# Rollback to previous version
kubectl rollout undo deployment/konnektr-mcp-server -n konnektr-mcp

# Rollback to specific revision
kubectl rollout undo deployment/konnektr-mcp-server --to-revision=2 -n konnektr-mcp
```

## High Availability

The deployment ensures HA through:

1. **Multiple replicas** (minimum 3)
2. **Pod anti-affinity** (spread across nodes)
3. **Readiness probes** (remove unhealthy pods from LB)
4. **HPA** (auto-scale based on load)
5. **Zero-downtime deployments** (maxUnavailable: 0)

## Security

### Network Policies

Create network policies to restrict traffic:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: konnektr-mcp-server
  namespace: konnektr-mcp
spec:
  podSelector:
    matchLabels:
      app: konnektr-mcp
  policyTypes:
  - Ingress
  - Egress
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          name: ingress-nginx
    ports:
    - protocol: TCP
      port: 8080
  egress:
  - to:
    - namespaceSelector: {}
    ports:
    - protocol: TCP
      port: 443  # HTTPS to API pods
  - to:
    - namespaceSelector:
        matchLabels:
          name: kube-system
    ports:
    - protocol: UDP
      port: 53  # DNS
```

### Pod Security Standards

The deployment uses restrictive security context:

```yaml
securityContext:
  runAsNonRoot: true
  runAsUser: 1000
  allowPrivilegeEscalation: false
  capabilities:
    drop:
    - ALL
```

## Cost Optimization

### Right-size resources

```bash
# Monitor actual usage
kubectl top pods -n konnektr-mcp

# Adjust requests/limits in deployment.yaml
```

### Use spot instances

```yaml
# Add node selector and toleration
nodeSelector:
  node.kubernetes.io/lifecycle: spot
tolerations:
- key: "spot"
  operator: "Equal"
  value: "true"
  effect: "NoSchedule"
```

### Adjust HPA behavior

```yaml
# More aggressive scale-down
behavior:
  scaleDown:
    stabilizationWindowSeconds: 60  # Faster scale-down
```

## Maintenance

### Update secrets

```bash
# Update secret
kubectl create secret generic auth0-config \
  --from-literal=domain=new-tenant.auth0.com \
  --from-literal=audience=https://graph.konnektr.io \
  --dry-run=client -o yaml | kubectl apply -f -

# Restart pods to pick up new secret
kubectl rollout restart deployment/konnektr-mcp-server -n konnektr-mcp
```

### Backup

The MCP server is stateless, so no backups needed. However:

1. Store Kubernetes manifests in Git
2. Store secrets in secret manager (Vault, AWS Secrets Manager)
3. Document configuration

## CI/CD Integration

See `../docs/deployment.md` for GitHub Actions example.

## Next Steps

- Set up monitoring (Prometheus + Grafana)
- Configure alerting (PagerDuty, Slack)
- Set up log aggregation (Loki, ELK)
- Perform load testing
- Document runbooks
