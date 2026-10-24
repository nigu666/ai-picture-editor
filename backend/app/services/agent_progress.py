"""从已保存计划推导展示原因；不更改状态、不选工具、不调度任务。"""


def describe(turn):
    steps = turn.steps
    by_id = {step["id"]: (index, step) for index, step in enumerate(steps, 1)}
    first = next((step["id"] for step in steps if step["status"] != "succeeded"), None)
    completed = {step["id"] for step in steps if step["status"] == "succeeded"}
    views = []
    for step in steps:
        dependencies = [
            dict(
                id=identity,
                number=by_id[identity][0] if identity in by_id else None,
                label=by_id[identity][1]["label"] if identity in by_id else "不存在的步骤",
                status=by_id[identity][1]["status"] if identity in by_id else "missing",
            )
            for identity in step["depends_on"]
        ]
        waiting = [item for item in dependencies if item["id"] not in completed]
        if step["status"] == "succeeded":
            state, label, reason = "succeeded", "已完成", "此步骤已保存，恢复计划不会重复执行。"
        elif step["status"] == "failed":
            state, label, reason = (
                "failed",
                "未完成",
                "请先核对失败原因；存在安全检查点时可明确恢复。",
            )
        elif step["status"] == "cancelled":
            state, label, reason = (
                "cancelled",
                "未执行 · 已停止",
                "此步骤未执行，原计划不会再次启动它。",
            )
        elif step["status"] == "running":
            if turn.status in {"cancelled", "stale"}:
                state, label, reason = (
                    "running",
                    "原任务处理中",
                    "只核对已提交任务，后续步骤不再执行。",
                )
            elif turn.status in {"stale", "failed"}:
                state, label, reason = (
                    "blocked",
                    "原任务待核对",
                    "计划已暂停；已提交任务可能继续，请核对原图片任务。",
                )
            else:
                state, label, reason = "running", "处理中", "等待此步骤实际完成后，再读取计划进度。"
        elif turn.status == "pending":
            state, label, reason = (
                "awaiting_confirmation",
                "等待你确认",
                "计划尚未执行，确认后才按顺序推进。",
            )
        elif turn.status in {"failed", "stale", "cancelled", "succeeded", "clarification"}:
            state, label = "blocked", "后续暂停" if turn.status == "failed" else "未执行 · 已停止"
            reason = (
                "先处理失败步骤，明确恢复后才继续。"
                if turn.status == "failed"
                else "当前计划不再推进；需要修改要求时重新规划。"
            )
        elif waiting:
            state, label, reason = (
                "waiting_dependency",
                "等待依赖",
                "需要先完成："
                + "、".join(
                    f"第{item['number']}步 {item['label']}" if item["number"] else item["label"]
                    for item in waiting
                )
                + "。",
            )
        elif turn.status == "running" and step["id"] == first:
            state, label, reason = "ready", "下一步", "依赖已完成；下一次推进只执行此步骤。"
        elif turn.status == "running":
            state, label, reason = (
                "waiting_order",
                "等待前序步骤",
                "依赖已满足，但当前计划按顺序执行，需等待前面的步骤结束。",
            )
        else:
            state, label, reason = "blocked", "尚未执行", "等待计划状态更新。"
        views.append(dict(state=state, label=label, reason=reason, dependencies=dependencies))
    summary = dict(
        completed=len(completed),
        total=len(steps),
        current_step_id=first if turn.status == "running" else None,
        execution_order="serial",
    )
    return views, summary
