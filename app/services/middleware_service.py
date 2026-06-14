import hashlib
import time
from typing import Optional, Dict
from app.core.logger import logger
from app.models.schema import PromptRequest, PromptResponse
from app.cache.cache_manager import CacheManager
from app.services.complexity_analyzer import ComplexityAnalyzer
from app.services.prompt_optimizer import PromptOptimizer
from app.services.llm_provider import LLMProvider
from app.db.models import UserAPIKey, TokenUsageRecord, CacheRecord, Conversation, Message
from app.core.security import decrypt_api_key
from app.core.tokens import count_tokens
from sqlalchemy.orm import Session
from datetime import datetime, timedelta


class MiddlewareService:
    """Main middleware service orchestrating the flow"""

    def __init__(self):
        """Initialize middleware service"""
        self.cache_manager = CacheManager()
        self.complexity_analyzer = ComplexityAnalyzer()
        self.prompt_optimizer = PromptOptimizer()
        self.llm_provider = LLMProvider()

    def _get_user_api_key(self, user_id: Optional[str], provider: str, db: Session) -> Optional[str]:
        """Retrieve a user's API key for a provider."""
        if not user_id:
            return None

        try:
            user_api_key = (
                db.query(UserAPIKey)
                .filter(
                    UserAPIKey.user_id == int(user_id) if str(user_id).isdigit() else user_id,
                    UserAPIKey.provider == provider,
                )
                .first()
            )
            return decrypt_api_key(user_api_key.api_key) if user_api_key else None
        except Exception as e:
            logger.error(f"Error loading user API key for provider {provider}: {e}")
            return None

    def _list_user_advanced_keys(self, user_id: Optional[str], db: Session):
        """Return user's saved non-ollama (provider, model_name) pairs."""
        if not user_id:
            return []
        try:
            user_pk = int(user_id) if str(user_id).isdigit() else user_id
            keys = (
                db.query(UserAPIKey)
                .filter(UserAPIKey.user_id == user_pk, UserAPIKey.provider != "ollama")
                .all()
            )
            return [(k.provider, k.model_name) for k in keys]
        except Exception as e:
            logger.error(f"Error listing user's advanced keys: {e}")
            return []

    def _auto_select_advanced_model(
        self, prompt_text: str, candidates: list
    ) -> Optional[tuple]:
        """Ask Ollama to pick the most suitable model from the user's saved advanced
        provider/model pairs for a difficult prompt. Falls back to the first candidate
        on any failure."""
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]

        options = [f"{provider}:{model}" for provider, model in candidates]
        selection_prompt = (
            "You are a routing assistant. Choose exactly one model identifier from "
            "the list below that is best suited to answer the user's difficult prompt.\n"
            "Respond with ONLY the chosen identifier (format provider:model), no extra text.\n\n"
            f"Available models: {options}\n\n"
            f"User prompt:\n{prompt_text}"
        )

        try:
            choice, _ = self.llm_provider.query_ollama(selection_prompt, temperature=0.0)
            choice = (choice or "").strip().splitlines()[0].strip().strip("`'\"")
            for provider, model in candidates:
                ident = f"{provider}:{model}"
                if ident.lower() == choice.lower() or choice.lower().endswith(model.lower()):
                    logger.info(f"Auto-selected advanced model via Ollama: {ident}")
                    return (provider, model)
            logger.warning(
                f"Ollama returned unrecognized auto-selection '{choice}', falling back to first candidate"
            )
        except Exception as e:
            logger.error(f"Auto-selection via Ollama failed: {e}")

        return candidates[0]

    def _resolve_conversation(
        self, request: PromptRequest, db: Session
    ) -> Optional[Conversation]:
        """Load an existing conversation (when conversation_id is provided) or
        create a fresh one for this user. Returns None if user_id is missing,
        which means the caller is making a one-off (anonymous) request."""
        user_id = str(request.user_id).strip() if request.user_id is not None else ""
        if not user_id or user_id.lower() in {"string", "null", "none"}:
            return None

        if request.conversation_id:
            convo = (
                db.query(Conversation)
                .filter(
                    Conversation.id == request.conversation_id,
                    Conversation.user_id == user_id,
                )
                .first()
            )
            if convo:
                return convo
            logger.warning(
                f"conversation_id={request.conversation_id} not found for user {user_id}; creating a new one"
            )

        # Title from the first ~60 characters of the prompt
        title = request.prompt.strip().splitlines()[0][:60] or "New conversation"
        convo = Conversation(user_id=user_id, title=title)
        db.add(convo)
        db.commit()
        db.refresh(convo)
        logger.info(f"Created conversation id={convo.id} for user {user_id}")
        return convo

    def _save_message(
        self,
        db: Session,
        conversation: Conversation,
        role: str,
        content: str,
        *,
        model_used: Optional[str] = None,
        complexity_level: Optional[str] = None,
        tokens: Optional[Dict[str, int]] = None,
        cache_hit: bool = False,
        processing_time_ms: float = 0.0,
    ) -> Message:
        message = Message(
            conversation_id=conversation.id,
            role=role,
            content=content,
            model_used=model_used,
            complexity_level=complexity_level,
            prompt_tokens=(tokens or {}).get("prompt_tokens", 0),
            response_tokens=(tokens or {}).get("response_tokens", 0),
            total_tokens=(tokens or {}).get("total_tokens", 0),
            cache_hit=cache_hit,
            processing_time_ms=processing_time_ms,
        )
        db.add(message)
        conversation.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(message)
        return message

    def _build_prompt_with_history(
        self, db: Session, conversation: Optional[Conversation], latest_prompt: str
    ) -> str:
        """When there is prior chat history, prepend a transcript so the LLM has
        context. Used by the advanced-model path (OpenAI/Anthropic) which still
        accepts a single string. The Ollama path uses /api/chat with structured
        messages — see `_build_history_messages`."""
        if conversation is None:
            return latest_prompt

        prior = (
            db.query(Message)
            .filter(Message.conversation_id == conversation.id)
            .order_by(Message.created_at.asc(), Message.id.asc())
            .all()
        )
        # The current turn's user message was already persisted by `process_prompt`
        # before this call. Drop trailing user messages so the latest question
        # doesn't appear twice (once with the original text and once as the
        # optimized rewrite).
        while prior and prior[-1].role == "user":
            prior = prior[:-1]
        if not prior:
            return latest_prompt

        lines = []
        # Keep the last ~12 turns to avoid context bloat
        for msg in prior[-12:]:
            speaker = "User" if msg.role == "user" else "Assistant"
            lines.append(f"{speaker}: {msg.content}")
        lines.append(f"User: {latest_prompt}")
        lines.append("Assistant:")
        return "\n\n".join(lines)

    def _build_history_messages(
        self, db: Session, conversation: Optional[Conversation]
    ) -> list:
        """Return prior chat as a list of {role, content} dicts ready to send
        to Ollama's /api/chat endpoint. EXCLUDES the current user turn (which
        was just saved). Returns [] for a one-shot request — callers should
        treat that as "no history"."""
        if conversation is None:
            return []

        prior = (
            db.query(Message)
            .filter(Message.conversation_id == conversation.id)
            .order_by(Message.created_at.asc(), Message.id.asc())
            .all()
        )
        while prior and prior[-1].role == "user":
            prior = prior[:-1]
        # Keep the last ~12 turns to avoid context bloat
        return [
            {
                "role": "user" if m.role == "user" else "assistant",
                "content": m.content or "",
            }
            for m in prior[-12:]
        ]

    def process_prompt(
        self,
        request: PromptRequest,
        db: Session,
        status_callback=None,
    ) -> PromptResponse:
        """Process user prompt through middleware pipeline.

        status_callback(step: str, data: dict) is invoked at each pipeline
        stage. Streaming endpoints pass a callback that forwards events to the
        client as SSE; the non-streaming endpoint passes None.
        """
        start_time = time.time()

        def emit(step: str, **data):
            if status_callback:
                try:
                    status_callback(step, data)
                except Exception as e:  # don't break the pipeline on emit errors
                    logger.warning(f"status_callback for step={step!r} raised: {e}")

        conversation = self._resolve_conversation(request, db)
        # Persist the user's message immediately so the UI shows it even if the
        # LLM fails downstream.
        user_message = None
        if conversation is not None:
            user_message = self._save_message(
                db, conversation, role="user", content=request.prompt
            )
            # Emit the conversation_id as soon as we have it so the frontend
            # can recover by polling /api/conversations/{id} if the SSE stream
            # is killed by a proxy before the `done` event arrives.
            emit(
                "conversation_started",
                conversation_id=conversation.id,
                user_message_id=user_message.id,
            )

        # Generate cache key — include conversation id when present so multi-turn
        # threads don't collide with single-shot prompts.
        model = request.model or "ollama"
        cache_seed = request.prompt
        if conversation is not None:
            cache_seed = f"{conversation.id}:{request.prompt}"
        cache_key = self.cache_manager.generate_cache_key(cache_seed, model)

        # Step 1: Check cache
        logger.info("Step 1: Checking cache...")
        emit("cache_check")
        cached = self.cache_manager.get(cache_key)
        if cached:
            logger.info("Cache hit! Using cached response")
            emit("cache_hit", model=cached.get("model_used"))
            processing_time = (time.time() - start_time) * 1000
            assistant_message = None
            if conversation is not None:
                assistant_message = self._save_message(
                    db,
                    conversation,
                    role="assistant",
                    content=cached["response"],
                    model_used=cached["model_used"],
                    complexity_level=cached.get("complexity_level", "unknown"),
                    tokens=cached.get("tokens_used"),
                    cache_hit=True,
                    processing_time_ms=processing_time,
                )
            return PromptResponse(
                response=cached["response"],
                model_used=cached["model_used"],
                tokens_used=cached["tokens_used"],
                cache_hit=True,
                complexity_level=cached.get("complexity_level", "unknown"),
                processing_time_ms=processing_time,
                conversation_id=conversation.id if conversation else None,
                user_message_id=user_message.id if user_message else None,
                assistant_message_id=assistant_message.id if assistant_message else None,
            )

        emit("cache_miss")

        # "Preview mode" Continue-click path: /api/optimize already ran every
        # pre-check (bypass / complexity / optimization / internet-needed) and
        # returned the results to the UI. The user reviewed (and possibly
        # edited) the optimized prompt and clicked Continue, so the request
        # carries the precomputed decisions back. Re-running them here would
        # be wasted Ollama cycles, so we replay the decisions instead.
        preview_continue = bool(
            request.skip_optimization
            and request.pre_complexity_level is not None
        )

        # Sensible defaults so the rest of the function works regardless of
        # which branch runs below.
        optimized_prompt = request.prompt
        final_prompt = request.prompt
        complexity = None  # only computed when not bypassing
        optimized = None

        if preview_continue:
            logger.info(
                "Preview-continue path: skipping bypass / complexity / "
                "optimize / internet-classifier (precomputed by /api/optimize). "
                f"pre_complexity={request.pre_complexity_level}, "
                f"pre_bypass={request.pre_bypass}, "
                f"pre_needs_internet={request.pre_needs_internet}"
            )
            emit("preview_continue")
            bypass = bool(request.pre_bypass)
            # Re-hydrate a complexity-like shim so the downstream routing
            # logic (`if bypass or complexity.level == 'difficult'`) works
            # without any further branching.
            class _PrecomputedComplexity:
                def __init__(self, level: str):
                    self.level = level
                    self.score = 0.0
            complexity = _PrecomputedComplexity(request.pre_complexity_level)
            optimized_prompt = request.prompt  # already optimized + possibly edited
            final_prompt = self._build_prompt_with_history(
                db, conversation, optimized_prompt
            )
        else:
            # Normal (non-preview) flow — run every pre-check inline.
            # Step 2: Check bypass keywords
            logger.info("Step 2: Checking for bypass keywords...")
            emit("bypass_check")
            bypass = self.prompt_optimizer.check_bypass_keywords(request.prompt)

            if bypass:
                logger.info(
                    "Bypass keyword found — skipping complexity + optimization"
                )
                emit("bypass_hit")
            else:
                emit("complexity_analyzing")
                # Step 3: Analyze complexity (on the latest user message only)
                logger.info("Step 3: Analyzing prompt complexity...")
                complexity = self.complexity_analyzer.analyze(request.prompt)
                logger.info(
                    f"Complexity analysis: {complexity.level} "
                    f"(score: {complexity.score})"
                )
                emit(
                    "complexity_done",
                    level=complexity.level,
                    score=complexity.score,
                )

                # Step 4: Optimize prompt. If skip_optimization=True (preview
                # flow without precomputed routing), treat the incoming prompt
                # as the optimized version.
                if request.skip_optimization:
                    logger.info(
                        "Step 4: skip_optimization=True — using prompt as-is"
                    )
                    emit("optimization_skipped")
                    optimized_prompt = request.prompt
                else:
                    logger.info("Step 4: Optimizing prompt with Ollama...")
                    emit("optimizing")
                    optimized = self.prompt_optimizer.optimize(request.prompt)
                    optimized_prompt = (
                        optimized.optimized_prompt if optimized else request.prompt
                    )
                    emit(
                        "optimized",
                        original_tokens=count_tokens(request.prompt),
                        optimized_tokens=count_tokens(optimized_prompt),
                        tokens_saved=(
                            getattr(optimized, "tokens_saved", 0)
                            if optimized else 0
                        ),
                    )
                final_prompt = self._build_prompt_with_history(
                    db, conversation, optimized_prompt
                )

        # Once optimization has produced a (possibly shorter) version of the
        # prompt, propagate it to EVERY downstream operation — including the
        # chat history that future turns will be built from. The user message
        # was originally saved with the raw text so the UI could echo it
        # immediately; now that we have the optimized version, overwrite it
        # so the next turn's `_build_history_messages` carries the optimized
        # form forward.
        if (
            user_message is not None
            and optimized_prompt
            and optimized_prompt != user_message.content
        ):
            user_message.content = optimized_prompt
            db.commit()
            db.refresh(user_message)
            logger.info(
                f"Persisted optimized prompt to message id={user_message.id} "
                f"({count_tokens(request.prompt)} → {count_tokens(optimized_prompt)} tokens)"
            )

        logger.info(
            f"Final prompt tokens (with history): {count_tokens(final_prompt)}"
        )

        # "Original" for the dashboard chart = the raw text the user TYPED,
        # not whatever was forwarded to /api/process. In preview-continue
        # mode the frontend has already swapped `request.prompt` with the
        # optimized translation (so the LLM call uses the cleaner text),
        # which would make this comparison meaningless. The frontend
        # passes the user's original text in `pre_original_prompt` so we
        # can chart the real before/after.
        accounting_original = (
            request.pre_original_prompt
            if (request.pre_original_prompt and request.pre_original_prompt.strip())
            else request.prompt
        )
        original_prompt_tokens = count_tokens(accounting_original)
        optimized_prompt_tokens = count_tokens(optimized_prompt)
        logger.info(
            f"Token accounting: original={original_prompt_tokens} tokens "
            f"({len(accounting_original)} chars), "
            f"optimized={optimized_prompt_tokens} tokens "
            f"({len(optimized_prompt)} chars)"
        )

        if bypass or complexity.level == "difficult":
            reason = (
                "bypass keyword matched"
                if bypass
                else f"complexity={complexity.level} (score={complexity.score:.1f})"
            )
            level = "advanced" if bypass else complexity.level
            logger.info(f"ROUTING → advanced model ({reason})")
            emit("routing", target="advanced", reason=reason)

            # When the user selected "auto", let the local model pick which of
            # their saved providers is best for this prompt BEFORE we route.
            # This makes the selection visible as a stream event and lets the
            # UI show the chosen model (e.g. GPT-4) up front instead of just
            # "Thinking…".
            preselected = None
            raw_model = (request.model or "").strip().lower()
            if not raw_model or raw_model == "auto":
                candidates = self._list_user_advanced_keys(request.user_id, db)
                if candidates:
                    emit(
                        "selecting_advanced_model",
                        candidates=[f"{p}:{m}" for p, m in candidates],
                    )
                    preselected = self._auto_select_advanced_model(
                        final_prompt, candidates
                    )
                    if preselected:
                        prov, mdl = preselected
                        emit(
                            "selected_advanced_model",
                            provider=prov,
                            model=mdl,
                        )
                else:
                    logger.warning(
                        "Auto-routing requested but user has no advanced API keys"
                    )

            emit(
                "thinking",
                target="advanced",
                model=(preselected[1] if preselected else None),
                provider=(preselected[0] if preselected else None),
            )
            return self._query_advanced_model(
                request,
                start_time,
                cache_key,
                db,
                level,
                final_prompt,
                conversation=conversation,
                user_message=user_message,
                original_prompt_tokens=original_prompt_tokens,
                optimized_prompt_tokens=optimized_prompt_tokens,
                status_callback=status_callback,
                preselected_advanced=preselected,
            )

        # Easy / medium → Ollama
        logger.info(
            f"ROUTING → ollama (complexity={complexity.level}, score={complexity.score:.1f})"
        )
        emit("routing", target="ollama", complexity=complexity.level)
        emit("thinking", target="ollama")
        # For the Ollama path we send STRUCTURED chat messages (system + prior
        # turns + current user message) so /api/chat applies the model's
        # native chat template. Transcript-style /api/generate prompts caused
        # small models (Mistral 7B etc.) to keep continuing the prior topic
        # — e.g. answering "tell me about iPhone 17" with Akbar content.
        history_messages = self._build_history_messages(db, conversation)
        response, tokens = self.llm_provider.query_ollama(
            optimized_prompt,
            temperature=request.temperature,
            user_query=optimized_prompt,
            history=history_messages or None,
            # Pass the SSE status callback through so the provider can emit
            # "searching_internet", "search_complete", "summarizing_results"
            # for the UI when the web-fallback path runs.
            status_callback=status_callback,
            # When /api/optimize already ran the YES/NO classifier, skip the
            # second round-trip and use that decision.
            needs_internet_override=request.pre_needs_internet,
        )

        processing_time = (time.time() - start_time) * 1000

        # Cache (only for single-turn — multi-turn responses depend on history)
        if conversation is None:
            cache_data = {
                "response": response,
                "model_used": "ollama",
                "tokens_used": tokens,
                "complexity_level": complexity.level,
            }
            self.cache_manager.set(cache_key, cache_data)

        self._record_token_usage(
            request,
            response,
            tokens,
            "ollama",
            complexity.level,
            db,
            original_prompt_tokens=original_prompt_tokens,
            optimized_prompt_tokens=optimized_prompt_tokens,
        )

        assistant_message = None
        if conversation is not None:
            assistant_message = self._save_message(
                db,
                conversation,
                role="assistant",
                content=response,
                model_used="ollama",
                complexity_level=complexity.level,
                tokens=tokens,
                cache_hit=False,
                processing_time_ms=processing_time,
            )

        emit("done", model="ollama", total_tokens=tokens.get("total_tokens", 0))

        return PromptResponse(
            response=response,
            model_used="ollama",
            tokens_used=tokens,
            cache_hit=False,
            complexity_level=complexity.level,
            processing_time_ms=processing_time,
            prompt_optimization=(
                f"Saved {optimized.tokens_saved} tokens ({optimized.optimization_percentage:.1f}%)"
                if optimized and optimized.tokens_saved > 0
                else None
            ),
            conversation_id=conversation.id if conversation else None,
            user_message_id=user_message.id if user_message else None,
            assistant_message_id=assistant_message.id if assistant_message else None,
        )

    def _query_advanced_model(
        self,
        request: PromptRequest,
        start_time: float,
        cache_key: str,
        db: Session,
        complexity_level: str,
        prompt_text: str,
        conversation: Optional[Conversation] = None,
        user_message: Optional[Message] = None,
        original_prompt_tokens: int = 0,
        optimized_prompt_tokens: int = 0,
        status_callback=None,
        preselected_advanced: Optional[tuple] = None,
    ) -> PromptResponse:
        """Route to advanced LLM model"""
        raw_model = (request.model or "").strip()

        provider = "ollama"
        model = raw_model or "gpt-4"
        api_key = None

        if preselected_advanced:
            # process_prompt already asked the local model which provider/model
            # to use and emitted a status event. Reuse that choice instead of
            # re-running auto-selection.
            provider, model = preselected_advanced
            api_key = self._get_user_api_key(request.user_id, provider, db)
        elif not raw_model or raw_model.lower() == "auto":
            # Auto-routing: ask Ollama to pick the best model from the user's saved providers
            candidates = self._list_user_advanced_keys(request.user_id, db)
            chosen = self._auto_select_advanced_model(prompt_text, candidates)
            if chosen:
                provider, model = chosen
                api_key = self._get_user_api_key(request.user_id, provider, db)
            else:
                logger.warning(
                    "Auto-routing requested but user has no advanced API keys; using Ollama"
                )
        elif ":" in raw_model:
            # Explicit provider:model from the dashboard dropdown
            provider, _, model = raw_model.partition(":")
            provider = provider.lower()
            api_key = self._get_user_api_key(request.user_id, provider, db)
        elif raw_model.lower() == "openai" or raw_model.startswith("gpt"):
            provider = "openai"
            api_key = self._get_user_api_key(request.user_id, "openai", db)
        elif raw_model.lower() == "anthropic" or raw_model.startswith("claude"):
            provider = "anthropic"
            api_key = self._get_user_api_key(request.user_id, "anthropic", db)

        try:
            if provider in ["openai", "anthropic"] and not api_key:
                logger.warning(
                    f"No user API key found for provider {provider}, falling back to global configuration"
                )

            missing_global_key = (
                provider == "openai" and not self.llm_provider.openai_key
            ) or (
                provider == "anthropic" and not self.llm_provider.anthropic_key
            )

            if missing_global_key and provider != "ollama":
                logger.warning(
                    f"No API key configured for provider {provider}. Falling back to Ollama for advanced query."
                )
                response, tokens = self.llm_provider.query_ollama(
                    prompt_text,
                    temperature=request.temperature,
                )
                model = "ollama"
            elif provider == "openai":
                response, tokens = self.llm_provider.query_openai(
                    prompt_text, model, request.temperature, api_key=api_key
                )
            elif provider == "anthropic":
                response, tokens = self.llm_provider.query_anthropic(
                    prompt_text, model, request.temperature, api_key=api_key
                )
            else:
                response, tokens = self.llm_provider.query_ollama(
                    prompt_text, model=model if model != "auto" else None,
                    temperature=request.temperature,
                )
                model = "ollama"

            processing_time = (time.time() - start_time) * 1000

            # Cache only when not part of a multi-turn conversation (cached
            # answers depend on history that isn't part of the cache key).
            if conversation is None:
                cache_data = {
                    "response": response,
                    "model_used": model,
                    "tokens_used": tokens,
                    "complexity_level": complexity_level,
                }
                self.cache_manager.set(cache_key, cache_data)

            self._record_token_usage(
                request,
                response,
                tokens,
                model,
                complexity_level,
                db,
                original_prompt_tokens=original_prompt_tokens,
                optimized_prompt_tokens=optimized_prompt_tokens,
            )

            assistant_message = None
            if conversation is not None:
                assistant_message = self._save_message(
                    db,
                    conversation,
                    role="assistant",
                    content=response,
                    model_used=model,
                    complexity_level=complexity_level,
                    tokens=tokens,
                    cache_hit=False,
                    processing_time_ms=processing_time,
                )

            if status_callback:
                try:
                    status_callback(
                        "done",
                        {"model": model, "total_tokens": tokens.get("total_tokens", 0)},
                    )
                except Exception:
                    pass

            return PromptResponse(
                response=response,
                model_used=model,
                tokens_used=tokens,
                cache_hit=False,
                complexity_level=complexity_level,
                processing_time_ms=processing_time,
                conversation_id=conversation.id if conversation else None,
                user_message_id=user_message.id if user_message else None,
                assistant_message_id=assistant_message.id if assistant_message else None,
            )
        except Exception as e:
            logger.error(f"Error querying advanced model: {e}")
            raise

    def _record_token_usage(
        self,
        request: PromptRequest,
        response: str,
        tokens: Dict[str, int],
        model: str,
        complexity_level: str,
        db: Session,
        original_prompt_tokens: int = 0,
        optimized_prompt_tokens: int = 0,
    ):
        """Record token usage in database"""
        try:
            prompt_hash = hashlib.sha256(request.prompt.encode()).hexdigest()

            # Coerce user_id: numeric -> str, missing/placeholder -> "anonymous".
            raw_user_id = request.user_id
            if raw_user_id is None:
                user_id_value = "anonymous"
            else:
                user_id_str = str(raw_user_id).strip()
                if not user_id_str or user_id_str.lower() in {"string", "null", "none"}:
                    user_id_value = "anonymous"
                else:
                    user_id_value = user_id_str

            record = TokenUsageRecord(
                user_id=user_id_value,
                prompt=request.prompt,
                prompt_hash=prompt_hash,
                response=response,
                prompt_tokens=tokens.get("prompt_tokens", 0),
                response_tokens=tokens.get("response_tokens", 0),
                total_tokens=tokens.get("total_tokens", 0),
                original_prompt_tokens=original_prompt_tokens,
                optimized_prompt_tokens=optimized_prompt_tokens,
                optimization_applied=(
                    original_prompt_tokens > 0
                    and optimized_prompt_tokens > 0
                    and optimized_prompt_tokens < original_prompt_tokens
                ),
                model_used=model,
                complexity_level=complexity_level,
                timestamp=datetime.utcnow(),
            )

            db.add(record)
            db.commit()
            logger.info(
                f"Token usage recorded: {tokens['total_tokens']} tokens "
                f"(original_prompt={original_prompt_tokens}, "
                f"optimized_prompt={optimized_prompt_tokens})"
            )
        except Exception as e:
            logger.error(f"Error recording token usage: {e}")
            db.rollback()
