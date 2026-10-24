"""只用已安装的RapidOCR 1.x模型；识别是只读操作，不触发下载。"""

import hashlib
import importlib.util
import io
import json
import math
import threading
from pathlib import Path

from PIL import Image

LOCK = threading.Lock()
ENGINE = None
MODEL_NAMES = (
    "ch_PP-OCRv4_det_infer.onnx",
    "ch_ppocr_mobile_v2.0_cls_infer.onnx",
    "ch_PP-OCRv4_rec_infer.onnx",
)


class OcrUnavailable(Exception):
    pass


class OcrBusy(Exception):
    pass


def model_directory():
    spec = importlib.util.find_spec("rapidocr_onnxruntime")
    if spec is None or spec.origin is None:
        raise OcrUnavailable("本地RapidOCR尚未安装，仍可手动添加文字")
    directory = Path(spec.origin).parent / "models"
    if not all((directory / name).is_file() for name in MODEL_NAMES):
        raise OcrUnavailable("本地OCR模型不完整，仍可手动添加文字")
    return directory


def detect(raw, width, height):
    global ENGINE
    if not LOCK.acquire(blocking=False):
        raise OcrBusy("OCR正在识别另一张图片，请稍后重试")
    try:
        directory = model_directory()
        if ENGINE is None:
            from rapidocr_onnxruntime import RapidOCR

            ENGINE = RapidOCR(
                det_model_path=str(directory / MODEL_NAMES[0]),
                cls_model_path=str(directory / MODEL_NAMES[1]),
                rec_model_path=str(directory / MODEL_NAMES[2]),
                intra_op_num_threads=2,
                inter_op_num_threads=1,
            )
        image = Image.open(io.BytesIO(raw)).convert("RGBA")
        background = Image.new("RGBA", image.size, "white")
        background.alpha_composite(image)
        result, _ = ENGINE(background.convert("RGB"))
        scale_x, scale_y = width / image.width, height / image.height
        boxes = []
        for points, value, score in result or []:
            if (
                not isinstance(value, str)
                or not value.strip()
                or not math.isfinite(float(score))
                or float(score) < 0.5
            ):
                continue
            points = [(float(x) * scale_x, float(y) * scale_y) for x, y in points]
            if not all(math.isfinite(x) and math.isfinite(y) for x, y in points):
                continue
            left = max(0, min(width - 1, math.floor(min(x for x, _ in points))))
            top = max(0, min(height - 1, math.floor(min(y for _, y in points))))
            right = max(left + 1, min(width, math.ceil(max(x for x, _ in points))))
            bottom = max(top + 1, min(height, math.ceil(max(y for _, y in points))))
            content = value.strip()[:1000]
            if any(ord(c) < 32 and c != "\n" for c in content):
                continue
            key = hashlib.sha256(
                json.dumps([content, left, top, right, bottom], ensure_ascii=False).encode()
            ).hexdigest()[:16]
            boxes.append(
                dict(
                    id=key,
                    text=content,
                    x=left,
                    y=top,
                    width=min(4096, right - left),
                    height=min(4096, bottom - top),
                    font_size=max(6, min(512, round((bottom - top) * 0.72))),
                    confidence=round(min(1, float(score)), 4),
                )
            )
        boxes.sort(key=lambda box: (box["y"], box["x"]))
        return {"boxes": boxes[:100], "truncated": len(boxes) > 100}
    except (OcrBusy, OcrUnavailable):
        raise
    except Exception:
        raise OcrUnavailable("OCR本地识别暂未完成，可重试或手动添加文字；画布未修改") from None
    finally:
        LOCK.release()
