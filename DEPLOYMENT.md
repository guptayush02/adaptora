# Deployment & Production Guide

## Production Checklist

- [x] Project structure created
- [x] Core services implemented
- [x] API endpoints ready
- [x] Database models configured
- [x] Caching system implemented
- [ ] Set up PostgreSQL (for production)
- [ ] Configure Redis cluster (for production)
- [ ] Add authentication middleware
- [ ] Setup rate limiting
- [ ] Configure monitoring/logging
- [ ] Setup CI/CD pipeline
- [ ] Performance testing
- [ ] Security audit
- [ ] Load testing

## Environment Setup

### Development
```bash
CACHE_TYPE=memory
DATABASE_URL=sqlite:///./token_optimizer.db
LOG_LEVEL=DEBUG
```

### Production
```bash
CACHE_TYPE=redis
DATABASE_URL=postgresql://user:password@db:5432/token_optimizer
REDIS_URL=redis://redis-cluster:6379/0
LOG_LEVEL=INFO
```

## Docker Deployment

### Single Container

Create `Dockerfile`:
```dockerfile
FROM python:3.10-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Expose port
EXPOSE 8000

# Run application
CMD ["python", "main.py"]
```

Build and run:
```bash
docker build -t llm-middleware:1.0 .
docker run -p 8000:8000 --env-file .env llm-middleware:1.0
```

### Docker Compose (Recommended)

Create `docker-compose.yml`:
```yaml
version: '3.8'

services:
  middleware:
    build: .
    container_name: llm-middleware
    ports:
      - "8000:8000"
    environment:
      - CACHE_TYPE=redis
      - REDIS_URL=redis://redis:6379/0
      - DATABASE_URL=postgresql://postgres:password@postgres:5432/token_optimizer
      - OLLAMA_API_URL=http://ollama:11434
      - LOG_LEVEL=INFO
    depends_on:
      - redis
      - postgres
      - ollama
    volumes:
      - ./logs:/app/logs
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    container_name: llm-redis
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    restart: unless-stopped

  postgres:
    image: postgres:15-alpine
    container_name: llm-postgres
    environment:
      - POSTGRES_USER=postgres
      - POSTGRES_PASSWORD=password
      - POSTGRES_DB=token_optimizer
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    restart: unless-stopped

  ollama:
    image: ollama/ollama:latest
    container_name: llm-ollama
    ports:
      - "11434:11434"
    volumes:
      - ollama_data:/root/.ollama
    restart: unless-stopped

volumes:
  redis_data:
  postgres_data:
  ollama_data:
```

Run with Docker Compose:
```bash
docker-compose up -d

# Check status
docker-compose ps

# View logs
docker-compose logs -f middleware

# Pull Ollama model
docker-compose exec ollama ollama pull mistral

# Stop services
docker-compose down
```

## Kubernetes Deployment

### Deployment manifest (`k8s/middleware-deployment.yaml`)

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: llm-middleware
spec:
  replicas: 3
  selector:
    matchLabels:
      app: llm-middleware
  template:
    metadata:
      labels:
        app: llm-middleware
    spec:
      containers:
      - name: middleware
        image: llm-middleware:1.0
        ports:
        - containerPort: 8000
        env:
        - name: CACHE_TYPE
          value: "redis"
        - name: REDIS_URL
          value: "redis://redis-service:6379/0"
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: db-secret
              key: url
        resources:
          requests:
            memory: "256Mi"
            cpu: "250m"
          limits:
            memory: "512Mi"
            cpu: "500m"
```

### Service manifest (`k8s/middleware-service.yaml`)

```yaml
apiVersion: v1
kind: Service
metadata:
  name: llm-middleware-service
spec:
  selector:
    app: llm-middleware
  ports:
  - port: 80
    targetPort: 8000
  type: LoadBalancer
```

Deploy:
```bash
kubectl apply -f k8s/
kubectl get deployments
kubectl get services
```

## Monitoring & Observability

### Add Prometheus metrics

Create `app/services/metrics.py`:
```python
from prometheus_client import Counter, Histogram
import time

# Metrics
request_count = Counter('middleware_requests', 'Total requests')
request_duration = Histogram('middleware_request_duration', 'Request duration')
cache_hits = Counter('cache_hits', 'Cache hit count')
tokens_used = Counter('tokens_used', 'Total tokens used')

@app.middleware("http")
async def track_metrics(request, call_next):
    start = time.time()
    request_count.inc()
    response = await call_next(request)
    duration = time.time() - start
    request_duration.observe(duration)
    return response
```

### Logging configuration

```python
# app/core/logger.py
import logging
from logging.handlers import RotatingFileHandler
import os

os.makedirs('logs', exist_ok=True)

