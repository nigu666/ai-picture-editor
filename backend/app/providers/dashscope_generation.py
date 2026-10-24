"""普通文生图：单次收费请求，不重试；验证下载后交给原素材保存流程。"""

import asyncio
import ipaddress
from urllib.parse import urlsplit

import httpx

from app.config import Settings
from app.providers.base import GenerateRequest, ProgressCallback, ProviderError, validate_request
from app.providers.dashscope_background import official_base
from app.providers.zhipu_background import public_host
from app.services.images import MAX_FILE_BYTES, ImageRejected, probe

SIZES = {
    "1:1": (1280, 1280),
    "4:5": (1152, 1440),
    "3:4": (1152, 1536),
    "9:16": (1008, 1792),
    "16:9": (1792, 1008),
}


def validate(request: GenerateRequest) -> None:
    validate_request(request)
    if request.references:
        raise ProviderError("普通文生图仅支持文字描述，暂不支持参考图或人物替换")
    if request.count > 4:
        raise ProviderError("百炼普通文生图每次支持1至4张候选")
    if request.negative_prompt and len(request.negative_prompt) > 500:
        raise ProviderError("百炼反向描述不能超过500字，本次未提交")
    if not 1280 * 1280 <= request.width * request.height <= 1440 * 1440 or not (
        0.25 <= request.width / request.height <= 4
    ):
        raise ProviderError("百炼生图尺寸超出模型支持范围，本次未提交")


class DashscopeImageProvider:
    name = "dashscope"

    def __init__(self, settings: Settings, *, transport=None, resolve_host=public_host):
        if not settings.dashscope_api_key.strip():
            raise ProviderError("请在开发项目/.env填写 DASHSCOPE_API_KEY，保存后重启后端")
        if settings.image_model != "wan2.6-t2i":
            raise ProviderError("当前普通文生图只支持 wan2.6-t2i")
        try:
            self.base = official_base(settings.dashscope_base_url)
        except ProviderError:
            raise ProviderError("百炼普通文生图地址须为北京地域官方根地址，不含API路径") from None
        self.key = settings.dashscope_api_key.strip()
        self.model = settings.image_model
        self.transport, self.resolve_host = transport, resolve_host

    async def download(
        self, client: httpx.AsyncClient, address: str, request: GenerateRequest
    ) -> bytes:
        parsed = urlsplit(address)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.fragment
            or parsed.port not in {None, 443}
        ):
            raise ProviderError("百炼结果须为不含凭据的HTTPS图片地址")
        addresses = await self.resolve_host(parsed.hostname)
        if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
            raise ProviderError("百炼图片地址不能指向本机或私有网络")
        async with client.stream("GET", address) as response:
            if response.status_code != 200:
                raise ProviderError("图片下载未完成，请先核对平台结果，不会重新生成")
            raw = bytearray()
            async for chunk in response.aiter_bytes():
                raw.extend(chunk)
                if len(raw) > MAX_FILE_BYTES:
                    raise ProviderError("百炼返回图片超过当前文件大小限制")
        data = bytes(raw)
        meta = probe(data)
        if (meta.width, meta.height) != (request.width, request.height):
            raise ProviderError("百炼返回图片尺寸与请求不一致")
        return data

    async def generate(
        self, request: GenerateRequest, on_progress: ProgressCallback | None = None
    ) -> list[bytes]:
        validate(request)
        parameters = {
            "size": f"{request.width}*{request.height}",
            "n": request.count,
            "prompt_extend": False,
            "watermark": True,
        }
        if request.seed is not None:
            parameters["seed"] = request.seed
        if request.negative_prompt:
            parameters["negative_prompt"] = request.negative_prompt
        if on_progress:
            await on_progress(10, "已交由百炼生成，等待图片返回")
        try:
            # 一个任务只有一个POST；HTTP和Worker均不自动重试收费请求。
            async with asyncio.timeout(240):
                async with httpx.AsyncClient(
                    timeout=180, transport=self.transport, follow_redirects=False
                ) as client:
                    response = await client.post(
                        self.base + "/api/v1/services/aigc/multimodal-generation/generation",
                        headers={"Authorization": "Bearer " + self.key},
                        json={
                            "model": self.model,
                            "input": {
                                "messages": [
                                    {"role": "user", "content": [{"text": request.prompt}]}
                                ]
                            },
                            "parameters": parameters,
                        },
                    )
                    if response.status_code in {401, 403}:
                        raise ProviderError("百炼生图鉴权失败，请核对北京地域密钥及模型权限")
                    if response.status_code == 429:
                        raise ProviderError("百炼生图受限，请核对平台额度与并发限制")
                    if response.status_code != 200:
                        raise ProviderError("百炼生成未完成，请先核对平台调用记录；不会自动重试")
                    body = response.json()
                    if not isinstance(body, dict) or body.get("code"):
                        raise ProviderError("百炼没有返回有效图片，请核对平台调用记录")
                    output = body["output"]
                    if not isinstance(output, dict) or output.get("finished") is not True:
                        raise ProviderError("百炼生图尚未正常结束，请先核对平台记录")
                    choices = output["choices"]
                    if not isinstance(choices, list) or not 1 <= len(choices) <= request.count:
                        raise ProviderError("百炼候选数量与请求不一致")
                    addresses = []
                    for choice in choices:
                        if not isinstance(choice, dict) or choice.get("finish_reason") != "stop":
                            raise ProviderError("百炼生图输出未正常完成")
                        message = choice["message"]
                        if not isinstance(message, dict):
                            raise ProviderError("百炼生图响应格式不符合预期")
                        content = message["content"]
                        if (
                            not isinstance(content, list)
                            or not content
                            or len(content) > request.count
                        ):
                            raise ProviderError("百炼生图响应格式不符合预期")
                        for item in content:
                            if (
                                not isinstance(item, dict)
                                or item.get("type") != "image"
                                or not isinstance(item.get("image"), str)
                            ):
                                raise ProviderError("百炼没有返回有效图片地址")
                            addresses.append(item["image"])
                    if len(addresses) != request.count or len(set(addresses)) != request.count:
                        raise ProviderError("百炼返回的独立候选数量与请求不一致")
                    images = []
                    for index, address in enumerate(addresses):
                        images.append(await self.download(client, address, request))
                        if on_progress:
                            await on_progress(
                                60 + 30 * (index + 1) // request.count, "已下载并核对生成图片"
                            )
                    return images
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
                "百炼生成或下载中断，不会自动重试；请先核对平台调用记录，避免重复付费"
            ) from None
