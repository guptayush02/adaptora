"""MCP server that exposes the Dynamic Agent over the Model Context Protocol.

Run as a subprocess from an MCP client (typically Claude Desktop):

    python -m app.mcp.server

It speaks JSON-RPC over stdio. The server reuses the existing
:class:`DynamicAgentService` so every capability of the chat-mode agent
(tool discovery, doc fetching, OpenAPI probing, AWS introspection,
credential handling, action planning, HTTP execution) is available to
MCP clients without code duplication.

Tools exposed:

  Meta-tools (always present):
    * ``setup_new_tool``     — fetch docs for an arbitrary tool, ready to use
    * ``list_known_tools``   — every cached tool definition
    * ``list_connections``   — which tools this user already authenticated
    * ``run_action``         — natural-language dispatch (the chat-mode API)

  Dynamic per-endpoint tools:
    * For each tool the user has connected, every endpoint becomes its
      own MCP tool with a typed input schema derived from the endpoint's
      ``params`` / ``body`` dicts. Re-evaluated on each ``tools/list``
      so newly connected tools appear immediately.

Auth model: MCP has no built-in auth — a single MCP server instance
represents one local user. By default we use ``MCP_USER_ID`` (env var,
defaults to 1) for all DB scoping. Set this if you want to attach an
MCP client to a specific multi-user installation.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from collections import Counter
from typing import Any, Callable, Dict, List, Optional

# Resolve the project root from this file's location and chdir to it
# BEFORE any project imports. MCP clients (Claude Code, Claude Desktop,
# Cursor, …) launch the server with their OWN cwd — usually the user's
# active project, not the Token Optimizer install dir. We need the cwd
# to be the install dir so relative paths in config (DATABASE_URL,
# REDIS_URL, etc.) and on-disk file lookups all resolve correctly.
#
# server.py is at <root>/app/mcp/server.py — three dirnames up = root.
_PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
if os.path.isdir(_PROJECT_ROOT):
    os.chdir(_PROJECT_ROOT)
    # Ensure imports work even when launched as `python -m app.mcp.server`
    # from a different cwd: prepend the root to sys.path defensively.
    if _PROJECT_ROOT not in sys.path:
        sys.path.insert(0, _PROJECT_ROOT)

from mcp.server import Server  # noqa: E402
from mcp.server.stdio import stdio_server  # noqa: E402
from mcp.types import TextContent, Tool  # noqa: E402

from app.core.logger import logger  # noqa: E402
from app.core.tokens import count_tokens  # noqa: E402
from app.db.database import SessionLocal, init_db  # noqa: E402
from app.db.models import (  # noqa: E402
    DynamicAgentRunLog,
    DynamicToolConnection,
    McpToolListStat,
    ToolDefinition,
    User,
)
from app.services.dynamic_agent_service import (  # noqa: E402
    _strip_empties,
    dynamic_agent_service,
    warmup_model,
)


# A single MCP server instance represents one local user. Two ways to
# tell it which DB user to scope to:
#
#   MCP_USER_EMAIL — friendly, looked up at startup. The recommended
#                    path: you already remember your email, and changes
#                    to the DB (new user added, IDs reshuffle) don't
#                    break the config.
#   MCP_USER_ID    — direct numeric ID. Used as fallback if EMAIL isn't
#                    set, or for headless setups where the email lookup
#                    is unavailable. Defaults to 1.
#
# The actual value is resolved by :func:`_resolve_mcp_user_id` on first
# DB access — we can't query the DB at import time because main.py and
# tests may import this module before the schema is migrated.
_MCP_USER_EMAIL_ENV = os.environ.get("MCP_USER_EMAIL", "").strip().lower() or None
_MCP_USER_ID_ENV = int(os.environ.get("MCP_USER_ID", "1"))

# Resolved lazily and cached. Set by _resolve_mcp_user_id().
MCP_USER_ID: Optional[int] = None


def _resolve_mcp_user_id(db) -> int:
    """Resolve the env vars MCP_USER_EMAIL / MCP_USER_ID to a real DB
    user. Cached after the first successful lookup so each subsequent
    call is free.

    Resolution order:
      1. MCP_USER_EMAIL — case-insensitive lookup against User.email.
      2. MCP_USER_ID — used as-is. If the user doesn't exist, the
         placeholder-creation path in :func:`_ensure_mcp_user` runs.
    """
    global MCP_USER_ID
    if MCP_USER_ID is not None:
        return MCP_USER_ID

    if _MCP_USER_EMAIL_ENV:
        user = (
            db.query(User)
            .filter(User.email.ilike(_MCP_USER_EMAIL_ENV))
            .first()
        )
        if user:
            MCP_USER_ID = user.id
            logger.info(
                f"MCP resolved MCP_USER_EMAIL={_MCP_USER_EMAIL_ENV!r} "
                f"to user_id={user.id} ({user.username})"
            )
            return MCP_USER_ID
        # Email was set but didn't match — fail loudly. Falling back to
        # ID=1 here would silently scope every action to the wrong user,
        # which is exactly the bug this whole feature exists to prevent.
        raise RuntimeError(
            f"MCP_USER_EMAIL={_MCP_USER_EMAIL_ENV!r} does not match any "
            f"user in the database. Run "
            f"`python mcp_server.py --list-users` to see who exists, or "
            f"sign up at the web UI first."
        )

    MCP_USER_ID = _MCP_USER_ID_ENV
    return MCP_USER_ID

def _make_progress_callback(
    server: Server,
    loop: asyncio.AbstractEventLoop,
) -> tuple[Callable[[str, Dict[str, Any]], None], asyncio.Queue]:
    """Return a (status_callback, queue) pair.

    The callback is safe to call from any thread (it uses
    call_soon_threadsafe). The queue is drained by
    :func:`_progress_emitter_task`, which sends MCP progress notifications
    to the connected client so the client's request timeout keeps
    resetting while a slow operation runs.
    """
    q: asyncio.Queue = asyncio.Queue()

    def callback(step: str, data: Optional[Dict[str, Any]] = None) -> None:
        msg = step if not data else f"{step}: {json.dumps(data, default=str)[:120]}"
        loop.call_soon_threadsafe(q.put_nowait, msg)

    return callback, q


_HEARTBEAT_INTERVAL = 5  # seconds between keepalive pings when no step fires


async def _progress_emitter_task(
    server: Server,
    queue: asyncio.Queue,
    progress_token: Any,
    request_id: Any = None,
) -> None:
    """Drain *queue* and emit each item as an MCP progress notification.

    Runs as a background asyncio.Task alongside the slow
    asyncio.to_thread() call. Stops when the sentinel ``None`` is put
    into the queue. If the client didn't supply a progressToken we still
    drain the queue (so it doesn't grow unbounded) but skip the network
    write.

    Heartbeat: if no step fires for _HEARTBEAT_INTERVAL seconds (e.g.
    during a long local-LLM inference call that has no intermediate
    callbacks), we emit a generic "working…" notification so the MCP
    client's request timeout keeps resetting.
    """
    step = 0
    elapsed = 0

    async def _send(msg: str) -> None:
        nonlocal step
        step += 1
        if progress_token is not None:
            try:
                ctx = server.request_context
                await ctx.session.send_progress_notification(
                    progress_token=progress_token,
                    progress=float(step),
                    total=None,
                    message=str(msg)[:200],
                    related_request_id=str(request_id) if request_id is not None else None,
                )
            except Exception:
                pass  # never let notification failure crash the main call

    # Emit an immediate ping so the client sees activity right away and
    # starts (re)setting its request timeout from t=0, rather than waiting
    # a full heartbeat interval for the first sign of life.
    await _send("starting…")

    while True:
        try:
            msg = await asyncio.wait_for(queue.get(), timeout=_HEARTBEAT_INTERVAL)
        except asyncio.TimeoutError:
            elapsed += _HEARTBEAT_INTERVAL
            await _send(f"working… ({elapsed}s elapsed)")
            continue
        if msg is None:
            break
        await _send(msg)


# Meta-tool names — also used as a guard in handle_call_tool to route
# special-cased ones before falling through to the dynamic dispatcher.
_META_SETUP = "setup_new_tool"
_META_LIST_KNOWN = "list_known_tools"
_META_LIST_CONNS = "list_connections"
_META_RUN_ACTION = "run_action"
_META_REFRESH = "refresh_tool_docs"
_META_TOOLS = {_META_SETUP, _META_LIST_KNOWN, _META_LIST_CONNS, _META_RUN_ACTION, _META_REFRESH}


def _meta_tool_defs() -> List[Tool]:
    """The always-present meta-tools. Names + schemas only — the actual
    work happens in :func:`handle_call_tool`."""
    return [
        Tool(
            name=_META_SETUP,
            description=(
                "Discover documentation for an arbitrary API tool and seed "
                "it into the agent. Runs the full pipeline: web search → "
                "OpenAPI spec probing → LLM extraction → endpoint merging. "
                "Returns the tool's auth requirements so the next step is "
                "to provide credentials via your usual config (the agent "
                "doesn't accept credentials over MCP for security reasons)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "tool": {
                        "type": "string",
                        "description": "Canonical lowercase tool name (e.g. 'github', 'stripe', 'shopify').",
                    },
                    "force_refresh": {
                        "type": "boolean",
                        "description": "Re-fetch docs from the web even if a cached version exists.",
                        "default": False,
                    },
                },
                "required": ["tool"],
            },
        ),
        Tool(
            name=_META_REFRESH,
            description=(
                "Force-refresh the cached docs for a tool. Equivalent to "
                "the Refresh button in the web UI. Useful when a provider "
                "has updated their API and you want the latest endpoints, "
                "rate limits, and examples."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "tool": {"type": "string"},
                },
                "required": ["tool"],
            },
        ),
        Tool(
            name=_META_LIST_KNOWN,
            description=(
                "List every tool the agent has docs cached for, including "
                "endpoint counts and last-refreshed times. Use this to see "
                "what's available before deciding to set up something new."
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name=_META_LIST_CONNS,
            description=(
                "List the tools this user has authenticated (i.e. "
                "credentials saved). Only connected tools' endpoints "
                "appear as their own MCP tools below."
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name=_META_RUN_ACTION,
            description=(
                "⚡ CALL THIS FIRST FOR EVERY USER MESSAGE. This is the "
                "sole entry point for all user requests. Pass the user's "
                "exact message as `prompt` — do not interpret, modify, or "
                "plan it yourself. The Adaptora agent (local Ollama LLM) "
                "handles all intelligence: it identifies the right service, "
                "plans the HTTP call, executes it with saved credentials, "
                "and returns a complete answer.\n\n"
                "DO NOT write boto3/aws-cli/curl/code or reason about the "
                "request. DO NOT use any other tool unless the user "
                "explicitly names it (setup_new_tool, list_connections, "
                "etc.). For everything else: call this immediately.\n\n"
                "Handles any connected service: AWS · GitHub · Stripe · "
                "Slack · Notion · Razorpay · Spotify · Linear · Gmail · "
                "OpenAI · and more."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "What you want the agent to do, in plain English. The agent extracts intent + service automatically.",
                    },
                    "language": {
                        "type": "string",
                        "enum": ["en", "hinglish"],
                        "default": "en",
                    },
                },
                "required": ["prompt"],
            },
        ),
    ]


def _endpoint_tool_name(tool: str, endpoint: str) -> str:
    """Build a stable MCP tool name from (tool, endpoint) pair. MCP names
    must be unique across the server, so we prefix every endpoint with
    its parent tool: ``github_list_repos``, ``stripe_create_charge``."""
    return f"{tool}_{endpoint}"


def _split_endpoint_tool_name(name: str) -> Optional[tuple]:
    """Reverse of _endpoint_tool_name. Returns (tool, endpoint) or None
    if this doesn't look like a tool-endpoint MCP name."""
    parts = name.split("_", 1)
    if len(parts) != 2:
        return None
    return parts[0], parts[1]


def _endpoint_input_schema(endpoint: Dict[str, Any]) -> Dict[str, Any]:
    """Build a JSON-schema for an endpoint based on its params/body
    metadata. We don't have rich type info, so everything becomes
    ``string`` — the agent's planner will coerce types at call time.

    Adds an optional ``raw_prompt`` so the user can fall back to natural
    language for endpoints whose params we couldn't accurately model."""
    properties: Dict[str, Dict[str, Any]] = {}
    params = endpoint.get("params") or {}
    body = endpoint.get("body") or {}
    if isinstance(params, dict):
        for key, desc in params.items():
            properties[key] = {
                "type": "string",
                "description": str(desc) if desc else "query parameter",
            }
    if isinstance(body, dict):
        for key, desc in body.items():
            properties[key] = {
                "type": "string",
                "description": str(desc) if desc else "body field",
            }
    properties["raw_prompt"] = {
        "type": "string",
        "description": (
            "Optional natural-language description of what you want "
            "this call to do. If supplied, the agent uses this to fill "
            "in any params/body fields not explicitly provided."
        ),
    }
    return {"type": "object", "properties": properties}


def _connected_endpoint_tools(db) -> List[Tool]:
    """Build the dynamic per-endpoint Tool list. Only includes endpoints
    of tools the MCP user has actually connected — that way the MCP
    client doesn't see hundreds of locked-out actions."""
    out: List[Tool] = []
    user_id = _resolve_mcp_user_id(db)
    conns = (
        db.query(DynamicToolConnection)
        .filter(
            DynamicToolConnection.user_id == user_id,
            DynamicToolConnection.is_active == True,  # noqa: E712
        )
        .all()
    )
    for conn in conns:
        tool_def = (
            db.query(ToolDefinition)
            .filter(ToolDefinition.name == conn.tool_name)
            .first()
        )
        if not tool_def:
            continue
        svc = conn.tool_name.upper()
        for ep_name, ep in (tool_def.endpoints or {}).items():
            if not isinstance(ep, dict):
                continue
            out.append(
                Tool(
                    name=_endpoint_tool_name(conn.tool_name, ep_name),
                    description=_endpoint_base_desc(ep) + _LEAN_PREAMBLE.format(svc=svc),
                    inputSchema=_endpoint_input_schema(ep),
                )
            )
    return out


def _endpoint_base_desc(ep: Dict[str, Any]) -> str:
    return ep.get("description") or f"{ep.get('method', 'GET')} {ep.get('path', '')}"


# The preamble still nudges Claude toward the MCP tool (not Bash/curl/SDK),
# but in ~12 words instead of ~55. Repeated on EVERY connected endpoint, so
# the saving multiplies by the user's endpoint count — this is the dominant
# INPUT-token lever. `_VERBOSE_PREAMBLE` is kept only as the accounting
# baseline (what the old build cost), never sent to a client.
_LEAN_PREAMBLE = " — runs via your saved {svc} connection; prefer over curl/SDK code."
_VERBOSE_PREAMBLE = (
    ". Executes against your authenticated {svc} connection (credentials "
    "already saved in the Token Optimizer DB). PREFER this MCP tool over "
    "writing boto3 / curl / cli code — using it ensures the call goes "
    "through the user's existing connection without re-prompting for credentials."
)


def _tool_tokens(name: str, description: str, schema: Any) -> int:
    """Token cost of one tool entry in the tools/list payload."""
    return (
        count_tokens(name)
        + count_tokens(description or "")
        + count_tokens(json.dumps(schema, default=str))
    )


def _record_tool_list_stats(db) -> None:
    """Measure the INPUT-side cost of the tools/list payload and upsert it for
    the dashboard. sent = lean (what we ship now); raw = the old verbose
    per-endpoint preamble baseline. Tool-agnostic — iterates whatever the user
    has connected. Best-effort; never blocks listing tools."""
    try:
        sent = raw = count = 0
        for t in _meta_tool_defs():  # meta tools are identical in both
            n = _tool_tokens(t.name, t.description, t.inputSchema)
            sent += n
            raw += n
            count += 1
        user_id = _resolve_mcp_user_id(db)
        conns = (
            db.query(DynamicToolConnection)
            .filter(
                DynamicToolConnection.user_id == user_id,
                DynamicToolConnection.is_active == True,  # noqa: E712
            )
            .all()
        )
        for conn in conns:
            tool_def = (
                db.query(ToolDefinition)
                .filter(ToolDefinition.name == conn.tool_name)
                .first()
            )
            if not tool_def:
                continue
            svc = conn.tool_name.upper()
            for ep_name, ep in (tool_def.endpoints or {}).items():
                if not isinstance(ep, dict):
                    continue
                name = _endpoint_tool_name(conn.tool_name, ep_name)
                schema = _endpoint_input_schema(ep)
                base = _endpoint_base_desc(ep)
                sent += _tool_tokens(name, base + _LEAN_PREAMBLE.format(svc=svc), schema)
                raw += _tool_tokens(name, base + _VERBOSE_PREAMBLE.format(svc=svc), schema)
                count += 1
        row = (
            db.query(McpToolListStat)
            .filter(McpToolListStat.user_id == user_id)
            .first()
        )
        if row is None:
            row = McpToolListStat(user_id=user_id)
            db.add(row)
        row.input_raw_tokens = raw
        row.input_sent_tokens = sent
        row.input_saved = max(0, raw - sent)
        row.tool_count = count
        db.commit()
    except Exception as exc:  # pragma: no cover — accounting is non-critical
        logger.warning(f"tool-list input accounting failed: {exc}")
        try:
            db.rollback()
        except Exception:
            pass


def _ensure_mcp_user(db) -> None:
    """The dynamic agent stores connections keyed by user_id. MCP has no
    auth, so we anchor everything to the resolved MCP user. Create a
    placeholder row only when MCP_USER_EMAIL wasn't set — if it WAS set,
    _resolve_mcp_user_id already raised on a missing match, so we won't
    reach here with an unknown ID."""
    user_id = _resolve_mcp_user_id(db)
    existing = db.query(User).filter(User.id == user_id).first()
    if existing:
        return
    placeholder = User(
        id=user_id,
        username=f"mcp-user-{user_id}",
        email=f"mcp-user-{user_id}@local",
        hashed_password="!mcp-no-login!",
        is_active=True,
    )
    db.add(placeholder)
    db.commit()
    logger.info(f"created placeholder user id={user_id} for MCP")


def _identity_hint(db, user_id: int) -> Dict[str, Any]:
    """Build a diagnostic block for ``needs_credentials`` responses.

    When the agent asks for credentials, the most common cause in MCP
    mode is the MCP server scoped to the wrong user — the credentials
    EXIST but on a different user_id. We report:
      * which user_id/email the MCP server is currently using,
      * whether the requested tool happens to be connected on ANY user
        (a strong signal of the misconfiguration),
      * a one-line remediation pointing at MCP_USER_EMAIL.
    """
    user = db.query(User).filter(User.id == user_id).first()
    other_users_with_any_conn = (
        db.query(DynamicToolConnection.user_id)
        .filter(DynamicToolConnection.is_active == True)  # noqa: E712
        .distinct()
        .all()
    )
    other_ids = sorted({uid for (uid,) in other_users_with_any_conn if uid != user_id})
    hint = {
        "current_mcp_user": {
            "id": user_id,
            "email": user.email if user else None,
            "username": user.username if user else None,
        },
    }
    if other_ids:
        # Don't leak other users' identities in detail — just signal
        # that another user has connections, so the operator knows to
        # check their MCP_USER_EMAIL value.
        hint["other_users_have_connections"] = True
        hint["remediation"] = (
            "If you connected this tool in the web UI as a different user, "
            "re-launch the MCP server with --env "
            "MCP_USER_EMAIL=<your-web-ui-email>. Run "
            "`python mcp_server.py --list-users` to see which emails exist."
        )
    else:
        hint["remediation"] = (
            "No connections exist for any user. Sign in to the web UI "
            "and connect this tool first."
        )
    return hint


def _json_block(payload: Any) -> List[TextContent]:
    """Return a single TextContent containing pretty JSON. MCP clients
    render text content in chat; JSON gives Claude maximum signal."""
    return [TextContent(type="text", text=json.dumps(payload, indent=2, default=str))]


# Adaptora-envelope keys the calling assistant never needs in order to answer.
# These describe Adaptora's own internal planning, not the tool's data, so the
# cloud model spends tokens reading them for nothing. Kept ONLY on errors
# (handled by the success-guard in `_compact_payload`) where they aid debugging.
_ENVELOPE_NOISE = {"thought", "action_input", "duration_ms", "log_id", "final_answer"}


def _compact_payload(payload: Any) -> Any:
    """Shrink an MCP response before it reaches the cloud model — generically.

    Two passes, BOTH tool-agnostic (no per-tool field lists, no hardcoding):
      1. Drop Adaptora's envelope metadata (`thought`, timings, …).
      2. Recursively drop null / empty / blank fields from the tool's own
         response via the shared `_strip_empties` helper.

    Works identically for every tool a user has connected or will connect in
    future — Razorpay, Spotify, AWS, or some API discovered tomorrow — because
    it reasons about JSON shape, not tool identity. Only successful responses
    are touched; errors pass through untouched so debugging stays easy."""
    if not isinstance(payload, dict) or payload.get("status") != "success":
        return payload
    slim = {k: v for k, v in payload.items() if k not in _ENVELOPE_NOISE}
    if "response" in slim:
        slim["response"] = _strip_empties(slim["response"])
    return slim


# Phase 2 — opt-in aggregation. When the user's prompt signals they want a
# rollup ("compare", "total", "graph"…) rather than individual rows, we
# replace large lists with generic stats. This is the big-saving path
# (~10x vs compaction's ~1.3x) and stays fully tool-agnostic: it profiles
# whatever fields the records happen to have, never a per-tool field list.
_SUMMARY_INTENT = re.compile(
    r"\b(compar|summar|aggregat|total|overall|how many|count|graph|chart|"
    r"trend|breakdown|overview|distribut|statistic|stats)\b",
    re.I,
)


def _wants_summary(prompt: Optional[str]) -> bool:
    return bool(prompt and _SUMMARY_INTENT.search(prompt))


def _aggregate_items(items: List[Any]) -> Dict[str, Any]:
    """Schema-agnostic stats for a list of record dicts. No tool knowledge —
    profiles whatever fields exist:
      * categorical fields (strings/bools, 2-8 distinct values) → value counts
      * numeric fields → sum/min/max, skipping constants (no signal) and
        epoch/id-like magnitudes (summing a timestamp is meaningless)."""
    out: Dict[str, Any] = {"count": len(items)}
    dicts = [x for x in items if isinstance(x, dict)]
    if not dicts:
        return out
    cats: Dict[str, Counter] = {}
    nums: Dict[str, List[float]] = {}
    for it in dicts:
        for k, v in it.items():
            if isinstance(v, bool):
                cats.setdefault(k, Counter())[str(v).lower()] += 1
            elif isinstance(v, (int, float)):
                nums.setdefault(k, []).append(v)
            elif isinstance(v, str) and v:
                cats.setdefault(k, Counter())[v] += 1
    by = {k: dict(c.most_common()) for k, c in cats.items() if 2 <= len(c) <= 8}
    totals: Dict[str, Any] = {}
    for k, vals in nums.items():
        lo, hi = min(vals), max(vals)
        if lo == hi:               # constant column — nothing to compare
            continue
        if hi >= 1_000_000_000:    # epoch/id-like — a sum would be noise
            continue
        totals[k] = {"sum": sum(vals), "min": lo, "max": hi}
    if by:
        out["by"] = by
    if totals:
        out["totals"] = totals
    return out


def _summarize_response(payload: Any) -> Any:
    """Collapse any list-of-records under `response` into generic aggregates.
    Tool-agnostic and lossy by design — only applied when the prompt asks for
    a rollup. Returns a NEW payload; anything without a sizable list is
    returned unchanged."""
    if not isinstance(payload, dict) or payload.get("status") != "success":
        return payload
    resp = payload.get("response")
    if not isinstance(resp, dict):
        return payload
    aggregated: Dict[str, Any] = {}
    changed = False
    for key, val in resp.items():
        if isinstance(val, list) and len(val) >= 3 and any(isinstance(x, dict) for x in val):
            aggregated[key] = _aggregate_items(val)
            changed = True
        else:
            aggregated[key] = val
    if not changed:
        return payload
    slim = {k: v for k, v in payload.items() if k != "response"}
    slim["response"] = aggregated
    slim["_summary"] = "aggregated stats — re-ask without summary/compare keywords for full rows"
    return slim


def _record_savings(db, raw: Any, sent: Any) -> None:
    """Persist how many cloud tokens the compaction saved on this response so
    the dashboard can total it. Best-effort: token accounting must NEVER break
    the actual tool call, so every failure is swallowed."""
    try:
        log_id = raw.get("log_id") if isinstance(raw, dict) else None
        if not log_id:
            return
        raw_tokens = count_tokens(json.dumps(raw, default=str))
        sent_tokens = count_tokens(json.dumps(sent, default=str))
        row = (
            db.query(DynamicAgentRunLog)
            .filter(DynamicAgentRunLog.id == log_id)
            .first()
        )
        if row is None:
            return
        row.raw_tokens = raw_tokens
        row.sent_tokens = sent_tokens
        row.tokens_saved = max(0, raw_tokens - sent_tokens)
        db.commit()
    except Exception as exc:  # pragma: no cover — accounting is non-critical
        logger.warning(f"token-savings accounting failed: {exc}")
        try:
            db.rollback()
        except Exception:
            pass


def build_mcp_server() -> Server:
    """Construct (but don't start) the MCP server. Pulled out so tests
    can inspect it without running stdio."""
    server: Server = Server("adaptora-dynamic-agent")

    @server.list_tools()
    async def handle_list_tools() -> List[Tool]:
        """Re-evaluated on every client request. Newly connected tools
        appear in the list automatically — no restart needed."""
        db = SessionLocal()
        try:
            tools = _meta_tool_defs() + _connected_endpoint_tools(db)
            _record_tool_list_stats(db)
            return tools
        finally:
            db.close()

    @server.call_tool()
    async def handle_call_tool(
        name: str, arguments: Dict[str, Any]
    ) -> List[TextContent]:
        """Single dispatch entry. Routes meta-tools first, then falls
        through to the dynamic per-endpoint dispatch."""
        arguments = arguments or {}
        db = SessionLocal()
        # Extract progress token from request context (may be None if
        # the client didn't include one — notifications are skipped then
        # but the queue is still drained to avoid memory growth).
        try:
            _ctx = server.request_context
            _meta = _ctx.meta
            progress_token = (_meta.progressToken if _meta else None)
            request_id = _ctx.request_id
        except Exception:
            progress_token = None
            request_id = None
        try:
            _ensure_mcp_user(db)
            if name == _META_SETUP:
                return await _call_setup_new_tool(db, arguments, server=server, progress_token=progress_token, request_id=request_id)
            if name == _META_REFRESH:
                return await _call_refresh(db, arguments, server=server, progress_token=progress_token, request_id=request_id)
            if name == _META_LIST_KNOWN:
                return _call_list_known(db)
            if name == _META_LIST_CONNS:
                return _call_list_connections(db)
            if name == _META_RUN_ACTION:
                return await _call_run_action(db, arguments, server=server, progress_token=progress_token, request_id=request_id)
            # Dynamic per-endpoint tool: <tool>_<endpoint>
            return await _call_endpoint_tool(db, name, arguments)
        except Exception as exc:
            logger.exception(f"MCP tool {name!r} crashed")
            return _json_block({"error": str(exc), "tool": name})
        finally:
            db.close()

    return server


# ───────────────────────── tool implementations ─────────────────────────


async def _call_setup_new_tool(
    db,
    args: Dict[str, Any],
    *,
    server: Optional[Server] = None,
    progress_token: Any = None,
    request_id: Any = None,
) -> List[TextContent]:
    tool = (args.get("tool") or "").strip().lower()
    if not tool:
        return _json_block({"error": "tool name is required"})
    force = bool(args.get("force_refresh", False))
    loop = asyncio.get_event_loop()
    cb, queue = _make_progress_callback(server, loop) if server else (None, asyncio.Queue())
    emitter = asyncio.create_task(
        _progress_emitter_task(server, queue, progress_token, request_id=request_id)
    ) if server else None
    try:
        tool_def = await asyncio.to_thread(
            dynamic_agent_service.lookup_or_fetch_docs,
            db,
            tool,
            force_refresh=force,
            status_callback=cb,
        )
    finally:
        await queue.put(None)
        if emitter:
            await emitter
    if not tool_def:
        return _json_block(
            {
                "error": (
                    f"Couldn't fetch docs for `{tool}`. We tried the web "
                    f"search, every common OpenAPI URL pattern, and the "
                    f"hosts returned by the search engine — nothing "
                    f"yielded a usable spec."
                ),
                "tool": tool,
            }
        )
    return _json_block(
        {
            "ok": True,
            "tool": tool_def.name,
            "display_name": tool_def.display_name,
            "base_url": tool_def.base_url,
            "auth_type": tool_def.auth_type,
            "endpoint_count": len(tool_def.endpoints or {}),
            "endpoints": list((tool_def.endpoints or {}).keys()),
            "source": tool_def.source,
            "docs_url": tool_def.docs_url,
            "next_step": (
                f"Open the web UI and connect `{tool_def.name}` to provide "
                f"credentials, then the per-endpoint MCP tools will become "
                f"callable."
            ),
        }
    )


async def _call_refresh(
    db,
    args: Dict[str, Any],
    *,
    server: Optional[Server] = None,
    progress_token: Any = None,
    request_id: Any = None,
) -> List[TextContent]:
    tool = (args.get("tool") or "").strip().lower()
    if not tool:
        return _json_block({"error": "tool name is required"})
    loop = asyncio.get_event_loop()
    cb, queue = _make_progress_callback(server, loop) if server else (None, asyncio.Queue())
    emitter = asyncio.create_task(
        _progress_emitter_task(server, queue, progress_token, request_id=request_id)
    ) if server else None
    try:
        tool_def = await asyncio.to_thread(
            dynamic_agent_service.lookup_or_fetch_docs,
            db,
            tool,
            force_refresh=True,
            status_callback=cb,
        )
    finally:
        await queue.put(None)
        if emitter:
            await emitter
    if not tool_def:
        return _json_block({"error": f"refresh failed for `{tool}`"})
    return _json_block(
        {
            "ok": True,
            "tool": tool_def.name,
            "endpoint_count": len(tool_def.endpoints or {}),
            "source": tool_def.source,
            "last_fetched_at": (
                tool_def.last_fetched_at.isoformat()
                if tool_def.last_fetched_at
                else None
            ),
        }
    )


def _call_list_known(db) -> List[TextContent]:
    rows = db.query(ToolDefinition).order_by(ToolDefinition.name.asc()).all()
    return _json_block(
        [
            {
                "name": r.name,
                "display_name": r.display_name,
                "base_url": r.base_url,
                "auth_type": r.auth_type,
                "endpoint_count": len(r.endpoints or {}),
                "source": r.source,
                "last_fetched_at": (
                    r.last_fetched_at.isoformat() if r.last_fetched_at else None
                ),
            }
            for r in rows
        ]
    )


def _call_list_connections(db) -> List[TextContent]:
    user_id = _resolve_mcp_user_id(db)
    rows = (
        db.query(DynamicToolConnection)
        .filter(
            DynamicToolConnection.user_id == user_id,
            DynamicToolConnection.is_active == True,  # noqa: E712
        )
        .order_by(DynamicToolConnection.tool_name.asc())
        .all()
    )
    # Include the resolved identity in the response so the user can
    # immediately see WHICH account they're MCP'd as. If `tool` is empty
    # but they thought they connected something, this is the first
    # diagnostic to check.
    user = db.query(User).filter(User.id == user_id).first()
    return _json_block(
        {
            "mcp_user": {
                "id": user_id,
                "email": user.email if user else None,
                "username": user.username if user else None,
            },
            "connections": [
                {
                    "tool": r.tool_name,
                    "auth_type": r.auth_type,
                    "last_used_at": r.last_used_at.isoformat() if r.last_used_at else None,
                }
                for r in rows
            ],
        }
    )


async def _call_run_action(
    db,
    args: Dict[str, Any],
    *,
    server: Optional[Server] = None,
    progress_token: Any = None,
    request_id: Any = None,
) -> List[TextContent]:
    prompt = (args.get("prompt") or "").strip()
    if not prompt:
        return _json_block({"error": "prompt is required"})
    language = args.get("language") or "en"
    if language not in ("en", "hinglish"):
        language = "en"
    user_id = _resolve_mcp_user_id(db)
    loop = asyncio.get_event_loop()
    cb, queue = _make_progress_callback(server, loop) if server else (None, asyncio.Queue())
    emitter = asyncio.create_task(
        _progress_emitter_task(server, queue, progress_token, request_id=request_id)
    ) if server else None
    try:
        result = await asyncio.to_thread(
            dynamic_agent_service.run_turn,
            db,
            user_id=user_id,
            prompt=prompt,
            language=language,
            status_callback=cb,
            # The calling assistant summarizes the raw response itself, so
            # skip the extra local-LLM summary round-trip (saves a whole
            # inference and shrinks the timeout window).
            summarize=False,
        )
    finally:
        await queue.put(None)
        if emitter:
            await emitter
    # If the agent says "needs_credentials" but we know this user has
    # zero connections, the most common cause is the wrong user being
    # used by MCP. Annotate the response with the resolved identity
    # so the user can spot the mismatch immediately.
    if isinstance(result, dict) and result.get("status") == "needs_credentials":
        result = dict(result)
        result["mcp_diagnostic"] = _identity_hint(db, user_id)
    # Phase 2: if the prompt asks for a rollup, aggregate large lists first
    # (big saving). Otherwise just compact (safe saving). Accounting compares
    # the original raw result against whatever we finally send.
    shaped = _summarize_response(result) if _wants_summary(prompt) else result
    compact = _compact_payload(shaped)
    _record_savings(db, result, compact)
    return _json_block(compact)


async def _call_endpoint_tool(
    db, name: str, args: Dict[str, Any]
) -> List[TextContent]:
    """Dispatch a per-endpoint MCP tool call. We don't know which token
    in ``name`` separates the tool from the endpoint — try the longest
    matching tool name first, since endpoint names can contain
    underscores too."""
    # Find the longest cached tool name that prefixes `name`.
    known = [
        n for (n,) in db.query(ToolDefinition.name).all() if n and name.startswith(f"{n}_")
    ]
    if not known:
        return _json_block(
            {"error": f"unknown tool {name!r} — not in the cached tool list"}
        )
    tool = max(known, key=len)
    endpoint = name[len(tool) + 1 :]

    user_id = _resolve_mcp_user_id(db)
    raw_prompt = args.pop("raw_prompt", None)

    if raw_prompt:
        # The caller explicitly wants natural-language planning (e.g. to
        # fill in fields it couldn't model). Use the full LLM pipeline.
        synthesized = (
            f"Using {tool}, perform the `{endpoint}` action. "
            f"Context: {raw_prompt}. Arguments: {json.dumps(args)}."
        )
        result = await asyncio.to_thread(
            dynamic_agent_service.run_turn,
            db,
            user_id=user_id,
            prompt=synthesized,
            language="en",
        )
    else:
        # FAST PATH: tool + endpoint are already known, so skip the LLM
        # entirely (no identify / plan / summarize). This is what keeps
        # per-endpoint MCP calls from timing out on a slow local model.
        result = await asyncio.to_thread(
            dynamic_agent_service.run_endpoint_action,
            db,
            user_id=user_id,
            tool_name=tool,
            endpoint_name=endpoint,
            arguments=args,
            language="en",
        )

    if isinstance(result, dict) and result.get("status") == "needs_credentials":
        result = dict(result)
        result["mcp_diagnostic"] = _identity_hint(db, user_id)
    compact = _compact_payload(result)
    _record_savings(db, result, compact)
    return _json_block(compact)


# ─────────────────────────── runtime entry points ───────────────────────────


_PASSTHROUGH_INSTRUCTIONS = """\
You are a transparent relay for the Adaptora AI agent. Your ONLY job is to \
call the `run_action` tool immediately with the user's exact message verbatim.

Rules — follow without exception:
1. For EVERY user message, call `run_action` with prompt = the user's exact \
   text. Do NOT paraphrase, summarize, or alter it in any way.
2. Do NOT think, plan, interpret, or reason about the request yourself.
3. Do NOT write any text before or after calling `run_action`.
4. Do NOT use any other tool unless the user explicitly asks you to \
   (e.g. "list my connections" → `list_connections`, "set up github" → \
   `setup_new_tool`). For everything else: `run_action`.
5. Return the tool result exactly as-is. Add no commentary.

The Adaptora agent (powered by a local Ollama LLM) handles all intelligence. \
Your role is purely to forward the message and return the answer.\
"""


def _isolate_stdout_for_protocol():
    """Make stdout (fd 1) PRIVATE to the MCP JSON-RPC transport.

    stdio MCP uses fd 1 exclusively for protocol frames — one JSON
    message per line. Any other write to stdout corrupts the stream and
    the client dies with "Unexpected non-whitespace character after JSON
    at position 4" (the "2026" of a log timestamp parses as a number,
    then the "-" breaks it). Per-`print()` fixes can't cover third-party
    libraries (googlesearch, ollama, httpx, C extensions) that write to
    stdout during a request, so we close that whole class of bug here:

      * dup the real stdout to a private fd → hand ONLY this to the
        transport, so protocol frames still reach the client;
      * dup2 stderr onto fd 1 → every other write to stdout (from any
        language level, including C) now lands on stderr, harmlessly;
      * repoint sys.stdout at sys.stderr → Python-level prints follow.

    Returns an anyio-wrapped text file over the private stdout, ready to
    pass as ``stdio_server(stdout=...)``.
    """
    import anyio

    sys.stdout.flush()
    real_stdout_fd = os.dup(1)          # private copy of the true stdout
    os.dup2(2, 1)                       # fd 1 now points at stderr
    sys.stdout = sys.stderr             # Python-level prints → stderr too
    real_stdout = os.fdopen(
        real_stdout_fd, "w", encoding="utf-8", buffering=1
    )
    return anyio.wrap_file(real_stdout)


async def run_stdio() -> None:
    """Run the MCP server over stdio (the standard transport for
    desktop MCP clients like Claude Desktop)."""
    # Lock down stdout BEFORE anything else can write to it (warmup,
    # request handling, third-party libs). See the function docstring.
    protocol_stdout = _isolate_stdout_for_protocol()
    init_db()  # ensure tables exist on first run
    # Warm the local model in the background so the first run_action is
    # already resident in memory instead of paying a ~30s cold load inside
    # the request (which is what tripped the MCP client's timeout). Runs in
    # a thread so it never blocks the server from accepting connections.
    # Keep a reference so the task isn't garbage-collected before it runs.
    _warmup_task = asyncio.create_task(asyncio.to_thread(warmup_model))  # noqa: F841
    server = build_mcp_server()
    init_options = server.create_initialization_options()
    init_options.instructions = _PASSTHROUGH_INSTRUCTIONS
    async with stdio_server(stdout=protocol_stdout) as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            init_options,
        )


