import hashlib
import json
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

AUDIT_LOCK_KEY = 7_120_001


def compute_entry_hash(
    prev_hash: str | None,
    user_id: str | None,
    action: str,
    resource: str,
    ip: str | None,
    ts: datetime,
) -> str:
    payload = json.dumps(
        [prev_hash or "", user_id, action, resource, ip, ts.astimezone(UTC).isoformat()],
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def append_audit(
    db: Session,
    user_id: str | None,
    action: str,
    resource: str,
    ip: str | None,
) -> str:
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": AUDIT_LOCK_KEY})
    prev_hash = db.scalar(text("SELECT entry_hash FROM audit_log ORDER BY id DESC LIMIT 1"))
    timestamp = datetime.now(UTC)
    entry_hash = compute_entry_hash(prev_hash, user_id, action, resource, ip, timestamp)
    db.execute(
        text("""
            INSERT INTO audit_log (user_id, action, resource, ip, ts, prev_hash, entry_hash)
            VALUES (:user_id, :action, :resource, :ip, :timestamp, :prev_hash, :entry_hash)
            """),
        {
            "user_id": user_id,
            "action": action,
            "resource": resource,
            "ip": ip,
            "timestamp": timestamp,
            "prev_hash": prev_hash,
            "entry_hash": entry_hash,
        },
    )
    return entry_hash
