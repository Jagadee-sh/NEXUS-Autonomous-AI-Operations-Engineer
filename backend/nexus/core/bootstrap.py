"""Bootstrap: default roles and users for first-run usability.

Passwords come from environment (NEXUS_ADMIN_PASSWORD / NEXUS_ANALYST_PASSWORD).
In development a documented default is used; in production bootstrap is skipped
unless explicit passwords are provided.
"""

from __future__ import annotations

import os

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.core.security import hash_password
from nexus.database.models import Role, User
from nexus.logging_config import get_logger

log = get_logger("nexus.bootstrap")

DEV_ADMIN_EMAIL = "admin@nexus.local"
DEV_ANALYST_EMAIL = "analyst@nexus.local"
DEV_PASSWORD = "nexus-dev-password"

_DEFAULT_ROLES = [
    {"name": "admin", "permissions": {"*": True}},
    {"name": "analyst", "permissions": {"tasks:write": True, "documents:write": True, "approvals:decide": True}},
    {"name": "viewer", "permissions": {"tasks:read": True}},
]


async def ensure_roles(session: AsyncSession) -> dict[str, Role]:
    existing = {r.name: r for r in (await session.execute(select(Role))).scalars()}
    changed = False
    for spec in _DEFAULT_ROLES:
        if spec["name"] not in existing:
            role = Role(name=spec["name"], permissions=spec["permissions"])
            session.add(role)
            existing[spec["name"]] = role
            changed = True
    if changed:
        await session.commit()
        for r in existing.values():
            await session.refresh(r)
    return existing


async def ensure_default_users(session: AsyncSession) -> list[str]:
    """Create default users if the users table is empty. Returns created emails."""
    is_prod = os.environ.get("NEXUS_ENV", "development").lower() == "production"
    admin_pw = os.environ.get("NEXUS_ADMIN_PASSWORD", "")
    analyst_pw = os.environ.get("NEXUS_ANALYST_PASSWORD", "")

    if is_prod and not (admin_pw or analyst_pw):
        log.info("production without bootstrap passwords; skipping default users")
        return []

    roles = await ensure_roles(session)
    user_count = (await session.execute(select(User))).scalars().first()
    if user_count is not None:
        return []

    created: list[str] = []
    specs = [
        (DEV_ADMIN_EMAIL, admin_pw or DEV_PASSWORD, "NEXUS Admin", "admin"),
        (DEV_ANALYST_EMAIL, analyst_pw or DEV_PASSWORD, "NEXUS Analyst", "analyst"),
    ]
    for email, password, name, role_name in specs:
        session.add(
            User(
                email=email,
                hashed_password=hash_password(password),
                full_name=name,
                role_id=roles[role_name].id if role_name in roles else None,
                is_active=True,
            )
        )
        created.append(email)
    await session.commit()
    if created:
        log.warning(
            "created bootstrap users: %s (dev passwords — set NEXUS_ADMIN_PASSWORD/NEXUS_ANALYST_PASSWORD and change them)",
            ", ".join(created),
        )
    return created
