"""成层分阶段保存；原任务恢复只查询同一个百炼任务。"""

import asyncio
import base64
import uuid

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError

from app.edits.promote import (
    checked_image,
    cut_object,
    document_for,
    expanded,
    flatten,
    punch,
    repaired_layer,
    selection_mask,
    signature,
)
from app.edits.split import prefill
from app.edits.background_repair import configured, for_task, is_local
from app.models import Asset, AssetKind, AssetSource
from app.providers.base import ProviderError
from app.providers.region import DashscopeRegion, ExpansionError
from app.services import assets, runs, sessions
from app.services.assets import AssetCommitUncertain, AssetSaveFailed, StorageUnavailable
from app.services.layer_documents import keys_for_document, read_sources
from app.tools.promote import LOCAL_NAME, NAME
from app.services.inpainting import repair as repair_background


async def save_part(db, store, run, raw, role, kind):
    asset_id = uuid.uuid5(run.id, "promote:" + role)
    known = await db.get(Asset, asset_id)
    if known:
        if known.user_id != run.user_id or known.kind != kind:
            raise ProviderError("成层素材归属不符")
        return known
    meta = await asyncio.to_thread(checked_image, raw)
    key = f"users/{run.user_id}/{asset_id}.png"
    try:
        await store.put(key, raw, meta.content_type)
    except (BotoCoreError, ClientError, OSError):
        raise StorageUnavailable("成层素材暂未保存，可继续原任务") from None
    item = Asset(
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
    db.add(item)
    run.result = {
        **run.result,
        "parts": {**run.result["parts"], role: str(asset_id)},
        "recoverable": True,
    }
    try:
        await db.flush()
    except SQLAlchemyError:
        await assets._discard_uncommitted(db, store, key)
        raise AssetSaveFailed("成层素材记录未保存，请核对原任务") from None
    try:
        await db.commit()
    except SQLAlchemyError:
        await db.rollback()
        raise AssetCommitUncertain("成层保存回执未确认，保留对象并核对原任务") from None
    return item


async def execute(ctx, db, run):
    settings, params = ctx["settings"], run.params
    local = is_local(params)
    configured(settings, local=local)
    if params["provider"] != (LOCAL_NAME if local else NAME) or params["model"] != (
        "lama-onnx" if local else settings.region_model
    ):
        raise ProviderError("成层配置与原任务不符，请核对后恢复")

    async def progress(value, text):
        await runs.report(db, run, value, text)
        await ctx["events"].notify(run.id)

    try:
        if not run.result.get("layer_document"):
            document = params["document"]
            keys = await keys_for_document(db, run.user_id, document)
            await db.commit()
            await progress(10, "合成提交时的画布与固定选区")
            data = await read_sources(ctx["store"], keys)
            original = await asyncio.to_thread(flatten, data, document)
            mask = await asyncio.to_thread(
                selection_mask,
                base64.b64decode(params["mask_png"], validate=True),
                (document["width"], document["height"]),
            )
            if signature(mask) != params["mask_sha256"]:
                raise ProviderError("成层选区快照校验失败")
            cut, box = await asyncio.to_thread(cut_object, original, mask)
            roles = ["background", "object"] + (
                []
                if len(document["layers"]) == 1
                else ["rest-" + item["id"] for item in document["layers"]]
            )
            # 在提交云端前验证新文档预算，防止完成付费任务后才发现超过图层上限。
            await asyncio.to_thread(
                document_for,
                document,
                run.id,
                {key: uuid.uuid5(run.id, "promote:" + key) for key in roles},
                box,
                params["mask_sha256"],
            )
            if "object" not in run.result["parts"]:
                await progress(18, "保存裁切的透明物体")
                await save_part(db, ctx["store"], run, cut, "object", AssetKind.SUBJECT)
            if len(document["layers"]) > 1:
                for index, item in enumerate(document["layers"]):
                    role = "rest-" + item["id"]
                    if role not in run.result["parts"]:
                        await progress(20 + index, "保留各层变换并移除原位置的物体")
                        raw = await asyncio.to_thread(punch, data[item["asset_id"]], item, mask)
                        await save_part(db, ctx["store"], run, raw, role, AssetKind.SUBJECT)
            if "background" not in run.result["parts"]:
                if is_local(params):
                    await progress(45, "本地LaMa正在修复选区原位置")
                    generated = await asyncio.to_thread(
                        repair_background, original, expanded(mask), settings.lama_model_path
                    )
                else:
                    provider = ctx.get("promote_provider_factory", DashscopeRegion)(settings)
                    remote_id = run.result.get("remote_task_id")
                    if not remote_id:
                        if run.result.get("submission_started"):
                            raise ProviderError("背景提交未确认，不会重复生成，请到百炼核对记录")
                        request_prompt = for_task(params)
                        cloud, cloud_mask = await asyncio.to_thread(
                            prefill, original, expanded(mask)
                        )
                        run.result = {
                            **run.result,
                            "submission_started": True,
                            "recoverable": False,
                        }
                        await progress(42, "提交选区原位置的背景补全")
                        remote_id = await provider.submit(cloud, cloud_mask, request_prompt)
                        run.result = {
                            **run.result,
                            "remote_task_id": remote_id,
                            "recoverable": True,
                        }
                        await db.commit()
                    await progress(50, "查询原背景补全任务")
                    generated = await provider.wait(remote_id)
                if len(document["layers"]) == 1:
                    raw = await asyncio.to_thread(
                        repaired_layer, generated, mask.size, mask, original
                    )
                else:
                    raw = await asyncio.to_thread(repaired_layer, generated, mask.size, mask)
                await save_part(db, ctx["store"], run, raw, "background", AssetKind.BACKGROUND)
            result_doc = document_for(
                document, run.id, run.result["parts"], box, params["mask_sha256"]
            )
            await keys_for_document(db, run.user_id, result_doc)
            run.result = {
                **run.result,
                "layer_document": result_doc,
                "asset_ids": [item["asset_id"] for item in result_doc["layers"]],
                "object_asset_id": run.result["parts"]["object"],
                "background_asset_id": run.result["parts"]["background"],
                "recoverable": True,
            }
            await db.commit()
        candidates = await sessions.owned_assets(
            db, run.user_id, [uuid.UUID(value) for value in run.result["asset_ids"]]
        )
        row = await sessions.load(db, run.user_id, uuid.UUID(params["session_id"]))
        await sessions.attach(db, row, candidates)
        await db.commit()
        run.result = {**run.result, "recoverable": False}
        await progress(95, "独立物体与修复结果已保存，请检查后应用")
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
    except (HTTPException, ProviderError) as exc:
        # 已完成文档仅在候选墙挂接失败时可恢复，恢复不会重新生成。
        run.result = {**run.result, "recoverable": bool(run.result.get("layer_document"))}
        await db.commit()
        raise ProviderError(
            str(exc.detail) if isinstance(exc, HTTPException) else str(exc)
        ) from None
