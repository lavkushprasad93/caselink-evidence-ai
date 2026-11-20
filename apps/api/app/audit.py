import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.config import settings

AUDIT_LOCK_KEY = 7_120_001


@dataclass(frozen=True)
class ChainReport:
    ok: bool
    entries: int
    head_hash: str | None
    first_bad_id: int | None
    problem: str | None


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


def verify_chain(db: Session) -> ChainReport:
    """Verify the stored chain; a saved external head is needed to detect whole-chain rewrites."""
    rows = db.execute(text("""
            SELECT id, user_id, action, resource, ip, ts, prev_hash, entry_hash
            FROM audit_log
            ORDER BY id
            """))
    previous_hash: str | None = None
    head_hash: str | None = None
    entries = 0
    first_bad_id: int | None = None
    problem: str | None = None

    for row in rows:
        entries += 1
        head_hash = row.entry_hash
        if problem is not None:
            continue
        if entries == 1 and row.prev_hash is not None:
            first_bad_id = row.id
            problem = "earlier entries were removed or the chain has no trusted starting point"
            continue
        if row.prev_hash != previous_hash:
            first_bad_id = row.id
            problem = "previous hash does not match; an earlier entry may be missing or altered"
            continue
        expected_hash = compute_entry_hash(
            row.prev_hash,
            row.user_id,
            row.action,
            row.resource,
            row.ip,
            row.ts,
        )
        if row.entry_hash != expected_hash:
            first_bad_id = row.id
            problem = "entry was modified: stored hash does not match its contents"
            continue
        previous_hash = row.entry_hash

    return ChainReport(
        ok=problem is None,
        entries=entries,
        head_hash=head_hash,
        first_bad_id=first_bad_id,
        problem=problem,
    )


def _verify_cli() -> int:
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    try:
        with Session(engine) as db:
            report = verify_chain(db)
        print(json.dumps(asdict(report), sort_keys=True))
        return 0 if report.ok else 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(_verify_cli())
