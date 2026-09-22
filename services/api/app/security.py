import re
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from argon2 import PasswordHasher
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from .config import get_settings
from .database import get_db
from .models import User

ph = PasswordHasher()
oauth2 = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")
settings = get_settings()


def hash_password(password: str) -> str:
    return ph.hash(password)


def verify_password(password: str, encoded: str) -> bool:
    try:
        return ph.verify(encoded, password)
    except Exception:
        return False


def create_token(user_id: str, kind: str = "access") -> str:
    delta = (
        timedelta(minutes=settings.access_token_minutes)
        if kind == "access"
        else timedelta(days=settings.refresh_token_days)
    )
    now = datetime.now(UTC)
    return jwt.encode(
        {"sub": user_id, "kind": kind, "iat": now, "exp": now + delta},
        settings.jwt_secret,
        algorithm="HS256",
    )


def current_user(
    token: Annotated[str, Depends(oauth2)], db: Annotated[Session, Depends(get_db)]
) -> User:
    error = HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired access token")
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        if payload.get("kind") != "access":
            raise error
        user = db.get(User, payload.get("sub"))
    except (JWTError, TypeError):
        raise error from None
    if not user or not user.is_active:
        raise error
    return user


SENSITIVE_PATTERNS = [
    (re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}"), "[REDACTED_EMAIL]"),
    (re.compile(r"(?<!\w)(?:\+?\d[\d ()-]{7,}\d)(?!\w)"), "[REDACTED_PHONE]"),
    (re.compile(r"(?i)(api[_-]?key|token|secret)\s*[:=]\s*[^\s,;]+"), r"\1=[REDACTED]"),
]


def redact(value: str) -> str:
    for pattern, replacement in SENSITIVE_PATTERNS:
        value = pattern.sub(replacement, value)
    return value


def redact_value(value: Any) -> Any:
    """Recursively redact persisted and returned observability data."""
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {str(key): redact_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_value(item) for item in value]
    return value
