"""case_member: which user belongs to which case

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-20
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE case_member (
          case_id uuid NOT NULL REFERENCES investigation_case(id),
          user_id text NOT NULL,
          role text NOT NULL,
          PRIMARY KEY (case_id, user_id)
        )
        """)
    op.execute("CREATE INDEX ix_case_member_user ON case_member(user_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS case_member")
