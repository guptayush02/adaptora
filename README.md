# Adaptora

A self-hosted Dynamic API Agent with an MCP (Model Context Protocol) layer on top. Talk to any REST API in natural language — the agent discovers the docs, handles auth, plans the HTTP call, and executes it. Plug it into Claude Desktop, Cursor, Cline, n8n, or any MCP-compatible client to give your AI assistant access to **every API you can describe**.

> Bring-your-own-LLM. Runs locally with [Ollama](https://ollama.com) (default: `qwen2.5-coder:3b`). Optional Anthropic/OpenAI keys for tougher queries. No SaaS dependencies.

---

## Key Features

- **Dynamic Tool Discovery** — Type a tool name (`github`, `stripe`, `shopify`, `notion`, …) or describe what you want to do, and the agent fetches its docs, OpenAPI spec, and rate limits automatically. Curated seed tools (github, aws, stripe, slack, notion, openai, razorpay, linear, gmail) ship pre-configured.
- **Multi-source doc fetching** — Web search + OpenAPI spec probing (24+ URL patterns) + native parsing + LLM extraction, merged with method/path deduplication. Refreshing `github` grows from 5 → 120+ endpoints; AWS uses local `boto3` introspection for 49+.
- **MCP Server** — Exposes the agent over the Model Context Protocol. Every connected tool's endpoints become typed MCP tools your AI assistant can call directly.
- **Authenticated chat UI** — React frontend with per-user encrypted credential storage (AES), conversation history, streaming SSE responses, and a "Cached Tools" page with live refresh progress.
- **Token tracking & caching** — Tracks every model call, caches identical prompts, routes simple queries to local Ollama and complex ones to Claude/GPT (optional).
- **One-command Docker deploy** — 4-container stack (app, Postgres, Redis, Ollama) wired with healthchecks and persistent volumes.

---

## License

Adaptora is source-available under the **Business Source License 1.1** (BUSL-1.1).

- **Free for**: personal use, self-hosted non-commercial deployments, evaluation, and open-source contributions.
- **Commercial use** (running Adaptora as a hosted service, embedding it in a paid product, or selling access to it) requires a separate commercial license — [contact us](mailto:guptayush02@gmail.com).
- **Converts to Apache 2.0** on 2030-06-15, four years after the initial release.

See [LICENSE](./LICENSE) for the full text.

---

## Demo

```
> "list my open GitHub issues assigned to me"

[agent] identifying tool... github
[agent] loading docs... 122 endpoints cached
[agent] planning action... GET /issues?filter=assigned&state=open
[agent] executing...
[agent] You have 7 open issues. Top 3:
        1. #482 — Bug: cache invalidation race  (opened 2 days ago)
        2. #481 — Doc fetcher should support YAML specs
        3. #475 — Streaming endpoint for /tools/refresh
```

*(Screenshots & GIF — coming soon.)*

---

## Quick Start

### Option 1 — Docker (recommended)

The full stack runs in 4 containers (app + Postgres + Redis + Ollama). The first start downloads ~2 GB for `qwen2.5-coder:3b`; subsequent starts are fast thanks to a named volume.

```bash
git clone https://github.com/ayushgupta02/adaptora.git
cd adaptora

# 1. Configure (only secrets — infra URLs are wired to compose service names)
cp .env.docker.example .env.docker
# edit .env.docker — at minimum set SECRET_KEY

# 2. Bring up the stack
docker compose --env-file .env.docker up --build

# 3. Open the web UI
open http://localhost:8000
```

The first Ollama model pull happens in the background — the app's `start_period` healthcheck (300 s) absorbs the wait without flapping. Watch progress with `docker compose logs -f ollama`.

#### GPU acceleration (optional)

If you have an NVIDIA GPU and the [nvidia-container-toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) installed, uncomment the `deploy.resources.devices` block in [docker-compose.yml](./docker-compose.yml) for ~10× faster inference.

### Option 2 — Local (no Docker)

Useful for development. You'll need Python 3.11+, Node 18+, Ollama, and Redis running on your host.

```bash
# Backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Pull the LLM
ollama pull qwen2.5-coder:3b

# Frontend
cd frontend && npm install && npm run build && cd ..

# Configure
cp .env.example .env   # edit OLLAMA_API_URL, REDIS_URL, etc.

# Run (DB auto-initialises on first start)
python -m uvicorn main:app --host 0.0.0.0 --port 8000
# open http://localhost:8000
```

---

## Using the MCP Server

The MCP server runs as a subprocess that any MCP client can talk to over JSON-RPC stdio. It's the same Python process whether you're inside Docker or running locally — your AI assistant just launches `python mcp_server.py`.

### What you get

| Always-on meta-tools | What it does |
|---|---|
| `setup_new_tool` | Discover docs for any tool (web search → OpenAPI probe → LLM extract → merge) and seed it |
| `refresh_tool_docs` | Re-fetch the latest docs (equivalent to the UI's Refresh button) |
| `list_known_tools` | Every cached tool with endpoint counts |
| `list_connections` | Which tools you've authenticated |
| `run_action` | Natural-language dispatch through the full Dynamic Agent pipeline |

**Plus dynamic per-endpoint tools**: every endpoint of every connected tool becomes its own MCP tool with a typed input schema (`github_list_repos`, `stripe_create_charge`, etc.). Newly connected tools appear automatically — no restart required.

### Setup for various clients

Full step-by-step configs for 8+ clients are in [docs/MCP_CLIENTS.md](./docs/MCP_CLIENTS.md):

- **Claude Desktop** (macOS / Windows)
- **Claude Code** (Anthropic CLI)
- **Cursor** (IDE)
- **Cline** (VS Code extension)
- **Continue.dev** (VS Code / JetBrains)
- **Zed** (editor)
- **n8n / make.com** (workflow automation)
- **Custom Python / TypeScript clients**

### Quickest path — Claude Desktop

```jsonc
// ~/Library/Application Support/Claude/claude_desktop_config.json  (macOS)
// %APPDATA%\Claude\claude_desktop_config.json                       (Windows)
{
  "mcpServers": {
    "adaptora": {
      "command": "/ABSOLUTE/PATH/TO/adaptora/venv/bin/python",
      "args": ["/ABSOLUTE/PATH/TO/adaptora/mcp_server.py"],
      "env": { "MCP_USER_EMAIL": "you@example.com" }
    }
  }
}
```

Restart Claude Desktop. The hammer icon now lists `setup_new_tool`, `run_action`, and every connected tool's endpoints.

### Quickest path — Claude Code (CLI)

```bash
# Find which email your web-UI account uses
/ABSOLUTE/PATH/TO/adaptora/venv/bin/python \
  /ABSOLUTE/PATH/TO/adaptora/mcp_server.py --list-users

# Register the server
claude mcp add adaptora \
  --scope user \
  --transport stdio \
  --env MCP_USER_EMAIL=you@example.com \
  -- \
  /ABSOLUTE/PATH/TO/adaptora/venv/bin/python \
  /ABSOLUTE/PATH/TO/adaptora/mcp_server.py
```

Verify:
```bash
claude mcp list
# adaptora: … - ✓ Connected
```

Start a session:
```bash
claude
> /mcp                              # confirms adaptora is listed
> List my open GitHub issues        # → calls run_action under the hood
> Set up shopify with the Admin API # → calls setup_new_tool
> Refresh the docs for stripe       # → calls refresh_tool_docs
```

---

## Architecture

```
                ┌──────────────────────────────────────┐
                │           Frontend (React)           │
                │   Chat • Cached Tools • Settings     │
                └─────────────────┬────────────────────┘
                                  │ HTTPS (same origin)
                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│                          FastAPI Backend                            │
│                                                                     │
│   ┌──────────────┐    ┌──────────────────┐    ┌────────────────┐    │
│   │  /api/auth   │    │ /api/dynamic-    │    │  /api/process  │    │
│   │   JWT        │    │ agent/*          │    │  /api/optimize │    │
│   │              │    │  (turn, tools,   │    │  (token opt.)  │    │
│   │              │    │   refresh, …)    │    │                │    │
│   └──────────────┘    └────────┬─────────┘    └────────┬───────┘    │
│                                │                       │            │
│                                ▼                       │            │
│                  ┌─────────────────────────┐           │            │
│                  │  DynamicAgentService    │           │            │
│                  │  identify → docs →      │           │            │
│                  │  connection → plan →    │           │            │
│                  │  execute → summarize    │           │            │
│                  └────────┬────────────────┘           │            │
└───────────────────────────┼────────────────────────────┼────────────┘
                            │                            │
       ┌────────────────────┼──────────────┐             │
       ▼                    ▼              ▼             ▼
┌─────────────┐    ┌──────────────┐  ┌──────────┐  ┌──────────────┐
│ Ollama LLM  │    │  SQLite /    │  │  Redis   │  │ External APIs│
│ qwen2.5-    │    │  Postgres    │  │ (cache)  │  │ GitHub, AWS, │
│ coder:3b    │    │  (tools,     │  │          │  │ Stripe, …    │
│             │    │   creds enc, │  │          │  │              │
└─────────────┘    └──────────────┘  └──────────┘  └──────────────┘
       ▲
       │ stdio JSON-RPC
       │
┌──────┴────────────────────────────┐
│   MCP clients                     │
│   Claude Desktop, Cursor, Cline,  │
│   Continue, Zed, n8n, custom      │
└───────────────────────────────────┘
```

See [ARCHITECTURE.md](./ARCHITECTURE.md) for a deeper dive into the agent pipeline, doc-extraction strategy, OpenAPI parser, and credential vault.

---

## Configuration

The agent is configured via environment variables. See [.env.example](./.env.example) (local) or [.env.docker.example](./.env.docker.example) (Docker).

| Var | Purpose | Default |
|---|---|---|
| `OLLAMA_API_URL` | Where the local LLM lives | `http://localhost:11434` (docker: `http://ollama:11434`) |
| `OLLAMA_MODEL` | Which model to use | `qwen2.5-coder:3b` |
| `DATABASE_URL` | SQLAlchemy URL | `sqlite:///./adaptora.db` (docker: Postgres) |
| `REDIS_URL` | Cache | `redis://localhost:6379/0` |
| `SECRET_KEY` | JWT signing — **change in production** | (placeholder) |
| `TAVILY_API_KEY` | Optional — best web search for AI agents | unset |
| `GOOGLE_API_KEY` / `GOOGLE_CSE_ID` | Optional — Google Custom Search fallback | unset |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | Optional — for cloud-LLM routing on complex queries | unset |
| `MCP_USER_EMAIL` | Which DB user the MCP server impersonates | unset (defaults to user ID 1) |

---

## Roadmap

- [ ] WebSocket transport for MCP server (in addition to stdio) — easier integration with browser clients
- [ ] Per-tool credential vault rotation / refresh-token handling for OAuth2
- [ ] GraphQL support (for Linear, Shopify Admin)
- [ ] AsyncAPI / WebHook subscription support
- [ ] Audit-log export & replay (already stored in `dynamic_agent_runs` table)
- [ ] Pluggable LLM provider for the agent itself (currently Ollama-only)

---

## Contributing

PRs and issues welcome — see [CONTRIBUTING.md](./CONTRIBUTING.md).

---

## Contact

Questions, commercial licensing, or partnership: [guptayush02@gmail.com](mailto:guptayush02@gmail.com)

Built by [Ayush Gupta](https://github.com/ayushgupta02).
