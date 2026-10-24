import asyncio
import uuid
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status

from app.deps import CurrentUser, SessionDep, StorageDep
from app.schemas.asset import AssetOut
from app.services import assets as service
from app.services.images import MAX_FILE_BYTES, ImageRejected, probe

router = APIRouter(prefix="/assets", tags=["assets"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def upload(
    user: CurrentUser,
    session: SessionDep,
    store: StorageDep,
    file: Annotated[UploadFile, File()],
) -> AssetOut:
    try:
        data = await file.read(MAX_FILE_BYTES + 1)
    finally:
        await file.close()
    if len(data) > MAX_FILE_BYTES:
        raise HTTPException(413, "文件超过 20 MB 上限")
    try:
        meta = await asyncio.to_thread(probe, data)
    except ImageRejected as exc:
        raise HTTPException(422, str(exc)) from exc
    try:
        asset = await service.create_from_bytes(session, store, user.id, data, meta)
    except (
        service.StorageUnavailable,
        service.AssetSaveFailed,
        service.AssetCommitUncertain,
    ) as exc:
        raise HTTPException(503, str(exc)) from exc
    return AssetOut.of(asset, store)


@router.get("")
async def list_assets(
    user: CurrentUser,
    session: SessionDep,
    store: StorageDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[AssetOut]:
    return [
        AssetOut.of(asset, store) for asset in await service.list_for_user(session, user.id, limit)
    ]


@router.get("/{asset_id}")
async def get_asset(
    asset_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    store: StorageDep,
) -> AssetOut:
    asset = await service.get_for_user(session, user.id, asset_id)
    if asset is None:
        raise HTTPException(404, "素材不存在")
    return AssetOut.of(asset, store)
