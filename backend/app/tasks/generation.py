"""Worker 作业入口：领取记录 → Provider → 素材保存 → 任务终态。"""

import asyncio
import logging
import uuid

from app.db import session_scope
from app.providers import GenerateRequest, get_image_provider
from app.providers.base import ProviderError
from app.providers.reference_generation import ReferenceImageProvider
from app.services import generation, runs
from app.services.assets import AssetCommitUncertain, AssetSaveFailed, StorageUnavailable
from app.services.generation_references import reference_bytes
from app.services.matting import MattingUnavailable

logger = logging.getLogger(__name__)


async def generate_task(ctx: dict, run_id: str) -> None:
    async with session_scope(ctx["session_factory"]) as state_session:
        run = await runs.claim(state_session, uuid.UUID(run_id))
        if run is None:
            return
        await ctx["events"].notify(run.id)
        try:
            if run.tool in {
                "remove_background",
                "replace_background",
                "expand_canvas",
                "upscale_image",
                "erase_region",
                "replace_region",
                "split_layers",
                "promote_object",
                "edit_image",
            }:
                if run.tool == "remove_background":
                    from app.tasks.matting import execute
                elif run.tool == "replace_background":
                    from app.tasks.background import execute
                elif run.tool == "expand_canvas":
                    from app.tasks.outpainting import execute
                elif run.tool == "upscale_image":
                    from app.tasks.upscaling import execute
                elif run.tool == "split_layers":
                    from app.tasks.split import execute
                elif run.tool == "promote_object":
                    from app.tasks.promote import execute
                elif run.tool == "edit_image":
                    from app.tasks.canvas_edit import execute
                else:
                    from app.tasks.region import execute

                await execute(ctx, state_session, run)
                await runs.finish(state_session, run)
                await ctx["events"].notify(run.id)
                return
            if run.tool != "generate":
                raise ValueError("unknown task")
            reference_ids = run.params.get("reference_asset_ids", [])
            model_field = "reference_image_model" if reference_ids else "image_model"
            settings = ctx["settings"].model_copy(
                update={
                    "image_provider": run.params["provider"],
                    model_field: run.params.get("model", getattr(ctx["settings"], model_field)),
                }
            )
            # 测试可替换 Provider；正常独立 Worker 使用同一选择工厂。
            if reference_ids:
                provider = ctx.get("reference_provider_factory", ReferenceImageProvider)(settings)
                references = await reference_bytes(
                    state_session, ctx["store"], run.user_id, reference_ids
                )
            else:
                provider = ctx.get("provider_factory", get_image_provider)(settings)
                references = []
            request = (
                GenerateRequest(**run.params["request"], references=references)
                if reference_ids
                else GenerateRequest(**run.params["request"])
            )
            run.result = {
                "provider": provider.name,
                "is_mock": provider.name == "mock",
                "model": getattr(settings, model_field) if provider.name != "mock" else "mock",
                "generation_mode": "reference" if reference_ids else "text",
                "asset_ids": [],
            }
            await state_session.commit()

            async def progress(value: int, stage: str):
                await runs.report(state_session, run, value, stage)
                await ctx["events"].notify(run.id)

            async def saved(asset):
                run.result = {**run.result, "asset_ids": [*run.result["asset_ids"], str(asset.id)]}
                await state_session.commit()
                await ctx["events"].notify(run.id)

            async with session_scope(ctx["session_factory"]) as asset_session:
                await generation.generate_and_store(
                    asset_session, ctx["store"], run.user_id, provider, request, progress, saved
                )
            await runs.finish(state_session, run)
            await ctx["events"].notify(run.id)
        except asyncio.CancelledError:
            await state_session.rollback()
            await state_session.refresh(run)
            await runs.finish(state_session, run, "执行被中断，请核对已保存的素材")
            await ctx["events"].notify(run.id)
            raise
        except Exception as exc:
            await state_session.rollback()
            await state_session.refresh(run)
            safe = (
                ProviderError,
                StorageUnavailable,
                AssetSaveFailed,
                AssetCommitUncertain,
                MattingUnavailable,
            )
            message = str(exc) if isinstance(exc, safe) else "执行失败，请根据任务编号检查服务日志"
            # 不将原始连接字符串、签名 URL 或请求内容写入错误日志。
            logger.error("生成任务失败 run=%s error_type=%s", run_id, type(exc).__name__)
            await runs.finish(state_session, run, message)
            await ctx["events"].notify(run.id)
