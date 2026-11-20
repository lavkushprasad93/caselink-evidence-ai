"""Schema tests for migration 0001. Skipped when PostgreSQL is not reachable."""

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError, OperationalError

from app.config import settings


@pytest.fixture()
def conn():
    engine = create_engine(settings.database_url)
    try:
        connection = engine.connect()
    except OperationalError:
        pytest.skip("PostgreSQL not reachable")
    tx = connection.begin()
    try:
        has_table = connection.execute(text("SELECT to_regclass('public.entity')")).scalar()
        if has_table is None:
            pytest.skip("Run `alembic upgrade head` first")
        yield connection
    finally:
        tx.rollback()
        connection.close()
        engine.dispose()


def _add_entity(conn, type_: str, value: str) -> None:
    conn.execute(
        text("INSERT INTO entity (type, normalized_value) VALUES (:t, :v)"),
        {"t": type_, "v": value},
    )


def test_strong_identifier_is_unique(conn):
    _add_entity(conn, "UPI", "alpha@upi")
    with pytest.raises(IntegrityError), conn.begin_nested():
        _add_entity(conn, "UPI", "alpha@upi")


def test_same_value_allowed_across_different_strong_types(conn):
    _add_entity(conn, "PHONE", "9000000001")
    _add_entity(conn, "ACCOUNT", "9000000001")


def test_person_names_are_not_unique(conn):
    _add_entity(conn, "PERSON", "rajesh kumar")
    _add_entity(conn, "PERSON", "rajesh kumar")


def test_page_number_unique_per_document(conn):
    doc_id = conn.execute(
        text(
            "INSERT INTO document (sha256, storage_uri, uploaded_by) "
            "VALUES (repeat('a', 64), 's3://x/y', 'tester') RETURNING id"
        )
    ).scalar()
    ins = text("INSERT INTO page (document_id, page_no) VALUES (:d, 1)")
    conn.execute(ins, {"d": doc_id})
    with pytest.raises(IntegrityError), conn.begin_nested():
        conn.execute(ins, {"d": doc_id})


def test_mention_defaults_to_unverified(conn):
    doc_id = conn.execute(
        text(
            "INSERT INTO document (sha256, storage_uri, uploaded_by) "
            "VALUES (repeat('b', 64), 's3://x/z', 'tester') RETURNING id"
        )
    ).scalar()
    span_id = conn.execute(
        text("INSERT INTO span (document_id, text) VALUES (:d, 'sample') RETURNING id"),
        {"d": doc_id},
    ).scalar()
    status = conn.execute(
        text(
            "INSERT INTO mention (span_id, raw_text) VALUES (:s, 'sample') "
            "RETURNING verification_status"
        ),
        {"s": span_id},
    ).scalar()
    assert status == "unverified"
