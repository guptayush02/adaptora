# Setup Checklist - Complete Your Setup

Follow this checklist to get your LLM Token Optimizer running in 30 minutes.

## ✅ Step 1: Prerequisites (5 minutes)

- [ ] Python 3.8+ installed
  ```bash
  python3 --version
  ```

- [ ] Git installed (for version control)
  ```bash
  git --version
  ```

- [ ] Download Ollama from https://ollama.ai
- [ ] Download Redis (optional but recommended)

## ✅ Step 2: Install Ollama

- [ ] Install Ollama from https://ollama.ai
- [ ] Start Ollama service
  ```bash
  ollama serve
  ```
- [ ] In another terminal, pull a model
  ```bash
  ollama pull mistral
  ```
- [ ] Verify Ollama is working
  ```bash
  curl http://localhost:11434/api/tags
  ```

## ✅ Step 3: Project Setup (10 minutes)

- [ ] Navigate to project directory
  ```bash
  cd /Users/ayushgupta/Documents/projects/token-optimizer
  ```

- [ ] Create and activate virtual environment
  ```bash
  python3 -m venv venv
  source venv/bin/activate
  ```

- [ ] Install dependencies
  ```bash
  pip install -r requirements.txt
  ```

- [ ] Copy environment file
  ```bash
  cp .env.example .env
  ```

- [ ] Edit `.env` file (optional - defaults are configured)
  ```bash
  # View the file
  cat .env
  
  # Edit if needed
  nano .env
  ```

## ✅ Step 4: Database Setup (2 minutes)

- [ ] Initialize database
  ```bash
  python -c "from app.db.database import init_db; init_db()"
  ```

- [ ] Verify database was created
  ```bash
  ls -la token_optimizer.db
  ```

## ✅ Step 5: Start the Middleware (1 minute)

- [ ] Start the middleware server
  ```bash
  python main.py
  ```

- [ ] Verify server is running
  ```bash
  # In another terminal, check health
  curl http://localhost:8000/api/health
  ```

- [ ] Expected response:
  ```json
  {"status": "healthy", "message": "LLM Middleware is running"}
  ```

## ✅ Step 6: Test the API (5 minutes)

- [ ] Test simple query
  ```bash
  curl -X POST "http://localhost:8000/api/process" \
    -H "Content-Type: application/json" \
    -d '{"prompt": "What is AI?", "user_id": "test_user"}'
  ```

- [ ] Test cache hit (run same query again)
  ```bash
  curl -X POST "http://localhost:8000/api/process" \
    -H "Content-Type: application/json" \
    -d '{"prompt": "What is AI?", "user_id": "test_user"}'
  ```

- [ ] Check user statistics
  ```bash
  curl http://localhost:8000/api/stats/test_user
  ```

- [ ] Open interactive docs
  ```bash
  open http://localhost:8000/docs
  ```

## ✅ Step 7: Optional - Setup Redis (5 minutes)

- [ ] Install Redis
  ```bash
  brew install redis   # macOS
  # or use Docker: docker run -d -p 6379:6379 redis:7
  ```

- [ ] Start Redis
  ```bash
  redis-server
  ```

- [ ] Verify Redis is running
  ```bash
  redis-cli ping
  # Expected: PONG
  ```

- [ ] Update `.env` to use Redis
  ```bash
  CACHE_TYPE=redis
  REDIS_URL=redis://localhost:6379/0
  ```

## ✅ Step 8: Optional - Add API Keys

For advanced models (not required - Ollama works standalone):

- [ ] Get OpenAI API Key
  - Visit https://platform.openai.com/account/api-keys
  - Copy your key

- [ ] Add to `.env`
  ```bash
  OPENAI_API_KEY=sk-YOUR_KEY_HERE
  ```

- [ ] Get Anthropic API Key (optional)
  - Visit https://console.anthropic.com/account/keys
  - Copy your key

- [ ] Add to `.env`
  ```bash
  ANTHROPIC_API_KEY=sk-ant-YOUR_KEY_HERE
  ```

## ✅ Step 9: Try Example Script

- [ ] Run example usage script
  ```bash
  python example_usage.py
  ```

- [ ] Observe outputs:
  - ✅ Health check passed
  - ✅ Simple query processed
  - ✅ Cache mechanism working
  - ✅ User statistics available

## ✅ Step 10: Read Documentation

- [ ] Read [QUICKSTART.md](./QUICKSTART.md) for quick reference
- [ ] Read [README.md](./README.md) for full documentation
- [ ] Read [ARCHITECTURE.md](./ARCHITECTURE.md) to understand the system
- [ ] Read [API_EXAMPLES.md](./API_EXAMPLES.md) for cURL examples

## ✅ Optional: Production Setup

