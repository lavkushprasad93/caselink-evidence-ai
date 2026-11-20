"""Protect audit and provenance tables from row changes and truncation.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-20
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("audit_log", "provenance_event")


def upgrade() -> None:
    op.execute("""
        CREATE FUNCTION caselink_forbid_append_only_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION '% on % is not allowed because this table is append-only',
            TG_OP, TG_TABLE_NAME USING ERRCODE = 'insufficient_privilege';
        END;
        $$
        """)
    for table in TABLES:
        op.execute(f"""
            CREATE TRIGGER {table}_no_update_delete
              BEFORE UPDATE OR DELETE ON {table}
              FOR EACH ROW EXECUTE FUNCTION caselink_forbid_append_only_mutation()
            """)
        op.execute(f"""
            CREATE TRIGGER {table}_no_truncate
              BEFORE TRUNCATE ON {table}
              FOR EACH STATEMENT EXECUTE FUNCTION caselink_forbid_append_only_mutation()
            """)


def downgrade() -> None:
    for table in TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_no_truncate ON {table}")
        op.execute(f"DROP TRIGGER IF EXISTS {table}_no_update_delete ON {table}")
    op.execute("DROP FUNCTION IF EXISTS caselink_forbid_append_only_mutation()")
