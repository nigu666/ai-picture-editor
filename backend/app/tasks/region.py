"""局部编辑云任务编号立即落库，恢复只查询原编号，不重复创建云任务。"""

import asyncio
import base64
import hashlib
import uuid

from app.db import session_scope
from app.edits.region import composite, prepare
from app.models import AssetKind, AssetSource
from app.providers.base import ProviderError
from app.providers.region import NAME, DashscopeRegion, ExpansionError, configured
from app.services import assets, runs, sessions
from app.services.images import probe
from app.services.layer_documents import read_snapshot


async def execute(ctx, db, run):
    configured(ctx["settings"])
    params = run.params
    if params["provider"] != NAME or params.get("model") != ctx["settings"].region_model:
        raise ProviderError("局部编辑平台配置与原任务不符")

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
    mask = base64.b64decode(params["mask_png"])
    if hashlib.sha256(mask).hexdigest() != params["mask_sha256"]:
        raise ProviderError("局部编辑选区快照校验失败")
    image, cloud_mask = await asyncio.to_thread(prepare, data, params["document"], mask)
    provider = ctx.get("region_provider_factory", DashscopeRegion)(ctx["settings"])
    remote_id = run.result.get("remote_task_id")
    try:
        if not remote_id:
            if run.result.get("submission_started"):
                raise ExpansionError(
                    "原提交结果未确认，不会重复创建局部编辑任务，请到百炼核对调用记录"
                )
            run.result = {**run.result, "submission_started": True}
            await progress(20, "提交百炼局部编辑")
            remote_id = await provider.submit(image, cloud_mask, params["request"]["prompt"])
            run.result = {
                **run.result,
                "remote_task_id": remote_id,
                "recoverable": True,
                "provider": NAME,
            }
            await db.commit()
        await progress(35, "云端局部编辑处理中")
        generated = await provider.wait(remote_id)
        await progress(80, "合成选区并保留选区外像素")
        result = await asyncio.to_thread(composite, image, generated, mask)
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
        await progress(95, "局部编辑候选已保存，请检查后采用")
    except ExpansionError as exc:
        run.result = {**run.result, "recoverable": bool(remote_id) and exc.recoverable}
        await db.commit()
        raise
    except ProviderError:
        run.result = {**run.result, "recoverable": False}
        await db.commit()
        raise
