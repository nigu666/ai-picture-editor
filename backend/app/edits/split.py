"""基础拆层：固定已保存画布、主体Alpha、外扩遮罩和局部背景预填。"""

import hashlib
import io
import uuid

import cv2
import numpy as np
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field

from app.edits.region import bounds, png
from app.edits.render import render_document
from app.layers import LayerDocument
from app.providers.base import ProviderError


class SplitParams(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    prompt: str = Field(min_length=2, max_length=600)
    request_id: uuid.UUID


def source_image(data, document):
    bounds(document["width"], document["height"])
    if len(document["layers"]) != 1:
        raise ProviderError("基础拆层只处理单图画布；已拆层时请勿重复提交")
    image = render_document(data, document)
    if image.getchannel("A").getextrema()[0] != 255:
        raise ProviderError("基础拆层需要不透明画布，请先选择带完整背景的图片")
    return image


def prepare_subject(source, cutout):
    original = (
        source
        if isinstance(source, Image.Image)
        else Image.open(io.BytesIO(source)).convert("RGBA")
    )
    with Image.open(io.BytesIO(cutout)) as cut:
        if cut.size != original.size:
            raise ProviderError("抠图尺寸与画布不符，未提交背景补全")
        alpha = np.array(cut.convert("RGBA").getchannel("A"))
    alpha[alpha <= 16] = 0
    selected = np.uint8(alpha > 0) * 255
    grow = max(2, min(original.size) // 64)
    mask = cv2.dilate(selected, np.ones((grow * 2 + 1, grow * 2 + 1), dtype=np.uint8))
    coverage = float(np.count_nonzero(mask)) / mask.size
    if not 0.005 <= coverage <= 0.95:
        raise ProviderError("主体范围为空、过小或覆盖几乎整图，请换一张主体边界清晰的图片")
    subject = original.copy()
    subject.putalpha(Image.fromarray(alpha))
    return png(subject), png(Image.fromarray(mask)), coverage


def prefill(source, mask_png):
    original = Image.open(io.BytesIO(source)).convert("RGB")
    with Image.open(io.BytesIO(mask_png)) as mask:
        if mask.mode != "L" or mask.size != original.size:
            raise ProviderError("拆层遮罩与画布不匹配")
        binary = np.array(mask)
    if not set(np.unique(binary)) <= {0, 255}:
        raise ProviderError("拆层遮罩必须为黑白二值图")
    pixels = np.array(original)
    filled = cv2.inpaint(pixels, binary, max(3, min(original.size) // 80), cv2.INPAINT_TELEA)
    # 本地预填也强制保护遮罩外，避免实现细节或后续库变化误改原背景。
    filled[binary == 0] = pixels[binary == 0]
    cloud = png(Image.fromarray(filled))
    cloud_mask = png(Image.fromarray(binary).convert("RGB"))
    if max(len(cloud), len(cloud_mask)) > 10 * 1024 * 1024:
        raise ProviderError("拆层提交图片或遮罩超过10MB，请缩小画布")
    return cloud, cloud_mask


def prompt(description):
    return (
        "只把已预填且被白色遮罩覆盖的区域修复为自然背景，保持周围光线、透视和构图。"
        "不要新增人物、动物、文字或前景物体。期望背景：" + description
    )


def split_document(width, height, background_id, subject_id, run_id, mask_sha):
    def layer(name, kind, asset_id, locked):
        return {
            "id": f"{kind}-{run_id}",
            "kind": "image",
            "name": name,
            "asset_id": str(asset_id),
            "width": width,
            "height": height,
            "locked": locked,
            "visible": True,
            "opacity": 1,
            "transform": {"x": 0, "y": 0, "scale_x": 1, "scale_y": 1, "rotation": 0},
            **({"source_hash": mask_sha} if kind == "subject" else {}),
        }

    document = {
        "schema_version": 1,
        "width": width,
        "height": height,
        "layers": [
            layer("背景", "background", background_id, True),
            layer("主体", "subject", subject_id, False),
        ],
    }
    LayerDocument.model_validate(document)
    return document


def digest(data):
    return hashlib.sha256(data).hexdigest()
