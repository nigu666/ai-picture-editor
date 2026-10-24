"""固定扩图输入快照；同一会话先完成或恢复原任务再提交。"""

from copy import deepcopy

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import func, or_, select

from app.edits.outpainting import ExpansionParams, bounds
from app.models import RunStatus, ToolRun
from app.models.edit_session import SessionAsset
from app.providers.base import ProviderError
from app.providers.outpainting import NAME, configured
from app.queue import QueueUnavailable, enqueue
from app.schemas.generation import RunOut
from app.services import runs, sessions
from app.services.layer_documents import keys_for_document
from app.tools.base import ToolContext, ToolSpec


async def expand_canvas(context: ToolContext, params: BaseModel):
    assert isinstance(params, ExpansionParams)
    try:
        configured(context.settings)
    except ProviderError as exc:
        raise HTTPException(503, str(exc)) from None
    row = context.record
    try:
        target = bounds(row.document["width"], row.document["height"], params.ratio)
    except ProviderError as exc:
        raise HTTPException(422, str(exc)) from None
    run = await context.db.scalar(
        select(ToolRun)
        .where(
            ToolRun.user_id == context.user_id,
            ToolRun.tool == "expand_canvas",
            ToolRun.params["session_id"].astext == str(row.id),
            or_(
                ToolRun.status.in_([RunStatus.QUEUED, RunStatus.RUNNING]),
                (ToolRun.status == RunStatus.FAILED)
                & ToolRun.result["recoverable"].as_boolean().is_(True),
            ),
        )
        .order_by(ToolRun.created_at.desc())
        .limit(1)
    )
    if run is not None and run.status == RunStatus.FAILED:
        raise HTTPException(409, "此会话有可恢复的扩图任务，请点击继续查询原任务，避免重复生成")
    if run is not None and (
        run.params["revision"] != row.revision or run.params["request"] != params.model_dump()
    ):
        raise HTTPException(409, "此会话已有扩图任务处理中，请先核对原任务")
    if run is None:
        count = await context.db.scalar(
            select(func.count()).select_from(SessionAsset).where(SessionAsset.session_id == row.id)
        )
        if count >= sessions.WALL_LIMIT:
            raise HTTPException(422, "会话候选已满，请新建会话后再扩图")
        await keys_for_document(context.db, context.user_id, row.document)
        run = await runs.create(
            context.db,
            context.user_id,
            {
                "provider": NAME,
                "model": context.settings.outpainting_model,
                "session_id": str(row.id),
                "revision": row.revision,
                "asset_id": str(row.current_asset_id),
                "document": deepcopy(row.document),
                "target": target,
                "request": params.model_dump(),
            },
            tool="expand_canvas",
            commit=False,
        )
        run.result = {
            "source_revision": row.revision,
            "asset_ids": [],
            "is_mock": False,
            "recoverable": False,
            "query_attempt": 0,
        }
    if context.commit:
        await context.db.commit()
        try:
            await enqueue(context.settings, run.id, attempt=run.result.get("query_attempt", 0))
        except QueueUnavailable:
            await runs.submission_uncertain(context.db, run.id)
            raise HTTPException(
                503, {"message": "扩图投递未确认，请刷新任务核对", "run_id": str(run.id)}
            ) from None
    return {"status": run.status.value, "run": RunOut.of(run), "session": None}


SPECS = (
    ToolSpec(
        "expand_canvas",
        "AI扩图补全边缘",
        "将已保存画布的可见图层合成整图后居中扩展到ratio比例，原画面不裁切不缩放。当前画布每边须512至4096像素、"
        "不含透明区域，目标每边不超过4096。调用百炼付费扩图模型补全四周，只有一张候选，需用户采用，"
        "采用前不改变画布，采用后可撤销。不是超分，也不是透明留白扩边。",
        ExpansionParams,
        expand_canvas,
        queued=True,
    ),
)
