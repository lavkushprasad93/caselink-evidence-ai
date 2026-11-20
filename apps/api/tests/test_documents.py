import hashlib
import itertools
import uuid
from collections.abc import Iterable, Iterator
from typing import Any, BinaryIO

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.audit import compute_entry_hash
from app.auth.tokens import get_key_resolver
from app.config import settings
from app.db import get_db
from app.jobs import get_enqueue
from app.main import app
from app.scanner import ScannerUnavailable, get_scanner
from app.storage import StorageUnavailable, get_store
from tests.helpers import PRIVATE, auth, make_token

PDF = b"%PDF-1.7\n%test document\n" + b"x" * 5000


class FakeStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.fail = False

    def put(self, key: str, stream: BinaryIO, size: int, content_type: str) -> str:
        if self.fail:
            raise StorageUnavailable("down")
        data = stream.read()
        assert len(data) == size
        self.objects[key] = data
        return f"s3://originals/{key}"


class FakeScanner:
    def __init__(self) -> None:
        self.verdict: str | None = None
        self.down = False

    def scan(self, chunks: Iterable[bytes]) -> str | None:
        for _ in chunks:
            pass
        if self.down:
            raise ScannerUnavailable("down")
        return self.verdict


@pytest.fixture
def env(upload_conn) -> Iterator[dict[str, Any]]:
    store, scanner, queued = FakeStore(), FakeScanner(), []

    def enqueue(document_id: str) -> bool:
        queued.append(document_id)
        return True

    def get_test_db() -> Iterator[Session]:
        yield Session(bind=upload_conn)

    app.dependency_overrides[get_key_resolver] = lambda: (lambda _token: PRIVATE.public_key())
    app.dependency_overrides[get_db] = get_test_db
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_scanner] = lambda: scanner
    app.dependency_overrides[get_enqueue] = lambda: enqueue

    case_id = upload_conn.execute(
        text("INSERT INTO investigation_case (title, created_by) VALUES ('t', 't') RETURNING id")
    ).scalar()
    upload_conn.execute(
        text(
            "INSERT INTO case_member (case_id, user_id, role) "
            "VALUES (:case_id, 'alice', 'investigator')"
        ),
        {"case_id": case_id},
    )
    audit_start = upload_conn.execute(text("SELECT coalesce(max(id), 0) FROM audit_log")).scalar()
    audit_last_hash = upload_conn.execute(
        text("SELECT entry_hash FROM audit_log ORDER BY id DESC LIMIT 1")
    ).scalar()
    yield {
        "client": TestClient(app),
        "conn": upload_conn,
        "store": store,
        "scanner": scanner,
        "queued": queued,
        "case_id": case_id,
        "audit_start": audit_start,
        "audit_last_hash": audit_last_hash,
        "headers": auth(make_token(["investigator"], sub="alice")),
    }
    app.dependency_overrides.clear()


def upload(
    env: dict[str, Any],
    content: bytes = PDF,
    filename: str = "fir101.pdf",
    **kwargs: Any,
) -> Any:
    return env["client"].post(
        f"/cases/{env['case_id']}/documents",
        files={"file": (filename, content, "application/pdf")},
        headers=kwargs.get("headers", env["headers"]),
    )


def test_upload_cors_preflight_allows_post() -> None:
    response = TestClient(app).options(
        "/cases/00000000-0000-0000-0000-000000000000/documents",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )

    assert response.status_code == 200
    assert "POST" in response.headers["access-control-allow-methods"]


def rows(env: dict[str, Any], sql: str, **params: Any) -> list[Any]:
    return list(env["conn"].execute(text(sql), params).all())


def audit_actions(env: dict[str, Any]) -> list[str]:
    return [
        row.action
        for row in rows(
            env,
            "SELECT action FROM audit_log WHERE id > :start "
            "AND action NOT LIKE 'API\\_%' ORDER BY id",
            start=env["audit_start"],
        )
    ]


def new_audit_entries(env: dict[str, Any]) -> list[Any]:
    return rows(
        env,
        "SELECT * FROM audit_log WHERE id > :start ORDER BY id",
        start=env["audit_start"],
    )


