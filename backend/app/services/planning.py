"""规划前后检查会话修订；等待模型期间释放数据库事务与行锁。"""

import asyncio
import copy
import uuid
from collections.abc import Callable
from dataclasses import replace

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import graph
from app.agent.llm import Planner, PlannerUnavailable
from app.agent.plan import PlanningContext, PlanResult
from app.agent.vision import preview_data_url
from app.config import Settings
from app.models import Asset
from app.models.edit_session import EditHistory, SessionAsset
from app.services import sessions
from app.services.layer_documents import keys_for_document, read_sources
from app.services.region_binding import TOOLS, capture


async def prepare(
    db: AsyncSession, user_id: uuid.UUID, session_id: uuid.UUID, revision: int, settings=None
) -> PlanningContext:
    row = await sessions.load(db, user_id, session_id)
    sessions.check_version(row, revision)
    ids = tuple(
        str(item)
        for item in await db.scalars(
            select(Asset.id)
            .join(SessionAsset, SessionAsset.asset_id == Asset.id)
            .where(SessionAsset.session_id == session_id, Asset.user_id == user_id)
            .order_by(SessionAsset.position)
        )
    )
    seqs = set(
        await db.scalars(select(EditHistory.seq).where(EditHistory.session_id == session_id))
    )
    asset = (await sessions.owned_assets(db, user_id, [row.current_asset_id]))[0]
    context = PlanningContext(
        row.revision,
        row.document["width"],
        row.document["height"],
        str(row.current_asset_id),
        ids,
        row.history_seq - 1 in seqs,
        row.history_seq + 1 in seqs,
        document=copy.deepcopy(row.document),
        storage_key=asset.storage_key,
        selection=await capture(row, settings) if settings is not None else None,
        storage_keys=await keys_for_document(db, user_id, row.document)
        if len(row.document["layers"]) > 1
        else {},
    )
    await db.rollback()
    return context


async def plan(
    db: AsyncSession,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    revision: int,
    goal: str,
    settings: Settings,
    factory: Callable[[Settings], Planner],
    store=None,
) -> PlanResult:
    context = await prepare(db, user_id, session_id, revision, settings)
    planner = factory(settings)
    if getattr(planner, "vision_enabled", False):
        if store is None or context.document is None:
            raise PlannerUnavailable("当前画布预览不可用，本轮未发送给模型")
        try:
            async with asyncio.timeout(20):
                data = (
                    await read_sources(store, context.storage_keys)
                    if context.storage_keys
                    else await store.get(context.storage_key)
                )
                image = await asyncio.to_thread(preview_data_url, data, context.document)
        except Exception as exc:
            raise PlannerUnavailable("当前画布预览读取失败，请检查图片存储后重试") from exc
        context = replace(context, image_data_url=image)
    result = await graph.run(goal, context, planner)
    row = await sessions.load(db, user_id, session_id)
    sessions.check_version(row, context.revision)
    await db.rollback()
    if result.status == "unavailable":
        raise PlannerUnavailable(result.message)
    return result.model_copy(
        update={
            "session_id": str(session_id),
            "context_revision": revision,
            "selection_binding": context.selection
            if any(s.tool in TOOLS for s in result.steps)
            else None,
        }
    )
