from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session


def record_provenance(
    db: Session,
    object_type: str,
    object_id: UUID | str | None,
    action: str,
    actor: str,
    tool: str,
    tool_version: str,
    input_hash: str | None,
    output_hash: str | None,
) -> None:
    db.execute(
        text("""
            INSERT INTO provenance_event
              (object_type, object_id, action, actor, tool, tool_version, input_hash, output_hash)
            VALUES
              (:object_type, :object_id, :action, :actor, :tool, :tool_version,
               :input_hash, :output_hash)
            """),
        {
            "object_type": object_type,
            "object_id": object_id,
            "action": action,
            "actor": actor,
            "tool": tool,
            "tool_version": tool_version,
            "input_hash": input_hash,
            "output_hash": output_hash,
        },
    )
