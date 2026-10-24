"""智谱文字生背景：固定官方入口，生成与下载分开，不把密钥发给图片域名。"""

import asyncio
import ipaddress
import math
import socket
from urllib.parse import urlsplit

import httpx

from app.config import Settings
from app.providers.base import ProviderError
from app.services.images import MAX_FILE_BYTES, ImageRejected, probe

SIZES = (
    (1280, 1280),
    (1568, 1056),
    (1056, 1568),
    (1472, 1088),
    (1088, 1472),
    (1728, 960),
    (960, 1728),
)


async def public_host(hostname: str) -> list[str]:
    records = await asyncio.get_running_loop().getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
    return list({record[4][0] for record in records})


def generation_size(width: int, height: int) -> tuple[int, int]:
    return min(SIZES, key=lambda size: abs(math.log((size[0] / size[1]) / (width / height))))


def image_url(value: object) -> str:
    if not isinstance(value, str):
        raise ProviderError("智谱没有返回可下载的背景图片")
    url = urlsplit(value)
    if (
        url.scheme != "https"
        or not url.hostname
        or url.username
        or url.password
        or url.port not in {None, 443}
    ):
        raise ProviderError("背景图片下载地址必须是不含凭据的 HTTPS 地址")
    return value


def configured(settings: Settings) -> None:
    if settings.background_provider != "zhipu" or not settings.zhipu_api_key.strip():
        raise ProviderError(
            "换背景尚未配置，请设置 BACKGROUND_PROVIDER=zhipu 并保留本机 ZHIPU_API_KEY"
        )


class ZhipuBackground:
    name = "zhipu-glm-image-rembg"

    def __init__(self, settings: Settings, *, transport=None, resolve_host=public_host):
        configured(settings)
        self.key = settings.zhipu_api_key
        self.transport = transport
        self.resolve_host = resolve_host

    async def generate(self, prompt: str, width: int, height: int) -> bytes:
        target = generation_size(width, height)
        instruction = (
            "为照片制作新背景。只生成环境与场景，不要生成前景人物、动物、商品或文字。背景描述："
            + prompt
        )
        try:
            async with httpx.AsyncClient(
                timeout=100, transport=self.transport, follow_redirects=False
            ) as client:
                response = await client.post(
                    "https://open.bigmodel.cn/api/paas/v4/images/generations",
                    headers={"Authorization": "Bearer " + self.key},
                    json={
                        "model": "glm-image",
                        "prompt": instruction,
                        "size": f"{target[0]}x{target[1]}",
                        "quality": "hd",
                    },
                )
                if response.status_code in {401, 403}:
                    raise ProviderError("智谱生图鉴权失败，请检查本机密钥和模型权限")
                if response.status_code == 429:
                    raise ProviderError("智谱生图调用受限，请到平台核对额度与调用限制")
                if response.status_code != 200:
                    raise ProviderError("智谱背景生成未完成，本次不会自动重试，请核对任务后再提交")
                body = response.json()
                if not isinstance(body, dict):
                    raise ProviderError("智谱返回的背景响应格式不符合预期")
                entries = body.get("data")
                if (
                    not isinstance(entries, list)
                    or len(entries) != 1
                    or not isinstance(entries[0], dict)
                ):
                    raise ProviderError("智谱返回的背景数量不符合预期")
                url = image_url(entries[0].get("url"))
                # 地址只能来自上面的官方API响应；CDN域名可变，按HTTPS、公网DNS和文件约束验证。
                addresses = await self.resolve_host(urlsplit(url).hostname)
                if not addresses or any(
                    not ipaddress.ip_address(address).is_global for address in addresses
                ):
                    raise ProviderError("背景图片下载地址不能指向本机或私有网络")
                # 不使用带 Authorization 的下载客户端；不跟随重定向。
                async with client.stream("GET", url) as download:
                    if download.status_code != 200:
                        raise ProviderError("背景图片下载未完成，已停止本次合成")
                    data = bytearray()
                    async for chunk in download.aiter_bytes():
                        data.extend(chunk)
                        if len(data) > MAX_FILE_BYTES:
                            raise ProviderError("背景图片超过当前文件大小限制")
            raw = bytes(data)
            meta = probe(raw)
            if (meta.width, meta.height) != target:
                raise ProviderError("智谱返回背景尺寸与请求不一致")
            return raw
        except ProviderError:
            raise
        except (httpx.HTTPError, ValueError, TypeError, ImageRejected, OSError):
            raise ProviderError("背景生成或下载暂时失败，请核对任务后重试") from None
