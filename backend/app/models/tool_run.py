"""第3章独立任务记录；画布会话、取消和重试在后续章节接入。"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import UUIDBase


class RunStatus(enum.StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ToolRun(UUIDBase):
    __tablename__ = "tool_runs"
    __table_args__ = (
        CheckConstraint("progress BETWEEN 0 AND 100", name="ck_runs_progress"),
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')", name="run_status"
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    tool: Mapped[str] = mapped_column(String(48))
    status: Mapped[RunStatus] = mapped_column(
        Enum(RunStatus, values_callable=lambda xs: [x.value for x in xs], native_enum=False),
        default=RunStatus.QUEUED,
    )
    progress: Mapped[int] = mapped_column(default=0)
    stage: Mapped[str] = mapped_column(String(64), default="等待执行")
    params: Mapped[dict] = mapped_column(JSONB, default=dict)
    result: Mapped[dict] = mapped_column(JSONB, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
