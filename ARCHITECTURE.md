# Architecture & Extension Guide

## System Architecture

### High-Level Components

```
┌────────────────────────────────────────────────────────┐
│                    FastAPI Server                       │
│                   (Port: 8000)                          │
└────────────────────────────────────────────────────────┘
                         │
        ┌────────────────┼────────────────┐
        │                │                │
        ▼                ▼                ▼
    ┌─────────┐    ┌──────────┐    ┌─────────────┐
    │  Routes │    │  Services │   │    Cache    │
    │ (API)   │    │ (Logic)   │   │  (Redis/    │
    └────────┬┘    └──────┬───┘    │   Memory)   │
             │           │        └────────┬────┘
             └───────────┼────────────────┘
                         │
        ┌────────────────┼────────────────┐
        │                │                │
        ▼                ▼                ▼
   ┌─────────────┐ ┌──────────┐  ┌──────────────┐
   │ Complexity  │ │ Prompt   │  │   LLM        │
   │ Analyzer    │ │ Optimizer│  │   Provider   │
   └────┬────────┘ └────┬─────┘  └──────┬───────┘
        │               │               │
        └───────────────┼───────────────┘
                        │
        ┌───────────────┼───────────────┐
        │               │               │
        ▼               ▼               ▼
    ┌────────┐  ┌────────────┐  ┌──────────────┐
    │ Ollama │  │  OpenAI    │  │  Anthropic   │
    │(Local) │  │  (GPT-4)   │  │  (Claude)    │
    └────────┘  └────────────┘  └──────────────┘
```

### Key Services

#### 1. **MiddlewareService** (Orchestrator)
Location: `app/services/middleware_service.py`

Coordinates the entire flow:
```
process_prompt()
├── 1. Check cache
├── 2. Check bypass keywords
├── 3. Analyze complexity
├── 4. Route to appropriate model
├── 5. Cache response
└── 6. Track tokens
```

#### 2. **ComplexityAnalyzer**
Location: `app/services/complexity_analyzer.py`

Determines query complexity using:
- Local heuristics (word count, technical terms)
- Ollama assessment
- Combined scoring

Returns: `simple`, `medium`, or `difficult`

#### 3. **PromptOptimizer**
Location: `app/services/prompt_optimizer.py`

Optimizes prompts with Ollama:
- Removes redundancy
- Improves clarity
- Tracks tokens saved
- Detects bypass keywords

#### 4. **LLMProvider**
Location: `app/services/llm_provider.py`

Interfaces with LLM models:
- `query_ollama()` - Local model
- `query_openai()` - OpenAI GPT
- `query_anthropic()` - Anthropic Claude
- `query()` - Smart router

#### 5. **CacheManager**
Location: `app/cache/cache_manager.py`

Manages response caching:
- Redis backend (distributed)
- In-memory fallback
- Configurable TTL
- Cache key generation

## File Organization

```
token-optimizer/
│
├── app/
│   ├── core/
│   │   ├── config.py          # Settings management
│   │   ├── logger.py          # Logging setup
│   │   └── __init__.py
│   │
│   ├── models/
│   │   ├── schema.py          # Pydantic models (request/response)
│   │   └── __init__.py
│   │
│   ├── services/
│   │   ├── middleware_service.py    # Main orchestrator
│   │   ├── complexity_analyzer.py   # Complexity detection
│   │   ├── prompt_optimizer.py      # Prompt optimization
│   │   ├── llm_provider.py          # LLM interfaces
│   │   └── __init__.py
│   │
│   ├── routes/
│   │   ├── api.py             # API endpoints
│   │   └── __init__.py
│   │
│   ├── cache/
│   │   ├── cache_manager.py   # Caching logic
│   │   └── __init__.py
│   │
│   ├── db/
│   │   ├── models.py          # SQLAlchemy models
│   │   ├── database.py        # DB connection
│   │   └── __init__.py
│   │
│   └── __init__.py
│
├── tests/
│   ├── test_api.py            # API tests
│   └── __init__.py
│
├── main.py                     # FastAPI app entry point
├── requirements.txt            # Dependencies
├── .env.example               # Config template
├── .gitignore                 # Git ignore patterns
├── README.md                  # Full documentation
├── QUICKSTART.md              # Quick start guide
├── example_usage.py           # Usage examples
└── ARCHITECTURE.md            # This file
```

