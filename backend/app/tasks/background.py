"""逐张生成并保存，部分失败保留已保存候选，不自动采用。"""

import asyncio
import uuid

from app.db import session_scope
from app.edits.background import compose
from app.models import AssetKind, AssetSource
from app.providers.background import configured, get_background_provider, provider_name
from app.providers.base import ProviderError
from app.services import assets, runs, sessions
from app.services.images import probe
from app.services.layer_documents import read_snapshot
from app.services.matting import remove_background


async def execute(ctx, db, run):
    configured(ctx["settings"])
    if run.params["provider"] != provider_name(ctx["settings"]):
        raise ProviderError("平台配置已变更，旧换背景任务已停止；请检查后重新提交")
    params = run.params

    async def progress(value, stage):
        await runs.report(db, run, value, stage)
        await ctx["events"].notify(run.id)

    await progress(10, "读取提交时的画布")
    data = await read_snapshot(db, ctx["store"], run.user_id, params["document"])
    await progress(20, "本地分离主体")
    subject = await asyncio.to_thread(
        remove_background, data, params["document"], ctx["settings"].matting_model_path
    )
    provider = ctx.get("background_provider_factory", get_background_provider)(ctx["settings"])
    count = params["request"]["count"]
    generation_lock = ctx.setdefault("background_generation_lock", asyncio.Lock())
    for index in range(count):
        await progress(25 + round(65 * index / count), "等待背景生成")
        # 同一Worker内串行调用生图，避免两个作业同时占用账号生图并发额度。
        async with generation_lock:
            await progress(25 + round(65 * index / count), f"正在生成背景 {index + 1}/{count}")
            backdrop = await provider.generate(
                params["request"]["prompt"],
                params["document"]["width"],
                params["document"]["height"],
            )
        result = await asyncio.to_thread(compose, subject, backdrop)
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
                "provider": provider.name,
                "is_mock": False,
                "asset_ids": [*run.result.get("asset_ids", []), str(asset.id)],
                "source_revision": params["revision"],
            }
            await db.commit()
            row = await sessions.load(asset_db, run.user_id, uuid.UUID(params["session_id"]))
            await sessions.attach(asset_db, row, [asset])
            await asset_db.commit()
        await progress(25 + round(65 * (index + 1) / count), f"合成候选已保存 {index + 1}/{count}")
    await progress(95, "合成候选已加入会话，请检查后采用")
