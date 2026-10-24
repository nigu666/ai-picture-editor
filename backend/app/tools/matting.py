"""服务端固定输入快照；排队返回编号，任务完成后才出现可采用的透明候选。"""

from copy import deepcopy

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.models import RunStatus, ToolRun
from app.queue import QueueUnavailable, enqueue
from app.schemas.generation import RunOut
from app.services import runs, sessions
from app.services.layer_documents import keys_for_document
from app.services.matting import MattingUnavailable, verify_model
from app.tools.base import ToolContext, ToolSpec
from app.tools.builtin import EmptyParams


async def remove_background(context: ToolContext, _: BaseModel) -> dict:
    try:
        verify_model(context.settings.matting_model_path)
    except MattingUnavailable as exc:
        raise HTTPException(503, str(exc)) from None
    row = context.record
    # 上游持有会话行锁；同一会话同时只允许一个抠图任务，重复点击复用编号。
    run = await context.db.scalar(
        select(ToolRun)
        .where(
            ToolRun.user_id == context.user_id,
            ToolRun.tool == "remove_background",
            ToolRun.params["session_id"].astext == str(row.id),
            ToolRun.status.in_([RunStatus.QUEUED, RunStatus.RUNNING]),
        )
        .order_by(ToolRun.created_at.desc())
        .limit(1)
    )
    if run is not None and (
        run.params["revision"] != row.revision or run.params["document"] != row.document
    ):
        raise HTTPException(409, "此会话仍有先前画布的去背景任务，请先核对原任务")
    if run is None:
        await keys_for_document(context.db, context.user_id, row.document)
        run = await runs.create(
            context.db,
            context.user_id,
            {
                "provider": "rembg-u2netp",
                "session_id": str(row.id),
                "revision": row.revision,
                "asset_id": str(row.current_asset_id),
                "document": deepcopy(row.document),
            },
            tool="remove_background",
            commit=False,
        )
        run.result = {"source_revision": row.revision, "asset_ids": []}
    if context.commit:
        await context.db.commit()
        try:
            await enqueue(context.settings, run.id)
        except QueueUnavailable:
            await runs.submission_uncertain(context.db, run.id)
            raise HTTPException(
                503, {"message": "投递未确认，请刷新去背景任务核对", "run_id": str(run.id)}
            ) from None
    return {"status": run.status.value, "run": RunOut.of(run), "session": None}


SPECS = (
    ToolSpec(
        "remove_background",
        "去背景",
        "使用本地 u2netp 模型去除当前已保存画布的背景，生成透明 PNG 候选，不自动采用。"
        "保留已保存的调色、旋转、翻转和裁剪。主体边缘效果需用户检查。无需云端密钥。",
        EmptyParams,
        remove_background,
        queued=True,
    ),
)