## Data Models

### Request Schema (PromptRequest)
```python
{
    "prompt": str,                    # User's input
    "model": Optional[str],           # Preferred model
    "temperature": float,             # 0-2 (randomness)
    "max_tokens": Optional[int],      # Response limit
    "top_p": float,                   # Nucleus sampling
    "user_id": Optional[str],         # User identifier
    "metadata": Optional[Dict]        # Custom data
}
```

### Response Schema (PromptResponse)
```python
{
    "response": str,                      # LLM output
    "model_used": str,                    # Which model
    "tokens_used": {
        "prompt_tokens": int,
        "response_tokens": int,
        "total_tokens": int
    },
    "cache_hit": bool,
    "complexity_level": str,              # simple/medium/difficult
    "processing_time_ms": float,
    "prompt_optimization": Optional[str]
}
```

### Database Models

**TokenUsageRecord**
```python
- id: int (PK)
- user_id: str (indexed)
- prompt: str
- response: str
- prompt_tokens: int
- response_tokens: int
- total_tokens: int
- model_used: str
- timestamp: datetime
- complexity_level: str
- cache_hit: bool
```

**CacheRecord**
```python
- id: int (PK)
- cache_key: str (unique, indexed)
- prompt: str
- response: str
- model_used: str
- tokens_used: int
- created_at: datetime
- expires_at: datetime (indexed)
- hit_count: int
```

## Decision Flow

### Routing Decision Tree

```
Query Arrives
    │
    ├─ Is in cache? YES ──► Return cached response ✨
    │                       (0-10ms)
    │
    └─ NO
        │
        ├─ Contains bypass keyword? YES ──► Advanced Model 🚀
        │                                   (OpenAI/Claude)
        │
        └─ NO
            │
            ├─ Analyze Complexity
            │   ├─ Get heuristic score (0-100)
            │   ├─ Query Ollama for assessment
            │   └─ Combine: (heuristic + ollama) / 2
            │
            ├─ Score < 33? ──► Simple ──► Ollama (local) 💰
            │
            ├─ 33 <= Score < 66? ──► Medium ──► Ollama (local) 💰
            │
            └─ Score >= 66? ──► Difficult ──► Advanced Model 🚀
                                              (if configured)
                                              else Ollama
```

## Extending the System

### Adding a New LLM Provider

Example: Adding Hugging Face Inference API

1. **Add method to LLMProvider** (`app/services/llm_provider.py`):

```python
def query_huggingface(
    self, prompt: str, model: str = "meta-llama/Llama-2-7b",
    temperature: float = 0.7
) -> Tuple[str, Dict[str, int]]:
    """Query Hugging Face Inference API"""
    try:
        from huggingface_hub import InferenceClient
        
        client = InferenceClient(api_key=self.hf_key)
        response = client.text_generation(
            prompt=prompt,
            model=model,
            temperature=temperature
        )
        
        tokens_used = {
            "prompt_tokens": len(prompt.split()),
            "response_tokens": len(response.split()),
        }
        tokens_used["total_tokens"] = (
            tokens_used["prompt_tokens"] + tokens_used["response_tokens"]
        )
        
        return response, tokens_used
    except Exception as e:
        logger.error(f"Error querying Hugging Face: {e}")
        raise
```

2. **Update config** (`app/core/config.py`):

```python
HUGGINGFACE_API_KEY: Optional[str] = None
HUGGINGFACE_MODEL: str = "meta-llama/Llama-2-7b"
```

