"""绝对图层属性更新；旋转、缩放围绕原中心，保留其他层与素材。"""

import copy
import math
from typing import Literal

from fastapi import HTTPException
from pydantic import Field, ValidationError, field_validator, model_validator

from app.edits.layout import position
from app.layers import LayerDocument, LayerModel, TextLayer


class LayerEdit(LayerModel):
    layer_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    visible: bool | None = Field(default=None, strict=True)
    locked: bool | None = Field(default=None, strict=True)
    opacity: float | None = Field(default=None, ge=0, le=1, strict=True)
    center_x: float | None = Field(default=None, ge=-100000, le=100000, strict=True)
    center_y: float | None = Field(default=None, ge=-100000, le=100000, strict=True)
    scale: float | None = Field(default=None, ge=0.05, le=4, strict=True)
    rotation: float | None = Field(default=None, ge=-360, le=360, strict=True)
    position: int | None = Field(default=None, ge=0, le=19, strict=True)
    text: str | None = Field(default=None, min_length=1, max_length=1000)
    font_size: int | None = Field(default=None, ge=6, le=512, strict=True)
    fill: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    align: Literal["left", "center", "right"] | None = None
    width: int | None = Field(default=None, ge=1, le=4096, strict=True)
    height: int | None = Field(default=None, ge=1, le=4096, strict=True)

    @field_validator("text")
    @classmethod
    def valid_text(cls, value):
        return TextLayer.printable(value) if value is not None else value

    @model_validator(mode="after")
    def nonempty(self):
        changed = self.model_fields_set - {"layer_id"}
        if not changed or any(getattr(self, name) is None for name in changed):
            raise ValueError("请提供至少一项有效的图层属性，属性不能为null")
        return self


def apply_document(document, params: LayerEdit):
    doc = copy.deepcopy(document)
    layers = doc["layers"]
    target = next((layer for layer in layers if layer["id"] == params.layer_id), None)
    if target is None:
        raise HTTPException(404, "图层不存在，请重新读取当前会话")
    text_fields = {
        "text",
        "font_size",
        "fill",
        "align",
        "width",
        "height",
    } & params.model_fields_set
    if text_fields and target["kind"] != "text":
        raise HTTPException(422, "文字内容、字号与文字框属性仅适用于文字图层")
    geometric = {
        "center_x",
        "center_y",
        "scale",
        "rotation",
        "width",
        "height",
    } & params.model_fields_set
    if geometric and target.get("locked", False):
        raise HTTPException(409, "此图层已锁定，请先解锁后调整位置、缩放或旋转")
    if geometric:
        frame = {"layers": [target]}
        before = position(frame)
        t = target["transform"]
        for key in ("width", "height"):
            if key in params.model_fields_set:
                target[key] = getattr(params, key)
        if params.scale is not None:
            t["scale_x"] = math.copysign(params.scale, t["scale_x"])
            t["scale_y"] = math.copysign(params.scale, t["scale_y"])
        if params.rotation is not None:
            t["rotation"] = params.rotation
        after = position(frame)
        t["x"] = round(
            t["x"]
            + (params.center_x if params.center_x is not None else before["center_x"])
            - after["center_x"],
            8,
        )
        t["y"] = round(
            t["y"]
            + (params.center_y if params.center_y is not None else before["center_y"])
            - after["center_y"],
            8,
        )
    for key in ["visible", "locked", "opacity"]:
        if key in params.model_fields_set:
            target[key] = getattr(params, key)
    for key in ("text", "font_size", "fill", "align"):
        if key in params.model_fields_set:
            target[key] = getattr(params, key)
    if params.position is not None:
        if params.position >= len(layers):
            raise HTTPException(422, "图层层序超出当前图层数量")
        if "adjustments" in doc:
            layers[0]["adjustments"] = doc.pop("adjustments")
        layers.remove(target)
        layers.insert(params.position, target)
    try:
        LayerDocument.model_validate(doc)
    except ValidationError:
        raise HTTPException(422, "图层属性或合成预算超出限制，请减小文字框或减少文字") from None
    return doc