- [ ] Read [DEPLOYMENT.md](./DEPLOYMENT.md)
- [ ] Create Docker setup for containers
- [ ] Setup PostgreSQL for database
- [ ] Configure Redis cluster for caching
- [ ] Setup monitoring and logging
- [ ] Configure CI/CD pipeline

## ✅ Troubleshooting Checklist

### If Ollama connection fails:
- [ ] Check Ollama is running: `ollama serve`
- [ ] Check OLLAMA_API_URL in .env
- [ ] Try manual curl: `curl http://localhost:11434/api/tags`
- [ ] Check firewall settings

### If database connection fails:
- [ ] Check DATABASE_URL in .env
- [ ] Verify database file exists: `ls -la token_optimizer.db`
- [ ] Reinitialize: `python -c "from app.db.database import init_db; init_db()"`

### If Redis connection fails:
- [ ] Check Redis is running: `redis-cli ping`
- [ ] Check REDIS_URL in .env
- [ ] Fallback to in-memory: `CACHE_TYPE=memory`

### If middleware won't start:
- [ ] Check Python version: `python3 --version` (need 3.8+)
- [ ] Reinstall dependencies: `pip install -r requirements.txt`
- [ ] Check port 8000 is available: `lsof -i :8000`
- [ ] Check error logs carefully

### If API requests timeout:
- [ ] Check Ollama is running
- [ ] Check model is installed: `ollama pull mistral`
- [ ] Increase timeout for slow networks
- [ ] Check system resources (RAM, CPU)

## 📊 Verification Commands

Run these commands to verify everything is working:

```bash
# 1. Check Python
python3 --version

# 2. Check Ollama
curl -s http://localhost:11434/api/tags | python3 -m json.tool

# 3. Check Middleware
curl -s http://localhost:8000/api/health | python3 -m json.tool

# 4. Check Database
ls -la token_optimizer.db

# 5. Check Redis (optional)
redis-cli ping

# 6. Check Environment
cat .env
```

## 🎯 Success Indicators

You'll know everything is working when:

- [ ] `curl http://localhost:8000/api/health` returns `{"status": "healthy"}`
- [ ] `python main.py` starts without errors
- [ ] `ollama serve` shows models available
- [ ] `redis-cli ping` returns `PONG` (if using Redis)
- [ ] First API request takes ~1 second
- [ ] Second identical API request takes <100ms (cache hit)
- [ ] User statistics endpoint returns valid JSON
- [ ] Interactive docs work at http://localhost:8000/docs

## 📞 Quick Help

| Problem | Solution |
|---------|----------|
| "Connection refused" | Start Ollama: `ollama serve` |
| "Module not found" | Install deps: `pip install -r requirements.txt` |
| "Port already in use" | Kill process: `lsof -i :8000 \| grep LISTEN \| awk '{print $2}' \| xargs kill` |
| "Database locked" | Delete and reinit: `rm token_optimizer.db && python -c "from app.db.database import init_db; init_db()"` |
| "Slow responses" | Check Ollama is running and model is loaded |

## 🚀 Next Steps After Setup

1. **Customize Configuration**
   - Edit complexity thresholds in `app/core/config.py`
   - Add bypass keywords to `.env`
   - Configure cache TTL

2. **Integrate with Your App**
   - Use the API endpoints in your application
   - Send prompts to `POST /api/process`
   - Track user statistics with `GET /api/stats/{user_id}`

3. **Monitor Usage**
   - Check token usage regularly
   - Monitor cache hit rates
   - Track cost savings

4. **Deploy to Production**
   - Follow [DEPLOYMENT.md](./DEPLOYMENT.md)
   - Setup Docker containers
   - Configure PostgreSQL + Redis

5. **Extend the System**
   - Add new LLM providers (see [ARCHITECTURE.md](./ARCHITECTURE.md))
   - Implement custom complexity metrics
   - Add monitoring and alerting

## 📚 Documentation Map

```
├── README.md              ← Start here for complete overview
├── QUICKSTART.md          ← Get running in 5 minutes
├── API_EXAMPLES.md        ← cURL examples and API reference
├── ARCHITECTURE.md        ← System design and extension guide
├── DEPLOYMENT.md          ← Production setup guide
├── PROJECT_SUMMARY.md     ← High-level overview
├── SETUP_CHECKLIST.md     ← This file!
└── example_usage.py       ← Python usage examples
```

## ✨ You're All Set!

Congratulations! Your LLM Token Optimizer Middleware is now running!

**Next: Read [QUICKSTART.md](./QUICKSTART.md) for usage examples or start sending queries to `/api/process`!**

---

**Questions?**
- Check docs at http://localhost:8000/docs
- See [API_EXAMPLES.md](./API_EXAMPLES.md) for cURL examples
- Read [ARCHITECTURE.md](./ARCHITECTURE.md) for technical details
- Follow [DEPLOYMENT.md](./DEPLOYMENT.md) for production setup
