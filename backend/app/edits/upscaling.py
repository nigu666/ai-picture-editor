"""超分只接受准确倍率的云端结果，不用本地插值冒充AI超分。"""

import io

from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.edits.render import render_document
from app.providers.base import ProviderError


class UpscaleParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scale: int = Field(default=2, strict=True)

    @field_validator("scale")
    @classmethod
    def supported_scale(cls, value):
        if value not in {2, 4}:
            raise ValueError("超分倍率仅支持2或4")
        return value


def bounds(width: int, height: int, scale: int) -> dict:
    if type(scale) is not int or scale not in {2, 4}:
        raise ProviderError("超分倍率仅支持2或4")
    if type(width) is not int or type(height) is not int or min(width, height) < 512:
        raise ProviderError("AI超分需要画布每边至少512像素，不会先插值放大原图")
    if max(width * scale, height * scale) > 4096:
        raise ProviderError("本阶段超分输出每边最多4096像素，请降低倍率或使用较小画布")
    return {"width": width * scale, "height": height * scale, "scale": scale}


def prepare(data: bytes, document: dict) -> bytes:
    image = render_document(data, document)
    if image.getchannel("A").getextrema() != (255, 255):
        raise ProviderError("AI超分目前需要不透明画布，请先换背景；本次未调用模型")
    out = io.BytesIO()
    image.convert("RGB").save(out, format="PNG")
    raw = out.getvalue()
    if len(raw) > 10 * 1024 * 1024:
        raise ProviderError("送入超分模型的图片超过10MB，本次未调用模型")
    return raw


def validate_output(generated: bytes, target: dict) -> bytes:
    with Image.open(io.BytesIO(generated)) as image:
        if image.size != (target["width"], target["height"]):
            raise ProviderError("超分模型返回尺寸与倍率不符，未保存候选，请核对原云端任务")
    return generated
