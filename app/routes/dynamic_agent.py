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

import json
import queue
import threading
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.logger import logger
from app.db.database import SessionLocal, get_db
from app.db.models import (
    DynamicAgentRunLog,
    DynamicToolConnection,
    ToolDefinition,
    User,
)
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
    return [
        ConnectionItem(
            id=r.id,
            tool=r.tool_name,
            display_name=r.display_name,
            auth_type=r.auth_type or "API_KEY",
            token_expires_at=r.token_expires_at.isoformat() if r.token_expires_at else None,
            last_used_at=r.last_used_at.isoformat() if r.last_used_at else None,
            created_at=r.created_at.isoformat(),
        )
        for r in rows
    ]


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
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(DynamicAgentRunLog)
        .filter(DynamicAgentRunLog.user_id == current_user.id)
        .order_by(DynamicAgentRunLog.created_at.desc())
        .limit(min(max(limit, 1), 200))
        .all()
    )
    return [
        RunLogItem(
            id=r.id,
            tool=r.tool_name,
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
