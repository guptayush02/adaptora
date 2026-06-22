from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.db.models import User, UserAPIKey, DeveloperApiKey
from app.models.auth_schema import (
    UserRegister,
    UserLogin,
    UserResponse,
    TokenResponse,
    APIKeyRequest,
    APIKeyResponse,
    DeveloperKeyCreate,
    DeveloperKeyResponse,
    DeveloperKeyCreateResponse,
)
from app.core.security import (
    hash_password,
    verify_password,
    create_access_token,
    decode_token,
    encrypt_api_key,
    decrypt_api_key,
    generate_api_key,
    hash_api_key,
)
from datetime import datetime as _dt
from app.core.logger import logger
from datetime import timedelta
from app.services.llm_provider import LLMProvider

router = APIRouter(prefix="/api/auth", tags=["Authentication"])
security = HTTPBearer()


def _mask_api_key(raw_key: str) -> str:
    """Return first 2 + *** + last 2 characters of an API key for safe display."""
    if not raw_key:
        return ""
    if len(raw_key) <= 4:
        return "***"
    return f"{raw_key[:2]}***{raw_key[-2:]}"


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security), db: Session = Depends(get_db)
) -> User:
    """Get current authenticated user"""
    token = credentials.credentials
    payload = decode_token(token)

    if not payload:
        logger.warning(
            "Auth: decode_token returned None — token is invalid, expired, or "
            "signed with a different SECRET_KEY than the running server uses."
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
        )

    user_id = payload.get("sub")
    # The token stores sub as a string (see create_access_token); the User.id
    # column is Integer. SQLite is forgiving but Postgres isn't, so coerce.
    try:
        user_pk = int(user_id) if user_id is not None else None
    except (TypeError, ValueError):
        user_pk = user_id

    user = db.query(User).filter(User.id == user_pk).first()

    if not user:
        logger.warning(
            f"Auth: token decoded ok (sub={user_id!r}) but no user with id={user_pk!r} exists. "
            f"This often means the token was issued against a different DB."
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    return user


@router.post("/register", response_model=TokenResponse)
async def register(request: UserRegister, db: Session = Depends(get_db)):
    """Register a new user"""
    try:
        # Check if user already exists
        existing_user = db.query(User).filter(User.email == request.email).first()
        print (existing_user)
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered",
            )

        existing_username = db.query(User).filter(User.username == request.username).first()
        print (existing_username)
        if existing_username:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username already taken",
            )

        # Create new user
        hashed_password = hash_password(request.password)
        user = User(
            username=request.username,
            email=request.email,
            hashed_password=hashed_password,
        )

        db.add(user)
        db.commit()
        db.refresh(user)

        # Create access token
        access_token = create_access_token(data={"sub": user.id})

        logger.info(f"New user registered: {user.username}")

        return TokenResponse(
            access_token=access_token,
            token_type="bearer",
            user=UserResponse(
                id=user.id,
                username=user.username,
                email=user.email,
                created_at=user.created_at,
                total_tokens_used=user.total_tokens_used,
                total_cost=user.total_cost,
                is_active=user.is_active,
            ),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Registration error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Registration failed",
        )


@router.post("/login", response_model=TokenResponse)
async def login(request: UserLogin, db: Session = Depends(get_db)):
    """Login user"""
    try:
        # Find user by email
        user = db.query(User).filter(User.email == request.email).first()

        if not user or not verify_password(request.password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password",
            )

        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is disabled",
            )

        # Create access token
        access_token = create_access_token(data={"sub": user.id})

        logger.info(f"User logged in: {user.username}")

        return TokenResponse(
            access_token=access_token,
            token_type="bearer",
            user=UserResponse(
                id=user.id,
                username=user.username,
                email=user.email,
                created_at=user.created_at,
                total_tokens_used=user.total_tokens_used,
                total_cost=user.total_cost,
                is_active=user.is_active,
            ),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Login failed",
        )


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(current_user: User = Depends(get_current_user)):
    """Get current user information"""
    return UserResponse(
        id=current_user.id,
        username=current_user.username,
        email=current_user.email,
        created_at=current_user.created_at,
        total_tokens_used=current_user.total_tokens_used,
        total_cost=current_user.total_cost,
        is_active=current_user.is_active,
    )


