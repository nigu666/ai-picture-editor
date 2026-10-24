from app.config import Settings
from app.providers.base import GenerateRequest, ImageProvider, ProviderError
from app.providers.mock import MockImageProvider


def get_image_provider(settings: Settings) -> ImageProvider:
    if settings.image_provider == "mock":
        return MockImageProvider()
    if settings.image_provider == "dashscope":
        from app.providers.dashscope_generation import DashscopeImageProvider

        return DashscopeImageProvider(settings)
    raise ProviderError("未知的 IMAGE_PROVIDER 配置，不自动回退到 Mock")


__all__ = ["GenerateRequest", "ImageProvider", "ProviderError", "get_image_provider"]
