"""Schema tests for migration 0001."""

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError


def _add_entity(conn: Connection, type_: str, value: str) -> None:
    conn.execute(
        text("INSERT INTO entity (type, normalized_value) VALUES (:t, :v)"),
        {"t": type_, "v": value},
    )


def test_strong_identifier_is_unique(schema_conn: Connection) -> None:
    _add_entity(schema_conn, "UPI", "alpha@upi")
    with pytest.raises(IntegrityError), schema_conn.begin_nested():
        _add_entity(schema_conn, "UPI", "alpha@upi")


def test_same_value_allowed_across_different_strong_types(schema_conn: Connection) -> None:
    _add_entity(schema_conn, "PHONE", "9000000001")
    _add_entity(schema_conn, "ACCOUNT", "9000000001")


def test_person_names_are_not_unique(schema_conn: Connection) -> None:
    _add_entity(schema_conn, "PERSON", "rajesh kumar")
    _add_entity(schema_conn, "PERSON", "rajesh kumar")


def test_page_number_unique_per_document(schema_conn: Connection) -> None:
    doc_id = schema_conn.execute(
        text(
            "INSERT INTO document (sha256, storage_uri, uploaded_by) "
            "VALUES (repeat('a', 64), 's3://x/y', 'tester') RETURNING id"
        )
    ).scalar()
    ins = text("INSERT INTO page (document_id, page_no) VALUES (:d, 1)")
    schema_conn.execute(ins, {"d": doc_id})
    with pytest.raises(IntegrityError), schema_conn.begin_nested():
        schema_conn.execute(ins, {"d": doc_id})


def test_mention_defaults_to_unverified(schema_conn: Connection) -> None:
    doc_id = schema_conn.execute(
        text(
            "INSERT INTO document (sha256, storage_uri, uploaded_by) "
            "VALUES (repeat('b', 64), 's3://x/z', 'tester') RETURNING id"
        )
    ).scalar()
    span_id = schema_conn.execute(
        text("INSERT INTO span (document_id, text) VALUES (:d, 'sample') RETURNING id"),
        {"d": doc_id},
    ).scalar()
    status = schema_conn.execute(
        text(
            "INSERT INTO mention (span_id, raw_text) VALUES (:s, 'sample') "
            "RETURNING verification_status"
        ),
        {"s": span_id},
    ).scalar()
    assert status == "unverified"
