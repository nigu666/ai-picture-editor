"""读取确认时的画布快照，单次生成并挂入候选；不更新当前文档。"""

import asyncio
import hashlib
import uuid

from app.db import session_scope
from app.edits.canvas_edit import NAME, prepare
from app.models import AssetSource
from app.providers.base import GenerateRequest, ProviderError
from app.providers.reference_generation import ReferenceImageProvider, configured
from app.services import generation, runs, sessions
from app.services.layer_documents import read_snapshot


async def execute(ctx, db, run):
    params = run.params
    if params["provider"] != NAME:
        raise ProviderError("整图编辑任务平台不符，本次未调用模型")
    settings = ctx["settings"].model_copy(update={"reference_image_model": params["model"]})
    configured(settings)

    async def progress(value, stage):
        await runs.report(db, run, value, stage)
        await ctx["events"].notify(run.id)

    async def attach(asset_db, assets):
        row = await sessions.load(asset_db, run.user_id, uuid.UUID(params["session_id"]))
        await sessions.attach(asset_db, row, assets)
        await asset_db.commit()

    if run.result.get("asset_ids"):
        async with session_scope(ctx["session_factory"]) as asset_db:
            assets = await sessions.owned_assets(
                asset_db, run.user_id, [uuid.UUID(value) for value in run.result["asset_ids"]]
            )
            await attach(asset_db, assets)
        await progress(95, "已有整图编辑候选已找回，未重新生成")
        return
    if run.result.get("submission_started"):
        raise ProviderError("原整图编辑提交结果尚未确认，不会重复调用模型，请先核对百炼记录")
    await progress(10, "读取确认执行时的已保存画布")
    sources = await read_snapshot(db, ctx["store"], run.user_id, params["document"])
    image = await asyncio.to_thread(prepare, sources, params["document"])
    provider = ctx.get("canvas_edit_provider_factory", ReferenceImageProvider)(settings)
    request = GenerateRequest(
        params["request"]["prompt"],
        params["target"]["width"],
        params["target"]["height"],
        references=[image],
    )
    run.result = {
        **run.result,
        "submission_started": True,
        "source_render_sha256": hashlib.sha256(image).hexdigest(),
    }
    await progress(20, "将已确认画布交由百炼编辑，等待候选")
    async with session_scope(ctx["session_factory"]) as asset_db:

        async def saved(asset):
            run.result = {**run.result, "asset_ids": [str(asset.id)]}
            await db.commit()
            await attach(asset_db, [asset])

        await generation.generate_and_store(
            asset_db,
            ctx["store"],
            run.user_id,
            provider,
            request,
            progress,
            saved,
            asset_source=AssetSource.TOOL,
        )
    await progress(95, "整图编辑候选已保存，检查后再采用")
