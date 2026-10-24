"""将生成背景居中覆盖到当前画布，再合成已分离的主体。"""

import io

from PIL import Image, ImageOps

from app.services.images import MAX_PIXELS


def compose(subject: bytes, background: bytes) -> bytes:
    with Image.open(io.BytesIO(subject)) as image:
        foreground = image.convert("RGBA")
    if foreground.width * foreground.height > MAX_PIXELS:
        raise ValueError("canvas too large")
    with Image.open(io.BytesIO(background)) as image:
        backdrop = ImageOps.fit(
            image.convert("RGB"), foreground.size, method=Image.Resampling.LANCZOS
        ).convert("RGBA")
    backdrop.alpha_composite(foreground)
    output = io.BytesIO()
    backdrop.save(output, format="PNG")
    return output.getvalue()
