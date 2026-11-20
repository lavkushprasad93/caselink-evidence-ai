"""core schema: case, document, page, span, entity, mention, provenance, audit

Revision ID: 0001
Revises:
Create Date: 2026-11-20

Note: "case" is a reserved SQL word, so the table is named investigation_case.
Strong identifiers (UPI, phone, account, URL, vehicle) are unique per type so one
value always maps to one entity. Names and places are not unique on purpose.

Later phases add event, claim, link, link_evidence, contradiction, hypothesis,
hypothesis_evidence, hypothesis_gap, mo_cluster and embedding, each in its own migration.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.execute("""
        CREATE TABLE investigation_case (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          title text NOT NULL,
          status text NOT NULL DEFAULT 'open',
          created_by text NOT NULL,
          created_at timestamptz NOT NULL DEFAULT now()
        )
        """)

    op.execute("""
        CREATE TABLE document (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          case_id uuid REFERENCES investigation_case(id),
          fir_no text,
          doc_type text,
          language text,
          sha256 char(64) NOT NULL,
          storage_uri text NOT NULL,
          uploaded_by text NOT NULL,
          uploaded_at timestamptz NOT NULL DEFAULT now()
        )
        """)

    op.execute("""
        CREATE TABLE page (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          document_id uuid NOT NULL REFERENCES document(id),
          page_no int NOT NULL,
          image_uri text,
          ocr_confidence real,
          UNIQUE (document_id, page_no)
        )
        """)

    op.execute("""
        CREATE TABLE span (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          document_id uuid NOT NULL REFERENCES document(id),
          page_id uuid REFERENCES page(id),
          text text NOT NULL,
          char_start int,
          char_end int,
          bbox jsonb,
          language text
        )
        """)

    op.execute("""
        CREATE TABLE entity (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          type text NOT NULL,
          canonical_value text,
          normalized_value text NOT NULL
        )
        """)
    op.execute("""
        CREATE UNIQUE INDEX ux_entity_strong ON entity(type, normalized_value)
          WHERE type IN ('UPI','PHONE','ACCOUNT','URL','VEHICLE')
        """)

    op.execute("""
        CREATE TABLE mention (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          entity_id uuid REFERENCES entity(id),
          span_id uuid NOT NULL REFERENCES span(id),
          raw_text text NOT NULL,
          confidence real,
          extractor text,
          extractor_version text,
          verification_status text NOT NULL DEFAULT 'unverified'
        )
        """)

    op.execute("""
        CREATE TABLE provenance_event (
          id bigserial PRIMARY KEY,
          object_type text,
          object_id uuid,
          action text,
          actor text,
          tool text,
          tool_version text,
          input_hash text,
          output_hash text,
          ts timestamptz NOT NULL DEFAULT now()
        )
        """)

    op.execute("""
        CREATE TABLE audit_log (
          id bigserial PRIMARY KEY,
          user_id text,
          action text,
          resource text,
          ip text,
          ts timestamptz NOT NULL DEFAULT now(),
          prev_hash text,
          entry_hash text NOT NULL
        )
        """)


def downgrade() -> None:
    for table in (
        "audit_log",
        "provenance_event",
        "mention",
        "entity",
        "span",
        "page",
        "document",
        "investigation_case",
    ):
        op.execute(f"DROP TABLE IF EXISTS {table}")
    # Extensions are left installed: other databases objects or migrations may rely on them.
