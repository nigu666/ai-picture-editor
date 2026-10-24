"""短暂渲染位置与大小草稿；预览不写入会话、素材或队列。"""

import asyncio
import io
import uuid

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

from app.deps import CurrentUser, SessionDep, StorageDep
from app.edits.layout import LayoutParams, apply_document
from app.edits.render import render_document
from app.routers.color import snapshot
from app.services import sessions

router = APIRouter(prefix="/sessions/{session_id}", tags=["layout"])


class PreviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1, strict=True)
    placement: LayoutParams


def preview_png(data: bytes, document: dict) -> bytes:
    image = render_document(data, document, max_side=1536)
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


@router.post("/layout-preview")
async def preview(
    session_id: uuid.UUID, body: PreviewIn, user: CurrentUser, db: SessionDep, store: StorageDep
):
    user_id = user.id
    document, key = await snapshot(db, user_id, session_id, body.revision)
    document = apply_document(document, body.placement)
    try:
        async with asyncio.timeout(30):
            data = await store.get(key)
            png = await asyncio.to_thread(preview_png, data, document)
    except Exception as exc:
        raise HTTPException(503, "位置预览暂时无法读取，请稍后重试") from exc
    row = await sessions.load(db, user_id, session_id)
    sessions.check_version(row, body.revision)
    await db.rollback()
    return Response(png, media_type="image/png", headers={"Cache-Control": "no-store"})
