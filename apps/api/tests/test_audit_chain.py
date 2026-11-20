import threading
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, OperationalError, ProgrammingError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.audit import append_audit, compute_entry_hash, verify_chain
from app.auth.tokens import get_key_resolver
from app.config import settings
from app.db import get_db
from app.main import app
from tests.helpers import PRIVATE, auth, make_token


@pytest.mark.parametrize("table", ["audit_log", "provenance_event"])
def test_database_refuses_update_delete_and_truncate(append_only_conn, table: str) -> None:
    if table == "audit_log":
        append_audit(Session(bind=append_only_conn), "u", "TEST", "r", None)
    else:
        append_only_conn.execute(
            text("INSERT INTO provenance_event (object_type, action) VALUES ('t', 'TEST')")
        )

    statements = (
        f"UPDATE {table} SET action = 'CHANGED'",
        f"DELETE FROM {table}",
        f"TRUNCATE {table}",
    )
    for statement in statements:
        with pytest.raises(DBAPIError, match="append-only"), append_only_conn.begin_nested():
            append_only_conn.execute(text(statement))


def test_inserting_is_still_allowed(append_only_conn) -> None:
    append_audit(Session(bind=append_only_conn), "u", "TEST", "r", None)
    count = append_only_conn.execute(text("SELECT count(*) FROM audit_log")).scalar_one()
    assert count >= 1


@pytest.fixture
def chain(conn) -> Iterator[Session]:
    """Use a throwaway table so tampering tests never change the real audit log."""
    schema = f"t_{uuid.uuid4().hex[:8]}"
    conn.execute(text(f"CREATE SCHEMA {schema}"))
    conn.execute(text(f"CREATE TABLE {schema}.audit_log (LIKE public.audit_log INCLUDING ALL)"))
    conn.execute(text(f"SET LOCAL search_path TO {schema}, public"))
    yield Session(bind=conn)


def fill(db: Session, count: int = 5) -> list[int]:
    for index in range(count):
        append_audit(db, f"user{index}", "ACTION", f"resource{index}", "10.0.0.1")
    return list(db.scalars(text("SELECT id FROM audit_log ORDER BY id")))


def _now() -> datetime:
    return datetime.now(UTC)


def test_untouched_chain_verifies(chain: Session) -> None:
    ids = fill(chain)
    report = verify_chain(chain)
    head = chain.scalar(text("SELECT entry_hash FROM audit_log WHERE id = :id"), {"id": ids[-1]})

    assert report.ok and report.entries == 5 and report.problem is None
    assert report.head_hash == head


def test_empty_log_verifies(chain: Session) -> None:
    report = verify_chain(chain)
    assert report.ok and report.entries == 0 and report.head_hash is None


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("action", "'SOMETHING_ELSE'"),
        ("user_id", "'someone_else'"),
        ("resource", "'resource_changed'"),
        ("ip", "'6.6.6.6'"),
        ("ts", "ts + interval '1 second'"),
    ],
)
def test_editing_entry_fields_is_detected(chain: Session, column: str, value: str) -> None:
    ids = fill(chain)
    chain.execute(text(f"UPDATE audit_log SET {column} = {value} WHERE id = :id"), {"id": ids[2]})

    report = verify_chain(chain)
    assert not report.ok
    assert report.first_bad_id == ids[2]
    assert "modified" in (report.problem or "")


def test_deleting_a_middle_entry_is_detected(chain: Session) -> None:
    ids = fill(chain)
    chain.execute(text("DELETE FROM audit_log WHERE id = :id"), {"id": ids[2]})

    report = verify_chain(chain)
    assert not report.ok
    assert report.first_bad_id == ids[3]


def test_deleting_the_first_entry_is_detected(chain: Session) -> None:
    ids = fill(chain)
    chain.execute(text("DELETE FROM audit_log WHERE id = :id"), {"id": ids[0]})

    report = verify_chain(chain)
    assert not report.ok
    assert report.first_bad_id == ids[1]
    assert "earlier entries were removed" in (report.problem or "")


def test_inserting_a_forged_entry_is_detected(chain: Session) -> None:
    ids = fill(chain)
    forged_hash = compute_entry_hash(
        "not-the-real-previous-hash",
        "x",
        "A",
        "r",
        None,
        _now(),
    )
    chain.execute(
        text("""
            INSERT INTO audit_log
              (id, user_id, action, resource, ts, prev_hash, entry_hash)
            VALUES (:id, 'x', 'A', 'r', :ts, 'not-the-real-previous-hash', :hash)
            """),
        {"id": ids[-1] + 1000, "ts": _now(), "hash": forged_hash},
    )

    report = verify_chain(chain)
    assert not report.ok
    assert report.first_bad_id == ids[-1] + 1000


