"""万相超分；复用已经验证的异步查询和安全下载，不依赖扩图开关。"""

import base64

import httpx

from app.providers.base import ProviderError
from app.providers.dashscope_background import official_base
from app.providers.outpainting import DashscopeOutpainting, ExpansionError, task_id
from app.providers.zhipu_background import public_host

NAME = "dashscope-wanx2.1-super-resolution"


def configured(settings):
    if settings.upscaling_provider != "dashscope" or not settings.dashscope_api_key.strip():
        raise ProviderError("超分尚未配置，请启用UPSCALING_PROVIDER=dashscope并填写百炼密钥")
    return official_base(settings.dashscope_base_url)


class DashscopeUpscaling(DashscopeOutpainting):
    name = NAME

    def __init__(
        self,
        settings,
        *,
        transport=None,
        resolve_host=public_host,
        poll_interval=2,
        poll_timeout=150,
    ):
        self.base = configured(settings)
        self.key = settings.dashscope_api_key.strip()
        self.model = settings.upscaling_model
        self.transport, self.resolve_host = transport, resolve_host
        self.poll_interval, self.poll_timeout = poll_interval, poll_timeout

    async def submit(self, image: bytes, target: dict) -> str:
        try:
            async with httpx.AsyncClient(
                timeout=30, transport=self.transport, follow_redirects=False
            ) as client:
                r = await client.post(
                    self.base + "/api/v1/services/aigc/image2image/image-synthesis",
                    headers={**self.headers(), "X-DashScope-Async": "enable"},
                    json={
                        "model": self.model,
                        "input": {
                            "function": "super_resolution",
                            "prompt": "图像超分。",
                            "base_image_url": "data:image/png;base64,"
                            + base64.b64encode(image).decode("ascii"),
                        },
                        "parameters": {
                            "upscale_factor": target["scale"],
                            "n": 1,
                            "watermark": True,
                        },
                    },
                )
            if r.status_code in {401, 403}:
                raise ExpansionError("百炼超分鉴权失败，请检查北京地域密钥和模型权限")
            if r.status_code == 429:
                raise ExpansionError("百炼超分受限，请核对额度与并发限制")
            if r.status_code != 200:
                raise ExpansionError(f"超分提交未完成（HTTP {r.status_code}），不会自动重试")
            return task_id(r.json()["output"]["task_id"])
        except ProviderError as exc:
            raise ExpansionError(str(exc).replace("扩图", "超分")) from None
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            raise ExpansionError("超分提交响应未确认，不会自动重试，请核对百炼记录") from None

    async def wait(self, remote_id: str) -> bytes:
        try:
            return await super().wait(remote_id)
        except ExpansionError as exc:
            raise ExpansionError(
                str(exc).replace("扩图", "超分"), recoverable=exc.recoverable
            ) from None
