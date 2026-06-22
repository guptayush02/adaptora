from passlib.context import CryptContext
from datetime import datetime, timedelta
from typing import Optional
import hashlib
import hmac
import secrets
import jwt
from app.core.config import settings

# Prefix for developer secret keys minted on the dashboard. The `_live_`
# segment leaves room for a future `_test_` variant without breaking parsing.
API_KEY_PREFIX = "adp_live_"

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """Hash password"""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password"""
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create JWT access token"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )

    if "sub" in to_encode:
        to_encode["sub"] = str(to_encode["sub"])

    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(
        to_encode, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM
    )
    return encoded_jwt


def decode_token(token: str) -> Optional[dict]:
    """Decode JWT token"""
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            options={"verify_subject": False},
        )
        return payload
    except jwt.InvalidTokenError:
        return None


def generate_api_key() -> str:
    """Mint a new developer secret key, e.g. ``adp_live_<43 url-safe chars>``.

    Returned raw exactly once at creation — only its sha256 hash is stored."""
    return f"{API_KEY_PREFIX}{secrets.token_urlsafe(32)}"


def hash_api_key(raw_key: str) -> str:
    """sha256 hex digest of a raw developer key. One-way: bearer secrets must
    never be recoverable, so unlike provider keys these are hashed, not
    encrypted."""
    return hashlib.sha256(raw_key.encode()).hexdigest()


def verify_api_key(raw_key: str, stored_hash: str) -> bool:
    """Constant-time comparison of a presented key against a stored hash."""
    return hmac.compare_digest(hash_api_key(raw_key), stored_hash or "")


def encrypt_api_key(api_key: str) -> str:
    """Simple encryption for API keys (use stronger encryption in production)"""
    # In production, use proper encryption like cryptography library
    import base64
    return base64.b64encode(api_key.encode()).decode()


def decrypt_api_key(encrypted_key: str) -> str:
    """Simple decryption for API keys (use stronger encryption in production)"""
    import base64
    try:
        return base64.b64decode(encrypted_key.encode()).decode()
    except:
        return encrypted_key