def test_successful_upload(env: dict[str, Any]) -> None:
    response = upload(env)
    assert response.status_code == 201
    body = response.json()
    sha = hashlib.sha256(PDF).hexdigest()
    assert body["sha256"] == sha
    assert body["size_bytes"] == len(PDF)
    assert body["queued"] is True

    key = f"{env['case_id']}/{sha}/fir101.pdf"
    assert env["store"].objects[key] == PDF
    assert env["queued"] == [body["id"]]

    document = rows(
        env,
        "SELECT sha256, storage_uri, uploaded_by, content_type, original_filename, size_bytes "
        "FROM document",
    )[0]
    assert document.sha256 == sha
    assert document.uploaded_by == "alice"
    assert document.content_type == "application/pdf"
    assert document.original_filename == "fir101.pdf"
    assert document.size_bytes == len(PDF)

    provenance = rows(
        env,
        "SELECT action, input_hash, output_hash FROM provenance_event",
    )[0]
    assert (provenance.action, provenance.input_hash, provenance.output_hash) == (
        "UPLOAD",
        sha,
        sha,
    )
    assert audit_actions(env) == ["UPLOAD"]


def test_duplicate_is_rejected_but_recorded(env: dict[str, Any]) -> None:
    first = upload(env).json()
    second = upload(env, filename="renamed.pdf")
    assert second.status_code == 409
    assert second.json()["detail"]["existing_document_id"] == first["id"]

    assert len(env["store"].objects) == 1
    assert len(rows(env, "SELECT 1 FROM document")) == 1
    actions = [row.action for row in rows(env, "SELECT action FROM provenance_event ORDER BY id")]
    assert actions == ["UPLOAD", "UPLOAD_DUPLICATE_REJECTED"]
    assert audit_actions(env) == ["UPLOAD", "UPLOAD_DUPLICATE_REJECTED"]
    assert len(env["queued"]) == 1


def test_same_file_is_allowed_in_a_different_case(env: dict[str, Any]) -> None:
    upload(env)
    other_case = (
        env["conn"]
        .execute(
            text(
                "INSERT INTO investigation_case (title, created_by) VALUES ('t2', 't') RETURNING id"
            )
        )
        .scalar()
    )
    env["conn"].execute(
        text(
            "INSERT INTO case_member (case_id, user_id, role) "
            "VALUES (:case_id, 'alice', 'investigator')"
        ),
        {"case_id": other_case},
    )
    response = env["client"].post(
        f"/cases/{other_case}/documents",
        files={"file": ("fir101.pdf", PDF, "application/pdf")},
        headers=env["headers"],
    )
    assert response.status_code == 201


def test_malware_is_rejected_and_not_stored(env: dict[str, Any]) -> None:
    env["scanner"].verdict = "Test.Signature"
    response = upload(env)
    assert response.status_code == 422
    assert response.json()["detail"] == "File failed malware scan"
    assert env["store"].objects == {}
    assert rows(env, "SELECT 1 FROM document") == []
    assert env["queued"] == []
    assert audit_actions(env) == ["UPLOAD_REJECTED_MALWARE"]


def test_scanner_down_fails_closed(env: dict[str, Any]) -> None:
    env["scanner"].down = True
    response = upload(env)
    assert response.status_code == 503
    assert env["store"].objects == {}
    assert rows(env, "SELECT 1 FROM document") == []


def test_storage_down_stores_nothing_in_database(env: dict[str, Any]) -> None:
    env["store"].fail = True
    response = upload(env)
    assert response.status_code == 503
    assert rows(env, "SELECT 1 FROM document") == []
    assert env["queued"] == []


@pytest.mark.parametrize(
    ("content", "filename"),
    [
        (b"MZ\x90\x00 pretend exe", "report.pdf"),
        (b"\x89PNG\r\n\x1a\n" + b"0" * 50, "scan.pdf"),
        (PDF, "report.exe"),
        (b"", "empty.pdf"),
    ],
)
def test_wrong_type_is_415(env: dict[str, Any], content: bytes, filename: str) -> None:
    response = upload(env, content, filename)
    assert response.status_code == 415
    assert env["store"].objects == {}


