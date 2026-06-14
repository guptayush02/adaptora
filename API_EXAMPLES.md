# Visual API Guide - cURL Examples

This guide shows how to interact with the LLM Token Optimizer Middleware using cURL commands.

## 🟢 Basic Usage

### 1. Health Check
```bash
curl http://localhost:8000/api/health
```
**Response:**
```json
{
  "status": "healthy",
  "message": "LLM Middleware is running"
}
```

### 2. Root Endpoint
```bash
curl http://localhost:8000/
```
**Response:**
```json
{
  "name": "LLM Token Optimizer Middleware",
  "version": "1.0.0",
  "description": "A middleware for optimizing prompts and tracking tokens",
  "endpoints": {
    "process": "/api/process",
    "health": "/api/health",
    "stats": "/api/stats/{user_id}",
    "cache_clear": "/api/cache/clear"
  }
}
```

## 🔵 Process Prompt

### Simple Query (will use Ollama)
```bash
curl -X POST "http://localhost:8000/api/process" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "What is Python?",
    "user_id": "user1",
    "temperature": 0.7
  }'
```

**Response:**
```json
{
  "response": "Python is a high-level, interpreted programming language known for its simplicity and readability...",
  "model_used": "ollama",
  "tokens_used": {
    "prompt_tokens": 5,
    "response_tokens": 45,
    "total_tokens": 50
  },
  "cache_hit": false,
  "complexity_level": "simple",
  "processing_time_ms": 245.38
}
```

### Medium Complexity Query
```bash
curl -X POST "http://localhost:8000/api/process" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Explain how REST APIs work with HTTP methods and status codes",
    "user_id": "user1",
    "temperature": 0.5
  }'
```

### Complex Query (will route to advanced model if configured)
```bash
curl -X POST "http://localhost:8000/api/process" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Design a microservices architecture for a real-time collaborative document editor with CRDT-based conflict resolution, handling 10K concurrent users with sub-100ms latency requirements",
    "model": "gpt-4",
    "user_id": "user1"
  }'
```

### Using Bypass Keywords
```bash
curl -X POST "http://localhost:8000/api/process" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "URGENT: Fix this critical bug in production - [code]",
    "user_id": "user1"
  }'
# Note: "URGENT" keyword forces advanced model
```

### Full Parameters Example
```bash
curl -X POST "http://localhost:8000/api/process" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Explain quantum computing",
    "model": "ollama",
    "temperature": 0.7,
    "max_tokens": 500,
    "top_p": 0.95,
    "user_id": "demo_user",
    "metadata": {
      "source": "web",
      "version": "1.0"
    }
  }'
```

## 📊 Statistics & Analytics

### Get User Statistics
```bash
curl "http://localhost:8000/api/stats/user1"
```

**Response:**
```json
{
  "user_id": "user1",
  "total_queries": 15,
  "total_tokens": 2500,
  "average_tokens_per_query": 166.67,
  "models_used": {
    "ollama": 12,
    "gpt-4": 3
  }
}
```

### Get Stats for Different User
```bash
curl "http://localhost:8000/api/stats/user2"
```

## 💾 Cache Management

### Clear All Cache
```bash
curl -X POST "http://localhost:8000/api/cache/clear"
```

**Response:**
```json
{
  "message": "Cache cleared successfully"
}
```

## 🔄 Test Cache Behavior

### First Request (Cache Miss)
```bash
curl -X POST "http://localhost:8000/api/process" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "What is AI?",
    "user_id": "user1"
  }'
```

**Response includes:**
```json
{
  "cache_hit": false,
  "processing_time_ms": 487.23
}
```

### Second Identical Request (Cache Hit)
```bash
curl -X POST "http://localhost:8000/api/process" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "What is AI?",
    "user_id": "user1"
  }'
```

**Response includes:**
```json
{
  "cache_hit": true,
  "processing_time_ms": 12.45  // Much faster!
}
```

## 📋 Batch Queries with jq