def test_deleting_newest_entries_needs_an_external_checkpoint(chain: Session) -> None:
    ids = fill(chain)
    saved = verify_chain(chain)
    chain.execute(
        text("DELETE FROM audit_log WHERE id IN (:last, :previous)"),
        {"last": ids[-1], "previous": ids[-2]},
    )

    after = verify_chain(chain)
    assert after.ok
    assert (after.entries, after.head_hash) != (saved.entries, saved.head_hash)


def test_rewriting_newest_entry_and_hash_needs_an_external_checkpoint(chain: Session) -> None:
    ids = fill(chain)
    saved = verify_chain(chain)
    row = chain.execute(
        text("SELECT * FROM audit_log WHERE id = :id"),
        {"id": ids[-1]},
    ).one()
    new_hash = compute_entry_hash(
        row.prev_hash,
        row.user_id,
        "FORGED",
        row.resource,
        row.ip,
        row.ts,
    )
    chain.execute(
        text("UPDATE audit_log SET action = 'FORGED', entry_hash = :hash WHERE id = :id"),
        {"hash": new_hash, "id": ids[-1]},
    )

    after = verify_chain(chain)
    assert after.ok
    assert after.head_hash != saved.head_hash


def test_concurrent_writers_keep_one_unbroken_chain() -> None:
    schema = f"t_{uuid.uuid4().hex[:8]}"
    admin = create_engine(settings.database_url, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            has_table = connection.execute(text("SELECT to_regclass('public.audit_log')")).scalar()
            if has_table is None:
                pytest.skip("Run `alembic upgrade head` first")
            connection.execute(text(f"CREATE SCHEMA {schema}"))
            connection.execute(
                text(f"CREATE TABLE {schema}.audit_log (LIKE public.audit_log INCLUDING ALL)")
            )
    except (OperationalError, ProgrammingError):
        admin.dispose()
        pytest.skip("PostgreSQL is unavailable or cannot create a scratch schema")

    engine = create_engine(
        settings.database_url,
        connect_args={"options": f"-c search_path={schema},public"},
    )
    errors: list[Exception] = []

    def writer(worker: int) -> None:
        try:
            for index in range(6):
                with Session(engine) as db:
                    append_audit(db, f"w{worker}", "CONCURRENT", f"item{index}", None)
                    db.commit()
        except Exception as exc:  # noqa: BLE001 - collect worker failures for the assertion
            errors.append(exc)

    try:
        threads = [threading.Thread(target=writer, args=(worker,)) for worker in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert errors == []
        with Session(engine) as db:
            report = verify_chain(db)
        assert report.ok, report.problem
        assert report.entries == 48
    finally:
        engine.dispose()
        with admin.connect() as connection:
            connection.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        admin.dispose()


@pytest.fixture
def http(conn) -> Iterator[tuple[TestClient, int]]:
    app.dependency_overrides[get_key_resolver] = lambda: (lambda _token: PRIVATE.public_key())

    def get_test_db() -> Iterator[Session]:
        yield Session(bind=conn)

    app.dependency_overrides[get_db] = get_test_db
    start = conn.execute(text("SELECT coalesce(max(id), 0) FROM audit_log")).scalar_one()
    yield TestClient(app), start
    app.dependency_overrides.clear()


def _new_entries(conn, start: int):
    return conn.execute(
        text("""
            SELECT user_id, action, resource
            FROM audit_log
            WHERE id > :start
            ORDER BY id
            """),
        {"start": start},
    ).all()


def test_authenticated_request_is_recorded(http, conn) -> None:
    client, start = http
    response = client.get("/me", headers=auth(make_token(["investigator"], sub="alice")))

    assert response.status_code == 200
    assert [tuple(row) for row in _new_entries(conn, start)] == [("alice", "API_GET", "/me")]


def test_query_string_is_not_recorded(http, conn) -> None:
    client, start = http
    client.get(
        "/me?search=secret-name",
        headers=auth(make_token(["investigator"])),
    )

    assert "secret" not in _new_entries(conn, start)[0].resource


def test_health_and_anonymous_requests_leave_no_entries(http, conn) -> None:
    client, start = http
    assert client.get("/health").status_code == 200
    assert client.get("/me").status_code == 401
    assert client.get("/me", headers=auth("garbage")).status_code == 401
    assert _new_entries(conn, start) == []


def test_audit_write_failure_refuses_the_request(http) -> None:
    client, _start = http

    class BrokenDB:
        def scalar(self, *_args: object, **_kwargs: object) -> None:
            raise SQLAlchemyError("audit table unavailable")

        def execute(self, *_args: object, **_kwargs: object) -> None:
            raise SQLAlchemyError("audit table unavailable")

        def commit(self) -> None:
            return None

        def rollback(self) -> None:
            return None

    app.dependency_overrides[get_db] = lambda: BrokenDB()
    response = client.get("/me", headers=auth(make_token(["investigator"])))
    assert response.status_code == 503


def test_admin_can_verify_the_chain(http) -> None:
    client, _start = http
    response = client.get("/audit/verify", headers=auth(make_token(["admin"])))

    assert response.status_code == 200
    assert response.json()["ok"] is True
