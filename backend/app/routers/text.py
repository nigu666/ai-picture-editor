"""本地OCR只读识别；用户校对后明确添加文字层，沿用修订与历史。"""

import asyncio
import copy
import hashlib
import json
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import Field, ValidationError, model_validator

from app.deps import CurrentUser, SessionDep, SettingsDep, StorageDep
from app.edits.text import font_path
from app.layers import LayerDocument, LayerModel, TextLayer
from app.services import ocr, sessions
from app.services.layer_documents import keys_for_document, preview_png, read_sources

router = APIRouter(prefix="/sessions/{session_id}", tags=["text"])


class Revision(LayerModel):
    revision: int = Field(ge=1, strict=True)


class TextInput(LayerModel):
    text: str = Field(min_length=1, max_length=1000)
    x: float = Field(ge=-100000, le=100000)
    y: float = Field(ge=-100000, le=100000)
    width: int = Field(ge=1, le=4096, strict=True)
    height: int = Field(ge=1, le=4096, strict=True)
    font_size: int = Field(default=32, ge=6, le=512, strict=True)
    fill: str = Field(default="#172b43", pattern=r"^#[0-9a-fA-F]{6}$")

    @model_validator(mode="after")
    def valid(self):
        TextLayer.printable(self.text)
        if self.width * self.height > 4_000_000:
            raise ValueError("文字框过大，请缩小文字框")
        return self


class AddText(Revision):
    request_id: uuid.UUID
    layers: list[TextInput] = Field(min_length=1, max_length=20)


@router.get("/text-options")
async def options(session_id: uuid.UUID, user: CurrentUser, db: SessionDep, settings: SettingsDep):
    await sessions.load(db, user.id, session_id)
    await db.rollback()
    try:
        font_path()
        font_ready = True
    except ValueError:
        font_ready = False
    try:
        ocr.model_directory()
        ocr_ready = settings.ocr_provider == "rapidocr"
    except ocr.OcrUnavailable:
        ocr_ready = False
    return dict(
        ocr_enabled=ocr_ready,
        text_enabled=font_ready,
        font_name="微软雅黑",
        provider=settings.ocr_provider,
    )


@router.post("/ocr")
async def recognize(
    session_id: uuid.UUID,
    body: Revision,
    user: CurrentUser,
    db: SessionDep,
    store: StorageDep,
    settings: SettingsDep,
):
    if settings.ocr_provider != "rapidocr":
        raise HTTPException(422, "本地OCR未启用，仍可手动添加文字")
    owner = user.id
    row = await sessions.load(db, owner, session_id)
    sessions.check_version(row, body.revision)
    document = copy.deepcopy(row.document)
    keys = await keys_for_document(db, owner, document)
    await db.rollback()
    try:
        async with asyncio.timeout(90):
            data = await read_sources(store, keys)
            raw = await asyncio.to_thread(preview_png, data, document, 2048)
            result = await asyncio.to_thread(ocr.detect, raw, document["width"], document["height"])
    except ocr.OcrBusy as exc:
        raise HTTPException(429, str(exc)) from None
    except ocr.OcrUnavailable as exc:
        raise HTTPException(503, str(exc)) from None
    except Exception:
        raise HTTPException(503, "文字识别暂未完成，原图和编辑记录未修改") from None
    row = await sessions.load(db, owner, session_id)
    sessions.check_version(row, body.revision)
    await db.rollback()
    return {"revision": body.revision, "provider": "rapidocr-local", **result}


@router.post("/text-layers")
async def add_text(
    session_id: uuid.UUID, body: AddText, user: CurrentUser, db: SessionDep, store: StorageDep
):
    row = await sessions.load(db, user.id, session_id)
    fingerprint = hashlib.sha256(
        json.dumps(
            [entry.model_dump(mode="json") for entry in body.layers],
            sort_keys=True,
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    ids = [f"text-{body.request_id}-{index}" for index in range(len(body.layers))]
    previous = [
        item for item in row.document["layers"] if item["id"].startswith(f"text-{body.request_id}-")
    ]
    if previous:
        if {item["id"] for item in previous} != set(ids) or any(
            item.get("source_hash") != fingerprint for item in previous
        ):
            raise HTTPException(409, "此请求编号已用于其他文字，请先核对画布")
        return await sessions.describe(db, row, store)
    sessions.check_version(row, body.revision)
    try:
        font_path()
    except ValueError as exc:
        raise HTTPException(503, str(exc)) from None
    doc = copy.deepcopy(row.document)
    if "adjustments" in doc:
        doc["layers"][0]["adjustments"] = doc.pop("adjustments")
    for index, entry in enumerate(body.layers):
        doc["layers"].append(
            dict(
                id=ids[index],
                kind="text",
                name="文字 · " + entry.text.strip().split("\n")[0][:18],
                asset_id=None,
                width=entry.width,
                height=entry.height,
                text=entry.text,
                font_family="yahei",
                font_size=entry.font_size,
                fill=entry.fill,
                align="left",
                visible=True,
                locked=False,
                opacity=1,
                transform=dict(x=entry.x, y=entry.y, scale_x=1, scale_y=1, rotation=0),
                source_hash=fingerprint,
            )
        )
    try:
        LayerDocument.model_validate(doc)
    except ValidationError:
        raise HTTPException(422, "文字数量、长度或画布合成预算超出限制，请减少文字后重试") from None
    await keys_for_document(db, user.id, doc)
    await sessions.apply_edit(db, row, doc, "add_text_layers")
    result = await sessions.describe(db, row, store)
    await db.commit()
    return result


@router.post("/text-layers/{layer_id}/remove")
async def remove_text(
    session_id: uuid.UUID,
    layer_id: str,
    body: Revision,
    user: CurrentUser,
    db: SessionDep,
    store: StorageDep,
):
    row = await sessions.load(db, user.id, session_id)
    sessions.check_version(row, body.revision)
    target = next((item for item in row.document["layers"] if item["id"] == layer_id), None)
    if target is None or target["kind"] != "text":
        raise HTTPException(404, "文字图层不存在，请重新读取")
    doc = copy.deepcopy(row.document)
    doc["layers"] = [item for item in doc["layers"] if item["id"] != layer_id]
    LayerDocument.model_validate(doc)
    await sessions.apply_edit(db, row, doc, "remove_text_layer")
    result = await sessions.describe(db, row, store)
    await db.commit()
    return result
