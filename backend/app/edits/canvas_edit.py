"""整图编辑采用已保存的画布合成图；输出尺寸显式按16像素对齐。"""

import io

from pydantic import BaseModel, ConfigDict, Field

from app.edits.render import render_document
from app.providers.base import ProviderError
from app.providers.reference_generation import MAX_REFERENCE_BYTES

NAME = "dashscope-canvas-edit"


class CanvasEditParams(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    prompt: str = Field(
        min_length=1, max_length=800, description="对当前已保存画布的修改要求，不包含素材编号或路径"
    )


def bounds(document: dict) -> dict:
    width, height = document["width"], document["height"]
    if any(type(side) is not int or not 512 <= side <= 2048 for side in (width, height)):
        raise ProviderError("本阶段AI整图编辑需要画布宽和高均在512至2048像素之间")
    return {"width": (width + 8) // 16 * 16, "height": (height + 8) // 16 * 16}


def prepare(data, document: dict) -> bytes:
    bounds(document)
    image = render_document(data, document)
    if image.getchannel("A").getextrema() != (255, 255):
        raise ProviderError("AI整图编辑目前需要不透明画布，请先添加背景；本次未调用模型")
    output = io.BytesIO()
    image.convert("RGB").save(output, "PNG")
    raw = output.getvalue()
    if len(raw) > MAX_REFERENCE_BYTES:
        raise ProviderError("合成后的画布超过10MB，本次未调用模型")
    return raw
