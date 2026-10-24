from pydantic import BaseModel

from app.edits.color import ColorParams, apply_document
from app.services import sessions
from app.tools.base import ToolContext, ToolSpec
from app.tools.builtin import _canvas_result


async def adjust(context: ToolContext, params: BaseModel) -> dict:
    assert isinstance(params, ColorParams)
    document = apply_document(context.record.document, params)
    await sessions.apply_edit(context.db, context.record, document, "adjust_colors")
    return await _canvas_result(context)


SPECS = (
    ToolSpec(
        "adjust_colors",
        "调色与细节",
        "设置当前单底图的亮度、对比度、饱和度、锐化绝对系数（0 到 2，1 为原始），"
        "以及高光、阴影、冷暖与绿/洋红绝对偏移（-1 到 1，0 为不变）。"
        "自然饱和度和清晰度为-1到1的绝对偏移，0不变；暗角为0到1的绝对强度，0不变，"
        "按当前画布范围渐暗边缘。自然饱和度优先影响较淡的颜色；清晰度改变中间调局部对比。"
        "从原始素材计算，不叠加上一次结果；要保留某项已有调色值须传入上下文中的值。"
        "原图和透明度保留，可撤销；恢复时四个系数设为 1、其余七项设为 0。"
        "不具备扩图、真实超分或恢复已丢失细节的能力。",
        ColorParams,
        adjust,
        changes_canvas=True,
    ),
)
