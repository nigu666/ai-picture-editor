"""密码哈希、验证与固定算法的 JWT 签发及读取。"""

import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

MAX_PASSWORD_BYTES = 72
SESSION_COOKIE = "session"
ALGORITHM = "HS256"


def _password_bytes(plain: str) -> bytes:
    encoded = plain.encode("utf-8")
    if len(encoded) > MAX_PASSWORD_BYTES:
        raise ValueError("密码按 UTF-8 编码后不得超过 72 字节")
    return encoded


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(_password_bytes(plain), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(_password_bytes(plain), hashed.encode("utf-8"))


def issue_token(user_id: uuid.UUID, secret: str, *, ttl_hours: int) -> str:
    payload = {
        "sub": str(user_id),
        "exp": datetime.now(UTC) + timedelta(hours=ttl_hours),
    }
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


def read_token(token: str, secret: str) -> uuid.UUID | None:
    try:
        payload = jwt.decode(
            token, secret, algorithms=[ALGORITHM], options={"require": ["sub", "exp"]}
        )
        return uuid.UUID(payload["sub"])
    except (jwt.InvalidTokenError, KeyError, ValueError, TypeError):
        return None
