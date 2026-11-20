from collections.abc import Callable
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.tokens import decode_jwt
from app.db import get_db
from app.models import CaseMember


def require_role(*roles: str) -> Callable[..., dict[str, Any]]:
    """Check 1 of 2: the user holds at least one of the given realm roles."""

    def dep(token: Annotated[dict[str, Any], Depends(decode_jwt)]) -> dict[str, Any]:
        realm_access = token.get("realm_access")
        held_roles = realm_access.get("roles", []) if isinstance(realm_access, dict) else []
        if not isinstance(held_roles, list) or not all(
            isinstance(role, str) for role in held_roles
        ):
            held_roles = []
        if not set(roles).intersection(held_roles):
            raise HTTPException(status_code=403, detail="Insufficient role")
        return token

    return dep


def require_case_access(
    case_id: UUID,
    user: Annotated[dict[str, Any], Depends(require_role("investigator", "supervisor"))],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """Check case membership after role authorization, hiding non-member cases with 404."""
    member = db.scalar(
        select(CaseMember).where(
            CaseMember.case_id == case_id,
            CaseMember.user_id == user["sub"],
        )
    )
    if member is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return user
