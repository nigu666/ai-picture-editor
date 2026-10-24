"""在内存中渲染当前单底图画布，向模型传递有大小上限的预览，保留原图。"""

import base64
import io

from PIL import Image

from app.agent.llm import PlannerUnavailable
from app.edits.render import render_document

MAX_PREVIEW_SIDE = 1536
MAX_PREVIEW_BYTES = 2 * 1024 * 1024


def render_preview(data: bytes, document: dict) -> Image.Image:
    picture = render_document(data, document, max_side=MAX_PREVIEW_SIDE)
    canvas = Image.new("RGBA", picture.size, "white")
    canvas.alpha_composite(picture)
    return canvas.convert("RGB")


def preview_data_url(data: bytes, document: dict) -> str:
    try:
        image = render_preview(data, document)
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=85, optimize=True)
        encoded = output.getvalue()
        if len(encoded) > MAX_PREVIEW_BYTES:
            raise ValueError("preview too large")
        return "data:image/jpeg;base64," + base64.b64encode(encoded).decode("ascii")
    except Exception as exc:
        raise PlannerUnavailable("当前画布预览读取失败，本轮未发送给模型；请刷新后重试") from exc
