"""第六章第一部分：同步、无外部模型的单底图画布工具。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.edits import geometry
from app.edits.layout import LayoutParams, apply_document
from app.services import sessions
from app.tools.base import ToolContext, ToolSpec
from app.tools.builtin import _canvas_result


class TransformIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["flip_horizontal", "flip_vertical", "rotate_left", "rotate_right"]


class CropIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ratio: Literal["1:1", "4:5", "3:4", "9:16", "16:9"]


async def transform(context: ToolContext, params: BaseModel) -> dict:
    assert isinstance(params, TransformIn)
    document = geometry.transform(context.record.document, params.operation)
    await sessions.apply_edit(context.db, context.record, document, params.operation)
    return await _canvas_result(context)


async def crop(context: ToolContext, params: BaseModel) -> dict:
    assert isinstance(params, CropIn)
    document = geometry.crop(context.record.document, params.ratio)
    await sessions.apply_edit(context.db, context.record, document, "crop_canvas")
    return await _canvas_result(context)


async def layout(context: ToolContext, params: BaseModel) -> dict:
    assert isinstance(params, LayoutParams)
    document = apply_document(context.record.document, params)
    await sessions.apply_edit(context.db, context.record, document, "layout_canvas")
    return await _canvas_result(context)


SPECS = (
    ToolSpec(
        "layout_canvas",
        "设置位置与大小",
        "精确移动/等比缩放当前单底图。center_x/center_y是图片中心在当前画布中的像素坐标，"
        "scale是相对原图绝对倍率，非累乘。省略的字段保留，保留旋转、翻转与调色。"
        "仅修改文档，画布尺寸不变，超出画布的部分隐藏，可撤销；不会提高分辨率。",
        LayoutParams,
        layout,
        changes_canvas=True,
    ),
    ToolSpec(
        "transform_canvas",
        "翻转或旋转画布",
        "对当前单底图画布进行水平/垂直翻转，或向左/向右旋转 90 度。旋转同时交换画布宽高。"
        "仅改变编辑参数，保留原图像素，可撤销。",
        TransformIn,
        transform,
        changes_canvas=True,
    ),
    ToolSpec(
        "crop_canvas",
        "按比例居中裁剪",
        "按指定比例居中裁剪当前单底图画布，最短边不少于 32 像素；"
        "仅改文档边界，不删除原图像素，可撤销。",
        CropIn,
        crop,
        changes_canvas=True,
    ),
)
