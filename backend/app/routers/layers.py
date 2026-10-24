"""添加已加入会话的图片为新图层；合成预览只读、不新增素材。"""

import asyncio
import copy
import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.deps import CurrentUser, SessionDep, StorageDep
from app.edits.layer_controls import LayerEdit, apply_document
from app.layers import MAX_LAYERS
from app.models.edit_session import EditHistory, SessionAsset
from app.services import sessions
from app.services.layer_documents import keys_for_document, preview_png, read_sources

router = APIRouter(prefix="/sessions/{session_id}", tags=["layers"])


class PreviewLayer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1, strict=True)
    params: LayerEdit


@router.post("/layers/preview")
async def preview_layer(
    session_id: uuid.UUID, body: PreviewLayer, user: CurrentUser, db: SessionDep, store: StorageDep
):
    owner = user.id
    row = await sessions.load(db, owner, session_id)
    sessions.check_version(row, body.revision)
    document = apply_document(row.document, body.params)
    keys = await keys_for_document(db, owner, document)
    await db.rollback()
    try:
        async with asyncio.timeout(30):
            data = await read_sources(store, keys)
            png = await asyncio.to_thread(preview_png, data, document, 1536)
    except Exception:
        raise HTTPException(503, "图层预览读取失败，原图和编辑记录仍保留") from None
    row = await sessions.load(db, owner, session_id)
    sessions.check_version(row, body.revision)
    await db.rollback()
    return Response(png, media_type="image/png", headers={"Cache-Control": "no-store"})


class AddLayer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1, strict=True)
    asset_id: uuid.UUID
    request_id: uuid.UUID


@router.post("/layers")
async def add(
    session_id: uuid.UUID, body: AddLayer, user: CurrentUser, db: SessionDep, store: StorageDep
):
    row = await sessions.load(db, user.id, session_id)
    layer_id = "image-" + str(body.request_id)
    previous = next((layer for layer in row.document["layers"] if layer["id"] == layer_id), None)
    if previous is not None:
        if previous["asset_id"] != str(body.asset_id):
            raise HTTPException(409, "此请求编号已用于另一张图片，请先核对图层")
        return await sessions.describe(db, row, store)
    sessions.check_version(row, body.revision)
    if len(row.document["layers"]) >= MAX_LAYERS:
        raise HTTPException(422, f"最多保留{MAX_LAYERS}个图层")
    asset = (await sessions.owned_assets(db, user.id, [body.asset_id]))[0]
    if await db.get(SessionAsset, (row.id, asset.id)) is None:
        raise HTTPException(422, "请先将图片加入当前会话候选，再添加为图层")
    document = copy.deepcopy(row.document)
    # 旧全局调色参数实际只作用于底图，迁移为底图参数后新层不继承。
    if "adjustments" in document:
        document["layers"][0]["adjustments"] = document.pop("adjustments")
    scale = min(1, document["width"] / asset.width, document["height"] / asset.height)
    document["layers"].append(
        {
            "id": layer_id,
            "kind": "image",
            "name": f"图片图层 {len(document['layers']) + 1}",
            "asset_id": str(asset.id),
            "width": asset.width,
            "height": asset.height,
            "locked": False,
            "visible": True,
            "opacity": 1,
            "transform": {
                "x": (document["width"] - asset.width * scale) / 2,
                "y": (document["height"] - asset.height * scale) / 2,
                "scale_x": scale,
                "scale_y": scale,
                "rotation": 0,
            },
        }
    )
    document["schema_version"] = 1
    await keys_for_document(db, user.id, document)
    await sessions.apply_edit(db, row, document, "add_image_layer")
    result = await sessions.describe(db, row, store)
    await db.commit()
    return result


@router.get("/canvas-render")
async def render(
    session_id: uuid.UUID,
    revision: Annotated[int, Query(ge=1)],
    user: CurrentUser,
    db: SessionDep,
    store: StorageDep,
    previous: bool = False,
    max_side: Annotated[int, Query(ge=32, le=2048)] = 1536,
):
    owner = user.id
    row = await sessions.load(db, owner, session_id)
    sessions.check_version(row, revision)
    document = row.document
    if previous:
        history = await db.scalar(
            select(EditHistory).where(
                EditHistory.session_id == row.id, EditHistory.seq == row.history_seq - 1
            )
        )
        if history is None:
            raise HTTPException(409, "没有上一版本画布")
        document = history.document
    document = copy.deepcopy(document)
    keys = await keys_for_document(db, owner, document)
    await db.rollback()
    try:
        async with asyncio.timeout(30):
            data = await read_sources(store, keys)
            png = await asyncio.to_thread(preview_png, data, document, max_side)
    except Exception:
        raise HTTPException(503, "图层合成预览读取失败，请重新读取图片；原图与历史仍保留") from None
    row = await sessions.load(db, owner, session_id)
    sessions.check_version(row, revision)
    await db.rollback()
    return Response(png, media_type="image/png", headers={"Cache-Control": "no-store"})
