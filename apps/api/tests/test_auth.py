import time
import uuid
from collections.abc import Iterator
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from app.auth.tokens import get_key_resolver
from app.config import settings
from app.db import get_db
from app.main import app

PRIVATE = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_PRIVATE = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def make_token(
    roles: list[str],
    *,
    sub: str = "user-1",
    key: Any = PRIVATE,
    audience: str | None = None,
    issuer: str | None = None,
    exp_in: int = 300,
) -> str:
    claims = {
        "sub": sub,
        "preferred_username": "tester",
        "iss": issuer or settings.keycloak_issuer,
        "aud": audience or settings.keycloak_audience,
        "exp": int(time.time()) + exp_in,
        "realm_access": {"roles": roles},
    }
    return jwt.encode(claims, key, algorithm="RS256")


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class FakeDB:
    def __init__(self, member: object | None) -> None:
        self.member = member

    def scalar(self, _stmt: object) -> object | None:
        return self.member


@pytest.fixture
def client() -> Iterator[TestClient]:
    app.dependency_overrides[get_key_resolver] = lambda: (lambda _token: PRIVATE.public_key())
    yield TestClient(app)
    app.dependency_overrides.clear()


def use_db(db: Any) -> None:
    def _get_db() -> Iterator[Any]:
        yield db

    app.dependency_overrides[get_db] = _get_db


def test_health_needs_no_token(client: TestClient) -> None:
    assert client.get("/health").status_code == 200


def test_missing_token_is_401(client: TestClient) -> None:
    assert client.get("/me").status_code == 401


def test_valid_token_returns_identity(client: TestClient) -> None:
    response = client.get("/me", headers=auth(make_token(["investigator"])))
    assert response.status_code == 200
    assert response.json() == {
        "sub": "user-1",
        "username": "tester",
        "roles": ["investigator"],
    }


def test_expired_token_is_401(client: TestClient) -> None:
    response = client.get("/me", headers=auth(make_token(["investigator"], exp_in=-3600)))
    assert response.status_code == 401


def test_wrong_audience_is_401(client: TestClient) -> None:
    response = client.get("/me", headers=auth(make_token(["investigator"], audience="account")))
    assert response.status_code == 401


def test_wrong_issuer_is_401(client: TestClient) -> None:
    response = client.get(
        "/me",
        headers=auth(make_token(["investigator"], issuer="http://evil/realms/x")),
    )
    assert response.status_code == 401


def test_token_signed_with_another_key_is_401(client: TestClient) -> None:
    response = client.get("/me", headers=auth(make_token(["investigator"], key=OTHER_PRIVATE)))
    assert response.status_code == 401


def test_unsigned_token_is_401(client: TestClient) -> None:
    claims = {
        "sub": "x",
        "iss": settings.keycloak_issuer,
        "aud": settings.keycloak_audience,
        "exp": int(time.time()) + 300,
    }
    token = jwt.encode(claims, None, algorithm="none")
    assert client.get("/me", headers=auth(token)).status_code == 401


def test_garbage_token_is_401(client: TestClient) -> None:
    assert client.get("/me", headers=auth("not-a-jwt")).status_code == 401


@pytest.mark.parametrize("roles", [["auditor"], ["admin"], []])
def test_roles_without_case_access_get_403(client: TestClient, roles: list[str]) -> None:
    use_db(FakeDB(member=object()))
    response = client.get(
        f"/cases/{uuid.uuid4()}/access",
        headers=auth(make_token(roles)),
    )
    assert response.status_code == 403


def test_malformed_role_claim_gets_403(client: TestClient) -> None:
    claims = {
        "sub": "user-1",
        "iss": settings.keycloak_issuer,
        "aud": settings.keycloak_audience,
        "exp": int(time.time()) + 300,
        "realm_access": {"roles": "investigator"},
    }
    token = jwt.encode(claims, PRIVATE, algorithm="RS256")
    response = client.get(
        f"/cases/{uuid.uuid4()}/access",
        headers=auth(token),
    )
    assert response.status_code == 403


def test_non_member_gets_404_not_403(client: TestClient) -> None:
    use_db(FakeDB(member=None))
    response = client.get(
        f"/cases/{uuid.uuid4()}/access",
        headers=auth(make_token(["investigator"])),
    )
    assert response.status_code == 404


@pytest.mark.parametrize("role", ["investigator", "supervisor"])
def test_member_with_role_is_allowed(client: TestClient, role: str) -> None:
    use_db(FakeDB(member=object()))
    case_id = uuid.uuid4()
    response = client.get(
        f"/cases/{case_id}/access",
        headers=auth(make_token([role])),
    )
    assert response.status_code == 200
    assert response.json()["case_id"] == str(case_id)


def test_membership_query_against_real_database(
    client: TestClient,
    auth_conn: Connection,
) -> None:
    case_id = auth_conn.execute(
        text(
            "INSERT INTO investigation_case (title, created_by) "
            "VALUES ('t', 'tester') RETURNING id"
        )
    ).scalar()
    auth_conn.execute(
        text(
            "INSERT INTO case_member (case_id, user_id, role) "
            "VALUES (:c, 'alice', 'investigator')"
        ),
        {"c": case_id},
    )
    use_db(Session(bind=auth_conn))

    allowed = client.get(
        f"/cases/{case_id}/access",
        headers=auth(make_token(["investigator"], sub="alice")),
    )
    denied = client.get(
        f"/cases/{case_id}/access",
        headers=auth(make_token(["investigator"], sub="bob")),
    )
    assert allowed.status_code == 200
    assert denied.status_code == 404
