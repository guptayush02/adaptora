from sqlalchemy import create_engine, inspect, text, event
from sqlalchemy.orm import sessionmaker, Session
from app.core.config import settings
from app.db.models import Base

# Create database engine. For SQLite we use the default QueuePool (NOT
# StaticPool) so concurrent requests each get their own connection — sharing
# a single connection across FastAPI's threadpool causes intermittent races
# that surface as random 401s when tabs fetch in parallel.
if settings.DATABASE_URL.startswith("sqlite"):
    engine = create_engine(
        settings.DATABASE_URL,
        connect_args={"check_same_thread": False, "timeout": 30},
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
    )

    # WAL mode lets many readers operate in parallel with a single writer.
    # busy_timeout makes contended writes wait briefly instead of failing.
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()
else:
    engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Session:
    """Get database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _ensure_sqlite_schema():
    """Ensure SQLite schema matches current SQLAlchemy models."""
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())

    # --- users: backup-and-recreate if the shape is fundamentally wrong ---
    if "users" in tables:
        existing_columns = {col["name"] for col in inspector.get_columns("users")}
        required_columns = {
            "id",
            "username",
            "email",
            "hashed_password",
            "created_at",
            "is_active",
            "total_tokens_used",
            "total_cost",
        }

        if not required_columns.issubset(existing_columns):
            backup_table = f"users_backup_{int(__import__('time').time())}"
            with engine.begin() as connection:
                connection.execute(text(f"ALTER TABLE users RENAME TO {backup_table}"))
            Base.metadata.create_all(bind=engine)

    # --- token_usage: index + column migrations (don't drop data) ---
    if "token_usage" in tables:
        # The old schema declared prompt_hash as UNIQUE, which made repeat
        # prompts fail with IntegrityError. Replace the UNIQUE index with a
        # plain index so duplicate prompts can be recorded across users/turns.
        indexes = inspector.get_indexes("token_usage")
        for ix in indexes:
            if ix["name"] == "ix_token_usage_prompt_hash" and ix.get("unique"):
                with engine.begin() as connection:
                    connection.execute(text("DROP INDEX ix_token_usage_prompt_hash"))
                    connection.execute(
                        text(
                            "CREATE INDEX ix_token_usage_prompt_hash "
                            "ON token_usage (prompt_hash)"
                        )
                    )

        existing = {col["name"] for col in inspector.get_columns("token_usage")}
        additions = []
        if "original_prompt_tokens" not in existing:
            additions.append(
                "ALTER TABLE token_usage ADD COLUMN original_prompt_tokens INTEGER DEFAULT 0"
            )
        if "optimized_prompt_tokens" not in existing:
            additions.append(
                "ALTER TABLE token_usage ADD COLUMN optimized_prompt_tokens INTEGER DEFAULT 0"
            )
        for stmt in additions:
            with engine.begin() as connection:
                connection.execute(text(stmt))

        # Backfill: for rows inserted before the optimization tracking was
        # added, set original_prompt_tokens from the stored prompt's word count,
        # and mirror it onto optimized_prompt_tokens (no real before/after data
        # to compare, so they show as equal in the chart instead of vanishing).
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    UPDATE token_usage
                       SET original_prompt_tokens =
                           LENGTH(TRIM(prompt))
                           - LENGTH(REPLACE(TRIM(prompt), ' ', ''))
                           + 1
                     WHERE COALESCE(original_prompt_tokens, 0) = 0
                       AND prompt IS NOT NULL
                       AND TRIM(prompt) != ''
                    """
                )
            )
            connection.execute(
                text(
                    """
                    UPDATE token_usage
                       SET optimized_prompt_tokens = original_prompt_tokens
                     WHERE COALESCE(optimized_prompt_tokens, 0) = 0
                       AND COALESCE(original_prompt_tokens, 0) > 0
                    """
                )
            )

    # --- dynamic_agent_runs: add response-compaction token columns (additive) ---
    if "dynamic_agent_runs" in tables:
        existing = {col["name"] for col in inspector.get_columns("dynamic_agent_runs")}
        for col in ("raw_tokens", "sent_tokens", "tokens_saved"):
            if col not in existing:
                with engine.begin() as connection:
                    connection.execute(
                        text(
                            f"ALTER TABLE dynamic_agent_runs "
                            f"ADD COLUMN {col} INTEGER DEFAULT 0"
                        )
                    )
        # api_key_id: attributes a run to the developer key that triggered it
        # (NULL for UI/MCP runs). Nullable, no default needed.
        if "api_key_id" not in existing:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "ALTER TABLE dynamic_agent_runs "
                        "ADD COLUMN api_key_id INTEGER"
                    )
                )

    # --- developer_api_keys: add reversible key_encrypted column (additive) ---
    if "developer_api_keys" in tables:
        existing = {col["name"] for col in inspector.get_columns("developer_api_keys")}
        if "key_encrypted" not in existing:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "ALTER TABLE developer_api_keys ADD COLUMN key_encrypted VARCHAR"
                    )
                )

    # --- tool_definitions: add rate_limits + examples columns (additive) ---
    if "tool_definitions" in tables:
        existing = {col["name"] for col in inspector.get_columns("tool_definitions")}
        additions = []
        if "rate_limits" not in existing:
            additions.append(
                "ALTER TABLE tool_definitions ADD COLUMN rate_limits JSON"
            )
        if "examples" not in existing:
            additions.append(
                "ALTER TABLE tool_definitions ADD COLUMN examples JSON"
            )
        if "quirks" not in existing:
            additions.append(
                "ALTER TABLE tool_definitions ADD COLUMN quirks JSON"
            )
        for stmt in additions:
            with engine.begin() as connection:
                connection.execute(text(stmt))


def _ensure_postgres_schema():
    """Additive column migrations for Postgres (the Docker stack uses it).

    ``Base.metadata.create_all`` creates missing TABLES but never adds new
    COLUMNS to an existing table — so model-level additions (e.g. the
    response-compaction token columns) need an explicit ALTER. Postgres
    supports ``ADD COLUMN IF NOT EXISTS``, making these idempotent and safe
    to run on every startup."""
    additions = [
        "ALTER TABLE dynamic_agent_runs ADD COLUMN IF NOT EXISTS raw_tokens INTEGER DEFAULT 0",
        "ALTER TABLE dynamic_agent_runs ADD COLUMN IF NOT EXISTS sent_tokens INTEGER DEFAULT 0",
        "ALTER TABLE dynamic_agent_runs ADD COLUMN IF NOT EXISTS tokens_saved INTEGER DEFAULT 0",
        "ALTER TABLE dynamic_agent_runs ADD COLUMN IF NOT EXISTS api_key_id INTEGER",
        "ALTER TABLE developer_api_keys ADD COLUMN IF NOT EXISTS key_encrypted VARCHAR",
        "ALTER TABLE tool_definitions ADD COLUMN IF NOT EXISTS quirks JSON",
    ]
    with engine.begin() as connection:
        for stmt in additions:
            connection.execute(text(stmt))


def init_db():
    """Initialize database tables"""
    Base.metadata.create_all(bind=engine)
    if settings.DATABASE_URL.startswith("sqlite"):
        _ensure_sqlite_schema()
    else:
        _ensure_postgres_schema()
