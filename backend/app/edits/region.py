"""局部编辑输入校验及选区内柔化合成；黑色区域逐像素保留。"""

import io
import uuid

from PIL import Image, ImageChops, ImageFilter
from pydantic import BaseModel, ConfigDict, Field

from app.edits.render import render_document
from app.providers.base import ProviderError


class EraseParams(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    selection_version: int = Field(ge=1, strict=True)
    request_id: uuid.UUID
    prompt: str = Field(default="", max_length=800)


class ReplaceParams(EraseParams):
    prompt: str = Field(min_length=1, max_length=800)


def bounds(width, height):
    if min(width, height) < 512 or max(width, height) > 4096:
        raise ProviderError("局部编辑要求画布每边在512～4096 px之间")


def png(image):
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def prepare(data, document, mask):
    bounds(document["width"], document["height"])
    source = render_document(data, document)
    if source.getchannel("A").getextrema()[0] != 255:
        raise ProviderError("当前局部编辑支持不透明画布，请先采用不透明背景图片")
    with Image.open(io.BytesIO(mask)) as selection:
        if selection.size != source.size or selection.mode != "L":
            raise ProviderError("局部编辑遮罩与提交画布不匹配")
        if not set(selection.get_flattened_data()) <= {0, 255} or not selection.getbbox():
            raise ProviderError("局部编辑需要非空黑白选区")
        cloud_mask = png(selection.convert("RGB"))
    image = png(source.convert("RGB"))
    if max(len(image), len(cloud_mask)) > 10 * 1024 * 1024:
        raise ProviderError("提交百炼的图片或遮罩超过10MB，请缩小图片后再试")
    return image, cloud_mask


def composite(source_png, generated, mask):
    from app.services.images import ImageRejected, probe

    try:
        probe(generated)
    except ImageRejected:
        raise ProviderError("局部编辑结果不是有效图片") from None
    with Image.open(io.BytesIO(source_png)) as source, Image.open(io.BytesIO(generated)) as edited:
        original = source.convert("RGBA")
        result = edited.convert("RGBA")
        if result.size != original.size:
            raise ProviderError("局部编辑结果尺寸与原图不符，未保存错位候选")
        with Image.open(io.BytesIO(mask)) as selection:
            binary = selection.convert("L")
            if binary.size != original.size:
                raise ProviderError("局部编辑遮罩尺寸不符")
            # 高斯模糊只向选区内部柔化，不允许灰度扩散到原来的黑色区域。
            softened = ImageChops.darker(binary, binary.filter(ImageFilter.GaussianBlur(1.2)))
            return png(Image.composite(result, original, softened))
