from uuid import UUID

from sqlalchemy import ForeignKey, Index, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class CaseMember(Base):
    __tablename__ = "case_member"
    __table_args__ = (Index("ix_case_member_user", "user_id"),)

    case_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("investigation_case.id"),
        primary_key=True,
    )
    user_id: Mapped[str] = mapped_column(Text, primary_key=True)
    role: Mapped[str] = mapped_column(Text, nullable=False)
