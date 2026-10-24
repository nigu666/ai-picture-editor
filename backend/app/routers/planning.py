import uuid
from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.agent.llm import Planner, PlannerUnavailable, make_planner
from app.agent.plan import PlanResult
from app.config import Settings
from app.deps import CurrentUser, SessionDep, SettingsDep, StorageDep
from app.services import planning as service

router = APIRouter(tags=["planning"])


class PlanningInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    goal: str = Field(min_length=1, max_length=1500)
    revision: int = Field(ge=1, strict=True)


def planner_factory() -> Callable[[Settings], Planner]:
    # 只提供工厂；实例化及模型调用发生在归属检查之后。
    return make_planner


@router.post("/sessions/{session_id}/agent/plan", response_model=PlanResult)
async def plan(
    session_id: uuid.UUID,
    body: PlanningInput,
    user: CurrentUser,
    db: SessionDep,
    settings: SettingsDep,
    store: StorageDep,
    factory: Annotated[Callable[[Settings], Planner], Depends(planner_factory)],
) -> PlanResult:
    try:
        return await service.plan(
            db, user.id, session_id, body.revision, body.goal, settings, factory, store
        )
    except PlannerUnavailable as exc:
        raise HTTPException(
            503, {"message": str(exc), "code": "planner_unavailable", "executed": False}
        ) from None
