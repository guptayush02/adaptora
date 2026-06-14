import json
import queue
import threading
import time
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.models.schema import (
    PromptRequest,
    PromptResponse,
    ConversationCreate,
    ConversationSummary,
    ConversationDetail,
    MessageItem,
    OptimizePromptRequest,
    OptimizePromptResponse,
)
from app.services.middleware_service import MiddlewareService
from app.db.database import get_db
from app.db.models import Conversation, Message
from app.routes.auth import get_current_user
from app.db.models import User
from app.core.logger import logger
from datetime import datetime, timedelta
from typing import Optional, List
from app.core.config import settings as _settings

router = APIRouter(prefix="/api", tags=["LLM Middleware"])

middleware_service = MiddlewareService()


@router.post("/process", response_model=PromptResponse)
async def process_prompt(
    request: PromptRequest, db: Session = Depends(get_db)
) -> PromptResponse:
    """
    Process a prompt through the optimization middleware.

    - **prompt**: The user's input prompt
    - **model**: Optional model choice (openai, anthropic, or ollama)
    - **temperature**: Controls randomness (0-2)
    - **user_id**: Optional user identifier for tracking
    """
    try:
        logger.info(f"Processing prompt request: {request.prompt[:100]}...")
        response = middleware_service.process_prompt(request, db)
        logger.info(f"Prompt processed successfully")
        return response
    except Exception as e:
        logger.error(f"Error processing prompt: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def _serialize_message(m: Message) -> MessageItem:
    return MessageItem(
        id=m.id,
        role=m.role,
        content=m.content,
        model_used=m.model_used,
        complexity_level=m.complexity_level,
        total_tokens=m.total_tokens or 0,
        cache_hit=bool(m.cache_hit),
        processing_time_ms=m.processing_time_ms or 0.0,
        created_at=m.created_at,
    )


@router.get("/conversations", response_model=List[ConversationSummary])
async def list_conversations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return all conversations owned by the current user, newest first."""
    user_id = str(current_user.id)
    convos = (
        db.query(Conversation)
        .filter(Conversation.user_id == user_id)
        .order_by(Conversation.updated_at.desc())
        .all()
    )

    summaries = []
    for c in convos:
        last_msg = (
            db.query(Message)
            .filter(Message.conversation_id == c.id)
            .order_by(Message.created_at.desc(), Message.id.desc())
            .first()
        )
        msg_count = (
            db.query(func.count(Message.id))
            .filter(Message.conversation_id == c.id)
            .scalar()
            or 0
        )
        preview = None
        if last_msg and last_msg.content:
            preview = last_msg.content.strip().splitlines()[0][:120]
        summaries.append(
            ConversationSummary(
                id=c.id,
                title=c.title or "Untitled",
                created_at=c.created_at,
                updated_at=c.updated_at,
                message_count=msg_count,
                last_message_preview=preview,
            )
        )
    return summaries


@router.post("/conversations", response_model=ConversationSummary)
async def create_conversation(
    payload: ConversationCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create an empty conversation for the current user."""
    convo = Conversation(
        user_id=str(current_user.id),
        title=(payload.title or "New conversation").strip()[:120] or "New conversation",
    )
    db.add(convo)
    db.commit()
    db.refresh(convo)
    return ConversationSummary(
        id=convo.id,
        title=convo.title,
        created_at=convo.created_at,
        updated_at=convo.updated_at,
        message_count=0,
        last_message_preview=None,
    )


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return one conversation with its full message thread."""
    convo = (
        db.query(Conversation)
        .filter(
            Conversation.id == conversation_id,
            Conversation.user_id == str(current_user.id),
        )
        .first()
    )
    if not convo:
        raise HTTPException(status_code=404, detail="Conversation not found")

    messages = (
        db.query(Message)
        .filter(Message.conversation_id == convo.id)
        .order_by(Message.created_at.asc(), Message.id.asc())
        .all()
    )
    return ConversationDetail(
        id=convo.id,
        title=convo.title,
        created_at=convo.created_at,
        updated_at=convo.updated_at,
        messages=[_serialize_message(m) for m in messages],
    )


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a conversation (and all its messages) owned by the current user."""
    convo = (
        db.query(Conversation)
        .filter(
            Conversation.id == conversation_id,
            Conversation.user_id == str(current_user.id),
        )
        .first()
    )
    if not convo:
        raise HTTPException(status_code=404, detail="Conversation not found")

    db.query(Message).filter(Message.conversation_id == convo.id).delete()
    db.delete(convo)
    db.commit()
    return {"message": "Conversation deleted"}


@router.post("/optimize", response_model=OptimizePromptResponse)
async def optimize_prompt_only(
    request: OptimizePromptRequest,
) -> OptimizePromptResponse:
    """Preview-mode pre-check pipeline.

    When the user has 'Preview optimized prompt' enabled, this endpoint runs
    EVERY decision step up front — bypass keywords, complexity analysis,
    prompt optimization, and the YES/NO internet-needed classifier — and
    returns the full set of results. The frontend renders all of it; when
    the user clicks Continue, /api/process is called with `skip_optimization`
    plus `pre_complexity_level` / `pre_bypass` / `pre_needs_internet` so the
    streaming pipeline skips every pre-check and runs only the LLM call /
    web search / cache / persist."""
    try:
        # 1. Bypass keywords (fast, regex).
        bypass = middleware_service.prompt_optimizer.check_bypass_keywords(
            request.prompt
        )

        # 2. Complexity analysis (deterministic).
        complexity = middleware_service.complexity_analyzer.analyze(request.prompt)

        # 3. Prompt optimization (LLM-assisted with deterministic fallback).
        result = middleware_service.prompt_optimizer.optimize(request.prompt)

        # 4. Internet-needed classifier — runs on the OPTIMIZED prompt so the
        # decision matches what the streaming step would do downstream.
        try:
            needs_internet = (
                middleware_service.llm_provider._classify_needs_internet(
                    result.optimized_prompt, _settings.OLLAMA_MODEL
                )
            )
        except Exception as e:
            logger.warning(f"Internet classifier failed in /optimize: {e}")
            needs_internet = False

        return OptimizePromptResponse(
            original_prompt=result.original_prompt,
            optimized_prompt=result.optimized_prompt,
            optimization_reason=result.optimization_reason,
            tokens_saved=result.tokens_saved,
            optimization_percentage=result.optimization_percentage,
            complexity_level=complexity.level,
            complexity_score=complexity.score,
            bypass=bypass,
            needs_internet=needs_internet,
        )
    except Exception as e:
        logger.error(f"Error optimizing prompt: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/optimize/stream")
async def optimize_prompt_stream(request: OptimizePromptRequest):
    """Streaming version of /api/optimize.

    Emits one SSE `status` event per pre-check stage — bypass / complexity /
    translating / optimizing / internet-needed — followed by a final `done`
    event whose data payload is the full OptimizePromptResponse. The UI uses
    this to show *what* the optimizer is doing rather than a generic spinner
    (especially important for non-English prompts, where the translate step
    can take several seconds on small models)."""
    events_q: "queue.Queue" = queue.Queue()
    _SENTINEL = object()

    def emit_status(step: str, data: dict):
        events_q.put({"step": step, **(data or {})})

    result_box = {"response": None, "error": None}

    def run_pipeline():
        try:
            # 1. Bypass keywords (fast, regex).
            logger.info("Starting streaming /optimize pipeline")
            logger.info("STEP 1: Bypass keyword check")
            emit_status("optimize_bypass_check", {})
            bypass = middleware_service.prompt_optimizer.check_bypass_keywords(
                request.prompt
            )
            emit_status("optimize_bypass_done", {"bypass": bypass})

            # 2. Complexity analysis (deterministic, fast).
            logger.info("STEP 2: Complexity analysis")
            emit_status("optimize_complexity_analyzing", {})
            complexity = middleware_service.complexity_analyzer.analyze(
                request.prompt
            )
            emit_status(
                "optimize_complexity_done",
                {"level": complexity.level, "score": complexity.score},
            )

            # 3. Prompt optimization (LLM-assisted; fires its own intermediate
            # events via the status_callback — e.g. language_detected,
            # translating, translated, optimizing).
            logger.info("STEP 3: Prompt optimization")
            emit_status("optimize_optimizing", {})
            result = middleware_service.prompt_optimizer.optimize(
                request.prompt, status_callback=emit_status
            )
            emit_status(
                "optimize_optimization_done",
                {"tokens_saved": result.tokens_saved},
            )

            # 4. Internet-needed classifier on the OPTIMIZED prompt.
            logger.info("STEP 4: Checking if internet is needed")
            emit_status("optimize_internet_check", {})
            try:
                needs_internet = (
                    middleware_service.llm_provider._classify_needs_internet(
                        result.optimized_prompt, _settings.OLLAMA_MODEL
                    )
                )
            except Exception as e:
                logger.warning(f"Internet classifier failed in /optimize/stream: {e}")
                needs_internet = False
            emit_status(
                "optimize_internet_done", {"needs_internet": needs_internet}
            )

            payload = OptimizePromptResponse(
                original_prompt=result.original_prompt,
                optimized_prompt=result.optimized_prompt,
                optimization_reason=result.optimization_reason,
                tokens_saved=result.tokens_saved,
                optimization_percentage=result.optimization_percentage,
                complexity_level=complexity.level,
                complexity_score=complexity.score,
                bypass=bypass,
                needs_internet=needs_internet,
            )
            result_box["response"] = (
                payload.model_dump()
                if hasattr(payload, "model_dump")
                else payload.dict()
            )
        except Exception as e:
            logger.error(f"Streaming /optimize pipeline error: {e}")
            result_box["error"] = str(e)
        finally:
            events_q.put(_SENTINEL)

    threading.Thread(target=run_pipeline, daemon=True).start()

    HEARTBEAT_SECONDS = 15

    def event_source():
        # Prime the connection so the client sees bytes immediately.
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
                        f"event: error\ndata: "
                        f"{json.dumps({'error': result_box['error']})}\n\n"
                    )
                else:
                    yield (
                        f"event: done\ndata: "
                        f"{json.dumps(result_box['response'], default=str)}\n\n"
                    )
                break
            yield f"event: status\ndata: {json.dumps(evt)}\n\n"

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/process/stream")
async def process_prompt_stream(request: PromptRequest):
    """Stream pipeline status as Server-Sent Events while processing the prompt.

    Emits one event per pipeline step (cache_check, complexity_analyzing,
    optimizing, routing, thinking, …), then a final `done` event whose data
    payload is the full PromptResponse.

    The frontend uses this to show real-time status (e.g. "Optimizing prompt…",
    "Thinking…") instead of a generic spinner.
    """
    from app.db.database import SessionLocal

    events_q: "queue.Queue" = queue.Queue()
    _SENTINEL = object()

    def emit_status(step: str, data: dict):
        events_q.put({"step": step, **(data or {})})

    result_box = {"response": None, "error": None}

    def run_pipeline():
        # Each worker gets its own DB session so it doesn't share state with
        # the streaming response handler.
        db = SessionLocal()
        try:
            result = middleware_service.process_prompt(
                request, db, status_callback=emit_status
            )
            result_box["response"] = (
                result.model_dump() if hasattr(result, "model_dump") else result.dict()
            )
        except Exception as e:
            logger.error(f"Streaming pipeline error: {e}")
            result_box["error"] = str(e)
        finally:
            db.close()
            events_q.put(_SENTINEL)

    threading.Thread(target=run_pipeline, daemon=True).start()

    HEARTBEAT_SECONDS = 15

    def event_source():
        # Prime the connection so the client sees bytes immediately. Some
        # proxies / load balancers buffer until the first chunk arrives and
        # decide on idle-timeout from there.
        yield ": stream-open\n\n"
        while True:
            try:
                evt = events_q.get(timeout=HEARTBEAT_SECONDS)
            except queue.Empty:
                # No event for HEARTBEAT_SECONDS — emit a comment line so any
                # intermediary (nginx, ALB, CloudFront, …) sees activity and
                # doesn't drop the connection as idle. SSE-spec comments start
                # with `:` and are ignored by the client.
                yield f": keepalive {int(time.time())}\n\n"
                continue
            if evt is _SENTINEL:
                if result_box["error"]:
                    yield f"event: error\ndata: {json.dumps({'error': result_box['error']})}\n\n"
                else:
                    yield f"event: done\ndata: {json.dumps(result_box['response'], default=str)}\n\n"
                break
            yield f"event: status\ndata: {json.dumps(evt)}\n\n"

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # disable nginx response buffering
        },
    )


