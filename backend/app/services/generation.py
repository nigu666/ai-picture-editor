"""Provider 到素材保存的调用链；回调供 Worker 记录进度和已保存候选。"""

import asyncio
import uuid
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Asset, AssetKind, AssetSource
from app.providers.base import (
    GenerateRequest,
    ImageProvider,
    ProgressCallback,
    ProviderError,
    validate_request,
)
from app.services.assets import create_from_bytes
from app.services.images import ImageRejected, probe
from app.storage import ObjectStorage


async def generate_and_store(
    session: AsyncSession,
    store: ObjectStorage,
    user_id: uuid.UUID,
    provider: ImageProvider,
    request: GenerateRequest,
    on_progress: ProgressCallback | None = None,
    on_asset_saved: Callable[[Asset], Awaitable[None]] | None = None,
    *,
    asset_source: AssetSource = AssetSource.GENERATE,
) -> list[Asset]:
    validate_request(request)

    async def generating_progress(value: int, stage: str) -> None:
        if on_progress:
            await on_progress(min(80, max(0, int(value * 0.8))), stage)

    raw_images = await provider.generate(request, generating_progress)
    if not isinstance(raw_images, list) or len(raw_images) != request.count:
        raise ProviderError("Provider 返回的图片数量不符合请求")
    metadata = []
    for raw in raw_images:
        if not isinstance(raw, bytes):
            raise ProviderError("Provider 未返回图片字节")
        try:
            meta = await asyncio.to_thread(probe, raw)
        except ImageRejected as exc:
            raise ProviderError("Provider 返回了无效图片") from exc
        if (meta.width, meta.height) != (request.width, request.height):
            raise ProviderError("Provider 返回尺寸不符合当前生成契约")
        metadata.append(meta)
    assets = []
    for index, (raw, meta) in enumerate(zip(raw_images, metadata, strict=True)):
        asset = await create_from_bytes(
            session,
            store,
            user_id,
            raw,
            meta,
            kind=AssetKind.GENERATED,
            source=asset_source,
        )
        assets.append(asset)
        if on_asset_saved:
            await on_asset_saved(asset)
        if on_progress:
            await on_progress(
                80 + int(20 * (index + 1) / request.count),
                f"素材已保存 {index + 1}/{request.count}",
            )
    return assets
