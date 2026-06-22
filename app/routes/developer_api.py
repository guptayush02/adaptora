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
import uuid
from datetime import datetime
from typing import Any, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.logger import logger
from app.core.security import hash_api_key
from app.db.database import get_db
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

    # Tag the just-written run log with the originating key. Post-update keeps
    # the deep service signature untouched. Best-effort: never fail the call.
    log_id = result.get("log_id")
    if log_id:
        try:
            (
                db.query(DynamicAgentRunLog)
                .filter(DynamicAgentRunLog.id == log_id)
                .update({DynamicAgentRunLog.api_key_id: key.id})
            )
            db.commit()
        except Exception as exc:  # pragma: no cover — tagging is non-critical
            logger.warning(f"failed to tag run {log_id} with key {key.id}: {exc}")
            db.rollback()

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
