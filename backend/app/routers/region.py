import uuid

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.deps import CurrentUser, SessionDep, SettingsDep
from app.models import RunStatus, ToolRun
from app.providers.base import ProviderError
from app.providers.region import configured
from app.queue import QueueUnavailable, enqueue
from app.schemas.generation import RunOut
from app.services import runs, sessions

router = APIRouter(tags=["region"])


@router.get("/region-options")
async def options(_: CurrentUser, settings: SettingsDep):
    try:
        configured(settings)
        enabled = True
    except ProviderError:
        enabled = False
    return {
        "enabled": enabled,
        "model": settings.region_model,
        "min_input_side": 512,
        "max_input_side": 4096,
        "max_output_side": 4096,
    }


@router.get("/sessions/{session_id}/region-runs")
async def list_runs(session_id: uuid.UUID, user: CurrentUser, db: SessionDep):
    await sessions.load(db, user.id, session_id)
    rows = await db.scalars(
        select(ToolRun)
        .where(
            ToolRun.user_id == user.id,
            ToolRun.tool.in_(["erase_region", "replace_region"]),
            ToolRun.params["session_id"].astext == str(session_id),
        )
        .order_by(ToolRun.created_at.desc(), ToolRun.id.desc())
        .limit(10)
    )
    return [
        {**RunOut.of(row).model_dump(mode="json"), "request": row.params["request"]} for row in rows
    ]


@router.post("/sessions/{session_id}/region-runs/{run_id}/resume", status_code=202)
async def resume(
    session_id: uuid.UUID,
    run_id: uuid.UUID,
    user: CurrentUser,
    db: SessionDep,
    settings: SettingsDep,
):
    try:
        configured(settings)
    except ProviderError as exc:
        raise HTTPException(503, str(exc)) from None
    await sessions.load(db, user.id, session_id)
    run = await db.scalar(
        select(ToolRun).where(ToolRun.id == run_id, ToolRun.user_id == user.id).with_for_update()
    )
    if (
        run is None
        or run.tool not in {"erase_region", "replace_region"}
        or run.params.get("session_id") != str(session_id)
    ):
        raise HTTPException(404, "局部编辑任务不存在")
    if (
        run.status == RunStatus.FAILED
        and run.result.get("recoverable")
        and run.result.get("remote_task_id")
    ):
        run.status, run.stage, run.error, run.finished_at = (
            RunStatus.QUEUED,
            "等待恢复查询原任务",
            None,
            None,
        )
        run.result = {**run.result, "query_attempt": run.result.get("query_attempt", 0) + 1}
    elif run.status not in {RunStatus.QUEUED, RunStatus.RUNNING}:
        raise HTTPException(409, "此任务不可恢复查询，请先核对结果")
    await db.commit()
    try:
        await enqueue(settings, run.id, attempt=run.result.get("query_attempt", 0))
    except QueueUnavailable:
        await runs.submission_uncertain(db, run.id)
        raise HTTPException(
            503, {"message": "恢复查询投递未确认，请先刷新任务", "run_id": str(run.id)}
        ) from None
    return {"run": RunOut.of(run)}
