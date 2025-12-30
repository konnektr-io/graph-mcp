# Deployment Guide

## Local Development

### Prerequisites

- Python 3.12+
- pip
- Virtual environment tool (venv)

### Quick Start

```bash
# 1. Clone repository
git clone <repository-url>
cd graph-mcp

# 2. Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env:
#   AUTH_ENABLED=false  # For local dev without Auth0
#   API_BASE_URL_TEMPLATE=http://localhost:5000  # Your local API

# 5. Run server
uvicorn konnektr_mcp.server:app --reload --port 8080

# 6. Test with MCP Inspector
npx @modelcontextprotocol/inspector http://localhost:8080/mcp?resource_id=test
```

### Using in Claude Desktop (Local)

```json
// ~/Library/Application Support/Claude/claude_desktop_config.json
{
  "mcpServers": {
    "konnektr-graph-local": {
      "type": "http",
      "url": "http://localhost:8080/mcp?resource_id=test"
    }
  }
}
```

## Docker Deployment

### Build Image

```bash
# Build
docker build -t konnektr-mcp-server:latest .

# Test locally
docker run -p 8080:8080 \
  -e AUTH_ENABLED=false \
  -e API_BASE_URL_TEMPLATE=http://host.docker.internal:5000 \
  konnektr-mcp-server:latest
```

### Docker Compose

```yaml
# docker-compose.yml
version: '3.8'

services:
  mcp-server:
    build: .
    ports:
      - "8080:8080"
    environment:
      AUTH0_DOMAIN: ${AUTH0_DOMAIN}
      AUTH0_AUDIENCE: https://graph.konnektr.io
      AUTH_ENABLED: "true"
      API_BASE_URL_TEMPLATE: https://{resource_id}.api.graph.konnektr.io
    healthcheck:
      test: ["CMD", "python", "-c", "import httpx; httpx.get('http://localhost:8080/health')"]
      interval: 30s
      timeout: 3s
      retries: 3
    restart: unless-stopped
```

```bash
# Run
docker-compose up -d

# Logs
docker-compose logs -f mcp-server

# Stop
docker-compose down
```

## Kubernetes Deployment

### Prerequisites

- Kubernetes cluster (1.25+)
- kubectl configured
- Helm (optional, for Redis)

### 1. Create Namespace

```bash
kubectl create namespace konnektr-mcp
```

### 2. Create Secrets

```bash
# Auth0 credentials
kubectl create secret generic auth0-config \
  --from-literal=domain=your-tenant.auth0.com \
  --from-literal=audience=https://graph.konnektr.io \
  -n konnektr-mcp
```

### 3. Deploy Application

```yaml
# deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mcp-server
  namespace: konnektr-mcp
  labels:
    app: mcp-server
spec:
  replicas: 3
  selector:
    matchLabels:
      app: mcp-server
  template:
    metadata:
      labels:
        app: mcp-server
    spec:
      containers:
      - name: mcp-server
        image: your-registry/konnektr-mcp-server:latest
        ports:
        - containerPort: 8080
          name: http
        env:
        - name: AUTH0_DOMAIN
          valueFrom:
            secretKeyRef:
              name: auth0-config
              key: domain
        - name: AUTH0_AUDIENCE
          valueFrom:
            secretKeyRef:
              name: auth0-config
              key: audience
        - name: AUTH_ENABLED
          value: "true"
        - name: API_BASE_URL_TEMPLATE
          value: "https://{resource_id}.api.graph.konnektr.io"
        - name: API_TIMEOUT_SECONDS
          value: "30"
        resources:
          requests:
            memory: "256Mi"
            cpu: "250m"
          limits:
            memory: "512Mi"
            cpu: "500m"
        livenessProbe:
          httpGet:
            path: /health
            port: 8080
          initialDelaySeconds: 10
          periodSeconds: 30
        readinessProbe:
          httpGet:
            path: /ready
            port: 8080
          initialDelaySeconds: 5
          periodSeconds: 10
---
apiVersion: v1
kind: Service
metadata:
  name: mcp-server
  namespace: konnektr-mcp
spec:
  selector:
    app: mcp-server
  ports:
  - port: 80
    targetPort: 8080
    protocol: TCP
  type: ClusterIP
```

```bash
kubectl apply -f deployment.yaml
```