### Process multiple queries and parse results
```bash
# Extract just the model used from response
curl -s -X POST "http://localhost:8000/api/process" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Hello", "user_id": "user1"}' | jq '.model_used'

# Extract tokens used
curl -s -X POST "http://localhost:8000/api/process" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Hello", "user_id": "user1"}' | jq '.tokens_used.total_tokens'

# Extract cache hit status
curl -s -X POST "http://localhost:8000/api/process" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Hello", "user_id": "user1"}' | jq '.cache_hit'
```

## 🔐 Bearer Token (if authentication added)

```bash
curl -X POST "http://localhost:8000/api/process" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "What is machine learning?",
    "user_id": "user1"
  }'
```

## 📝 Request Variations

### Minimal Request
```bash
curl -X POST "http://localhost:8000/api/process" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Hello"}'
```

### With Custom Model
```bash
curl -X POST "http://localhost:8000/api/process" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Question",
    "model": "gpt-4"
  }'
```

### With Temperature Variation
```bash
# More creative (higher temperature)
curl -X POST "http://localhost:8000/api/process" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Write a poem about AI",
    "temperature": 1.5
  }'

# More deterministic (lower temperature)
curl -X POST "http://localhost:8000/api/process" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "2+2=?",
    "temperature": 0.0
  }'
```

## 🛠️ Debugging Requests

### Verbose Output
```bash
curl -v -X POST "http://localhost:8000/api/process" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Test"}'
```

### Show Response Headers
```bash
curl -i -X POST "http://localhost:8000/api/process" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Test"}'
```

### Pretty Print JSON
```bash
curl -s -X POST "http://localhost:8000/api/process" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Test"}' | python3 -m json.tool
```

### Save Response to File
```bash
curl -X POST "http://localhost:8000/api/process" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Test"}' > response.json
```

## 📊 Monitoring Requests

### Check Request Rate
```bash
# Send 5 requests and measure time
time for i in {1..5}; do
  curl -X POST "http://localhost:8000/api/process" \
    -H "Content-Type: application/json" \
    -d '{"prompt": "test", "user_id": "user1"}' > /dev/null
done
```

### Load Testing with Apache Bench
```bash
ab -n 100 -c 10 http://localhost:8000/api/health
```

### Load Testing with wrk
```bash
wrk -t4 -c100 -d30s http://localhost:8000/api/health
```

## 🔍 Response Status Codes

| Code | Meaning |
|------|---------|
| 200 | Success |
| 400 | Bad request (invalid JSON) |
| 422 | Validation error (missing required fields) |
| 500 | Server error (model unavailable, etc.) |
| 503 | Service unavailable (dependencies down) |

### Handle Errors
```bash
# Check status code
curl -w "Status: %{http_code}\n" -X POST "http://localhost:8000/api/process" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "test"}'

# Capture error response
response=$(curl -X POST "http://localhost:8000/api/process" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "test"}')

if echo "$response" | grep -q "error"; then
  echo "Error occurred: $response"
else
  echo "Success: $response"
fi
```

## 🎯 Real-World Scenarios

### Scenario 1: Quick Question
```bash
curl -X POST "http://localhost:8000/api/process" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "What is the capital of France?",
    "user_id": "student_001"
  }'
```

### Scenario 2: Code Review
```bash
curl -X POST "http://localhost:8000/api/process" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "ADVANCED: Review this code for performance issues:\n\nfor i in range(1000000):\n    print(i)",
    "user_id": "developer_001",
    "temperature": 0.3
  }'
```

### Scenario 3: Content Generation
```bash
curl -X POST "http://localhost:8000/api/process" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Write a blog post about machine learning",
    "user_id": "content_team",
    "temperature": 1.0,
    "max_tokens": 2000
  }'
```

### Scenario 4: Urgent Production Issue
```bash
curl -X POST "http://localhost:8000/api/process" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "CRITICAL: Database connection timeout in production. Fix immediately.",
    "user_id": "on_call_engineer",
    "model": "gpt-4"
  }'
```

## 📚 References

- **Full API Docs**: http://localhost:8000/docs
- **OpenAPI Schema**: http://localhost:8000/openapi.json
- **Project README**: See README.md
- **Examples**: See example_usage.py

---

**Pro Tips:**
- Use `cache_hit: true` responses for analytics
- Track `processing_time_ms` to identify bottlenecks
- Monitor `tokens_used` for cost analysis
- Use `complexity_level` to understand query patterns
