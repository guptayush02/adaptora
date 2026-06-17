import logging
import sys
from app.core.config import settings

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    # stderr, NOT stdout: the stdio MCP server (app/mcp/server.py) uses
    # stdout exclusively for JSON-RPC frames. Any log line on stdout
    # corrupts the protocol — the client tries to JSON.parse the log
    # timestamp ("2026-..." parses as the number 2026, then chokes on the
    # "-") and dies with "Unexpected non-whitespace character after JSON".
    handlers=[logging.StreamHandler(sys.stderr)],
)

logger = logging.getLogger(__name__)