### 4. Configure Ingress

```yaml
# ingress.yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: mcp-server
  namespace: konnektr-mcp
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
spec:
  ingressClassName: nginx
  tls:
  - hosts:
    - mcp.graph.konnektr.io
    secretName: mcp-tls
  rules:
  - host: mcp.graph.konnektr.io
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: mcp-server
            port:
              number: 80
```

```bash
kubectl apply -f ingress.yaml
```

### 5. Horizontal Pod Autoscaling

```yaml
# hpa.yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: mcp-server
  namespace: konnektr-mcp
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: mcp-server
  minReplicas: 3
  maxReplicas: 20
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
```

```bash
kubectl apply -f hpa.yaml
```

## Production Best Practices

### 1. Resource Sizing

**Small Deployment (< 100 req/sec):**
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

**Medium Deployment (100-500 req/sec):**
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

**Large Deployment (> 500 req/sec):**
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

### 2. Monitoring

#### Prometheus Metrics

```yaml
# servicemonitor.yaml (if using Prometheus Operator)
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: mcp-server
  namespace: konnektr-mcp
spec:
  selector:
    matchLabels:
      app: mcp-server
  endpoints:
  - port: http
    path: /metrics
    interval: 30s
```

#### Key Metrics to Monitor

- `http_requests_total`: Total requests
- `http_request_duration_seconds`: Request latency
- `python_gc_objects_collected_total`: GC activity
- `process_resident_memory_bytes`: Memory usage

#### Grafana Dashboard

Import dashboard ID: [Create custom dashboard]

### 3. Logging

```yaml
# Configure structured JSON logging
env:
- name: LOG_LEVEL
  value: "INFO"
- name: LOG_FORMAT
  value: "json"
```

**Log aggregation options:**
- Loki (lightweight)
- Elasticsearch + Kibana
- CloudWatch Logs (AWS)
- Stackdriver (GCP)

### 4. Security

#### Network Policies

```yaml
# network-policy.yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: mcp-server
  namespace: konnektr-mcp
spec:
  podSelector:
    matchLabels:
      app: mcp-server
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

#### Pod Security Policy

```yaml
apiVersion: policy/v1beta1
kind: PodSecurityPolicy
metadata:
  name: mcp-server
spec:
  privileged: false
  allowPrivilegeEscalation: false
  requiredDropCapabilities:
  - ALL
  runAsUser:
    rule: MustRunAsNonRoot
  seLinux:
    rule: RunAsAny
  fsGroup:
    rule: RunAsAny
  volumes:
  - 'configMap'
  - 'emptyDir'
  - 'secret'
```

### 5. Backup & Disaster Recovery

The MCP server is stateless, so no backups are needed. However:

**Document:**
- Auth0 configuration
- Environment variables
- Kubernetes manifests

**Store in:**
- Git repository (infrastructure-as-code)
- Secret manager (credentials)

## CI/CD Pipeline

### GitHub Actions Example

```yaml
# .github/workflows/deploy.yml
name: Deploy MCP Server

on:
  push:
    branches: [main]

jobs:
  build-and-deploy:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v3

    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.12'

    - name: Run tests
      run: |
        pip install -r requirements.txt
        pytest

    - name: Build Docker image
      run: |
        docker build -t ${{ secrets.REGISTRY }}/konnektr-mcp-server:${{ github.sha }} .
        docker tag ${{ secrets.REGISTRY }}/konnektr-mcp-server:${{ github.sha }} \
                   ${{ secrets.REGISTRY }}/konnektr-mcp-server:latest

    - name: Push to registry
      run: |
        echo ${{ secrets.REGISTRY_PASSWORD }} | docker login ${{ secrets.REGISTRY }} -u ${{ secrets.REGISTRY_USER }} --password-stdin
        docker push ${{ secrets.REGISTRY }}/konnektr-mcp-server:${{ github.sha }}
        docker push ${{ secrets.REGISTRY }}/konnektr-mcp-server:latest

    - name: Deploy to Kubernetes
      run: |
        kubectl set image deployment/mcp-server \
          mcp-server=${{ secrets.REGISTRY }}/konnektr-mcp-server:${{ github.sha }} \
          -n konnektr-mcp

    - name: Wait for rollout
      run: kubectl rollout status deployment/mcp-server -n konnektr-mcp
