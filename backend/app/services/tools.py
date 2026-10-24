"""参数格式、资源归属、会话修订检查之后，才调用登记的处理函数。"""

import uuid

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.services import sessions
from app.services.layer_documents import require_tool
from app.storage import ObjectStorage
from app.tools import REGISTRY, UnknownTool
from app.tools.base import ToolContext


async def invoke(
    db: AsyncSession,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    revision: int,
    name: str,
    params: dict,
    settings: Settings,
    store: ObjectStorage,
) -> dict:
    try:
        spec = REGISTRY.get(name)
    except UnknownTool as exc:
        raise HTTPException(404, str(exc)) from None
    try:
        checked = spec.validate(params)
    except ValidationError as exc:
        # 与已有 HTTP 输入校验保持一致；不回显用户输入和异常上下文。
        errors = [
            {key: item[key] for key in ("loc", "msg", "type")}
            for item in exc.errors(include_input=False, include_context=False)
        ]
        raise HTTPException(422, errors) from None
    record = await sessions.load(db, user_id, session_id)
    sessions.check_version(record, revision)
    require_tool(record.document, name)
    result = await spec.handler(ToolContext(db, user_id, record, settings, store), checked)
    return {"tool": spec.name, **result}
