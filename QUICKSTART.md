# Quick Start Guide - LLM Token Optimizer Middleware

## 🎯 What is This?

This middleware sits between you and LLM models (OpenAI, Claude, Ollama) and:
- **Optimizes prompts** using local Ollama before sending to expensive APIs
- **Analyzes complexity** to route simple queries to local models (save money!)
- **Caches responses** to avoid redundant API calls
- **Tracks tokens** to monitor usage and costs
- **Supports bypass keywords** for urgent queries that need advanced models

## 📦 Prerequisites

1. **Ollama** (for local prompt optimization)
   ```bash
   # Install from https://ollama.ai
   ollama serve  # In terminal 1
   ```

2. **Pull a model** (in another terminal)
   ```bash
   ollama pull mistral  # or llama2, neural-chat, etc.
   ```

3. **Redis** (optional but recommended for caching)
   ```bash
   brew install redis
   redis-server
   ```

4. **API Keys** (optional, only if using OpenAI/Claude)
   - Get OpenAI key from https://platform.openai.com/
   - Get Anthropic key from https://console.anthropic.com/

## 🚀 Quick Start (5 minutes)

### 1. Setup
```bash
cd /Users/ayushgupta/Documents/projects/token-optimizer

# Copy environment file
cp .env.example .env

# Edit .env with your preferences (API keys optional)
# OLLAMA_API_URL=http://localhost:11434
# OPENAI_API_KEY=sk-... (optional)
# ANTHROPIC_API_KEY=sk-ant-... (optional)
```

### 2. Start the Middleware
```bash
python main.py
```

You'll see:
```
INFO:     Uvicorn running on http://0.0.0.0:8000
```

### 3. Open Another Terminal & Test
```bash
# Check health
curl http://localhost:8000/api/health

# Open API docs (interactive!)
open http://localhost:8000/docs
```

### 4. Send Your First Query
```bash
curl -X POST "http://localhost:8000/api/process" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "What is machine learning?",
    "model": "ollama",
    "temperature": 0.7,
    "user_id": "test_user"
  }'
```

### 5. Check Statistics
```bash
curl http://localhost:8000/api/stats/test_user
```

## 📚 API Endpoints

### Process Prompt
```bash
POST /api/process
Content-Type: application/json

{
  "prompt": "Your question here",
  "model": "ollama",           # or "gpt-4", "claude-3-opus"
  "temperature": 0.7,          # 0-2 (lower = more deterministic)
  "max_tokens": 500,           # optional
  "user_id": "your_user_id"    # for tracking
}
```

**Response:**
```json
{
  "response": "The answer...",
  "model_used": "ollama",
  "tokens_used": {
    "prompt_tokens": 10,
    "response_tokens": 150,
    "total_tokens": 160
  },
  "cache_hit": false,
  "complexity_level": "simple",
  "processing_time_ms": 450.25
}
```

### Get User Statistics
```bash
GET /api/stats/{user_id}
```

### Clear Cache
```bash
POST /api/cache/clear
```

## 🎯 How It Works - Flow Diagram

```
User Query
    ↓
1️⃣  Cache Check → Hit? Return cached response ✨
    ↓ (miss)
2️⃣  Bypass Keywords Check → Contains urgent/critical? → Route to Advanced Model 🚀
    ↓ (no bypass)
3️⃣  Complexity Analysis
    ↓
    ├─ Simple/Medium → Use Ollama (local, fast, free) 💰
    │
    └─ Difficult → Route to GPT-4/Claude (powerful but $$) 🧠
    ↓
4️⃣  Cache Response for future
    ↓
5️⃣  Track tokens in database
    ↓
Return Response to User ✅
```

## 🔑 Bypass Keywords

Include these words to force using advanced models (OpenAI/Claude):

- `urgent`
- `critical`
- `advanced`
- `direct`
- `llama-direct`

**Example:**
```json
{
  "prompt": "URGENT: Solve this complex optimization problem..."
}
```

## 💾 Caching Example

```bash
# First request (cache miss) - takes ~1 second
curl -X POST "http://localhost:8000/api/process" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "What is AI?", "model": "ollama", "user_id": "user1"}'

# Same prompt again (cache hit) - takes ~10ms
curl -X POST "http://localhost:8000/api/process" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "What is AI?", "model": "ollama", "user_id": "user1"}'
```

