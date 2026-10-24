"""注册/登录请求与公开用户响应；不负责哈希、数据库或会话签发。"""

import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=6, max_length=64, repr=False)

    @field_validator("username", mode="before")
    @classmethod
    def normalize_username(cls, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("用户名必须为字符串")
        normalized = value.strip()
        if not normalized.replace("_", "").isalnum():
            raise ValueError("用户名只能包含字母、数字和下划线")
        return normalized

    @field_validator("password")
    @classmethod
    def validate_password_bytes(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 72:
            raise ValueError("密码按 UTF-8 编码后不得超过 72 字节")
        return value


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    username: str
