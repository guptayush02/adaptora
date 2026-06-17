from pydantic import field_validator
from pydantic_settings import BaseSettings
from typing import Optional, List
import os

# Absolute path to the project root (parent of the `app/` package). Pinning the
# default DATABASE_URL to this avoids accidentally pointing at a different
# `./token_optimizer.db` when the server is launched from a different cwd.
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_DEFAULT_SQLITE_PATH = os.path.join(_PROJECT_ROOT, "token_optimizer.db")


class Settings(BaseSettings):
    """Application settings and configuration"""

    # API Configuration
    APP_NAME: str = "LLM Token Optimizer Middleware"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False

    # HTTP server (uvicorn)
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    CORS_ALLOW_ORIGINS: List[str] | str = ["*"]

    # Auth / JWT
    SECRET_KEY: str = "your-secret-key-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours

    # Ollama Configuration — defaults to a local Ollama instance. Override with
    # OLLAMA_API_URL in .env if you run Ollama on a remote host.
    OLLAMA_API_URL: Optional[str] = None
    OLLAMA_MODEL: Optional[str] = None
    # Read timeout (how long we wait for the model to finish generating).
    OLLAMA_TIMEOUT: int = 1800
    # Connect timeout (how long we wait for the initial TCP handshake). Kept
    # short so unreachable hosts fail fast — a hung connect should not block
    # a request for the full read timeout.
    OLLAMA_CONNECT_TIMEOUT: int = 10
    # How long Ollama keeps the model resident in memory after a request.
    # The default Ollama keep-alive is only 5 minutes, after which the model
    # unloads and the next request pays a ~30s cold reload — that reload is
    # what made `run_action` (3 sequential LLM calls) blow past the MCP
    # client's request timeout. Keeping the model pinned ("-1" = forever,
    # or a duration like "30m") turns every call into a warm ~1-3s call.
    OLLAMA_KEEP_ALIVE: str = "30m"

    # Ollama hosted web search (optional). This is a SEPARATE service from the
    # EC2 chat endpoint above — it's hosted on ollama.com and needs an API
    # key from https://ollama.com/. When set, it becomes the preferred web
    # search backend ahead of Google CSE / DuckDuckGo.
    OLLAMA_API_KEY: Optional[str] = None
    OLLAMA_WEB_SEARCH_URL: str = "https://ollama.com/api/web_search"

    # LLM Provider Keys
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_MODEL: str = "gpt-4"
    ANTHROPIC_API_KEY: Optional[str] = None
    ANTHROPIC_MODEL: str = "claude-3-opus"

    # Google Custom Search (optional). When both are set, web search prefers
    # Google over DuckDuckGo — Google returns substantially better snippets
    # for fact-finding queries. Free tier: 100 queries/day.
    #   1. Get an API key: https://console.cloud.google.com/apis/library/customsearch.googleapis.com
    #   2. Create a Programmable Search Engine: https://programmablesearchengine.google.com/
    #      (set "Search the entire web" to ON so it isn't site-restricted)
    GOOGLE_API_KEY: Optional[str] = None
    GOOGLE_CSE_ID: Optional[str] = None

    # Tavily Search API (optional). Purpose-built for AI agents — its
    # `search()` returns full page content, not just snippets, so the
    # summarizer gets much richer source material to work with. When set,
    # Tavily becomes the preferred web-search backend ahead of every other
    # engine. Free tier: 1000 credits/month. Sign up at https://tavily.com.
    TAVILY_API_KEY: Optional[str] = None

    SEARCH_SEARXNG_URL: Optional[str] = None  # e.g. "https://searxng.example.com/search"

    # Cache Configuration
    CACHE_TYPE: str = "redis"
    REDIS_URL: str = "redis://localhost:6379/0"
    CACHE_TTL: int = 3600  # 1 hour

    # Database Configuration. Uses an absolute path so the same SQLite file is
    # opened regardless of the process's current working directory.
    DATABASE_URL: str = f"sqlite:///{_DEFAULT_SQLITE_PATH}"

    # Complexity Thresholds
    SIMPLE_QUERY_THRESHOLD: int = 100  # tokens
    MEDIUM_QUERY_THRESHOLD: int = 500  # tokens

    # Bypass Keywords
    BYPASS_KEYWORDS: List[str] | str = [
        "urgent",
        "critical",
        "advanced",
        "direct",
        "llama-direct",
    ]

    # Logging
    LOG_LEVEL: str = "INFO"

    # Cloud Brain — Optional endpoint for offloading tool identification and action planning
    # If set, the agent will call this URL for identify_tool and plan_action steps instead of
    # using the local Ollama model. Useful for high-accuracy reasoning at the cost of latency.
    # Expected to be an Adaptora instance. Leave unset to use local Ollama.
    CLOUD_BRAIN_URL: Optional[str] = None

    @field_validator("CORS_ALLOW_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, value):
        if value is None or value == "":
            return ["*"]
        if isinstance(value, str):
            raw = value.strip()
            if raw.startswith("[") and raw.endswith("]"):
                import json

                try:
                    parsed = json.loads(raw)
                    return [item.strip() for item in parsed if isinstance(item, str)]
                except Exception:
                    pass
            return [item.strip() for item in raw.split(",") if item.strip()]
        return value

    @field_validator("BYPASS_KEYWORDS", mode="before")
    @classmethod
    def parse_bypass_keywords(cls, value):
        if value is None:
            return []

        if isinstance(value, str):
            raw = value.strip()
            if raw.startswith("[") and raw.endswith("]"):
                import json

                try:
                    parsed = json.loads(raw)
                    return [item.strip() for item in parsed if isinstance(item, str)]
                except Exception:
                    pass

            return [item.strip() for item in raw.split(",") if item.strip()]

        return value

    class Config:
        env_file = ".env"
        case_sensitive = True
        # Tolerate stray vars (e.g. NANGO_* left over from the previous
        # branch) so an old .env doesn't break startup.
        extra = "ignore"


settings = Settings()
