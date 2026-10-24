"""拆层生成两个可检查的素材与文档，应用需单独操作。"""

from copy import deepcopy

from fastapi import HTTPException
from sqlalchemy import func, or_, select

from app.edits.region import bounds
from app.edits.background_repair import configured, snapshot
from app.edits.split import SplitParams
from app.models import RunStatus, ToolRun
from app.models.edit_session import SessionAsset
from app.providers.base import ProviderError
from app.queue import QueueUnavailable, enqueue
from app.schemas.generation import RunOut
from app.services import runs, sessions
from app.services.matting import MattingUnavailable, verify_model
from app.tools.base import ToolSpec

NAME = "rembg-u2netp+dashscope-split"
LOCAL_NAME = "rembg-u2netp+lama-split"


async def split_layers(context, params):
    try:
        configured(context.settings)
        verify_model(context.settings.matting_model_path)
    except (ProviderError, MattingUnavailable) as exc:
        raise HTTPException(503, str(exc)) from None
    row, db = context.record, context.db
    if len(row.document["layers"]) != 1:
        raise HTTPException(409, "当前已有多个图层，请先检查现有图层，避免重复拆层")
    try:
        bounds(row.document["width"], row.document["height"])
    except ProviderError as exc:
        raise HTTPException(422, str(exc)) from None
    request = params.model_dump(mode="json")
    previous = await db.scalar(
        select(ToolRun)
        .where(
            ToolRun.user_id == context.user_id,
            ToolRun.tool == "split_layers",
            ToolRun.params["session_id"].astext == str(row.id),
            ToolRun.params["request"]["request_id"].astext == str(params.request_id),
        )
        .limit(1)
    )
    if previous is not None:
        if previous.params["request"] != request or previous.params["revision"] != row.revision:
            raise HTTPException(409, "此请求编号已用于其他拆层内容，请核对原任务")
        run = previous
    else:
        try:
            repair = snapshot(
                params.prompt, local=context.settings.background_repair_backend == "lama"
            )
        except ProviderError as exc:
            raise HTTPException(422, str(exc)) from None
        existing = await db.scalar(
            select(ToolRun)
            .where(
                ToolRun.user_id == context.user_id,
                ToolRun.tool == "split_layers",
                ToolRun.params["session_id"].astext == str(row.id),
                or_(
                    ToolRun.status.in_([RunStatus.QUEUED, RunStatus.RUNNING]),
                    ToolRun.result["recoverable"].as_boolean().is_(True),
                    (ToolRun.result["submission_started"].as_boolean().is_(True))
                    & (ToolRun.result["remote_task_id"].astext.is_(None)),
                    (ToolRun.status == RunStatus.SUCCEEDED)
                    & (ToolRun.params["revision"].as_integer() == row.revision),
                ),
            )
            .order_by(ToolRun.created_at.desc())
            .limit(1)
        )
        if existing:
            raise HTTPException(409, "此画布已有拆层任务或结果，请先检查并应用，避免重复生成背景")
        count = await db.scalar(
            select(func.count()).select_from(SessionAsset).where(SessionAsset.session_id == row.id)
        )
        if count > sessions.WALL_LIMIT - 2:
            raise HTTPException(422, "会话候选不足两个空位，请新建会话后拆层")
        await sessions.owned_assets(db, context.user_id, [row.current_asset_id])
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
                "document": deepcopy(row.document),
                "request": request,
                **repair,
            },
            tool="split_layers",
            commit=False,
        )
        run.result = {
            "source_revision": row.revision,
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
                    503, {"message": "拆层投递未确认，请刷新原任务核对", "run_id": str(run.id)}
                ) from None
    return {"status": run.status.value, "run": RunOut.of(run), "session": None}


SPECS = (
    ToolSpec(
        "split_layers",
        "分离主体与背景",
        "本地抠出主体，百炼补全背景，检查后手动应用两层。",
        SplitParams,
        split_layers,
        queued=True,
        agent_visible=False,
    ),
)