@router.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "message": "LLM Middleware is running",
    }


@router.post("/cache/clear")
async def clear_cache():
    """Clear all cached responses"""
    try:
        middleware_service.cache_manager.clear()
        return {"message": "Cache cleared successfully"}
    except Exception as e:
        logger.error(f"Error clearing cache: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats/{user_id}")
async def get_user_stats(
    user_id: str,
    db: Session = Depends(get_db),
    range: str = Query("30d", description="Preset range: 7d, 30d, 90d, all"),
    model: Optional[str] = Query(None, description="Filter by model name"),
    complexity: Optional[str] = Query(None, description="Filter by complexity level"),
):
    """Get usage statistics for a user with optional filters."""
    try:
        from app.db.models import TokenUsageRecord

        query = db.query(TokenUsageRecord).filter(
            TokenUsageRecord.user_id == str(user_id)
        )

        now = datetime.utcnow()
        range_map = {"7d": 7, "30d": 30, "90d": 90}
        if range in range_map:
            query = query.filter(
                TokenUsageRecord.timestamp >= now - timedelta(days=range_map[range])
            )

        if model:
            query = query.filter(TokenUsageRecord.model_used == model)

        if complexity:
            query = query.filter(TokenUsageRecord.complexity_level == complexity)

        records = query.order_by(TokenUsageRecord.timestamp.asc()).all()

        if not records:
            return {
                "user_id": user_id,
                "range": range,
                "total_queries": 0,
                "total_tokens": 0,
                "avg_tokens_per_query": 0,
                "cache_hit_rate": 0,
                "tokens_over_time": [],
                "queries_over_time": [],
                "tokens_by_model": [],
                "model_distribution": [],
                "complexity_distribution": [],
                "model_stats": [],
                "available_models": [],
                "available_complexities": [],
                "optimization_over_time": [],
                "optimization_summary": {
                    "original_tokens": 0,
                    "optimized_tokens": 0,
                    "saved_tokens": 0,
                    "savings_percentage": 0,
                },
            }

        total_tokens = sum(r.total_tokens or 0 for r in records)
        total_queries = len(records)
        avg_tokens = total_tokens / total_queries if total_queries else 0
        cache_hits = sum(1 for r in records if r.cache_hit)
        cache_hit_rate = (cache_hits / total_queries * 100) if total_queries else 0

        # Daily aggregations
        tokens_by_day = {}
        queries_by_day = {}
        optimization_by_day = {}
        for r in records:
            day = r.timestamp.date().isoformat() if r.timestamp else "unknown"
            tokens_by_day[day] = tokens_by_day.get(day, 0) + (r.total_tokens or 0)
            queries_by_day[day] = queries_by_day.get(day, 0) + 1

            original = r.original_prompt_tokens or 0
            optimized = r.optimized_prompt_tokens or 0
            # Skip historical rows that pre-date the optimization-tracking
            # columns. They have no real before/after data and would otherwise
            # flatten the chart.
            if original == 0 and optimized == 0:
                continue
            entry = optimization_by_day.setdefault(
                day, {"date": day, "original": 0, "optimized": 0, "saved": 0}
            )
            entry["original"] += original
            entry["optimized"] += optimized
            entry["saved"] += max(0, original - optimized)

        tokens_over_time = [
            {"date": d, "tokens": t} for d, t in sorted(tokens_by_day.items())
        ]
        queries_over_time = [
            {"date": d, "queries": q} for d, q in sorted(queries_by_day.items())
        ]
        optimization_over_time = [
            optimization_by_day[d] for d in sorted(optimization_by_day.keys())
        ]

        total_original = sum(e["original"] for e in optimization_over_time)
        total_optimized = sum(e["optimized"] for e in optimization_over_time)
        total_saved = max(0, total_original - total_optimized)
        savings_percentage = (
            (total_saved / total_original * 100) if total_original > 0 else 0
        )

        # Model aggregations
        model_totals = {}
        for r in records:
            key = r.model_used or "unknown"
            entry = model_totals.setdefault(
                key,
                {
                    "model": key,
                    "queries": 0,
                    "tokens": 0,
                    "cache_hits": 0,
                },
            )
            entry["queries"] += 1
            entry["tokens"] += r.total_tokens or 0
            entry["cache_hits"] += 1 if r.cache_hit else 0

        tokens_by_model = [
            {"model": m["model"], "tokens": m["tokens"]} for m in model_totals.values()
        ]
        model_distribution = [
            {"name": m["model"], "queries": m["queries"]} for m in model_totals.values()
        ]
        model_stats = [
            {
                "model": m["model"],
                "query_count": m["queries"],
                "total_tokens": m["tokens"],
                "avg_tokens": (m["tokens"] / m["queries"]) if m["queries"] else 0,
                "cache_hits": m["cache_hits"],
            }
            for m in model_totals.values()
        ]

        # Complexity distribution
        complexity_counts = {}
        for r in records:
            level = r.complexity_level or "unknown"
            complexity_counts[level] = complexity_counts.get(level, 0) + 1
        complexity_distribution = [
            {"name": k, "queries": v} for k, v in complexity_counts.items()
        ]

        # Available filter options pulled from all-time records (so filters don't
        # disappear when the user narrows the range)
        all_records = (
            db.query(TokenUsageRecord)
            .filter(TokenUsageRecord.user_id == str(user_id))
            .all()
        )
        available_models = sorted({r.model_used for r in all_records if r.model_used})
        available_complexities = sorted(
            {r.complexity_level for r in all_records if r.complexity_level}
        )

        return {
            "user_id": user_id,
            "range": range,
            "total_queries": total_queries,
            "total_tokens": total_tokens,
            "avg_tokens_per_query": avg_tokens,
            "cache_hit_rate": cache_hit_rate,
            "tokens_over_time": tokens_over_time,
            "queries_over_time": queries_over_time,
            "tokens_by_model": tokens_by_model,
            "model_distribution": model_distribution,
            "complexity_distribution": complexity_distribution,
            "model_stats": model_stats,
            "available_models": available_models,
            "available_complexities": available_complexities,
            "optimization_over_time": optimization_over_time,
            "optimization_summary": {
                "original_tokens": total_original,
                "optimized_tokens": total_optimized,
                "saved_tokens": total_saved,
                "savings_percentage": savings_percentage,
            },
        }
    except Exception as e:
        logger.error(f"Error getting user stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))