The second request is MUCH faster because response is cached!

## 📊 Understanding the Response

```json
{
  "response": "The actual LLM response",
  
  "model_used": "ollama",           // Which model was used
  
  "tokens_used": {
    "prompt_tokens": 10,             // Tokens in your prompt
    "response_tokens": 150,          // Tokens in response
    "total_tokens": 160              // Total (for billing)
  },
  
  "cache_hit": false,                // Was it cached?
  
  "complexity_level": "simple",      // simple/medium/difficult
  
  "processing_time_ms": 450.25,      // How long it took
  
  "prompt_optimization": "Saved 20 tokens (15%)"  // Optimization details
}
```

## ⚙️ Configuration (.env)

```env
# Ollama (local model for optimization)
OLLAMA_API_URL=http://localhost:11434
OLLAMA_MODEL=mistral

# Advanced LLM (optional)
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4

# Caching
CACHE_TYPE=redis                    # or "memory"
REDIS_URL=redis://localhost:6379/0

# Database
DATABASE_URL=sqlite:///./token_optimizer.db

# Complexity Thresholds (tokens)
SIMPLE_QUERY_THRESHOLD=100
MEDIUM_QUERY_THRESHOLD=500

# Bypass Keywords
BYPASS_KEYWORDS=urgent,critical,advanced,direct
```

## 💡 Real-World Examples

### Example 1: Simple Question (Uses Ollama)
```bash
curl -X POST "http://localhost:8000/api/process" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "What is Python?",
    "user_id": "user1"
  }'
# ✅ Processed by Ollama locally (fast & free)
```

### Example 2: Complex Problem (Auto-routes to GPT-4)
```bash
curl -X POST "http://localhost:8000/api/process" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Design a microservices architecture for a real-time collaborative editor with distributed state management...",
    "user_id": "user1"
  }'
# 🚀 Detected as difficult, routed to GPT-4 automatically
```

### Example 3: Force Advanced Model (Bypass)
```bash
curl -X POST "http://localhost:8000/api/process" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "URGENT: Fix this production bug - [code]",
    "user_id": "user1"
  }'
# 🔴 "URGENT" keyword detected, uses advanced model
```

## 🐛 Troubleshooting

### ❌ "Connection refused" error
**Solution:** Make sure Ollama is running
```bash
ollama serve  # In terminal 1
```

### ❌ "No module named 'openai'"
**Solution:** Dependencies not installed
```bash
pip install -r requirements.txt
```

### ❌ Cache not working
**Solution:** Redis not running (or in-memory cache mode)
```bash
redis-server   # Start Redis, or
# Edit .env: CACHE_TYPE=memory  # Use in-memory instead
```

### ❌ API keys not working
**Solution:** Check .env file has correct keys
```bash
# Verify your keys are in .env
cat .env | grep API_KEY
```

## 📈 Monitoring Usage

```bash
# Get user statistics
curl http://localhost:8000/api/stats/user1
```

**Sample output:**
```json
{
  "user_id": "user1",
  "total_queries": 45,
  "total_tokens": 8500,
  "average_tokens_per_query": 188.9,
  "models_used": {
    "ollama": 30,
    "gpt-4": 15
  }
}
```

💡 **Insight:** User ran 30 queries on Ollama (free) and only 15 on GPT-4 (paid). Nice savings!

## 🎓 Next Steps

1. **Read [README.md](./README.md)** for complete documentation
2. **Try [example_usage.py](./example_usage.py)** for Python examples
3. **Customize complexity thresholds** in `app/core/config.py`
4. **Add your own LLM provider** by extending `LLMProvider` class
5. **Setup production** with PostgreSQL + Redis

## 🔗 Useful Links

- 📖 **FastAPI Docs:** http://localhost:8000/docs (when running)
- 🤖 **Ollama:** https://ollama.ai
- 📊 **OpenAI API:** https://platform.openai.com/docs
- 🧠 **Anthropic Claude:** https://console.anthropic.com
- 📚 **Project README:** [README.md](./README.md)

## 🎉 Success!

You now have a production-ready middleware that:
- ✅ Saves money by using local models for simple queries
- ✅ Ensures quality by using advanced models for complex queries
- ✅ Speeds up responses through intelligent caching
- ✅ Tracks every token for cost analysis
- ✅ Provides flexible routing with bypass keywords

Happy optimizing! 🚀
