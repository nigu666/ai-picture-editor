"""一条指令及其已校验计划；状态和实际副作用由同一事务保存。"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import UUIDBase

STATES = (
    "planning",
    "pending",
    "running",
    "succeeded",
    "failed",
    "stale",
    "cancelled",
    "clarification",
)


class AgentTurn(UUIDBase):
    __tablename__ = "agent_turns"
    __table_args__ = (
        UniqueConstraint("session_id", "request_id", name="uq_agent_request"),
        CheckConstraint("revision > 0 AND expected_revision > 0", name="ck_agent_revision"),
        CheckConstraint("status IN " + str(STATES), name="ck_agent_status"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("edit_sessions.id", ondelete="CASCADE"), index=True
    )
    request_id: Mapped[uuid.UUID]
    goal: Mapped[str] = mapped_column(Text)
    revision: Mapped[int]
    expected_revision: Mapped[int]
    status: Mapped[str] = mapped_column(String(24))
    message: Mapped[str] = mapped_column(Text)
    analysis: Mapped[str] = mapped_column(Text, default="", server_default="")
    planner_source: Mapped[str] = mapped_column(String(64), default="")
    steps: Mapped[list] = mapped_column(JSONB, default=list)
    planning_deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True))
