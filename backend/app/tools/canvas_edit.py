"""确认后由服务端固定画布快照；Agent只能提供修改描述。"""

from copy import deepcopy

from fastapi import HTTPException
from sqlalchemy import func, select

from app.edits.canvas_edit import NAME, CanvasEditParams, bounds
from app.models import RunStatus, ToolRun
from app.models.edit_session import SessionAsset
from app.providers.base import ProviderError
from app.providers.reference_generation import configured
from app.queue import QueueUnavailable, enqueue
from app.schemas.generation import RunOut
from app.services import runs, sessions
from app.services.layer_documents import keys_for_document
from app.tools.base import ToolContext, ToolSpec


async def edit_image(context: ToolContext, params):
    assert isinstance(params, CanvasEditParams)
    try:
        configured(context.settings)
    except ProviderError as exc:
        raise HTTPException(503, str(exc)) from None
    row = context.record
    try:
        target = bounds(row.document)
    except ProviderError as exc:
        raise HTTPException(422, str(exc)) from None
    active = await context.db.scalar(
        select(ToolRun)
        .where(
            ToolRun.user_id == context.user_id,
            ToolRun.tool == "edit_image",
            ToolRun.params["session_id"].astext == str(row.id),
            ToolRun.status.in_([RunStatus.QUEUED, RunStatus.RUNNING]),
        )
        .order_by(ToolRun.created_at.desc())
        .limit(1)
    )
    if active is not None:
        if (
            active.params["revision"] != row.revision
            or active.params["request"] != params.model_dump()
        ):
            raise HTTPException(409, "本会话已有整图编辑任务，请先核对原任务，不重复提交")
        run = active
    else:
        count = await context.db.scalar(
            select(func.count()).select_from(SessionAsset).where(SessionAsset.session_id == row.id)
        )
        if count >= sessions.WALL_LIMIT:
            raise HTTPException(422, "会话候选已满，请新建会话后再编辑")
        await keys_for_document(context.db, context.user_id, row.document)
        run = await runs.create(
            context.db,
            context.user_id,
            {
                "provider": NAME,
                "model": context.settings.reference_image_model,
                "session_id": str(row.id),
                "revision": row.revision,
                "document": deepcopy(row.document),
                "target": target,
                "request": params.model_dump(),
            },
            tool="edit_image",
            commit=False,
        )
        run.result = {
            "source_revision": row.revision,
            "asset_ids": [],
            "is_mock": False,
            "model": context.settings.reference_image_model,
            "submission_started": False,
        }
    if context.commit:
        await context.db.commit()
        try:
            await enqueue(context.settings, run.id)
        except QueueUnavailable:
            await runs.submission_uncertain(context.db, run.id)
            raise HTTPException(
                503, {"message": "整图编辑投递未确认，请按原任务编号查询", "run_id": str(run.id)}
            ) from None
    return {"status": run.status.value, "run": RunOut.of(run), "session": None}


SPECS = (
    ToolSpec(
        "edit_image",
        "AI整图编辑（生成候选）",
        "按照prompt修改当前已保存画布的内容、颜色、风格或图中文字。服务端自动合成当前可见图层作为参考图，不需要素材编号。"
        "宽高均需512至2048像素，本阶段需要不透明画布；输出尺寸按最接近的16像素对齐。"
        "使用百炼千问付费模型，每次生成一张独立候选，可能重建细节；不自动采用、不修改原文件或图层。"
        "精确限定选区时使用erase_region/replace_region；新建无关画面用generate_image；只调整已有可编辑文字层或位置时用edit_layer。",
        CanvasEditParams,
        edit_image,
        queued=True,
    ),
)
