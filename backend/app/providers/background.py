"""显式选择背景供应商；不因空密钥自动回退到其他平台。"""

from app.config import Settings
from app.providers.base import ProviderError
from app.providers.dashscope_background import DashscopeBackground
from app.providers.zhipu_background import ZhipuBackground


def provider_name(settings: Settings) -> str:
    return {
        "dashscope": DashscopeBackground.name,
        "zhipu": ZhipuBackground.name,
    }.get(settings.background_provider, "disabled")


def configured(settings: Settings) -> None:
    if settings.background_provider == "dashscope":
        from app.providers.dashscope_background import configured as validate
    elif settings.background_provider == "zhipu":
        from app.providers.zhipu_background import configured as validate
    else:
        raise ProviderError("换背景尚未启用，请完成百炼配置后重启后端")
    validate(settings)


def get_background_provider(settings: Settings):
    configured(settings)
    return (
        DashscopeBackground(settings)
        if settings.background_provider == "dashscope"
        else ZhipuBackground(settings)
    )
