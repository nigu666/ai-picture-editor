"""单底图文档的无损画布变换；坐标变换不修改存储中的图片像素。"""

from copy import deepcopy

from fastapi import HTTPException

MIN_CROP = 32
RATIOS = {"1:1": (1, 1), "4:5": (4, 5), "3:4": (3, 4), "9:16": (9, 16), "16:9": (16, 9)}


def editable(document: dict) -> dict:
    if len(document["layers"]) != 1 or document["layers"][0]["kind"] != "image":
        raise HTTPException(409, "当前工具仅支持单底图画布，多图层编辑将在后续章节接入")
    return deepcopy(document)


def transform(document: dict, operation: str) -> dict:
    doc = editable(document)
    width, height = doc["width"], doc["height"]
    t = doc["layers"][0]["transform"]
    x, y, angle = t["x"], t["y"], t["rotation"]
    # 将画布坐标变换左乘到图层变换；翻转会改变角度符号，不能只切换 scale。
    if operation == "flip_horizontal":
        t.update(x=width - x, rotation=(-angle) % 360, scale_x=-t["scale_x"])
    elif operation == "flip_vertical":
        t.update(y=height - y, rotation=(-angle) % 360, scale_y=-t["scale_y"])
    elif operation == "rotate_right":
        t.update(x=height - y, y=x, rotation=(angle + 90) % 360)
        doc.update(width=height, height=width)
    elif operation == "rotate_left":
        t.update(x=y, y=width - x, rotation=(angle - 90) % 360)
        doc.update(width=height, height=width)
    else:
        raise HTTPException(422, "不支持的画布变换")
    return doc


def crop_box(width: int, height: int, ratio: str) -> tuple[int, int, int, int]:
    if ratio not in RATIOS:
        raise HTTPException(422, "不支持的裁剪比例")
    a, b = RATIOS[ratio]
    multiple = min(width // a, height // b)
    w, h = a * multiple, b * multiple
    if min(w, h) < MIN_CROP:
        raise HTTPException(422, "裁剪区域过小，最短边至少需要 32 像素")
    return (width - w) // 2, (height - h) // 2, w, h


def crop(document: dict, ratio: str) -> dict:
    doc = editable(document)
    x, y, width, height = crop_box(doc["width"], doc["height"], ratio)
    t = doc["layers"][0]["transform"]
    t["x"] -= x
    t["y"] -= y
    doc.update(width=width, height=height)
    return doc