3. **Update router** (`app/services/llm_provider.py` - `query()` method):

```python
def query(self, prompt: str, model: str = "ollama", ...):
    if model.lower() == "huggingface" or model.startswith("meta-llama"):
        return self.query_huggingface(prompt, model, temperature)
    # ... existing code
```

### Adding Custom Complexity Metrics

Edit `app/services/complexity_analyzer.py`:

```python
def _local_heuristic_score(self, prompt: str) -> float:
    score = 0
    
    # Add your custom metrics
    if self._contains_code_blocks(prompt):
        score += 20
    
    if self._requires_math(prompt):
        score += 25
    
    return min(score, 100)

def _contains_code_blocks(self, prompt: str) -> bool:
    return "```" in prompt or "<code>" in prompt

def _requires_math(self, prompt: str) -> bool:
    math_terms = ["equation", "calculate", "integral", "derivative"]
    return any(term in prompt.lower() for term in math_terms)
```

### Custom Caching Strategy

Create `app/cache/custom_cache.py`:

```python
class SemanticCacheManager(CacheManager):
    """Cache based on semantic similarity"""
    
    def get_similar(self, prompt: str, threshold: float = 0.9):
        """Find similar cached prompts"""
        # Use embedding model to find similar prompts
        # Return response if similarity > threshold
        pass
```

### Adding Analytics/Monitoring

Create `app/services/analytics.py`:

```python
class AnalyticsService:
    def track_event(self, event_type: str, data: Dict):
        """Track events for analytics"""
        pass
    
    def get_metrics(self, user_id: str) -> Dict:
        """Get user metrics"""
        pass
    
    def calculate_cost_savings(self, user_id: str) -> float:
        """Calculate cost savings from using local models"""
        pass
```

## Performance Optimization

### Caching Strategy
- Use Redis for production (supports TTL, clustering)
- Use in-memory for development
- Configure appropriate TTL for your use case

### Complexity Analysis Optimization
- Cache complexity scores
- Use async Ollama calls
- Implement complexity prediction model

### Token Counting
- Use tiktoken for accurate OpenAI token counting
- Implement local token estimation
- Cache token counts

## Security Considerations

1. **API Keys**
   - Never commit .env file
   - Use environment variables
   - Rotate keys regularly

2. **Input Validation**
   - Validate all incoming data
   - Use Pydantic schemas
   - Sanitize user inputs

3. **Rate Limiting**
   - Implement per-user rate limits
   - Add request throttling
   - Use Redis for distributed rate limiting

4. **Authentication**
   - Add JWT/API key authentication
   - Implement user roles
   - Log all access

## Testing Strategy

### Unit Tests
```bash
pytest tests/test_services.py
```

### Integration Tests
```bash
pytest tests/test_api.py
```

### Performance Tests
```bash
pytest tests/test_performance.py --benchmark
```

### Load Tests
```bash
locust -f tests/locustfile.py
```

## Deployment

### Docker Deployment
Create `Dockerfile`:
```dockerfile
FROM python:3.10-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["python", "main.py"]
```

### Docker Compose
```yaml
version: '3.8'
services:
  middleware:
    build: .
    ports:
      - "8000:8000"
  redis:
    image: redis:7
    ports:
      - "6379:6379"
  ollama:
    image: ollama/ollama
    ports:
      - "11434:11434"
```

## Monitoring & Logging

- **Logs**: See `app/core/logger.py`
- **Metrics**: Database queries via SQLAlchemy ORM
- **Alerting**: Implement custom alerting based on metrics

## Future Enhancements

1. ML-based complexity prediction
2. Semantic caching (similarity-based)
3. Cost optimization algorithms
4. Multi-language support
5. Streaming responses
6. WebSocket support
7. GraphQL API
8. Advanced analytics dashboard
9. A/B testing framework
10. Automated model selection
