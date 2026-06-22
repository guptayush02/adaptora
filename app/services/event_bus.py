"""Cross-process pub/sub for live agent step traces.

Each step a run emits (``identifying_tool`` → ``looking_up_docs`` →
``planning_action`` → ``executing`` → ``done`` …) is published to a per-user
Redis channel so the dashboard's live Logs stream can render it in real time —
even though the run executes on a different connection, and usually a different
process (the public ``/api/v1`` worker or the standalone MCP server), than the
one serving the dashboard.

Redis-backed on purpose: an in-process asyncio bus can't reach across
processes. Degrades gracefully — if Redis is unavailable, publish/subscribe
become no-ops and the dashboard simply falls back to its polling refresh.
"""

from __future__ import annotations

import json
import threading
from typing import Any, Dict, Optional

import redis

from app.core.config import settings
from app.core.logger import logger

_CHANNEL = "agent:steps:{user_id}"

_client: Optional[redis.Redis] = None
_client_lock = threading.Lock()
_disabled = False


def _get_client() -> Optional[redis.Redis]:
    """Lazily build a shared Redis client. Caches the connection; on first
    failure marks the bus disabled so we don't retry-storm on every step."""
    global _client, _disabled
    if _disabled:
        return None
    if _client is not None:
        return _client
    with _client_lock:
        if _client is not None:
            return _client
        try:
            c = redis.from_url(settings.REDIS_URL)
            c.ping()
            _client = c
            logger.info("event_bus: connected to Redis for live step streaming")
        except Exception as e:  # pragma: no cover - infra dependent
            logger.warning(
                f"event_bus: Redis unavailable ({e}); live step streaming "
                f"disabled (dashboard falls back to polling)"
            )
            _disabled = True
            return None
    return _client


def channel_for(user_id: int) -> str:
    return _CHANNEL.format(user_id=user_id)


def publish_step(user_id: int, payload: Dict[str, Any]) -> None:
    """Publish one step event to the user's channel. Best-effort: never let a
    telemetry failure break the actual run."""
    client = _get_client()
    if not client:
        return
    try:
        client.publish(channel_for(user_id), json.dumps(payload, default=str))
    except Exception as e:  # pragma: no cover - infra dependent
        logger.debug(f"event_bus publish failed: {e}")


def make_subscription(user_id: int):
    """Return an active pubsub subscribed to the user's channel, or None if
    Redis is unavailable. Caller owns closing it."""
    client = _get_client()
    if not client:
        return None
    pubsub = client.pubsub()
    pubsub.subscribe(channel_for(user_id))
    return pubsub
