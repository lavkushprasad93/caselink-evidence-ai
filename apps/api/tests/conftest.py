from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import OperationalError

from app.config import settings


@pytest.fixture
def conn() -> Iterator[Connection]:
    engine = create_engine(settings.database_url, connect_args={"connect_timeout": 2})
    try:
        connection = engine.connect()
    except OperationalError:
        engine.dispose()
        pytest.skip("PostgreSQL not reachable")

    transaction = connection.begin()
    try:
        yield connection
    finally:
        transaction.rollback()
        connection.close()
        engine.dispose()


def _require_table(connection: Connection, table_name: str) -> None:
    name = connection.execute(
        text("SELECT to_regclass(:table_name)"),
        {"table_name": f"public.{table_name}"},
    ).scalar()
    if name is None:
        pytest.skip(f"Run `alembic upgrade head` before testing {table_name}")


@pytest.fixture
def schema_conn(conn: Connection) -> Iterator[Connection]:
    _require_table(conn, "entity")
    yield conn


@pytest.fixture
def auth_conn(conn: Connection) -> Iterator[Connection]:
    _require_table(conn, "case_member")
    yield conn


@pytest.fixture
def upload_conn(conn: Connection) -> Iterator[Connection]:
    _require_table(conn, "case_member")
    column_count = conn.execute(text("""
            SELECT count(*)
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'document'
              AND column_name IN ('original_filename', 'size_bytes', 'content_type')
            """)).scalar_one()
    if column_count != 3:
        pytest.skip("Run `alembic upgrade head` before testing document uploads")
    yield conn
