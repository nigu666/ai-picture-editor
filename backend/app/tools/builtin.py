"""只注册当前项目已经实现的四项能力。"""

import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.generation import GenerateIn, GenerateTextIn
from app.services import generation_jobs, sessions
from app.tools.base import ToolContext, ToolSpec


class EmptyParams(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AdoptParams(EmptyParams):
    asset_id: uuid.UUID = Field(description="本会话候选图片墙中要采用的素材 UUID")


async def _canvas_result(context: ToolContext) -> dict:
    result = await sessions.describe(context.db, context.record, context.store)
    if context.commit:
        await context.db.commit()
    return {"status": "succeeded", "session": result, "run": None}


async def adopt(context: ToolContext, params: BaseModel) -> dict:
    assert isinstance(params, AdoptParams)
    await sessions.adopt(context.db, context.record, params.asset_id)
    return await _canvas_result(context)


async def undo(context: ToolContext, _: BaseModel) -> dict:
    await sessions.navigate(context.db, context.record, -1)
    return await _canvas_result(context)


async def redo(context: ToolContext, _: BaseModel) -> dict:
    await sessions.navigate(context.db, context.record, 1)
    return await _canvas_result(context)


async def generate(context: ToolContext, params: BaseModel) -> dict:
    assert isinstance(params, GenerateIn)
    if context.commit:
        run = await generation_jobs.submit(context.db, context.user_id, context.settings, params)
    else:
        from app.schemas.generation import RunOut

        run = RunOut.of(
            await generation_jobs.prepare(context.db, context.user_id, context.settings, params)
        )
    # 排队只返回实际任务；不假称生图完成，不自动采用或写入会话历史。
    return {"status": run.status.value, "run": run, "session": None}


SPECS = (
    ToolSpec(
        "generate_image",
        "生成候选图",
        "仅根据文字描述生成独立候选图片，使用当前配置的生图模式；结果不会自动替换画布。",
        GenerateIn,
        generate,
        queued=True,
        agent_params=GenerateTextIn,
    ),
    ToolSpec(
        "adopt_candidate",
        "采用候选图片",
        "将本会话图片墙中的一张候选采用到画布，产生可撤销的编辑记录。",
        AdoptParams,
        adopt,
        changes_canvas=True,
    ),
    ToolSpec(
        "undo_canvas",
        "撤销画布操作",
        "撤销本会话最近一次画布编辑，包括采用、翻转、旋转或裁剪。",
        EmptyParams,
        undo,
        changes_canvas=True,
    ),
    ToolSpec(
        "redo_canvas",
        "重做画布操作",
        "重做本会话刚撤销的画布编辑。",
        EmptyParams,
        redo,
        changes_canvas=True,
    ),
)
