"""Public REST API for external developers.

Mounted under ``/api/v1``. Unlike the dashboard routes (JWT) and the MCP
server (``MCP_USER_EMAIL`` env), these endpoints authenticate with a
developer secret key minted on the dashboard:

    Authorization: Bearer adp_live_…

The key resolves to its owning user, so every action runs against that
user's saved tool connections — exactly as the web UI would. Each run is
logged and tagged with the originating key so the dashboard can attribute
activity per project (key) and per tool.
"""

from __future__ import annotations

import asyncio
import json
import queue
import threading
import time
import uuid
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.logger import logger
from app.core.security import hash_api_key
from app.db.database import SessionLocal, get_db
from app.db.models import DeveloperApiKey, DynamicAgentRunLog, User
from app.services.dynamic_agent_service import dynamic_agent_service
from app.services.event_bus import publish_step

router = APIRouter(prefix="/api/v1", tags=["Public API"])

_bearer = HTTPBearer(auto_error=True)


def get_user_from_api_key(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    db: Session = Depends(get_db),
) -> Tuple[User, DeveloperApiKey]:
    """Resolve a developer secret key to its owning user.

    Hashes the presented bearer token and looks up an active key by hash.
    Bumps ``last_used_at`` on success. 401 on missing / invalid / revoked."""
    raw_key = (credentials.credentials or "").strip()
    if not raw_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing API key"
        )

    key = (
        db.query(DeveloperApiKey)
        .filter(
            DeveloperApiKey.key_hash == hash_api_key(raw_key),
            DeveloperApiKey.is_active == True,  # noqa: E712
        )
        .first()
    )
    if not key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or revoked API key",
        )

    user = db.query(User).filter(User.id == key.user_id).first()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key owner is inactive",
        )

    key.last_used_at = datetime.utcnow()
    db.commit()
    return user, key


def _tag_run_with_key(db: Session, log_id: Optional[int], key_id: int) -> None:
    """Tag a just-written run log with the originating key for per-project
    attribution. Post-update keeps the deep service signature untouched.
    Best-effort: tagging never fails the actual call."""
    if not log_id:
        return
    try:
        (
            db.query(DynamicAgentRunLog)
            .filter(DynamicAgentRunLog.id == log_id)
            .update({DynamicAgentRunLog.api_key_id: key_id})
        )
        db.commit()
    except Exception as exc:  # pragma: no cover — tagging is non-critical
        logger.warning(f"failed to tag run {log_id} with key {key_id}: {exc}")
        db.rollback()


class RunRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    language: str = Field("en", description="'en' or 'hinglish'")


class RunResponse(BaseModel):
    log_id: int
    status: str  # success | needs_credentials | needs_tool_setup | error
    tool: Optional[str] = None
    summary: Optional[str] = None
    final_answer: Optional[str] = None
    http_status: Optional[int] = None
    response: Optional[Any] = None
    error: Optional[str] = None
    duration_ms: float


@router.post("/run", response_model=RunResponse)
async def run(
    payload: RunRequest,
    auth: Tuple[User, DeveloperApiKey] = Depends(get_user_from_api_key),
    db: Session = Depends(get_db),
):
    """Run one agent turn on behalf of the key's owner.

    Same pipeline as the dashboard's ``/api/dynamic-agent/turn`` — identify
    tool → load docs → check connection → plan → execute — scoped to the
    key owner's saved connections. The resulting run log is tagged with the
    key id for per-project attribution."""
    user, key = auth

    # Correlation id so the dashboard can group this run's step events.
    run_uid = uuid.uuid4().hex

    def _emit(step: str, data: Optional[dict] = None) -> None:
        """Forward each pipeline step to the user's live channel so the
        dashboard renders the execution as it happens. Best-effort."""
        publish_step(
            user.id,
            {
                "run_uid": run_uid,
                "source": "api",
                "key_label": key.label,
                "step": step,
                "data": data or {},
            },
        )

    _emit("received", {"prompt": payload.prompt})
    try:
        # Run in a worker thread so the (blocking) pipeline doesn't stall the
        # event loop — keeping the dashboard's live SSE responsive meanwhile.
        result = await asyncio.to_thread(
            dynamic_agent_service.run_turn,
            db,
            user_id=user.id,
            prompt=payload.prompt,
            language=payload.language,
            status_callback=_emit,
        )
    except Exception as exc:
        logger.exception("public /run turn failed")
        _emit("error", {"error": str(exc)})
        raise HTTPException(status_code=500, detail=f"Agent error: {exc}")

    _tag_run_with_key(db, result.get("log_id"), key.id)

    # Final event: lets the dashboard mark the run complete and pull the
    # finished row (with its full trace) into the table.
    _emit(
        "done",
        {
            "log_id": result.get("log_id"),
            "status": result.get("status"),
            "tool": result.get("tool"),
        },
    )

    return RunResponse(
        log_id=result.get("log_id"),
        status=result.get("status"),
        tool=result.get("tool"),
        summary=result.get("summary"),
        final_answer=result.get("final_answer"),
        http_status=result.get("http_status"),
        response=result.get("response"),
        error=result.get("error"),
        duration_ms=result.get("duration_ms", 0.0),
    )