def _print_users() -> int:
    """Print the user table so the operator can pick the right
    MCP_USER_EMAIL / MCP_USER_ID value. Doesn't print password hashes
    or any other secret. Returns a process exit code (0 = success)."""
    init_db()
    db = SessionLocal()
    try:
        users = db.query(User).order_by(User.id.asc()).all()
        if not users:
            print(
                "No users found. Sign up at the web UI first "
                "(http://localhost:8000), then re-run this command."
            )
            return 1
        print(f"{'ID':>4}  {'EMAIL':<40}  USERNAME")
        print(f"{'─'*4}  {'─'*40}  {'─'*20}")
        for u in users:
            email = (u.email or "")[:40]
            username = (u.username or "")[:20]
            print(f"{u.id:>4}  {email:<40}  {username}")
        print()
        print(
            "Use in your MCP client config:\n"
            "  --env MCP_USER_EMAIL=<email from above>\n"
            "or, if you prefer the numeric ID:\n"
            "  --env MCP_USER_ID=<id from above>"
        )
        return 0
    finally:
        db.close()


def main() -> None:
    """Console entry point.

    Modes:
      * ``python mcp_server.py``               — run the MCP server (stdio)
      * ``python mcp_server.py --list-users``  — print known users + how to
                                                 configure MCP for them
    """
    args = sys.argv[1:]
    if args and args[0] in ("--list-users", "-l", "list-users"):
        raise SystemExit(_print_users())
    try:
        asyncio.run(run_stdio())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
