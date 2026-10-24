"""网页生成接口和工具调用共用同一任务投递入口。"""

import uuid

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import ToolRun
from app.providers import GenerateRequest, get_image_provider
from app.providers.base import ProviderError
from app.providers.generation_options import check_request, sizes_for
from app.providers.reference_generation import ReferenceImageProvider, validate_parameters
from app.queue import QueueUnavailable, enqueue
from app.schemas.generation import GenerateIn, RunOut
from app.services import runs
from app.services.generation_references import owned_references


async def prepare(
    db: AsyncSession, user_id: uuid.UUID, settings: Settings, payload: GenerateIn
) -> ToolRun:
    """只准备数据库任务；由调用方连同计划步骤一起提交，再投递同一任务编号。"""
    try:
        if payload.reference_asset_ids:
            ReferenceImageProvider(settings)
        else:
            get_image_provider(settings)
    except ProviderError as exc:
        raise HTTPException(503, str(exc)) from None
    width, height = sizes_for(settings)[payload.ratio]
    request = payload.model_dump(exclude={"ratio", "reference_asset_ids"}) | {
        "width": width,
        "height": height,
    }
    try:
        if payload.reference_asset_ids:
            validate_parameters(GenerateRequest(**request))
            await owned_references(db, user_id, payload.reference_asset_ids)
        else:
            check_request(settings, GenerateRequest(**request))
    except ProviderError as exc:
        raise HTTPException(422, str(exc)) from None
    return await runs.create(
        db,
        user_id,
        {
            "provider": settings.image_provider,
            "model": settings.reference_image_model
            if payload.reference_asset_ids
            else settings.image_model,
            "reference_asset_ids": [str(value) for value in payload.reference_asset_ids],
            "request": request,
        },
        commit=False,
    )


async def submit(
    db: AsyncSession, user_id: uuid.UUID, settings: Settings, payload: GenerateIn
) -> RunOut:
    run = await prepare(db, user_id, settings, payload)
    await db.commit()
    try:
        await enqueue(settings, run.id)
    except QueueUnavailable:
        await runs.submission_uncertain(db, run.id)
        raise HTTPException(
            503, {"message": "投递未确认，请按任务编号查询后核对", "run_id": str(run.id)}
        ) from None
    return RunOut.of(run)
