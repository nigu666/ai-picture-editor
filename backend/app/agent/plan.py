"""只读取工具元数据和参数模型；不调用工具处理函数。"""

import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.agent.layer_binding import LayerBindingError, bind_ordered
from app.agent.layer_binding import metadata as layer_metadata
from app.edits.canvas_edit import bounds as canvas_edit_bounds
from app.edits.color import ColorParams
from app.edits.layout import position
from app.layers import tool_supported
from app.providers.base import ProviderError
from app.services.region_binding import TOOLS, summary
from app.tools import REGISTRY, UnknownTool

MAX_STEPS = 8


class PlanError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class PlanningContext:
    revision: int
    width: int
    height: int
    current_asset_id: str
    candidate_ids: tuple[str, ...]
    can_undo: bool
    can_redo: bool
    document: dict | None = field(default=None, repr=False)
    storage_key: str = field(default="", repr=False)
    image_data_url: str = field(default="", repr=False)
    selection: dict | None = field(default=None, repr=False)
    storage_keys: dict[str, str] = field(default_factory=dict, repr=False)

    def metadata(self) -> dict:
        return {
            "revision": self.revision,
            "selection": summary(self.selection) if self.selection else None,
            "canvas": {
                "width": self.width,
                "height": self.height,
                "current_asset_id": self.current_asset_id,
            },
            "candidates": [
                {"number": index, "asset_id": asset_id}
                for index, asset_id in enumerate(self.candidate_ids, 1)
            ],
            "can_undo": self.can_undo,
            "can_redo": self.can_redo,
            "image_pixels_sent": bool(self.image_data_url),
            "image_scope": "current_canvas_only" if self.image_data_url else "none",
            "placement": position(self.document)
            if self.document and len(self.document["layers"]) == 1
            else None,
            "layer_count": len(self.document["layers"]) if self.document else 1,
            "layer_editing_available": self.document is not None,
            "layers": layer_metadata(self.document),
            "layer_order": "bottom_to_top; position starts at 0",
            "panel_selected_layer_available": False,
            "generated_result_policy": (
                "candidate_only; flatten saved visible layers; never replace layer document "
                "automatically; adopting a candidate resets to one image and is undoable"
            ),
            "adjustments": ColorParams.model_validate(
                (self.document or {}).get("adjustments", {})
            ).model_dump(),
        }


class RawStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str | None = Field(default=None, pattern=r"^[a-zA-Z][a-zA-Z0-9_-]{0,47}$")
    tool: str = Field(min_length=1, max_length=48)
    params: dict[str, Any] = Field(default_factory=dict, max_length=16)
    depends_on: list[str] | None = Field(default=None, max_length=MAX_STEPS)


class Step(BaseModel):
    id: str
    tool: str
    label: str
    params: dict[str, Any]
    depends_on: list[str]
    selection: dict | None = None


class PlanResult(BaseModel):
    status: Literal["ready", "needs_confirmation", "clarification", "invalid", "unavailable"]
    message: str
    analysis: str = Field(default="", max_length=3000)
    steps: list[Step] = Field(default_factory=list)
    executed: Literal[False] = False
    saved: Literal[False] = False
    error_code: str | None = None
    trace: list[str] = Field(default_factory=list)
    planner_source: str = ""
    session_id: str | None = None
    context_revision: int | None = None
    selection_binding: dict | None = Field(default=None, exclude=True, repr=False)


