from sqlalchemy import Column, String, Integer, Float, DateTime, Text, Boolean, JSON
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()


class User(Base):
    """Database model for users with authentication"""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, index=True)
    email = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)
    total_tokens_used = Column(Integer, default=0)
    total_cost = Column(Float, default=0.0)


class UserAPIKey(Base):
    """Database model for storing user's API keys for different providers"""

    __tablename__ = "user_api_keys"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, index=True)
    provider = Column(String)  # openai, anthropic, ollama, etc.
    api_key = Column(String)  # Encrypted
    model_name = Column(String)  # gpt-4, claude-3-opus, mistral, etc.
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class DeveloperApiKey(Base):
    """A developer secret key minted on the dashboard.

    Lets an external project drive Adaptora via the public REST API
    (``POST /api/v1/run``) with ``Authorization: Bearer adp_live_…``,
    scoped to the owning user. We store ONLY a sha256 hash of the secret —
    the raw value is shown exactly once at creation and can never be
    recovered. ``key_prefix`` + ``last_four`` are kept for safe display."""

    __tablename__ = "developer_api_keys"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, index=True)
    label = Column(String)  # human name for the key / project
    key_hash = Column(String, unique=True, index=True)  # sha256 hex of the raw key
    key_prefix = Column(String)  # e.g. "adp_live_ab12" — safe to display
    last_four = Column(String)  # last 4 chars of the raw key
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_used_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)


class TokenUsageRecord(Base):
    """Database model for tracking token usage"""

    __tablename__ = "token_usage"

    id = Column(Integer, primary_key=True)
    user_id = Column(String, index=True)
    prompt = Column(Text)
    # NOT unique — multiple requests with the same prompt are allowed.
    prompt_hash = Column(String, index=True)
    response = Column(Text)
    prompt_tokens = Column(Integer)
    response_tokens = Column(Integer)
    total_tokens = Column(Integer)
    # Word-count estimates of the user's raw prompt vs the prompt actually
    # forwarded to the LLM after Ollama-based optimization. Used to chart
    # "before vs after optimization" savings.
    original_prompt_tokens = Column(Integer, default=0)
    optimized_prompt_tokens = Column(Integer, default=0)
    model_used = Column(String)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    cost_estimate = Column(Float)
    cache_hit = Column(Boolean, default=False)
    complexity_level = Column(String)
    optimization_applied = Column(Boolean, default=False)


class Conversation(Base):
    """A chat conversation/thread owned by a user."""

    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True)
    user_id = Column(String, index=True)
    title = Column(String, default="New conversation")
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Message(Base):
    """A single message inside a conversation."""

    __tablename__ = "messages"

    id = Column(Integer, primary_key=True)
    conversation_id = Column(Integer, index=True)
    role = Column(String)  # "user" or "assistant"
    content = Column(Text)
    model_used = Column(String, nullable=True)
    complexity_level = Column(String, nullable=True)
    prompt_tokens = Column(Integer, default=0)
    response_tokens = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    cache_hit = Column(Boolean, default=False)
    processing_time_ms = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class CacheRecord(Base):
    """Database model for caching prompts and responses"""

    __tablename__ = "cache"

    id = Column(Integer, primary_key=True)
    cache_key = Column(String, unique=True, index=True)
    prompt_hash = Column(String, index=True)
    prompt = Column(Text)
    response = Column(Text)
    model_used = Column(String)
    prompt_tokens = Column(Integer)
    response_tokens = Column(Integer)
    total_tokens = Column(Integer)
    user_id = Column(String, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, index=True)
    hit_count = Column(Integer, default=0)


