import uuid
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.deps import CurrentUser, SessionDep, StorageDep
from app.models.edit_session import EditSession
from app.schemas.session import AdoptInput, AttachInput, RenameInput, SessionCreate, VersionInput
from app.services import sessions as service
from app.services.exports import BundleInput, ExportInput, download

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.get("")
async def list_sessions(
    user: CurrentUser, db: SessionDep, limit: Annotated[int, Query(ge=1, le=200)] = 100
) -> list[dict]:
    rows = await db.scalars(
        select(EditSession)
        .where(EditSession.user_id == user.id)
        .order_by(EditSession.updated_at.desc(), EditSession.id)
        .limit(limit)
    )
    return [service.summary(row) for row in rows]


@router.post("", status_code=201)
async def create_session(
    body: SessionCreate, user: CurrentUser, db: SessionDep, store: StorageDep
) -> dict:
    row = await service.create(db, user.id, body.current_asset_id, body.asset_ids, body.title)
    result = await service.describe(db, row, store)
    await db.commit()
    return result


@router.get("/{session_id}")
async def get_session(
    session_id: uuid.UUID, user: CurrentUser, db: SessionDep, store: StorageDep
) -> dict:
    return await service.describe(db, await service.load(db, user.id, session_id), store)


@router.post("/{session_id}/adopt")
async def adopt(
    session_id: uuid.UUID, body: AdoptInput, user: CurrentUser, db: SessionDep, store: StorageDep
) -> dict:
    row = await service.load(db, user.id, session_id)
    service.check_version(row, body.revision)
    await service.adopt(db, row, body.asset_id)
    result = await service.describe(db, row, store)
    await db.commit()
    return result


@router.post("/{session_id}/assets")
async def attach(
    session_id: uuid.UUID, body: AttachInput, user: CurrentUser, db: SessionDep, store: StorageDep
) -> dict:
    row = await service.load(db, user.id, session_id)
    service.check_version(row, body.revision)
    await service.attach(db, row, await service.owned_assets(db, user.id, body.asset_ids))
    result = await service.describe(db, row, store)
    await db.commit()
    return result


@router.post("/{session_id}/rename")
async def rename(
    session_id: uuid.UUID, body: RenameInput, user: CurrentUser, db: SessionDep, store: StorageDep
) -> dict:
    row = await service.load(db, user.id, session_id)
    service.check_version(row, body.revision)
    row.title = body.title
    await db.flush()
    result = await service.describe(db, row, store)
    await db.commit()
    return result


async def move(session_id, body, user, db, store, direction):
    row = await service.load(db, user.id, session_id)
    service.check_version(row, body.revision)
    await service.navigate(db, row, direction)
    result = await service.describe(db, row, store)
    await db.commit()
    return result


@router.post("/{session_id}/undo")
async def undo(
    session_id: uuid.UUID, body: VersionInput, user: CurrentUser, db: SessionDep, store: StorageDep
) -> dict:
    return await move(session_id, body, user, db, store, -1)


@router.post("/{session_id}/redo")
async def redo(
    session_id: uuid.UUID, body: VersionInput, user: CurrentUser, db: SessionDep, store: StorageDep
) -> dict:
    return await move(session_id, body, user, db, store, 1)


@router.post("/{session_id}/export")
async def export_canvas(
    session_id: uuid.UUID, body: ExportInput, user: CurrentUser, db: SessionDep, store: StorageDep
):
    return await download(db, store, user.id, session_id, body)


@router.post("/{session_id}/export-bundle")
async def export_bundle(
    session_id: uuid.UUID, body: BundleInput, user: CurrentUser, db: SessionDep, store: StorageDep
):
    return await download(db, store, user.id, session_id, body)
