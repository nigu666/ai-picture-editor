"""百炼万相背景生成：仅向北京官方入口发送密钥，下载单独验证。"""

import asyncio
import ipaddress
import math
import re
from urllib.parse import urlsplit

import httpx

from app.config import Settings
from app.providers.base import ProviderError
from app.providers.zhipu_background import public_host
from app.services.images import MAX_FILE_BYTES, ImageRejected, probe

# 各尺寸在万相2.6的总像素区间内；与当前画布最接近的比例优先。
SIZES = ((1280, 1280), (1152, 1440), (1152, 1536), (960, 1728), (1728, 960))


def official_base(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.port not in {None, 443}
        or parsed.path not in {"", "/"}
        or not (
            parsed.hostname == "dashscope.aliyuncs.com"
            or re.fullmatch(r"[a-zA-Z0-9-]+\.cn-beijing\.maas\.aliyuncs\.com", parsed.hostname)
        )
    ):
        raise ProviderError("百炼换背景地址须为北京地域官方根地址，不含API路径")
    return value.rstrip("/")


def configured(settings: Settings) -> None:
    if settings.background_provider != "dashscope" or not settings.dashscope_api_key.strip():
        raise ProviderError("请在开发项目/.env填写 DASHSCOPE_API_KEY，保存后重启后端")
    official_base(settings.dashscope_base_url)


def generation_size(width: int, height: int) -> tuple[int, int]:
    if width <= 0 or height <= 0:
        raise ProviderError("画布尺寸无效")
    return min(SIZES, key=lambda size: abs(math.log((size[0] / size[1]) / (width / height))))


class DashscopeBackground:
    name = "dashscope-wan2.6-t2i-rembg"

    def __init__(self, settings: Settings, *, transport=None, resolve_host=public_host):
        configured(settings)
        self.key = settings.dashscope_api_key.strip()
        self.base = official_base(settings.dashscope_base_url)
        self.model = settings.background_model
        self.transport, self.resolve_host = transport, resolve_host

    async def generate(self, prompt: str, width: int, height: int) -> bytes:
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 800:
            raise ProviderError("背景描述须为1至800字")
        target = generation_size(width, height)
        instruction = "只生成照片的环境背景，不生成前景人物、动物、商品或文字。场景：" + prompt
        try:
            # 四张候选串行最坏约480秒，Worker600秒；本次HTTP不自动重试。
            async with asyncio.timeout(120):
                async with httpx.AsyncClient(
                    timeout=100,
                    transport=self.transport,
                    follow_redirects=False,
                ) as client:
                    response = await client.post(
                        self.base + "/api/v1/services/aigc/multimodal-generation/generation",
                        headers={"Authorization": "Bearer " + self.key},
                        json={
                            "model": self.model,
                            "input": {
                                "messages": [{"role": "user", "content": [{"text": instruction}]}]
                            },
                            "parameters": {
                                "size": f"{target[0]}*{target[1]}",
                                "n": 1,
                                "prompt_extend": False,
                                "watermark": True,
                            },
                        },
                    )
                    if response.status_code in {401, 403}:
                        raise ProviderError("百炼生图鉴权失败，请检查北京地域密钥和模型权限")
                    if response.status_code == 429:
                        raise ProviderError("百炼生图受限，请到平台核对额度与并发限制")
                    if response.status_code != 200:
                        raise ProviderError(
                            "百炼背景生成未完成，不会自动重试，请先核对平台调用记录"
                        )
                    body = response.json()
                    if not isinstance(body, dict) or body.get("code"):
                        raise ProviderError("百炼没有返回有效的背景生成结果")
                    choices = body["output"]["choices"]
                    if not isinstance(choices, list) or len(choices) != 1:
                        raise ProviderError("百炼背景候选数量与请求不一致")
                    if choices[0].get("finish_reason") != "stop":
                        raise ProviderError("百炼背景输出未正常完成")
                    content = choices[0]["message"]["content"]
                    if not isinstance(content, list) or len(content) != 1:
                        raise ProviderError("百炼背景响应格式不符合预期")
                    address = content[0]["image"]
                    if not isinstance(address, str):
                        raise ProviderError("百炼没有返回图片地址")
                    parsed = urlsplit(address)
                    if (
                        parsed.scheme != "https"
                        or not parsed.hostname
                        or parsed.username
                        or parsed.password
                        or parsed.fragment
                        or parsed.port not in {None, 443}
                    ):
                        raise ProviderError("百炼图片地址必须是不含凭据的HTTPS地址")
                    addresses = await self.resolve_host(parsed.hostname)
                    if not addresses or any(
                        not ipaddress.ip_address(ip).is_global for ip in addresses
                    ):
                        raise ProviderError("百炼图片地址不能指向本机或私有网络")
                    async with client.stream("GET", address) as download:
                        if download.status_code != 200:
                            raise ProviderError("百炼图片下载未完成，请先核对平台结果")
                        data = bytearray()
                        async for chunk in download.aiter_bytes():
                            data.extend(chunk)
                            if len(data) > MAX_FILE_BYTES:
                                raise ProviderError("百炼背景图片超过当前大小限制")
            raw = bytes(data)
            meta = probe(raw)
            if (meta.width, meta.height) != target:
                raise ProviderError("百炼背景返回尺寸与请求不一致")
            return raw
        except ProviderError:
            raise
        except (
            httpx.HTTPError,
            ValueError,
            TypeError,
            KeyError,
            IndexError,
            ImageRejected,
            OSError,
            TimeoutError,
        ):
            raise ProviderError(
                "百炼背景生成或下载失败，不会自动重试；请先核对平台调用记录"
            ) from None
