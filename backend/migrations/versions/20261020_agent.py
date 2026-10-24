"""第五章：持久化指令和确认计划。"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20261020_agent"
down_revision = "20261020_sessions"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "agent_turns",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "user_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "session_id",
            sa.UUID(),
            sa.ForeignKey("edit_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("request_id", sa.UUID(), nullable=False),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("expected_revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("planner_source", sa.String(64), nullable=False),
        sa.Column("steps", JSONB(), nullable=False),
        sa.Column("planning_deadline", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("session_id", "request_id", name="uq_agent_request"),
        sa.CheckConstraint("revision > 0 AND expected_revision > 0", name="ck_agent_revision"),
        sa.CheckConstraint(
            "status IN ('planning', 'pending', 'running', 'succeeded', 'failed', "
            "'stale', 'cancelled', 'clarification')",
            name="ck_agent_status",
        ),
    )
    op.create_index("ix_agent_turns_user_id", "agent_turns", ["user_id"])
    op.create_index("ix_agent_turns_session_id", "agent_turns", ["session_id"])


def downgrade():
    op.drop_table("agent_turns")