def test_too_large_is_413(env: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "max_upload_bytes", 100)
    response = upload(env)
    assert response.status_code == 413
    assert env["store"].objects == {}
    assert rows(env, "SELECT 1 FROM document") == []


def test_path_traversal_in_filename_is_neutralized(env: dict[str, Any]) -> None:
    response = upload(env, filename="../../etc/passwd.pdf")
    assert response.status_code == 201
    key = next(iter(env["store"].objects))
    assert ".." not in key
    assert key.endswith("/passwd.pdf")


def test_non_member_gets_404_and_nothing_is_stored(env: dict[str, Any]) -> None:
    response = upload(env, headers=auth(make_token(["investigator"], sub="mallory")))
    assert response.status_code == 404
    assert env["store"].objects == {}


def test_auditor_cannot_upload(env: dict[str, Any]) -> None:
    response = upload(env, headers=auth(make_token(["auditor"], sub="alice")))
    assert response.status_code == 403


def test_unknown_case_is_404(env: dict[str, Any]) -> None:
    response = env["client"].post(
        f"/cases/{uuid.uuid4()}/documents",
        files={"file": ("a.pdf", PDF, "application/pdf")},
        headers=env["headers"],
    )
    assert response.status_code == 404


def test_audit_entries_form_a_hash_chain(env: dict[str, Any]) -> None:
    upload(env)
    upload(env, content=PDF + b"different", filename="second.pdf")
    entries = new_audit_entries(env)
    assert len(entries) == 4
    assert entries[0].prev_hash == env["audit_last_hash"]
    for earlier, later in itertools.pairwise(entries):
        assert later.prev_hash == earlier.entry_hash
    for entry in entries:
        assert entry.entry_hash == compute_entry_hash(
            entry.prev_hash,
            entry.user_id,
            entry.action,
            entry.resource,
            entry.ip,
            entry.ts,
        )


def test_authenticated_refused_requests_are_audited(env: dict[str, Any]) -> None:
    wrong_type = upload(env, b"MZ not a PDF", "bad.pdf")
    non_member = upload(env, headers=auth(make_token(["investigator"], sub="mallory")))

    assert wrong_type.status_code == 415
    assert non_member.status_code == 404
    entries = new_audit_entries(env)
    assert [(row.user_id, row.action) for row in entries] == [
        ("alice", "API_POST"),
        ("mallory", "API_POST"),
    ]
    assert all(row.resource == f"/cases/{env['case_id']}/documents" for row in entries)


def test_queue_failure_does_not_lose_the_upload(env: dict[str, Any]) -> None:
    app.dependency_overrides[get_enqueue] = lambda: lambda _document_id: False
    response = upload(env)
    assert response.status_code == 201
    assert response.json()["queued"] is False
    assert len(rows(env, "SELECT 1 FROM document")) == 1


def test_end_to_end_with_real_clamav(env: dict[str, Any]) -> None:
    """Scan a clean and an EICAR sample through the upload route when ClamAV is available."""
    from app.scanner import ClamAVScanner
    from tests.test_scanner import EICAR

    scanner = ClamAVScanner(settings.clamav_host, settings.clamav_port, timeout=10)
    try:
        scanner.scan([b"ping"])
    except ScannerUnavailable:
        pytest.skip("ClamAV not reachable")
    app.dependency_overrides[get_scanner] = lambda: scanner

    assert upload(env).status_code == 201
    infected_pdf = (
        b"%PDF-1.7\n1 0 obj\n<< /Length "
        + str(len(EICAR)).encode()
        + b" >>\nstream\n"
        + EICAR
        + b"\nendstream\nendobj\n%%EOF\n"
    )
    infected = upload(env, content=infected_pdf, filename="infected.pdf")
    assert infected.status_code == 422
    assert len(env["store"].objects) == 1
