import uuid

from fastapi import APIRouter
from sqlalchemy import select

from app.deps import CurrentUser, SessionDep, SettingsDep
from app.models import ToolRun
from app.providers.background import configured, provider_name
from app.providers.base import ProviderError
from app.providers.generation_options import options as generation_options
from app.schemas.generation import RunOut
from app.services import sessions

router = APIRouter(tags=["background"])


@router.get("/background-options")
async def options(_: CurrentUser, settings: SettingsDep):
    enabled = True
    try:
        configured(settings)
    except ProviderError:
        enabled = False
    return {
        "enabled": enabled,
        "provider": provider_name(settings),
        "label": "百炼万相"
        if settings.background_provider == "dashscope"
        else "智谱"
        if settings.background_provider == "zhipu"
        else "未启用",
        "model": settings.background_model
        if settings.background_provider == "dashscope"
        else "glm-image"
        if settings.background_provider == "zhipu"
        else "",
        "counts": [1, 2, 4],
        "prompt_limit": 800,
    }


@router.get("/model-options")
async def model_options(_: CurrentUser, settings: SettingsDep):
    return {
        "planner_provider": settings.planner_provider,
        "planner_model": settings.planner_model,
        "planner_configured": bool(settings.dashscope_api_key.strip())
        if settings.planner_provider == "dashscope"
        else bool(settings.zhipu_api_key.strip()),
        "vision_enabled": settings.planner_vision_enabled
        if settings.planner_provider == "dashscope"
        else True,
        **generation_options(settings),
        "background": await options(_, settings),
    }


@router.get("/sessions/{session_id}/background-runs")
async def list_runs(session_id: uuid.UUID, user: CurrentUser, db: SessionDep):
    await sessions.load(db, user.id, session_id)
    rows = await db.scalars(
        select(ToolRun)
        .where(
            ToolRun.user_id == user.id,
            ToolRun.tool == "replace_background",
            ToolRun.params["session_id"].astext == str(session_id),
        )
        .order_by(ToolRun.created_at.desc(), ToolRun.id.desc())
        .limit(10)
    )
    return [
        {**RunOut.of(row).model_dump(mode="json"), "request": row.params["request"]} for row in rows
    ]
