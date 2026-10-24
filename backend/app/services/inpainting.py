"""本地LaMa ONNX补洞；不依据文字生图，遮罩外逐像素保留。"""

import hashlib
import io
import threading
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image

from app.edits.region import composite, png
from app.providers.base import ProviderError

MODEL_SHA256 = "1faef5301d78db7dda502fe59966957ec4b79dd64e16f03ed96913c7a4eb68d6"
LOCK = threading.Lock()


@lru_cache(maxsize=2)
def _verified(path, size, modified_ns):
    with Path(path).open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != MODEL_SHA256:
            raise ProviderError("本地背景修复模型校验失败，请重新准备模型")
    return True


def verify_model(path):
    try:
        info = Path(path).stat()
        _verified(str(Path(path).resolve()), info.st_size, info.st_mtime_ns)
    except OSError:
        raise ProviderError("本地LaMa背景修复模型未准备好，请运行模型准备脚本") from None


@lru_cache(maxsize=1)
def _engine(path):
    import onnxruntime as ort

    verify_model(path)
    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    options.inter_op_num_threads = 1
    model = ort.InferenceSession(
        str(path), sess_options=options, providers=["CPUExecutionProvider"]
    )
    values = model.get_inputs()
    inputs = {value.name: (value.shape[1:], value.type) for value in values}
    if inputs != {
        "image": ([3, 512, 512], "tensor(float)"),
        "mask": ([1, 512, 512], "tensor(float)"),
    } or any(value.shape[0] not in {1, "batch"} for value in values):
        raise ProviderError("本地背景模型输入结构不符")
    return model


def repair(source, mask_png, model_path):
    verify_model(model_path)
    image = Image.open(io.BytesIO(source)).convert("RGBA")
    mask = Image.open(io.BytesIO(mask_png))
    if (
        mask.mode != "L"
        or mask.size != image.size
        or not mask.getbbox()
        or not set(np.unique(np.asarray(mask))) <= {0, 255}
    ):
        raise ProviderError("本地背景修复需要与画布匹配的非空黑白遮罩")
    if image.getchannel("A").getextrema() != (255, 255):
        raise ProviderError("本地背景修复需要完整不透明画布")
    if min(image.size) < 32 or max(image.size) > 4096:
        raise ProviderError("本地背景修复画布尺寸超出范围")
    left, top, right, bottom = mask.getbbox()
    padding = max(64, round(max(right - left, bottom - top) * 0.25))
    box = (
        max(0, left - padding),
        max(0, top - padding),
        min(image.width, right + padding),
        min(image.height, bottom + padding),
    )
    crop, cropped_mask = image.crop(box).convert("RGB"), mask.crop(box)
    scale = 512 / max(crop.size)
    width, height = max(1, round(crop.width * scale)), max(1, round(crop.height * scale))
    small = (
        np.asarray(crop.resize((width, height), Image.Resampling.LANCZOS), dtype=np.float32) / 255
    )
    selected = (
        np.asarray(cropped_mask.resize((width, height), Image.Resampling.NEAREST), dtype=np.float32)
        / 255
    )
    small = np.pad(small, ((0, 512 - height), (0, 512 - width), (0, 0)), mode="symmetric")
    selected = np.pad(selected, ((0, 512 - height), (0, 512 - width)), mode="symmetric")
    with LOCK:
        output = _engine(str(Path(model_path).resolve())).run(
            None,
            {
                "image": small.transpose(2, 0, 1)[None].astype(np.float32),
                "mask": selected[None, None].astype(np.float32),
            },
        )[0]
    if output.shape != (1, 3, 512, 512) or not np.isfinite(output).all():
        raise ProviderError("本地背景修复结果无效，原图未修改")
    generated = Image.fromarray(
        np.clip(output[0].transpose(1, 2, 0)[:height, :width], 0, 255).astype(np.uint8)
    ).resize(crop.size, Image.Resampling.LANCZOS)
    canvas = image.convert("RGB")
    canvas.paste(generated, (box[0], box[1]))
    return composite(source, png(canvas), mask_png)
