"""提交只返回任务编号；查询接口严格检查任务和素材归属。"""

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import and_, or_, select

from app.deps import CurrentUser, SessionDep, SettingsDep, StorageDep
from app.models import ToolRun
from app.schemas.asset import AssetOut
from app.schemas.generation import GenerateIn, GenerationPage, GenerationRecord, RunOut
from app.services import assets, generation_jobs, runs, sessions

router = APIRouter(tags=["generations"])


@router.get("/generations")
async def history(
    user: CurrentUser,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=20)] = 10,
    before: uuid.UUID | None = None,
) -> GenerationPage:
    query = select(ToolRun).where(ToolRun.user_id == user.id, ToolRun.tool == "generate")
    if before is not None:
        anchor = await runs.get_for_user(session, user.id, before)
        if anchor is None or anchor.tool != "generate":
            raise HTTPException(404, "生成记录位置不存在，请返回最新记录")
        query = query.where(
            or_(
                ToolRun.created_at < anchor.created_at,
                and_(ToolRun.created_at == anchor.created_at, ToolRun.id < anchor.id),
            )
        )
    rows = list(
        await session.scalars(
            query.order_by(ToolRun.created_at.desc(), ToolRun.id.desc()).limit(limit + 1)
        )
    )
    return GenerationPage(
        items=[GenerationRecord.of(row) for row in rows[:limit]],
        next_cursor=rows[limit - 1].id if len(rows) > limit else None,
    )


@router.get("/sessions/{session_id}/matting-runs")
async def matting_runs(
    session_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
) -> list[RunOut]:
    await sessions.load(session, user.id, session_id)
    rows = await session.scalars(
        select(ToolRun)
        .where(
            ToolRun.user_id == user.id,
            ToolRun.tool == "remove_background",
            ToolRun.params["session_id"].astext == str(session_id),
        )
        .order_by(ToolRun.created_at.desc(), ToolRun.id.desc())
        .limit(10)
    )
    return [RunOut.of(row) for row in rows]


@router.post("/generations", status_code=202)
async def submit(
    payload: GenerateIn,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
    store: StorageDep,
) -> RunOut:
    return await generation_jobs.submit(session, user.id, settings, payload)


@router.get("/runs/{run_id}")
async def get_run(
    run_id: uuid.UUID, user: CurrentUser, session: SessionDep, store: StorageDep
) -> RunOut:
    run = await runs.get_for_user(session, user.id, run_id)
    if run is None:
        raise HTTPException(404, "任务不存在")
    candidates = []
    for candidate_id in run.result.get("asset_ids", []):
        asset = await assets.get_for_user(session, user.id, uuid.UUID(candidate_id))
        if asset is not None:
            candidates.append(AssetOut.of(asset, store))
    return RunOut.of(run, candidates)
