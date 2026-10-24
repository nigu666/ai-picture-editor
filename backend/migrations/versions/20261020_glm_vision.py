"""模型正式分析与执行状态分开保存；保留已有计划。"""

import sqlalchemy as sa
from alembic import op

revision = "20261020_glm_vision"
down_revision = "20261020_agent"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("agent_turns", sa.Column("analysis", sa.Text(), nullable=False, server_default=""))


def downgrade():
    op.drop_column("agent_turns", "analysis")