handler = RotatingFileHandler(
    'logs/middleware.log',
    maxBytes=10485760,  # 10MB
    backupCount=10
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        handler
    ]
)
```

### Add health checks

```python
@app.get("/health/live")
async def liveness():
    return {"status": "alive"}

@app.get("/health/ready")
async def readiness():
    try:
        # Check database
        db = SessionLocal()
        db.execute("SELECT 1")
        db.close()
        
        # Check cache
        cache_manager.get("test_key")
        
        return {"status": "ready"}
    except:
        return {"status": "not_ready"}, 503
```

## Performance Tuning

### Database Optimization

```python
# Add indexes
CREATE INDEX idx_user_id ON token_usage(user_id);
CREATE INDEX idx_timestamp ON token_usage(timestamp);
CREATE INDEX idx_cache_key ON cache(cache_key);
CREATE INDEX idx_expires_at ON cache(expires_at);
```

### Connection Pooling

```python
from sqlalchemy.pool import QueuePool

engine = create_engine(
    DATABASE_URL,
    poolclass=QueuePool,
    pool_size=20,
    max_overflow=40,
    pool_pre_ping=True,  # Test connections
    pool_recycle=3600    # Recycle connections
)
```

### Async Support

```python
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession

engine = create_async_engine("postgresql+asyncpg://...")
```

## Rate Limiting

```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

@app.post("/api/process")
@limiter.limit("30/minute")
async def process_prompt(request, *, limiter_key=None):
    # Process prompt
    pass
```

## API Gateway (Optional)

### With NGINX

```nginx
upstream middleware {
    server middleware:8000;
    server middleware:8001;
}

server {
    listen 80;
    server_name api.example.com;

    location / {
        proxy_pass http://middleware;
        proxy_set_header Host $host;
        
        # Rate limiting
        limit_req_zone $binary_remote_addr zone=api:10m rate=30r/m;
        limit_req zone=api burst=60;
    }
}
```

## Backup & Disaster Recovery

### Database Backup

```bash
# PostgreSQL backup
pg_dump -U postgres token_optimizer > backup.sql

# Restore
psql -U postgres token_optimizer < backup.sql

# Automated backup (cron)
0 2 * * * pg_dump -U postgres token_optimizer | gzip > /backups/db_$(date +%Y%m%d_%H%M%S).sql.gz
```

### Redis Backup

```bash
# Manual snapshot
redis-cli BGSAVE

# Restore
# Redis will automatically load dump.rdb on startup
```

## SSL/TLS Setup

### With Let's Encrypt

```bash
# Install certbot
pip install certbot

# Generate certificate
certbot certonly --standalone -d api.example.com

# Add to FastAPI
uvicorn main:app --ssl-keyfile=/path/to/key.pem --ssl-certfile=/path/to/cert.pem
```

## Environment Variables Checklist

```bash
# Database
DATABASE_URL=postgresql://user:pass@host:5432/db

# Cache
CACHE_TYPE=redis
REDIS_URL=redis://host:6379/0

# LLM Models
OLLAMA_API_URL=http://ollama:11434
OLLAMA_MODEL=mistral
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...

# Application
LOG_LEVEL=INFO
DEBUG=False

# Complexity Thresholds
SIMPLE_QUERY_THRESHOLD=100
MEDIUM_QUERY_THRESHOLD=500

# Bypass Keywords
BYPASS_KEYWORDS=urgent,critical,advanced
```

## Monitoring Dashboard (Optional)

### Grafana + Prometheus

```yaml
# prometheus.yml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: 'middleware'
    static_configs:
      - targets: ['localhost:8000/metrics']
```

## Troubleshooting Production

### Out of Memory
```bash
# Check memory usage
docker stats

# Increase container memory limit
docker update -m 2g <container_id>
```

### Database Connection Issues
```bash
# Check PostgreSQL status
docker-compose logs postgres

# Test connection
psql -h localhost -U postgres -d token_optimizer
```

### Slow Responses
```bash
# Check Redis
redis-cli ping

# Monitor cache hit rate
# Query database for cache hit statistics
```

### Deployment Rollback

```bash
# If using Docker Compose
docker-compose down
docker-compose pull  # Get previous image tag
docker-compose up -d
```

## Cost Optimization

1. **Use Ollama for 80% of queries** → Save OpenAI costs
2. **Aggressive caching** → Reduce API calls by 60-70%
3. **Batch similar queries** → Optimize token usage
4. **Use appropriate models** → Don't use GPT-4 for simple tasks

## Resources

- [FastAPI Deployment](https://fastapi.tiangolo.com/deployment/)
- [Docker Best Practices](https://docs.docker.com/develop/dev-best-practices/)
- [Kubernetes Basics](https://kubernetes.io/docs/concepts/overview/)
- [PostgreSQL Performance](https://www.postgresql.org/docs/current/performance.html)
