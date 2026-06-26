"""HTTP API for the Dynamic Agent (Nango-free).

All routes are mounted under ``/api/dynamic-agent`` and require an
authenticated user. The lifecycle:

  1. POST /turn                     → run one user turn; may return
                                      needs_credentials with a field schema
  2. POST /credentials              → submit creds collected in step 1
  3. POST /turn  (again)            → now the agent can plan + execute
  4. GET  /connections              → list active connections
  5. DELETE /connections/{id}       → disconnect
  6. GET  /tools                    → list known tool definitions
  7. POST /tools/refresh            → force re-fetch a tool's docs
  8. GET  /logs                     → audit trail
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import queue
import secrets
import threading
import time
import urllib.parse
from typing import Any, Dict, List, Optional

import requests as http_requests
from fastapi import (
    APIRouter,
    Depends,
    File as FastAPIFile,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import RedirectResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.logger import logger
from app.db.database import SessionLocal, get_db
from app.db.models import (
    DeveloperApiKey,
    DynamicAgentRunLog,
    DynamicToolConnection,
    McpToolListStat,
    ToolDefinition,
    User,
)
from app.core.security import decode_token, encrypt_api_key
from app.routes.auth import get_current_user
from app.services.dynamic_agent_service import (
    DynamicAgentError,
    dynamic_agent_service,
)


router = APIRouter(prefix="/api/dynamic-agent", tags=["Dynamic Agent"])


# ---------------------------------------------------------------- schemas


class TurnRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    language: str = Field("en", description="'en' or 'hinglish'")


class TurnResponse(BaseModel):
    log_id: int
    status: str  # success | needs_credentials | needs_tool_setup | error
    tool: Optional[str] = None
    thought: Optional[str] = None
    action: Optional[str] = None
    action_input: Optional[Any] = None
    summary: Optional[str] = None
    final_answer: Optional[str] = None
    http_status: Optional[int] = None
    response: Optional[Any] = None
    error: Optional[str] = None
    duration_ms: float
    language: str


class CredentialsRequest(BaseModel):
    tool: str = Field(..., min_length=1)
    credentials: Dict[str, Any] = Field(..., description="Field name → value")


class CredentialsResponse(BaseModel):
    tool: str
    display_name: str
    auth_type: str
    connection_id: int
    test_status: str  # ok | failed | skipped
    test_detail: Optional[str] = None


class ConnectionItem(BaseModel):
    id: int
    tool: str
    display_name: Optional[str] = None
    auth_type: str
    is_authorized: bool = True  # False for OAUTH2 connections missing access_token
    token_expires_at: Optional[str] = None
    last_used_at: Optional[str] = None
    created_at: str


class ToolItem(BaseModel):
    name: str
    display_name: str
    base_url: str
    auth_type: str
    endpoint_count: int
    source: str
    docs_url: Optional[str] = None
    last_fetched_at: Optional[str] = None


class RunLogItem(BaseModel):
    id: int
    tool: Optional[str] = None
    # Which developer key triggered this run (None = web UI / MCP).
    api_key_id: Optional[int] = None
    key_label: Optional[str] = None
    source: str = "ui"  # "api" if produced via a developer key, else "ui"
    language: str
    prompt: str
    thought: Optional[str] = None
    action: Optional[str] = None
    action_input: Optional[Any] = None
    summary: Optional[str] = None
    final_answer: Optional[str] = None
    status: str
    http_status: Optional[int] = None
    response_body: Optional[str] = None
    error: Optional[str] = None
    duration_ms: float
    created_at: str


# ---------------------------------------------------------------- endpoints


@router.post("/turn", response_model=TurnResponse)
async def turn(
    payload: TurnRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Run one full agent turn. May return ``needs_credentials`` with a
    field schema the frontend renders to collect the creds, then the user
    POSTs to ``/credentials`` and re-runs ``/turn``."""
    try:
        result = dynamic_agent_service.run_turn(
            db,
            user_id=current_user.id,
            prompt=payload.prompt,
            language=payload.language,
        )
    except Exception as exc:
        logger.exception("dynamic agent turn failed")
        raise HTTPException(status_code=500, detail=f"Agent error: {exc}")
    return TurnResponse(**result)


