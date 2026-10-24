"""当前学习阶段的图片生成契约；类型声明不代替运行时校验。"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Protocol

ProgressCallback = Callable[[int, str], Awaitable[None]]


class ProviderError(Exception):
    pass


@dataclass(frozen=True)
class GenerateRequest:
    prompt: str
    width: int
    height: int
    count: int = 1
    negative_prompt: str | None = None
    seed: int | None = None
    references: list[bytes] = field(default_factory=list)


class ImageProvider(Protocol):
    name: str

    async def generate(
        self, request: GenerateRequest, on_progress: ProgressCallback | None = None
    ) -> list[bytes]:
        """返回请求数量的图片字节；失败抛出 ProviderError。"""
        ...


def validate_request(request: GenerateRequest) -> None:
    if not isinstance(request.prompt, str) or not request.prompt.strip():
        raise ProviderError("生成描述不能为空")
    if len(request.prompt) > 1500:
        raise ProviderError("生成描述不得超过 1500 字")
    for value in (request.width, request.height):
        if type(value) is not int or not 32 <= value <= 2048:
            raise ProviderError("图片宽高需为 32–2048 的整数")
    if type(request.count) is not int or not 1 <= request.count <= 6:
        raise ProviderError("图片数量需为 1–6 的整数")
    if request.seed is not None and (
        type(request.seed) is not int or not 0 <= request.seed <= 2147483647
    ):
        raise ProviderError("seed 需为 0–2147483647 的整数")
    if request.negative_prompt is not None and (
        not isinstance(request.negative_prompt, str) or len(request.negative_prompt) > 1500
    ):
        raise ProviderError("反向描述需为不超过 1500 字的文本")
    if not isinstance(request.references, list) or len(request.references) > 3:
        raise ProviderError("参考图列表最多 3 张")
    if any(not isinstance(raw, bytes) or not raw for raw in request.references):
        raise ProviderError("参考图需为非空图片字节")
