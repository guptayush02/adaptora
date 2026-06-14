# Contributing to Adaptora

Thanks for your interest in contributing. This guide covers the local dev setup, the project layout, and the conventions we use so PRs land smoothly.

---

## Quick dev loop

```bash
# One-time setup
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cd frontend && npm install && cd ..
cp .env.example .env

# Pull the local LLM (only needed if you don't already have it)
ollama pull qwen2.5-coder:3b

# Run backend (auto-reloads)
python -m uvicorn main:app --reload --port 8000

# Run frontend (separate terminal — Vite dev server with proxy to :8000)
cd frontend && npm run dev
```

For Docker-based development, see the README's Quick Start. The compose file binds Postgres / Redis / Ollama ports to localhost so you can mix-and-match (e.g. run the backend on the host but use containerised dependencies).

---

## Project layout

```
.
├── app/
│   ├── core/                 # Config, logging, encryption helpers
│   ├── db/                   # SQLAlchemy models + ad-hoc migrations
│   ├── services/             # Business logic (the bulk of the codebase)
│   │   ├── dynamic_agent_service.py    # Tool discovery, doc extraction, execution
│   │   ├── llm_provider.py             # Ollama / OpenAI / Anthropic routing
│   │   ├── complexity_analyzer.py      # Routing heuristics
│   │   └── prompt_optimizer.py         # Token-saving prompt rewrites
│   ├── routes/               # FastAPI routers (auth, api, dynamic_agent)
│   ├── mcp/                  # MCP server (wraps DynamicAgentService)
│   └── cache/                # Redis / in-memory cache layer
├── frontend/                 # React + Vite SPA
│   └── src/
│       ├── pages/            # Top-level routes (ToolsPage, ChatPage, …)
│       ├── components/       # Reusable UI (Sidebar, Modal, …)
│       └── services/api.js   # Backend client + SSE streaming
├── docker/                   # Docker assets (Ollama init script, …)
├── tests/                    # Pytest tests
├── docs/                     # Extended docs
├── main.py                   # FastAPI entry point
├── Dockerfile                # Multi-stage build
└── docker-compose.yml        # Full-stack runtime
```

---

## Where to add things

| Adding… | Goes in… |
|---|---|
| A new built-in tool (curated auth + base endpoints) | `_SEED_TOOLS` in [app/services/dynamic_agent_service.py](app/services/dynamic_agent_service.py) |
| An OpenAPI spec URL for an existing seed tool | `_OPENAPI_OVERRIDE_URLS` in the same file |
| A new probe URL pattern | `_OPENAPI_PROBE_PATHS` in the same file |
| A new API route | `app/routes/<area>.py`, then register in `main.py` |
| A new DB column | Add to the model + a migration block in [_ensure_sqlite_schema](app/db/database.py) |
| A new MCP tool | `_meta_tool_defs()` + a handler in [app/mcp/server.py](app/mcp/server.py) |
| A new frontend page | `frontend/src/pages/`, then a route in `App.jsx` and a sidebar entry |

---

## Coding conventions

### Python

- **Type hints** on all new public functions. Pydantic models for request/response schemas.
- **Logging over print**: use `app.core.logger.logger`.
- **Encrypt anything user-secret** with `app.core.security.encrypt_api_key` before persisting. Never log credential bodies.
- **Idempotent migrations**: schema changes live in `_ensure_sqlite_schema()` — guard each `ALTER TABLE` behind an inspector check (see the existing `tool_definitions` block for the pattern).
- **No hardcoded endpoints in seed expansion code**. If a tool gains endpoints, it's from the OpenAPI probe path, web extraction, or SDK introspection (like the `boto3` path for AWS). Curated `_SEED_TOOLS` entries are only for auth setup + a small "starter" endpoint set.

### JavaScript / React

- Functional components + hooks; no class components.
- Plain CSS in `src/styles/` — no CSS-in-JS or Tailwind (yet).
- Toasts for user feedback (`react-hot-toast` is already wired up).
- Streaming endpoints use the `fetch` + ReadableStream pattern in [services/api.js](frontend/src/services/api.js) — copy `streamRefreshTool` as a template.

### Commits & PRs

- **Conventional-style commit subjects** are appreciated but not enforced (`feat: …`, `fix: …`, `docs: …`).
- **One logical change per PR**. If you're refactoring while adding a feature, split it.
- **Tests for new features**. Smoke tests live in `tests/`, run with `pytest` (install `pytest pytest-asyncio` first — they're dev-only).
- **Migration safety**: if you add a column, verify the migration runs on an existing DB. Quick check:
  ```bash
  python -c "from app.db.database import init_db; init_db()"
  ```

---

## Adding a new MCP client integration

If you've wired this server up to a client that isn't documented yet (a new editor, a workflow tool, …), please add a section to [docs/MCP_CLIENTS.md](./docs/MCP_CLIENTS.md) with the exact config snippet. Future users will thank you.

---

## Reporting bugs

Open an issue with:

1. What you tried (the exact request / command).
2. What you expected to happen.
3. What actually happened (full error message + relevant logs from `docker compose logs app` or the uvicorn stdout).
4. Your environment: OS, Python version, Docker version, which LLM model.

For doc-extraction bugs (refresh returns the wrong endpoints), include the tool name and a link to its docs page so we can reproduce.

---

## Building with Cython (Optional)

To compile the core modules into unreadable `.so` (compiled) binaries while preserving the interface:

```bash
pip install cython
python setup.py build_ext --inplace
```

This replaces `app/services/dynamic_agent_service.py` and `app/services/llm_provider.py` with compiled versions. The app works identically from the outside, but the implementation is no longer readable — useful for public deployments where you want to protect customizations.

To revert:
```bash
git checkout app/services/*.py
```

---

## Security

If you find a vulnerability, please **email** [guptayush02@gmail.com](mailto:guptayush02@gmail.com) rather than opening a public issue. Common areas of concern:

- Credential decryption path
- Prompt-injection attacks against `identify_tool` / `plan_action`
- SSRF in the OpenAPI probe step

We treat these reports seriously and aim to ship a fix within 7 days for high-severity issues.

---

## License

By contributing, you agree that your contributions will be licensed under the same Business Source License 1.1 (BUSL-1.1) that covers the project.
