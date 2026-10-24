"""第四章：画布权威状态、线性历史及独立候选图片墙。"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDBase


class EditSession(UUIDBase):
    __tablename__ = "edit_sessions"
    __table_args__ = (
        CheckConstraint("revision > 0 AND history_seq > 0", name="ck_sessions_version"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(80))
    original_asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assets.id", ondelete="RESTRICT")
    )
    current_asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assets.id", ondelete="RESTRICT")
    )
    revision: Mapped[int] = mapped_column(default=1)
    history_seq: Mapped[int] = mapped_column(default=1)
    document: Mapped[dict] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SessionAsset(Base):
    __tablename__ = "session_assets"
    __table_args__ = (
        UniqueConstraint("session_id", "position", name="uq_session_asset_position"),
        CheckConstraint("position > 0", name="ck_session_asset_position"),
    )

    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("edit_sessions.id", ondelete="CASCADE"), primary_key=True
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assets.id", ondelete="RESTRICT"), primary_key=True
    )
    position: Mapped[int]


class EditHistory(UUIDBase):
    __tablename__ = "edit_history"
    __table_args__ = (
        UniqueConstraint("session_id", "seq", name="uq_edit_history_seq"),
        CheckConstraint("seq > 0", name="ck_edit_history_seq"),
    )

    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("edit_sessions.id", ondelete="CASCADE"), index=True
    )
    seq: Mapped[int]
    action: Mapped[str] = mapped_column(String(48))
    current_asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assets.id", ondelete="RESTRICT")
    )
    document: Mapped[dict] = mapped_column(JSONB)
