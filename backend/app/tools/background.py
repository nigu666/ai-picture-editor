"""换背景提交只固定快照并排队，所有结果均需用户采用。"""

from copy import deepcopy

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select

from app.models import RunStatus, ToolRun
from app.models.edit_session import SessionAsset
from app.providers.background import configured, provider_name
from app.providers.base import ProviderError
from app.queue import QueueUnavailable, enqueue
from app.schemas.generation import RunOut
from app.services import runs, sessions
from app.services.layer_documents import keys_for_document
from app.services.matting import MattingUnavailable, verify_model
from app.tools.base import ToolContext, ToolSpec


class BackgroundParams(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    prompt: str = Field(min_length=1, max_length=800)
    count: int = Field(default=1, strict=True)

    @field_validator("count")
    @classmethod
    def count_choice(cls, value):
        if value not in {1, 2, 4}:
            raise ValueError("候选数量仅支持1、2或4张")
        return value


async def replace_background(context: ToolContext, params: BaseModel) -> dict:
    assert isinstance(params, BackgroundParams)
    try:
        configured(context.settings)
        verify_model(context.settings.matting_model_path)
    except (ProviderError, MattingUnavailable) as exc:
        raise HTTPException(503, str(exc)) from None
    row = context.record
    run = await context.db.scalar(
        select(ToolRun)
        .where(
            ToolRun.user_id == context.user_id,
            ToolRun.tool == "replace_background",
            ToolRun.params["session_id"].astext == str(row.id),
            ToolRun.status.in_([RunStatus.QUEUED, RunStatus.RUNNING]),
        )
        .order_by(ToolRun.created_at.desc())
        .limit(1)
    )
    if run is not None and (
        run.params["revision"] != row.revision
        or run.params["request"] != params.model_dump()
        or run.params["provider"] != provider_name(context.settings)
    ):
        raise HTTPException(409, "此会话已有换背景任务处理中，请先核对任务，完成后再提交新描述")
    if run is None:
        wall_size = await context.db.scalar(
            select(func.count()).select_from(SessionAsset).where(SessionAsset.session_id == row.id)
        )
        if wall_size + params.count > sessions.WALL_LIMIT:
            raise HTTPException(422, "会话候选空间不足，请新建会话后再生成背景")
        await keys_for_document(context.db, context.user_id, row.document)
        run = await runs.create(
            context.db,
            context.user_id,
            {
                "provider": provider_name(context.settings),
                "session_id": str(row.id),
                "revision": row.revision,
                "asset_id": str(row.current_asset_id),
                "document": deepcopy(row.document),
                "request": params.model_dump(),
            },
            tool="replace_background",
            commit=False,
        )
        run.result = {"source_revision": row.revision, "asset_ids": [], "is_mock": False}
    if context.commit:
        await context.db.commit()
        try:
            await enqueue(context.settings, run.id)
        except QueueUnavailable:
            await runs.submission_uncertain(context.db, run.id)
            raise HTTPException(
                503, {"message": "投递未确认，请先刷新换背景任务核对", "run_id": str(run.id)}
            ) from None
    return {"status": run.status.value, "run": RunOut.of(run), "session": None}


SPECS = (
    ToolSpec(
        "replace_background",
        "生成新背景并合成主体",
        "按描述生成新背景，再用本地抠图合成当前已保存画布的主体。不是直接图像编辑；"
        "原主体颜色来自已保存画布，边缘取决于抠图效果，不自动重打光。count为1、2或4，"
        "会调用已配置平台的付费生图API，生成结果只进入候选墙，需用户采用，不覆盖当前画布。",
        BackgroundParams,
        replace_background,
        queued=True,
    ),
)
