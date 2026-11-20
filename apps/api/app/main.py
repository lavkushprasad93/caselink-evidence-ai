import logging
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.auth.deps import require_case_access
from app.auth.tokens import decode_jwt
from app.config import settings
from app.db import get_db
from app.routers.documents import router as documents_router
from app.scanner import ScannerUnavailable
from app.storage import StorageUnavailable

log = logging.getLogger(__name__)

app = FastAPI(title="CaseLink Evidence AI API", version=settings.app_version)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(documents_router)


@app.exception_handler(ScannerUnavailable)
async def scanner_unavailable(
    request: Request,
    exc: ScannerUnavailable,
) -> JSONResponse:
    log.warning("ClamAV unavailable during upload: %s", exc)
    return JSONResponse(status_code=503, content={"detail": "Malware scanner unavailable"})


@app.exception_handler(StorageUnavailable)
async def storage_unavailable(
    request: Request,
    exc: StorageUnavailable,
) -> JSONResponse:
    log.warning("MinIO unavailable during upload: %s", exc)
    return JSONResponse(status_code=503, content={"detail": "Object storage unavailable"})


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness: the API process is up. Does not touch the database."""
    return {"status": "ok", "version": settings.app_version}


@app.get("/health/db")
def health_db(db: Annotated[Session, Depends(get_db)]) -> dict[str, str]:
    """Readiness: the API can reach PostgreSQL."""
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return {"status": "ok", "database": "up"}


@app.get("/me")
def me(user: Annotated[dict[str, Any], Depends(decode_jwt)]) -> dict[str, Any]:
    realm_access = user.get("realm_access")
    roles = realm_access.get("roles", []) if isinstance(realm_access, dict) else []
    return {
        "sub": user["sub"],
        "username": user.get("preferred_username"),
        "roles": roles,
    }


@app.get("/cases/{case_id}/access")
def check_case_access(
    case_id: UUID,
    user: Annotated[dict[str, Any], Depends(require_case_access)],
) -> dict[str, str]:
    return {"case_id": str(case_id), "user_id": user["sub"]}
