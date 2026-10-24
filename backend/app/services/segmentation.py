"""SAM vit_b 量化 CPU 点选；本地固定权重，不在接口中下载或回退画圆。"""

import hashlib
import io
import json
import threading
from collections import OrderedDict
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image

from app.edits.render import render_document

MODEL_HASHES = {
    "sam_vit_b_01ec64.encoder.quant.onnx": "26fc0e01d2fa34ed2d3f91259118482d",
    "sam_vit_b_01ec64.decoder.quant.onnx": "45391530307d1aee79b2a1507769e6c7",
}
CACHE_LIMIT = 4


class SamUnavailable(Exception):
    pass


class SamBusy(Exception):
    pass


def verify_models(directory: Path):
    for name, expected in MODEL_HASHES.items():
        path = directory / name
        if not path.is_file():
            raise SamUnavailable("SAM点选模型未准备好，请运行本地SAM模型准备脚本")
        with path.open("rb") as stream:
            if hashlib.file_digest(stream, "md5").hexdigest() != expected:
                raise SamUnavailable("SAM模型文件校验失败，请重新准备模型")


class SamEngine:
    def __init__(self, directory: Path):
        self.directory = directory
        self.lock = threading.Lock()
        self.encoder = self.decoder = None
        self.embeddings = OrderedDict()
        self.encodes = self.decodes = self.hits = 0

    def load(self):
        if self.encoder is not None:
            return
        import onnxruntime as ort

        verify_models(self.directory)
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        providers = ["CPUExecutionProvider"]
        encoder, decoder = [
            ort.InferenceSession(str(self.directory / name), options, providers=providers)
            for name in MODEL_HASHES
        ]
        self.encoder, self.decoder = encoder, decoder

    def embedding(self, source: Image.Image, key: str):
        if key in self.embeddings:
            self.hits += 1
            self.embeddings.move_to_end(key)
            return self.embeddings[key]
        import cv2

        # 与 rembg SAM 预处理一致：等比缩放后补黑，不把长宽分别拉伸。
        target = (684, 1024)
        scale = min(target[1] / source.width, target[0] / source.height)
        transform = np.array([[scale, 0, 0], [0, scale, 0], [0, 0, 1]], dtype=np.float64)
        rgb = Image.new("RGB", source.size, "white")
        rgb.paste(source, mask=source.getchannel("A"))
        pixels = cv2.warpAffine(np.asarray(rgb), transform[:2], (target[1], target[0]))
        vector = self.encoder.run(None, {self.encoder.get_inputs()[0].name:
                                       pixels.astype(np.float32)})[0]
        entry = (vector, transform, target)
        self.encodes += 1
        self.embeddings[key] = entry
        while len(self.embeddings) > CACHE_LIMIT:
            self.embeddings.popitem(last=False)
        return entry

    def run(self, raw: bytes, document: dict, scope: str, prompts: list[dict] | None):
        # 不排队积累CPU任务。取消请求不会中止ONNX线程，但锁会保留到计算结束。
        if not self.lock.acquire(blocking=False):
            raise SamBusy("SAM正在处理另一张图片，请稍后重试")
        try:
            self.load()
            key = hashlib.sha256(
                scope.encode() + hashlib.sha256(raw).digest()
                + json.dumps(document, sort_keys=True).encode()
            ).hexdigest()
            source = render_document(raw, document)
            if source.getchannel("A").getbbox() is None:
                raise SamUnavailable("当前画布没有可识别的可见内容")
            cached = key in self.embeddings
            vector, transform, target = self.embedding(source, key)
            if prompts is None:
                return {"model": "SAM vit_b quantized", "cache_hit": cached,
                        "width": source.width, "height": source.height}
            coords = np.array([[min(source.width - 1, p["x"] * source.width),
                                min(source.height - 1, p["y"] * source.height)]
                               for p in prompts] + [[0, 0]], dtype=np.float32)
            coords = (np.c_[coords, np.ones(len(coords))] @ transform.T)[:, :2]
            masks, scores, _ = self.decoder.run(None, {
                "image_embeddings": vector,
                "point_coords": coords[None].astype(np.float32),
                "point_labels": np.array([[p["label"] for p in prompts] + [-1]], np.float32),
                "mask_input": np.zeros((1, 1, 256, 256), np.float32),
                "has_mask_input": np.zeros(1, np.float32),
                "orig_im_size": np.array(target, np.float32),
            })
            self.decodes += 1
            # 多候选只取模型评分最高者，不能把所有候选并集成整片背景。
            chosen = masks[0, int(np.argmax(scores[0]))]
            import cv2

            restored = cv2.warpAffine(chosen, np.linalg.inv(transform)[:2], source.size)
            selected = (restored > 0) & (np.asarray(source.getchannel("A")) > 0)
            if not selected.any():
                raise SamUnavailable("没有识别到可选区域，请换一个保留点或使用笔刷选区")
            output = io.BytesIO()
            Image.fromarray(selected.astype(np.uint8) * 255).save(output, format="PNG")
            return output.getvalue()
        finally:
            self.lock.release()


@lru_cache(maxsize=1)
def engine(directory: str):
    return SamEngine(Path(directory))
