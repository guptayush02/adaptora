"""MCP (Model Context Protocol) layer on top of the Dynamic Agent.

This package exposes the existing :class:`DynamicAgentService` over the
MCP protocol so MCP-compatible clients (Claude Desktop, etc.) can:

  * call :func:`setup_new_tool` to discover docs for an arbitrary API
    and seed it into the cache;
  * call :func:`list_connected_tools` / :func:`list_known_tools` to see
    what's available;
  * call :func:`run_action` for natural-language dispatch through the
    full identify → docs → connection → plan → execute pipeline.

The implementation is intentionally a thin wrapper — every operation
delegates to ``DynamicAgentService``. Adding a new feature to the agent
automatically makes it available over MCP without changing this layer.
"""

from app.mcp.server import build_mcp_server, run_stdio  # noqa: F401
