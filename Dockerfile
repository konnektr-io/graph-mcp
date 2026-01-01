FROM python:3.12-slim

WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY konnektr_mcp/ ./konnektr_mcp/

# Set Python path
ENV PYTHONPATH=/app

# Health check using readiness probe
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import httpx; exit(0 if httpx.get('http://localhost:8080/readyz', timeout=2).status_code == 200 else 1)" || exit 1

EXPOSE 8080

CMD ["uvicorn", "konnektr_mcp.server:app", "--host", "0.0.0.0", "--port", "8080"]
