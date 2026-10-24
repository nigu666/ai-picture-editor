"""百炼专用扩图：创建一次云任务，查询与下载可独立恢复。"""

import asyncio
import base64
import io
import ipaddress
import re
from urllib.parse import urlsplit

import httpx
from PIL import Image

from app.config import Settings
from app.providers.base import ProviderError
from app.providers.dashscope_background import official_base
from app.providers.zhipu_background import public_host
from app.services.images import MAX_FILE_BYTES, ImageRejected, probe

NAME = "dashscope-wanx2.1-expand"


class ExpansionError(ProviderError):
    def __init__(self, message: str, *, recoverable=False):
        self.recoverable = recoverable
        super().__init__(message)


def configured(settings: Settings):
    if settings.outpainting_provider != "dashscope" or not settings.dashscope_api_key.strip():
        raise ProviderError("扩图尚未配置，请启用OUTPAINTING_PROVIDER=dashscope并填写百炼密钥")
    return official_base(settings.dashscope_base_url)


def task_id(value) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", value):
        raise ExpansionError("百炼没有返回有效的扩图任务编号，请先核对平台调用记录")
    return value


class DashscopeOutpainting:
    name = NAME

    def __init__(
        self,
        settings: Settings,
        *,
        transport=None,
        resolve_host=public_host,
        poll_interval=2,
        poll_timeout=150,
    ):
        self.base = configured(settings)
        self.key = settings.dashscope_api_key.strip()
        self.model = settings.outpainting_model
        self.transport, self.resolve_host = transport, resolve_host
        self.poll_interval, self.poll_timeout = poll_interval, poll_timeout

    def headers(self):
        return {"Authorization": "Bearer " + self.key}

    async def submit(self, image: bytes, target: dict) -> str:
        with Image.open(io.BytesIO(image)) as source:
            width, height = source.size
        parameters = {
            # 实际接口以完整原图边长计算各侧增量：1 + 该侧新增像素 / 原边长。
            "left_scale": 1 + target["left_offset"] / width,
            "right_scale": 1 + target["right_offset"] / width,
            "top_scale": 1 + target["top_offset"] / height,
            "bottom_scale": 1 + target["bottom_offset"] / height,
            "n": 1,
            "watermark": True,
        }
        if any(
            not 1 <= parameters[k] <= 2
            for k in ("left_scale", "right_scale", "top_scale", "bottom_scale")
        ):
            raise ExpansionError("目标扩展比例超出万相限制，本次未调用模型")
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
                            "function": "expand",
                            "prompt": "自然延展原画面的环境、纹理与光线，保持原有主体和场景一致。",
                            "base_image_url": "data:image/png;base64,"
                            + base64.b64encode(image).decode("ascii"),
                        },
                        "parameters": parameters,
                    },
                )
            if r.status_code in {401, 403}:
                raise ExpansionError("百炼扩图鉴权失败，请检查北京地域密钥和模型权限")
            if r.status_code == 429:
                raise ExpansionError("百炼扩图受限，请核对平台额度与并发限制")
            if r.status_code != 200:
                raise ExpansionError(
                    f"扩图提交未完成（HTTP {r.status_code}），不会自动重试，请核对百炼记录"
                )
            body = r.json()
            return task_id(body["output"]["task_id"])
        except ProviderError:
            raise
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            raise ExpansionError("扩图提交响应未确认，不会自动重试，请先核对平台调用记录") from None

    async def wait(self, remote_id: str) -> bytes:
        remote_id = task_id(remote_id)
        try:
            async with asyncio.timeout(self.poll_timeout):
                async with httpx.AsyncClient(
                    timeout=20, transport=self.transport, follow_redirects=False
                ) as client:
                    while True:
                        r = await client.get(
                            self.base + "/api/v1/tasks/" + remote_id, headers=self.headers()
                        )
                        if r.status_code != 200:
                            raise ExpansionError(
                                "扩图结果查询暂时失败，可继续查询原云端任务", recoverable=True
                            )
                        output = r.json()["output"]
                        if output.get("task_id") != remote_id:
                            raise ExpansionError("百炼扩图任务编号不匹配，已停止查询")
                        status = output.get("task_status")
                        if status == "SUCCEEDED":
                            results = output.get("results")
                            if (
                                not isinstance(results, list)
                                or len(results) != 1
                                or not isinstance(results[0], dict)
                            ):
                                raise ExpansionError("百炼扩图结果数量不符，已停止下载")
                            return await self.download(client, results[0].get("url"))
                        if status in {"FAILED", "CANCELED", "UNKNOWN"}:
                            raise ExpansionError("百炼扩图未成功或任务已过期，请核对平台任务记录")
                        if status not in {"PENDING", "RUNNING"}:
                            raise ExpansionError(
                                "百炼扩图状态无法识别，可继续查询原任务", recoverable=True
                            )
                        await asyncio.sleep(self.poll_interval)
        except ProviderError:
            raise
        except (httpx.HTTPError, ValueError, KeyError, TypeError, TimeoutError, OSError):
            raise ExpansionError(
                "扩图结果查询或下载中断，可继续查询原云端任务", recoverable=True
            ) from None

    async def download(self, client, address):
        if not isinstance(address, str):
            raise ExpansionError("百炼扩图结果缺少图片地址", recoverable=True)
        url = urlsplit(address)
        if (
            url.scheme != "https"
            or not url.hostname
            or url.username
            or url.password
            or url.fragment
            or url.port not in {None, 443}
        ):
            raise ExpansionError("扩图下载地址须为不含凭据的HTTPS地址")
        addresses = await self.resolve_host(url.hostname)
        if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
            raise ExpansionError("扩图下载地址不能指向本机或私有网络")
        async with client.stream("GET", address) as r:
            if r.status_code != 200:
                raise ExpansionError("扩图图片下载暂时失败，可继续查询原任务", recoverable=True)
            data = bytearray()
            async for chunk in r.aiter_bytes():
                data.extend(chunk)
                if len(data) > MAX_FILE_BYTES:
                    raise ExpansionError("扩图图片超过当前文件大小限制")
        raw = bytes(data)
        try:
            probe(raw)
        except ImageRejected:
            raise ExpansionError("扩图模型返回了无效图片") from None
        return raw
