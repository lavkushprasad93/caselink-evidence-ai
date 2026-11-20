"""document: filename/size/type columns and one-copy-per-case rule

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-20
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE document
          ADD COLUMN original_filename text,
          ADD COLUMN size_bytes bigint,
          ADD COLUMN content_type text
        """)
    op.execute("CREATE UNIQUE INDEX ux_document_case_sha256 ON document(case_id, sha256)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ux_document_case_sha256")
    op.execute("""
        ALTER TABLE document
          DROP COLUMN IF EXISTS original_filename,
          DROP COLUMN IF EXISTS size_bytes,
          DROP COLUMN IF EXISTS content_type
        """)
