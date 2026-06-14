#!/usr/bin/env python3
"""Token Optimizer MCP server entry point.

This thin wrapper exists so MCP clients (Claude Code, Claude Desktop,
Cursor, …) can launch the server from anywhere on disk without needing
``cwd``, ``PYTHONPATH``, or ``-m`` package resolution to line up. We add
this file's directory to ``sys.path`` BEFORE importing the package, then
delegate to the real implementation in ``app.mcp.server``.

Run via any MCP client config like:

    /absolute/path/to/token-optimizer/venv/bin/python \
        /absolute/path/to/token-optimizer/mcp_server.py

Or with `claude mcp add`:

    claude mcp add token-optimizer \
        --scope user --transport stdio --env MCP_USER_ID=1 \
        -- /path/to/venv/bin/python /path/to/mcp_server.py
"""

import os
import sys

# Make `app.*` importable regardless of where this script was invoked
# from. We do this BEFORE the `from app.mcp ...` import so `python
# /path/to/mcp_server.py` works even when cwd is somewhere unrelated.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from app.mcp.server import main  # noqa: E402


if __name__ == "__main__":
    main()