```

## Rollback Procedures

### Kubernetes Rollback

```bash
# View deployment history
kubectl rollout history deployment/mcp-server -n konnektr-mcp

# Rollback to previous version
kubectl rollout undo deployment/mcp-server -n konnektr-mcp

# Rollback to specific revision
kubectl rollout undo deployment/mcp-server --to-revision=3 -n konnektr-mcp
```

### Docker Rollback

```bash
# Pull previous image
docker pull your-registry/konnektr-mcp-server:previous-tag

# Stop current container
docker stop mcp-server

# Start with previous image
docker run -d --name mcp-server \
  -p 8080:8080 \
  your-registry/konnektr-mcp-server:previous-tag
```

## Troubleshooting

### Pod Not Starting

```bash
# Check pod status
kubectl get pods -n konnektr-mcp

# View pod logs
kubectl logs -f deployment/mcp-server -n konnektr-mcp

# Describe pod for events
kubectl describe pod <pod-name> -n konnektr-mcp
```

**Common issues:**
- Missing secrets → Create auth0-config secret
- Image pull errors → Check registry credentials
- OOMKilled → Increase memory limits

### High Latency

```bash
# Check resource usage
kubectl top pods -n konnektr-mcp

# Check HPA status
kubectl get hpa -n konnektr-mcp

# Check if pods are throttled
kubectl describe pod <pod-name> -n konnektr-mcp | grep -A 5 "State:"
```

**Solutions:**
- Scale horizontally (increase replicas)
- Scale vertically (increase resources)
- Check API pod performance

### Auth Failures

```bash
# Test Auth0 connectivity
kubectl exec -it deployment/mcp-server -n konnektr-mcp -- \
  python -c "import httpx; print(httpx.get('https://your-tenant.auth0.com/.well-known/jwks.json').status_code)"
```

**Common issues:**
- Wrong AUTH0_DOMAIN → Check secret
- Invalid audience → Verify Auth0 API configuration
- Expired JWKS cache → Restart pods

## Health Checks

### Manual Health Check

```bash
# Health endpoint
curl https://mcp.graph.konnektr.io/health

# Expected response:
# {"status": "healthy", "version": "0.1.0"}
```

### Automated Monitoring

```bash
# Set up external monitoring (e.g., UptimeRobot, Pingdom)
Endpoint: https://mcp.graph.konnektr.io/health
Interval: 5 minutes
Expected: 200 status, {"status": "healthy"}
```

## Performance Tuning

### Uvicorn Workers

```dockerfile
# Dockerfile - adjust workers based on CPU
CMD ["uvicorn", "konnektr_mcp.server:app", \
     "--host", "0.0.0.0", \
     "--port", "8080", \
     "--workers", "4", \
     "--loop", "uvloop"]
```

**Rule of thumb:** `workers = (2 x CPU cores) + 1`

### Connection Pooling

Currently each request creates new SDK client. For high throughput:

```python
# Future optimization: Connection pool per resource_id
# See architecture.md "Future Enhancements"
```

## Cost Optimization

### Right-Sizing

```bash
# Monitor actual usage
kubectl top pods -n konnektr-mcp --sort-by=memory

# Adjust requests/limits accordingly
# Don't over-provision
```

### Spot/Preemptible Instances

```yaml
# nodeSelector for cost savings (AWS example)
nodeSelector:
  eks.amazonaws.com/capacityType: SPOT
tolerations:
- key: "spot"
  operator: "Equal"
  value: "true"
  effect: "NoSchedule"
```

### Autoscaling Tuning

```yaml
# Aggressive scaling for cost savings
behavior:
  scaleDown:
    stabilizationWindowSeconds: 60  # Scale down quickly
    policies:
    - type: Percent
      value: 50  # Scale down 50% at a time
      periodSeconds: 60
  scaleUp:
    stabilizationWindowSeconds: 0  # Scale up immediately
    policies:
    - type: Percent
      value: 100  # Double capacity
      periodSeconds: 15
```

## Next Steps

- **Monitoring Setup:** Configure Prometheus + Grafana
- **Alerting:** Set up PagerDuty/Opsgenie integration
- **Load Testing:** Use k6 or Locust to find limits
- **Security Audit:** Regular vulnerability scanning
- **Disaster Recovery:** Document and test recovery procedures
