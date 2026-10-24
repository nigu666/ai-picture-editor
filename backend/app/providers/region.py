"""万相2.1局部重绘，复用已验证的异步查询和安全下载。"""

import base64

import httpx

from app.providers.base import ProviderError
from app.providers.dashscope_background import official_base
from app.providers.outpainting import DashscopeOutpainting, ExpansionError, task_id
from app.providers.zhipu_background import public_host

NAME = "dashscope-wanx2.1-masked-edit"


def configured(settings):
    if settings.region_provider != "dashscope" or not settings.dashscope_api_key.strip():
        raise ProviderError("局部编辑未启用或未配置北京地域百炼密钥")
    return official_base(settings.dashscope_base_url)


class DashscopeRegion(DashscopeOutpainting):
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
        self.model = settings.region_model
        self.transport, self.resolve_host = transport, resolve_host
        self.poll_interval, self.poll_timeout = poll_interval, poll_timeout

    async def submit(self, image, mask, prompt):
        def data(raw):
            return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")

        try:
            async with httpx.AsyncClient(
                timeout=30, transport=self.transport, follow_redirects=False
            ) as client:
                response = await client.post(
                    self.base + "/api/v1/services/aigc/image2image/image-synthesis",
                    headers={**self.headers(), "X-DashScope-Async": "enable"},
                    json={
                        "model": self.model,
                        "input": {
                            "function": "description_edit_with_mask",
                            "prompt": prompt,
                            "base_image_url": data(image),
                            "mask_image_url": data(mask),
                        },
                        "parameters": {"n": 1, "watermark": True},
                    },
                )
            if response.status_code in {401, 403}:
                raise ExpansionError("局部编辑鉴权失败，请核对北京地域百炼密钥及模型权限")
            if response.status_code == 429:
                raise ExpansionError("局部编辑限流，请核对平台额度与并发限制")
            if response.status_code != 200:
                raise ExpansionError(
                    f"局部编辑提交未确认（HTTP {response.status_code}），不会自动重试"
                )
            return task_id(response.json()["output"]["task_id"])
        except ProviderError as exc:
            raise ExpansionError(str(exc).replace("扩图", "局部编辑")) from None
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            raise ExpansionError(
                "局部编辑提交响应未确认，不会自动重试，请到百炼核对调用记录"
            ) from None

    async def wait(self, remote_id):
        try:
            return await super().wait(remote_id)
        except ExpansionError as exc:
            raise ExpansionError(
                str(exc).replace("扩图", "局部编辑"), recoverable=exc.recoverable
            ) from None
