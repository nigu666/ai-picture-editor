"""归一化笔迹转二值遮罩。蓝色覆盖只用于展示，不修改原图。"""

import base64
import io

from PIL import Image, ImageDraw


def rasterize(width: int, height: int, strokes: list[dict]) -> tuple[bytes, int]:
    image = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(image)
    for stroke in strokes:
        if "mask" in stroke:
            # SAM 结果固化为同尺寸二值快照；撤销重放时不重新运行模型。
            with Image.open(io.BytesIO(base64.b64decode(stroke["mask"]))) as saved:
                if saved.size != image.size:
                    raise ValueError("selection mask size mismatch")
                image = saved.convert("L").point(lambda value: 255 if value else 0)
                draw = ImageDraw.Draw(image)
            continue
        radius = max(0.5, stroke["radius"] * min(width, height))
        points = [(x * width, y * height) for x, y in stroke["points"]]
        color = 255 if stroke["mode"] == "add" else 0
        if len(points) > 1:
            draw.line(points, fill=color, width=max(1, round(radius * 2)), joint="curve")
        for x, y in points:
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue(), image.histogram()[255]


def overlay(raw: bytes) -> bytes:
    with Image.open(io.BytesIO(raw)) as mask:
        image = Image.new("RGBA", mask.size, (47, 112, 224, 0))
        image.putalpha(mask.convert("L").point(lambda value: 100 if value else 0))
        out = io.BytesIO()
        image.save(out, format="PNG")
        return out.getvalue()
