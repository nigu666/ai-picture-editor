import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Unit = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]


class SelectionVersion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1, strict=True)
    version: int = Field(ge=0, strict=True)
    request_id: uuid.UUID


class StrokeIn(SelectionVersion):
    points: list[tuple[Unit, Unit]] = Field(min_length=1, max_length=1000)
    radius: float = Field(ge=0.0001, le=0.5, allow_inf_nan=False)
    mode: Literal["add", "subtract"] = "add"


class SelectionAction(SelectionVersion):
    action: Literal["undo", "redo", "clear"]


class SamPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x: Unit
    y: Unit
    label: int = Field(ge=0, le=1, strict=True)


class PointsIn(SelectionVersion):
    prompts: list[SamPoint] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def positive_required(self):
        if not any(point.label == 1 for point in self.prompts):
            raise ValueError("至少先添加一个保留点")
        return self


class PrepareIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1, strict=True)
