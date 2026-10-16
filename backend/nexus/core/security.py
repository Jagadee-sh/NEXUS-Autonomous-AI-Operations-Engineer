"""Auth utilities: password hashing, JWT, API keys, RBAC."""

from __future__ import annotations

from datetime import UTC, datetime

from itsdangerous import BadSignature, URLSafeTimedSerializer
from passlib.context import CryptContext

from nexus.config import settings

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
_serializer = URLSafeTimedSerializer(settings.nexus_secret_key, salt="nexus-auth")


def hash_password(password: str) -> str:
    return _pwd.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _pwd.verify(plain, hashed)
    except Exception:
        return False


def create_access_token(subject: str, role: str = "viewer") -> str:
    payload = {"sub": subject, "role": role, "exp": datetime.now(UTC).timestamp()}
    return _serializer.dumps(payload)


def decode_access_token(token: str, max_age: int | None = None) -> dict | None:
    try:
        data = _serializer.loads(
            token, max_age=max_age or settings.access_token_expire_minutes * 60
        )
        return data if isinstance(data, dict) else None
    except BadSignature:
        return None


def api_key_valid(candidate: str) -> bool:
    keys = settings.api_key_list
    return bool(candidate) and candidate in keys


ROLE_RANK = {"viewer": 1, "analyst": 2, "admin": 3}


def role_at_least(role: str | None, minimum: str) -> bool:
    return ROLE_RANK.get(role or "viewer", 0) >= ROLE_RANK.get(minimum, 99)
