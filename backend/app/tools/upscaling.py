"""固定超分输入快照；同一会话先完成或恢复原任务再提交。"""

from copy import deepcopy

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import func, or_, select

from app.edits.upscaling import UpscaleParams, bounds
from app.models import RunStatus, ToolRun
from app.models.edit_session import SessionAsset
from app.providers.base import ProviderError
from app.providers.upscaling import NAME, configured
from app.queue import QueueUnavailable, enqueue
from app.schemas.generation import RunOut
from app.services import runs, sessions
from app.services.layer_documents import keys_for_document
from app.tools.base import ToolContext, ToolSpec


async def upscale_image(context: ToolContext, params: BaseModel):
    assert isinstance(params, UpscaleParams)
    try:
        configured(context.settings)
    except ProviderError as exc:
        raise HTTPException(503, str(exc)) from None
    row = context.record
    try:
        target = bounds(row.document["width"], row.document["height"], params.scale)
    except ProviderError as exc:
        raise HTTPException(422, str(exc)) from None
    run = await context.db.scalar(
        select(ToolRun)
        .where(
            ToolRun.user_id == context.user_id,
            ToolRun.tool == "upscale_image",
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
        raise HTTPException(409, "此会话有可恢复的超分任务，请点击继续查询原任务，避免重复生成")
    if run is not None and (
        run.params["revision"] != row.revision or run.params["request"] != params.model_dump()
    ):
        raise HTTPException(409, "此会话已有超分任务处理中，请先核对原任务")
    if run is None:
        count = await context.db.scalar(
            select(func.count()).select_from(SessionAsset).where(SessionAsset.session_id == row.id)
        )
        if count >= sessions.WALL_LIMIT:
            raise HTTPException(422, "会话候选已满，请新建会话后再超分")
        await keys_for_document(context.db, context.user_id, row.document)
        run = await runs.create(
            context.db,
            context.user_id,
            {
                "provider": NAME,
                "model": context.settings.upscaling_model,
                "session_id": str(row.id),
                "revision": row.revision,
                "asset_id": str(row.current_asset_id),
                "document": deepcopy(row.document),
                "target": target,
                "request": params.model_dump(),
            },
            tool="upscale_image",
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
                503, {"message": "超分投递未确认，请刷新任务核对", "run_id": str(run.id)}
            ) from None
    return {"status": run.status.value, "run": RunOut.of(run), "session": None}


SPECS = (
    ToolSpec(
        "upscale_image",
        "AI图像超分",
        "将当前已保存画布以scale=2或4进行AI超分，保持构图并增强细节。"
        "每边至少512像素，目标每边不超过4096，仅支持不透明画布。"
        "调用百炼付费模型生成一张候选，用户采用后才能改变画布，可撤销。不要用于扩图或修改内容。",
        UpscaleParams,
        upscale_image,
        queued=True,
    ),
)
