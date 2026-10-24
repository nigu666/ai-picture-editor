"""鉴权的调色源图与临时预览；图片只在内存中计算，不新增素材或历史。"""

import asyncio
import copy
import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.deps import CurrentUser, SessionDep, StorageDep
from app.edits.color import ColorParams, apply_document, source_png
from app.edits.geometry import editable
from app.models.edit_session import EditHistory
from app.services import sessions

router = APIRouter(prefix="/sessions/{session_id}", tags=["color"])


class PreviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1, strict=True)
    adjustments: ColorParams


async def snapshot(db, user_id, session_id, revision, previous=False):
    row = await sessions.load(db, user_id, session_id)
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
    editable(document)
    # 素材编号只从服务端文档取，不接受调用方指定路径或其他用户的素材。
    asset = (
        await sessions.owned_assets(db, user_id, [uuid.UUID(document["layers"][0]["asset_id"])])
    )[0]
    key = asset.storage_key
    await db.rollback()
    return document, key


async def render(db, user_id, session_id, revision, document, key, store, *, preview):
    try:
        async with asyncio.timeout(30):
            data = await store.get(key)
            png = await asyncio.to_thread(source_png, data, document, preview=preview)
    except Exception as exc:
        raise HTTPException(503, "调色画面暂时无法读取，请稍后重试") from exc
    row = await sessions.load(db, user_id, session_id)
    sessions.check_version(row, revision)
    await db.rollback()
    return Response(png, media_type="image/png", headers={"Cache-Control": "no-store"})


@router.post("/color-preview")
async def preview(
    session_id: uuid.UUID, body: PreviewIn, user: CurrentUser, db: SessionDep, store: StorageDep
):
    user_id = user.id
    document, key = await snapshot(db, user_id, session_id, body.revision)
    document = apply_document(document, body.adjustments)
    return await render(db, user_id, session_id, body.revision, document, key, store, preview=True)


@router.get("/color-source")
async def source(
    session_id: uuid.UUID,
    revision: Annotated[int, Query(ge=1)],
    user: CurrentUser,
    db: SessionDep,
    store: StorageDep,
    previous: bool = False,
):
    user_id = user.id
    document, key = await snapshot(db, user_id, session_id, revision, previous)
    return await render(db, user_id, session_id, revision, document, key, store, preview=False)
