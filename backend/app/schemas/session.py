import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SessionCreate(StrictInput):
    current_asset_id: uuid.UUID
    asset_ids: list[uuid.UUID] = Field(default_factory=list, max_length=12)
    title: str = Field(default="未命名会话", min_length=1, max_length=80)

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("会话名称不能为空")
        return value


class VersionInput(StrictInput):
    revision: int = Field(ge=1)


class AdoptInput(VersionInput):
    asset_id: uuid.UUID


class AttachInput(VersionInput):
    asset_ids: list[uuid.UUID] = Field(min_length=1, max_length=12)


class RenameInput(VersionInput):
    title: str = Field(min_length=1, max_length=80)

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        return SessionCreate.clean_title(value)
