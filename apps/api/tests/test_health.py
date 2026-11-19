from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from app.db import get_db
from app.main import app

client = TestClient(app)


def test_health_is_a_liveness_check() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "0.1.0"}


def test_health_allows_vite_loopback_origin() -> None:
    response = client.get(
        "/health",
        headers={"Origin": "http://127.0.0.1:5173"},
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"


def test_database_health_returns_503_when_query_fails() -> None:
    class UnavailableSession:
        def execute(self, statement: object) -> None:
            raise SQLAlchemyError("database unavailable")

    def get_unavailable_session():
        yield UnavailableSession()

    app.dependency_overrides[get_db] = get_unavailable_session
    try:
        response = client.get("/health/db")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}