@router.post("/api-keys", response_model=APIKeyResponse)
async def add_api_key(
    request: APIKeyRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Add or update user's API key"""
    try:
        # Check if API key already exists for this provider
        existing_key = (
            db.query(UserAPIKey)
            .filter(
                UserAPIKey.user_id == current_user.id,
                UserAPIKey.provider == request.provider,
            )
            .first()
        )

        if existing_key:
            # Update existing key
            existing_key.api_key = encrypt_api_key(request.api_key)
            existing_key.model_name = request.model_name
            existing_key.updated_at = __import__("datetime").datetime.utcnow()
        else:
            # Create new key
            api_key_record = UserAPIKey(
                user_id=current_user.id,
                provider=request.provider,
                api_key=encrypt_api_key(request.api_key),
                model_name=request.model_name,
            )
            db.add(api_key_record)

        db.commit()

        logger.info(f"API key updated for user {current_user.username}: {request.provider}")

        return APIKeyResponse(
            id=existing_key.id if existing_key else api_key_record.id,
            provider=request.provider,
            model_name=request.model_name,
            is_active=existing_key.is_active if existing_key else True,
            created_at=existing_key.created_at if existing_key else api_key_record.created_at,
            masked_key=_mask_api_key(request.api_key),
        )

    except Exception as e:
        db.rollback()
        logger.error(f"Error adding API key: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to add API key",
        )


@router.get("/api-keys")
async def get_user_api_keys(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """Get user's API keys (masked)"""
    api_keys = (
        db.query(UserAPIKey)
        .filter(UserAPIKey.user_id == current_user.id)
        .all()
    )

    def _safe_mask(encrypted: str) -> str:
        try:
            return _mask_api_key(decrypt_api_key(encrypted) or "")
        except Exception:
            return ""

    return [
        APIKeyResponse(
            id=key.id,
            provider=key.provider,
            model_name=key.model_name,
            is_active=key.is_active,
            created_at=key.created_at,
            masked_key=_safe_mask(key.api_key),
        )
        for key in api_keys
    ]


@router.delete("/api-keys/{key_id}")
async def delete_api_key(
    key_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete user's API key"""
    try:
        api_key = db.query(UserAPIKey).filter(
            UserAPIKey.id == key_id, UserAPIKey.user_id == current_user.id
        ).first()

        if not api_key:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="API key not found",
            )

        db.delete(api_key)
        db.commit()

        logger.info(f"API key deleted for user {current_user.username}")

        return {"message": "API key deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting API key: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete API key",
        )



@router.post("/developer-keys", response_model=DeveloperKeyCreateResponse)
async def create_developer_key(
    request: DeveloperKeyCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Mint a developer secret key for the public REST API.

    The raw secret is returned exactly once here — only its hash is stored,
    so it can never be retrieved again."""
    raw_key = generate_api_key()
    key = DeveloperApiKey(
        user_id=current_user.id,
        label=request.label,
        key_hash=hash_api_key(raw_key),
        # Reversible copy so the owner can re-reveal/copy the key later.
        key_encrypted=encrypt_api_key(raw_key),
        # Prefix shown in the dashboard (scheme + first 4 random chars).
        key_prefix=raw_key[: len("adp_live_") + 4],
        last_four=raw_key[-4:],
    )
    db.add(key)
    db.commit()
    db.refresh(key)

    logger.info(f"Developer key minted for user {current_user.username}: {key.label}")

    return DeveloperKeyCreateResponse(
        id=key.id,
        label=key.label,
        key_prefix=key.key_prefix,
        last_four=key.last_four,
        is_active=key.is_active,
        created_at=key.created_at,
        last_used_at=key.last_used_at,
        secret_key=raw_key,
    )


@router.get("/developer-keys", response_model=list[DeveloperKeyResponse])
async def list_developer_keys(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """List the user's developer keys (never the secret)."""
    keys = (
        db.query(DeveloperApiKey)
        .filter(DeveloperApiKey.user_id == current_user.id)
        .order_by(DeveloperApiKey.created_at.desc())
        .all()
    )
    return [
        DeveloperKeyResponse(
            id=k.id,
            label=k.label,
            key_prefix=k.key_prefix,
            last_four=k.last_four,
            is_active=k.is_active,
            created_at=k.created_at,
            last_used_at=k.last_used_at,
        )
        for k in keys
    ]


@router.get("/developer-keys/{key_id}/reveal")
async def reveal_developer_key(
    key_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the raw secret for one of the user's keys so they can copy it
    again. Only works for keys minted after reversible storage was added."""
    key = (
        db.query(DeveloperApiKey)
        .filter(
            DeveloperApiKey.id == key_id,
            DeveloperApiKey.user_id == current_user.id,
        )
        .first()
    )
    if not key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Developer key not found"
        )
    if not key.key_encrypted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This key was created before copy-anytime was supported; create a new key.",
        )
    return {"secret_key": decrypt_api_key(key.key_encrypted)}


@router.delete("/developer-keys/{key_id}")
async def revoke_developer_key(
    key_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Revoke (deactivate) a developer key. Calls using it then 401."""
    key = (
        db.query(DeveloperApiKey)
        .filter(
            DeveloperApiKey.id == key_id,
            DeveloperApiKey.user_id == current_user.id,
        )
        .first()
    )
    if not key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Developer key not found"
        )
    key.is_active = False
    key.revoked_at = _dt.utcnow()
    db.commit()
    logger.info(f"Developer key revoked for user {current_user.username}: {key.label}")
    return {"message": "Developer key revoked"}


@router.post("/models")
async def get_available_models(
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return available models for a provider. Accepts JSON {"provider": "openai", "api_key": "..."}

    If `api_key` is not provided, attempts to use the stored user API key for that provider.
    """
    provider = payload.get("provider") if isinstance(payload, dict) else None
    api_key = payload.get("api_key") if isinstance(payload, dict) else None

    if not provider:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="provider is required")

    # Use user key if api_key not provided
    if not api_key:
        stored = (
            db.query(UserAPIKey)
            .filter(UserAPIKey.user_id == current_user.id, UserAPIKey.provider == provider)
            .first()
        )
        if stored:
            try:
                api_key = decrypt_api_key(stored.api_key)
            except Exception:
                api_key = None

    provider_client = LLMProvider()
    try:
        models = provider_client.list_models(provider, api_key=api_key)
        return {"models": models}
    except Exception as e:
        logger.error(f"Error fetching models for provider {provider}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