def validate(raw: list[dict], context: PlanningContext) -> list[Step]:
    if not isinstance(raw, list) or len(raw) > MAX_STEPS:
        raise PlanError("step_limit", "最多规划 8 步，请拆分要求")
    steps = []
    for index, item in enumerate(raw, 1):
        try:
            entry = RawStep.model_validate(item)
            spec = REGISTRY.get(entry.tool)
            if entry.tool == "edit_image":
                try:
                    canvas_edit_bounds({"width": context.width, "height": context.height})
                except ProviderError as exc:
                    raise PlanError("canvas_edit_size", str(exc)) from None
            if context.document and not tool_supported(context.document, entry.tool):
                raise PlanError(
                    "layer_tool_not_supported", "当前工具暂不支持多图层，请先撤销添加图层后再使用"
                )
            if not spec.agent_visible:
                raise UnknownTool("此工具尚未接入Agent规划，请通过页面选择区域后使用")
            if entry.tool in TOOLS:
                if not context.selection:
                    raise PlanError(
                        "selection_required", "请先建立选区，再发送局部编辑指令；本轮未执行"
                    )
                proposed = spec.agent_params.model_validate(entry.params).model_dump(mode="json")
                params = spec.validate(
                    proposed
                    | {
                        "selection_version": context.selection["version"],
                        "request_id": uuid.uuid4(),
                    }
                ).model_dump(mode="json")
            elif entry.tool == "edit_layer":
                params = spec.agent_params.model_validate(entry.params).model_dump(
                    mode="json", exclude_unset=True
                )
            else:
                params = spec.validate(entry.params).model_dump(mode="json")
        except UnknownTool:
            raise PlanError("unknown_tool", "模型提出了未注册或尚未实现的工具") from None
        except ValidationError:
            raise PlanError("invalid_parameters", "模型提出的工具参数不符合定义") from None
        if entry.tool == "adopt_candidate" and params["asset_id"] not in context.candidate_ids:
            raise PlanError("invalid_target", "要采用的图片不在当前会话候选中，不能猜测素材编号")
        depends = entry.depends_on
        if depends is None:
            depends = [steps[-1].id] if steps else []
        if len(set(depends)) != len(depends):
            raise PlanError("duplicate_dependency", "步骤包含重复依赖")
        steps.append(
            Step(
                id=entry.id or f"s{index}",
                tool=spec.name,
                label=spec.label,
                params=params,
                depends_on=depends,
                selection=summary(context.selection) if entry.tool in TOOLS else None,
            )
        )
    by_id = {step.id: step for step in steps}
    if any(s.tool in TOOLS for s in steps) and any(
        REGISTRY.get(s.tool).changes_canvas for s in steps
    ):
        raise PlanError(
            "selection_canvas_conflict",
            "局部编辑不能与改变画布的步骤混在同一计划，请先完成旋转、裁剪或采用，再重新选区规划",
        )
    if len(by_id) != len(steps):
        raise PlanError("duplicate_id", "步骤编号重复")
    for step in steps:
        if any(dep not in by_id for dep in step.depends_on):
            raise PlanError("missing_dependency", "步骤依赖了不存在的步骤")
    # 稳定拓扑排序，同时拒绝自依赖与环。
    ordered = []
    done = set()
    while len(ordered) < len(steps):
        ready = [step for step in steps if step.id not in done and set(step.depends_on) <= done]
        if not ready:
            raise PlanError("cycle", "步骤存在循环依赖")
        for step in ready:
            ordered.append(step)
            done.add(step.id)
    for step in ordered:
        if not step.depends_on:
            if step.tool == "undo_canvas" and not context.can_undo:
                raise PlanError("cannot_undo", "当前会话没有可撤销记录")
            if step.tool == "redo_canvas" and not context.can_redo:
                raise PlanError("cannot_redo", "当前会话没有可重做记录")
    if any(step.tool == "edit_layer" for step in ordered):
        if any(
            REGISTRY.get(step.tool).changes_canvas and step.tool != "edit_layer" for step in ordered
        ):
            raise PlanError(
                "layer_canvas_conflict",
                "图层调整不能与采用候选、撤销或其他整图修改混在同一计划，请分开提出",
            )
        try:
            bind_ordered(ordered, context.document)
        except LayerBindingError as exc:
            raise PlanError("invalid_layer_target", str(exc)) from None
    return ordered
