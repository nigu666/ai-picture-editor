"""对象文件与素材记录关联；已知写库失败补偿，提交结果不确定时不盲删。"""

import logging
import uuid

from botocore.exceptions import BotoCoreError, ClientError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Asset, AssetKind, AssetSource
from app.services.images import ImageMeta
from app.storage import ObjectStorage

logger = logging.getLogger(__name__)


class StorageUnavailable(Exception):
    pass


class AssetSaveFailed(Exception):
    pass


class AssetCommitUncertain(Exception):
    pass


async def _discard_uncommitted(session: AsyncSession, store: ObjectStorage, key: str) -> None:
    try:
        await session.rollback()
    finally:
        try:
            await store.delete(key)
        except (BotoCoreError, ClientError, OSError):
            logger.error("素材写库失败，临时对象清理失败；需核对对象", extra={"storage_key": key})


async def create_from_bytes(
    session: AsyncSession,
    store: ObjectStorage,
    user_id: uuid.UUID,
    data: bytes,
    meta: ImageMeta,
    *,
    kind: AssetKind = AssetKind.ORIGINAL,
    source: AssetSource = AssetSource.UPLOAD,
) -> Asset:
    asset_id = uuid.uuid4()
    key = f"users/{user_id}/{asset_id}.{meta.extension}"
    try:
        await store.put(key, data, meta.content_type)
    except (BotoCoreError, ClientError, OSError) as exc:
        raise StorageUnavailable("图片存储暂不可用，请稍后重试") from exc
    asset = Asset(
        id=asset_id,
        user_id=user_id,
        kind=kind,
        source=source,
        storage_key=key,
        image_format=meta.image_format,
        width=meta.width,
        height=meta.height,
        size_bytes=meta.size_bytes,
        has_alpha=meta.has_alpha,
    )
    session.add(asset)
    try:
        await session.flush()
    except SQLAlchemyError as exc:
        await _discard_uncommitted(session, store, key)
        raise AssetSaveFailed("素材记录未保存，请稍后重试") from exc
    try:
        await session.commit()
    except IntegrityError as exc:
        await _discard_uncommitted(session, store, key)
        raise AssetSaveFailed("素材记录未保存，请稍后重试") from exc
    except SQLAlchemyError as exc:
        await session.rollback()
        # 例如提交成功但确认响应丢失，删除对象可能破坏已提交的记录。
        logger.error("素材提交结果未确认，保留对象待核对", extra={"asset_id": str(asset_id)})
        raise AssetCommitUncertain("保存结果未确认，请稍后刷新素材列表") from exc
    return asset


async def list_for_user(session: AsyncSession, user_id: uuid.UUID, limit: int) -> list[Asset]:
    result = await session.scalars(
        select(Asset).where(Asset.user_id == user_id).order_by(Asset.created_at.desc()).limit(limit)
    )
    return list(result)


async def get_for_user(
    session: AsyncSession, user_id: uuid.UUID, asset_id: uuid.UUID
) -> Asset | None:
    return await session.scalar(select(Asset).where(Asset.id == asset_id, Asset.user_id == user_id))
