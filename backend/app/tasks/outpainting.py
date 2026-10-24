"""扩图云任务编号立即落库，恢复只查询原编号，不重复创建云任务。"""

import asyncio
import uuid

from app.db import session_scope
from app.edits.outpainting import prepare, protect_original
from app.models import AssetKind, AssetSource
from app.providers.base import ProviderError
from app.providers.outpainting import NAME, DashscopeOutpainting, ExpansionError, configured
from app.services import assets, runs, sessions
from app.services.images import probe
from app.services.layer_documents import read_snapshot


async def execute(ctx, db, run):
    configured(ctx["settings"])
    params = run.params
    if params["provider"] != NAME or params.get("model") != ctx["settings"].outpainting_model:
        raise ProviderError("扩图平台配置与原任务不符")

    async def progress(value, text):
        await runs.report(db, run, value, text)
        await ctx["events"].notify(run.id)

    # 素材已保存但挂墙中断时，直接恢复挂墙，不创建或查询云端任务。
    if run.result.get("asset_ids"):
        async with session_scope(ctx["session_factory"]) as asset_db:
            candidates = await sessions.owned_assets(
                asset_db, run.user_id, [uuid.UUID(i) for i in run.result["asset_ids"]]
            )
            row = await sessions.load(asset_db, run.user_id, uuid.UUID(params["session_id"]))
            await sessions.attach(asset_db, row, candidates)
            await asset_db.commit()
        run.result = {**run.result, "recoverable": False}
        await db.commit()
        return
    await progress(10, "读取提交时的画布")
    data = await read_snapshot(db, ctx["store"], run.user_id, params["document"])
    image = await asyncio.to_thread(prepare, data, params["document"])
    provider = ctx.get("outpainting_provider_factory", DashscopeOutpainting)(ctx["settings"])
    remote_id = run.result.get("remote_task_id")
    try:
        if not remote_id:
            if run.result.get("submission_started"):
                raise ExpansionError("原提交结果未确认，不会重复创建扩图任务，请到百炼核对调用记录")
            run.result = {**run.result, "submission_started": True}
            await progress(20, "提交百炼扩图")
            remote_id = await provider.submit(image, params["target"])
            run.result = {
                **run.result,
                "remote_task_id": remote_id,
                "recoverable": True,
                "provider": NAME,
            }
            await db.commit()
        await progress(35, "云端扩图处理中")
        generated = await provider.wait(remote_id)
        await progress(80, "保留原画布区域并保存候选")
        result = await asyncio.to_thread(protect_original, image, generated, params["target"])
        meta = await asyncio.to_thread(probe, result)
        async with session_scope(ctx["session_factory"]) as asset_db:
            asset = await assets.create_from_bytes(
                asset_db,
                ctx["store"],
                run.user_id,
                result,
                meta,
                kind=AssetKind.GENERATED,
                source=AssetSource.TOOL,
            )
            run.result = {
                **run.result,
                "asset_ids": [str(asset.id)],
                "target_width": meta.width,
                "target_height": meta.height,
            }
            await db.commit()
            row = await sessions.load(asset_db, run.user_id, uuid.UUID(params["session_id"]))
            await sessions.attach(asset_db, row, [asset])
            await asset_db.commit()
        run.result = {**run.result, "recoverable": False}
        await progress(95, "扩图候选已保存，请检查后采用")
    except ExpansionError as exc:
        run.result = {**run.result, "recoverable": bool(remote_id) and exc.recoverable}
        await db.commit()
        raise
    except ProviderError:
        run.result = {**run.result, "recoverable": False}
        await db.commit()
        raise