@router.post("/turn/stream")
async def turn_stream(
    payload: TurnRequest,
    current_user: User = Depends(get_current_user),
):
    """Server-Sent Events variant of ``/turn``.

    Emits one ``status`` event per pipeline step
    (``identifying_tool``, ``tool_identified``, ``looking_up_docs``,
    ``docs_loaded``, ``checking_connection``, ``connection_found`` /
    ``connection_missing``, ``planning_action``, ``action_planned``,
    ``executing``, ``executed``, ``summarizing``), then a final ``done``
    event whose data payload is the full turn result (same shape as
    ``TurnResponse``).

    SOLVES the AWS 504 problem: ALBs / nginx / CloudFront kill idle
    connections after 60 seconds. With SSE we emit per-step bytes (and a
    keepalive comment every 15 s while Ollama is still grinding), so the
    proxy sees continuous activity and never times out — even when the
    underlying Ollama EC2 takes a minute on cold load."""
    # FastAPI's Session dependency lives only for the request lifetime —
    # but we hand work off to a worker thread that outlives the function
    # return, so we mint a fresh session inside the worker (mirroring the
    # /api/process/stream pattern).

    events_q: "queue.Queue" = queue.Queue()
    _SENTINEL = object()

    def emit_status(step: str, data: Dict[str, Any]) -> None:
        events_q.put({"step": step, **(data or {})})

    result_box: Dict[str, Any] = {"response": None, "error": None}
    user_id = current_user.id
    prompt = payload.prompt
    language = payload.language

    def run_pipeline() -> None:
        worker_db = SessionLocal()
        try:
            result = dynamic_agent_service.run_turn(
                worker_db,
                user_id=user_id,
                prompt=prompt,
                language=language,
                status_callback=emit_status,
            )
            result_box["response"] = result
        except Exception as exc:
            logger.exception("dynamic agent stream pipeline failed")
            result_box["error"] = str(exc)
        finally:
            worker_db.close()
            events_q.put(_SENTINEL)

    threading.Thread(target=run_pipeline, daemon=True).start()

    HEARTBEAT_SECONDS = 15

    def event_source():
        # Prime the connection so proxies see bytes immediately and don't
        # buffer until the first chunk arrives.
        yield ": stream-open\n\n"
        while True:
            try:
                evt = events_q.get(timeout=HEARTBEAT_SECONDS)
            except queue.Empty:
                # No status update for HEARTBEAT_SECONDS — emit an SSE
                # comment line so ALB / nginx see activity and don't time
                # out. The browser's EventSource parser ignores comments.
                yield f": keepalive {int(time.time())}\n\n"
                continue
            if evt is _SENTINEL:
                if result_box["error"]:
                    yield f"event: error\ndata: {json.dumps({'error': result_box['error']})}\n\n"
                else:
                    yield (
                        f"event: done\n"
                        f"data: {json.dumps(result_box['response'], default=str)}\n\n"
                    )
                break
            yield f"event: status\ndata: {json.dumps(evt, default=str)}\n\n"

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # Disable nginx response buffering on the path so events flush
            # to the client immediately instead of getting batched.
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/credentials", response_model=CredentialsResponse)
async def submit_credentials(
    payload: CredentialsRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Persist credentials for a tool, then optionally smoke-test them.

    For API_KEY / BEARER / PAT we run the tool's first GET endpoint to
    verify the secret works. For OAUTH2 we just store the client_id/secret
    pair — the actual authorize round-trip happens on a follow-up turn."""
    tool = (
        db.query(ToolDefinition)
        .filter(ToolDefinition.name == payload.tool.strip().lower())
        .first()
    )
    if not tool:
        # Lazy-fetch: maybe the user is supplying creds for a tool we
        # haven't fetched docs for yet.
        tool = dynamic_agent_service.lookup_or_fetch_docs(
            db, payload.tool.strip().lower()
        )
        if not tool:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Tool `{payload.tool}` not found and no docs could "
                    "be fetched. Try a different name or set up manually."
                ),
            )

    # Normalize shorthand — frontend may send 'api_key' or 'token' where
    # the agent expects 'secret' for API_KEY/BEARER/PAT.
    creds = dict(payload.credentials)
    if (tool.auth_type or "").upper() in ("API_KEY", "BEARER", "PAT"):
        if "secret" not in creds:
            for alias in ("api_key", "token", "pat", "value"):
                if alias in creds and creds[alias]:
                    creds["secret"] = creds[alias]
                    break

    connection = dynamic_agent_service.save_credentials(
        db,
        user_id=current_user.id,
        tool=tool,
        credentials=creds,
    )

    # Smoke test the new credentials by making one safe call. Picks a
    # provider-appropriate "whoami" / first GET endpoint. Skipped for
    # OAUTH2 because we only have client_id/secret on file — no access
    # token to test yet.
    test_status = "skipped"
    test_detail: Optional[str] = None
    auth_type_upper = (tool.auth_type or "").upper()

    def _record_test(http_status: Optional[int], body: Any, exc: Optional[Exception]) -> None:
        nonlocal test_status, test_detail
        if exc is not None:
            test_status = "failed"
            test_detail = str(exc)
            return
        if http_status is not None and http_status < 400:
            test_status = "ok"
            test_detail = f"HTTP {http_status}"
        else:
            test_status = "failed"
            test_detail = (
                body if isinstance(body, str) else json.dumps(body, default=str)
            )[:300] if body is not None else f"HTTP {http_status}"

    if auth_type_upper == "AWS_SIGV4":
        # sts:GetCallerIdentity returns the IAM identity if creds are
        # valid; it requires no permissions, so it's the canonical AWS
        # smoke test.
        try:
            http_status, body = dynamic_agent_service.execute_http(
                tool=tool,
                connection=connection,
                method="POST",
                endpoint="sts/get_caller_identity",
            )
            _record_test(http_status, body, None)
        except DynamicAgentError as exc:
            _record_test(None, None, exc)
        except Exception as exc:
            logger.exception("AWS credential smoke-test crashed")
            _record_test(None, None, exc)
    elif auth_type_upper in ("API_KEY", "BEARER", "PAT", "BASIC"):
        first_get = next(
            (
                ep
                for ep in (tool.endpoints or {}).values()
                if isinstance(ep, dict) and (ep.get("method") or "").upper() == "GET"
            ),
            None,
        )
        if first_get and first_get.get("path") and "{" not in first_get["path"]:
            try:
                http_status, body = dynamic_agent_service.execute_http(
                    tool=tool,
                    connection=connection,
                    method="GET",
                    endpoint=first_get["path"],
                )
                _record_test(http_status, body, None)
            except DynamicAgentError as exc:
                _record_test(None, None, exc)
            except Exception as exc:
                logger.exception("credential smoke-test crashed")
                _record_test(None, None, exc)

    return CredentialsResponse(
        tool=tool.name,
        display_name=tool.display_name or tool.name,
        auth_type=tool.auth_type or "API_KEY",
        connection_id=connection.id,
        test_status=test_status,
        test_detail=test_detail,
    )


@router.get("/connections", response_model=List[ConnectionItem])
async def list_connections(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(DynamicToolConnection)
        .filter(
            DynamicToolConnection.user_id == current_user.id,
            DynamicToolConnection.is_active == True,  # noqa: E712
        )
        .order_by(DynamicToolConnection.created_at.desc())
        .all()
    )
    items = []
    for r in rows:
        at = (r.auth_type or "API_KEY").upper()
        is_authorized = True
        if at in ("OAUTH2", "OAUTH2_PKCE"):
            creds = dynamic_agent_service.decrypt_credentials(r)
            is_authorized = bool(creds.get("access_token"))
        items.append(ConnectionItem(
            id=r.id,
            tool=r.tool_name,
            display_name=r.display_name,
            auth_type=r.auth_type or "API_KEY",
            is_authorized=is_authorized,
            token_expires_at=r.token_expires_at.isoformat() if r.token_expires_at else None,
            last_used_at=r.last_used_at.isoformat() if r.last_used_at else None,
            created_at=r.created_at.isoformat(),
        ))
    return items


@router.delete("/connections/{connection_id}")
async def delete_connection(
    connection_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = (
        db.query(DynamicToolConnection)
        .filter(
            DynamicToolConnection.id == connection_id,
            DynamicToolConnection.user_id == current_user.id,
        )
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Connection not found")
    row.is_active = False
    db.commit()
    return {"ok": True}


@router.get("/tools", response_model=List[ToolItem])
async def list_tools(
    current_user: User = Depends(get_current_user),  # noqa: ARG001
    db: Session = Depends(get_db),
):
    """All tool definitions we've cached so far (seeds + LLM-fetched)."""
    rows = (
        db.query(ToolDefinition)
        .order_by(ToolDefinition.name.asc())
        .all()
    )
    return [
        ToolItem(
            name=t.name,
            display_name=t.display_name or t.name,
            base_url=t.base_url or "",
            auth_type=t.auth_type or "API_KEY",
            endpoint_count=len(t.endpoints or {}),
            source=t.source or "llm",
            docs_url=t.docs_url,
            last_fetched_at=t.last_fetched_at.isoformat() if t.last_fetched_at else None,
        )
        for t in rows
    ]


@router.get("/tools/{name}")
async def get_tool(
    name: str,
    current_user: User = Depends(get_current_user),  # noqa: ARG001
    db: Session = Depends(get_db),
):
    tool = (
        db.query(ToolDefinition)
        .filter(ToolDefinition.name == name.strip().lower())
        .first()
    )
    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")
    return {
        "name": tool.name,
        "display_name": tool.display_name,
        "base_url": tool.base_url,
        "auth_type": tool.auth_type,
        "auth_config": tool.auth_config or {},
        "endpoints": tool.endpoints or {},
        "rate_limits": tool.rate_limits,
        "examples": tool.examples,
        "docs_url": tool.docs_url,
        "source": tool.source,
        "last_fetched_at": tool.last_fetched_at.isoformat() if tool.last_fetched_at else None,
        "credential_fields": dynamic_agent_service.required_credential_fields(tool),
    }


@router.post("/tools/refresh")
async def refresh_tool(
    payload: Dict[str, Any],
    current_user: User = Depends(get_current_user),  # noqa: ARG001
    db: Session = Depends(get_db),
):
    """Force re-fetch a tool's docs via web search + LLM extract."""
    name = (payload.get("tool") or "").strip().lower()
    if not name:
        raise HTTPException(status_code=400, detail="`tool` is required")
    tool = dynamic_agent_service.lookup_or_fetch_docs(db, name, force_refresh=True)
    if not tool:
        raise HTTPException(
            status_code=404,
            detail=f"Couldn't fetch docs for `{name}` from the web.",
        )
    return {
        "name": tool.name,
        "source": tool.source,
        "endpoint_count": len(tool.endpoints or {}),
        "last_fetched_at": tool.last_fetched_at.isoformat() if tool.last_fetched_at else None,
    }


@router.post("/tools/import")
async def import_tool(
    tool: str = Form(...),
    spec_url: Optional[str] = Form(None),
    file: Optional[UploadFile] = FastAPIFile(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Build a tool from a USER-SUPPLIED source instead of web discovery.

    Send multipart/form-data with `tool` and ONE of:
      • `spec_url`  — link to an OpenAPI/Swagger spec or a doc page, or
      • `file`      — an uploaded OpenAPI JSON/YAML (most accurate) or any
                      text / markdown / HTML doc.

    An OpenAPI/Swagger spec is parsed natively → all endpoints, exact. Other
    docs are extracted by the LLM from the supplied content."""
    name = (tool or "").strip().lower()
    if not name:
        raise HTTPException(status_code=400, detail="`tool` is required")

    spec_url = (spec_url or "").strip() or None
    file_bytes: Optional[bytes] = None
    filename: Optional[str] = None
    file_ct: Optional[str] = None
    if file is not None:
        file_bytes = await file.read()
        filename = file.filename
        file_ct = file.content_type
    if not spec_url and not file_bytes:
        raise HTTPException(
            status_code=400,
            detail="Provide either `spec_url` or a `file` upload.",
        )

    try:
        result = dynamic_agent_service.import_tool_from_source(
            db, name, source_url=spec_url, file_bytes=file_bytes,
            filename=filename, content_type=file_ct, user_id=current_user.id,
        )
    except Exception as exc:
        logger.exception("tool import failed")
        raise HTTPException(status_code=500, detail=f"Import failed: {exc}")

    if not result:
        raise HTTPException(
            status_code=422,
            detail="Couldn't build a tool from that source — make sure it's an "
            "OpenAPI/Swagger spec or a doc page that lists endpoints + base URL.",
        )
    return {
        "name": result.name,
        "source": result.source,
        "base_url": result.base_url,
        "auth_type": result.auth_type,
        "endpoint_count": len(result.endpoints or {}),
    }


@router.post("/tools/refresh/stream")
async def refresh_tool_stream(
    payload: Dict[str, Any],
    current_user: User = Depends(get_current_user),  # noqa: ARG001
):
    """SSE variant of /tools/refresh.

    Emits one ``status`` event per pipeline stage so the user sees what's
    happening during a slow web-extraction (which can take 20-30s):

      starting → searching_web → web_results → openapi_parsed? →
      enriching → prompt_built → llm_extracting → saved

    Concluded by a ``done`` event with the saved tool, or an ``error``
    event if no usable docs were found. Mirrors the keepalive +
    threadpool pattern from /turn/stream so proxies (ALB / nginx /
    CloudFront) don't kill the connection mid-Ollama-call."""
    name = (payload.get("tool") or "").strip().lower()
    if not name:
        raise HTTPException(status_code=400, detail="`tool` is required")

    events_q: "queue.Queue" = queue.Queue()
    _SENTINEL = object()
    result_box: Dict[str, Any] = {"tool": None, "error": None}

    def emit_status(step: str, data: Dict[str, Any]) -> None:
        events_q.put({"step": step, **(data or {})})

    def run_refresh() -> None:
        worker_db = SessionLocal()
        try:
            tool = dynamic_agent_service.lookup_or_fetch_docs(
                worker_db,
                name,
                force_refresh=True,
                status_callback=emit_status,
            )
            if tool is None:
                result_box["error"] = (
                    f"Couldn't fetch docs for `{name}`. We tried the web "
                    f"search, every common OpenAPI spec URL pattern "
                    f"(api.{name}.com/openapi.json, /swagger.json, etc.), "
                    f"and the hosts returned by the search engine — nothing "
                    f"yielded a usable spec. The tool may not publish a "
                    f"public OpenAPI/Swagger document. Try a more specific "
                    f"name (e.g. `microsoft-graph` instead of `teams`)."
                )
            else:
                result_box["tool"] = {
                    "name": tool.name,
                    "display_name": tool.display_name,
                    "source": tool.source,
                    "auth_type": tool.auth_type,
                    "base_url": tool.base_url,
                    "endpoint_count": len(tool.endpoints or {}),
                    "has_rate_limits": tool.rate_limits is not None,
                    "examples_count": len(tool.examples or []),
                    "last_fetched_at": (
                        tool.last_fetched_at.isoformat()
                        if tool.last_fetched_at
                        else None
                    ),
                }
        except Exception as exc:
            logger.exception("refresh stream failed")
            result_box["error"] = str(exc)
        finally:
            worker_db.close()
            events_q.put(_SENTINEL)

    threading.Thread(target=run_refresh, daemon=True).start()

    HEARTBEAT_SECONDS = 15

    def event_source():
        # Prime the connection so proxies see bytes immediately.
        yield ": stream-open\n\n"
        while True:
            try:
                evt = events_q.get(timeout=HEARTBEAT_SECONDS)
            except queue.Empty:
                yield f": keepalive {int(time.time())}\n\n"
                continue
            if evt is _SENTINEL:
                if result_box["error"]:
                    yield (
                        f"event: error\n"
                        f"data: {json.dumps({'error': result_box['error']})}\n\n"
                    )
                else:
                    yield (
                        f"event: done\n"
                        f"data: {json.dumps(result_box['tool'], default=str)}\n\n"
                    )
                break
            yield f"event: status\ndata: {json.dumps(evt, default=str)}\n\n"

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/logs", response_model=List[RunLogItem])
async def list_logs(
    limit: int = 50,
    offset: int = Query(0, ge=0, description="Rows to skip — for pagination"),
    tool: Optional[str] = Query(None, description="Filter by tool name"),
    source: Optional[str] = Query(
        None, description="'api' (developer-key runs) or 'ui' (web UI / MCP)"
    ),
    status: Optional[str] = Query(
        None,
        description="Filter by run status, e.g. 'error', 'success'. "
        "Use 'error' to surface only failed runs for debugging.",
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(DynamicAgentRunLog).filter(
        DynamicAgentRunLog.user_id == current_user.id
    )
    if tool:
        q = q.filter(DynamicAgentRunLog.tool_name == tool)
    if source == "api":
        q = q.filter(DynamicAgentRunLog.api_key_id.isnot(None))
    elif source == "ui":
        q = q.filter(DynamicAgentRunLog.api_key_id.is_(None))
    if status:
        q = q.filter(DynamicAgentRunLog.status == status)

    rows = (
        q.order_by(DynamicAgentRunLog.created_at.desc())
        .offset(max(offset, 0))
        .limit(min(max(limit, 1), 200))
        .all()
    )

    # Resolve key labels in one query for the keys referenced by this page.
    key_ids = {r.api_key_id for r in rows if r.api_key_id}
    labels: Dict[int, str] = {}
    if key_ids:
        labels = {
            k.id: k.label
            for k in db.query(DeveloperApiKey)
            .filter(DeveloperApiKey.id.in_(key_ids))
            .all()
        }

    return [
        RunLogItem(
            id=r.id,
            tool=r.tool_name,
            api_key_id=r.api_key_id,
            key_label=labels.get(r.api_key_id) if r.api_key_id else None,
            source="api" if r.api_key_id else "ui",
            language=r.language or "en",
            prompt=r.prompt,
            thought=r.thought,
            action=r.action,
            action_input=r.action_input,
            summary=r.summary,
            final_answer=r.final_answer,
            status=r.status,
            http_status=r.http_status,
            response_body=r.response_body,
            error=r.error,
            duration_ms=r.duration_ms or 0.0,
            created_at=r.created_at.isoformat(),
        )
        for r in rows
    ]


@router.get("/logs/tools", response_model=List[str])
async def list_log_tools(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Distinct tool names that appear in this user's run logs — powers the
    tool dropdown on the logs page."""
    rows = (
        db.query(DynamicAgentRunLog.tool_name)
        .filter(
            DynamicAgentRunLog.user_id == current_user.id,
            DynamicAgentRunLog.tool_name.isnot(None),
        )
        .distinct()
        .all()
    )
    return sorted({r.tool_name for r in rows if r.tool_name})


@router.get("/logs/stream")
async def logs_stream(current_user: User = Depends(get_current_user)):
    """Live SSE feed of pipeline steps for this user's runs.

    Subscribes to the user's Redis channel and forwards every step
    (``received`` → ``identifying_tool`` → … → ``done``) as it happens —
    including runs triggered from a developer's curl against ``/api/v1/run``
    in a different process. The dashboard renders these as a live, step-by-step
    execution trace. If Redis is unavailable the stream just heartbeats and the
    dashboard relies on polling instead.
    """
    from app.services.event_bus import make_subscription

    user_id = current_user.id
    pubsub = make_subscription(user_id)
    events_q: "queue.Queue" = queue.Queue()
    stop = threading.Event()

    def reader() -> None:
        if pubsub is None:
            return
        try:
            while not stop.is_set():
                msg = pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if msg and msg.get("type") == "message":
                    data = msg.get("data")
                    if isinstance(data, (bytes, bytearray)):
                        data = data.decode("utf-8", "ignore")
                    try:
                        events_q.put(json.loads(data))
                    except Exception:
                        pass
        finally:
            try:
                pubsub.close()
            except Exception:
                pass

    threading.Thread(target=reader, daemon=True).start()

    HEARTBEAT_SECONDS = 15

    def event_source():
        # Prime the connection so proxies flush immediately.
        yield ": stream-open\n\n"
        try:
            while True:
                try:
                    evt = events_q.get(timeout=HEARTBEAT_SECONDS)
                except queue.Empty:
                    yield f": keepalive {int(time.time())}\n\n"
                    continue
                yield f"event: step\ndata: {json.dumps(evt, default=str)}\n\n"
        finally:
            # Client disconnected / generator closed — stop the reader thread.
            stop.set()

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------- OAuth2 flow
# In-memory state store: state_token → {user_id, tool_name}
# Short-lived (10 min TTL enforced by the callback).
_OAUTH_STATES: Dict[str, Dict[str, Any]] = {}
_OAUTH_STATE_TTL = 600  # seconds

# Override the callback base URL via env var (useful when running behind a
# reverse proxy or when the provider requires https but the app runs on http).
# Example: OAUTH_REDIRECT_BASE_URL=https://localhost:8000
_OAUTH_REDIRECT_BASE_URL = os.environ.get("OAUTH_REDIRECT_BASE_URL", "").rstrip("/")


def _callback_uri(request: Request) -> str:
    base = _OAUTH_REDIRECT_BASE_URL or str(request.base_url).rstrip("/")
    return f"{base}/api/dynamic-agent/oauth/callback"


@router.get("/oauth/authorize/{tool_name}")
async def oauth_authorize(
    tool_name: str,
    request: Request,
    db: Session = Depends(get_db),
    token: Optional[str] = Query(None),
):
    """Start OAuth2 authorization code flow for a tool.

    Accepts the JWT either via Authorization header (normal API calls) or via
    ?token= query param (browser redirect where headers can't be set).
    """
    # Resolve user from query-param token (browser redirect) or header.
    current_user = None
    if token:
        payload = decode_token(token)
        if payload:
            try:
                uid = int(payload.get("sub"))
            except (TypeError, ValueError):
                uid = None
            if uid:
                current_user = db.query(User).filter(User.id == uid).first()
    if current_user is None:
        # Fall back to Authorization header via the normal dependency.
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            payload = decode_token(auth_header[7:])
            if payload:
                try:
                    uid = int(payload.get("sub"))
                except (TypeError, ValueError):
                    uid = None
                if uid:
                    current_user = db.query(User).filter(User.id == uid).first()
    if current_user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    tool = (
        db.query(ToolDefinition)
        .filter(ToolDefinition.name == tool_name.strip().lower())
        .first()
    )
    if not tool:
        raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found.")

    cfg = tool.auth_config or {}
    authorize_url = cfg.get("oauth_authorize_url")
    if not authorize_url:
        raise HTTPException(
            status_code=400,
            detail=f"Tool '{tool_name}' has no oauth_authorize_url configured.",
        )

    conn = (
        db.query(DynamicToolConnection)
        .filter(
            DynamicToolConnection.user_id == current_user.id,
            DynamicToolConnection.tool_name == tool.name,
            DynamicToolConnection.is_active == True,
        )
        .first()
    )
    if not conn:
        raise HTTPException(
            status_code=400,
            detail=f"No saved credentials for '{tool_name}'. Save client_id/secret first.",
        )

    creds = dynamic_agent_service.decrypt_credentials(conn)
    client_id = creds.get("client_id")
    if not client_id:
        raise HTTPException(
            status_code=400,
            detail="client_id not found in saved credentials.",
        )

    state = secrets.token_urlsafe(32)
    _OAUTH_STATES[state] = {
        "user_id": current_user.id,
        "tool_name": tool.name,
        "created_at": time.time(),
    }

    callback_uri = _callback_uri(request)

    scopes = creds.get("scopes") or cfg.get("default_scopes") or ""
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": callback_uri,
        "state": state,
        "scope": scopes,
    }
    full_url = authorize_url + "?" + urllib.parse.urlencode(params)
    return RedirectResponse(url=full_url)


@router.get("/oauth/callback")
async def oauth_callback(
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
    request: Request = None,
    db: Session = Depends(get_db),
):
    """Handle the OAuth2 callback, exchange code for tokens, update credentials."""
    if error:
        return RedirectResponse(url=f"/?oauth_error={urllib.parse.quote(error)}")

    if not state or state not in _OAUTH_STATES:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state.")

    state_data = _OAUTH_STATES.pop(state)
    if time.time() - state_data["created_at"] > _OAUTH_STATE_TTL:
        raise HTTPException(status_code=400, detail="OAuth state expired. Try again.")

    user_id = state_data["user_id"]
    tool_name = state_data["tool_name"]

    tool = db.query(ToolDefinition).filter(ToolDefinition.name == tool_name).first()
    if not tool:
        raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found.")

    cfg = tool.auth_config or {}
    token_url = cfg.get("oauth_token_url")
    if not token_url:
        raise HTTPException(
            status_code=400,
            detail=f"Tool '{tool_name}' has no oauth_token_url configured.",
        )

    conn = (
        db.query(DynamicToolConnection)
        .filter(
            DynamicToolConnection.user_id == user_id,
            DynamicToolConnection.tool_name == tool_name,
            DynamicToolConnection.is_active == True,
        )
        .first()
    )
    if not conn:
        raise HTTPException(status_code=400, detail="No credentials row found.")

    creds = dynamic_agent_service.decrypt_credentials(conn)
    client_id = creds.get("client_id", "")
    client_secret = creds.get("client_secret", "")

    callback_uri = _callback_uri(request)

    try:
        resp = http_requests.post(
            token_url,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": callback_uri,
                "client_id": client_id,
                "client_secret": client_secret,
            },
            headers={"Accept": "application/json"},
            timeout=15,
        )
        resp.raise_for_status()
        token_data = resp.json()
    except Exception as exc:
        logger.error("OAuth2 token exchange failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"Token exchange failed: {exc}")

    access_token = token_data.get("access_token")
    if not access_token:
        raise HTTPException(
            status_code=502,
            detail=f"Provider returned no access_token: {token_data}",
        )

    # Merge new tokens into existing credentials and re-encrypt.
    creds["access_token"] = access_token
    if token_data.get("refresh_token"):
        creds["refresh_token"] = token_data["refresh_token"]
    if token_data.get("expires_in"):
        from datetime import datetime, timedelta
        conn.token_expires_at = datetime.utcnow() + timedelta(
            seconds=int(token_data["expires_in"])
        )

    conn.credentials_encrypted = encrypt_api_key(json.dumps(creds, default=str))
    db.commit()

    logger.info("OAuth2 token stored for user=%s tool=%s", user_id, tool_name)
    return RedirectResponse(url="/?oauth_success=1&tool=" + urllib.parse.quote(tool_name))


@router.get("/savings")
async def token_savings(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Total cloud tokens saved by response-compaction for this user.

    Powers the dashboard's "tokens saved" metric. Aggregates the per-run
    accounting written by the MCP transport layer — tool-agnostic, so it
    covers every tool the user has called."""
    saved, raw, sent, calls = (
        db.query(
            func.coalesce(func.sum(DynamicAgentRunLog.tokens_saved), 0),
            func.coalesce(func.sum(DynamicAgentRunLog.raw_tokens), 0),
            func.coalesce(func.sum(DynamicAgentRunLog.sent_tokens), 0),
            func.count(DynamicAgentRunLog.id),
        )
        .filter(DynamicAgentRunLog.user_id == current_user.id)
        .first()
    )
    saved, raw, sent, calls = int(saved or 0), int(raw or 0), int(sent or 0), int(calls or 0)

    # Recent per-call series for the dashboard's raw-vs-sent comparison chart.
    recent_rows = (
        db.query(
            DynamicAgentRunLog.id,
            DynamicAgentRunLog.tool_name,
            DynamicAgentRunLog.raw_tokens,
            DynamicAgentRunLog.sent_tokens,
            DynamicAgentRunLog.tokens_saved,
        )
        .filter(
            DynamicAgentRunLog.user_id == current_user.id,
            DynamicAgentRunLog.raw_tokens > 0,
        )
        .order_by(DynamicAgentRunLog.id.desc())
        .limit(12)
        .all()
    )
    recent = [
        {
            "label": f"{r.tool_name or '?'} #{r.id}",
            "raw": int(r.raw_tokens or 0),
            "sent": int(r.sent_tokens or 0),
            "saved": int(r.tokens_saved or 0),
        }
        for r in reversed(recent_rows)
    ]

    # Input side — the tools/list payload cost (schemas shipped into context).
    in_stat = (
        db.query(McpToolListStat)
        .filter(McpToolListStat.user_id == current_user.id)
        .first()
    )
    in_raw = int(in_stat.input_raw_tokens or 0) if in_stat else 0
    in_sent = int(in_stat.input_sent_tokens or 0) if in_stat else 0
    in_saved = int(in_stat.input_saved or 0) if in_stat else 0
    tool_count = int(in_stat.tool_count or 0) if in_stat else 0

    return {
        # Output side — per-call MCP response compaction.
        "tokens_saved": saved,
        "raw_tokens": raw,
        "sent_tokens": sent,
        "calls": calls,
        "reduction_pct": round((1 - sent / raw) * 100, 1) if raw else 0.0,
        "recent": recent,
        # Input side — tools/list schema cost.
        "input_tokens": in_sent,
        "input_raw_tokens": in_raw,
        "input_tokens_saved": in_saved,
        "input_reduction_pct": round((1 - in_sent / in_raw) * 100, 1) if in_raw else 0.0,
        "tool_count": tool_count,
    }
