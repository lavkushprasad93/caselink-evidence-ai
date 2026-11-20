from datetime import UTC, datetime, timedelta

from app.audit import compute_entry_hash


def test_audit_hash_is_deterministic_for_same_entry() -> None:
    timestamp = datetime.now(UTC)

    first = compute_entry_hash(None, "user-1", "UPLOAD", "document:1", None, timestamp)

    assert first == compute_entry_hash(
        None,
        "user-1",
        "UPLOAD",
        "document:1",
        None,
        timestamp,
    )


def test_audit_hash_depends_on_previous_entry_and_timestamp() -> None:
    timestamp = datetime.now(UTC)
    first = compute_entry_hash(None, "user-1", "UPLOAD", "document:1", None, timestamp)

    assert compute_entry_hash(first, "user-1", "UPLOAD", "document:2", None, timestamp) != first
    assert compute_entry_hash(
        None, "user-1", "UPLOAD", "document:1", None, timestamp
    ) != compute_entry_hash(
        None,
        "user-1",
        "UPLOAD",
        "document:1",
        None,
        timestamp + timedelta(seconds=1),
    )
