# Adaptora

A self-hosted Dynamic API Agent with an MCP (Model Context Protocol) layer on top. Talk to any REST API in natural language — the agent discovers the docs, handles auth, plans the HTTP call, and executes it. Plug it into Claude Desktop, Cursor, Cline, n8n, or any MCP-compatible client to give your AI assistant access to **every API you can describe**.

> Bring-your-own-LLM. Runs locally with [Ollama](https://ollama.com) (default: `qwen2.5-coder:3b`). Optional Anthropic/OpenAI keys for tougher queries. No SaaS dependencies.

<p>
  <a href="https://github.com/guptayush02/adaptora/stargazers"><img src="https://img.shields.io/github/stars/guptayush02/adaptora?style=social" alt="GitHub stars"></a>
  <a href="./LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License: MIT"></a>
  <img src="https://img.shields.io/badge/python-3.11+-blue.svg" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/node-18+-green.svg" alt="Node 18+">
  <img src="https://img.shields.io/badge/PRs-welcome-brightgreen.svg" alt="PRs welcome">
</p>

---

## Demo

https://github.com/user-attachments/assets/62dad55a-a0a3-46d8-a689-bca21e9007db

*Setting up a tool in Adaptora and running it on the Docker stack — plays right here on GitHub.* ▶️ **[Watch in HD on YouTube](https://youtu.be/BoGareRAZJk)**

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

---

## Why Adaptora?

Connecting an LLM to real APIs usually breaks on the unglamorous parts: hunting
down docs, wiring up auth, hand-writing a JSON schema for every endpoint, and
one malformed argument silently killing the call. Adaptora owns that boundary
for you — point it at any API and it discovers the docs, stores your credentials
encrypted, turns every endpoint into a typed tool, and runs it from plain
language through **MCP, a REST API, or the web UI**.

---

## Key Features

- **Dynamic Tool Discovery** — Type a tool name (`github`, `stripe`, `shopify`, `notion`, …) or describe what you want to do, and the agent fetches its docs, OpenAPI spec, and rate limits automatically. Curated seed tools (github, aws, stripe, slack, notion, openai, razorpay, linear, gmail) ship pre-configured.
- **Multi-source doc fetching** — Web search + OpenAPI spec probing (24+ URL patterns) + native parsing + LLM extraction, merged with method/path deduplication. Refreshing `github` grows from 5 → 120+ endpoints; AWS uses local `boto3` introspection for 49+.
- **MCP Server** — Exposes the agent over the Model Context Protocol. Every connected tool's endpoints become typed MCP tools your AI assistant can call directly.
- **REST API + developer keys** — Mint a secret key on the dashboard and call Adaptora from any project in any language (`POST /api/v1/run` with `Authorization: Bearer adp_live_…`). Every call runs against your saved connections and is logged, tagged by key and tool, on the dashboard. A streaming variant (`POST /api/v1/run/stream`, Server-Sent Events) emits each pipeline step as it happens so you can render the agent's progress live in your own UI.
- **Live execution logs** — The dashboard **Logs** page tails every run from every source (Web UI, MCP, and `/api/v1`) in real time over SSE. In-flight runs appear as a live row at the top of the table that updates step-by-step, then settle into the completed-run history once done.
- **Authenticated chat UI** — React frontend with per-user encrypted credential storage (AES), conversation history, streaming SSE responses, and a "Cached Tools" page with live refresh progress.
- **Token tracking & caching** — Tracks every model call, caches identical prompts, routes simple queries to local Ollama and complex ones to Claude/GPT (optional).
- **One-command Docker deploy** — 4-container stack (app, Postgres, Redis, Ollama) wired with healthchecks and persistent volumes.

---

## Quick Start

### Option 1 — Docker (recommended)

The full stack runs in 4 containers (app + Postgres + Redis + Ollama). The first start downloads ~2 GB for `qwen2.5-coder:3b`; subsequent starts are fast thanks to a named volume.

```bash
git clone https://github.com/guptayush02/adaptora.git
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

The MCP server runs as a subprocess that any MCP client can talk to over JSON-RPC stdio — your AI assistant launches `python mcp_server.py`.

> **Important — the MCP server must talk to the *same* database as your web UI.** It reads credentials/connections by user, so if the two point at different databases, you'll see `User not found` and tools won't connect. Pick the launch style that matches how you run Adaptora:
>
> - **Running the full stack with Docker Compose?** The app stores everything in the Postgres container, *not* in a local `token_optimizer.db`. Launch the MCP server **inside the running container** with `docker exec` so it inherits the container's `DATABASE_URL`/`SECRET_KEY`. See [Docker stack](#quickest-path--claude-desktop-docker-stack) below.
> - **Running locally (no Docker)?** Launch host `python mcp_server.py` directly — it uses the same local SQLite DB the app does. See [Local install](#quickest-path--claude-desktop-local-install) below.
>
> A host `python mcp_server.py` started while the stack runs in Docker defaults to an empty local SQLite DB — that mismatch is the #1 cause of `User not found`.

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

Config file location:
- macOS: `~/Library/Application\ Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

> On macOS, quote the path if you `cat`/`cp` it — it contains a space (`Application Support`). Unquoted, the shell splits it into two paths and reads/writes the wrong file.

#### Quickest path — Claude Desktop (Docker stack)

Use this when you brought the stack up with `docker compose up`. The MCP server runs **inside** the `adaptora-app` container, so it automatically inherits the same Postgres `DATABASE_URL` and `SECRET_KEY` as the web app — you only pass your email.

```jsonc
{
  "mcpServers": {
    "adaptora": {
      "command": "/usr/local/bin/docker",
      "args": [
        "exec", "-i",
        "-e", "MCP_USER_EMAIL=you@example.com",
        "adaptora-app",
        "python", "mcp_server.py"
      ]
    }
  }
}
```

Prerequisites: the `adaptora-app` container must be running (`docker ps`), and `MCP_USER_EMAIL` must match an email that exists in the Postgres DB:

```bash
docker exec -i adaptora-db psql -U tokopt -d tokopt -c "SELECT id, email FROM users;"
```

#### Adaptora running on a remote server (VPS / cloud) — connect over SSH

The configs above launch the MCP server on your **own computer**. But if you've
deployed Adaptora on a remote machine (a DigitalOcean droplet, an AWS EC2
instance, a Hetzner VPS, your office server…), your AI assistant still runs on
your laptop — and it can't reach the server's database directly. Launching a
**local** `mcp_server.py` would talk to an empty local database and fail with
`User not found`.

The fix: tell your assistant to start the MCP server **on the remote machine,
over SSH**. SSH is the standard, secure way to run a command on another
computer; it carries the MCP messages back and forth over the same encrypted
connection your assistant already needs. No code changes, no extra ports to
open — if you can `ssh` into the box, this works.

```jsonc
{
  "mcpServers": {
    "adaptora": {
      "command": "ssh",
      "args": [
        "user@your-server.com",
        "docker", "exec", "-i",
        "-e", "MCP_USER_EMAIL=you@example.com",
        "adaptora-app",
        "python", "mcp_server.py"
      ]
    }
  }
}
```

**What is `user@your-server.com`?** It's the exact same thing you type to log
into your server with SSH — `ssh user@your-server.com` — split into two parts:

| Part | What it means | Examples |
|---|---|---|
| `user` (before the `@`) | Your **login username** on the server | `ubuntu` (common on AWS), `root`, `ayush` |
| `your-server.com` (after the `@`) | The server's **address** — its domain name *or* its public IP address | `adaptora.mycompany.com`, `203.0.113.42` |

So if you log into your server with `ssh ubuntu@203.0.113.42`, then you'd write
`"ubuntu@203.0.113.42"` on that first line. Don't copy `user@your-server.com`
literally — replace it with your real values.

**Before this works, check three things:**

1. **You can SSH in without typing a password.** Your assistant runs `ssh`
   unattended, so it can't answer a password prompt. Set up key-based login
   ([GitHub's SSH key guide](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/generating-a-new-ssh-key-and-adding-it-to-the-ssh-agent)
   works for any server) and confirm `ssh user@your-server.com` logs you in
   with no prompt.
2. **The `adaptora-app` container is running on the server.** SSH in and run
   `docker ps` — you should see `adaptora-app`.
3. **`MCP_USER_EMAIL` matches a real account.** Check on the server with the
   `psql` command shown just above.

> Not using Docker on the server? Replace the `docker exec …` part with the
> path to the remote Python and script, e.g.
> `"user@your-server.com", "/path/to/adaptora/venv/bin/python", "/path/to/adaptora/mcp_server.py"`,
> and move `MCP_USER_EMAIL` into an SSH-set env var or the command itself.

#### Quickest path — Claude Desktop (local install)

Use this when you run Adaptora directly on your host (no Docker) — the server shares the app's local SQLite DB.

```jsonc
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

## Using the REST API (developer keys)

Want to call Adaptora from your own app — a backend service, a script, a cron
job — instead of an MCP client? Mint a **developer secret key** on the dashboard
and hit the public REST API. The key authenticates as you, so every call runs
against the tools you've already connected.

### 1. Create a key

In the web UI, open **Developer Keys** in the sidebar → **New key** → give it a
name (e.g. `production-backend`). The secret (`adp_live_…`) is shown **once** —
copy it now; only its hash is stored, so it can never be retrieved again. Revoke
a key anytime from the same page (calls using it immediately start returning
`401`).

### 2. Call `POST /api/v1/run`

Send your prompt with the key as a bearer token. The agent identifies the right
service, plans the call, executes it against your saved credentials, and returns
the result:

```bash
curl -X POST http://localhost:8000/api/v1/run \
  -H "Authorization: Bearer adp_live_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "list my open github issues"}'
```

```python
# Python
import requests

resp = requests.post(
    "http://localhost:8000/api/v1/run",
    headers={"Authorization": "Bearer adp_live_YOUR_KEY"},
    json={"prompt": "list my open github issues"},
)
print(resp.json())
```

```javascript
// Node.js (fetch)
const resp = await fetch("http://localhost:8000/api/v1/run", {
  method: "POST",
  headers: {
    "Authorization": "Bearer adp_live_YOUR_KEY",
    "Content-Type": "application/json",
  },
  body: JSON.stringify({ prompt: "list my open github issues" }),
});
console.log(await resp.json());
```

**Request body**

| Field | Required | Description |
|---|---|---|
| `prompt` | yes | Natural-language instruction. The agent extracts intent + service automatically. |
| `language` | no | `"en"` (default) or `"hinglish"`. |

**Response** (shape):

```jsonc
{
  "log_id": 121,
  "status": "success",        // success | needs_credentials | needs_tool_setup | error
  "tool": "github",
  "summary": "You have 7 open issues…",
  "final_answer": "…",
  "http_status": 200,
  "response": { /* the upstream API's data */ },
  "error": null,
  "duration_ms": 842.1
}
```

If you haven't connected the target tool yet, `status` is `needs_credentials` —
connect it once in the web UI (see [Connecting OAuth2
Tools](#connecting-oauth2-tools-spotify-github-notion-google-slack)), then retry.

### 3. Stream the run live — `POST /api/v1/run/stream`

A slow run (cold Ollama, a multi-step plan) can take seconds. Instead of waiting
for the single JSON response, hit the **streaming** endpoint to receive each
pipeline step as a [Server-Sent Event](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events)
the moment it happens — then render the agent's progress in your own UI. Same
request body as `/api/v1/run`.

**Event types** — every frame is a standard SSE block (`event:` line + `data:`
line of JSON). The stream always ends with **exactly one** terminal event —
either `done` or `error` — so you can reliably close your reader and finalize
your UI when one arrives:

| `event:` | When | `data` payload |
|---|---|---|
| `step` | Once per pipeline stage, in order | `{ "step": "...", "run_uid": "...", "data": { ... } }` |
| `done` | Run finished successfully | The full `RunResponse` object (same shape as `/api/v1/run` above) |
| `error` | Run failed | `{ "error": "message" }` |

The `step` values arrive in this order (some may be skipped depending on the
run): `received` → `identifying_tool` → `tool_identified` → `looking_up_docs`
→ `checking_connection` → `planning_action` → `executing` → `summarizing`.
The `run_uid` is the same on every event of a run — use it to group events if
you fire several runs concurrently. Stage-specific details ride along in
`data` (e.g. `{"tool": "github"}` on `tool_identified`).

```bash
curl -N -X POST http://localhost:8000/api/v1/run/stream \
  -H "Authorization: Bearer adp_live_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "list my open github issues"}'
```

```
event: step
data: {"step": "identifying_tool", "run_uid": "a1b2…", "data": {}}

event: step
data: {"step": "tool_identified", "run_uid": "a1b2…", "data": {"tool": "github"}}

event: step
data: {"step": "executing", "run_uid": "a1b2…", "data": {}}

event: done
data: {"log_id": 121, "status": "success", "tool": "github", "summary": "You have 7 open issues…", ...}
```

```javascript
// Node.js — parse the SSE stream as it arrives
const resp = await fetch("http://localhost:8000/api/v1/run/stream", {
  method: "POST",
  headers: {
    "Authorization": "Bearer adp_live_YOUR_KEY",
    "Content-Type": "application/json",
  },
  body: JSON.stringify({ prompt: "list my open github issues" }),
});

const reader = resp.body.getReader();
const decoder = new TextDecoder();
let buffer = "";
while (true) {
  const { value, done } = await reader.read();
  if (done) break;
  buffer += decoder.decode(value, { stream: true });
  let sep;
  while ((sep = buffer.indexOf("\n\n")) !== -1) {
    const frame = buffer.slice(0, sep);
    buffer = buffer.slice(sep + 2);
    if (frame.startsWith(":")) continue; // keepalive comment
    const event = frame.match(/event: (.*)/)?.[1];
    const data = JSON.parse(frame.match(/data: (.*)/s)?.[1] || "{}");
    if (event === "step") console.log("step:", data.step, data.data);
    if (event === "done") console.log("result:", data);
  }
}
```

```python
# Python — stream events with httpx (pip install httpx)
import json
import httpx

with httpx.stream(
    "POST",
    "http://localhost:8000/api/v1/run/stream",
    headers={"Authorization": "Bearer adp_live_YOUR_KEY"},
    json={"prompt": "list my open github issues"},
    timeout=None,
) as resp:
    event = None
    for line in resp.iter_lines():
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data = json.loads(line[5:].strip())
            if event == "step":
                print("step:", data["step"], data.get("data"))
            elif event == "done":
                print("result:", data)
            elif event == "error":
                print("error:", data["error"])
```

> A keepalive comment is sent every 15 s so proxies (ALB / nginx / CloudFront)
> don't drop the connection during a long run. Use `curl -N` to disable curl's
> own buffering and see events as they stream.

### 4. See your logs

Every API call is recorded under **Logs** in the dashboard, tagged with the key
that made it and the tool it hit — and runs triggered over the API show up there
**live**, streaming step-by-step as a row at the top of the table even while the
`curl` is still in flight. Filter by **tool** or by **source**
(`API` vs `Web UI / MCP`) to find a specific call. Use a separate key per
project/environment so you can tell their traffic apart at a glance.

> **Keep keys secret.** They grant full access to your connected tools. Store
> them in environment variables / a secrets manager — never commit them. Behind
> a public deployment, terminate TLS so keys aren't sent in cleartext.

---

## Architecture

```
                ┌──────────────────────────────────────┐
                │           Frontend (React)           │
                │  Chat • Cached Tools • Logs (live)   │
                │     Developer Keys • Settings        │
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

## Connecting OAuth2 Tools (Spotify, GitHub, Notion, Google, Slack…)

OAuth2 tools need two steps: save your app credentials first, then complete the browser-based authorization to get an access token.

### Step 1 — Create an OAuth2 app on the provider

Every OAuth2 provider requires you to register an app and get a `client_id` / `client_secret`. During registration you must whitelist a **redirect URI**.

Adaptora uses **one redirect URI for all tools** — no matter how many OAuth2 tools you connect:

```
http://<your-adaptora-host>/api/dynamic-agent/oauth/callback
```

| Deployment | Redirect URI |
|---|---|
| Local Docker / dev | `http://localhost:8000/api/dynamic-agent/oauth/callback` |
| Custom domain | `https://adaptora.example.com/api/dynamic-agent/oauth/callback` |

Add this exact URL in your provider's developer console before proceeding.

**Provider-specific console links:**

| Tool | Where to add the redirect URI |
|---|---|
| Spotify | [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard) → your app → Edit Settings → Redirect URIs |
| GitHub | [github.com/settings/apps](https://github.com/settings/apps) or OAuth Apps → Authorization callback URL |
| Google | [console.cloud.google.com](https://console.cloud.google.com) → APIs & Services → Credentials → Authorized redirect URIs |
| Notion | [notion.so/my-integrations](https://www.notion.so/my-integrations) → your app → Redirect URIs |
| Slack | [api.slack.com/apps](https://api.slack.com/apps) → your app → OAuth & Permissions → Redirect URLs |

### Step 2 — Save credentials in the web UI

Open the Dynamic Agent page → **Tools & Connections** sidebar → connect to your tool and enter:
- `client_id`
- `client_secret`
- `scopes` (comma-separated, e.g. `user-library-read,user-top-read` for Spotify)

Click **Save & Connect**. The tool appears in the Connected list but is marked **not authorized** until Step 3.

### Step 3 — Authorize (browser OAuth2 flow)

In the **Connected** section of the sidebar, click the **Authorize** button next to your tool. This opens the provider's consent screen. After you grant permission, you're redirected back and the `access_token` is stored automatically. The tool is now fully authorized.

> The same redirect URI covers every OAuth2 tool — whitelist it once per Adaptora deployment, not once per tool.

### Token refresh

Adaptora automatically refreshes expired tokens using the stored `refresh_token` before each request. If a provider doesn't issue a refresh token, re-authorize via the **Authorize** button in the sidebar.

---

## Roadmap

- [ ] WebSocket transport for MCP server (in addition to stdio) — easier integration with browser clients
- [x] Per-tool credential vault rotation / refresh-token handling for OAuth2
- [ ] GraphQL support (for Linear, Shopify Admin)
- [ ] AsyncAPI / WebHook subscription support
- [ ] Audit-log export & replay (already stored in `dynamic_agent_runs` table)
- [ ] Pluggable LLM provider for the agent itself (currently Ollama-only)

---

## License

Adaptora is open source under the **MIT License** — free to use, modify, and
distribute, including for commercial purposes. The only requirement is that the
copyright notice and license text are retained in copies.

See [LICENSE](./LICENSE) for the full text.

---

## Contributing

PRs and issues welcome — see [CONTRIBUTING.md](./CONTRIBUTING.md).

---

## Contact

Questions, support, or partnership: [guptayush02@gmail.com](mailto:guptayush02@gmail.com)

Built by [Ayush Gupta](https://github.com/guptayush02).
