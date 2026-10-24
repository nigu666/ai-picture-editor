"""所有素材引用先鉴权，再读取存储；不接受客户端文档或任意地址。"""

import copy
import io

from fastapi import HTTPException
from pydantic import ValidationError

from app.edits.render import render_document
from app.layers import MAX_SOURCE_PIXELS, LayerDocument, tool_supported
from app.services import sessions


def require_tool(document, tool):
    if not tool_supported(document, tool):
        if tool == "promote_object" and any(
            layer["kind"] == "text" for layer in document["layers"]
        ):
            raise HTTPException(409, "含可编辑文字层时暂不支持选区成层，请在添加文字前完成物体成层")
        raise HTTPException(409, "当前工具仅支持单图画布；多层画布请使用图层面板，或撤销回单图")


async def keys_for_document(db, user_id, document):
    try:
        validated = LayerDocument.model_validate(document)
    except ValidationError:
        raise HTTPException(422, "图层文档无效，未读取素材") from None
    assets = await sessions.owned_assets(
        db, user_id, [layer.asset_id for layer in validated.layers if layer.kind == "image"]
    )
    if sum(asset.width * asset.height for asset in assets) > MAX_SOURCE_PIXELS:
        raise HTTPException(422, "图层素材总像素过大，请减少图层或缩小图片")
    if sum(asset.size_bytes for asset in assets) > 64 * 1024 * 1024:
        raise HTTPException(422, "图层素材总文件大小超过64MB")
    return {str(asset.id): asset.storage_key for asset in assets}


async def read_sources(store, keys):
    data, total = {}, 0
    for asset_id, key in keys.items():
        raw = await store.get(key)
        total += len(raw)
        if total > 64 * 1024 * 1024:
            raise ValueError("combined source bytes limit")
        data[asset_id] = raw
    return data


async def read_snapshot(db, store, user_id, document):
    """读取提交时的全部图层；保持旧单图字节分支，读取不改会话与素材。"""
    keys = await keys_for_document(db, user_id, document)
    await db.commit()
    data = await read_sources(store, keys)
    if len(document["layers"]) == 1:
        return data[str(document["layers"][0]["asset_id"])]
    return data


def preview_png(data, document, max_side):
    image = render_document(data, copy.deepcopy(document), max_side=max_side)
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()
