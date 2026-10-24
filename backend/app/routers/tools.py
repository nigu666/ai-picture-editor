import uuid
from typing import Annotated

from fastapi import APIRouter, Path, Response
from pydantic import BaseModel, ConfigDict, Field

from app.deps import CurrentUser, SessionDep, SettingsDep, StorageDep
from app.services import tools as service
from app.tools import REGISTRY

router = APIRouter(tags=["tools"])


class ToolInvokeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1, strict=True)
    params: dict = Field(default_factory=dict, max_length=16)


@router.get("/tools")
async def catalog(_: CurrentUser) -> list[dict]:
    return REGISTRY.catalog()


@router.post("/sessions/{session_id}/tools/{tool_name}")
async def invoke(
    session_id: uuid.UUID,
    tool_name: Annotated[str, Path(pattern=r"^[a-z][a-z0-9_]{0,47}$")],
    body: ToolInvokeIn,
    user: CurrentUser,
    db: SessionDep,
    settings: SettingsDep,
    store: StorageDep,
    response: Response,
) -> dict:
    result = await service.invoke(
        db, user.id, session_id, body.revision, tool_name, body.params, settings, store
    )
    if result["run"] is not None:
        response.status_code = 202
    return result
