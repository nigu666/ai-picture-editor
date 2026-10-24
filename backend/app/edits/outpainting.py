"""扩图尺寸与原区域保护；扩展区域必须来自远程模型。"""

import io
from typing import Literal

from PIL import Image
from pydantic import BaseModel, ConfigDict

from app.edits.geometry import RATIOS
from app.edits.render import render_document
from app.providers.base import ProviderError


class ExpansionParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ratio: Literal["1:1", "4:5", "3:4", "9:16", "16:9"]


def bounds(width: int, height: int, ratio: str) -> dict:
    if (
        type(width) is not int
        or type(height) is not int
        or not 512 <= min(width, height) <= max(width, height) <= 4096
    ):
        raise ProviderError("AI扩图需要画布每边为512至4096像素，不会自动放大原图")
    if ratio not in RATIOS:
        raise ProviderError("不支持的扩图比例")
    a, b = RATIOS[ratio]
    unit = max((width + a - 1) // a, (height + b - 1) // b)
    w, h = a * unit, b * unit
    if (w, h) == (width, height):
        raise ProviderError("画布已是此比例，无需扩图")
    if max(w, h) > 4096 or w > 2 * width or h > 2 * height:
        raise ProviderError("目标超出本阶段扩图尺寸限制，请选择更接近原图的比例")
    x, y = (w - width) // 2, (h - height) // 2
    return {
        "width": w,
        "height": h,
        "left_offset": x,
        "right_offset": w - width - x,
        "top_offset": y,
        "bottom_offset": h - height - y,
    }


def prepare(data: bytes, document: dict) -> bytes:
    image = render_document(data, document)
    if image.getchannel("A").getextrema() != (255, 255):
        raise ProviderError("AI扩图目前需要不透明画布，请先采用换背景候选；本次未调用模型")
    out = io.BytesIO()
    image.convert("RGB").save(out, format="PNG")
    raw = out.getvalue()
    if len(raw) > 10 * 1024 * 1024:
        raise ProviderError("送入扩图模型的画布超过10MB，本次未调用模型")
    return raw


def protect_original(source: bytes, generated: bytes, target: dict) -> bytes:
    original = Image.open(io.BytesIO(source)).convert("RGB")
    image = Image.open(io.BytesIO(generated)).convert("RGB")
    w, h = target["width"], target["height"]
    if abs((image.width / image.height) / (w / h) - 1) > 0.02:
        raise ProviderError("扩图模型返回比例不符，未保存为候选，请核对云端任务")
    # 平台可压缩输出；只对生成结果对齐尺寸，再逐像素贴回原画布区域。
    if image.size != (w, h):
        image = image.resize((w, h), Image.Resampling.LANCZOS)
    image.paste(original, (target["left_offset"], target["top_offset"]))
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()
