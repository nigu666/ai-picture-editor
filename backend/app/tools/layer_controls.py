from app.agent.layer_binding import AgentLayerEdit
from app.edits.layer_controls import LayerEdit, apply_document
from app.services import sessions
from app.services.layer_documents import keys_for_document
from app.tools.base import ToolSpec
from app.tools.builtin import _canvas_result


async def edit_layer(context, params):
    document = apply_document(context.record.document, params)
    await keys_for_document(context.db, context.user_id, document)
    await sessions.apply_edit(context.db, context.record, document, "edit_layer")
    return await _canvas_result(context)


SPECS = (
    ToolSpec(
        "edit_layer",
        "调整单个图层",
        "调整当前图层的显示、透明度、中心位置、等比缩放、旋转、位置锁定和绝对层序。"
        "layer_id使用上下文id或唯一名称，省略为最上方可见层。"
        "只传要改的字段，不传null。数值是绝对值，opacity为0到1，scale为0.05到4，"
        "position为从底部0开始的层序。锁定层需先单独解锁才能移动、缩放或旋转。"
        "文字层还可修改text、font_size(6到512整数)、fill(#RRGGBB)、align(left/center/right)、"
        "width和height(文字框像素1到4096)，文字框外内容裁切。图片层不能接收文字字段。",
        LayerEdit,
        edit_layer,
        changes_canvas=True,
        agent_params=AgentLayerEdit,
    ),
)
