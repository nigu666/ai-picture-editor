"""选区裁物、原图层打孔与新图层文档；不改存储中的原文件。"""

import copy
import hashlib
import io
import math
import uuid

import cv2
import numpy as np
from PIL import Image, ImageChops
from pydantic import BaseModel, ConfigDict, Field

from app.edits.region import bounds, png
from app.edits.render import render_document
from app.layers import LayerDocument
from app.providers.base import ProviderError
from app.services.images import ImageRejected, probe


class PromoteParams(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    prompt: str = Field(min_length=2, max_length=600)
    selection_version: int = Field(ge=1, strict=True)
    request_id: uuid.UUID


def selection_mask(raw, size):
    with Image.open(io.BytesIO(raw)) as image:
        if image.mode != "L" or image.size != size or not image.getbbox():
            raise ProviderError("选区与画布不匹配或为空，请重新选择")
        mask = image.copy()
    if not set(mask.get_flattened_data()) <= {0, 255}:
        raise ProviderError("成层选区必须是黑白二值图")
    coverage = np.count_nonzero(np.asarray(mask)) / (size[0] * size[1])
    if not 0.00001 <= coverage <= 0.95:
        raise ProviderError("选区过小或几乎覆盖整图，请缩小选区或换一张图片")
    return mask


def signature(mask):
    return hashlib.sha256(
        b"promote-mask-v1:" + str(mask.size).encode() + mask.tobytes()
    ).hexdigest()


def flatten(data, document):
    bounds(document["width"], document["height"])
    image = render_document(data, document)
    if image.getchannel("A").getextrema()[0] != 255:
        raise ProviderError("选区成层目前需要完整的不透明画布，请先显示完整背景")
    return png(image)


def cut_object(source, mask):
    image = Image.open(io.BytesIO(source)).convert("RGBA")
    image.putalpha(ImageChops.multiply(image.getchannel("A"), mask))
    left, top, right, bottom = mask.getbbox()
    # 素材统一最短边32px；小物体补透明边，不放大像素。
    width, height = max(32, right - left), max(32, bottom - top)
    left = max(0, min(left, image.width - width))
    top = max(0, min(top, image.height - height))
    raw = png(image.crop((left, top, left + width, top + height)))
    checked_image(raw)
    return raw, (left, top, width, height)


def expanded(mask):
    grow = max(2, min(mask.size) // 64)
    values = cv2.dilate(np.asarray(mask), np.ones((2 * grow + 1, 2 * grow + 1), np.uint8))
    return png(Image.fromarray(values))


def punch(raw, layer, mask):
    image = Image.open(io.BytesIO(raw)).convert("RGBA")
    t = layer["transform"]
    angle = math.radians(t["rotation"])
    cos, sin = round(math.cos(angle), 12), round(math.sin(angle), 12)
    a, b = (
        cos * t["scale_x"] * layer["width"] / image.width,
        sin * t["scale_x"] * layer["width"] / image.width,
    )
    c, d = (
        -sin * t["scale_y"] * layer["height"] / image.height,
        cos * t["scale_y"] * layer["height"] / image.height,
    )
    # 输出为素材局部坐标，输入为画布遮罩；前向几何矩阵正好用于反向采样。
    local = mask.transform(
        image.size,
        Image.Transform.AFFINE,
        (a, c, t["x"], b, d, t["y"]),
        resample=Image.Resampling.BILINEAR,
        fillcolor=0,
    )
    image.putalpha(ImageChops.multiply(image.getchannel("A"), ImageChops.invert(local)))
    result = png(image)
    checked_image(result)
    return result


def checked_image(raw):
    try:
        return probe(raw)
    except ImageRejected as exc:
        raise ProviderError(str(exc)) from None


def repaired_layer(generated, size, mask, original=None):
    checked_image(generated)
    image = Image.open(io.BytesIO(generated)).convert("RGBA")
    if image.size != size:
        raise ProviderError("成层背景结果尺寸不符，未应用错位内容")
    if original is None:
        image.putalpha(mask)
    else:
        # 精确替换选区内的背景，物体移走后不留下原主体的柔化残影。
        image = Image.composite(image, Image.open(io.BytesIO(original)).convert("RGBA"), mask)
    result = png(image)
    checked_image(result)
    return result


def layer(name, prefix, asset_id, width, height, run_id, x=0, y=0, locked=False):
    return dict(
        id=f"{prefix}-{run_id}",
        kind="image",
        name=name,
        asset_id=str(asset_id),
        width=width,
        height=height,
        visible=True,
        locked=locked,
        opacity=1,
        transform=dict(x=x, y=y, scale_x=1, scale_y=1, rotation=0),
    )


def document_for(original, run_id, parts, box, mask_hash):
    left, top, width, height = box
    doc = copy.deepcopy(original)
    doc["schema_version"] = 1
    if len(doc["layers"]) == 1:
        doc.pop("adjustments", None)
        doc["layers"] = [
            layer(
                "背景",
                "background",
                parts["background"],
                doc["width"],
                doc["height"],
                run_id,
                locked=True,
            )
        ]
    else:
        for item in doc["layers"]:
            item["asset_id"] = str(parts["rest-" + item["id"]])
        # 全局旧调色继续属于旧底层，不作用到新修复底片或新物体。
        if "adjustments" in doc:
            doc["layers"][0]["adjustments"] = doc.pop("adjustments")
        doc["layers"].insert(
            0,
            layer(
                "背景修复",
                "repair",
                parts["background"],
                doc["width"],
                doc["height"],
                run_id,
                locked=True,
            ),
        )
    obj = layer(
        "独立物体 " + str(1 + sum(item["id"].startswith("object-") for item in original["layers"])),
        "object",
        parts["object"],
        width,
        height,
        run_id,
        left,
        top,
    )
    obj["source_hash"] = mask_hash
    doc["layers"].append(obj)
    try:
        LayerDocument.model_validate(doc)
    except ValueError:
        raise ProviderError(
            "成层后图层数量、总像素或合成工作量超出限制，请减少图层或缩小画布"
        ) from None
    return doc
