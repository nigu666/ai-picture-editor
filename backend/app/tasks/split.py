"""确定性素材编号与阶段检查点；恢复查询同一云端任务，不重复付费提交。"""

import asyncio
import base64
import uuid

from botocore.exceptions import BotoCoreError, ClientError
from sqlalchemy.exc import SQLAlchemyError

from app.edits.region import composite, png
from app.edits.split import digest, prefill, prepare_subject, source_image, split_document
from app.edits.background_repair import configured, for_task, is_local
from app.models import Asset, AssetKind, AssetSource
from app.providers.base import ProviderError
from app.providers.region import DashscopeRegion, ExpansionError
from app.services import assets, runs, sessions
from app.services.assets import AssetCommitUncertain, AssetSaveFailed, StorageUnavailable
from app.services.images import probe
from app.services.matting import remove_background
from app.tools.split import LOCAL_NAME, NAME
from app.services.inpainting import repair as repair_background


async def save_part(db, store, run, raw, kind):
    asset_id = uuid.uuid5(run.id, "split-" + kind.value)
    existing = await db.get(Asset, asset_id)
    if existing:
        if existing.user_id != run.user_id or existing.kind != kind:
            raise ProviderError("拆层素材检查点归属不符")
        return existing
    meta = await asyncio.to_thread(probe, raw)
    key = f"users/{run.user_id}/{asset_id}.png"
    try:
        await store.put(key, raw, meta.content_type)
    except (BotoCoreError, ClientError, OSError):
        raise StorageUnavailable("拆层素材存储暂不可用，可继续原任务") from None
    asset = Asset(
        id=asset_id,
        user_id=run.user_id,
        kind=kind,
        source=AssetSource.TOOL,
        storage_key=key,
        image_format=meta.image_format,
        width=meta.width,
        height=meta.height,
        size_bytes=meta.size_bytes,
        has_alpha=meta.has_alpha,
    )
    db.add(asset)
    run.result = {**run.result, kind.value + "_asset_id": str(asset_id), "recoverable": True}
    try:
        await db.flush()
    except SQLAlchemyError:
        await assets._discard_uncommitted(db, store, key)
        raise AssetSaveFailed("拆层素材记录未保存，请核对原任务") from None
    try:
        await db.commit()
    except SQLAlchemyError:
        await db.rollback()
        raise AssetCommitUncertain("拆层素材提交未确认，保留对象并使用原任务核对") from None
    return asset


async def execute(ctx, db, run):
    settings = ctx["settings"]
    local = is_local(run.params)
    configured(settings, local=local)
    if run.params["provider"] != (LOCAL_NAME if local else NAME) or run.params["model"] != (
        "lama-onnx" if local else settings.region_model
    ):
        raise ProviderError("拆层配置与原任务不符，请核对后继续原任务")
    params, result = run.params, run.result

    async def progress(value, text):
        await runs.report(db, run, value, text)
        await ctx["events"].notify(run.id)

    try:
        if result.get("layer_document") and len(result.get("asset_ids", [])) == 2:
            candidates = await sessions.owned_assets(
                db, run.user_id, [uuid.UUID(x) for x in result["asset_ids"]]
            )
        else:
            source = (
                await sessions.owned_assets(db, run.user_id, [uuid.UUID(params["asset_id"])])
            )[0]
            key = source.storage_key
            await db.commit()
            await progress(10, "读取拆层时的画布")
            raw = await ctx["store"].get(key)
            image = await asyncio.to_thread(source_image, raw, params["document"])
            original = await asyncio.to_thread(png, image)
            if not run.result.get("subject_asset_id"):
                await progress(18, "本地模型正在分离主体")
                cutout = await asyncio.to_thread(
                    ctx.get("split_matting", remove_background),
                    raw,
                    params["document"],
                    settings.matting_model_path,
                )
                subject_png, mask, coverage = await asyncio.to_thread(
                    prepare_subject, image, cutout
                )
                run.params = {
                    **run.params,
                    "local_input": {
                        "mask_png": base64.b64encode(mask).decode(),
                        "mask_sha256": digest(mask),
                        "source_sha256": digest(original),
                    },
                }
                run.result = {**run.result, "mask_coverage": coverage}
                await save_part(db, ctx["store"], run, subject_png, AssetKind.SUBJECT)
            local = run.params["local_input"]
            mask = base64.b64decode(local["mask_png"], validate=True)
            if digest(mask) != local["mask_sha256"] or digest(original) != local["source_sha256"]:
                raise ProviderError("拆层输入快照校验失败，已停止执行")
            if is_local(params):
                if not run.result.get("background_asset_id"):
                    await progress(35, "本地LaMa正在修复被遮挡的背景")
                    background = await asyncio.to_thread(
                        repair_background, original, mask, settings.lama_model_path
                    )
                    await save_part(db, ctx["store"], run, background, AssetKind.BACKGROUND)
            else:
                provider = ctx.get("split_provider_factory", DashscopeRegion)(settings)
                remote_id = run.result.get("remote_task_id")
                if not run.result.get("background_asset_id"):
                    if not remote_id:
                        if run.result.get("submission_started"):
                            raise ProviderError(
                                "原拆层背景提交未确认，不会重复生成，请到百炼核对调用记录"
                            )
                        await progress(25, "本地预填主体遮挡的背景")
                        request_prompt = for_task(params)
                        cloud, cloud_mask = await asyncio.to_thread(prefill, original, mask)
                        run.result = {
                            **run.result,
                            "submission_started": True,
                            "recoverable": False,
                        }
                        await progress(35, "提交百炼背景补全")
                        remote_id = await provider.submit(cloud, cloud_mask, request_prompt)
                        run.result = {
                            **run.result,
                            "remote_task_id": remote_id,
                            "recoverable": True,
                        }
                        await db.commit()
                    await progress(45, "等待原背景补全任务")
                    generated = await provider.wait(remote_id)
                    background = await asyncio.to_thread(composite, original, generated, mask)
                    await progress(80, "保存背景图层")
                    await save_part(db, ctx["store"], run, background, AssetKind.BACKGROUND)
            candidates = await sessions.owned_assets(
                db,
                run.user_id,
                [
                    uuid.UUID(run.result["background_asset_id"]),
                    uuid.UUID(run.result["subject_asset_id"]),
                ],
            )
            document = split_document(
                image.width,
                image.height,
                candidates[0].id,
                candidates[1].id,
                run.id,
                local["mask_sha256"],
            )
            run.result = {
                **run.result,
                "layer_document": document,
                "asset_ids": [str(a.id) for a in candidates],
                "recoverable": True,
            }
            await db.commit()
        row = await sessions.load(db, run.user_id, uuid.UUID(params["session_id"]))
        await sessions.attach(db, row, candidates)
        await db.commit()
        run.result = {**run.result, "recoverable": False}
        await progress(95, "主体与背景已保存，请检查后应用拆层")
    except ExpansionError as exc:
        run.result = {
            **run.result,
            "recoverable": bool(run.result.get("remote_task_id")) and exc.recoverable,
        }
        await db.commit()
        raise
    except (StorageUnavailable, AssetSaveFailed, AssetCommitUncertain):
        await db.rollback()
        await db.refresh(run)
        run.result = {
            **run.result,
            "recoverable": not run.result.get("submission_started")
            or bool(run.result.get("remote_task_id")),
        }
        await db.commit()
        raise
    except ProviderError:
        run.result = {**run.result, "recoverable": False}
        await db.commit()
        raise
