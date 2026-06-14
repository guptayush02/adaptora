# MCP Client Setup

How to plug the Adaptora MCP server into the major MCP-compatible clients. The Adaptora MCP server speaks JSON-RPC over **stdio** — the standard transport every client supports.

> **Prerequisite**: Adaptora installed locally (either via `pip install -r requirements.txt` or running in Docker — see the [main README](../README.md) for setup). The MCP server is just `python mcp_server.py` from the project root — and because the wrapper handles `sys.path` setup, it works from any cwd.

For Docker users: see the [Docker section](#running-the-mcp-server-from-a-docker-container) at the bottom.

---

## Which user does MCP run as?

Credentials are stored per-user in the database. If you signed up at the web UI as `you@example.com` and saved your AWS access keys, those keys are scoped to your user ID — **not** to the MCP server. You have to tell the MCP server which user to act as.

Two env vars control this (in priority order):

| Env var | What it does |
|---|---|
| `MCP_USER_EMAIL` | **Recommended.** Looked up at startup against `User.email` (case-insensitive). Set this to the email you signed up with. |
| `MCP_USER_ID` | Numeric fallback. Defaults to `1` — almost always wrong if you signed up as the second-or-later user. |

If neither matches, the agent will report `needs_credentials` for every tool — even tools you've fully connected — because it's looking under the wrong user.

**Find which email/ID you signed up with**:

```bash
python /path/to/adaptora/mcp_server.py --list-users
```

Output:
```
  ID  EMAIL                                     USERNAME
────  ────────────────────────────────────────  ────────
   1  agent_smoketest@test.local                agent_smoketest
   2  you@example.com                           you
```

Use `MCP_USER_EMAIL=you@example.com` in every example below.

---

## Table of contents

- [Claude Desktop](#claude-desktop) (macOS / Windows)
- [Claude Code](#claude-code) (Anthropic CLI)
- [Cursor](#cursor)
- [Cline](#cline) (VS Code extension)
- [Continue.dev](#continuedev)
- [Zed](#zed)
- [n8n](#n8n)
- [Custom Python client](#custom-python-client)
- [Docker](#running-the-mcp-server-from-a-docker-container)
- [Troubleshooting](#troubleshooting)

---

## Claude Desktop

The flagship MCP client from Anthropic.

**Config file**:
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

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

Restart Claude Desktop. Look for the hammer / wrench icon in the chat input — it now lists `setup_new_tool`, `run_action`, plus every connected tool's endpoints.

**Note**: The MCP server auto-resolves its own project root on startup, so no `cwd` field is needed. `command` should be the absolute path of the venv Python where Adaptora's deps are installed. If you didn't use a venv, `"python3"` works as long as `pip install -r requirements.txt` was run against that Python.

---

## Claude Code

Anthropic's CLI ([install guide](https://docs.claude.com/en/docs/claude-code)). The Adaptora MCP server auto-resolves its own project root, so you don't need a `--cwd` flag.

### Recommended — use the venv's Python directly

Replace `/ABSOLUTE/PATH/TO/adaptora` with your actual install path:

```bash
claude mcp add adaptora \
  --scope user \
  --transport stdio \
  --env MCP_USER_EMAIL=you@example.com \
  -- \
  /ABSOLUTE/PATH/TO/adaptora/venv/bin/python \
  /ABSOLUTE/PATH/TO/adaptora/mcp_server.py
```

What each flag does:

| Flag | Why |
|---|---|
| `--scope user` | Available across **all** your projects (stored in `~/.claude.json`). Use `--scope project` to share via a checked-in `.mcp.json` instead. |
| `--transport stdio` | The standard transport for desktop / CLI MCP clients. |
| `--env MCP_USER_EMAIL=…` | Tells the server which DB user to scope connections to. Use the email you signed up with in the web UI. |
| `--` | Stops `claude` from parsing the rest as its own flags. |
| `/ABSOLUTE/PATH/.../venv/bin/python` | Use the project's venv Python so all deps (`mcp`, `fastapi`, `sqlalchemy`, …) are available. |
| `mcp_server.py` (full path) | Thin wrapper at the repo root that sets up `sys.path`. Works from any cwd. |

### Verify the server is registered

```bash
claude mcp list
# adaptora: /ABSOLUTE/PATH/.../venv/bin/python /ABSOLUTE/PATH/.../mcp_server.py - ✓ Connected

claude mcp get adaptora
```

### Use it inside Claude Code

```bash
claude
> /mcp                              # confirms adaptora is listed
> List my open GitHub issues        # → calls run_action
> Set up shopify so I can list products  # → calls setup_new_tool
> Refresh the docs for stripe       # → calls refresh_tool_docs
```

### If you don't use a venv (system Python)

```bash
claude mcp add adaptora \
  --scope user \
  --transport stdio \
  --env MCP_USER_EMAIL=you@example.com \
  -- \
  python3 /ABSOLUTE/PATH/TO/adaptora/mcp_server.py
```

### Per-project setup (team-shared)

Drop a `.mcp.json` in the repo root:

```jsonc
{
  "mcpServers": {
    "adaptora": {
      "type": "stdio",
      "command": "/ABSOLUTE/PATH/TO/adaptora/venv/bin/python",
      "args": ["/ABSOLUTE/PATH/TO/adaptora/mcp_server.py"],
      "env": { "MCP_USER_EMAIL": "you@example.com" }
    }
  }
}
```

### Removing the server

```bash
claude mcp remove adaptora
```

---

## Cursor

Cursor supports MCP servers via `~/.cursor/mcp.json` (global) or `<project>/.cursor/mcp.json` (per-project).

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

Reload Cursor. The MCP indicator (lower right) shows `adaptora: connected`.

---

## Cline

[Cline](https://github.com/cline/cline) is a VS Code extension. Open Cline's MCP settings:

1. Open VS Code → Cline panel → Settings (gear icon)
2. Click **"Configure MCP Servers"** — this opens `cline_mcp_settings.json`
3. Add:

```jsonc
{
  "mcpServers": {
    "adaptora": {
      "command": "/ABSOLUTE/PATH/TO/adaptora/venv/bin/python",
      "args": ["/ABSOLUTE/PATH/TO/adaptora/mcp_server.py"],
      "env": { "MCP_USER_EMAIL": "you@example.com" },
      "disabled": false,
      "autoApprove": ["list_known_tools", "list_connections"]
    }
  }
}
```

`autoApprove` lets Cline call read-only meta-tools without prompting you each time. Keep write tools out of this list.

---

## Continue.dev

[Continue](https://continue.dev/) is a VS Code / JetBrains extension. Edit `~/.continue/config.yaml`:

```yaml
mcpServers:
  - name: adaptora
    command: /ABSOLUTE/PATH/TO/adaptora/venv/bin/python
    args:
      - /ABSOLUTE/PATH/TO/adaptora/mcp_server.py
    env:
      MCP_USER_EMAIL: "you@example.com"
```

Restart your IDE. Continue's chat now sees the agent's tools.

---

## Zed

[Zed](https://zed.dev/) supports MCP via its `context_servers` extension API. In `~/.config/zed/settings.json`:

```jsonc
{
  "context_servers": {
    "adaptora": {
      "command": {
        "path": "/ABSOLUTE/PATH/TO/adaptora/venv/bin/python",
        "args": ["/ABSOLUTE/PATH/TO/adaptora/mcp_server.py"],
        "env": { "MCP_USER_EMAIL": "you@example.com" }
      },
      "settings": {}
    }
  }
}
```

---

## n8n

In the MCP node:

- **Server Type**: Custom (stdio)
- **Command**: `/ABSOLUTE/PATH/TO/adaptora/venv/bin/python`
- **Arguments**: `/ABSOLUTE/PATH/TO/adaptora/mcp_server.py`
- **Environment Variables**: `MCP_USER_EMAIL=you@example.com`

Then drop the MCP node into a workflow — the available tools populate automatically.

> **Tip**: For n8n running in Docker, mount the Adaptora project as a volume and use the container path.

---

## Custom Python client

```python
import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

server_params = StdioServerParameters(
    command="/ABSOLUTE/PATH/TO/adaptora/venv/bin/python",
    args=["/ABSOLUTE/PATH/TO/adaptora/mcp_server.py"],
    env={"MCP_USER_EMAIL": "you@example.com"},
)

async def main():
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            print(f"available tools: {len(tools.tools)}")

            result = await session.call_tool(
                "setup_new_tool", {"tool": "shopify"}
            )
            print(result.content[0].text)

            result = await session.call_tool(
                "run_action", {"prompt": "list my open GitHub issues"}
            )
            print(result.content[0].text)

asyncio.run(main())
```

TypeScript clients work the same way — see the [@modelcontextprotocol/sdk](https://github.com/modelcontextprotocol/typescript-sdk) docs.

---

## Running the MCP server from a Docker container

### Option A — Run the MCP server on the host, hit the dockerised backend

Install the project deps on the host (`pip install -r requirements.txt`) and point its config at the container's Postgres / Redis / Ollama:

```jsonc
{
  "mcpServers": {
    "adaptora": {
      "command": "python",
      "args": ["/ABSOLUTE/PATH/TO/adaptora/mcp_server.py"],
      "env": {
        "MCP_USER_EMAIL": "you@example.com",
        "DATABASE_URL": "postgresql+psycopg2://tokopt:tokopt@localhost:5432/tokopt",
        "REDIS_URL": "redis://localhost:6379/0",
        "OLLAMA_API_URL": "http://localhost:11434"
      }
    }
  }
}
```

### Option B — `docker exec` into the app container

```jsonc
{
  "mcpServers": {
    "adaptora": {
      "command": "docker",
      "args": [
        "exec", "-i",
        "adaptora-app",
        "python", "/app/mcp_server.py"
      ],
      "env": { "MCP_USER_EMAIL": "you@example.com" }
    }
  }
}
```

---

## Troubleshooting

**Client shows "no tools" or "server not responding"**

1. Test the server on the command line first:
   ```bash
   echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}' \
     | /ABSOLUTE/PATH/TO/adaptora/venv/bin/python \
       /ABSOLUTE/PATH/TO/adaptora/mcp_server.py
   ```
   You should see a JSON response containing `"serverInfo":{"name":"adaptora",...}`. If you see an `ImportError`, the Python you're invoking doesn't have the deps — use the project's venv.

2. Check the dependencies are installed:
   ```bash
   python -c "import mcp; print(mcp.__version__)"
   ```
   Should print `1.27.2` or higher.

**Tools list is empty (only meta-tools)**

The per-endpoint tools only appear for tools the MCP user has **connected** (credentials saved). Open the web UI at `http://localhost:8000`, log in as the user identified by `MCP_USER_EMAIL`, and connect at least one tool (e.g. GitHub with a PAT). Then refresh the MCP client.

**Calling a tool returns `needs_credentials` even though I connected it**

This is the #1 MCP gotcha — the server is scoped to the wrong user. Run the diagnostic:

```bash
python /path/to/adaptora/mcp_server.py --list-users
```

Note the email of the user that has your connections, then update `MCP_USER_EMAIL` in your MCP client config and restart the client.

**Server raises `MCP_USER_EMAIL does not match any user`**

- Typo — double-check against `--list-users` output.
- You haven't signed up yet — open the web UI at `http://localhost:8000` and register first.
- You're pointing at the wrong DB — make sure both processes read the same `DATABASE_URL`.

**"Couldn't fetch docs for X" when calling `setup_new_tool`**

- The tool doesn't publish a public OpenAPI spec — try a more specific name (e.g. `microsoft-graph` instead of `teams`)
- The web search engine is throttled — try setting `TAVILY_API_KEY`
- The Ollama LLM isn't responding — check `OLLAMA_API_URL` is reachable
