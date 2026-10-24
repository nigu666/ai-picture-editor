import asyncio
import base64
import copy
import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, Response

from app.deps import CurrentUser, SessionDep, SettingsDep, StorageDep
from app.edits.geometry import editable
from app.edits.selection import overlay
from app.schemas.selection import PointsIn, PrepareIn, SelectionAction, StrokeIn
from app.services import sessions
from app.services.layer_documents import keys_for_document, preview_png, read_sources
from app.services.segmentation import SamBusy, SamUnavailable, engine
from app.services.selections import SelectionStore

router = APIRouter(tags=["selections"])


def store(request: Request, settings):
    return SelectionStore(request.app.state.event_bus.client, settings.queue_name)


async def inference(storage, key, document, user_id, settings, prompts):
    try:
        async with asyncio.timeout(90):
            raw = key if isinstance(key, bytes) else await storage.get(key)
            return await asyncio.to_thread(
                engine(str(settings.sam_model_dir.resolve())).run,
                raw,
                document,
                str(user_id),
                prompts,
            )
    except SamBusy as exc:
        raise HTTPException(429, str(exc)) from None
    except SamUnavailable as exc:
        raise HTTPException(503, str(exc)) from None
    except Exception:
        raise HTTPException(503, "SAM识别暂未完成，请重试或使用笔刷；原图与选区未改动") from None


async def sam_source(db, row, storage):
    if len(row.document["layers"]) > 1:
        document, owner = copy.deepcopy(row.document), row.user_id
        keys = await keys_for_document(db, owner, document)
        await db.commit()
        try:
            async with asyncio.timeout(30):
                data = await read_sources(storage, keys)
                flattened = await asyncio.to_thread(preview_png, data, document, None)
        except Exception:
            raise HTTPException(503, "合成画布暂时读取失败，原图和选区未修改") from None
        frame = {
            "width": document["width"],
            "height": document["height"],
            "layers": [
                {
                    "id": "selection-canvas",
                    "kind": "image",
                    "asset_id": next(
                        layer["asset_id"]
                        for layer in document["layers"]
                        if layer["kind"] == "image"
                    ),
                    "width": document["width"],
                    "height": document["height"],
                    "opacity": 1,
                    "visible": True,
                    "transform": {"x": 0, "y": 0, "scale_x": 1, "scale_y": 1, "rotation": 0},
                }
            ],
        }
        return frame, flattened, owner
    editable(row.document)
    document = copy.deepcopy(row.document)
    asset = (
        await sessions.owned_assets(db, row.user_id, [uuid.UUID(document["layers"][0]["asset_id"])])
    )[0]
    return document, asset.storage_key, row.user_id


@router.post("/sessions/{session_id}/selection/prepare")
async def prepare(
    session_id: uuid.UUID,
    body: PrepareIn,
    user: CurrentUser,
    db: SessionDep,
    settings: SettingsDep,
    storage: StorageDep,
):
    row = await sessions.load(db, user.id, session_id)
    sessions.check_version(row, body.revision)
    document, key, owner = await sam_source(db, row, storage)
    await db.commit()
    result = await inference(storage, key, document, owner, settings, None)
    await db.refresh(row, with_for_update=True)
    sessions.check_version(row, body.revision)
    await db.commit()
    return {"revision": body.revision, "ready": True, **result}


@router.post("/sessions/{session_id}/selection/points")
async def points(
    session_id: uuid.UUID,
    body: PointsIn,
    user: CurrentUser,
    db: SessionDep,
    settings: SettingsDep,
    storage: StorageDep,
    request: Request,
):
    row = await sessions.load(db, user.id, session_id)
    sessions.check_version(row, body.revision)
    document, key, owner = await sam_source(db, row, storage)

    async def make_mask():
        return await inference(
            storage, key, document, owner, settings, body.model_dump(mode="json")["prompts"]
        )

    return await store(request, settings).change(db, row, body, make_mask)


@router.get("/sessions/{session_id}/selection")
async def get_selection(
    session_id: uuid.UUID,
    revision: Annotated[int, Query(ge=1)],
    user: CurrentUser,
    db: SessionDep,
    settings: SettingsDep,
    request: Request,
):
    row = await sessions.load(db, user.id, session_id)
    sessions.check_version(row, revision)
    selected = store(request, settings)
    data = await selected.get(row)
    return selected.public(row, data)


@router.post("/sessions/{session_id}/selection/strokes")
async def stroke(
    session_id: uuid.UUID,
    body: StrokeIn,
    user: CurrentUser,
    db: SessionDep,
    settings: SettingsDep,
    request: Request,
):
    row = await sessions.load(db, user.id, session_id)
    return await store(request, settings).change(db, row, body)


@router.post("/sessions/{session_id}/selection/actions")
async def action(
    session_id: uuid.UUID,
    body: SelectionAction,
    user: CurrentUser,
    db: SessionDep,
    settings: SettingsDep,
    request: Request,
):
    row = await sessions.load(db, user.id, session_id)
    return await store(request, settings).change(db, row, body)


@router.get("/sessions/{session_id}/selection/mask")
async def mask(
    session_id: uuid.UUID,
    revision: Annotated[int, Query(ge=1)],
    version: Annotated[int, Query(ge=1)],
    user: CurrentUser,
    db: SessionDep,
    settings: SettingsDep,
    request: Request,
    preview: bool = False,
):
    row = await sessions.load(db, user.id, session_id)
    sessions.check_version(row, revision)
    data = await store(request, settings).get(row)
    if data["version"] != version:
        raise HTTPException(409, "遮罩版本已变化，请重新读取选区")
    if not data["selected_pixels"] or not data["png"]:
        raise HTTPException(404, "当前没有选区")
    await db.commit()
    raw = base64.b64decode(data["png"])
    if preview:
        raw = await asyncio.to_thread(overlay, raw)
    return Response(raw, media_type="image/png", headers={"Cache-Control": "no-store"})
