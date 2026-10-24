"""被统一队列入口派发；产物与候选墙关联，不改动当前画布或历史。"""

import asyncio
import uuid

from app.db import session_scope
from app.models import AssetKind, AssetSource
from app.services import assets, runs, sessions
from app.services.images import probe
from app.services.layer_documents import read_snapshot
from app.services.matting import remove_background


async def execute(ctx: dict, db, run) -> None:
    params = run.params

    async def progress(value, stage):
        await runs.report(db, run, value, stage)
        await ctx["events"].notify(run.id)

    await progress(15, "读取提交时的画布")
    data = await read_snapshot(db, ctx["store"], run.user_id, params["document"])
    await progress(30, "本地模型正在分离主体")
    result = await asyncio.to_thread(
        remove_background, data, params["document"], ctx["settings"].matting_model_path
    )
    meta = await asyncio.to_thread(probe, result)
    await progress(85, "保存透明 PNG")
    async with session_scope(ctx["session_factory"]) as asset_db:
        asset = await assets.create_from_bytes(
            asset_db,
            ctx["store"],
            run.user_id,
            result,
            meta,
            kind=AssetKind.SUBJECT,
            source=AssetSource.TOOL,
        )
        # 先登记素材编号，后续关联失败也能从任务中找到结果，而不是丢失产物。
        run.result = {
            "provider": "rembg-u2netp",
            "is_mock": False,
            "asset_ids": [str(asset.id)],
            "source_revision": params["revision"],
        }
        await db.commit()
        row = await sessions.load(asset_db, run.user_id, uuid.UUID(params["session_id"]))
        await sessions.attach(asset_db, row, [asset])
        await asset_db.commit()
    await progress(95, "候选已加入会话，请检查后采用")
