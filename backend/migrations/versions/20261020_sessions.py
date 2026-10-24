"""第四章会话、图片墙与画布历史；仅新增表。"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from alembic import op

revision = "20261020_sessions"
down_revision = "20261020_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "edit_sessions",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("user_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(80), nullable=False),
        sa.Column("original_asset_id", sa.UUID(), sa.ForeignKey("assets.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("current_asset_id", sa.UUID(), sa.ForeignKey("assets.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("history_seq", sa.Integer(), nullable=False),
        sa.Column("document", JSONB(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("revision > 0 AND history_seq > 0", name="ck_sessions_version"),
    )
    op.create_index("ix_edit_sessions_user_id", "edit_sessions", ["user_id"])
    op.create_table(
        "session_assets",
        sa.Column("session_id", sa.UUID(), sa.ForeignKey("edit_sessions.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("asset_id", sa.UUID(), sa.ForeignKey("assets.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.UniqueConstraint("session_id", "position", name="uq_session_asset_position"),
        sa.CheckConstraint("position > 0", name="ck_session_asset_position"),
    )
    op.create_table(
        "edit_history",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("session_id", sa.UUID(), sa.ForeignKey("edit_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(48), nullable=False),
        sa.Column("current_asset_id", sa.UUID(), sa.ForeignKey("assets.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("document", JSONB(), nullable=False),
        sa.UniqueConstraint("session_id", "seq", name="uq_edit_history_seq"),
        sa.CheckConstraint("seq > 0", name="ck_edit_history_seq"),
    )
    op.create_index("ix_edit_history_session_id", "edit_history", ["session_id"])


def downgrade() -> None:
    op.drop_table("edit_history")
    op.drop_table("session_assets")
    op.drop_table("edit_sessions")
