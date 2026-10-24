"""提供无密钥的普通生图能力描述；排队前按实际Provider验证。"""

from app.config import Settings
from app.providers import get_image_provider
from app.providers.base import GenerateRequest, ProviderError, validate_request
from app.providers.dashscope_generation import SIZES as REAL_SIZES
from app.providers.dashscope_generation import validate
from app.providers.reference_generation import configured as reference_configured
from app.schemas.generation import SIZES


def sizes_for(settings: Settings):
    return REAL_SIZES if settings.image_provider == "dashscope" else SIZES


def check_request(settings: Settings, request: GenerateRequest) -> None:
    if settings.image_provider == "dashscope":
        validate(request)
    else:
        validate_request(request)


def options(settings: Settings) -> dict:
    ready = True
    try:
        get_image_provider(settings)
    except ProviderError:
        ready = False
    reference_ready = True
    try:
        reference_configured(settings)
    except ProviderError:
        reference_ready = False
    return {
        "image_provider": settings.image_provider,
        "image_model": settings.image_model if settings.image_provider == "dashscope" else "mock",
        "image_configured": ready,
        "image_max_count": 4 if settings.image_provider == "dashscope" else 6,
        "image_sizes": sizes_for(settings),
        "reference_configured": reference_ready,
        "reference_model": settings.reference_image_model,
        "reference_max_count": 1,
        "reference_max_images": 3,
        "reference_prompt_limit": 800,
        "reference_min_side": 384,
        "reference_max_side": 3072,
        "reference_max_bytes": 10 * 1024 * 1024,
    }


def planner_instruction(settings: Settings) -> str:
    if settings.image_provider == "mock":
        return (
            "生成图片当前仅为Mock占位图，不具备真实画面语义效果；"
            "edit_image未启用，不要规划AI整图编辑。"
        )
    if not options(settings)["image_configured"]:
        return (
            "普通文生图当前配置不可用，不能声称能够真实生成图片；"
            "edit_image未启用，不要规划AI整图编辑。"
        )
    return (
        "普通文生图使用百炼wan2.6-t2i，按张计费；count每次1到4，用户未指定数量时为1。"
        "negative_prompt最多500字。Agent的generate_image仅接收文字描述，不自动参考画布；不要声称保留当前画布主体。"
        "网页的参考图模式由用户手动选择素材；不要虚构或传入reference_asset_ids。"
        + (
            "edit_image已启用：服务端使用确认执行时的已保存画布作参考，生成1张付费候选，不自动采用。"
            if options(settings)["reference_configured"]
            else "edit_image未启用，不要规划当前画布AI整图编辑。"
        )
        + "只生成候选，待用户确认执行；生成后不自动采用或修改画布。"
    )
