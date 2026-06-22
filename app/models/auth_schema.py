from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from datetime import datetime


class UserRegister(BaseModel):
    """User registration schema"""

    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=8)


class UserLogin(BaseModel):
    """User login schema"""

    email: EmailStr
    password: str


class UserResponse(BaseModel):
    """User response schema (without password)"""

    id: int
    username: str
    email: str
    created_at: datetime
    total_tokens_used: int
    total_cost: float
    is_active: bool


class APIKeyRequest(BaseModel):
    """Request to add/update API key"""

    provider: str  # openai, anthropic, ollama
    api_key: str
    model_name: str


class APIKeyResponse(BaseModel):
    """API key response (with masked key)"""

    id: int
    provider: str
    model_name: str
    is_active: bool
    created_at: datetime
    masked_key: Optional[str] = None
    # Note: full api_key is never returned for security


class DeveloperKeyCreate(BaseModel):
    """Request to mint a developer secret key."""

    label: str = Field(..., min_length=1, max_length=100)


class DeveloperKeyResponse(BaseModel):
    """Developer key as shown in the dashboard list — never the secret."""

    id: int
    label: str
    key_prefix: str
    last_four: str
    is_active: bool
    created_at: datetime
    last_used_at: Optional[datetime] = None


class DeveloperKeyCreateResponse(DeveloperKeyResponse):
    """Returned ONCE at creation — includes the raw secret. The client must
    store it now; it can never be retrieved again."""

    secret_key: str


class TokenResponse(BaseModel):
    """JWT token response"""

    access_token: str
    token_type: str
    user: UserResponse
