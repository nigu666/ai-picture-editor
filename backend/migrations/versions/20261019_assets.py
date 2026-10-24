"""素材记录：对象 Key、元信息与用户外键。"""

import sqlalchemy as sa
from alembic import op

revision = "20261019_assets"
down_revision = "20261019_users"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "assets",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "original",
                "generated",
                "subject",
                "background",
                "mask",
                "marketing",
                "export",
                name="asset_kind",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "source",
            sa.Enum(
                "upload",
                "generate",
                "tool",
                name="asset_source",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("storage_key", sa.String(255), nullable=False),
        sa.Column("image_format", sa.String(8), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("has_alpha", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("storage_key"),
        sa.CheckConstraint("width > 0 AND height > 0", name="ck_assets_dimensions"),
        sa.CheckConstraint("size_bytes > 0", name="ck_assets_size"),
    )
    op.create_index("ix_assets_user_id", "assets", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_assets_user_id", table_name="assets")
    op.drop_table("assets")
