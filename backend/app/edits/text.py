"""固定本地字体绘制文字；文本保存在文档中，预览共用同一渲染器。"""

import os
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def font_path():
    override = os.environ.get("TEXT_FONT_PATH")
    path = (
        Path(override)
        if override
        else Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/msyh.ttc"
    )
    if not path.is_file():
        raise ValueError("缺少可用中文字体，请准备系统字体或配置TEXT_FONT_PATH")
    return path


@lru_cache(maxsize=32)
def font(size):
    return ImageFont.truetype(str(font_path()), size=size)


def raster_text(layer):
    image = Image.new("RGBA", (layer["width"], layer["height"]), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    face = font(layer["font_size"])
    line_height = max(1, round(layer["font_size"] * 1.25))
    lines = []
    # 按实际字宽折行，中英文均适用；框外内容裁切，不静默缩小字号。
    for paragraph in layer["text"].split("\n"):
        line = ""
        for char in paragraph:
            if line and draw.textlength(line + char, font=face) > image.width:
                lines.append(line)
                line = char
            else:
                line += char
        lines.append(line)
    for index, line in enumerate(lines):
        y = index * line_height
        if y >= image.height:
            break
        length = draw.textlength(line, font=face)
        align = layer.get("align", "left")
        x = (
            (image.width - length) / 2
            if align == "center"
            else image.width - length
            if align == "right"
            else 0
        )
        draw.text((x, y), line, font=face, fill=layer["fill"], anchor="lt")
    return image
