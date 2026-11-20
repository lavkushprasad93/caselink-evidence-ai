import logging
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.audit import append_audit
from app.auth.tokens import try_decode
from app.db import get_db
from app.netutil import client_ip

log = logging.getLogger(__name__)


def audit_request(
    request: Request,
    user: Annotated[dict[str, Any] | None, Depends(try_decode)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    if user is None:
        return

    try:
        append_audit(
            db,
            user["sub"],
            f"API_{request.method.upper()}",
            request.url.path,
            client_ip(request),
        )
        db.commit()
    except SQLAlchemyError as exc:
        try:
            db.rollback()
        except SQLAlchemyError:
            log.error("Rollback failed after the request audit write failed")
        log.error("Request refused because its audit entry could not be saved")
        raise HTTPException(status_code=503, detail="Audit log unavailable") from exc
