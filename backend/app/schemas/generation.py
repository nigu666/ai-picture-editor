import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import RunStatus, ToolRun
from app.schemas.asset import AssetOut

# 当前教材交付比例；小尺寸单元测试继续使用 Provider 的 width/height 契约。
SIZES = {
    "1:1": (1080, 1080),
    "4:5": (1080, 1350),
    "3:4": (1080, 1440),
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
}


class GenerateTextIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    prompt: str = Field(min_length=1, max_length=1500)
    ratio: Literal["1:1", "4:5", "3:4", "9:16", "16:9"] = "1:1"
    count: int = Field(default=1, ge=1, le=6, strict=True)
    seed: int | None = Field(default=None, ge=0, le=2**31 - 1, strict=True)
    negative_prompt: str | None = Field(default=None, max_length=1500)


class GenerateIn(GenerateTextIn):
    reference_asset_ids: list[uuid.UUID] = Field(default_factory=list, max_length=3)

    @field_validator("reference_asset_ids")
    @classmethod
    def unique_references(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("同一参考图不能重复选择")
        return value


class RunOut(BaseModel):
    id: uuid.UUID
    tool: str
    status: RunStatus
    progress: int
    stage: str
    provider: str
    result: dict
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    candidates: list[AssetOut] = Field(default_factory=list)

    @classmethod
    def of(cls, run: ToolRun, candidates: list[AssetOut] | None = None):
        return cls(
            id=run.id,
            tool=run.tool,
            status=run.status,
            progress=run.progress,
            stage=run.stage,
            provider=run.params["provider"],
            result=run.result,
            error=run.error,
            created_at=run.created_at,
            started_at=run.started_at,
            finished_at=run.finished_at,
            candidates=candidates or [],
        )


class GenerationRecord(BaseModel):
    """历史只输出可复用的公开参数，不直接返回整份任务params或素材地址。"""

    id: uuid.UUID
    created_at: datetime
    status: RunStatus
    stage: str
    progress: int
    provider: str
    model: str | None
    prompt: str
    ratio: Literal["1:1", "4:5", "3:4", "9:16", "16:9"] | None
    width: int
    height: int
    count: int
    seed: int | None
    negative_prompt: str | None
    reference_asset_ids: list[uuid.UUID] = Field(default_factory=list)

    @classmethod
    def of(cls, run: ToolRun):
        request = run.params["request"]
        width, height = request["width"], request["height"]
        ratio = next(
            (
                ratio
                for ratio in SIZES
                if width * int(ratio.split(":")[1]) == height * int(ratio.split(":")[0])
            ),
            None,
        )
        provider = run.params["provider"]
        return cls(
            id=run.id,
            created_at=run.created_at,
            status=run.status,
            stage=run.stage,
            progress=run.progress,
            provider=provider,
            model="mock"
            if provider == "mock"
            else run.params.get("model") or run.result.get("model"),
            prompt=request["prompt"],
            ratio=ratio,
            width=width,
            height=height,
            count=request.get("count", 1),
            seed=request.get("seed"),
            negative_prompt=request.get("negative_prompt"),
            reference_asset_ids=run.params.get("reference_asset_ids", []),
        )


class GenerationPage(BaseModel):
    items: list[GenerationRecord]
    next_cursor: uuid.UUID | None
