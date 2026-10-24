"""提交时固定选区到任务JSON；之后清除/修改Redis选区不影响已提交任务。"""

import base64
import hashlib
from copy import deepcopy

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from redis.asyncio import Redis
from sqlalchemy import func, or_, select

from app.edits.region import EraseParams, ReplaceParams, bounds
from app.models import RunStatus, ToolRun
from app.models.edit_session import SessionAsset
from app.providers.base import ProviderError
from app.providers.region import NAME, configured
from app.queue import QueueUnavailable, enqueue
from app.schemas.generation import RunOut
from app.services import runs, sessions
from app.services.layer_documents import keys_for_document
from app.services.region_binding import checked
from app.services.selections import SelectionStore
from app.tools.base import ToolSpec

TOOLS = ("erase_region", "replace_region")


class AgentEraseParams(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    prompt: str = Field(default="", max_length=800)


class AgentReplaceParams(AgentEraseParams):
    prompt: str = Field(min_length=1, max_length=800)


async def submit(context, params, tool):
    try:
        configured(context.settings)
    except ProviderError as exc:
        raise HTTPException(503, str(exc)) from None
    try:
        bounds(context.record.document["width"], context.record.document["height"])
    except ProviderError as exc:
        raise HTTPException(422, str(exc)) from None
    row, db = context.record, context.db
    request = params.model_dump(mode="json")
    previous = await db.scalar(
        select(ToolRun)
        .where(
            ToolRun.user_id == context.user_id,
            ToolRun.tool.in_(TOOLS),
            ToolRun.params["session_id"].astext == str(row.id),
            ToolRun.params["request"]["request_id"].astext == str(params.request_id),
        )
        .order_by(ToolRun.created_at.desc())
        .limit(1)
    )
    if previous is not None:
        if previous.tool != tool or previous.params["request"] != request:
            raise HTTPException(409, "此请求编号已用于其他局部编辑，请先核对原任务")
        run = previous
    else:
        active = await db.scalar(
            select(ToolRun.id)
            .where(
                ToolRun.user_id == context.user_id,
                ToolRun.tool.in_(TOOLS),
                ToolRun.params["session_id"].astext == str(row.id),
                or_(
                    ToolRun.status.in_([RunStatus.QUEUED, RunStatus.RUNNING]),
                    (ToolRun.status == RunStatus.FAILED)
                    & ToolRun.result["recoverable"].as_boolean().is_(True),
                ),
            )
            .limit(1)
        )
        if active:
            raise HTTPException(409, "此会话已有局部编辑任务，请先完成或继续查询原任务")
        count = await db.scalar(
            select(func.count()).select_from(SessionAsset).where(SessionAsset.session_id == row.id)
        )
        if count >= sessions.WALL_LIMIT:
            raise HTTPException(422, "候选已满，请新建会话后再编辑")
        if context.region_binding is not None:
            state = checked(context.region_binding, row, params.selection_version)
        else:
            client = Redis.from_url(context.settings.redis_url, decode_responses=True)
            try:
                state = await SelectionStore(client, context.settings.queue_name).get(row)
            finally:
                await client.aclose()
        if state["version"] != params.selection_version:
            raise HTTPException(409, "选区已变化，请重新读取并核对后再提交")
        if not state["selected_pixels"] or not state["png"]:
            raise HTTPException(422, "请先用笔刷或智能点选选择要编辑的区域")
        mask = base64.b64decode(state["png"])
        await keys_for_document(db, context.user_id, row.document)
        run = await runs.create(
            db,
            context.user_id,
            {
                "provider": NAME,
                "model": context.settings.region_model,
                "session_id": str(row.id),
                "revision": row.revision,
                "asset_id": str(row.current_asset_id),
                "document": deepcopy(row.document),
                "mask_png": state["png"],
                "mask_sha256": hashlib.sha256(mask).hexdigest(),
                "request": request,
            },
            tool=tool,
            commit=False,
        )
        run.result = {
            "source_revision": row.revision,
            "selection_version": state["version"],
            "selected_pixels": state["selected_pixels"],
            "asset_ids": [],
            "is_mock": False,
            "recoverable": False,
            "query_attempt": 0,
        }
    if context.commit:
        await db.commit()
        if run.status == RunStatus.QUEUED:
            try:
                await enqueue(context.settings, run.id, attempt=run.result.get("query_attempt", 0))
            except QueueUnavailable:
                await runs.submission_uncertain(db, run.id)
                raise HTTPException(
                    503, {"message": "局部编辑投递未确认，请刷新原任务核对", "run_id": str(run.id)}
                ) from None
    return {"status": run.status.value, "run": RunOut.of(run), "session": None}


async def erase_region(context, params):
    return await submit(context, params, "erase_region")


async def replace_region(context, params):
    return await submit(context, params, "replace_region")


SPECS = (
    ToolSpec(
        "erase_region",
        "局部消除",
        "按当前选区消除物体并补全背景，生成候选后由用户采用。",
        EraseParams,
        erase_region,
        queued=True,
        agent_params=AgentEraseParams,
    ),
    ToolSpec(
        "replace_region",
        "局部替换",
        "按当前选区和描述替换内容，生成候选后由用户采用。",
        ReplaceParams,
        replace_region,
        queued=True,
        agent_params=AgentReplaceParams,
    ),
)
