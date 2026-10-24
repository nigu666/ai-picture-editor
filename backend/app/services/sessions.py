"""行锁串行化同会话写入；revision 始终递增，history_seq 可撤销。

只写画布快照，不重编码图像。图片墙独立保留候选，采用才产生编辑历史。
"""

import uuid

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Asset
from app.models.edit_session import EditHistory, EditSession, SessionAsset
from app.schemas.asset import AssetOut
from app.storage import ObjectStorage

HISTORY_LIMIT = 20
WALL_LIMIT = 100


def document_of(asset: Asset) -> dict:
    return {
        "width": asset.width,
        "height": asset.height,
        "layers": [
            {
                "id": "base",
                "kind": "image",
                "name": "底图",
                "asset_id": str(asset.id),
                "width": asset.width,
                "height": asset.height,
                "locked": True,
                "visible": True,
                "opacity": 1,
                "transform": {"x": 0, "y": 0, "scale_x": 1, "scale_y": 1, "rotation": 0},
            }
        ],
    }


async def owned_assets(db: AsyncSession, user_id: uuid.UUID, ids: list[uuid.UUID]) -> list[Asset]:
    unique = list(dict.fromkeys(ids))
    rows = list(
        await db.scalars(select(Asset).where(Asset.user_id == user_id, Asset.id.in_(unique)))
    )
    if len(rows) != len(unique):
        raise HTTPException(404, "素材不存在或不属于当前账号")
    by_id = {row.id: row for row in rows}
    return [by_id[item] for item in unique]


async def load(db: AsyncSession, user_id: uuid.UUID, session_id: uuid.UUID) -> EditSession:
    row = await db.scalar(
        select(EditSession)
        .where(EditSession.id == session_id, EditSession.user_id == user_id)
        .with_for_update()
    )
    if row is None:
        raise HTTPException(404, "编辑会话不存在")
    return row


def check_version(row: EditSession, revision: int) -> None:
    if row.revision != revision:
        raise HTTPException(409, "画布已在其他页面更新，请重新读取后再操作")


async def attach(db: AsyncSession, row: EditSession, assets: list[Asset]) -> None:
    wall = list(
        await db.scalars(
            select(SessionAsset)
            .where(SessionAsset.session_id == row.id)
            .order_by(SessionAsset.position)
        )
    )
    known = {item.asset_id for item in wall}
    new = [item for item in assets if item.id not in known]
    if len(wall) + len(new) > WALL_LIMIT:
        raise HTTPException(422, "每个会话最多保留 100 张候选，请新建会话")
    position = max((item.position for item in wall), default=0)
    for index, asset in enumerate(new, 1):
        db.add(SessionAsset(session_id=row.id, asset_id=asset.id, position=position + index))
    await db.flush()


async def create(
    db: AsyncSession,
    user_id: uuid.UUID,
    current_id: uuid.UUID,
    asset_ids: list[uuid.UUID],
    title: str,
) -> EditSession:
    assets = await owned_assets(db, user_id, [current_id, *asset_ids])
    row = EditSession(
        user_id=user_id,
        title=title,
        original_asset_id=current_id,
        current_asset_id=current_id,
        document=document_of(assets[0]),
        revision=1,
        history_seq=1,
    )
    db.add(row)
    await db.flush()
    await attach(db, row, assets)
    db.add(
        EditHistory(
            session_id=row.id,
            seq=1,
            action="create_session",
            current_asset_id=current_id,
            document=row.document,
        )
    )
    await db.flush()
    return row


async def adopt(db: AsyncSession, row: EditSession, asset_id: uuid.UUID) -> None:
    asset = (await owned_assets(db, row.user_id, [asset_id]))[0]
    member = await db.get(SessionAsset, (row.id, asset_id))
    if member is None:
        raise HTTPException(422, "请先将图片加入本会话候选，再采用")
    if row.current_asset_id == asset_id and len(row.document["layers"]) == 1:
        return
    await apply_edit(db, row, document_of(asset), "adopt_asset", current_asset_id=asset_id)


async def apply_edit(
    db: AsyncSession,
    row: EditSession,
    document: dict,
    action: str,
    *,
    current_asset_id: uuid.UUID | None = None,
) -> None:
    """画布文档和采用共用同一历史入口；无变化时不制造空版本。"""
    current = current_asset_id or row.current_asset_id
    if row.document == document and row.current_asset_id == current:
        return
    await db.execute(
        delete(EditHistory).where(
            EditHistory.session_id == row.id, EditHistory.seq > row.history_seq
        )
    )
    row.current_asset_id = current
    row.document = document
    row.revision += 1
    row.history_seq += 1
    db.add(
        EditHistory(
            session_id=row.id,
            seq=row.history_seq,
            action=action,
            current_asset_id=current,
            document=row.document,
        )
    )
    await db.execute(
        delete(EditHistory).where(
            EditHistory.session_id == row.id, EditHistory.seq <= row.history_seq - HISTORY_LIMIT
        )
    )
    await db.flush()


async def navigate(db: AsyncSession, row: EditSession, direction: int) -> None:
    target = await db.scalar(
        select(EditHistory).where(
            EditHistory.session_id == row.id, EditHistory.seq == row.history_seq + direction
        )
    )
    if target is None:
        raise HTTPException(409, "没有可撤销的记录" if direction < 0 else "没有可重做的记录")
    row.current_asset_id = target.current_asset_id
    row.document = target.document
    row.history_seq = target.seq
    # 不恢复旧 revision，避免其他标签页的过期操作重新变成有效操作。
    row.revision += 1
    await db.flush()


def summary(row: EditSession) -> dict:
    return {
        key: getattr(row, key)
        for key in (
            "id",
            "title",
            "original_asset_id",
            "current_asset_id",
            "revision",
            "history_seq",
            "created_at",
            "updated_at",
        )
    }


async def describe(db: AsyncSession, row: EditSession, store: ObjectStorage) -> dict:
    await db.refresh(row)
    wall = list(
        await db.scalars(
            select(Asset)
            .join(SessionAsset, SessionAsset.asset_id == Asset.id)
            .where(SessionAsset.session_id == row.id, Asset.user_id == row.user_id)
            .order_by(SessionAsset.position)
        )
    )
    history = list(
        await db.scalars(
            select(EditHistory).where(EditHistory.session_id == row.id).order_by(EditHistory.seq)
        )
    )
    previous = next((entry for entry in history if entry.seq == row.history_seq - 1), None)
    seqs = {entry.seq for entry in history}
    return {
        **summary(row),
        "document": row.document,
        "assets": [AssetOut.of(asset, store) for asset in wall],
        "previous_document": previous.document if previous else None,
        "can_undo": row.history_seq - 1 in seqs,
        "can_redo": row.history_seq + 1 in seqs,
        "history_limit": HISTORY_LIMIT,
        "history": [
            {
                "seq": entry.seq,
                "action": entry.action,
                "current_asset_id": entry.current_asset_id,
                "created_at": entry.created_at,
            }
            for entry in history
        ],
    }
