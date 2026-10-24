"""参考图在提交与Worker两端查归属；数据库只记录素材编号，不存base64。"""

import uuid

from botocore.exceptions import BotoCoreError, ClientError

from app.providers.base import ProviderError
from app.providers.reference_generation import validate_metadata
from app.services import assets


async def owned_references(db, user_id, ids):
    if len(ids) > 3 or len(set(ids)) != len(ids):
        raise ProviderError("参考图最多3张，不能重复选择同一素材")
    records = []
    for asset_id in ids:
        asset = await assets.get_for_user(db, user_id, uuid.UUID(str(asset_id)))
        if asset is None:
            raise ProviderError("参考素材不存在或不属于当前账号，本次未调用模型")
        validate_metadata(asset)
        records.append(asset)
    return records


async def reference_bytes(db, store, user_id, ids):
    records = await owned_references(db, user_id, ids)
    try:
        return [await store.get(asset.storage_key) for asset in records]
    except (BotoCoreError, ClientError, OSError):
        raise ProviderError("参考图读取失败，本次未调用模型，请先核对图片存储") from None
