"""保存生成任务状态；不引入尚未实现的编辑会话外键。"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from alembic import op

revision = "20261020_runs"
down_revision = "20261019_assets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tool_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("tool", sa.String(48), nullable=False),
        sa.Column("status", sa.String(9), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("stage", sa.String(64), nullable=False),
        sa.Column("params", JSONB(), nullable=False),
        sa.Column("result", JSONB(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.CheckConstraint("progress BETWEEN 0 AND 100", name="ck_runs_progress"),
        sa.CheckConstraint("status IN ('queued', 'running', 'succeeded', 'failed')", name="run_status"),
    )
    op.create_index("ix_tool_runs_user_id", "tool_runs", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_tool_runs_user_id", table_name="tool_runs")
    op.drop_table("tool_runs")
