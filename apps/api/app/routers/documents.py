import hashlib
import logging
import uuid
from collections.abc import Callable, Iterator
from typing import Annotated, Any, BinaryIO
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit import append_audit
from app.auth.deps import require_case_access
from app.config import settings
from app.db import get_db
from app.filetypes import ALLOWED, CONTENT_TYPES, extension_of, safe_filename, sniff_type
from app.jobs import get_enqueue
from app.provenance import record_provenance
from app.scanner import Scanner, get_scanner
from app.storage import ObjectStore, get_store

log = logging.getLogger(__name__)
router = APIRouter()

CHUNK = 256 * 1024


class TooLarge(Exception):
    pass


class _Progress:
    def __init__(self) -> None:
        self.size = 0
        self.hasher = hashlib.sha256()


def _read_chunks(stream: BinaryIO, progress: _Progress) -> Iterator[bytes]:
    """Count and hash the upload while yielding bounded chunks to the scanner."""
    while chunk := stream.read(CHUNK):
        progress.size += len(chunk)
        if progress.size > settings.max_upload_bytes:
            raise TooLarge
        progress.hasher.update(chunk)
        yield chunk


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _duplicate(
    db: Session,
    case_id: UUID,
    user: dict[str, Any],
    sha: str,
    ip: str | None,
) -> HTTPException:
    existing = db.scalar(
        text("SELECT id FROM document WHERE case_id = :case_id AND sha256 = :sha256"),
        {"case_id": case_id, "sha256": sha},
    )
    if existing is None:
        raise RuntimeError("Duplicate document was reported but no existing row was found.")
    record_provenance(
        db,
        "document",
        existing,
        "UPLOAD_DUPLICATE_REJECTED",
        user["sub"],
        "api",
        settings.app_version,
        sha,
        sha,
    )
    append_audit(db, user["sub"], "UPLOAD_DUPLICATE_REJECTED", f"document:{existing}", ip)
    db.commit()
    return HTTPException(
        status_code=409,
        detail={
            "message": "This exact file was already uploaded to this case.",
            "existing_document_id": str(existing),
        },
    )


@router.post("/cases/{case_id}/documents", status_code=201)
def upload_document(
    case_id: UUID,
    file: UploadFile,
    request: Request,
    user: Annotated[dict[str, Any], Depends(require_case_access)],
    db: Annotated[Session, Depends(get_db)],
    store: Annotated[ObjectStore, Depends(get_store)],
    scanner: Annotated[Scanner, Depends(get_scanner)],
    enqueue: Annotated[Callable[[str], bool], Depends(get_enqueue)],
) -> dict[str, Any]:
    ip = _client_ip(request)
    name = safe_filename(file.filename)
    stream = file.file

    head = stream.read(16)
    stream.seek(0)
    kind = sniff_type(head)
    if kind is None or extension_of(name) not in ALLOWED[kind]:
        raise HTTPException(
            status_code=415,
            detail="Unsupported or mismatched file type. Allowed: PDF, JPG, PNG, TIFF.",
        )

    progress = _Progress()
    try:
        signature = scanner.scan(_read_chunks(stream, progress))
    except TooLarge:
        limit_mb = settings.max_upload_bytes // (1024 * 1024)
        raise HTTPException(
            status_code=413,
            detail=f"File is larger than the {limit_mb} MB limit.",
        ) from None

    sha = progress.hasher.hexdigest()
    if signature is not None:
        append_audit(
            db,
            user["sub"],
            "UPLOAD_REJECTED_MALWARE",
            f"case:{case_id}:sha256:{sha}",
            ip,
        )
        db.commit()
        log.warning("Malware detected in upload to case %s: %s", case_id, signature)
        raise HTTPException(status_code=422, detail="File failed malware scan")

    already = db.scalar(
        text("SELECT 1 FROM document WHERE case_id = :case_id AND sha256 = :sha256"),
        {"case_id": case_id, "sha256": sha},
    )
    if already:
        raise _duplicate(db, case_id, user, sha, ip)

    key = f"{case_id}/{sha}/{name}"
    stream.seek(0)
    storage_uri = store.put(key, stream, progress.size, CONTENT_TYPES[kind])

    document_id = uuid.uuid4()
    try:
        with db.begin_nested():
            db.execute(
                text("""
                    INSERT INTO document
                      (id, case_id, sha256, storage_uri, uploaded_by,
                       original_filename, size_bytes, content_type)
                    VALUES (:id, :case_id, :sha256, :storage_uri, :uploaded_by,
                            :original_filename, :size_bytes, :content_type)
                    """),
                {
                    "id": document_id,
                    "case_id": case_id,
                    "sha256": sha,
                    "storage_uri": storage_uri,
                    "uploaded_by": user["sub"],
                    "original_filename": name,
                    "size_bytes": progress.size,
                    "content_type": CONTENT_TYPES[kind],
                },
            )
    except IntegrityError:
        existing = db.scalar(
            text("SELECT id FROM document WHERE case_id = :case_id AND sha256 = :sha256"),
            {"case_id": case_id, "sha256": sha},
        )
        if existing is None:
            raise
        raise _duplicate(db, case_id, user, sha, ip) from None

    record_provenance(
        db,
        "document",
        document_id,
        "UPLOAD",
        user["sub"],
        "api",
        settings.app_version,
        sha,
        sha,
    )
    append_audit(db, user["sub"], "UPLOAD", f"document:{document_id}", ip)
    db.commit()

    queued = enqueue(str(document_id))
    return {"id": str(document_id), "sha256": sha, "size_bytes": progress.size, "queued": queued}
