"""本地确定性占位图，非语义生成，不发起模型网络请求。"""

import asyncio
import colorsys
import hashlib
import io

from PIL import Image, ImageDraw

from app.providers.base import GenerateRequest, ProgressCallback, ProviderError, validate_request


class MockImageProvider:
    name = "mock"

    async def generate(
        self, request: GenerateRequest, on_progress: ProgressCallback | None = None
    ) -> list[bytes]:
        validate_request(request)
        if request.references:
            raise ProviderError("Mock 不支持参考图，不会模拟参考人物替换")
        if request.negative_prompt and request.negative_prompt.strip():
            raise ProviderError("Mock 不支持反向描述的语义效果")
        images = []
        for index in range(request.count):
            images.append(await asyncio.to_thread(self._render, request, index))
            if on_progress:
                await on_progress(
                    int((index + 1) / request.count * 100),
                    f"Mock 占位图已准备 {index + 1}/{request.count}",
                )
        return images

    def _render(self, request: GenerateRequest, index: int) -> bytes:
        material = (
            f"{request.prompt.strip()}|{request.width}|{request.height}|{request.seed}|{index}"
        )
        digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
        hue = int(digest[:8], 16) % 360 / 360
        accent = tuple(int(c * 255) for c in colorsys.hsv_to_rgb(hue, 0.55, 0.75))
        with Image.new("RGB", (request.width, request.height), "#eaf0f7") as image:
            draw = ImageDraw.Draw(image)
            margin = max(4, min(request.width, request.height) // 10)
            draw.rectangle(
                (margin, margin, request.width - margin - 1, request.height - margin - 1),
                outline=accent,
                width=max(2, margin // 3),
            )
            radius = max(3, min(request.width, request.height) // 5)
            cx, cy = request.width // 2, request.height // 2
            draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=accent)
            draw.rectangle((0, 0, request.width, min(request.height, 36)), fill="#182c42")
            draw.text((6, 4), "MOCK - NO AI MODEL", fill="white")
            if request.height >= 96:
                draw.text(
                    (6, request.height - 22), f"sample {index + 1} / {digest[:8]}", fill="#182c42"
                )
            output = io.BytesIO()
            image.save(output, format="PNG")
            return output.getvalue()
