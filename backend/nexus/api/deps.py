"""Shared API dependencies: auth, sessions, rate limiting."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.core.exceptions import PermissionDeniedError
from nexus.core.rate_limit import limiter
from nexus.core.security import api_key_valid, decode_access_token, role_at_least
from nexus.database.models import User
from nexus.database.session import get_session


@dataclass
class AuthContext:
    user_id: str | None = None
    email: str | None = None
    role: str = "analyst"
    via: str = "anonymous"


async def get_auth_context(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    authorization: Annotated[str | None, Header()] = None,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> AuthContext:
    # rate limit first
    client = request.client.host if request.client else "unknown"
    allowed, retry_after = limiter.check(client)
    if not allowed:
        from nexus.core.exceptions import NexusError

        raise NexusError(f"Rate limit exceeded; retry in {retry_after}s", code="rate_limited", status_code=429)

    candidate = None
    if authorization and authorization.lower().startswith("bearer "):
        candidate = authorization[7:].strip()
    elif x_api_key:
        candidate = x_api_key.strip()

    if not candidate:
        # dev mode: allow anonymous analyst when no API keys configured
        from nexus.config import settings

        if not settings.api_key_list:
            return AuthContext(role="analyst", via="dev-anonymous")
        from nexus.core.exceptions import PermissionDeniedError

        raise PermissionDeniedError("Missing credentials")

    if api_key_valid(candidate):
        return AuthContext(role="admin", via="api-key")

    data = decode_access_token(candidate)
    if data and data.get("sub"):
        email = str(data["sub"])
        from sqlalchemy.orm import selectinload

        user = (
            (
                await session.execute(
                    select(User).options(selectinload(User.role)).where(User.email == email)
                )
            )
            .scalars()
            .first()
        )
        role = user.role.name if user and user.role else str(data.get("role", "analyst"))
        return AuthContext(user_id=user.id if user else None, email=email, role=role, via="jwt")

    from nexus.core.exceptions import PermissionDeniedError

    raise PermissionDeniedError("Invalid credentials")


def require_role(minimum: str):
    async def _dep(ctx: Annotated[AuthContext, Depends(get_auth_context)]) -> AuthContext:
        if not role_at_least(ctx.role, minimum):
            raise PermissionDeniedError(f"Requires role >= {minimum}")
        return ctx

    return _dep
