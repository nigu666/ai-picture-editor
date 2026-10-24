"""有序图层合成；保留旧单图精确像素分支，后层覆盖前层。"""

import math
from copy import deepcopy

from PIL import Image

from app.edits.color import source_image
from app.edits.text import raster_text
from app.layers import MAX_SOURCE_PIXELS, LayerDocument
from app.services.images import MAX_FILE_BYTES, MAX_PIXELS


def render_document(data, document: dict, *, max_side: int | None = None) -> Image.Image:
    # 只校验，不将默认值写回历史JSON；现有单图的色彩参数计算保持原样。
    if isinstance(data, bytes) and len(document.get("layers", [])) == 1:
        # 旧纯像素调用显式提供唯一字节源，不依赖素材身份；HTTP文档仍需完整校验。
        document = deepcopy(document)
        document["layers"][0].setdefault("id", "base")
        document["layers"][0].setdefault("asset_id", "00000000-0000-0000-0000-000000000000")
    document = LayerDocument.model_validate(document).model_dump(mode="json", exclude_none=True)
    layers = document["layers"]
    if isinstance(data, bytes):
        if len(layers) != 1:
            raise ValueError("multiple layers require all image sources")
        if layers[0].get("adjustments") is not None:
            document["adjustments"] = layers[0]["adjustments"]
        return _render_layer(data, document, max_side=max_side)
    if not isinstance(data, dict) or any(
        str(layer["asset_id"]) not in data for layer in layers if layer["kind"] == "image"
    ):
        raise ValueError("missing layer sources")
    if sum(len(raw) for raw in data.values()) > 64 * 1024 * 1024:
        raise ValueError("combined image sources too large")
    if sum(layer["width"] * layer["height"] for layer in layers) > MAX_SOURCE_PIXELS:
        raise ValueError("combined layer pixels too large")
    canvas = None
    for index, layer in enumerate(layers):
        if not layer["visible"] or layer["opacity"] == 0:
            continue
        frame = {"width": document["width"], "height": document["height"], "layers": [layer]}
        adjustments = layer.get("adjustments") or (
            document.get("adjustments") if index == 0 else None
        )
        if adjustments is not None:
            frame["adjustments"] = adjustments
        picture = _render_layer(
            data[str(layer["asset_id"])] if layer["kind"] == "image" else b"",
            frame,
            max_side=max_side,
        )
        if canvas is None:
            canvas = picture
        else:
            canvas.alpha_composite(picture)
    if canvas is None:
        scale = min(1, max_side / max(document["width"], document["height"])) if max_side else 1
        canvas = Image.new(
            "RGBA",
            (max(1, round(document["width"] * scale)), max(1, round(document["height"] * scale))),
            (0, 0, 0, 0),
        )
    return canvas


def _render_layer(data: bytes, document: dict, *, max_side: int | None = None) -> Image.Image:
    layers = document["layers"]
    if len(layers) != 1:
        raise ValueError("unsupported layers")
    layer = layers[0]
    width, height = document["width"], document["height"]
    if min(width, height, layer["width"], layer["height"]) <= 0:
        raise ValueError("invalid dimensions")
    if width * height > MAX_PIXELS:
        raise ValueError("canvas too large")
    scale = min(1, max_side / max(width, height)) if max_side else 1
    size = (max(1, round(width * scale)), max(1, round(height * scale)))
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("image too large")
    source = raster_text(layer) if layer["kind"] == "text" else source_image(data, document)
    canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    if not layer["visible"]:
        return canvas
    t = layer["transform"]
    angle = math.radians(t["rotation"])
    a = round(math.cos(angle), 12) * t["scale_x"] * layer["width"] / source.width
    b = round(math.sin(angle), 12) * t["scale_x"] * layer["width"] / source.width
    c = -round(math.sin(angle), 12) * t["scale_y"] * layer["height"] / source.height
    d = round(math.cos(angle), 12) * t["scale_y"] * layer["height"] / source.height
    det, x, y = a * d - b * c, t["x"], t["y"]
    if abs(det) < 1e-12:
        raise ValueError("singular transform")
    opacity = layer["opacity"]
    if not 0 <= opacity <= 1:
        raise ValueError("invalid opacity")
    # 整像素翻转/90度旋转无需插值。RGBA 插值会经过预乘透明度，半透明颜色会有舍入。
    if (
        scale == 1
        and (layer["width"], layer["height"]) == source.size
        and abs(t["scale_x"]) == abs(t["scale_y"]) == 1
        and t["rotation"] % 90 == 0
        and x == round(x)
        and y == round(y)
    ):
        picture = source
        if t["scale_x"] < 0:
            picture = picture.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        if t["scale_y"] < 0:
            picture = picture.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
        turn = {
            90: Image.Transpose.ROTATE_270,
            180: Image.Transpose.ROTATE_180,
            270: Image.Transpose.ROTATE_90,
        }.get(t["rotation"] % 360)
        if turn is not None:
            picture = picture.transpose(turn)
        left = round(
            x + min(0, a * source.width, c * source.height, a * source.width + c * source.height)
        )
        top = round(
            y + min(0, b * source.width, d * source.height, b * source.width + d * source.height)
        )
        if opacity != 1:
            picture.putalpha(picture.getchannel("A").point(lambda value: round(value * opacity)))
        canvas.paste(picture, (left, top))
        return canvas
    # 同一渲染器供视觉缩略图与完整分辨率工具使用，保留透明度。
    sx, sy = width / size[0], height / size[1]
    inverse = (
        d * sx / det,
        -c * sy / det,
        (c * y - d * x) / det,
        -b * sx / det,
        a * sy / det,
        (b * x - a * y) / det,
    )
    picture = source.transform(
        size, Image.Transform.AFFINE, inverse, resample=Image.Resampling.BICUBIC
    )
    if opacity != 1:
        picture.putalpha(picture.getchannel("A").point(lambda value: round(value * opacity)))
    canvas.alpha_composite(picture)
    return canvas
