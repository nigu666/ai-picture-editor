import uuid
from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from app.agent.llm import Planner
from app.config import Settings
from app.deps import CurrentUser, SessionDep, SettingsDep, StorageDep
from app.routers.planning import PlanningInput, planner_factory
from app.services import agent, agent_recovery

router = APIRouter(prefix="/sessions/{session_id}/agent", tags=["agent"])


class MessageInput(PlanningInput):
    request_id: uuid.UUID


class AdvanceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: bool = Field(default=False, strict=True)


class RetryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1, strict=True)
    request_id: uuid.UUID


@router.get("/messages")
async def messages(session_id: uuid.UUID, user: CurrentUser, db: SessionDep):
    return await agent.listing(db, user.id, session_id)


@router.post("/messages", status_code=201)
async def message(
    session_id: uuid.UUID,
    body: MessageInput,
    user: CurrentUser,
    db: SessionDep,
    settings: SettingsDep,
    store: StorageDep,
    factory: Annotated[Callable[[Settings], Planner], Depends(planner_factory)],
):
    return await agent.create(db, user.id, session_id, body, settings, factory, store)


@router.post("/plans/{turn_id}/advance")
async def advance(
    session_id: uuid.UUID,
    turn_id: uuid.UUID,
    body: AdvanceInput,
    user: CurrentUser,
    db: SessionDep,
    settings: SettingsDep,
    store: StorageDep,
):
    return await agent.advance(
        db, user.id, session_id, turn_id, settings, store, confirm=body.confirm
    )


@router.post("/plans/{turn_id}/cancel")
async def cancel(session_id: uuid.UUID, turn_id: uuid.UUID, user: CurrentUser, db: SessionDep):
    return await agent.cancel(db, user.id, session_id, turn_id)


@router.post("/plans/{turn_id}/retry")
async def retry(
    session_id: uuid.UUID,
    turn_id: uuid.UUID,
    body: RetryInput,
    user: CurrentUser,
    db: SessionDep,
    settings: SettingsDep,
):
    record, turn = await agent.load(db, user.id, session_id, turn_id)
    turn = await agent_recovery.retry(
        db, record, turn, settings, revision=body.revision, request_id=body.request_id
    )
    return agent.public(turn)
