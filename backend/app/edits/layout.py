"""以画布坐标中的图层中心定位、按原素材比例缩放，不改变画布边界。"""

import math

from pydantic import BaseModel, ConfigDict, Field

from app.edits.geometry import editable


class LayoutParams(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    center_x: float | None = Field(
        default=None,
        ge=-100000,
        le=100000,
        strict=True,
        description="图片中心在当前画布中的 X 像素坐标，向右为正；省略则保持",
    )
    center_y: float | None = Field(
        default=None,
        ge=-100000,
        le=100000,
        strict=True,
        description="图片中心在当前画布中的 Y 像素坐标，向下为正；省略则保持",
    )
    scale: float | None = Field(
        default=None,
        ge=0.05,
        le=4,
        strict=True,
        description="相对原素材的绝对等比缩放，0.05到4，1为100%；保留翻转方向及中心，省略则保持",
    )


def position(document: dict) -> dict:
    layer = document["layers"][0]
    t = layer["transform"]
    angle = math.radians(t["rotation"])
    cos, sin = round(math.cos(angle), 12), round(math.sin(angle), 12)
    return {
        "center_x": t["x"]
        + (cos * t["scale_x"] * layer["width"] - sin * t["scale_y"] * layer["height"]) / 2,
        "center_y": t["y"]
        + (sin * t["scale_x"] * layer["width"] + cos * t["scale_y"] * layer["height"]) / 2,
        "scale": abs(t["scale_x"]),
    }


def apply_document(document: dict, params: LayoutParams) -> dict:
    doc = editable(document)
    before = position(doc)
    values = {key: before[key] if val is None else val for key, val in params.model_dump().items()}
    if all(math.isclose(values[key], before[key], abs_tol=1e-8, rel_tol=0) for key in before):
        return doc
    layer = doc["layers"][0]
    t = layer["transform"]
    t["scale_x"] = math.copysign(values["scale"], t["scale_x"])
    t["scale_y"] = math.copysign(values["scale"], t["scale_y"])
    # 先围绕原中心缩放，再移动到指定中心；翻转和旋转都参与原点坐标计算。
    offset = position(doc)
    t["x"] = round(t["x"] + values["center_x"] - offset["center_x"], 8)
    t["y"] = round(t["y"] + values["center_y"] - offset["center_y"], 8)
    return doc
