"""从当前应用取得配置和会话；查验 Cookie、JWT 与用户存在性。"""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db import session_scope
from app.models import User
from app.security import SESSION_COOKIE, read_token
from app.services.auth import get_by_id
from app.storage import ObjectStorage


def request_settings(request: Request) -> Settings:
    return request.app.state.settings


SettingsDep = Annotated[Settings, Depends(request_settings)]


def object_storage(request: Request) -> ObjectStorage:
    store = request.app.state.object_storage
    if store is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "图片存储尚未配置")
    return store


StorageDep = Annotated[ObjectStorage, Depends(object_storage)]


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with session_scope(request.app.state.session_factory) as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def current_user(
    session: SessionDep,
    settings: SettingsDep,
    token: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> User:
    user_id = None if token is None else read_token(token, settings.jwt_secret)
    if user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "未登录或会话已过期")
    user = await get_by_id(session, user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "未登录或会话已过期")
    return user


CurrentUser = Annotated[User, Depends(current_user)]
