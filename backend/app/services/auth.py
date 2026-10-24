"""认证业务：注册保存用户；登录查询用户并验证密码。"""

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.schemas.auth import Credentials
from app.security import hash_password, verify_password


class UsernameTaken(Exception):
    """用户名唯一索引拒绝了本次注册。"""


class InvalidCredentials(Exception):
    """用户名不存在或密码不匹配，统一拒绝登录。"""


async def register(session: AsyncSession, credentials: Credentials) -> User:
    user = User(
        username=credentials.username,
        password_hash=hash_password(credentials.password),
    )
    session.add(user)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        # SQLAlchemy 的 asyncpg 适配异常通过 __cause__ 保留原数据库异常。
        database_error = exc.orig.__cause__ or exc.orig
        if (
            getattr(database_error, "sqlstate", None) == "23505"
            and getattr(database_error, "constraint_name", None) == "ix_users_username"
        ):
            raise UsernameTaken("该用户名已被占用") from exc
        raise
    return user


async def authenticate(session: AsyncSession, credentials: Credentials) -> User:
    user = await session.scalar(select(User).where(User.username == credentials.username))
    if user is None or not verify_password(credentials.password, user.password_hash):
        raise InvalidCredentials("用户名或密码错误")
    return user


async def get_by_id(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await session.get(User, user_id)
