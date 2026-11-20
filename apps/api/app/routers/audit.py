from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.audit import ChainReport, verify_chain
from app.auth.deps import require_role
from app.db import get_db

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/verify", response_model=ChainReport)
def verify_audit_chain(
    _user: Annotated[dict[str, Any], Depends(require_role("admin"))],
    db: Annotated[Session, Depends(get_db)],
) -> ChainReport:
    try:
        return verify_chain(db)
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Could not verify audit chain") from exc