@router.post("/run/stream")
async def run_stream(
    payload: RunRequest,
    auth: Tuple[User, DeveloperApiKey] = Depends(get_user_from_api_key),
):
    """Server-Sent Events variant of ``/run``.

    Same pipeline as ``/run``, but instead of waiting for the final result the
    response is a ``text/event-stream`` that emits one ``step`` event per
    pipeline stage (``received`` → ``identifying_tool`` → ``tool_identified``
    → ``looking_up_docs`` → ``checking_connection`` → ``planning_action`` →
    ``executing`` → ``summarizing``) as it happens, then a final ``done`` event
    whose data is the full ``RunResponse`` payload (or an ``error`` event).

    This lets developers render the agent's progress live in their own UI —
    e.g. with the browser ``EventSource`` API or any SSE client:

        const es = new EventSource(url, { headers: { Authorization: … } });
        es.addEventListener('step', e => render(JSON.parse(e.data)));
        es.addEventListener('done', e => finish(JSON.parse(e.data)));

    Per-step bytes (plus a keepalive comment every 15 s) also keep proxies
    (ALB / nginx / CloudFront) from killing the connection on a slow run.
    """
    user, key = auth
    user_id = user.id
    key_id = key.id
    key_label = key.label
    prompt = payload.prompt
    language = payload.language

    run_uid = uuid.uuid4().hex
    events_q: "queue.Queue" = queue.Queue()
    _SENTINEL = object()

    def emit_status(step: str, data: Optional[dict] = None) -> None:
        """Fan a pipeline step out to both the developer's own SSE stream
        (local queue) and the dashboard's live channel (Redis). Best-effort."""
        data = data or {}
        events_q.put({"step": step, "run_uid": run_uid, "data": data})
        publish_step(
            user_id,
            {
                "run_uid": run_uid,
                "source": "api",
                "key_label": key_label,
                "step": step,
                "data": data,
            },
        )

    result_box: Dict[str, Any] = {"response": None, "error": None}

    def run_pipeline() -> None:
        # The request-scoped Session dies when this function returns, but the
        # worker outlives it — so mint a fresh session here (mirrors the
        # dashboard's /turn/stream pattern).
        worker_db = SessionLocal()
        try:
            emit_status("received", {"prompt": prompt})
            result = dynamic_agent_service.run_turn(
                worker_db,
                user_id=user_id,
                prompt=prompt,
                language=language,
                status_callback=emit_status,
            )
            _tag_run_with_key(worker_db, result.get("log_id"), key_id)
            result_box["response"] = result
            # Terminal step so the dashboard's live row marks the run complete
            # and retires it — mirrors the non-streaming /run. Without this the
            # live row stays stuck on the last pipeline step forever.
            emit_status(
                "done",
                {
                    "log_id": result.get("log_id"),
                    "status": result.get("status"),
                    "tool": result.get("tool"),
                },
            )
        except Exception as exc:
            logger.exception("public /run/stream pipeline failed")
            result_box["error"] = str(exc)
            emit_status("error", {"error": str(exc)})
        finally:
            worker_db.close()
            events_q.put(_SENTINEL)

    threading.Thread(target=run_pipeline, daemon=True).start()

    HEARTBEAT_SECONDS = 15

    def event_source():
        # Prime the connection so proxies flush bytes immediately.
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
                    r = result_box["response"] or {}
                    final = RunResponse(
                        log_id=r.get("log_id"),
                        status=r.get("status"),
                        tool=r.get("tool"),
                        summary=r.get("summary"),
                        final_answer=r.get("final_answer"),
                        http_status=r.get("http_status"),
                        response=r.get("response"),
                        error=r.get("error"),
                        duration_ms=r.get("duration_ms", 0.0),
                    )
                    yield (
                        f"event: done\n"
                        f"data: {json.dumps(final.model_dump(), default=str)}\n\n"
                    )
                break
            yield f"event: step\ndata: {json.dumps(evt, default=str)}\n\n"

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
