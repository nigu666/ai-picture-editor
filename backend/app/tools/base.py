"""工具能力与参数定义；工具参数中不携带用户身份、会话或修订号。"""

import re
import uuid
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from types import MappingProxyType

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.edit_session import EditSession
from app.storage import ObjectStorage


class UnknownTool(Exception):
    pass


@dataclass(frozen=True)
class ToolContext:
    """仅由鉴权及会话版本检查后的服务端执行入口创建。"""

    db: AsyncSession
    user_id: uuid.UUID
    record: EditSession
    settings: Settings
    store: ObjectStorage
    commit: bool = True
    region_binding: dict | None = None


ToolHandler = Callable[[ToolContext, BaseModel], Awaitable[dict]]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    label: str
    description: str
    params: type[BaseModel]
    handler: ToolHandler
    queued: bool = False
    changes_canvas: bool = False
    agent_visible: bool = True
    agent_params: type[BaseModel] | None = None

    def validate(self, raw: dict) -> BaseModel:
        return self.params.model_validate(raw)

    def function_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": (self.agent_params or self.params).model_json_schema(),
            },
        }

    def public(self) -> dict:
        return {
            "name": self.name,
            "label": self.label,
            "description": self.description,
            "queued": self.queued,
            "changes_canvas": self.changes_canvas,
            "session_required": True,
            "parameters": self.params.model_json_schema(),
        }


class ToolRegistry:
    def __init__(self, specs: Iterable[ToolSpec]):
        entries = {}
        for spec in specs:
            if not re.fullmatch(r"[a-z][a-z0-9_]{0,47}", spec.name):
                raise ValueError("工具名称必须是明确的函数标识")
            if spec.name in entries:
                raise ValueError("工具名称重复")
            if (
                not callable(spec.handler)
                or not isinstance(spec.params, type)
                or not issubclass(spec.params, BaseModel)
            ):
                raise ValueError("工具必须提供参数模型和实际处理函数")
            if spec.params.model_config.get("extra") != "forbid":
                raise ValueError("工具参数必须拒绝额外字段")
            reserved = {"user_id", "session_id", "revision", "storage_key", "provider"}
            if reserved.intersection(spec.params.model_fields):
                raise ValueError("工具参数不可包含服务端上下文字段")
            entries[spec.name] = spec
        self._entries = MappingProxyType(entries)

    @property
    def specs(self) -> tuple[ToolSpec, ...]:
        return tuple(self._entries.values())

    def get(self, name: str) -> ToolSpec:
        try:
            return self._entries[name]
        except KeyError:
            raise UnknownTool("未注册或尚未实现的工具") from None

    def catalog(self) -> list[dict]:
        return [spec.public() for spec in self.specs]

    def function_schemas(self) -> list[dict]:
        return [spec.function_schema() for spec in self.specs if spec.agent_visible]
