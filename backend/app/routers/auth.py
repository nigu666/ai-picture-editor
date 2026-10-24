"""认证 HTTP 接口：编排输入、业务结果、Cookie 与公开输出。"""

from fastapi import APIRouter, HTTPException, Response, status

from app.config import Settings
from app.deps import CurrentUser, SessionDep, SettingsDep
from app.models import User
from app.schemas.auth import Credentials, UserOut
from app.security import SESSION_COOKIE, issue_token
from app.services import auth as auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


def _start_session(response: Response, user: User, settings: Settings) -> UserOut:
    response.set_cookie(
        SESSION_COOKIE,
        issue_token(user.id, settings.jwt_secret, ttl_hours=settings.jwt_ttl_hours),
        max_age=settings.jwt_ttl_hours * 3600,
        httponly=True,
        samesite="lax",
        secure=settings.is_production,
        path="/",
    )
    return UserOut.model_validate(user)


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    credentials: Credentials, response: Response, session: SessionDep, settings: SettingsDep
) -> UserOut:
    try:
        user = await auth_service.register(session, credentials)
    except auth_service.UsernameTaken:
        raise HTTPException(status.HTTP_409_CONFLICT, "该用户名已被占用") from None
    return _start_session(response, user, settings)


@router.post("/login")
async def login(
    credentials: Credentials, response: Response, session: SessionDep, settings: SettingsDep
) -> UserOut:
    try:
        user = await auth_service.authenticate(session, credentials)
    except auth_service.InvalidCredentials:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户名或密码错误") from None
    return _start_session(response, user, settings)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(settings: SettingsDep) -> Response:
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(
        SESSION_COOKIE, path="/", httponly=True, secure=settings.is_production, samesite="lax"
    )
    return response


@router.get("/me")
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)
