"""固定画布与临时选区后入队；不直接修改当前文档。"""

import asyncio
import base64
import copy

from fastapi import HTTPException
from sqlalchemy import func, or_, select

from app.edits.promote import PromoteParams, selection_mask, signature
from app.edits.background_repair import configured, snapshot
from app.edits.region import bounds
from app.models import RunStatus, ToolRun
from app.models.edit_session import SessionAsset
from app.providers.base import ProviderError
from app.queue import QueueUnavailable, enqueue
from app.schemas.generation import RunOut
from app.services import runs, sessions
from app.services.region_binding import capture
from app.tools.base import ToolSpec

NAME = "selection+dashscope-promote"
LOCAL_NAME = "selection+lama-promote"


async def promote_object(context, params):
    row, db = context.record, context.db
    try:
        configured(context.settings)
        bounds(row.document["width"], row.document["height"])
    except ProviderError as exc:
        raise HTTPException(422, str(exc)) from None
    request = params.model_dump(mode="json")
    previous = await db.scalar(
        select(ToolRun)
        .where(
            ToolRun.user_id == context.user_id,
            ToolRun.tool == "promote_object",
            ToolRun.params["session_id"].astext == str(row.id),
            ToolRun.params["request"]["request_id"].astext == str(params.request_id),
        )
        .limit(1)
    )
    if previous:
        if previous.params["request"] != request or previous.params["revision"] != row.revision:
            raise HTTPException(409, "此请求编号已用于其他选区或画布，请核对原成层任务")
        run = previous
    else:
        try:
            repair = snapshot(
                params.prompt, local=context.settings.background_repair_backend == "lama"
            )
        except ProviderError as exc:
            raise HTTPException(422, str(exc)) from None
        count = len(row.document["layers"])
        if count > 18:
            raise HTTPException(422, "选区成层最多从18个现有图层开始，请先减少图层或新建会话")
        wall = await db.scalar(
            select(func.count()).select_from(SessionAsset).where(SessionAsset.session_id == row.id)
        )
        if wall + (2 if count == 1 else count + 2) > sessions.WALL_LIMIT:
            raise HTTPException(422, "会话候选空间不足，请新建会话后成层")
        binding = await capture(row, context.settings)
        if not binding or binding["version"] != params.selection_version:
            raise HTTPException(409, "选区不存在或已变化，请重新读取选区后提交")
        try:
            mask = await asyncio.to_thread(
                selection_mask,
                base64.b64decode(binding["png"], validate=True),
                (row.document["width"], row.document["height"]),
            )
        except ProviderError as exc:
            raise HTTPException(422, str(exc)) from None
        key = signature(mask)
        if any(item.get("source_hash") == key for item in row.document["layers"]):
            raise HTTPException(409, "该选区已是当前文档中的独立图层，无需重复成层")
        existing = await db.scalar(
            select(ToolRun)
            .where(
                ToolRun.user_id == context.user_id,
                ToolRun.tool == "promote_object",
                ToolRun.params["session_id"].astext == str(row.id),
                or_(
                    ToolRun.status.in_([RunStatus.QUEUED, RunStatus.RUNNING]),
                    ToolRun.result["recoverable"].as_boolean().is_(True),
                    ToolRun.result["submission_started"].as_boolean().is_(True)
                    & ToolRun.result["remote_task_id"].astext.is_(None),
                    (ToolRun.status == RunStatus.SUCCEEDED)
                    & (ToolRun.params["revision"].as_integer() == row.revision)
                    & (ToolRun.params["mask_sha256"].astext == key),
                ),
            )
            .limit(1)
        )
        if existing:
            raise HTTPException(409, "已有成层任务或此选区的结果，请先核对原任务，避免重复生成背景")
        run = await runs.create(
            db,
            context.user_id,
            {
                "provider": LOCAL_NAME
                if context.settings.background_repair_backend == "lama"
                else NAME,
                "model": "lama-onnx"
                if context.settings.background_repair_backend == "lama"
                else context.settings.region_model,
                "session_id": str(row.id),
                "revision": row.revision,
                "asset_id": str(row.current_asset_id),
                "document": copy.deepcopy(row.document),
                "request": request,
                **repair,
                "mask_png": binding["png"],
                "mask_sha256": key,
            },
            tool="promote_object",
            commit=False,
        )
        run.result = dict(
            source_revision=row.revision,
            selection_version=params.selection_version,
            asset_ids=[],
            parts={},
            recoverable=False,
            query_attempt=0,
            is_mock=False,
        )
    if context.commit:
        await db.commit()
        if run.status == RunStatus.QUEUED:
            try:
                await enqueue(context.settings, run.id, attempt=run.result.get("query_attempt", 0))
            except QueueUnavailable:
                await runs.submission_uncertain(db, run.id)
                raise HTTPException(
                    503, {"message": "成层投递未确认，请刷新原任务", "run_id": str(run.id)}
                ) from None
    return {"status": run.status.value, "run": RunOut.of(run), "session": None}


SPECS = (
    ToolSpec(
        "promote_object",
        "选区成层",
        "将已选区域提成独立物体，修复原位置，检查后明确应用。",
        PromoteParams,
        promote_object,
        queued=True,
        agent_visible=False,
    ),
)
