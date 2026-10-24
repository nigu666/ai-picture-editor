"""单底图非破坏式调色：保存绝对参数，对原始像素按固定顺序计算。"""

import io

from PIL import Image, ImageEnhance
from pydantic import BaseModel, ConfigDict, Field

from app.edits.geometry import editable
from app.edits.texture import clarity, vibrance, vignette
from app.edits.tone import sharpness, tone, white_balance
from app.services.images import MAX_FILE_BYTES, MAX_PIXELS


class ColorParams(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    brightness: float = Field(
        default=1, ge=0, le=2, strict=True, description="亮度绝对系数，0 到 2；1 为原始亮度"
    )
    contrast: float = Field(
        default=1, ge=0, le=2, strict=True, description="对比度绝对系数，0 到 2；1 为原始对比度"
    )
    saturation: float = Field(
        default=1,
        ge=0,
        le=2,
        strict=True,
        description="饱和度绝对系数，0 到 2；0 为黑白，1 为原始色彩",
    )
    sharpness: float = Field(
        default=1,
        ge=0,
        le=2,
        strict=True,
        description="锐化绝对系数，0 到 2；1 不变，0 柔和，2 加强细节；不能恢复缺失细节",
    )
    highlights: float = Field(
        default=0,
        ge=-1,
        le=1,
        strict=True,
        description="高光绝对偏移，-1 到 1；0 不变，负值压暗亮部，正值提亮亮部",
    )
    shadows: float = Field(
        default=0,
        ge=-1,
        le=1,
        strict=True,
        description="阴影绝对偏移，-1 到 1；0 不变，负值加深暗部，正值提亮暗部",
    )
    temperature: float = Field(
        default=0,
        ge=-1,
        le=1,
        strict=True,
        description="冷暖绝对偏移，-1 到 1；0 不变，负值偏冷，正值偏暖；不是 Kelvin",
    )
    tint: float = Field(
        default=0,
        ge=-1,
        le=1,
        strict=True,
        description="绿/洋红绝对偏移，-1 到 1；0 不变，负值偏绿，正值偏洋红",
    )
    vibrance: float = Field(
        default=0,
        ge=-1,
        le=1,
        strict=True,
        description="自然饱和度绝对偏移，-1 到 1；0 不变，优先增强或降低较淡颜色，保护已鲜艳颜色",
    )
    clarity: float = Field(
        default=0,
        ge=-1,
        le=1,
        strict=True,
        description="清晰度绝对偏移，-1 到 1；0 不变，正值增强中间调局部对比，负值柔化",
    )
    vignette: float = Field(
        default=0,
        ge=0,
        le=1,
        strict=True,
        description="暗角绝对强度，0 到 1；0 不变，正值从当前画布中心向边缘渐暗，1 最强",
    )


def apply_document(document: dict, params: ColorParams) -> dict:
    doc = editable(document)
    if params == ColorParams():
        doc.pop("adjustments", None)
    else:
        # 原三参数文档保持原格式；新增参数仅在非中性时保存，避免制造空编辑历史。
        values = params.model_dump()
        neutral = ColorParams().model_dump()
        doc["adjustments"] = {
            key: value
            for key, value in values.items()
            if key in {"brightness", "contrast", "saturation"} or value != neutral[key]
        }
    return doc


def adjust_pixels(
    image: Image.Image, params: ColorParams, *, document: dict | None = None
) -> Image.Image:
    alpha = image.convert("RGBA").getchannel("A")
    result = image.convert("RGB")
    for kind, factor in (
        (ImageEnhance.Brightness, params.brightness),
        (ImageEnhance.Contrast, params.contrast),
        (ImageEnhance.Color, params.saturation),
    ):
        if factor != 1:
            result = kind(result).enhance(factor)
    result = tone(result, params.highlights, params.shadows)
    result = white_balance(result, params.temperature, params.tint)
    result = vibrance(result, params.vibrance)
    result = clarity(result, alpha, params.clarity)
    result = sharpness(result, alpha, params.sharpness)
    result = vignette(result, params.vignette, document)
    result = result.convert("RGBA")
    result.putalpha(alpha)
    return result


def source_image(data: bytes, document: dict) -> Image.Image:
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("image too large")
    with Image.open(io.BytesIO(data)) as original:
        if original.width * original.height > MAX_PIXELS:
            raise ValueError("too many pixels")
        return adjust_pixels(
            original, ColorParams.model_validate(document.get("adjustments", {})), document=document
        )


def source_png(data: bytes, document: dict, *, preview=False) -> bytes:
    image = source_image(data, document)
    if preview:
        image.thumbnail((1536, 1536), Image.Resampling.LANCZOS)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()
