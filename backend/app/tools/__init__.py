"""统一工具注册表；导入仅定义能力，不连接存储、数据库或模型。"""

from app.tools.background import SPECS as BACKGROUND_SPECS
from app.tools.base import ToolRegistry, ToolSpec, UnknownTool
from app.tools.builtin import SPECS as BASE_SPECS
from app.tools.canvas import SPECS as CANVAS_SPECS
from app.tools.canvas_edit import SPECS as CANVAS_EDIT_SPECS
from app.tools.color import SPECS as COLOR_SPECS
from app.tools.layer_controls import SPECS as LAYER_SPECS
from app.tools.matting import SPECS as MATTING_SPECS
from app.tools.outpainting import SPECS as OUTPAINTING_SPECS
from app.tools.promote import SPECS as PROMOTE_SPECS
from app.tools.region import SPECS as REGION_SPECS
from app.tools.split import SPECS as SPLIT_SPECS
from app.tools.upscaling import SPECS as UPSCALING_SPECS

SPECS = (
    *BASE_SPECS,
    *CANVAS_SPECS,
    *CANVAS_EDIT_SPECS,
    *COLOR_SPECS,
    *LAYER_SPECS,
    *MATTING_SPECS,
    *BACKGROUND_SPECS,
    *OUTPAINTING_SPECS,
    *UPSCALING_SPECS,
    *REGION_SPECS,
    *SPLIT_SPECS,
    *PROMOTE_SPECS,
)
REGISTRY = ToolRegistry(SPECS)

__all__ = ["REGISTRY", "SPECS", "ToolRegistry", "ToolSpec", "UnknownTool"]
