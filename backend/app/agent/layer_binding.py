"""将模型提出的图层名称绑定为当前文档中的固定编号。"""

import copy

from fastapi import HTTPException
from pydantic import Field, ValidationError

from app.edits.layer_controls import LayerEdit, apply_document
from app.edits.layout import position


class AgentLayerEdit(LayerEdit):
    layer_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=80,
        description="当前layers中的图层id或唯一名称；省略时为最上方可见层，不代表面板选中层",
    )


class LayerBindingError(Exception):
    pass


def metadata(document):
    if document is None:
        return []
    return [
        {
            "id": layer["id"],
            "name": layer.get("name", "图片图层"),
            "kind": layer["kind"],
            **(
                {key: layer[key] for key in ("text", "font_size", "fill", "align")}
                if layer["kind"] == "text"
                else {}
            ),
            "position": index,
            "visible": layer["visible"],
            "opacity": layer["opacity"],
            "locked": layer.get("locked", False),
            "width": layer["width"],
            "height": layer["height"],
            "placement": position({"layers": [layer]}),
            "rotation": layer["transform"]["rotation"],
        }
        for index, layer in enumerate(document["layers"])
    ]


def resolve(document, wanted):
    if document is None:
        raise LayerBindingError("当前画布缺少图层文档，请重新读取会话")
    layers = document["layers"]
    if wanted is not None:
        wanted = wanted.strip()
        exact = next((layer for layer in layers if layer["id"] == wanted), None)
        if exact is not None:
            return exact
        matches = [layer for layer in layers if layer.get("name") == wanted]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise LayerBindingError("图层名称重复，请使用图层编号明确目标；本轮未执行")
        raise LayerBindingError("指定图层不在当前画布中，请使用现有图层的名称或编号")
    target = next((layer for layer in reversed(layers) if layer["visible"]), None)
    if target is None:
        raise LayerBindingError("没有可见图层，请明确要操作的图层名称或编号")
    return target


def bind_ordered(steps, document):
    """在副本中依次校验：解锁、显隐或层序变化影响后续默认目标。"""
    simulated = copy.deepcopy(document)
    for step in steps:
        if step.tool != "edit_layer":
            continue
        proposed = AgentLayerEdit.model_validate(step.params)
        target = resolve(simulated, proposed.layer_id)
        values = proposed.model_dump(mode="json", exclude_unset=True)
        values["layer_id"] = target["id"]
        try:
            checked = LayerEdit.model_validate(values)
            simulated = apply_document(simulated, checked)
        except HTTPException as exc:
            raise LayerBindingError(str(exc.detail)) from None
        except ValidationError:
            raise LayerBindingError("图层调整超出允许范围，请简化或修改要求") from None
        step.params = checked.model_dump(mode="json", exclude_unset=True)
        step.label = "调整图层：" + target.get("name", "图片图层")
