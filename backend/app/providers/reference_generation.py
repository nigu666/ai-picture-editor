"""千问参考图编辑：只发一次生成请求，图片以内嵌数据传入。"""

import asyncio
import base64

import httpx

from app.providers.base import GenerateRequest, ProviderError, validate_request
from app.providers.dashscope_background import official_base
from app.providers.dashscope_generation import DashscopeImageProvider
from app.providers.zhipu_background import public_host
from app.services.images import ImageRejected, probe

MAX_REFERENCE_BYTES = 10 * 1024 * 1024
MIN_REFERENCE_SIDE, MAX_REFERENCE_SIDE = 384, 3072


def configured(settings):
    if not settings.reference_generation_enabled or settings.image_provider != "dashscope":
        raise ProviderError("参考图生成尚未启用，不会退回纯文字生图或Mock")
    if not settings.dashscope_api_key.strip():
        raise ProviderError("参考图生成需要北京地域DASHSCOPE_API_KEY")
    if settings.reference_image_model != "qwen-image-2.0-pro":
        raise ProviderError("当前参考图生成只支持qwen-image-2.0-pro")
    try:
        return official_base(settings.dashscope_base_url)
    except ProviderError:
        raise ProviderError("参考图接口地址须为百炼北京地域官方根地址") from None


def validate_parameters(request: GenerateRequest):
    validate_request(request)
    if request.count != 1:
        raise ProviderError("当前参考图生成每次只支持1张候选")
    if len(request.prompt) > 800:
        raise ProviderError("参考图修改描述不能超过800字")
    if request.negative_prompt and len(request.negative_prompt) > 500:
        raise ProviderError("参考图反向描述不能超过500字")
    if any(not 512 <= side <= 2048 or side % 16 for side in (request.width, request.height)):
        raise ProviderError("参考图输出尺寸须为512至2048之间、且为16倍数的像素")


def validate_metadata(meta):
    if meta.size_bytes > MAX_REFERENCE_BYTES:
        raise ProviderError("单张参考图不能超过10MB")
    if not all(
        MIN_REFERENCE_SIDE <= side <= MAX_REFERENCE_SIDE for side in (meta.width, meta.height)
    ):
        raise ProviderError("本阶段参考图的宽和高均须在384至3072像素之间")
    if meta.image_format not in {"JPEG", "PNG", "WEBP"}:
        raise ProviderError("参考图仅支持JPG、PNG与WebP")


class ReferenceImageProvider(DashscopeImageProvider):
    name = "dashscope-reference"

    def __init__(self, settings, *, transport=None, resolve_host=public_host):
        self.base = configured(settings)
        self.key = settings.dashscope_api_key.strip()
        self.model = settings.reference_image_model
        self.transport, self.resolve_host = transport, resolve_host

    async def generate(self, request: GenerateRequest, on_progress=None) -> list[bytes]:
        validate_parameters(request)
        if not 1 <= len(request.references) <= 3:
            raise ProviderError("参考图生成需要1至3张已选择的图片")
        content = []
        try:
            for raw in request.references:
                if len(raw) > MAX_REFERENCE_BYTES:
                    raise ProviderError("单张参考图不能超过10MB")
                meta = await asyncio.to_thread(probe, raw)
                validate_metadata(meta)
                content.append(
                    {
                        "image": f"data:{meta.content_type};base64,"
                        + base64.b64encode(raw).decode("ascii")
                    }
                )
        except ImageRejected:
            raise ProviderError("参考图片无法解码，本次未调用模型") from None
        content.append({"text": request.prompt})
        parameters = {
            "n": 1,
            "size": f"{request.width}*{request.height}",
            "watermark": True,
            "prompt_extend": False,
        }
        if request.seed is not None:
            parameters["seed"] = request.seed
        if request.negative_prompt:
            parameters["negative_prompt"] = request.negative_prompt
        if on_progress:
            await on_progress(10, "参考图已核对，等待百炼返回候选")
        try:
            async with asyncio.timeout(300):
                async with httpx.AsyncClient(
                    timeout=240, transport=self.transport, follow_redirects=False
                ) as client:
                    response = await client.post(
                        self.base + "/api/v1/services/aigc/multimodal-generation/generation",
                        headers={"Authorization": "Bearer " + self.key},
                        json={
                            "model": self.model,
                            "input": {"messages": [{"role": "user", "content": content}]},
                            "parameters": parameters,
                        },
                    )
                    if response.status_code in {401, 403}:
                        raise ProviderError("参考图生成鉴权失败，请核对北京密钥及千问图像模型权限")
                    if response.status_code == 429:
                        raise ProviderError("参考图生成受限，请核对平台额度和并发限制")
                    if response.status_code != 200:
                        raise ProviderError("参考图生成未完成，不会自动重试，请先核对百炼调用记录")
                    body = response.json()
                    if not isinstance(body, dict) or body.get("code"):
                        raise ProviderError("百炼未返回有效的参考图编辑结果")
                    output = body["output"]
                    if not isinstance(output, dict):
                        raise ProviderError("参考图生成响应格式不符合预期")
                    choices = output["choices"]
                    if (
                        not isinstance(choices, list)
                        or len(choices) != 1
                        or not isinstance(choices[0], dict)
                    ):
                        raise ProviderError("参考图候选数量与请求不一致")
                    choice = choices[0]
                    if choice.get("finish_reason") != "stop" or not isinstance(
                        choice.get("message"), dict
                    ):
                        raise ProviderError("参考图输出未正常完成")
                    result = choice["message"]["content"]
                    if (
                        not isinstance(result, list)
                        or len(result) != 1
                        or not isinstance(result[0], dict)
                        or not isinstance(result[0].get("image"), str)
                    ):
                        raise ProviderError("参考图响应没有返回有效图片地址")
                    raw = await self.download(client, result[0]["image"], request)
                    if on_progress:
                        await on_progress(90, "参考图候选已下载并核对尺寸")
                    return [raw]
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
                "参考图生成或下载中断，不会自动重试；请先核对百炼记录，避免重复付费"
            ) from None
