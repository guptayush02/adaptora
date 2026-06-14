from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List, Union
from datetime import datetime


class PromptRequest(BaseModel):
    """Schema for incoming prompt requests"""

    prompt: str = Field(..., min_length=1, description="User prompt")
    model: Optional[str] = Field(None, description="Preferred LLM model")
    temperature: float = Field(0.7, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(None, ge=1)
    top_p: float = Field(1.0, ge=0.0, le=1.0)
    user_id: Optional[Union[str, int]] = Field(None, description="User identifier")
    conversation_id: Optional[int] = Field(
        None, description="Existing conversation to append this turn to"
    )
    skip_optimization: bool = Field(
        False,
        description=(
            "When True, the middleware will not re-run the prompt optimizer. "
            "Used by the 'preview & edit optimized prompt' UI flow where the "
            "user has already seen and possibly edited the optimized prompt."
        ),
    )
    # Pre-computed routing decisions from /api/optimize. When supplied (preview
    # flow), the middleware skips the corresponding pre-checks — no second
    # complexity analysis, no second bypass test, no second YES/NO internet
    # classifier call. The Continue click is therefore "just run the model".
    pre_complexity_level: Optional[str] = Field(
        None, description="easy / medium / difficult, precomputed by /api/optimize"
    )
    pre_bypass: Optional[bool] = Field(
        None, description="Whether bypass keyword matched, precomputed"
    )
    pre_needs_internet: Optional[bool] = Field(
        None, description="Whether the prompt needs a web search, precomputed"
    )
    pre_original_prompt: Optional[str] = Field(
        None,
        description=(
            "The raw text the user actually typed, BEFORE /api/optimize "
            "translated/optimized it. Used purely for accounting — the "
            "dashboard's 'before vs after' chart compares "
            "count_tokens(pre_original_prompt) against "
            "count_tokens(prompt). Without this, both columns would be "
            "computed on the already-optimized text in preview-continue "
            "mode and the chart would show equal bars."
        ),
    )
    metadata: Optional[Dict[str, Any]] = Field(None)


class OptimizePromptRequest(BaseModel):
    """Request for the standalone prompt-optimization endpoint used by the
    preview/edit UI flow."""

    prompt: str = Field(..., min_length=1)


class OptimizePromptResponse(BaseModel):
    """Result of the preview pipeline.

    `/api/optimize` runs ALL the pre-checks (bypass, complexity, optimization,
    internet-needed) up front and returns them here. The frontend shows the
    user what was decided, lets them edit the optimized prompt, then sends
    the decisions back to `/api/process` so the streaming endpoint can skip
    every pre-check and go straight to the LLM call."""

    original_prompt: str
    optimized_prompt: str
    optimization_reason: str
    tokens_saved: int
    optimization_percentage: float
    # Pre-check results echoed back so the UI can render them and so the
    # follow-up /api/process call can replay them via pre_* fields on
    # PromptRequest (no double-spending of LLM cycles).
    complexity_level: str = "medium"
    complexity_score: float = 0.0
    bypass: bool = False
    needs_internet: bool = False


class ConversationCreate(BaseModel):
    """Create a new (empty) conversation."""

    title: Optional[str] = Field(None, max_length=120)


class ConversationSummary(BaseModel):
    """Conversation row used in the sidebar list."""

    id: int
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int = 0
    last_message_preview: Optional[str] = None


class MessageItem(BaseModel):
    """A message inside a conversation."""

    id: int
    role: str
    content: str
    model_used: Optional[str] = None
    complexity_level: Optional[str] = None
    total_tokens: int = 0
    cache_hit: bool = False
    processing_time_ms: float = 0.0
    created_at: datetime


class ConversationDetail(BaseModel):
    """A conversation with all its messages."""

    id: int
    title: str
    created_at: datetime
    updated_at: datetime
    messages: List[MessageItem] = []


class PromptResponse(BaseModel):
    """Schema for prompt response"""

    response: str
    model_used: str
    tokens_used: Dict[str, int]
    cache_hit: bool
    complexity_level: str
    processing_time_ms: float
    prompt_optimization: Optional[str] = None
    conversation_id: Optional[int] = None
    user_message_id: Optional[int] = None
    assistant_message_id: Optional[int] = None


class ComplexityAnalysis(BaseModel):
    """Schema for complexity analysis result"""

    level: str  # simple, medium, difficult
    score: float  # 0-100
    reasoning: str
    confidence: float


class CacheEntry(BaseModel):
    """Schema for cached prompt/response"""

    cache_key: str
    prompt: str
    response: str
    model_used: str
    tokens_used: Dict[str, int]
    created_at: datetime
    ttl_seconds: int


class TokenUsage(BaseModel):
    """Schema for token tracking"""

    user_id: str
    prompt_tokens: int
    response_tokens: int
    total_tokens: int
    model: str
    timestamp: datetime
    prompt_hash: str
    cost_estimate: float = 0.0


class PromptOptimization(BaseModel):
    """Schema for optimized prompt"""

    original_prompt: str
    optimized_prompt: str
    optimization_reason: str
    tokens_saved: int
    optimization_percentage: float