class ToolDefinition(Base):
    """Cached docs for an external tool/API that the dynamic agent can call.

    Populated either from a manual seed or by the agent itself the first time
    a user asks for the tool — the agent runs a web search, fetches the docs
    page, and asks the LLM to extract the structured fields below."""

    __tablename__ = "tool_definitions"

    id = Column(Integer, primary_key=True)
    # Lowercase canonical name (github, notion, gmail, openai, …). Used as the
    # lookup key from the LLM-emitted Thought.
    name = Column(String, unique=True, index=True)
    display_name = Column(String)
    base_url = Column(String)
    # API_KEY | BEARER | OAUTH2 | OAUTH2_PKCE | OAUTH1 | BASIC | PAT
    auth_type = Column(String, default="API_KEY")
    # Auth-flow metadata: oauth_authorize_url, token_url, default_scopes,
    # header_name (for API_KEY), credential_prefix ("Bearer "), etc.
    auth_config = Column(JSON, default=dict)
    # Map of "verbName" → {"method", "path", "description", "params", "body"}
    # e.g. {"list_repos": {"method": "GET", "path": "/user/repos", ...}}
    endpoints = Column(JSON, default=dict)
    # Provider rate-limit metadata extracted from docs, e.g.
    # {"requests_per_minute": 60, "notes": "..."} or freeform string list.
    rate_limits = Column(JSON, nullable=True)
    # Code samples extracted from docs:
    # [{"language": "curl", "code": "..."}, {"language": "python", ...}]
    examples = Column(JSON, nullable=True)
    docs_url = Column(String, nullable=True)
    # "seed" | "scraped" | "llm" — tracks how we got these docs so we know
    # how much to trust them and when to refresh.
    source = Column(String, default="llm")
    last_fetched_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class DynamicToolConnection(Base):
    """A user's authenticated connection to one tool.

    Encrypted credentials live here — never the raw values. For OAuth2 we
    store access_token + refresh_token + expires_at; for API key/PAT we
    just store the key. `tool_name` is a FK-by-name to ToolDefinition.name."""

    __tablename__ = "dynamic_tool_connections"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, index=True)
    tool_name = Column(String, index=True)
    display_name = Column(String, nullable=True)
    auth_type = Column(String)
    # Encrypted JSON blob keyed by whatever the auth_type requires:
    # API_KEY → {"api_key": "..."}
    # BEARER  → {"token": "..."}
    # OAUTH2  → {"client_id": "...", "client_secret": "...",
    #            "access_token": "...", "refresh_token": "...",
    #            "scopes": "..."}
    credentials_encrypted = Column(Text)
    token_expires_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)
    last_used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class DynamicAgentRunLog(Base):
    """Audit trail for every turn of the dynamic agent.

    Stores the user's prompt, the structured Thought/Action plan the LLM
    produced, the upstream HTTP response, and the timing — enough to debug
    a failure or replay a successful action."""

    __tablename__ = "dynamic_agent_runs"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, index=True)
    # FK-by-id to DeveloperApiKey.id when the run was triggered through the
    # public REST API. NULL = web UI or MCP. Lets the dashboard attribute
    # each run to the project (key) that produced it.
    api_key_id = Column(Integer, index=True, nullable=True)
    language = Column(String, default="en")  # "en" | "hinglish"
    tool_name = Column(String, index=True, nullable=True)
    prompt = Column(Text)
    thought = Column(Text, nullable=True)
    action = Column(String, nullable=True)
    action_input = Column(JSON, nullable=True)
    summary = Column(Text, nullable=True)
    final_answer = Column(Text, nullable=True)
    # success | needs_credentials | needs_tool_setup | error
    status = Column(String, default="success")
    http_status = Column(Integer, nullable=True)
    response_body = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    duration_ms = Column(Float, default=0.0)
    # Response-compaction accounting (filled by the MCP transport layer):
    # raw_tokens   = cloud tokens the un-trimmed response would have cost
    # sent_tokens  = cloud tokens the compacted response actually costs
    # tokens_saved = raw_tokens - sent_tokens (>= 0). Summed for the
    # dashboard's "tokens saved" metric. Tool-agnostic — works for any
    # connected tool's response shape.
    raw_tokens = Column(Integer, default=0)
    sent_tokens = Column(Integer, default=0)
    tokens_saved = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class McpToolListStat(Base):
    """Per-user snapshot of the `tools/list` payload cost — Adaptora's INPUT
    side. Every MCP session ships the tool schemas into the cloud model's
    context, so this is the dominant input-token cost. One row per user,
    upserted whenever the MCP server lists tools.

      input_raw_tokens  = what the verbose per-endpoint descriptions would cost
      input_sent_tokens = what the lean descriptions actually cost
      input_saved       = raw - sent
    """

    __tablename__ = "mcp_toollist_stats"

    user_id = Column(Integer, primary_key=True)
    input_raw_tokens = Column(Integer, default=0)
    input_sent_tokens = Column(Integer, default=0)
    input_saved = Column(Integer, default=0)
    tool_count = Column(Integer, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
