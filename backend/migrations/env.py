"""受控迁移入口：当前阶段必须由调用者显式传入目标连接。"""

from alembic import context
from app.models import Base

connection = context.config.attributes.get("connection")
if connection is None:
    raise RuntimeError("请通过受控迁移入口显式提供连接；本阶段不自动迁移业务库")

context.configure(connection=connection, target_metadata=Base.metadata)
with context.begin_transaction():
    context.run_migrations()
