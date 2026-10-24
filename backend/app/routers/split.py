"""拆层任务查询、原任务恢复与显式应用；不接受客户端图层文档。"""

import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.deps import CurrentUser, SessionDep, SettingsDep, StorageDep
from app.edits.background_repair import configured, is_local
from app.models import RunStatus, ToolRun
from app.providers.base import ProviderError
from app.queue import QueueUnavailable, enqueue
from app.schemas.generation import RunOut
from app.services import runs, sessions
from app.services.layer_documents import keys_for_document
from app.services.matting import MattingUnavailable, verify_model

router = APIRouter(tags=["split"])


@router.get("/split-options")
async def options(_: CurrentUser, settings: SettingsDep):
    try:
        configured(settings)
        verify_model(settings.matting_model_path)
        enabled = True
    except (ProviderError, MattingUnavailable):
        enabled = False
    local = settings.background_repair_backend == "lama"
    return {
        "enabled": enabled,
        "model": "lama-onnx" if local else settings.region_model,
        "local_repair": local,
    }


@router.get("/sessions/{session_id}/split-runs")
async def list_runs(session_id: uuid.UUID, user: CurrentUser, db: SessionDep):
    await sessions.load(db, user.id, session_id)
    rows = await db.scalars(
        select(ToolRun)
        .where(
            ToolRun.user_id == user.id,
            ToolRun.tool == "split_layers",
            ToolRun.params["session_id"].astext == str(session_id),
        )
        .order_by(ToolRun.created_at.desc(), ToolRun.id.desc())
        .limit(10)
    )
    return [
        {**RunOut.of(row).model_dump(mode="json"), "request": row.params["request"]} for row in rows
    ]


async def owned_run(db, user_id, session_id, run_id):
    run = await db.scalar(
        select(ToolRun)
        .where(
            ToolRun.id == run_id,
            ToolRun.user_id == user_id,
        )
        .with_for_update()
    )
    if run is None or run.tool != "split_layers" or run.params.get("session_id") != str(session_id):
        raise HTTPException(404, "拆层任务不存在")
    return run


@router.post("/sessions/{session_id}/split-runs/{run_id}/resume", status_code=202)
async def resume(
    session_id: uuid.UUID,
    run_id: uuid.UUID,
    user: CurrentUser,
    db: SessionDep,
    settings: SettingsDep,
):
    await sessions.load(db, user.id, session_id)
    run = await owned_run(db, user.id, session_id, run_id)
    try:
        configured(settings, local=is_local(run.params))
    except ProviderError as exc:
        raise HTTPException(503, str(exc)) from None
    if run.result.get("submission_started") and not run.result.get("remote_task_id"):
        raise HTTPException(409, "云端提交未确认，请到百炼核对记录；不会重复提交")
    if run.status == RunStatus.FAILED and run.result.get("recoverable"):
        run.status, run.stage, run.error, run.finished_at = (
            RunStatus.QUEUED,
            "等待继续原拆层任务",
            None,
            None,
        )
        run.result = {**run.result, "query_attempt": run.result.get("query_attempt", 0) + 1}
    elif run.status not in {RunStatus.QUEUED, RunStatus.RUNNING}:
        raise HTTPException(409, "此拆层任务不可恢复，请先核对结果")
    await db.commit()
    try:
        await enqueue(settings, run.id, attempt=run.result.get("query_attempt", 0))
    except QueueUnavailable:
        await runs.submission_uncertain(db, run.id)
        raise HTTPException(
            503, {"message": "投递未确认，请刷新原拆层任务", "run_id": str(run.id)}
        ) from None
    return {"run": RunOut.of(run)}


class ApplySplit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1, strict=True)


@router.post("/sessions/{session_id}/split-runs/{run_id}/apply")
async def apply(
    session_id: uuid.UUID,
    run_id: uuid.UUID,
    body: ApplySplit,
    user: CurrentUser,
    db: SessionDep,
    store: StorageDep,
):
    row = await sessions.load(db, user.id, session_id)
    run = await owned_run(db, user.id, session_id, run_id)
    document = run.result.get("layer_document")
    if (
        run.status != RunStatus.SUCCEEDED
        or not document
        or len(run.result.get("asset_ids", [])) != 2
    ):
        raise HTTPException(409, "拆层尚未完成，请等待主体和背景均保存后再应用")
    await keys_for_document(db, user.id, document)
    if [layer["asset_id"] for layer in document["layers"]] != run.result["asset_ids"]:
        raise HTTPException(409, "拆层结果不完整，请核对任务")
    background_id = uuid.UUID(run.result["asset_ids"][0])
    # 回执丢失后重试同一应用，不能再制造一条历史。
    if (
        row.document == document
        and row.current_asset_id == background_id
        and run.result.get("applied_revision")
    ):
        return await sessions.describe(db, row, store)
    sessions.check_version(row, body.revision)
    if (
        row.revision != run.params["revision"]
        or row.document != run.params["document"]
        or str(row.current_asset_id) != run.params["asset_id"]
    ):
        raise HTTPException(409, "画布已有更新，拆层结果保留为独立素材，请勿覆盖新画布")
    await sessions.apply_edit(
        db, row, document, "apply_split_layers", current_asset_id=background_id
    )
    run.result = {**run.result, "applied_revision": row.revision}
    result = await sessions.describe(db, row, store)
    await db.commit()
    return result
