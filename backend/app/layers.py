"""有序图片图层文档；旧单底图JSON兼容，不回写或批量迁移历史。"""

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.edits.color import ColorParams
from app.services.images import MAX_PIXELS

MAX_LAYERS = 20
MAX_SOURCE_PIXELS = 100_000_000
MAX_RENDER_WORK = 200_000_000
MULTI_TOOLS = {
    "edit_image",
    "generate_image",
    "adopt_candidate",
    "undo_canvas",
    "redo_canvas",
    "edit_layer",
    "promote_object",
    "replace_background",
    "remove_background",
    "expand_canvas",
    "upscale_image",
    "erase_region",
    "replace_region",
}


class LayerModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Transform(LayerModel):
    x: float = Field(default=0, ge=-10_000_000, le=10_000_000)
    y: float = Field(default=0, ge=-10_000_000, le=10_000_000)
    scale_x: float = Field(default=1, ge=-100, le=100)
    scale_y: float = Field(default=1, ge=-100, le=100)
    rotation: float = Field(default=0, ge=-3600, le=3600)

    @field_validator("scale_x", "scale_y")
    @classmethod
    def nonsingular(cls, value):
        if abs(value) < 0.0001:
            raise ValueError("图层缩放不能为零或接近零")
        return value


class Layer(LayerModel):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    kind: Literal["image"] = "image"
    name: str = Field(default="图片图层", min_length=1, max_length=80)
    width: int = Field(ge=1, le=MAX_PIXELS, strict=True)
    height: int = Field(ge=1, le=MAX_PIXELS, strict=True)
    asset_id: uuid.UUID
    transform: Transform = Field(default_factory=Transform)
    opacity: float = Field(default=1, ge=0, le=1)
    visible: bool = True
    locked: bool = False
    source_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    adjustments: ColorParams | None = None


class TextLayer(LayerModel):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    kind: Literal["text"] = "text"
    name: str = Field(default="文字图层", min_length=1, max_length=80)
    asset_id: None = None
    width: int = Field(ge=1, le=4096, strict=True)
    height: int = Field(ge=1, le=4096, strict=True)
    transform: Transform = Field(default_factory=Transform)
    opacity: float = Field(default=1, ge=0, le=1)
    visible: bool = True
    locked: bool = False
    text: str = Field(min_length=1, max_length=1000)
    font_family: Literal["yahei"] = "yahei"
    font_size: int = Field(default=32, ge=6, le=512, strict=True)
    fill: str = Field(default="#172b43", pattern=r"^#[0-9a-fA-F]{6}$")
    align: Literal["left", "center", "right"] = "left"
    source_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @field_validator("text")
    @classmethod
    def printable(cls, value):
        if not value.strip() or any(ord(c) < 32 and c != "\n" for c in value):
            raise ValueError("文字不能为空或包含控制字符")
        return value


class LayerDocument(LayerModel):
    schema_version: Literal[1] = 1
    width: int = Field(ge=1, le=MAX_PIXELS, strict=True)
    height: int = Field(ge=1, le=MAX_PIXELS, strict=True)
    layers: list[Layer | TextLayer] = Field(min_length=1, max_length=MAX_LAYERS)
    adjustments: ColorParams | None = None

    @model_validator(mode="after")
    def limits(self):
        if not any(layer.kind == "image" for layer in self.layers):
            raise ValueError("画布至少保留一个图片图层")
        if sum(len(layer.text) for layer in self.layers if layer.kind == "text") > 4000:
            raise ValueError("文字总长度超过4000字")
        if any(
            layer.kind == "text" and layer.width * layer.height > 4_000_000 for layer in self.layers
        ):
            raise ValueError("单个文字框超过400万像素，请缩小文字框")
        if self.width * self.height > MAX_PIXELS:
            raise ValueError("画布像素超过限制")
        if len({layer.id for layer in self.layers}) != len(self.layers):
            raise ValueError("图层编号重复")
        if any(layer.width * layer.height > MAX_PIXELS for layer in self.layers):
            raise ValueError("图层像素超过限制")
        if sum(layer.width * layer.height for layer in self.layers) > MAX_SOURCE_PIXELS:
            raise ValueError("图层总像素超过限制")
        visible = sum(layer.visible and layer.opacity > 0 for layer in self.layers)
        if self.width * self.height * visible > MAX_RENDER_WORK:
            raise ValueError("图层合成工作量过大，请减少图层或缩小画布")
        return self


def tool_supported(document, tool):
    if tool == "promote_object" and any(layer["kind"] == "text" for layer in document["layers"]):
        return False
    return len(document["layers"]) == 1 or tool in MULTI_TOOLS
