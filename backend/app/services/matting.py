"""本地 CPU 主体分割：校验预置权重、复用推理会话，不在请求中下载。"""

import hashlib
import io
import threading
from functools import lru_cache
from pathlib import Path

from PIL import ImageChops

from app.edits.render import render_document

MODEL_MD5 = "8e83ca70e441ab06c318d82300c84806"
MODEL_URL = "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2netp.onnx"
_lock = threading.Lock()


class MattingUnavailable(Exception):
    pass


def verify_model(path: Path) -> None:
    if not path.is_file():
        raise MattingUnavailable("去背景模型未安装，请先运行本地模型准备脚本")
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "md5").hexdigest()
    if digest != MODEL_MD5:
        raise MattingUnavailable("去背景模型校验失败，请重新运行本地模型准备脚本")


@lru_cache(maxsize=2)
def _session(path: str):
    import onnxruntime as ort
    from rembg import new_session

    verify_model(Path(path))
    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    options.inter_op_num_threads = 1
    # u2net_custom 只读取指定文件，不调用下载器；权重已按官方 u2netp 摘要验证。
    return new_session(
        "u2net_custom", model_path=path, sess_opts=options, providers=["CPUExecutionProvider"]
    )


def remove_background(data: bytes, document: dict, model_path: Path) -> bytes:
    from rembg import remove

    image = render_document(data, document)
    # Worker 可并发其他任务，本地模型串行使用，避免多会话争抢 CPU/内存。
    with _lock:
        mask = remove(
            image.convert("RGB"), session=_session(str(model_path.resolve())), only_mask=True
        )
    alpha = ImageChops.multiply(image.getchannel("A"), mask.convert("L"))
    if alpha.getbbox() is None:
        raise MattingUnavailable("没有识别到可保留的主体，请换一张主体清晰的图片")
    image.putalpha(alpha)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()
